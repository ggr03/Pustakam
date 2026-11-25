/* Pustakam (पुस्तकम्) — shared helpers */
const P = (() => {
    async function api(url, opts = {}) {
        const init = { method: opts.method || 'GET', headers: {} };
        if (opts.json !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(opts.json);
        } else if (opts.body) {
            init.body = opts.body;
        }
        const res = await fetch(url, init);
        if (res.status === 401) { window.location.href = '/login'; throw new Error('Signed out'); }
        let data = null;
        try { data = await res.json(); } catch (e) { /* not json */ }
        if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
        return data;
    }

    function esc(text) {
        return String(text ?? '').replace(/[&<>"']/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    }

    function isoDate(d = new Date()) {
        const p = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    }

    function formatTs(ts) {
        if (!ts) return '';
        const d = new Date(ts < 1e12 ? ts * 1000 : ts);
        const p = n => String(n).padStart(2, '0');
        return `${isoDate(d)} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    function relTime(ts) {
        if (!ts) return 'never';
        const s = Math.round(Date.now() / 1000 - ts);
        if (s < 60) return 'just now';
        if (s < 3600) return `${Math.floor(s / 60)} min ago`;
        if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
        return formatTs(ts);
    }

    let toastTimer;
    function toast(msg, kind = 'info') {
        const el = document.getElementById('toast');
        if (!el) return;
        el.textContent = msg;
        el.className = `toast toast-${kind}`;
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
    }

    function boot() {
        const el = document.getElementById('boot-data');
        return el ? JSON.parse(el.textContent) : {};
    }

    // Inactivity logout: ping on activity (throttled), poll session.
    function startSessionWatch() {
        let last = 0;
        const ping = () => {
            if (Date.now() - last > 60000) { last = Date.now(); fetch('/api/ping', { method: 'POST' }); }
        };
        ['click', 'keydown'].forEach(ev => document.addEventListener(ev, ping, { passive: true }));
        setInterval(async () => {
            try {
                const r = await fetch('/api/check-session');
                const d = await r.json();
                if (!d.valid) {
                    if (d.expired) alert('You were logged out after a period of inactivity.');
                    window.location.href = '/login';
                }
            } catch (e) { /* offline: try again later */ }
        }, 30000);
    }

    return { api, esc, isoDate, formatTs, relTime, toast, boot, startSessionWatch };
})();
