"""
Pustakam (पुस्तकम्) — Microsoft OneDrive provider, powered by rclone.

No app registration or Client ID: you sign in with your Microsoft account
(outlook.com, hotmail.com, live.com, msn.com, or work/school) through rclone's
own registered app. Microsoft's consent screen therefore says "rclone".

rclone is looked up in <install>/bin, then on PATH. The rclone config holding the
OneDrive token lives in ~/.pustakam/rclone.conf (chmod 600), separate from any
rclone setup you may already have.

Sign-in flow:
  1. Pustakam runs `rclone authorize onedrive`, which listens on 127.0.0.1:53682.
  2. The Microsoft sign-in page opens in your browser. Afterwards Microsoft
     redirects to http://localhost:53682/?code=..., which rclone receives.
  3. Browsing from another device on the LAN? That redirect cannot reach this
     server, so you paste the address into Settings and Pustakam forwards it
     to rclone locally.
"""
import base64
import configparser
import json
import os
import posixpath
import re
import shutil
import subprocess
import threading
import time
import urllib.parse

import requests

import PustakamLogs
from PustakamCloudBase import CloudError, NotConnected
from PustakamConfig import DATA_DIR, IS_WINDOWS

RCLONE_CONF = os.path.join(DATA_DIR, "rclone.conf")
REMOTE = "pustakam-onedrive"
AUTH_PORT = 53682
APP_DIR = os.path.dirname(os.path.abspath(__file__))
EXE = "rclone.exe" if IS_WINDOWS else "rclone"
_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


# ------------------------------------------------------------------ rclone helpers
def rclone_path():
    for c in (os.environ.get("PUSTAKAM_RCLONE"),
              os.path.join(os.path.dirname(APP_DIR), "bin", EXE),
              os.path.join(APP_DIR, "bin", EXE),
              shutil.which("rclone")):
        if c and os.path.isfile(c):
            return c
    return None


_version_cache = {}


def rclone_info():
    path = rclone_path()
    if not path:
        return {"found": False, "version": None, "path": None}
    if path not in _version_cache:
        try:
            out = subprocess.run([path, "version"], capture_output=True, text=True, timeout=15,
                                 creationflags=_NOWINDOW).stdout
            _version_cache[path] = (out.splitlines() or ["rclone ?"])[0].replace("rclone ", "").strip()
        except Exception:
            _version_cache[path] = "?"
    return {"found": True, "version": _version_cache[path], "path": path}


def _exe():
    exe = rclone_path()
    if not exe:
        raise CloudError("rclone is not installed. Re-run the Pustakam installer, or install rclone "
                         "(https://rclone.org/install/), then try again.")
    return exe


def _run(args, data=None, timeout=180):
    cmd = [_exe(), "--config", RCLONE_CONF, "--low-level-retries", "5", *args]
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, creationflags=_NOWINDOW)
    except subprocess.TimeoutExpired:
        raise CloudError(f"OneDrive: rclone timed out ({args[0]})")
    if p.returncode != 0:
        err = [l for l in p.stderr.decode("utf-8", "replace").splitlines() if l.strip()]
        msg = err[-1] if err else f"exit code {p.returncode}"
        msg = re.sub(r"^\S+ \S+ (ERROR|NOTICE|CRITICAL)\s*:\s*", "", msg)
        if "token" in msg.lower() and ("expired" in msg.lower() or "invalid_grant" in msg.lower()):
            raise NotConnected("OneDrive sign-in has expired. Click 'Sign in with Microsoft' again.")
        PustakamLogs.sync_line(f"rclone {args[0]} failed: {msg}", "warning")
        raise CloudError(f"OneDrive: {msg}")
    return p.stdout


def _read_conf():
    cp = configparser.ConfigParser(interpolation=None)
    if os.path.exists(RCLONE_CONF):
        cp.read(RCLONE_CONF, encoding="utf-8")
    return cp


def _write_conf(cp):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = RCLONE_CONF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        cp.write(f)
    if not IS_WINDOWS:
        os.chmod(tmp, 0o600)
    os.replace(tmp, RCLONE_CONF)


def is_connected():
    cp = _read_conf()
    return cp.has_section(REMOTE) and bool(cp.get(REMOTE, "token", fallback=""))


def remove_remote():
    cp = _read_conf()
    if cp.remove_section(REMOTE):
        _write_conf(cp)


def _decode_token(blob):
    """rclone prints either the token JSON or a base64 'config token' wrapping it."""
    blob = blob.strip()
    if not blob.startswith("{"):
        blob = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)).decode("utf-8")
    data = json.loads(blob)
    if isinstance(data, dict) and "token" in data and "access_token" not in data:
        tok = data["token"]
        data = json.loads(tok) if isinstance(tok, str) else tok
    if not data.get("access_token"):
        raise CloudError("rclone did not return a OneDrive token")
    return data


