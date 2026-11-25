/*
 * Pustakam (पुस्तकम्) — Markdown editor: toolbar, smart editing, find & replace.
 *
 *  • Toolbar: undo/redo, text style, bold/italic/strike/code (toggles), lists (toggles),
 *    quote, link, image, table, code block, divider, math & chemistry, find/replace, help.
 *  • Smart editing: Enter continues lists, Tab / Shift+Tab indent lines.
 *  • Find & replace: live highlights in the text, "3 of 12", match case / whole word /
 *    regular expression ($1 groups), replace one, replace all (one undo step).
 *
 * Edits go through document.execCommand('insertText') where available so that the
 * browser's own undo (Ctrl+Z) keeps working; otherwise setRangeText is used.
 */
const PustakamEditor = (() => {
    const $ = id => document.getElementById(id);
    const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    let ta, hl, panel, active = false;

    // ================================================================ low-level editing
    function emitInput() { ta.dispatchEvent(new Event('input', { bubbles: true })); }

    function replaceRange(start, end, text, selStart = null, selEnd = null) {
        ta.focus();
        ta.setSelectionRange(start, end);
        let ok = false;
        try { ok = document.execCommand('insertText', false, text); } catch (e) { ok = false; }
        if (!ok || ta.value.slice(start, start + text.length) !== text) {
            ta.setRangeText(text, start, end, 'end');
            emitInput();
        }
        if (selStart !== null) ta.setSelectionRange(selStart, selEnd ?? selStart);
    }

    function lineBounds(start, end) {
        const v = ta.value;
        const ls = v.lastIndexOf('\n', start - 1) + 1;
        let le = v.indexOf('\n', end > start && v[end - 1] === '\n' ? end - 1 : end);
        if (le === -1) le = v.length;
        return [ls, le];
    }

    // ================================================================ inline formatting (toggles)
    function wrap(before, after = before, placeholder = 'text') {
        const v = ta.value, s = ta.selectionStart, e = ta.selectionEnd, sel = v.slice(s, e);
        if (v.slice(s - before.length, s) === before && v.slice(e, e + after.length) === after && (s - before.length) >= 0) {
            replaceRange(s - before.length, e + after.length, sel, s - before.length, s - before.length + sel.length);
            return;
        }
        if (sel.length >= before.length + after.length && sel.startsWith(before) && sel.endsWith(after)) {
            const inner = sel.slice(before.length, sel.length - after.length);
            replaceRange(s, e, inner, s, s + inner.length);
            return;
        }
        const text = sel || placeholder;
        replaceRange(s, e, before + text + after, s + before.length, s + before.length + text.length);
    }

    // ================================================================ line formatting (toggles)
    const LINE = {
        ul: /^(\s*)[-*+] (?!\[[ xX]\] )/,
        ol: /^(\s*)\d+[.)] /,
        task: /^(\s*)[-*+] \[[ xX]\] /,
        quote: /^(\s*)> ?/,
    };
    const ANY_LIST = /^(\s*)(?:[-*+] \[[ xX]\] |[-*+] |\d+[.)] |> ?)/;

    function toggleLines(kind) {
        const [ls, le] = lineBounds(ta.selectionStart, ta.selectionEnd);
        const lines = ta.value.slice(ls, le).split('\n');
        const content = lines.filter(l => l.trim());
        const allHave = content.length > 0 && content.every(l => LINE[kind].test(l));
        let n = 0;
        const out = lines.map(l => {
            if (allHave) return l.replace(LINE[kind], '$1');
            if (!l.trim() && lines.length > 1) return l;
            const ind = (l.match(/^\s*/) || [''])[0];
            const body = l.replace(ANY_LIST, '').replace(/^\s*/, '');
            n++;
            const prefix = { ul: '- ', ol: `${n}. `, task: '- [ ] ', quote: '> ' }[kind];
            return ind + prefix + body;
        }).join('\n');
        replaceRange(ls, le, out, lines.length === 1 && !ta.value.slice(ls, le).trim() ? ls + out.length : ls, ls + out.length);
    }

    function setHeading(level) {
        const [ls, le] = lineBounds(ta.selectionStart, ta.selectionEnd);
        const out = ta.value.slice(ls, le).split('\n').map(l => {
            const body = l.replace(/^\s*#{1,6}\s+/, '');
            return level > 0 ? '#'.repeat(level) + ' ' + body : body;
        }).join('\n');
        replaceRange(ls, le, out, ls + out.length);
    }

    function currentHeading() {
        const [ls, le] = lineBounds(ta.selectionStart, ta.selectionStart);
        const m = ta.value.slice(ls, le).match(/^\s*(#{1,6})\s/);
        return m ? Math.min(4, m[1].length) : 0;
    }

    // ================================================================ blocks
    function insertBlock(text, cursorInText = null, selectLen = 0) {
        const v = ta.value, s = ta.selectionStart, e = ta.selectionEnd;
        const pre = s > 0 && v[s - 1] !== '\n' ? '\n\n' : (s > 1 && v[s - 2] !== '\n' ? '\n' : '');
        const post = e < v.length && v[e] !== '\n' ? '\n' : '';
        const full = pre + text + post;
        const caret = s + pre.length + (cursorInText ?? text.length);
        replaceRange(s, e, full, caret, caret + selectLen);
    }

    function codeBlock() {
        const s = ta.selectionStart, e = ta.selectionEnd;
        if (s !== e) {
            const [ls, le] = lineBounds(s, e);
            const inner = ta.value.slice(ls, le);
            const out = '```\n' + inner + '\n```';
            replaceRange(ls, le, out, ls + 3);
        } else {
            insertBlock('```\n\n```', 4);
        }
    }

    function link(image = false) {
        const v = ta.value, s = ta.selectionStart, e = ta.selectionEnd, sel = v.slice(s, e).trim();
        const bang = image ? '!' : '';
        if (/^https?:\/\/\S+$/i.test(sel)) {
            const label = image ? 'image description' : 'link text';
            replaceRange(s, e, `${bang}[${label}](${sel})`, s + bang.length + 1, s + bang.length + 1 + label.length);
        } else {
            const label = sel || (image ? 'image description' : 'link text');
            const text = `${bang}[${label}](https://)`;
            const urlAt = s + bang.length + label.length + 3;
            replaceRange(s, e, text, urlAt, urlAt + 8);
        }
    }

    const TABLE = '| Column 1 | Column 2 | Column 3 |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |';

    const CMD = {
        undo: () => { ta.focus(); document.execCommand('undo'); },
        redo: () => { ta.focus(); document.execCommand('redo'); },
        bold: () => wrap('**', '**', 'bold text'),
        italic: () => wrap('*', '*', 'italic text'),
        strike: () => wrap('~~', '~~', 'struck text'),
        code: () => wrap('`', '`', 'code'),
        ul: () => toggleLines('ul'), ol: () => toggleLines('ol'), task: () => toggleLines('task'), quote: () => toggleLines('quote'),
        link: () => link(false), image: () => link(true),
        table: () => insertBlock(TABLE, 2, 8),
        codeblock: codeBlock,
        hr: () => insertBlock('---\n', 4),
        math: () => wrap('$', '$', 'E = mc^2'),
        mathblock: () => insertBlock('$$\n\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}\n$$', 3, 0),
        chem: () => wrap('$\\ce{', '}$', 'H2SO4'),
        reaction: () => wrap('$\\ce{', '}$', 'N2 + 3H2 <=> 2NH3'),
        find: () => openFind(false),
        replace: () => openFind(true),
        help: () => toggleHelp(),
    };

    // ================================================================ smart keys
    function smartEnter(e) {
        const v = ta.value, s = ta.selectionStart;
        if (s !== ta.selectionEnd) return false;
        const ls = v.lastIndexOf('\n', s - 1) + 1;
        const line = v.slice(ls, s);
        const m = line.match(/^(\s*)([-*+] \[[ xX]\] |[-*+] |(\d+)([.)]) |> )/);
        if (!m) return false;
        e.preventDefault();
        if (line.slice(m[0].length).trim() === '' && v.slice(s, v.indexOf('\n', s) === -1 ? v.length : v.indexOf('\n', s)).trim() === '') {
            replaceRange(ls, s, m[1], ls + m[1].length);          // empty item: end the list
            return true;
        }
        let next = m[2];
        if (m[3]) next = `${parseInt(m[3], 10) + 1}${m[4]} `;
        if (/\[[xX]\]/.test(next)) next = next.replace(/\[[xX]\]/, '[ ]');
        replaceRange(s, s, '\n' + m[1] + next);
        return true;
    }

    function indent(outdent) {
        const s = ta.selectionStart, e = ta.selectionEnd;
        if (!outdent && s === e) { replaceRange(s, e, '    '); return; }
        const [ls, le] = lineBounds(s, e);
        const lines = ta.value.slice(ls, le).split('\n');
        const out = lines.map(l => outdent ? l.replace(/^( {1,4}|\t)/, '') : '    ' + l).join('\n');
        replaceRange(ls, le, out, ls, ls + out.length);
    }

    function onEditorKey(e) {
        const mod = isMac ? e.metaKey : e.ctrlKey;
        const k = e.key.toLowerCase();
        if (e.key === 'Escape' && !panel.hidden) { e.preventDefault(); e.stopPropagation(); closeFind(); return; }
        if (e.key === 'Enter' && !mod && !e.shiftKey && !e.altKey) { smartEnter(e); return; }
        if (e.key === 'Tab' && !mod && !e.altKey) { e.preventDefault(); indent(e.shiftKey); return; }
        if (e.key === 'F3') { e.preventDefault(); if (panel.hidden) openFind(false); else step(e.shiftKey ? -1 : 1); return; }
        if (!mod) return;
        const map = {
            b: !e.shiftKey && 'bold', i: !e.shiftKey && 'italic', k: !e.shiftKey && 'link', m: !e.shiftKey && 'math',
            x: e.shiftKey && 'strike', '`': (e.shiftKey ? 'codeblock' : 'code'), '~': e.shiftKey && 'codeblock',
            '8': e.shiftKey && 'ul', '*': e.shiftKey && 'ul', '7': e.shiftKey && 'ol', '&': e.shiftKey && 'ol',
            '9': e.shiftKey && 'task', '(': e.shiftKey && 'task', '.': e.shiftKey && 'quote', '>': e.shiftKey && 'quote',
        };
        const cmd = map[k];
        if (cmd) { e.preventDefault(); CMD[cmd](); }
    }

    // ================================================================ find & replace
    const F = { matches: [], cur: -1, re: null, error: null };

    function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
    function pressed(id) { return $(id).getAttribute('aria-pressed') === 'true'; }

    function buildRe() {
        const q = $('fp-find').value;
        F.error = null;
        if (!q) return null;
        let src = pressed('fp-regex') ? q : escRe(q);
        if (pressed('fp-word')) src = `(?<![\\p{L}\\p{N}_])(?:${src})(?![\\p{L}\\p{N}_])`;
        try { return new RegExp(src, 'gmu' + (pressed('fp-case') ? '' : 'i')); }
        catch (err) {
            try { return new RegExp(src, 'gm' + (pressed('fp-case') ? '' : 'i')); }
            catch (err2) { F.error = 'Invalid pattern'; return null; }
        }
    }

    function search(keepPosition = true) {
        F.re = buildRe();
        F.matches = [];
        if (F.re) {
            const v = ta.value;
            let m, guard = 0;
            F.re.lastIndex = 0;
            while ((m = F.re.exec(v)) && guard++ < 10000) {
                if (m[0].length === 0) { F.re.lastIndex++; continue; }
                F.matches.push({ start: m.index, end: m.index + m[0].length });
            }
        }
        if (!F.matches.length) F.cur = -1;
        else if (!keepPosition || F.cur < 0 || F.cur >= F.matches.length) {
            const from = ta.selectionStart;
            const i = F.matches.findIndex(x => x.start >= from);
            F.cur = i === -1 ? 0 : i;
        }
        render();
    }

    function updateCount() {
        const c = $('fp-count');
        const q = $('fp-find').value;
        c.classList.toggle('fp-none', !!q && !F.matches.length);
        c.textContent = F.error ? F.error : !q ? '' : F.matches.length ? `${F.cur + 1} of ${F.matches.length}${F.matches.length >= 10000 ? '+' : ''}` : 'No results';
        const has = F.matches.length > 0;
        ['fp-prev', 'fp-next', 'fp-replace-one', 'fp-replace-all'].forEach(id => { $(id).disabled = !has; });
    }

    function render() {
        updateCount();
        if (panel.hidden || !F.matches.length) { hl.innerHTML = ''; return; }
        const v = ta.value;
        const frag = document.createDocumentFragment();
        let pos = 0;
        F.matches.forEach((m, i) => {
            if (m.start > pos) frag.appendChild(document.createTextNode(v.slice(pos, m.start)));
            const mark = document.createElement('mark');
            if (i === F.cur) { mark.className = 'current'; mark.id = 'fp-current'; }
            mark.textContent = v.slice(m.start, m.end);
            frag.appendChild(mark);
            pos = m.end;
        });
        frag.appendChild(document.createTextNode(v.slice(pos) + '​'));
        hl.replaceChildren(frag);
        syncHighlightBox();
    }

    function reveal() {
        const m = F.matches[F.cur];
        if (!m) return;
        ta.setSelectionRange(m.start, m.end);
        const cur = $('fp-current');
        if (cur) {
            // keep the current match visible *below* the floating find panel
            const top = cur.offsetTop, h = ta.clientHeight;
            const cover = panel.hidden ? 0 : panel.offsetTop + panel.offsetHeight + 12;
            if (top < ta.scrollTop + cover || top > ta.scrollTop + h - 60) {
                ta.scrollTop = Math.max(0, top - Math.max(cover + 8, h / 3));
            }
        }
        hl.scrollTop = ta.scrollTop;
    }

    function step(dir) {
        if (!F.matches.length) return;
        F.cur = (F.cur + dir + F.matches.length) % F.matches.length;
        render(); reveal();
    }

    function expandReplacement(m) {
        const rep = $('fp-replace').value;
        if (!pressed('fp-regex')) return rep;
        const one = new RegExp(F.re.source, F.re.flags.replace('g', ''));
        return ta.value.slice(m.start, m.end).replace(one, rep);
    }

    function replaceOne() {
        const m = F.matches[F.cur];
        if (!m) return;
        const text = expandReplacement(m);
        replaceRange(m.start, m.end, text, m.start + text.length);
        const after = m.start + text.length;
        search(false);
        if (F.matches.length) {
            const i = F.matches.findIndex(x => x.start >= after);
            F.cur = i === -1 ? 0 : i;
            render(); reveal();
        }
        $('fp-replace').focus();
    }

    function replaceAll() {
        if (!F.matches.length || !F.re) return;
        const n = F.matches.length;
        const rep = pressed('fp-regex') ? $('fp-replace').value : $('fp-replace').value.replace(/\$/g, '$$$$');
        F.re.lastIndex = 0;
        const out = ta.value.replace(F.re, rep);
        const keep = ta.scrollTop;
        replaceRange(0, ta.value.length, out, 0);
        ta.scrollTop = keep;
        search(false);
        $('fp-count').textContent = `Replaced ${n}`;
        $('fp-replace').focus();
        if (window.P) P.toast(`Replaced ${n} match${n === 1 ? '' : 'es'} (Ctrl+Z to undo)`, 'ok');
    }

    function setReplaceVisible(on) {
        $('fp-replace-row').hidden = !on;
        $('fp-toggle').setAttribute('aria-expanded', String(on));
        $('fp-toggle').classList.toggle('open', on);
    }

    function openFind(withReplace) {
        if (!active) return;
        const sel = ta.value.slice(ta.selectionStart, ta.selectionEnd);
        const wasHidden = panel.hidden;
        panel.hidden = false;
        $('editor-pane').classList.add('finding');
        if (withReplace) setReplaceVisible(true);
        else if (wasHidden) setReplaceVisible(false);
        if (sel && !sel.includes('\n') && sel.length < 200) $('fp-find').value = sel;
        const input = withReplace && $('fp-find').value ? $('fp-replace') : $('fp-find');
        input.focus(); input.select();
        search(false);
        reveal();
    }

    function closeFind() {
        panel.hidden = true;
        $('editor-pane').classList.remove('finding');
        hl.innerHTML = '';
        const m = F.matches[F.cur];
        ta.focus();
        if (m) ta.setSelectionRange(m.start, m.end);
    }

    function syncHighlightBox() {
        // the overlay must wrap text exactly like the textarea: same width minus its scrollbar
        const sb = ta.offsetWidth - ta.clientWidth;
        hl.style.right = `${sb}px`;
        hl.scrollTop = ta.scrollTop;
    }

    // ================================================================ status (Ln/Col, words)
    let statusTimer = null;
    function updateStatus() {
        clearTimeout(statusTimer);
        statusTimer = setTimeout(() => {
            if (!active) return;
            const v = ta.value, p = ta.selectionStart;
            const before = v.slice(0, p);
            const ln = before.split('\n').length, col = p - before.lastIndexOf('\n');
            const words = (v.match(/[\p{L}\p{N}][\p{L}\p{N}'’_-]*/gu) || []).length;
            const sel = ta.selectionEnd - ta.selectionStart;
            $('tb-status').textContent = `Ln ${ln}, Col ${col}${sel ? ` · ${sel} selected` : ''} · ${words} word${words === 1 ? '' : 's'}`;
            const h = $('tb-heading');
            if (document.activeElement !== h) h.value = String(currentHeading());
        }, 60);
    }

    // ================================================================ tooltips & help
    function shortcutText(t) { return isMac ? t.replace(/Ctrl\+/g, '⌘').replace(/Alt\+/g, '⌥').replace(/Shift\+/g, '⇧') : t; }

    function initTooltips() {
        const tip = $('tb-tooltip');
        let timer;
        const show = el => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                tip.textContent = shortcutText(el.dataset.tip);
                tip.hidden = false;
                const r = el.getBoundingClientRect(), w = tip.offsetWidth;
                tip.style.left = `${Math.max(6, Math.min(window.innerWidth - w - 6, r.left + r.width / 2 - w / 2))}px`;
                tip.style.top = `${r.bottom + 8}px`;
            }, 350);
        };
        const hide = () => { clearTimeout(timer); tip.hidden = true; };
        document.addEventListener('mouseover', e => { const el = e.target.closest('[data-tip]'); if (el) show(el); });
        document.addEventListener('mouseout', e => { if (e.target.closest('[data-tip]')) hide(); });
        document.addEventListener('focusin', e => { const el = e.target.closest('.md-toolbar [data-tip], .find-panel [data-tip]'); if (el && el.matches(':focus-visible')) show(el); else hide(); });
        document.addEventListener('mousedown', hide);
        document.addEventListener('scroll', hide, true);
    }

    function toggleHelp() {
        const box = $('md-help');
        if (!box.hidden) { box.hidden = true; return; }
        const m = isMac ? '⌘' : 'Ctrl+';
        const rows = [
            ['Bold', '**bold**', `${m}B`], ['Italic', '*italic*', `${m}I`], ['Strikethrough', '~~text~~', `${m}${isMac ? '⇧' : 'Shift+'}X`],
            ['Inline code', '`code`', `${m}\``], ['Link', '[text](https://…)', `${m}K`], ['Heading', '# Title, ## Section', 'Text style menu'],
            ['Bulleted list', '- item', `${m}${isMac ? '⇧' : 'Shift+'}8`], ['Numbered list', '1. item', `${m}${isMac ? '⇧' : 'Shift+'}7`],
            ['Task', '- [ ] to do', `${m}${isMac ? '⇧' : 'Shift+'}9`], ['Quote', '> quote', `${m}${isMac ? '⇧' : 'Shift+'}.`],
            ['Math', '$E=mc^2$ · $$…$$', `${m}M`], ['Chemistry', '$\\ce{2H2 + O2 -> 2H2O}$', '⚗ button'],
            ['Find / Replace', '', `${m}F · ${m}H · F3`], ['Indent / outdent', '', 'Tab · Shift+Tab'], ['Save · Read view', '', `${m}S · Esc`],
        ];
        box.replaceChildren();
        const h = document.createElement('div'); h.className = 'md-help-head';
        h.innerHTML = '<b>Markdown & shortcuts</b>';
        const x = document.createElement('button'); x.type = 'button'; x.className = 'fp-btn'; x.textContent = '✕'; x.setAttribute('aria-label', 'Close');
        x.addEventListener('click', () => { box.hidden = true; }); h.appendChild(x); box.appendChild(h);
        const t = document.createElement('table');
        rows.forEach(([a, b, c]) => {
            const tr = t.insertRow();
            [a, b, c].forEach((txt, i) => { const td = tr.insertCell(); if (i === 1) { const code = document.createElement('code'); code.textContent = txt; if (txt) td.appendChild(code); } else td.textContent = txt; });
        });
        box.appendChild(t);
        box.hidden = false;
        const r = document.querySelector('[data-cmd="help"]').getBoundingClientRect();
        box.style.top = `${r.bottom + 8}px`;
        box.style.left = `${Math.max(8, Math.min(window.innerWidth - box.offsetWidth - 8, r.right - box.offsetWidth))}px`;
    }

    // ================================================================ public
    function setActive(on) {
        active = on;
        if (!on) { if (!panel.hidden) { panel.hidden = true; $('editor-pane').classList.remove('finding'); hl.innerHTML = ''; } $('md-help').hidden = true; }
        else updateStatus();
    }

    function reset() {
        F.matches = []; F.cur = -1;
        hl.innerHTML = '';
        if (!panel.hidden) search(false);
        updateStatus();
    }

    function init() {
        ta = $('note-content'); hl = $('editor-highlights'); panel = $('find-panel');

        $('md-toolbar').addEventListener('mousedown', e => { if (e.target.closest('.tb-btn')) e.preventDefault(); }); // keep text selection
        $('md-toolbar').addEventListener('click', e => {
            const b = e.target.closest('[data-cmd]');
            if (b && CMD[b.dataset.cmd]) { CMD[b.dataset.cmd](); updateStatus(); }
        });
        $('tb-heading').addEventListener('change', e => { setHeading(+e.target.value); ta.focus(); });

        ta.addEventListener('keydown', onEditorKey);
        ta.addEventListener('input', () => { if (!panel.hidden) search(true); updateStatus(); });
        ta.addEventListener('scroll', () => { hl.scrollTop = ta.scrollTop; });
        ['keyup', 'click', 'select', 'focus'].forEach(ev => ta.addEventListener(ev, updateStatus));
        window.addEventListener('resize', () => { if (!panel.hidden) render(); });

        // find panel
        let t;
        $('fp-find').addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { search(false); reveal(); }, 80); });
        $('fp-find').addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
        });
        $('fp-replace').addEventListener('keydown', e => {
            const mod = isMac ? e.metaKey : e.ctrlKey;
            if (e.key === 'Enter' && mod && e.altKey) { e.preventDefault(); replaceAll(); }
            else if (e.key === 'Enter') { e.preventDefault(); replaceOne(); }
        });
        panel.addEventListener('keydown', e => {
            const mod = isMac ? e.metaKey : e.ctrlKey;
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeFind(); }
            else if (e.key === 'F3') { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
            else if (e.altKey && ['c', 'w', 'r'].includes(e.key.toLowerCase())) {
                e.preventDefault(); $({ c: 'fp-case', w: 'fp-word', r: 'fp-regex' }[e.key.toLowerCase()]).click();
            }
            else if (mod && e.key.toLowerCase() === 'h') { e.preventDefault(); setReplaceVisible($('fp-replace-row').hidden); }
            else if (mod && e.key.toLowerCase() === 'f') { e.preventDefault(); $('fp-find').select(); }
        });
        ['fp-case', 'fp-word', 'fp-regex'].forEach(id => $(id).addEventListener('click', () => {
            $(id).setAttribute('aria-pressed', String(!pressed(id)));
            search(false); reveal(); $('fp-find').focus();
        }));
        $('fp-next').addEventListener('click', () => step(1));
        $('fp-prev').addEventListener('click', () => step(-1));
        $('fp-close').addEventListener('click', closeFind);
        $('fp-toggle').addEventListener('click', () => { setReplaceVisible($('fp-replace-row').hidden); ($('fp-replace-row').hidden ? $('fp-find') : $('fp-replace')).focus(); });
        $('fp-replace-one').addEventListener('click', replaceOne);
        $('fp-replace-all').addEventListener('click', replaceAll);

        // Ctrl+F / Ctrl+H anywhere while editing (title, tags, …)
        document.addEventListener('keydown', e => {
            if (!active) return;
            const mod = isMac ? e.metaKey : e.ctrlKey;
            const k = e.key.toLowerCase();
            if (mod && !e.shiftKey && (k === 'f' || k === 'h') && !panel.contains(e.target)) { e.preventDefault(); openFind(k === 'h'); }
            if (isMac && e.metaKey && e.altKey && k === 'f') { e.preventDefault(); openFind(true); }
        });
        document.addEventListener('click', e => {
            const box = $('md-help');
            if (!box.hidden && !box.contains(e.target) && !e.target.closest('[data-cmd="help"]')) box.hidden = true;
        });
        initTooltips();
    }

    document.addEventListener('DOMContentLoaded', init);
    return { setActive, reset, openFind, closeFind, command: c => CMD[c] && CMD[c]() };
})();
