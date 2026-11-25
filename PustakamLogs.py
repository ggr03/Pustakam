"""
Pustakam (पुस्तकम्) — plain-text log files in ~/.pustakam/Logs

    connection.log  sign-ins/outs (with the device's IP), session expiry, server start,
                    OneDrive sign-in, connection tests and disconnects
    sync.log        every OneDrive sync: start, each upload/download/rename/delete/
                    conflict, errors, and the summary
    notes.log       every note and notebook created, edited, renamed, moved or deleted,
                    and by whom: [app] you in the browser, [onedrive] the sync, [import]
    backup.log      local backups

Each file rotates at 2 MB and keeps 5 old copies (connection.log.1 … .5).
Note *contents* are never written to the logs, only titles and sizes.
"""
import contextvars
import logging
import os
from logging.handlers import RotatingFileHandler

from PustakamConfig import LOG_DIR, ensure_dirs

FILES = {"connection": "connection.log", "sync": "sync.log", "notes": "notes.log", "backup": "backup.log"}

# Who is making a change: "app" (browser), "onedrive" (sync), "import", "backup"
source = contextvars.ContextVar("pustakam_source", default="app")

_loggers = {}


def _get(kind):
    lg = _loggers.get(kind)
    if lg:
        return lg
    ensure_dirs()
    lg = logging.getLogger(f"pustakam.{kind}")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        h = RotatingFileHandler(os.path.join(LOG_DIR, FILES[kind]), maxBytes=2_000_000,
                                backupCount=5, encoding="utf-8", delay=True)
        h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        lg.addHandler(h)
    _loggers[kind] = lg
    return lg


def _write(kind, msg, level="info"):
    try:
        _get(kind).log(getattr(logging, level.upper(), logging.INFO), msg)
    except Exception:  # logging must never break the app
        pass


def connection(msg, level="info"):
    _write("connection", msg, level)


def sync_line(msg, level="info"):
    _write("sync", msg, level)


def backup(msg, level="info"):
    _write("backup", msg, level)


def note(action, nid=None, title=None, details=""):
    who = source.get()
    target = f"#{nid} " if nid is not None else ""
    name = f"'{title}'" if title is not None else ""
    _write("notes", f"[{who}] {action} {target}{name}{(' ' + details) if details else ''}".rstrip())


# ------------------------------------------------------------------ viewer helpers
def list_logs():
    ensure_dirs()
    out = []
    for name in sorted(os.listdir(LOG_DIR)):
        path = os.path.join(LOG_DIR, name)
        if os.path.isfile(path) and ".log" in name:
            st = os.stat(path)
            out.append({"name": name, "size": st.st_size, "time": st.st_mtime})
    return out


def tail(name, lines=300):
    """Last `lines` lines of a log file in LOG_DIR (name is validated, no paths)."""
    if name != os.path.basename(name) or ".log" not in name:
        raise ValueError("bad log name")
    path = os.path.join(LOG_DIR, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(name)
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 512 * 1024))
        data = f.read().decode("utf-8", "replace")
    return "\n".join(data.splitlines()[-lines:])
