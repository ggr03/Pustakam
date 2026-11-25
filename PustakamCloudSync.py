"""
Pustakam (पुस्तकम्) — two-way sync between local notebooks and a OneDrive folder.

Layout in the cloud (folder name chosen by the user in Settings):

    <remote folder>/                 e.g.  My Drive/Pustakam
        Note without notebook.md
        <Notebook name>/
            Some note.md
            Shopping list.txt

* Each notebook  <-> one first-level sub-folder.
* Each note      <-> one .md file (title = file name, content = file body).
* .md / .markdown / .txt files added in the cloud become notes locally.
* Edits, renames, moves and deletes travel both ways.
* If a note changed on both sides since the last sync, the local version wins
  in the cloud and the cloud version is kept as a separate "(conflict …)" note.
* Deleted notes go to the OneDrive recycle bin, never hard-deleted.
"""
import datetime
import hashlib
import os
import threading
import time
import traceback

import PustakamDatabase as db
import PustakamLogs as logs
from PustakamCloudBase import CloudError, NotConnected, sanitize_name
from PustakamConfig import PROVIDER_KEYS, load_config, update_config
import PustakamOneDrive as onedrive
from PustakamOneDrive import OneDriveProvider

PROVIDERS = {"onedrive": OneDriveProvider}
ALLOWED_EXT = (".md", ".markdown", ".txt")
MAX_FILE_BYTES = 5 * 1024 * 1024
SAFETY_MIN = 6          # safety check applies once this many notes are linked
SAFETY_RATIO = 0.5      # refuse to delete more than half of linked notes in one run

_sync_lock = threading.Lock()
status = {"running": False, "provider": None, "started": None}


# ------------------------------------------------------------------ helpers
def make_provider(key, cfg=None):
    if key not in PROVIDERS:
        raise CloudError(f"Unknown provider {key}")
    cfg = cfg or load_config()
    return PROVIDERS[key](cfg["cloud"][key])


def is_connected(pcfg=None, key="onedrive"):
    return onedrive.is_connected()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _note_bytes(note):
    return (note.get("content") or "").encode("utf-8")


def _local_sig(note):
    return _sha(f"{note['title']}\0{note['folder_id']}\0".encode("utf-8") + _note_bytes(note))


def _split_ext(name):
    base, ext = os.path.splitext(name)
    return (base, ext.lower()) if ext.lower() in ALLOWED_EXT else (name, "")


