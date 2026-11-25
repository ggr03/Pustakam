"""
Pustakam (पुस्तकम्) — rotating backup (Linux and Windows).

Creates pustakam-backup-1.zip (newest) ... pustakam-backup-N.zip (oldest) in the
backup directory from config.json, holding a consistent copy of the SQLite database
and the Markdown mirror of every note. Scheduled daily at 21:00 by the installers
(cron on Linux, Task Scheduler on Windows).

Run by hand:   python PustakamBackup.py
"""
import datetime
import os
import sqlite3
import sys
import tempfile
import threading
import zipfile

import PustakamLogs
from PustakamConfig import BACKUP_MAX_COPIES, DB_PATH, NOTES_DIR, load_config


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def backup_dir(cfg=None):
    cfg = cfg or load_config()
    return os.path.expanduser(cfg.get("backup_dir") or os.path.join(os.path.dirname(DB_PATH), "backups"))


def list_backups(cfg=None):
    d = backup_dir(cfg)
    out = []
    if os.path.isdir(d):
        for name in os.listdir(d):
            if name.startswith("pustakam-backup-") and name.endswith(".zip"):
                st = os.stat(os.path.join(d, name))
                out.append({"name": name, "size": st.st_size, "time": st.st_mtime})
    return sorted(out, key=lambda b: b["time"], reverse=True)


_lock = threading.Lock()


def create_backup():
    """Rotate and write a new pustakam-backup-1.zip. Returns its path."""
    cfg = load_config()
    folder = backup_dir(cfg)
    keep = max(1, int(cfg.get("backup_max_copies") or BACKUP_MAX_COPIES))
    os.makedirs(folder, exist_ok=True)
    if not os.path.exists(DB_PATH):
        PustakamLogs.backup(f"backup skipped: database not found at {DB_PATH}", "warning")
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    def path(i):
        return os.path.join(folder, f"pustakam-backup-{i}.zip")

    with _lock:
        if os.path.exists(path(keep)):
            os.remove(path(keep))
        for i in range(keep - 1, 0, -1):
            if os.path.exists(path(i)):
                os.replace(path(i), path(i + 1))
        with tempfile.TemporaryDirectory() as tmp:
            snap = os.path.join(tmp, "pustakam.db")
            src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(snap)
            with dst:
                src.backup(dst)   # consistent even while the app is running
            src.close()
            dst.close()
            with zipfile.ZipFile(path(1), "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snap, "pustakam.db")
                if os.path.isdir(NOTES_DIR):
                    for name in sorted(os.listdir(NOTES_DIR)):
                        z.write(os.path.join(NOTES_DIR, name), f"notes/{name}")
    PustakamLogs.backup(f"backup created: {path(1)} ({os.path.getsize(path(1))} bytes, keeping {keep})")
    return path(1)


def main():
    log("Starting Pustakam backup...")
    try:
        p = create_backup()
    except FileNotFoundError as e:
        log(f"WARNING: {e}; nothing to back up.")
        return 1
    log(f"Backup created: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
