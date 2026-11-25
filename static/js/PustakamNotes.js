/* Pustakam (पुस्तकम्) — notebooks, note list, reading view and split editor */
(() => {
    const S = {
        folders: [], tags: [], defaultFolderId: null,
        folder: 'all', tag: null, query: '',
        note: null, mode: 'view', dirty: false,
    };
    const $ = id => document.getElementById(id);
    let previewTimer = null, searchTimer = null;

    // ================================================================ sidebar
    function folderById(id) { return S.folders.find(f => f.id === id); }

    function renderFolders() {
        const list = $('folder-list');
        const total = S.folders.reduce((n, f) => n + (f.note_count || 0), 0);
        let html = `<li class="folder-item ${S.folder === 'all' && !S.tag ? 'active' : ''}" data-folder="all">
                ${PustakamFolderIcons.special('all')}<span class="folder-name">All Notes</span></li>`;
        for (const f of S.folders) {
            const isDef = f.id === S.defaultFolderId;
            html += `<li class="folder-item ${S.folder === f.id && !S.tag ? 'active' : ''}" data-folder="${f.id}" title="${P.esc(f.name)}${isDef ? ' (default)' : ''} — right-click for options">
                ${PustakamFolderIcons.html(f.name)}
                <span class="folder-name">${P.esc(f.name)}</span>
                ${isDef ? '<span class="default-star" title="Default notebook">★</span>' : ''}
                <span class="folder-count">${f.note_count || 0}</span>
                <button class="folder-more" data-more="${f.id}" title="Notebook options">⋯</button></li>`;
        }
        list.innerHTML = html;
        list.dataset.total = total;
        updateHeader();
    }

    function renderTags() {
        const el = $('tag-cloud');
        el.innerHTML = S.tags.length
            ? S.tags.map(t => `<span class="tag ${S.tag === t.name ? 'active' : ''}" data-tag="${P.esc(t.name)}">#${P.esc(t.name)}<small>${t.note_count}</small></span>`).join('')
            : '<span class="muted small">No tags yet</span>';
    }

    function updateHeader() {
        const icon = $('current-folder-icon'), name = $('current-folder-name');
        if (S.query) { icon.innerHTML = PustakamFolderIcons.special('tag').replace('#', '⌕'); name.textContent = `Search: ${S.query}`; return; }
        if (S.tag) { icon.innerHTML = PustakamFolderIcons.special('tag'); name.textContent = `#${S.tag}`; return; }
        if (S.folder === 'all') { icon.innerHTML = PustakamFolderIcons.special('all'); name.textContent = 'All Notes'; return; }
        const f = folderById(S.folder);
        icon.innerHTML = f ? PustakamFolderIcons.html(f.name) : '';
        name.textContent = f ? f.name : 'Notebook';
    }

    async function refreshSidebar() {
        const [fd, tags] = await Promise.all([P.api('/api/folders'), P.api('/api/tags')]);
        S.folders = fd.folders; S.defaultFolderId = fd.default_folder_id; S.tags = tags;
        if (S.folder !== 'all' && !folderById(S.folder)) S.folder = 'all';
        renderFolders(); renderTags();
    }

    function confirmDiscard() {
        return !S.dirty || confirm('You have unsaved changes. Discard them?');
    }

    function selectFolder(fid) {
        if (!confirmDiscard()) return;
        S.folder = fid; S.tag = null; S.query = ''; $('search-input').value = '';
        renderFolders(); renderTags(); loadNotes();
        document.dispatchEvent(new Event('pk:folder-selected'));
    }

    function selectTag(tag) {
        if (!confirmDiscard()) return;
        S.tag = S.tag === tag ? null : tag; S.query = ''; $('search-input').value = '';
        renderFolders(); renderTags(); loadNotes();
        document.dispatchEvent(new Event('pk:folder-selected'));
    }

    // ---- folder context menu
    function showFolderMenu(x, y, fid) {
        const f = folderById(fid);
        if (!f) return;
        const isDef = fid === S.defaultFolderId;
        const menu = $('context-menu');
        menu.innerHTML = `
            <div class="cm-title">${PustakamFolderIcons.html(f.name)} ${P.esc(f.name)}</div>
            <button data-act="open">📂 Open</button>
            <button data-act="default">${isDef ? '☆ Remove as default' : '★ Set as default notebook'}</button>
            <button data-act="rename">✏️ Rename</button>
            <hr><button data-act="delete" class="danger">🗑️ Delete notebook</button>`;
        menu.hidden = false;
        menu.style.left = `${Math.min(x, window.innerWidth - 240)}px`;
        menu.style.top = `${Math.min(y, window.innerHeight - 200)}px`;
        menu.onclick = async (e) => {
            const act = e.target.closest('button')?.dataset.act;
            if (!act) return;
            menu.hidden = true;
            if (act === 'open') selectFolder(fid);
            if (act === 'default') {
                await P.api('/api/folders/default', { method: 'POST', json: { folder_id: isDef ? null : fid } });
                P.toast(isDef ? 'Default notebook cleared' : `"${f.name}" is now the default notebook`, 'ok');
                await refreshSidebar();
            }
            if (act === 'rename') {
                const name = prompt('Rename notebook:', f.name);
                if (name && name.trim() && name.trim() !== f.name) {
                    await P.api(`/api/folders/${fid}`, { method: 'PUT', json: { name: name.trim() } });
                    await refreshSidebar(); updateHeader();
                }
            }
            if (act === 'delete') {
                if (!confirm(`Delete notebook "${f.name}"?\nIts ${f.note_count} note(s) are kept and moved to All Notes (unfiled).`)) return;
                await P.api(`/api/folders/${fid}`, { method: 'DELETE' });
                if (S.folder === fid) S.folder = 'all';
                await refreshSidebar(); loadNotes();
            }
        };
    }

    async function createFolder() {
        const name = prompt('New notebook name:');
        if (!name || !name.trim()) return;
        const r = await P.api('/api/folders', { method: 'POST', json: { name: name.trim() } });
        await refreshSidebar();
        selectFolder(r.id);
    }

    // ================================================================ note list
    function plainPreview(md) {
        return (md || '').replace(/```[\s\S]*?```/g, ' ').replace(/\$\$?|\\ce\{|\\[a-z]+/g, '')
            .replace(/[#>*_`~\[\]()|-]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 110);
    }

    async function loadNotes() {
        updateHeader();
        let notes;
        if (S.query) notes = await P.api(`/api/search?q=${encodeURIComponent(S.query)}`);
        else if (S.tag) notes = await P.api(`/api/notes?tag=${encodeURIComponent(S.tag)}`);
        else notes = await P.api(`/api/notes?folder_id=${S.folder}`);
        renderNoteList(notes);
    }

    function renderNoteList(notes) {
        const list = $('note-list');
        if (!notes.length) {
            list.innerHTML = `<div class="empty-list">${S.query ? 'No matches' : 'No notes here yet'}<br><small>Press <b>+ New</b> to start writing</small></div>`;
            return;
        }
        const showFolder = S.folder === 'all' || S.tag || S.query;
        list.innerHTML = notes.map(n => {
            const f = n.folder_id ? folderById(n.folder_id) : null;
            return `<div class="note-card ${S.note && n.id === S.note.id ? 'active' : ''}" data-id="${n.id}">
                <div class="note-card-title">${P.esc(n.title)}</div>
                <div class="note-card-preview">${P.esc(plainPreview(n.preview)) || '<i>Empty note</i>'}</div>
                <div class="note-card-meta">
                    <span>${P.formatTs(n.updated_at)}</span>
                    ${showFolder && f ? `<span class="note-card-folder">${PustakamFolderIcons.html(f.name, 'folder-icon-xs')}${P.esc(f.name)}</span>` : ''}
                </div></div>`;
        }).join('');
    }

    // ================================================================ note view / edit
    function fillFolderSelect() {
        const sel = $('note-folder');
        sel.innerHTML = '<option value="">— Unfiled —</option>' +
            S.folders.map(f => `<option value="${f.id}">${P.esc(f.name)}</option>`).join('');
        sel.value = S.note && S.note.folder_id ? String(S.note.folder_id) : '';
    }

    function renderTagChips() {
        const tags = (S.note?.tags || []).map(t => t.name);
        $('tag-chips').innerHTML = tags.length
            ? tags.map(t => `<span class="tag" data-tag="${P.esc(t)}">#${P.esc(t)}</span>`).join('')
            : '<span class="muted small">No tags</span>';
    }

    async function openNote(nid, mode = 'view') {
        if (S.note && S.note.id === nid && mode === S.mode) return;
        if (!confirmDiscard()) return;
        const note = await P.api(`/api/notes/${nid}`);
        S.note = note; S.dirty = false;
        $('editor-placeholder').hidden = true;
        $('note-shell').hidden = false;
        $('note-title').value = note.title;
        $('note-content').value = note.content || '';
        $('note-tags-input').value = (note.tags || []).map(t => t.name).join(', ');
        fillFolderSelect(); renderTagChips();
        setMode(mode, true);
        document.dispatchEvent(new Event('pk:note-opened'));
        document.querySelectorAll('.note-card').forEach(el => el.classList.toggle('active', +el.dataset.id === nid));
        setSaveState('');
    }

    function closeNote() {
        S.note = null; S.dirty = false;
        $('note-shell').hidden = true;
        $('editor-placeholder').hidden = false;
        document.dispatchEvent(new Event('pk:note-closed'));
    }

    function setMode(mode, force = false) {
        if (!S.note) return;
        if (mode === 'view' && S.dirty && !force) {
            if (!confirm('Discard unsaved changes and go back to reading view?')) return;
            $('note-title').value = S.note.title;
            $('note-content').value = S.note.content || '';
            $('note-tags-input').value = (S.note.tags || []).map(t => t.name).join(', ');
            S.dirty = false; setSaveState('');
        }
        S.mode = mode;
        const edit = mode === 'edit';
        const body = $('editor-body');
        body.classList.toggle('mode-edit', edit);
        body.classList.toggle('mode-view', !edit);
        $('note-title').readOnly = !edit;
        $('note-folder').disabled = !edit;
        $('edit-btn').hidden = edit;
        $('view-btn').hidden = !edit;
        $('save-btn').hidden = !edit;
        $('md-toolbar').hidden = !edit;
        $('note-tags-input').hidden = !edit;
        $('tag-chips').hidden = edit;
        PustakamMarkdown.render($('note-preview'), $('note-content').value);
        if (edit) {
            const ta = $('note-content');
            setTimeout(() => { ta.focus(); if (!force) return; ta.setSelectionRange(ta.value.length, ta.value.length); }, 0);
        } else {
            $('note-preview').scrollTop = 0;
        }
    }

    function markDirty() {
        if (!S.dirty) { S.dirty = true; setSaveState('● Unsaved'); }
        clearTimeout(previewTimer);
        previewTimer = setTimeout(() => PustakamMarkdown.render($('note-preview'), $('note-content').value), 120);
    }

    function setSaveState(t) { $('save-state').textContent = t; $('save-state').classList.toggle('dirty', t.startsWith('●')); }

    async function saveNote({ thenView = false } = {}) {
        if (!S.note) return;
        const title = $('note-title').value.trim() || 'Untitled';
        const content = $('note-content').value;
        const tags = $('note-tags-input').value.split(',').map(t => t.trim()).filter(Boolean);
        const folderVal = $('note-folder').value;
        const folder_id = folderVal ? +folderVal : null;
        try {
            await P.api(`/api/notes/${S.note.id}`, { method: 'PUT', json: { title, content, tags, folder_id } });
        } catch (e) { P.toast(`Save failed: ${e.message}`, 'error'); return; }
        S.note = Object.assign(S.note, { title, content, folder_id, tags: tags.map(name => ({ name })) });
        S.dirty = false;
        $('note-title').value = title;
        setSaveState(`Saved ${new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`);
        renderTagChips();
        setStatus('💾 Saved', 'ok');
        await refreshSidebar();
        loadNotes();
        if (thenView) setMode('view', true);
    }

    async function deleteNote() {
        if (!S.note) return;
        if (!confirm(`Delete "${S.note.title}"?${PB.cloud_active.length ? '\nIt is also moved to the trash of your connected cloud drive on next sync.' : ''}`)) return;
        await P.api(`/api/notes/${S.note.id}`, { method: 'DELETE' });
        S.dirty = false;
        closeNote();
        await refreshSidebar();
        loadNotes();
        P.toast('Note deleted', 'ok');
    }

    async function createNote() {
        if (!confirmDiscard()) return;
        S.dirty = false;
        const folder_id = S.folder === 'all' ? null : S.folder;
        const r = await P.api('/api/notes', { method: 'POST', json: { title: 'New Note', content: '', folder_id } });
        if (S.folder === 'all' || S.folder === r.folder_id) { /* stays visible */ }
        else if (r.folder_id) S.folder = r.folder_id;
        S.tag = null; S.query = ''; $('search-input').value = '';
        await refreshSidebar();
        await loadNotes();
        await openNote(r.id, 'edit');
        const t = $('note-title'); t.focus(); t.select();
    }

    // ---- markdown toolbar
    function surround(before, after = before, placeholder = 'text') {
        const ta = $('note-content');
        const s = ta.selectionStart, e = ta.selectionEnd;
        const sel = ta.value.slice(s, e) || placeholder;
        ta.setRangeText(before + sel + after, s, e, 'select');
        ta.selectionStart = s + before.length; ta.selectionEnd = s + before.length + sel.length;
        ta.focus(); markDirty();
    }

    function insertBlock(text, cursorOffset = null) {
        const ta = $('note-content');
        const s = ta.selectionStart;
        const prefix = s > 0 && ta.value[s - 1] !== '\n' ? '\n' : '';
        ta.setRangeText(prefix + text, s, ta.selectionEnd, 'end');
        if (cursorOffset !== null) { const p = s + prefix.length + cursorOffset; ta.setSelectionRange(p, p); }
        ta.focus(); markDirty();
    }

    const TOOLBAR = {
        bold: () => surround('**'), italic: () => surround('*'),
        h2: () => insertBlock('## ', 3), ul: () => insertBlock('- ', 2), task: () => insertBlock('- [ ] ', 6),
        code: () => insertBlock('```\n\n```\n', 4), link: () => surround('[', '](https://)', 'link text'),
        table: () => insertBlock('| Column A | Column B |\n|---|---|\n| 1 | 2 |\n'),
        math: () => surround('$', '$', 'E = mc^2'),
        mathblock: () => insertBlock('$$\n\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}\n$$\n'),
        chem: () => surround('$\\ce{', '}$', 'H2SO4'),
        reaction: () => surround('$\\ce{', '}$', 'N2 + 3H2 <=> 2NH3'),
    };

    // ---- scroll sync between editor and preview
    let syncing = false;
    function syncScroll(from, to) {
        if (syncing || S.mode !== 'edit') return;
        syncing = true;
        const ratio = from.scrollTop / Math.max(1, from.scrollHeight - from.clientHeight);
        to.scrollTop = ratio * (to.scrollHeight - to.clientHeight);
        requestAnimationFrame(() => { syncing = false; });
    }

    // ================================================================ status / sync
    function setStatus(msg, kind = 'idle') {
        $('sync-status').textContent = msg;
        $('sync-dot').className = `sync-dot ${kind}`;
    }

    async function syncNow() {
        const btn = $('sync-btn');
        if (btn.classList.contains('spinning')) return;
        btn.classList.add('spinning');
        setStatus('Syncing with cloud…', 'busy');
        try {
            const r = await P.api('/api/sync/all', { method: 'POST' });
            if (!r.results || !Object.keys(r.results).length) {
                setStatus(r.error || 'No cloud drive connected', 'warn');
                P.toast('Sign in to OneDrive in Settings to sync', 'warn');
                return;
            }
            const parts = [];
            let changed = false, failed = [];
            for (const [k, res] of Object.entries(r.results)) {
                const name = 'OneDrive';
                if (res.error) { failed.push(`${name}: ${res.error}`); continue; }
                const st = res.stats;
                parts.push(`${name} ↑${st.uploaded} ↓${st.downloaded}${st.conflicts ? ` ⚠${st.conflicts}` : ''}${st.errors ? ` ✕${st.errors}` : ''}`);
                if (st.downloaded || st.deleted_local || st.folders || st.conflicts) changed = true;
            }
            if (failed.length) { setStatus(failed.join(' · '), 'error'); P.toast(failed[0], 'error'); }
            else setStatus(`Synced ${new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })} — ${parts.join(' · ')}`, 'ok');
            if (changed) {
                await refreshSidebar(); await loadNotes();
                if (S.note && !S.dirty) {
                    try { const n = await P.api(`/api/notes/${S.note.id}`); S.note = null; await openNote(n.id, S.mode); }
                    catch (e) { closeNote(); }
                }
            }
        } catch (e) {
            setStatus(`Sync failed: ${e.message}`, 'error');
        } finally {
            btn.classList.remove('spinning');
        }
    }

    // ================================================================ import
    async function importFiles(ev) {
        const files = ev.target.files;
        if (!files || !files.length) return;
        const fd = new FormData();
        for (const f of files) fd.append('files', f);
        fd.append('folder_id', S.folder === 'all' ? '' : S.folder);
        setStatus('📥 Importing…', 'busy');
        try {
            const d = await P.api('/api/import', { method: 'POST', body: fd });
            setStatus(d.imported ? `✅ Imported ${d.imported} note(s)` : 'No notes imported', d.imported ? 'ok' : 'warn');
            if (d.errors?.length) alert('Import finished with warnings:\n\n' + d.errors.join('\n'));
            await refreshSidebar(); loadNotes();
        } catch (e) { setStatus('Import failed', 'error'); }
        finally { ev.target.value = ''; }
    }

    // ================================================================ wiring
    let PB;
    function init() {
        PB = P.boot();
        S.folders = PB.folders || []; S.tags = PB.tags || []; S.defaultFolderId = PB.default_folder_id;
        if (S.defaultFolderId && folderById(S.defaultFolderId)) S.folder = S.defaultFolderId;
        renderFolders(); renderTags(); loadNotes();
        PustakamWeather.init(PB.weather_cities);
        P.startSessionWatch();
        setStatus(PB.cloud_active.length ? `Cloud sync: ${'OneDrive'}` : 'Local only — sign in to OneDrive in Settings to sync', PB.cloud_active.length ? 'ok' : 'idle');

        $('folder-list').addEventListener('click', e => {
            const more = e.target.closest('[data-more]');
            if (more) { e.stopPropagation(); const r = more.getBoundingClientRect(); showFolderMenu(r.right, r.bottom, +more.dataset.more); return; }
            const li = e.target.closest('.folder-item');
            if (li) selectFolder(li.dataset.folder === 'all' ? 'all' : +li.dataset.folder);
        });
        $('folder-list').addEventListener('contextmenu', e => {
            const li = e.target.closest('.folder-item');
            if (!li || li.dataset.folder === 'all') return;
            e.preventDefault(); showFolderMenu(e.clientX, e.clientY, +li.dataset.folder);
        });
        document.addEventListener('click', e => { if (!e.target.closest('#context-menu')) $('context-menu').hidden = true; });

        $('tag-cloud').addEventListener('click', e => { const t = e.target.closest('[data-tag]'); if (t) selectTag(t.dataset.tag); });
        $('tag-chips').addEventListener('click', e => { const t = e.target.closest('[data-tag]'); if (t) selectTag(t.dataset.tag); });
        $('note-list').addEventListener('click', e => { const c = e.target.closest('.note-card'); if (c) openNote(+c.dataset.id, 'view'); });
        $('note-preview').addEventListener('dblclick', () => { if (S.mode === 'view') setMode('edit'); });

        $('new-folder-btn').addEventListener('click', createFolder);
        $('new-note-btn').addEventListener('click', createNote);
        $('import-btn').addEventListener('click', () => $('import-file-input').click());
        $('import-file-input').addEventListener('change', importFiles);
        $('edit-btn').addEventListener('click', () => setMode('edit'));
        $('view-btn').addEventListener('click', () => setMode('view'));
        $('save-btn').addEventListener('click', () => saveNote());
        $('delete-btn').addEventListener('click', deleteNote);
        $('sync-btn').addEventListener('click', syncNow);
        $('logout-btn').addEventListener('click', e => { if (S.dirty && !confirm('You have unsaved changes. Log out anyway?')) e.preventDefault(); else S.dirty = false; });

        $('note-content').addEventListener('input', markDirty);
        $('note-title').addEventListener('input', () => { if (S.mode === 'edit') markDirty(); });
        $('note-tags-input').addEventListener('input', markDirty);
        $('note-folder').addEventListener('change', markDirty);
        $('note-content').addEventListener('scroll', () => syncScroll($('note-content'), $('note-preview')));
        $('note-content').addEventListener('keydown', e => {
            if (e.key === 'Tab') { e.preventDefault(); $('note-content').setRangeText('    ', $('note-content').selectionStart, $('note-content').selectionEnd, 'end'); markDirty(); }
        });
        $('md-toolbar').addEventListener('click', e => { const b = e.target.closest('[data-md]'); if (b) TOOLBAR[b.dataset.md](); });

        $('search-input').addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                S.query = $('search-input').value.trim();
                if (S.query) S.tag = null;
                renderFolders(); renderTags(); loadNotes();
            }, 250);
        });

        document.addEventListener('keydown', e => {
            const inField = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (S.mode === 'edit') saveNote(); }
            else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && S.mode === 'edit') { e.preventDefault(); saveNote({ thenView: true }); }
            else if (e.altKey && e.key.toLowerCase() === 'n') { e.preventDefault(); createNote(); }
            else if (e.key === 'Escape' && S.mode === 'edit' && !$('wx-search').matches(':focus')) { setMode('view'); }
            else if (!inField && e.key.toLowerCase() === 'e' && S.note && S.mode === 'view' && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); setMode('edit'); }
        });
        window.addEventListener('beforeunload', e => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });
    }

    document.addEventListener('DOMContentLoaded', init);
})();