def _decode(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    return text.replace("\r\n", "\n")


def _syncable(item):
    if item["is_dir"] or item["name"].startswith("."):
        return False
    return _split_ext(item["name"])[1] != "" and item.get("size", 0) <= MAX_FILE_BYTES


# ------------------------------------------------------------------ sign-in (OneDrive via rclone)
def _onedrive_signed_in(account):
    logs.connection(f"OneDrive signed in: {account.get('name', '')} <{account.get('email', '')}>")
    update_config(lambda c: c["cloud"]["onedrive"].update(account=account, root_id=None))
    test_provider("onedrive")


def start_signin(key):
    logs.connection("OneDrive sign-in started (waiting for Microsoft approval)")
    return {"auth_url": onedrive.start_signin(_onedrive_signed_in)}


def disconnect(key):
    logs.connection("OneDrive disconnected (sign-in removed; local notes kept)")
    onedrive.signin.stop()
    onedrive.remove_remote()
    def mut(c):
        pc = c["cloud"][key]
        pc.update(account=None, root_id=None, last_test=None, last_result=None)
    update_config(mut)
    db.cloud_reset(key)


# ------------------------------------------------------------------ test
def test_provider(key):
    """Verifies sign-in, the chosen folder, and read/write access."""
    cfg = load_config()
    pcfg = cfg["cloud"][key]
    checks = []
    result = {"ok": False, "checks": checks, "time": time.time()}
    try:
        p = make_provider(key, cfg)
        acct = p.account()
        result["account"] = acct
        checks.append(f"Signed in as {acct.get('name') or ''} <{acct.get('email') or '?'}>")
        folder = (pcfg.get("remote_folder") or "").strip()
        if not folder:
            checks.append("No cloud folder chosen yet. Enter one in Settings and test again.")
            result["needs_folder"] = True
        else:
            root = p.ensure_root(folder)
            checks.append(f"Folder '{folder}' is ready")
            items = p.list_children(root)
            notes = sum(1 for i in items if _syncable(i))
            dirs = sum(1 for i in items if i["is_dir"])
            checks.append(f"Folder contains {dirs} notebook folder(s) and {notes} note file(s) at top level")
            payload = f"Pustakam connection test {datetime.datetime.now().isoformat()}".encode()
            item = p.upload_new(root, f".pustakam-test-{int(time.time())}.txt", payload)
            back = p.download(item["id"])
            p.delete_permanently(item["id"])
            if back != payload:
                raise CloudError("Uploaded test file came back different")
            checks.append("Write, read and delete test passed")
            result["ok"] = True
    except NotConnected as e:
        result["error"] = str(e)
    except CloudError as e:
        result["error"] = str(e)
    except Exception as e:  # noqa
        result["error"] = f"Unexpected error: {e}"

    if result["ok"]:
        logs.connection(f"OneDrive test OK: {' | '.join(checks)}")
    else:
        logs.connection(f"OneDrive test FAILED: {result.get('error')} | {' | '.join(checks)}", "warning")

    def mut(c):
        pc = c["cloud"][key]
        pc["last_test"] = result
        if result.get("account"):
            pc["account"] = result["account"]
    update_config(mut)
    return result


# ------------------------------------------------------------------ sync engine
class _SyncRun:
    def __init__(self, key):
        self.key = key
        self.cfg = load_config()
        self.pcfg = self.cfg["cloud"][key]
        self.p = make_provider(key, self.cfg)
        self.label = self.p.label
        self.stats = dict(uploaded=0, downloaded=0, deleted_local=0, deleted_remote=0,
                          conflicts=0, folders=0, errors=0, skipped=0)
        self.messages = []

    def log(self, nid, action, details):
        db.log_sync(nid, f"{self.key}:{action}", details)

    def err(self, nid, what, e):
        self.stats["errors"] += 1
        msg = f"{what}: {e}"
        self.messages.append(msg)
        self.log(nid, "error", msg)

    # ---- name bookkeeping (avoid two notes mapping to the same file name)
    def _taken(self, parent):
        return self.names.setdefault(parent, {})

    def _unique_name(self, parent, title, ext, own_id=None):
        base = sanitize_name(title)
        taken = self._taken(parent)
        name, n = base + ext, 2
        while name.lower() in taken and taken[name.lower()] != own_id:
            name, n = f"{base} ({n}){ext}", n + 1
        return name

    def _claim(self, parent, name, item_id):
        self._taken(parent)[name.lower()] = item_id

    def _release(self, parent, name):
        self._taken(parent).pop(name.lower(), None)

    # ---- mapping between notebooks and remote folders
    def parent_for(self, note):
        fid = note.get("folder_id")
        return self.l2r.get(fid, self.root) if fid else self.root

    def folder_for(self, parent_id):
        return None if parent_id == self.root else self.r2l.get(parent_id)

    # ---- note operations
    def push_new(self, note, ext=".md"):
        parent = self.parent_for(note)
        name = self._unique_name(parent, note["title"], ext)
        item = self.p.upload_new(parent, name, _note_bytes(note))
        self._claim(parent, item["name"], item["id"])
        db.cloud_set_note_state(self.key, note["id"], item["id"], item["rev"], _local_sig(note), ext)
        self.stats["uploaded"] += 1
        self.log(note["id"], "upload", f"'{note['title']}' -> {self.label}/{item['name']}")

    def push_update(self, note, st, r):
        parent = self.parent_for(note)
        ext = st.get("ext") or ".md"
        name = self._unique_name(parent, note["title"], ext, own_id=r["id"])
        same_name = name.lower() == r["name"].lower() and parent == r["parent"]
        item = self.p.update_file(r, _note_bytes(note),
                                  name=None if same_name else name,
                                  new_parent=parent if parent != r["parent"] else None)
        self._release(r["parent"], r["name"])
        self._claim(item["parent"] or parent, item["name"], item["id"])
        db.cloud_set_note_state(self.key, note["id"], item["id"], item["rev"], _local_sig(note), ext)
        self.stats["uploaded"] += 1
        self.log(note["id"], "upload", f"Updated {self.label}/{item['name']}")

    def pull(self, r, note_id=None, data=None):
        if data is None:
            data = self.p.download(r["id"])
        title, ext = _split_ext(r["name"])
        content = _decode(data)
        fid = self.folder_for(r["parent"])
        if note_id:
            db.update_note(note_id, title=title, content=content, folder_id=fid)
        else:
            note_id = db.create_note(title, content, fid)
        note = db.get_note(note_id)
        db.cloud_set_note_state(self.key, note_id, r["id"], r["rev"], _local_sig(note), ext or ".md")
        self.stats["downloaded"] += 1
        self.log(note_id, "download", f"{self.label}/{r['name']} -> '{title}'")
        return note_id

    # ---- main
    def run(self):
        folder = (self.pcfg.get("remote_folder") or "").strip()
        if not folder:
            raise CloudError(f"Choose a {self.label} folder in Settings first.")
        self.root = self.p.ensure_root(folder)
        if self.pcfg.get("root_id") and self.pcfg["root_id"] != self.root:
            db.cloud_reset(self.key)   # folder changed -> link everything again
        update_config(lambda c: c["cloud"][self.key].__setitem__("root_id", self.root))

        self.names = {}
        root_items = self.p.list_children(self.root)
        remote_dirs = {i["id"]: i for i in root_items if i["is_dir"] and not i["name"].startswith(".")}
        for i in root_items:
            self._claim(self.root, i["name"], i["id"])

        gone_folders, trash_later = self._sync_folders(remote_dirs)

        remote_files = {i["id"]: i for i in root_items if _syncable(i)}
        for rid in self.r2l:
            for i in self.p.list_children(rid):
                self._claim(rid, i["name"], i["id"])
                if _syncable(i):
                    remote_files[i["id"]] = i

        self._sync_notes(remote_files)

        for rid in trash_later:
            try:
                if not self.p.list_children(rid):
                    self.p.trash(rid)
                    self.log(None, "delete_remote", f"Removed empty {self.label} folder")
            except CloudError as e:
                self.err(None, "Removing folder", e)
        for fid in gone_folders:
            if db.get_folder(fid) and db.count_live_notes(fid) == 0:
                db.delete_folder(fid)
                update_config(lambda c: c.__setitem__("default_folder_id", None)
                              if c.get("default_folder_id") == fid else None)
                self.log(None, "delete_local", f"Notebook #{fid} removed (deleted in {self.label})")
        return self.stats

    def _sync_folders(self, remote_dirs):
        states = db.cloud_folder_states(self.key)
        local = {f["id"]: f for f in db.get_folders()}
        self.r2l, self.l2r = {}, {}
        gone, trash_later = [], []

        # Self-heal: a stored folder ID that is no longer listed but whose folder
        # still exists by name is the same folder (e.g. IDs saved by older builds).
        claimed = {st["remote_id"] for st in states.values() if st["remote_id"] in remote_dirs}
        by_rname = {}
        for rid, rf in remote_dirs.items():
            if rid not in claimed:
                by_rname.setdefault(rf["name"].lower(), rid)
        for fid, st in states.items():
            if st["remote_id"] in remote_dirs:
                continue
            names = [(st.get("remote_name") or "").lower(), (local.get(fid) or {}).get("name", "").lower()]
            rid = next((by_rname.pop(n) for n in names if n and n in by_rname), None)
            if rid:
                self.log(None, "relink", f"Notebook '{st['local_name']}' re-linked to {self.label} folder '{remote_dirs[rid]['name']}'")
                st["remote_id"] = rid
                db.cloud_set_folder_state(self.key, fid, rid, st["local_name"], st["remote_name"])

        for fid, st in states.items():
            lf, rf = local.get(fid), remote_dirs.get(st["remote_id"])
            if lf is None:
                db.cloud_delete_folder_state(self.key, fid)
                if rf:
                    trash_later.append(rf["id"])
                    self.r2l[rf["id"]] = None  # keep listing it so its notes can move out
                continue
            if rf is None:
                db.cloud_delete_folder_state(self.key, fid)
                gone.append(fid)
                continue
            local_changed = lf["name"] != st["local_name"]
            remote_changed = rf["name"] != st["remote_name"]
            try:
                if local_changed:
                    rf = self.p.rename_folder(rf["id"], sanitize_name(lf["name"]))
                    self.log(None, "rename_remote", f"Notebook '{st['local_name']}' -> '{lf['name']}'")
                elif remote_changed:
                    db.rename_folder(fid, rf["name"])
                    lf = dict(lf, name=rf["name"])
                    self.log(None, "rename_local", f"Notebook '{st['local_name']}' -> '{rf['name']}'")
            except CloudError as e:
                self.err(None, f"Renaming notebook {lf['name']}", e)
            self._map(fid, rf["id"], lf["name"], rf["name"])

        mapped_local = set(self.l2r)
        by_name = {}
        for f in local.values():
            if f["id"] not in mapped_local:    # includes 'gone' ones: never duplicate a notebook name
                by_name.setdefault(f["name"].lower(), f["id"])
        for rid, rf in remote_dirs.items():
            if rid in self.r2l:
                continue
            fid = by_name.pop(rf["name"].lower(), None)
            if fid in gone:
                gone.remove(fid)
            if fid is None:
                fid = db.create_folder(rf["name"])
                self.stats["folders"] += 1
                self.log(None, "folder_local", f"New notebook '{rf['name']}' from {self.label}")
            self._map(fid, rid, rf["name"] if fid not in local else local[fid]["name"], rf["name"])

        for fid, f in local.items():
            if fid in self.l2r or fid in gone:
                continue
            try:
                rf = self.p.create_folder(self.root, sanitize_name(f["name"]))
                self._claim(self.root, rf["name"], rf["id"])
                self.stats["folders"] += 1
                self.log(None, "folder_remote", f"Created {self.label} folder '{rf['name']}'")
                self._map(fid, rf["id"], f["name"], rf["name"])
            except CloudError as e:
                self.err(None, f"Creating folder {f['name']}", e)
        return gone, trash_later

    def _relink_notes(self, states, notes, remote_files):
        """Self-heal: a linked note whose file ID vanished, but whose file is still
        there under the expected name, is re-linked instead of being treated as deleted."""
        linked = {s["remote_id"] for s in states.values()}
        index = {}
        for rid, r in remote_files.items():
            if rid not in linked:
                index.setdefault((r["parent"], r["name"].lower()), rid)
        for nid, st in states.items():
            note = notes.get(nid)
            if st["remote_id"] in remote_files or not note or note["is_deleted"]:
                continue
            name = (sanitize_name(note["title"]) + (st.get("ext") or ".md")).lower()
            rid = index.pop((self.parent_for(note), name), None)
            if not rid:
                continue
            r = remote_files[rid]
            try:
                same = _decode(self.p.download(rid)) == (note.get("content") or "")
            except CloudError:
                continue
            # identical text: fully in sync; different: let the normal rules decide (pull or conflict)
            st.update(remote_id=rid, remote_rev=r["rev"] if same else "")
            db.cloud_set_note_state(self.key, nid, rid, st["remote_rev"], st["local_sig"], st.get("ext") or ".md")
            self.log(nid, "relink", f"'{note['title']}' re-linked to {self.label}/{r['name']}")

    def _map(self, fid, rid, local_name, remote_name):
        self.r2l[rid] = fid
        self.l2r[fid] = rid
        db.cloud_set_folder_state(self.key, fid, rid, local_name, remote_name)

    def _sync_notes(self, remote_files):
        states = db.cloud_note_states(self.key)
        notes = {n["id"]: n for n in db.get_all_notes(include_deleted=True)}
        self._relink_notes(states, notes, remote_files)

        missing = [s for s in states.values() if s["remote_id"] not in remote_files]
        all_gone = len(states) >= 3 and len(missing) == len(states)
        if all_gone or (len(states) >= SAFETY_MIN and len(missing) > len(states) * SAFETY_RATIO):
            raise CloudError(
                f"Safety stop: {len(missing)} of {len(states)} linked notes are missing in {self.label}. "
                "If that is intended, use 'Reset link' in Settings and sync again.")

        linked_remote = {s["remote_id"] for s in states.values()}

        # 1) notes that were linked before
        for nid, st in states.items():
            note, r = notes.get(nid), remote_files.get(st["remote_id"])
            try:
                if note is None or note["is_deleted"]:
                    if r is None:
                        db.cloud_delete_note_state(self.key, nid)
                    elif r["rev"] == st["remote_rev"]:
                        self.p.trash(r["id"])
                        self._release(r["parent"], r["name"])
                        db.cloud_delete_note_state(self.key, nid)
                        self.stats["deleted_remote"] += 1
                        self.log(nid, "delete_remote", f"Moved {self.label}/{r['name']} to trash")
                    else:  # changed in cloud after local delete -> bring it back as new note
                        db.cloud_delete_note_state(self.key, nid)
                        self.pull(r)
                    continue

                local_changed = _local_sig(note) != st["local_sig"]
                if r is None:
                    db.cloud_delete_note_state(self.key, nid)
                    if local_changed:
                        self.push_new(note, st.get("ext") or ".md")
                    else:
                        db.delete_note(nid)
                        self.stats["deleted_local"] += 1
                        self.log(nid, "delete_local", f"'{note['title']}' deleted in {self.label}")
                    continue

                remote_changed = r["rev"] != st["remote_rev"]
                if local_changed and remote_changed:
                    data = self.p.download(r["id"])
                    if data == _note_bytes(note):
                        self.push_update(note, st, r)  # same text, only names differ
                    else:
                        title, _ = _split_ext(r["name"])
                        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
                        cid = db.create_note(f"{title} (conflict {self.label} {stamp})", _decode(data),
                                             self.folder_for(r["parent"]))
                        notes[cid] = db.get_note(cid)
                        self.push_update(note, st, r)
                        self.stats["conflicts"] += 1
                        self.log(nid, "conflict", f"Both sides changed '{note['title']}'; cloud copy saved as note #{cid}")
                elif local_changed:
                    self.push_update(note, st, r)
                elif remote_changed:
                    self.pull(r, note_id=nid)
            except CloudError as e:
                self.err(nid, f"Syncing '{note['title'] if note else nid}'", e)

        # 2) files that appeared in the cloud
        # match on the cloud-safe file name: a title like "re:Inforce" is stored as "re-Inforce.md"
        unlinked_local = {}
        for n in db.get_all_notes():
            if n["id"] not in states:
                unlinked_local.setdefault((sanitize_name(n["title"]).lower(), n["folder_id"]), n)
        for rid, r in remote_files.items():
            if rid in linked_remote:
                continue
            try:
                title, ext = _split_ext(r["name"])
                fid = self.folder_for(r["parent"])
                if r["parent"] in self.r2l and fid is None:
                    continue  # folder about to be removed
                cand = unlinked_local.pop((sanitize_name(title).lower(), fid), None)
                data = self.p.download(r["id"])
                if cand and _note_bytes(cand) == data.replace(b"\r\n", b"\n"):
                    db.cloud_set_note_state(self.key, cand["id"], rid, r["rev"], _local_sig(cand), ext)
                    self.log(cand["id"], "link", f"'{title}' already identical in {self.label}")
                    states[cand["id"]] = True
                else:
                    if cand:
                        unlinked_local[(sanitize_name(title).lower(), fid)] = cand
                    nid = self.pull(r, data=data)
                    states[nid] = True
            except CloudError as e:
                self.err(None, f"Downloading {r['name']}", e)

        # 3) local notes never uploaded
        for n in db.get_all_notes():
            if n["id"] in states:
                continue
            try:
                self.push_new(n)
            except CloudError as e:
                self.err(n["id"], f"Uploading '{n['title']}'", e)


def sync_provider(key, wait=False):
    if not _sync_lock.acquire(blocking=wait):
        return {"ok": False, "error": "A sync is already running."}
    status.update(running=True, provider=key, started=time.time())
    run = None
    token = logs.source.set("onedrive")
    logs.sync_line(f"--- sync with {key} started")
    try:
        run = _SyncRun(key)
        stats = run.run()
        result = {"ok": stats["errors"] == 0, "stats": stats, "messages": run.messages[:20]}
    except (CloudError, NotConnected) as e:
        result = {"ok": False, "error": str(e), "stats": run.stats if run else None}
        db.log_sync(None, f"{key}:error", str(e))
    except Exception as e:  # noqa
        traceback.print_exc()
        result = {"ok": False, "error": f"Unexpected error: {e}"}
        db.log_sync(None, f"{key}:error", str(e))
    finally:
        status.update(running=False, provider=None, started=None)
        logs.source.reset(token)
        _sync_lock.release()
    result["time"] = time.time()
    if result.get("error"):
        logs.sync_line(f"--- sync with {key} FAILED: {result['error']}", "error")
    else:
        logs.sync_line(f"--- sync with {key} finished: {result.get('stats')}")

    def mut(c):
        c["cloud"][key]["last_sync"] = result["time"]
        c["cloud"][key]["last_result"] = result
    update_config(mut)
    return result


def active_providers(cfg=None):
    cfg = cfg or load_config()
    return [k for k in PROVIDER_KEYS
            if cfg["cloud"][k].get("enabled") and is_connected(cfg["cloud"][k], k)
            and (cfg["cloud"][k].get("remote_folder") or "").strip()]


def sync_all():
    keys = active_providers()
    if not keys:
        return {"ok": False, "error": "No cloud drive is connected. Set one up in Settings.", "results": {}}
    results = {k: sync_provider(k, wait=True) for k in keys}
    return {"ok": all(r.get("ok") for r in results.values()), "results": results}


def start_scheduler():
    def loop():
        time.sleep(20)
        while True:
            try:
                cfg = load_config()
                minutes = int(cfg["cloud"].get("sync_interval_minutes") or 0)
                if minutes > 0:
                    for k in active_providers(cfg):
                        last = cfg["cloud"][k].get("last_sync") or 0
                        if time.time() - last >= minutes * 60:
                            sync_provider(k)
            except Exception:
                traceback.print_exc()
            time.sleep(30)

    t = threading.Thread(target=loop, name="pustakam-sync", daemon=True)
    t.start()
    return t
