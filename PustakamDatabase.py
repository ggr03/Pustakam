"""
Pustakam (पुस्तकम्) — SQLite storage for notebooks, notes, tags and cloud-sync state.
Every note is also mirrored as a Markdown file in ~/.pustakam/notes.
"""
import glob
import os
import sqlite3
import time

import PustakamLogs as logs
from PustakamConfig import DB_PATH, NOTES_DIR, ensure_dirs

_UNSET = object()

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    created_at REAL DEFAULT (strftime('%s','now')),
    updated_at REAL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Untitled',
    content TEXT DEFAULT '',
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    created_at REAL DEFAULT (strftime('%s','now')),
    updated_at REAL DEFAULT (strftime('%s','now')),
    sync_status TEXT DEFAULT 'local',
    remote_path TEXT,
    is_deleted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER,
    action TEXT,
    timestamp REAL DEFAULT (strftime('%s','now')),
    details TEXT
);

-- Cloud sync: which remote file each note is linked to, per provider.
CREATE TABLE IF NOT EXISTS cloud_note_state (
    provider TEXT NOT NULL,
    note_id INTEGER NOT NULL,
    remote_id TEXT NOT NULL,
    remote_rev TEXT,
    local_sig TEXT,
    ext TEXT DEFAULT '.md',
    last_synced REAL,
    PRIMARY KEY (provider, note_id)
);

