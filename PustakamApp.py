"""
Pustakam (पुस्तकम्) — "book" in Sanskrit. A local-first Markdown notebook with
two-way OneDrive sync and local backups. Runs on Linux and Windows.

Start:  python PustakamApp.py      (served by waitress on http://<host>:5150)
"""
import os
import sys
import time

if sys.version_info < (3, 11):
    sys.exit(f"Pustakam needs Python 3.11 or newer (this is {sys.version.split()[0]}). "
             "Re-run the installer to set up a newer Python.")
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.utils import secure_filename

import PustakamAuth as auth
import PustakamLogs as logs
import PustakamCloudSync as cloud
import PustakamDatabase as db
import PustakamOneDrive as onedrive
from PustakamCloudBase import CloudError
from PustakamConfig import (APP_NAME, APP_NAME_DEVANAGARI, AUTOLOCK_MINUTES,
                            IS_WINDOWS, LOG_DIR, PROVIDER_KEYS, VERSION, get_secret_key,
                            load_config, update_config)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = get_secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=32 * 1024 * 1024)

db.init_db()


@app.context_processor
def _globals():
    return {"version": VERSION, "app_name": APP_NAME, "app_name_dev": APP_NAME_DEVANAGARI}


# ------------------------------------------------------------------ request security
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
CSRF_HEADER = "X-Pustakam"

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",   # KaTeX and notebook icons use style attributes
    "font-src 'self' data: https://cdn.jsdelivr.net",
    "img-src 'self' data: https:",                                 # Markdown images from https sites
    "connect-src 'self' https://api.open-meteo.com https://air-quality-api.open-meteo.com https://geocoding-api.open-meteo.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def _is_local_request():
    return (request.remote_addr or "") in ("127.0.0.1", "::1")


@app.before_request
def _csrf_guard():
    """Block cross-site request forgery:
    * any state-changing request whose Origin is another site is refused;
    * API calls must carry the X-Pustakam header, which other sites cannot add
      without a CORS pre-flight that this server never approves."""
    if request.method not in UNSAFE_METHODS:
        return None
    origin = request.headers.get("Origin")
    if origin and origin != "null" and urlparse(origin).netloc.lower() != (request.host or "").lower():
        logs.connection(f"blocked cross-site {request.method} {request.path} from origin {origin} ({request.remote_addr})", "warning")
        abort(403)
    if request.path.startswith("/api/") and request.headers.get(CSRF_HEADER) != "1":
        return jsonify({"error": "Missing request header"}), 403
    return None


@app.after_request
def _security_headers(resp):
    h = resp.headers
    h.setdefault("Content-Security-Policy", CSP)
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    if request.path.startswith("/api/") or request.path in ("/", "/settings", "/login"):
        h["Cache-Control"] = "no-store"
    return resp


def _current_user():
    return auth.validate_session(session.get("token"))


def _session_expired():
    """Server-side inactivity logout (not only in the browser)."""
    minutes = load_config().get("autolock_minutes", AUTOLOCK_MINUTES)
    return time.time() - session.get("last_activity", 0) > minutes * 60


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if user and _session_expired():
            logs.connection(f"logged out after inactivity: user '{user}' from {request.remote_addr}")
            auth.destroy_session(session.get("token"))
            user = None
        if user:
            session["last_activity"] = time.time()
        if not user:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not signed in"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------ auth
@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    local = _is_local_request()
    username = auth.service_user() if local else ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        ok, error = auth.authenticate(username, request.form.get("password", ""),
                                      client=request.remote_addr or "?")
        ip = request.remote_addr or "?"
        if ok:
            logs.connection(f"sign-in OK: user '{username}' from {ip}")
            session.clear()
            session["token"] = auth.create_session(username)
            session["user"] = username
            session["last_activity"] = time.time()
            return redirect(url_for("index_page"))
        logs.connection(f"sign-in FAILED: user '{username}' from {ip}: {error}", "warning")
    return render_template("PustakamLogin.html", error=error, username=username,
                           platform=auth.platform_label(), service_user=auth.service_user() if local else "")


