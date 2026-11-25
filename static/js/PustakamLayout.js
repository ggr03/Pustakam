/*
 * Pustakam (पुस्तकम्) — layout: collapsible notebooks pane (desktop) and
 * slide-in drawers for notebooks and notes (phones/tablets in portrait).
 *
 * Desktop : ‹ / › arrow collapses the notebooks pane to icons (remembered).
 * Mobile  : 📚 opens notebooks, ☰ opens the note list; opening a note closes both,
 *           so the note gets the whole screen. Tap the dimmed area, press Esc,
 *           or swipe left to close; swipe right from the left edge to open.
 * Works with Chrome/Edge/Firefox/Samsung Internet on Android and Safari/Chrome/
 * Firefox on iPhone/iPad (uses only standard pointer/touch events).
 */
const PustakamLayout = (() => {
    const MOBILE = '(max-width: 760px)';
    const STORE = 'pustakam.sidebarCollapsed';
    const mq = window.matchMedia(MOBILE);
    const body = document.body;
    const $ = id => document.getElementById(id);
    let open = null;   // 'folders' | 'notes' | null (mobile only)

    const isMobile = () => mq.matches;

    function store(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* private mode */ } }
    function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

    // ------------------------------------------------------------ desktop collapse
    function setCollapsed(collapsed, persist = true) {
        body.classList.toggle('sidebar-collapsed', collapsed);
        const btn = $('sidebar-collapse');
        btn.setAttribute('aria-expanded', String(!collapsed));
        btn.title = collapsed ? 'Expand notebooks' : 'Collapse notebooks';
        btn.setAttribute('aria-label', btn.title);
        btn.querySelector('.chev').textContent = collapsed ? '›' : '‹';
        if (persist) store(STORE, collapsed ? '1' : '0');
    }

    // ------------------------------------------------------------ mobile drawers
    function openPane(which) {
        open = isMobile() ? which : null;
        body.classList.toggle('m-folders-open', open === 'folders');
        body.classList.toggle('m-notes-open', open === 'notes');
        $('pane-backdrop').hidden = !open;
        $('m-toggle-folders').setAttribute('aria-expanded', String(open === 'folders'));
        $('m-toggle-notes').setAttribute('aria-expanded', String(open === 'notes'));
        // keep focus/scroll inside the editor from leaking behind an open drawer
        $('editor-panel').toggleAttribute('inert', !!open);
    }

    function toggle(which) { openPane(open === which ? null : which); }

    function hasNote() { return !$('note-shell').hidden; }

    function onModeChange() {
        if (isMobile()) {
            body.classList.remove('sidebar-collapsed');
            openPane(hasNote() ? null : 'notes');
        } else {
            openPane(null);
            setCollapsed(recall(STORE) === '1', false);
        }
    }

    // ------------------------------------------------------------ swipe gestures
    function initSwipe() {
        let sx = 0, sy = 0, st = 0, tracking = false;
        document.addEventListener('touchstart', e => {
            if (!isMobile() || e.touches.length !== 1) return;
            const t = e.touches[0];
            sx = t.clientX; sy = t.clientY; st = Date.now();
            // only from the left edge (to open) or anywhere when a drawer is open (to close)
            tracking = !!open || sx < 24;
        }, { passive: true });
        document.addEventListener('touchend', e => {
            if (!tracking) return;
            tracking = false;
            const t = e.changedTouches[0];
            const dx = t.clientX - sx, dy = t.clientY - sy;
            if (Date.now() - st > 600 || Math.abs(dx) < 60 || Math.abs(dy) > Math.abs(dx) * 0.7) return;
            if (dx > 0 && !open) openPane('folders');
            else if (dx > 0 && open === 'folders') openPane('notes');
            else if (dx < 0 && open === 'notes') openPane(null);
            else if (dx < 0 && open === 'folders') openPane(null);
        }, { passive: true });
    }

    // ------------------------------------------------------------ account menu
    function initAccountMenu() {
        const btn = $('acct-btn'), menu = $('acct-menu');
        const items = () => [...menu.querySelectorAll('[role=menuitem]')];
        const setOpen = (on, focusFirst = false) => {
            menu.hidden = !on;
            btn.setAttribute('aria-expanded', String(on));
            btn.classList.toggle('open', on);
            if (on && focusFirst) items()[0]?.focus();
        };
        btn.addEventListener('click', e => { e.stopPropagation(); setOpen(menu.hidden, e.detail === 0); });
        document.addEventListener('click', e => { if (!menu.hidden && !menu.contains(e.target)) setOpen(false); });
        menu.addEventListener('keydown', e => {
            const list = items(), i = list.indexOf(document.activeElement);
            if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length].focus(); }
            if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
            if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); btn.focus(); }
        });
        $('sync-btn').addEventListener('click', () => setOpen(false));
        let lastW = window.innerWidth;   // ignore height-only resizes (mobile address bar)
        window.addEventListener('resize', () => { if (window.innerWidth !== lastW) { lastW = window.innerWidth; setOpen(false); } });
    }

    function init() {
        initAccountMenu();
        $('sidebar-collapse').addEventListener('click', () => setCollapsed(!body.classList.contains('sidebar-collapsed')));
        $('m-toggle-folders').addEventListener('click', () => toggle('folders'));
        $('m-toggle-notes').addEventListener('click', () => toggle('notes'));
        $('m-new-note').addEventListener('click', () => $('new-note-btn').click());
        $('pane-backdrop').addEventListener('click', () => openPane(null));
        document.addEventListener('keydown', e => { if (e.key === 'Escape' && open) { openPane(null); e.stopPropagation(); } }, true);

        // events sent by PustakamNotes.js
        document.addEventListener('pk:folder-selected', () => { if (isMobile()) openPane('notes'); });
        document.addEventListener('pk:note-opened', () => { if (isMobile()) openPane(null); });
        document.addEventListener('pk:note-closed', () => { if (isMobile()) openPane('notes'); });
        $('search-input').addEventListener('focus', () => { if (isMobile()) openPane('notes'); });

        if (mq.addEventListener) mq.addEventListener('change', onModeChange);
        else mq.addListener(onModeChange);   // older Safari (iOS 13)
        initSwipe();
        onModeChange();
        requestAnimationFrame(() => body.classList.add('layout-ready'));   // enable transitions after first paint
    }

    document.addEventListener('DOMContentLoaded', init);
    return { isMobile, openPane };
})();