def _save_remote(token):
    """Look up the user's drive with the fresh token and write the rclone remote."""
    h = {"Authorization": f"Bearer {token['access_token']}"}
    r = requests.get("https://graph.microsoft.com/v1.0/me/drive", headers=h, timeout=30)
    if r.status_code >= 400:
        raise CloudError(f"OneDrive: could not read your drive ({r.status_code}): {r.text[:200]}")
    drive = r.json()
    owner = ((drive.get("owner") or {}).get("user") or {})
    account = {"name": owner.get("displayName", ""), "email": owner.get("email", "")}
    if not account["email"]:
        try:
            me = requests.get("https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName",
                              headers=h, timeout=15)
            if me.ok:
                account["email"] = me.json().get("mail") or me.json().get("userPrincipalName") or ""
        except requests.RequestException:
            pass
    cp = _read_conf()
    if cp.has_section(REMOTE):
        cp.remove_section(REMOTE)
    cp.add_section(REMOTE)
    cp.set(REMOTE, "type", "onedrive")
    cp.set(REMOTE, "token", json.dumps(token))
    cp.set(REMOTE, "drive_id", drive["id"])
    cp.set(REMOTE, "drive_type", drive.get("driveType", "personal"))
    _write_conf(cp)
    return account


# ------------------------------------------------------------------ sign-in session
class _SignIn:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.state = "idle"      # idle | waiting | finishing | done | error
        self.error = None
        self.started = 0

    def status(self):
        return {"state": self.state, "error": self.error, "started": self.started}

    def stop(self):
        p = self.proc
        if p and p.poll() is None:
            p.kill()
        self.proc = None


signin = _SignIn()