@app.route("/logout")
def logout():
    if session.get("user"):
        logs.connection(f"logout: user '{session.get('user')}' from {request.remote_addr}")
    auth.destroy_session(session.get("token"))
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/api/check-session")
def check_session():
    user = _current_user()
    if not user:
        session.clear()
        return jsonify({"valid": False})
    minutes = load_config().get("autolock_minutes", AUTOLOCK_MINUTES)
    if time.time() - session.get("last_activity", 0) > minutes * 60:
        logs.connection(f"logged out after {minutes} min inactivity: user '{user}' from {request.remote_addr}")
        auth.destroy_session(session.get("token"))
        session.clear()
        return jsonify({"valid": False, "expired": True})
    return jsonify({"valid": True, "user": user})


@app.route("/api/ping", methods=["POST"])
@login_required
def ping():
    session["last_activity"] = time.time()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ pages
def _public_cloud(cfg):
    out = {"sync_interval_minutes": cfg["cloud"].get("sync_interval_minutes", 10)}
    for k in PROVIDER_KEYS:
        pc = cfg["cloud"][k]
        out[k] = {
            "enabled": pc.get("enabled", False),
            "remote_folder": pc.get("remote_folder", ""),
            "connected": cloud.is_connected(pc, k),
            "account": pc.get("account"),
            "last_sync": pc.get("last_sync"),
            "last_result": pc.get("last_result"),
            "last_test": pc.get("last_test"),
        }
    out["onedrive"]["rclone"] = onedrive.rclone_info()
    out["onedrive"]["signin"] = onedrive.signin.status()
    out["running"] = cloud.status["running"]
    out["running_provider"] = cloud.status["provider"]
    return out


@app.route("/")
@login_required
def index_page():
    cfg = load_config()
    boot = {
        "folders": db.get_folders(),
        "tags": db.get_tags(),
        "default_folder_id": cfg.get("default_folder_id"),
        "weather_cities": cfg.get("weather_cities", []),
        "cloud_active": cloud.active_providers(cfg),
        "user": session.get("user", ""),
    }
    return render_template("PustakamIndex.html", boot=boot, user=session.get("user", ""),
                           platform=auth.platform_label())


@app.route("/settings")
@login_required
def settings_page():
    cfg = load_config()
    return render_template("PustakamSettings.html", cfg=cfg, cloud=_public_cloud(cfg),
                           folders=db.get_folders(), user=session.get("user", ""),
                           platform=auth.platform_label(), service_user=auth.service_user(),
                           is_windows=IS_WINDOWS, lan_urls=_lan_urls(cfg))


def _lan_urls(cfg):
    """Addresses other devices on the network can use to open Pustakam."""
    import socket
    port, host = int(cfg.get("port", 5150)), cfg.get("host", "0.0.0.0")
    if host not in ("0.0.0.0", "::", ""):
        return [] if host.startswith("127.") or host == "localhost" else [f"http://{host}:{port}"]
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))   # no packet is sent; picks the LAN interface
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    urls = [f"http://{ip}:{port}" for ip in ips if not ip.startswith("127.")]
    try:
        urls.append(f"http://{socket.gethostname()}:{port}")
    except OSError:
        pass
    return urls


# ------------------------------------------------------------------ notes
def _list_item(n):
    content = n.get("content") or ""
    n = dict(n)
    n["preview"] = content[:160]
    n.pop("content", None)
    return n


@app.route("/api/notes", methods=["GET"])
@login_required
def api_list_notes():
    folder = request.args.get("folder_id")
    if folder not in (None, "", "all", "unfiled"):
        folder = int(folder)
    elif folder in ("", "all"):
        folder = None
    notes = db.get_notes(folder, tag=request.args.get("tag") or None)
    return jsonify([_list_item(n) for n in notes])


