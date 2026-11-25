"""
Pustakam (पुस्तकम्) — configuration and paths.

Works the same on Linux and Windows: all user data lives in ~/.pustakam
(on Windows that is C:\\Users\\<you>\\.pustakam). Set PUSTAKAM_DATA_DIR to
override the location (useful for testing).
"""
import copy
import json
import os
import secrets
import threading

VERSION = "1.1"
APP_NAME = "Pustakam"
APP_NAME_DEVANAGARI = "पुस्तकम्"

IS_WINDOWS = os.name == "nt"

HOME = os.path.expanduser("~")
DATA_DIR = os.environ.get("PUSTAKAM_DATA_DIR") or os.path.join(HOME, ".pustakam")
NOTES_DIR = os.path.join(DATA_DIR, "notes")
DB_PATH = os.path.join(DATA_DIR, "pustakam.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
LOG_DIR = os.path.join(DATA_DIR, "Logs")
_OLD_LOG_DIR = os.path.join(DATA_DIR, "logs")
SECRET_KEY_PATH = os.path.join(DATA_DIR, ".secret_key")

DEFAULT_PORT = 5150
AUTOLOCK_MINUTES = 15
BACKUP_MAX_COPIES = 5

PROVIDER_KEYS = ("onedrive",)


def _provider_defaults():
    return {
        "enabled": False,
        "remote_folder": "",      # asked from the user in Settings
        "account": None,          # {name, email, quota_used, quota_total}
        "root_id": None,          # remote id of remote_folder (detects changes)
        "last_sync": None,
        "last_result": None,
        "last_test": None,
    }


DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": DEFAULT_PORT,
    "autolock_minutes": AUTOLOCK_MINUTES,
    "backup_dir": BACKUP_DIR,
    "backup_max_copies": BACKUP_MAX_COPIES,
    "default_folder_id": None,
    # Empty list = only the OS account that runs the Pustakam server may sign in.
    "allowed_users": [],
    "pam_service": "login",
    "weather_cities": [],
    "cloud": {
        "sync_interval_minutes": 10,
        "onedrive": _provider_defaults(),
    },
}

_lock = threading.RLock()


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    # earlier builds used a lowercase "logs" folder: move its files into "Logs"
    if os.path.isdir(_OLD_LOG_DIR) and os.path.normcase(_OLD_LOG_DIR) != os.path.normcase(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)
        for name in os.listdir(_OLD_LOG_DIR):
            src, dst = os.path.join(_OLD_LOG_DIR, name), os.path.join(LOG_DIR, name)
            if not os.path.exists(dst):
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        try:
            os.rmdir(_OLD_LOG_DIR)
        except OSError:
            pass
    for d in (NOTES_DIR, BACKUP_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def _merge_defaults(cfg, defaults):
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(cfg[k], dict):
            _merge_defaults(cfg[k], v)
    return cfg


def _restrict_permissions(path):
    if not IS_WINDOWS:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load_config():
    with _lock:
        ensure_dirs()
        if not os.path.exists(CONFIG_PATH):
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            save_config(cfg)
            return cfg
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
        cfg = _merge_defaults(cfg, DEFAULT_CONFIG)
        cfg.pop("oauth_redirect_base", None)            # Google Drive support was removed
        cfg["cloud"].pop("gdrive", None)
        for k in ("client_id", "client_secret", "tenant", "tokens"):
            cfg["cloud"]["onedrive"].pop(k, None)
        return cfg


def save_config(cfg):
    """Atomic write; chmod 600 on Linux."""
    with _lock:
        ensure_dirs()
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        _restrict_permissions(tmp)
        os.replace(tmp, CONFIG_PATH)


def update_config(mutator):
    """Load, mutate in place via callback, save. Thread-safe."""
    with _lock:
        cfg = load_config()
        mutator(cfg)
        save_config(cfg)
        return cfg


def get_secret_key():
    """Persistent Flask secret so sessions survive a restart."""
    ensure_dirs()
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "rb") as f:
            key = f.read()
        if len(key) >= 32:
            return key
    key = secrets.token_bytes(48)
    with open(SECRET_KEY_PATH, "wb") as f:
        f.write(key)
    _restrict_permissions(SECRET_KEY_PATH)
    return key
