"""
Pustakam (पुस्तकम्) — sign in with the operating-system account.

* Linux (Debian/Ubuntu/MX, Fedora/RHEL/Rocky/Alma, openSUSE): PAM via python-pam.
* Windows: LogonUserW from advapi32 (no extra packages needed).

By default only the OS account that runs the Pustakam server can sign in, because
the notes belong to that account. Extra accounts can be listed in config.json
under "allowed_users".
"""
import getpass
import json
import os
import secrets
import threading
import time

from PustakamConfig import DATA_DIR, IS_WINDOWS, load_config

SESSION_FILE = os.path.join(DATA_DIR, ".sessions.json")
SESSION_TTL = 12 * 3600
MAX_FAILURES = 5
FAILURE_WINDOW = 300

_lock = threading.Lock()
_sessions = None
_failures = {}


def service_user():
    """The OS account running this server."""
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def platform_label():
    return "Windows" if IS_WINDOWS else "Linux"


# ---------------------------------------------------------------- Windows
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _LOGON32_LOGON_NETWORK = 3
    _LOGON32_PROVIDER_DEFAULT = 0
    _TOKEN_QUERY = 0x0008
    _TOKEN_USER_CLASS = 1

    _advapi32.LogonUserW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.LogonUserW.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def _token_sid(token):
        size = wintypes.DWORD(0)
        _advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not _advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, buf, size, ctypes.byref(size)):
            return None
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_str = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(psid, ctypes.byref(sid_str)):
            return None
        try:
            return sid_str.value
        finally:
            _kernel32.LocalFree(ctypes.cast(sid_str, ctypes.c_void_p))

    def _current_sid():
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return _token_sid(token)
        finally:
            _kernel32.CloseHandle(token)

    def _windows_logon_sid(username, password):
        """Returns the SID of the account if the password is right, else None.
        Accepts 'user', 'MACHINE\\user', 'DOMAIN\\user', 'user@domain' and
        'MicrosoftAccount\\you@outlook.com'. (A Windows Hello PIN will not work.)"""
        if "\\" in username:
            domain, user = username.split("\\", 1)
        elif "@" in username:
            domain, user = None, username
        else:
            domain, user = ".", username
        token = wintypes.HANDLE()
        ok = _advapi32.LogonUserW(user, domain, password, _LOGON32_LOGON_NETWORK,
                                  _LOGON32_PROVIDER_DEFAULT, ctypes.byref(token))
        if not ok:
            return None
        try:
            return _token_sid(token)
        finally:
            _kernel32.CloseHandle(token)


# ---------------------------------------------------------------- Linux
def _linux_is_service_account(username):
    try:
        import pwd
        return pwd.getpwnam(username).pw_uid == os.getuid()
    except (KeyError, ImportError):
        return False


def _linux_pam(username, password, service):
    try:
        import pam
    except ImportError:
        raise RuntimeError("python-pam is not installed (pip install python-pam)")
    p = pam.pam()
    return bool(p.authenticate(username, password, service=service))


# ---------------------------------------------------------------- public API
def _in_allowed_list(username, cfg):
    allowed = [u.lower() for u in cfg.get("allowed_users") or []]
    return username.lower() in allowed


def _rate_limited(client):
    now = time.time()
    hits = [t for t in _failures.get(client, []) if now - t < FAILURE_WINDOW]
    _failures[client] = hits
    return len(hits) >= MAX_FAILURES


def authenticate(username, password, client="local"):
    """Returns (ok: bool, message: str)."""
    username = (username or "").strip()
    if not username or not password:
        return False, "Enter your username and password."
    if _rate_limited(client):
        return False, "Too many failed attempts. Wait a few minutes and try again."

    cfg = load_config()
    ok = False
    try:
        if IS_WINDOWS:
            sid = _windows_logon_sid(username, password)
            ok = bool(sid) and (sid == _current_sid() or _in_allowed_list(username, cfg))
        else:
            if _linux_is_service_account(username) or _in_allowed_list(username, cfg):
                ok = _linux_pam(username, password, cfg.get("pam_service") or "login")
    except RuntimeError as e:
        return False, str(e)
    except Exception:
        ok = False

    if ok:
        _failures.pop(client, None)
        return True, ""
    _failures.setdefault(client, []).append(time.time())
    return False, f"Invalid credentials. Sign in with the {platform_label()} account that runs Pustakam."


def _load_sessions():
    global _sessions
    if _sessions is None:
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                _sessions = json.load(f)
        except (OSError, ValueError):
            _sessions = {}
    return _sessions


def _persist():
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_sessions, f)
    if not IS_WINDOWS:
        os.chmod(tmp, 0o600)
    os.replace(tmp, SESSION_FILE)


def create_session(username):
    with _lock:
        sessions = _load_sessions()
        now = time.time()
        for t in [t for t, s in sessions.items() if now - s["created"] > SESSION_TTL]:
            sessions.pop(t, None)
        token = secrets.token_hex(32)
        sessions[token] = {"user": username, "created": now}
        _persist()
        return token


def validate_session(token):
    if not token:
        return None
    with _lock:
        s = _load_sessions().get(token)
        if not s:
            return None
        if time.time() - s["created"] > SESSION_TTL:
            _sessions.pop(token, None)
            _persist()
            return None
        return s["user"]


def destroy_session(token):
    with _lock:
        if _load_sessions().pop(token, None) is not None:
            _persist()