@app.route("/api/notes", methods=["POST"])
@login_required
def api_create_note():
    data = request.json or {}
    title = (data.get("title") or "Untitled").strip() or "Untitled"
    folder_id = data.get("folder_id")
    if folder_id in (None, "", "all"):
        folder_id = load_config().get("default_folder_id")
    if folder_id == "unfiled" or (folder_id and not db.get_folder(folder_id)):
        folder_id = None
    nid = db.create_note(title, data.get("content", ""), folder_id)
    return jsonify({"id": nid, "title": title, "folder_id": folder_id})


@app.route("/api/notes/<int:nid>", methods=["GET"])
@login_required
def api_get_note(nid):
    note = db.get_note(nid)
    if not note or note["is_deleted"]:
        abort(404)
    note["tags"] = db.get_note_tags(nid)
    return jsonify(note)


@app.route("/api/notes/<int:nid>", methods=["PUT"])
@login_required
def api_update_note(nid):
    data = request.json or {}
    kwargs = {"title": data.get("title"), "content": data.get("content")}
    if "folder_id" in data:
        kwargs["folder_id"] = data["folder_id"] or None
    db.update_note(nid, **kwargs)
    if "tags" in data:
        db.set_note_tags(nid, data["tags"])
    return jsonify({"ok": True, "updated_at": time.time()})


@app.route("/api/notes/<int:nid>", methods=["DELETE"])
@login_required
def api_delete_note(nid):
    db.delete_note(nid)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ notebooks
@app.route("/api/folders", methods=["GET"])
@login_required
def api_list_folders():
    return jsonify({"folders": db.get_folders(), "default_folder_id": load_config().get("default_folder_id")})


