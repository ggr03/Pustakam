/* Pustakam (पुस्तकम्) — Settings page: OneDrive sync, local backup, app options */
(() => {
    const $ = id => document.getElementById(id);
    const PROVIDER = 'onedrive';
    let cloud = {};
    let pollTimer = null;

    function fmtBytes(n) {
        if (!n) return '0 B';
        const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return `${n.toFixed(i > 1 ? 1 : 0)} ${u[i]}`;
    }

    function msg(el, text, kind) {
        el.textContent = text;
        el.className = `status-msg ${kind || 'info'}`;
        el.style.display = text ? 'block' : 'none';
    }

    const card = () => $('card-onedrive');
    const q = sel => card().querySelector(sel);
    const status = () => q('[data-role=status]');

    // ---------------------------------------------------------------- OneDrive
    function renderChecks(test) {
        const ul = q('[data-role=checks]');
        if (!test) { ul.innerHTML = ''; return; }
        ul.innerHTML = (test.checks || []).map(c => `<li class="ok">${P.esc(c)}</li>`).join('') +
            (test.error ? `<li class="bad">${P.esc(test.error)}</li>` : '') +
            (test.time ? `<li class="meta">Tested ${P.esc(P.relTime(test.time))}</li>` : '');
    }

    function render() {
        const p = cloud[PROVIDER];
        const pill = q('[data-role=pill]');
        if (p.connected) {
            const a = p.account || {};
            const who = a.email || a.name;
            const quota = a.quota_total ? ` · ${fmtBytes(a.quota_used)} of ${fmtBytes(a.quota_total)} used` : '';
            pill.innerHTML = `<span class="dot ok"></span>Connected${who ? ` as <b>${P.esc(who)}</b>` : ''}${quota}`;
        } else {
            pill.innerHTML = '<span class="dot"></span>Not connected';
        }
        ['test', 'sync', 'disconnect'].forEach(a => { q(`[data-action=${a}]`).disabled = !p.connected; });
        q('[data-action=connect]').textContent = p.connected ? '🔄 Sign in again' : '🔑 Sign in with Microsoft';
        q('[data-action=connect]').disabled = !(p.rclone && p.rclone.found);
        q('[data-action=reset]').hidden = !p.connected;
        q('[data-field=enabled]').checked = !!p.enabled;
        renderChecks(p.last_test);
        const ls = q('[data-role=last-sync]');
        const r = p.last_result;
        if (p.last_sync && r) {
            ls.innerHTML = r.error
                ? `<span class="bad">Last sync ${P.esc(P.relTime(p.last_sync))} failed: ${P.esc(r.error)}</span>`
                : `Last sync ${P.esc(P.relTime(p.last_sync))}: ↑ ${r.stats.uploaded} up · ↓ ${r.stats.downloaded} down · 🗑 ${r.stats.deleted_local + r.stats.deleted_remote} removed · ⚠ ${r.stats.conflicts} conflicts${r.stats.errors ? ` · ✕ ${r.stats.errors} errors` : ''}`;
        } else ls.textContent = p.connected && !p.enabled ? 'Connected. Turn on the switch (top right) to start syncing.' : '';
        card().classList.toggle('is-connected', p.connected);
        card().classList.toggle('is-enabled', !!p.enabled);
    }

    async function refresh() {
        cloud = await P.api('/api/cloud/status');
        render();
        loadLog();
    }

    async function save(quiet = false) {
        const folder = q('[data-field=remote_folder]').value.trim();
        const enabled = q('[data-field=enabled]').checked;
        if (enabled && !folder) {
            msg(status(), 'Tell Pustakam where to keep your notebooks in OneDrive first.', 'error');
            q('[data-field=remote_folder]').focus();
            return false;
        }
        const prev = cloud[PROVIDER].remote_folder;
        if (prev && folder && prev !== folder &&
            !confirm(`Change the OneDrive folder from "${prev}" to "${folder}"?\nNotes will be linked again to the new folder on the next sync. Nothing is deleted.`)) {
            q('[data-field=remote_folder]').value = prev;
            return false;
        }
        try {
            const r = await P.api(`/api/cloud/${PROVIDER}/config`, { method: 'POST', json: { remote_folder: folder, enabled } });
            cloud = r.cloud; render();
            if (!quiet) msg(status(), '✅ Saved', 'success');
            return true;
        } catch (e) { msg(status(), `❌ ${e.message}`, 'error'); return false; }
    }

    async function connect() {
        const folderEl = q('[data-field=remote_folder]');
        if (!folderEl.value.trim()) {
            const ans = prompt('Where should Pustakam keep your notebooks in OneDrive?\n(A folder path from the top of your OneDrive; it will be created if missing)', 'Pustakam');
            if (!ans || !ans.trim()) { msg(status(), 'A OneDrive folder is needed before signing in.', 'error'); folderEl.focus(); return; }
            folderEl.value = ans.trim();
        }
        if (!(await save(true))) return;
        msg(status(), 'Starting Microsoft sign-in…', 'info');
        const win = window.open('about:blank', '_blank');   // open now so pop-up blockers allow it
        try {
            const r = await P.api(`/api/cloud/${PROVIDER}/connect`, { method: 'POST' });
            if (win) { win.location.href = r.auth_url; msg(status(), 'Waiting for you to approve access in the Microsoft tab…', 'info'); }
            else { msg(status(), 'Pop-up blocked. Open this link to sign in:', 'error'); status().insertAdjacentHTML('beforeend', ` <a href="${P.esc(r.auth_url)}" target="_blank" rel="noopener">Sign in with Microsoft</a>`); }
            q('[data-role=paste]').hidden = false;
            waitForConnection(cloud[PROVIDER].last_test?.time || 0);
        } catch (e) {
            if (win) win.close();
            msg(status(), `❌ ${e.message}`, 'error');
        }
    }

    function waitForConnection(since) {
        clearInterval(pollTimer);
        const started = Date.now();
        pollTimer = setInterval(async () => {
            if (Date.now() - started > 15 * 60 * 1000) { clearInterval(pollTimer); return; }
            const c = await P.api('/api/cloud/status');
            const p = c[PROVIDER];
            if (p.signin && p.signin.state === 'error') {
                clearInterval(pollTimer);
                msg(status(), `❌ ${p.signin.error}`, 'error');
                return;
            }
            if (p.connected && p.last_test && p.last_test.time > since) {
                clearInterval(pollTimer);
                cloud = c; render();
                q('[data-role=paste]').hidden = true;
                onTested(p.last_test);
            }
        }, 2000);
    }

    function onTested(t) {
        if (t.ok) {
            msg(status(), '✅ OneDrive connected and tested. Two-way sync is on. Press "Sync now" to start right away.', 'success');
            if (!cloud[PROVIDER].enabled) { q('[data-field=enabled]').checked = true; save(true); }
        } else if (t.needs_folder) {
            msg(status(), 'Connected. Now tell Pustakam where to keep your notebooks in OneDrive, Save, and Test.', 'error');
            q('[data-field=remote_folder]').focus();
        } else {
            msg(status(), `❌ Connected, but the test failed: ${t.error || 'unknown error'}`, 'error');
        }
    }

    async function complete() {
        const url = q('[data-role=paste-url]').value.trim();
        if (!url) return;
        msg(status(), 'Finishing sign-in…', 'info');
        try {
            const r = await P.api(`/api/cloud/${PROVIDER}/complete`, { method: 'POST', json: { url } });
            clearInterval(pollTimer);
            q('[data-role=paste]').hidden = true;
            await refresh();
            if (r.test) onTested(r.test);
        } catch (e) { msg(status(), `❌ ${e.message}`, 'error'); }
    }

    async function test() {
        if (!(await save(true))) return;
        msg(status(), 'Testing OneDrive…', 'info');
        const t = await P.api(`/api/cloud/${PROVIDER}/test`, { method: 'POST' });
        await refresh();
        onTested(t);
    }

    async function syncNow() {
        if (!(await save(true))) return;
        msg(status(), 'Syncing with OneDrive…', 'info');
        const r = await P.api(`/api/cloud/${PROVIDER}/sync`, { method: 'POST' });
        await refresh();
        if (r.error) msg(status(), `❌ ${r.error}`, 'error');
        else msg(status(), `✅ Sync done: ↑${r.stats.uploaded} ↓${r.stats.downloaded}, ${r.stats.conflicts} conflict(s), ${r.stats.errors} error(s)`, r.ok ? 'success' : 'error');
    }

    async function disconnect() {
        if (!confirm('Disconnect OneDrive?\nYour notes stay on this computer and in OneDrive; they just stop syncing.')) return;
        await P.api(`/api/cloud/${PROVIDER}/disconnect`, { method: 'POST' });
        await refresh();
        msg(status(), 'Disconnected.', 'success');
    }

    async function resetLink() {
        if (!confirm('Reset the OneDrive link?\nOn the next sync Pustakam matches notes and files by name again. Identical notes are linked, others are copied both ways. Nothing is deleted.')) return;
        await P.api(`/api/cloud/${PROVIDER}/reset`, { method: 'POST' });
        msg(status(), 'Link reset. Press "Sync now".', 'success');
        loadLog();
    }

    // ---------------------------------------------------------------- activity log
    async function loadLog() {
        const el = $('sync-log');
        const logs = await P.api('/api/sync/log');
        const label = { onedrive: 'OneDrive', backup: 'Backup' };
        el.innerHTML = logs.length ? logs.map(l => {
            const [prov, act] = (l.action || '').split(':');
            const cls = /error|conflict/.test(act || prov) ? 'bad' : '';
            return `<div class="sync-log-entry ${cls}"><span class="t">${P.formatTs(l.timestamp)}</span><span class="p">${P.esc(label[prov] || prov)}</span><span class="a">${P.esc(act || '')}</span> ${P.esc(l.details || '')}</div>`;
        }).join('') : '<div class="sync-log-entry">No activity yet</div>';
    }

    // ---------------------------------------------------------------- local backup
    function renderBackups(d) {
        const el = $('backup-list');
        el.innerHTML = d.backups.length
            ? d.backups.map(b => `<div class="backup-row"><span class="b-name">📦 ${P.esc(b.name)}</span><span class="b-meta">${P.formatTs(b.time)} · ${fmtBytes(b.size)}</span></div>`).join('')
              + `<div class="muted small b-folder">in ${P.esc(d.folder)}</div>`
            : `<div class="muted small">No backups yet in ${P.esc(d.folder)}</div>`;
    }

    async function loadBackups() {
        try { renderBackups(await P.api('/api/backup')); }
        catch (e) { $('backup-list').textContent = e.message; }
    }

    async function saveBackupSettings(quiet = false) {
        try {
            await P.api('/api/settings/app', { method: 'POST', json: {
                backup_dir: $('backup-dir').value, backup_max_copies: +$('backup-keep').value || 5 } });
            if (!quiet) msg($('backup-status'), '✅ Saved', 'success');
            await loadBackups();
            return true;
        } catch (e) { msg($('backup-status'), `❌ ${e.message}`, 'error'); return false; }
    }

    async function backupNow() {
        if (!(await saveBackupSettings(true))) return;
        const btn = $('backup-now'); btn.disabled = true;
        msg($('backup-status'), 'Creating backup…', 'info');
        try {
            const r = await P.api('/api/backup', { method: 'POST' });
            msg($('backup-status'), `✅ Backup saved: ${r.path}`, 'success');
            renderBackups(r); loadLog();
        } catch (e) { msg($('backup-status'), `❌ ${e.message}`, 'error'); }
        finally { btn.disabled = false; }
    }

    // ---------------------------------------------------------------- log files
    const LOG_LABEL = { 'connection.log': '🔌 Connections', 'sync.log': '⟳ Sync', 'notes.log': '📝 Notes', 'backup.log': '💾 Backup', 'server.log': '🖥️ Server' };
    async function loadLogs() {
        try {
            const d = await P.api('/api/logs');
            $('logs-folder').textContent = d.folder;
            const main = d.files.filter(f => /\.log$/.test(f.name));
            const old = d.files.length - main.length;
            $('log-files').innerHTML = main.length
                ? main.map(f => `<button class="btn btn-sm log-btn" data-log="${P.esc(f.name)}" title="${P.esc(f.name)} · ${fmtBytes(f.size)} · ${P.formatTs(f.time)}">${P.esc(LOG_LABEL[f.name] || f.name)} <small>${fmtBytes(f.size)}</small></button>`).join('')
                  + (old ? `<span class="muted small">+ ${old} rotated file(s)</span>` : '')
                : '<span class="muted small">No log entries yet</span>';
        } catch (e) { $('log-files').textContent = e.message; }
    }
    async function showLog(name) {
        const view = $('log-view');
        document.querySelectorAll('.log-btn').forEach(b => b.classList.toggle('btn-primary', b.dataset.log === name));
        try {
            const d = await P.api(`/api/logs/${encodeURIComponent(name)}?lines=400`);
            view.textContent = d.text || '(empty)';
            view.hidden = false;
            view.scrollTop = view.scrollHeight;
        } catch (e) { view.textContent = e.message; view.hidden = false; }
    }

    // ---------------------------------------------------------------- app settings
    async function postApp(statusId, json) {
        try { await P.api('/api/settings/app', { method: 'POST', json }); msg($(statusId), '✅ Saved', 'success'); }
        catch (e) { msg($(statusId), `❌ ${e.message}`, 'error'); }
    }

    function init() {
        cloud = P.boot();
        render();
        card().addEventListener('click', e => {
            const a = e.target.closest('[data-action]')?.dataset.action;
            if (!a) return;
            ({ save: () => save(), connect, complete, test, sync: syncNow, disconnect, reset: resetLink })[a]?.();
        });
        q('[data-field=enabled]').addEventListener('change', () => save());
        loadLog(); loadBackups(); loadLogs();
        $('log-files').addEventListener('click', e => { const b = e.target.closest('[data-log]'); if (b) showLog(b.dataset.log); });
        P.startSessionWatch();

        $('save-interval').addEventListener('click', async () => {
            try {
                await P.api(`/api/cloud/${PROVIDER}/config`, { method: 'POST', json: { sync_interval_minutes: +$('sync-interval').value || 0 } });
                msg($('interval-status'), '✅ Saved', 'success');
            } catch (e) { msg($('interval-status'), `❌ ${e.message}`, 'error'); }
        });
        $('save-backup').addEventListener('click', () => saveBackupSettings());
        $('backup-now').addEventListener('click', backupNow);
        $('save-app').addEventListener('click', () => postApp('app-status', {
            default_folder_id: $('default-folder').value,
            autolock_minutes: +$('autolock-minutes').value,
        }));
        $('save-server').addEventListener('click', () => postApp('server-status', {
            host: $('srv-host').value, port: +$('srv-port').value,
        }));
    }

    document.addEventListener('DOMContentLoaded', init);
})();