-- Cloud sync: which remote folder each notebook is linked to, per provider.
CREATE TABLE IF NOT EXISTS cloud_folder_state (
    provider TEXT NOT NULL,
    folder_id INTEGER NOT NULL,
    remote_id TEXT NOT NULL,
    local_name TEXT,
    remote_name TEXT,
    PRIMARY KEY (provider, folder_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, content, content=notes, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
    INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
"""


def get_conn():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT COUNT(*) FROM folders").fetchone()[0]:
        conn.execute("INSERT INTO folders (name) VALUES (?)", ("Default",))
    conn.commit()
    conn.close()


def now():
    return time.time()


def _rows(rows):
    return [dict(r) for r in rows]


# --- Folders (notebooks) ---
def get_folders():
    conn = get_conn()
    rows = conn.execute(
        """SELECT f.*, (SELECT COUNT(*) FROM notes n
                         WHERE n.folder_id = f.id AND n.is_deleted = 0) AS note_count
           FROM folders f ORDER BY f.name COLLATE NOCASE"""
    ).fetchall()
    conn.close()
    return _rows(rows)


def get_folder(fid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_folder(name, parent_id=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO folders (name, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, parent_id, now(), now()),
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    logs.note("created notebook", fid, name)
    return fid


def _folder_name(fid):
    if fid is None:
        return "Unfiled"
    f = get_folder(fid)
    return f["name"] if f else f"#{fid}"


def rename_folder(fid, name):
    old = _folder_name(fid)
    logs.note("renamed notebook", fid, name, f"(was '{old}')")
    conn = get_conn()
    conn.execute("UPDATE folders SET name=?, updated_at=? WHERE id=?", (name, now(), fid))
    conn.commit()
    conn.close()


def delete_folder(fid):
    """Deletes the notebook; its notes move to 'Unfiled' (they are not deleted)."""
    logs.note("deleted notebook", fid, _folder_name(fid), f"({count_live_notes(fid)} note(s) moved to Unfiled)")
    conn = get_conn()
    conn.execute("UPDATE notes SET folder_id=NULL, updated_at=? WHERE folder_id=?", (now(), fid))
    conn.execute("DELETE FROM folders WHERE id=?", (fid,))
    conn.commit()
    conn.close()


def count_live_notes(fid):
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE folder_id=? AND is_deleted=0", (fid,)
    ).fetchone()[0]
    conn.close()
    return n


# --- Notes ---
def get_notes(folder_id=None, tag=None):
    conn = get_conn()
    sql = "SELECT n.* FROM notes n"
    where, args = ["n.is_deleted=0"], []
    if tag:
        sql += " JOIN note_tags nt ON nt.note_id = n.id JOIN tags t ON t.id = nt.tag_id"
        where.append("t.name = ?")
        args.append(tag)
    if folder_id == "unfiled":
        where.append("n.folder_id IS NULL")
    elif folder_id:
        where.append("n.folder_id = ?")
        args.append(folder_id)
    sql += " WHERE " + " AND ".join(where) + " ORDER BY n.updated_at DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return _rows(rows)


def get_all_notes(include_deleted=False):
    conn = get_conn()
    sql = "SELECT * FROM notes" + ("" if include_deleted else " WHERE is_deleted=0")
    rows = conn.execute(sql).fetchall()
    conn.close()
    return _rows(rows)


def get_note(nid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_note(title, content="", folder_id=None):
    conn = get_conn()
    ts = now()
    cur = conn.execute(
        "INSERT INTO notes (title, content, folder_id, created_at, updated_at) VALUES (?,?,?,?,?)",
        (title, content, folder_id, ts, ts),
    )
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    _write_note_file(nid, title, content)
    logs.note("created note", nid, title, f"in '{_folder_name(folder_id)}', {len(content or '')} chars")
    return nid


def update_note(nid, title=None, content=None, folder_id=_UNSET):
    """folder_id: leave unset to keep, pass None to move to 'Unfiled'."""
    note = get_note(nid)
    if not note:
        return False
    t = title if title is not None else note["title"]
    c = content if content is not None else note["content"]
    f = note["folder_id"] if folder_id is _UNSET else folder_id
    conn = get_conn()
    conn.execute(
        "UPDATE notes SET title=?, content=?, folder_id=?, updated_at=? WHERE id=?",
        (t, c, f, now(), nid),
    )
    conn.commit()
    conn.close()
    _write_note_file(nid, t, c)
    changes = []
    if t != note["title"]:
        changes.append(f"renamed from '{note['title']}'")
    if f != note["folder_id"]:
        changes.append(f"moved '{_folder_name(note['folder_id'])}' -> '{_folder_name(f)}'")
    if c != note["content"]:
        changes.append(f"text {len(note['content'] or '')} -> {len(c or '')} chars")
    if changes:
        logs.note("edited note", nid, t, "; ".join(changes))
    return True


def delete_note(nid):
    """Soft delete (kept in the database, removed from lists and cloud)."""
    n = get_note(nid)
    logs.note("deleted note", nid, n["title"] if n else None, "(kept in the database, hidden)")
    conn = get_conn()
    conn.execute("UPDATE notes SET is_deleted=1, updated_at=? WHERE id=?", (now(), nid))
    conn.commit()
    conn.close()
    _remove_note_file(nid)


def _fts_query(q):
    terms = [t for t in q.replace('"', " ").split() if t]
    return " ".join(f'"{t}"*' for t in terms)


def search_notes(query):
    fts = _fts_query(query)
    if not fts:
        return []
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT n.* FROM notes n
               JOIN notes_fts f ON n.id = f.rowid
               WHERE notes_fts MATCH ? AND n.is_deleted=0
               ORDER BY rank""",
            (fts,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return _rows(rows)


# --- Tags ---
def get_tags():
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.*, COUNT(n.id) AS note_count FROM tags t
           JOIN note_tags nt ON nt.tag_id = t.id
           JOIN notes n ON n.id = nt.note_id AND n.is_deleted = 0
           GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
    ).fetchall()
    conn.close()
    return _rows(rows)


def get_note_tags(nid):
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.* FROM tags t JOIN note_tags nt ON t.id = nt.tag_id
           WHERE nt.note_id=? ORDER BY t.name""",
        (nid,),
    ).fetchall()
    conn.close()
    return _rows(rows)


def set_note_tags(nid, tag_names):
    before = sorted(t["name"] for t in get_note_tags(nid))
    after = sorted({t.strip() for t in tag_names if t.strip()})
    if before != after:
        logs.note("tagged note", nid, None, f"tags: {', '.join(after) or '(none)'}")
    conn = get_conn()
    conn.execute("DELETE FROM note_tags WHERE note_id=?", (nid,))
    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        tag = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        conn.execute("INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?,?)", (nid, tag["id"]))
    conn.commit()
    conn.close()


# --- Sync log ---
def log_sync(nid, action, details=""):
    level = "error" if action.endswith(":error") else ("warning" if "conflict" in action else "info")
    logs.sync_line(f"{action}{f' note #{nid}' if nid else ''}: {details}", level)
    conn = get_conn()
    conn.execute(
        "INSERT INTO sync_log (note_id, action, timestamp, details) VALUES (?,?,?,?)",
        (nid, action, now(), details),
    )
    conn.commit()
    conn.close()


def get_sync_log(limit=100):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sync_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return _rows(rows)


# --- Cloud sync state ---
def cloud_note_states(provider):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cloud_note_state WHERE provider=?", (provider,)).fetchall()
    conn.close()
    return {r["note_id"]: dict(r) for r in rows}


def cloud_set_note_state(provider, note_id, remote_id, remote_rev, local_sig, ext):
    conn = get_conn()
    conn.execute(
        """INSERT INTO cloud_note_state (provider, note_id, remote_id, remote_rev, local_sig, ext, last_synced)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(provider, note_id) DO UPDATE SET
             remote_id=excluded.remote_id, remote_rev=excluded.remote_rev,
             local_sig=excluded.local_sig, ext=excluded.ext, last_synced=excluded.last_synced""",
        (provider, note_id, remote_id, remote_rev, local_sig, ext, now()),
    )
    conn.commit()
    conn.close()


def cloud_delete_note_state(provider, note_id):
    conn = get_conn()
    conn.execute("DELETE FROM cloud_note_state WHERE provider=? AND note_id=?", (provider, note_id))
    conn.commit()
    conn.close()


def cloud_folder_states(provider):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cloud_folder_state WHERE provider=?", (provider,)).fetchall()
    conn.close()
    return {r["folder_id"]: dict(r) for r in rows}


def cloud_set_folder_state(provider, folder_id, remote_id, local_name, remote_name):
    conn = get_conn()
    conn.execute(
        """INSERT INTO cloud_folder_state (provider, folder_id, remote_id, local_name, remote_name)
           VALUES (?,?,?,?,?)
           ON CONFLICT(provider, folder_id) DO UPDATE SET
             remote_id=excluded.remote_id, local_name=excluded.local_name,
             remote_name=excluded.remote_name""",
        (provider, folder_id, remote_id, local_name, remote_name),
    )
    conn.commit()
    conn.close()


def cloud_delete_folder_state(provider, folder_id):
    conn = get_conn()
    conn.execute("DELETE FROM cloud_folder_state WHERE provider=? AND folder_id=?", (provider, folder_id))
    conn.commit()
    conn.close()


def cloud_reset(provider):
    conn = get_conn()
    conn.execute("DELETE FROM cloud_note_state WHERE provider=?", (provider,))
    conn.execute("DELETE FROM cloud_folder_state WHERE provider=?", (provider,))
    conn.commit()
    conn.close()


# --- Notes mirrored as Markdown files on disk ---
def _note_path(nid, title):
    safe = "".join(c for c in title if c.isalnum() or c in " _-").strip()[:80]
    if not safe:
        safe = f"note_{nid}"
    return os.path.join(NOTES_DIR, f"{nid:06d}_{safe}.md")


def _write_note_file(nid, title, content):
    _remove_note_file(nid)  # title may have changed -> old filename
    with open(_note_path(nid, title), "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{content or ''}")


def _remove_note_file(nid):
    for p in glob.glob(os.path.join(NOTES_DIR, f"{nid:06d}_*")):
        try:
            os.remove(p)
        except OSError:
            pass