@app.route("/api/folders", methods=["POST"])
@login_required
def api_create_folder():
    name = ((request.json or {}).get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    return jsonify({"id": db.create_folder(name), "name": name})


@app.route("/api/folders/<int:fid>", methods=["PUT"])
@login_required
def api_rename_folder(fid):
    name = ((request.json or {}).get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    db.rename_folder(fid, name)
    return jsonify({"ok": True})


@app.route("/api/folders/<int:fid>", methods=["DELETE"])
@login_required
def api_delete_folder(fid):
    db.delete_folder(fid)
    update_config(lambda c: c.__setitem__("default_folder_id", None)
                  if c.get("default_folder_id") == fid else None)
    return jsonify({"ok": True})


@app.route("/api/folders/default", methods=["POST"])
@login_required
def api_set_default_folder():
    fid = (request.json or {}).get("folder_id")
    if fid is not None and not db.get_folder(int(fid)):
        return jsonify({"error": "Notebook not found"}), 404
    update_config(lambda c: c.__setitem__("default_folder_id", int(fid) if fid is not None else None))
    return jsonify({"ok": True, "default_folder_id": fid})


# ------------------------------------------------------------------ search / tags
@app.route("/api/search")
@login_required
def api_search():
    q = request.args.get("q", "").strip()
    return jsonify([_list_item(n) for n in db.search_notes(q)] if q else [])


@app.route("/api/tags")
@login_required
def api_list_tags():
    return jsonify(db.get_tags())


# ------------------------------------------------------------------ import
@app.route("/api/import", methods=["POST"])
@login_required
def api_import_notes():
    folder_id = request.form.get("folder_id")
    try:
        folder_id = int(folder_id) if folder_id not in (None, "", "null", "all", "unfiled") else None
    except ValueError:
        folder_id = None
    if folder_id is None and request.form.get("folder_id") != "unfiled":
        folder_id = load_config().get("default_folder_id")

    imported, errors = 0, []
    token = logs.source.set("import")
    try:
        return _do_import(folder_id, imported, errors)
    finally:
        logs.source.reset(token)


def _do_import(folder_id, imported, errors):
    for file in request.files.getlist("files"):
        if not file or not file.filename:
            continue
        original = file.filename
        ext = os.path.splitext(secure_filename(original) or "x.txt")[1].lower()
        if ext not in (".txt", ".md", ".markdown"):
            errors.append(f"Skipped {original}: unsupported format")
            continue
        raw = file.read()
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw.decode("latin-1", errors="ignore")
        title = os.path.splitext(os.path.basename(original))[0].replace("_", " ").strip()
        if ext in (".md", ".markdown"):
            lines = content.split("\n")
            if lines and lines[0].strip().startswith("# "):
                title = lines[0].strip()[2:].strip()
                content = "\n".join(lines[1:]).strip()
        try:
            db.create_note(title or "Imported Note", content, folder_id)
            imported += 1
        except Exception as e:  # noqa
            logs.note("import failed", None, original, f"({type(e).__name__}: {e})")
            errors.append(f"Failed to save {original} (details in Settings → Logs → notes.log)")
    return jsonify({"imported": imported, "errors": errors})


# ------------------------------------------------------------------ weather cities
@app.route("/api/weather/cities", methods=["GET", "POST"])
@login_required
def api_weather_cities():
    if request.method == "POST":
        cities = (request.json or {}).get("cities", [])
        clean = []
        for c in cities[:12]:
            try:
                clean.append({"city": str(c["city"])[:120], "cc": str(c.get("cc", ""))[:4],
                              "country": str(c.get("country", ""))[:80], "tz": str(c.get("tz", "UTC"))[:64],
                              "lat": float(c["lat"]), "lon": float(c["lon"])})
            except (KeyError, TypeError, ValueError):
                continue
        update_config(lambda cfg: cfg.__setitem__("weather_cities", clean))
        return jsonify({"ok": True, "cities": clean})
    return jsonify(load_config().get("weather_cities", []))


# ------------------------------------------------------------------ cloud
def _check_provider(key):
    if key not in PROVIDER_KEYS:
        abort(404)


@app.route("/api/cloud/status")
@login_required
def api_cloud_status():
    return jsonify(_public_cloud(load_config()))


@app.route("/api/cloud/<key>/config", methods=["POST"])
@login_required
def api_cloud_config(key):
    _check_provider(key)
    data = request.json or {}
    reset = {"value": False}

    def mut(c):
        pc = c["cloud"][key]
        if "remote_folder" in data:
            folder = "/".join(p.strip() for p in str(data["remote_folder"]).replace("\\", "/").split("/") if p.strip())
            if folder != pc.get("remote_folder"):
                pc["remote_folder"] = folder
                pc["root_id"] = None
                reset["value"] = True
        if "enabled" in data:
            pc["enabled"] = bool(data["enabled"])
        if "sync_interval_minutes" in data:
            c["cloud"]["sync_interval_minutes"] = max(0, int(data["sync_interval_minutes"] or 0))
    update_config(mut)
    logs.connection(f"OneDrive settings saved: {', '.join(f'{k}={v}' for k, v in data.items())}")
    if reset["value"]:
        db.cloud_reset(key)
    return jsonify({"ok": True, "cloud": _public_cloud(load_config())})


@app.route("/api/cloud/<key>/connect", methods=["POST"])
@login_required
def api_cloud_connect(key):
    _check_provider(key)
    try:
        return jsonify(cloud.start_signin(key))
    except CloudError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/cloud/<key>/complete", methods=["POST"])
@login_required
def api_cloud_complete(key):
    """Sign-in started from another LAN device: forward the pasted localhost:53682 address to rclone."""
    _check_provider(key)
    url = ((request.json or {}).get("url") or "").strip()
    try:
        onedrive.complete_signin(url)
        return jsonify({"ok": True, "test": load_config()["cloud"]["onedrive"].get("last_test")})
    except CloudError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/cloud/<key>/test", methods=["POST"])
@login_required
def api_cloud_test(key):
    _check_provider(key)
    return jsonify(cloud.test_provider(key))


@app.route("/api/cloud/<key>/disconnect", methods=["POST"])
@login_required
def api_cloud_disconnect(key):
    _check_provider(key)
    cloud.disconnect(key)
    return jsonify({"ok": True})


@app.route("/api/cloud/<key>/reset", methods=["POST"])
@login_required
def api_cloud_reset(key):
    _check_provider(key)
    db.cloud_reset(key)
    db.log_sync(None, f"{key}:reset", "Sync links cleared; next sync re-matches notes by name")
    return jsonify({"ok": True})


@app.route("/api/cloud/<key>/sync", methods=["POST"])
@login_required
def api_cloud_sync(key):
    _check_provider(key)
    return jsonify(cloud.sync_provider(key, wait=True))


@app.route("/api/sync/all", methods=["POST"])
@login_required
def api_sync_all():
    return jsonify(cloud.sync_all())


@app.route("/api/sync/log")
@login_required
def api_sync_log():
    return jsonify(db.get_sync_log())


# ------------------------------------------------------------------ app settings
@app.route("/api/settings/app", methods=["POST"])
@login_required
def api_save_app_settings():
    data = request.json or {}

    def mut(c):
        if "autolock_minutes" in data:
            c["autolock_minutes"] = max(1, int(data["autolock_minutes"] or AUTOLOCK_MINUTES))
        if "backup_dir" in data and str(data["backup_dir"]).strip():
            c["backup_dir"] = str(data["backup_dir"]).strip()
        if "backup_max_copies" in data:
            c["backup_max_copies"] = min(100, max(1, int(data["backup_max_copies"] or 5)))
        if "default_folder_id" in data:
            v = data["default_folder_id"]
            c["default_folder_id"] = int(v) if v not in (None, "", "none") else None
        if "port" in data:
            c["port"] = int(data["port"])
        if "host" in data and str(data["host"]).strip():
            c["host"] = str(data["host"]).strip()
    try:
        update_config(mut)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid value"}), 400
    return jsonify({"ok": True})


# ------------------------------------------------------------------ local backups
@app.route("/api/backup", methods=["GET", "POST"])
@login_required
def api_backup():
    import PustakamBackup as backup
    if request.method == "POST":
        try:
            path = backup.create_backup()
        except Exception as e:  # noqa
            logs.backup(f"backup failed: {type(e).__name__}: {e}", "error")
            return jsonify({"error": "Backup failed. Check the backup folder in Settings, and Settings → Logs → backup.log."}), 500
        db.log_sync(None, "backup:create", path)
        return jsonify({"ok": True, "path": path, "folder": backup.backup_dir(), "backups": backup.list_backups()})
    return jsonify({"folder": backup.backup_dir(), "backups": backup.list_backups()})


# ------------------------------------------------------------------ log files
@app.route("/api/logs")
@login_required
def api_logs():
    from PustakamConfig import LOG_DIR as folder
    return jsonify({"folder": folder, "files": logs.list_logs()})


@app.route("/api/logs/<name>")
@login_required
def api_log_tail(name):
    try:
        lines = min(2000, max(20, request.args.get("lines", 300, type=int)))
        return jsonify({"name": name, "text": logs.tail(name, lines)})
    except (ValueError, FileNotFoundError):
        abort(404)


@app.route("/api/version")
def api_version():
    return jsonify({"version": VERSION, "app": APP_NAME})


# ------------------------------------------------------------------ main
def main():
    if sys.stdout is None or sys.stderr is None:   # pythonw.exe on Windows has no console
        log = open(os.path.join(LOG_DIR, "server.log"), "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    cfg = load_config()
    host, port = cfg.get("host", "0.0.0.0"), int(cfg.get("port", 5150))
    cloud.start_scheduler()
    print(f"{APP_NAME} ({APP_NAME_DEVANAGARI}) v{VERSION} listening on http://{host}:{port}", flush=True)
    logs.connection(f"server started: v{VERSION} on http://{host}:{port} as OS user '{auth.service_user()}'")
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8, ident=APP_NAME)
    except ImportError:
        app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