def start_signin(on_done):
    """Starts `rclone authorize onedrive`; returns the Microsoft sign-in URL.
    on_done(account) runs after the remote is saved (used to run the connection test)."""
    exe = _exe()
    with signin.lock:
        signin.stop()
        output, found = [], {}
        proc = subprocess.Popen([exe, "--config", RCLONE_CONF, "authorize", "onedrive", "--auth-no-open-browser"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", creationflags=_NOWINDOW)
        signin.proc, signin.state, signin.error, signin.started = proc, "waiting", None, time.time()

    url_seen = threading.Event()

    def reader():
        for line in proc.stdout:
            output.append(line)
            m = re.search(rf"http://(?:127\.0\.0\.1|localhost):{AUTH_PORT}/auth\?state=\S+", line)
            if m and "url" not in found:
                found["url"] = m.group(0)
                url_seen.set()
        url_seen.set()

    def waiter():
        try:
            proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill()
            signin.state, signin.error = "error", "Sign-in timed out after 15 minutes. Try again."
            return
        if signin.proc is not proc:
            return  # superseded by a newer attempt
        text = "".join(output)
        m = re.search(r"--->\s*(.+?)\s*<---End paste", text, re.S)
        if not m:
            tail = [l.strip() for l in output if l.strip()][-3:]
            signin.state, signin.error = "error", "Sign-in did not complete. " + " ".join(tail)[:300]
            PustakamLogs.connection(f"OneDrive sign-in did not complete: {signin.error}", "warning")
            return
        try:
            signin.state = "finishing"
            account = _save_remote(_decode_token(m.group(1)))
            on_done(account)
            signin.state = "done"
        except Exception as e:  # noqa
            signin.state, signin.error = "error", str(e)
            PustakamLogs.connection(f"OneDrive sign-in FAILED: {e}", "warning")

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=waiter, daemon=True).start()
    if not url_seen.wait(25) or "url" not in found:
        signin.stop()
        signin.state = "error"
        signin.error = ("rclone did not start the sign-in (is another program using port "
                        f"{AUTH_PORT}?). " + " ".join(l.strip() for l in output[-3:]))[:300]
        raise CloudError(signin.error)
    local = found["url"].replace("localhost", "127.0.0.1")
    try:  # rclone's /auth page redirects to Microsoft; hand that URL to the browser directly
        r = requests.get(local, allow_redirects=False, timeout=10)
        return r.headers.get("Location") or found["url"]
    except requests.RequestException:
        return found["url"]


def complete_signin(pasted_url):
    """Forward the 'localhost:53682/?code=…' address pasted from another device to rclone."""
    if signin.state != "waiting" or not signin.proc or signin.proc.poll() is not None:
        raise CloudError("No Microsoft sign-in is waiting. Click 'Sign in with Microsoft' again.")
    q = urllib.parse.urlparse(pasted_url.strip()).query
    if "code=" not in q:
        raise CloudError("That address has no 'code='. Copy the full address of the page Microsoft sent you to.")
    try:
        requests.get(f"http://127.0.0.1:{AUTH_PORT}/?{q}", timeout=30)
    except requests.RequestException as e:
        raise CloudError(f"Could not hand the code to rclone: {e}")
    for _ in range(60):
        if signin.state in ("done", "error"):
            break
        time.sleep(0.5)
    if signin.state == "error":
        raise CloudError(signin.error)
    if signin.state != "done":
        raise CloudError("Sign-in is still finishing; check the status in a moment.")


# ------------------------------------------------------------------ file API
class OneDriveProvider:
    key = "onedrive"
    label = "OneDrive"

    def __init__(self, pcfg, redirect_uri=None, on_tokens=None):
        self.cfg = pcfg
        self.paths = {}     # remote id -> path inside the drive
        self.ids = {"": "root"}
        self.dirs = set()

    def _require(self):
        if not is_connected():
            raise NotConnected("OneDrive is not connected. Click 'Sign in with Microsoft' in Settings.")

    def _r(self, path):
        return f"{REMOTE}:{path}"

    def _norm(self, e, parent_path):
        path = posixpath.join(parent_path, e["Name"]) if parent_path else e["Name"]
        rid = e.get("ID") or path
        parent_id = self.ids.get(parent_path, parent_path)
        self.paths[rid], self.ids[path] = path, rid
        if e.get("IsDir"):
            self.dirs.add(rid)
        hashes = e.get("Hashes") or {}
        h = next((hashes[k] for k in ("quickxor", "sha1", "sha256", "md5") if hashes.get(k)), None) \
            or f"{e.get('ModTime', '')}:{e.get('Size', 0)}"
        return {"id": rid, "name": e["Name"], "is_dir": bool(e.get("IsDir")), "parent": parent_id,
                "size": max(0, int(e.get("Size") or 0)), "rev": f"{h}|{e['Name']}|{parent_id}"}

    def _stat(self, path):
        """Look an item up through its parent's listing.

        `rclone lsjson --stat` reports no ID for folders, while folder listings do.
        Mixing the two gave the same OneDrive folder two different IDs, which made
        each sync think the folder was deleted and re-created (duplicate notebooks).
        Using the listing everywhere keeps IDs identical between runs."""
        parent, name = posixpath.dirname(path), posixpath.basename(path)
        for attempt in range(4):
            entries = json.loads(_run(["lsjson", "--hash", "--no-mimetype", self._r(parent)]) or "[]")
            hit = next((e for e in entries if e["Name"] == name), None) or \
                next((e for e in entries if e["Name"].lower() == name.lower()), None)
            if hit:
                return self._norm(hit, parent)
            time.sleep(1 + attempt)   # just-written item not listed yet
        raise CloudError(f"OneDrive: '{path}' was written but cannot be found in its folder")

    def account(self):
        self._require()
        acct = dict(self.cfg.get("account") or {})
        try:
            about = json.loads(_run(["about", "--json", self._r("")], timeout=60))
            acct["quota_used"], acct["quota_total"] = int(about.get("used") or 0), int(about.get("total") or 0)
        except (CloudError, ValueError):
            pass
        return acct

    def ensure_root(self, path):
        self._require()
        path = "/".join(p for p in (path or "").replace("\\", "/").split("/") if p.strip())
        if not path:
            raise CloudError("Choose a OneDrive folder name in Settings first.")
        _run(["mkdir", self._r(path)])
        return self._stat(path)["id"]

    def list_children(self, folder_id):
        path = self.paths[folder_id]
        out = _run(["lsjson", "--hash", "--no-mimetype", self._r(path)])
        return [self._norm(e, path) for e in json.loads(out or "[]")]

    def create_folder(self, parent_id, name):
        path = posixpath.join(self.paths[parent_id], name)
        _run(["mkdir", self._r(path)])
        return self._stat(path)

    def rename_folder(self, folder_id, name):
        old = self.paths[folder_id]
        new = posixpath.join(posixpath.dirname(old), name)
        _run(["moveto", self._r(old), self._r(new)])
        return self._stat(new)

    def download(self, item_id):
        return _run(["cat", self._r(self.paths[item_id])])

    def upload_new(self, parent_id, name, data):
        path = posixpath.join(self.paths[parent_id], name)
        _run(["rcat", "--size", str(len(data)), self._r(path)], data=data)
        return self._stat(path)

    def update_file(self, item, data, name=None, new_parent=None):
        old = self.paths[item["id"]]
        folder = self.paths[new_parent] if new_parent else posixpath.dirname(old)
        new = posixpath.join(folder, name or posixpath.basename(old))
        if new != old:
            _run(["moveto", self._r(old), self._r(new)])
        _run(["rcat", "--size", str(len(data)), self._r(new)], data=data)
        return self._stat(new)

    def trash(self, item_id):
        # OneDrive keeps deleted items in its recycle bin
        path = self.paths[item_id]
        _run(["rmdir" if item_id in self.dirs else "deletefile", self._r(path)])

    def delete_permanently(self, item_id):
        _run(["deletefile", "--onedrive-hard-delete", self._r(self.paths[item_id])])
