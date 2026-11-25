/*
 * Pustakam (पुस्तकम्) — Markdown + math + chemistry renderer.
 *
 * Math (KaTeX):      $inline$   $$display$$   \( inline \)   \[ display \]
 * Chemistry (mhchem): $\ce{H2SO4}$   $\ce{2H2 + O2 -> 2H2O}$   or a bare \ce{CO2} anywhere in text
 * Units:              $\pu{9.81 m/s^2}$   or bare \pu{…}
 *
 * Math is cut out before Markdown runs (so _ and \\ are not mangled), the HTML
 * is sanitised with DOMPurify, then KaTeX output is put back in.
 */
const PustakamMarkdown = (() => {
    const TOKEN = i => `PKMATH${i}X`;

    function splitCode(src) {
        // -> [{code:bool, text}] ; fenced blocks and `inline code` are left untouched
        const out = [];
        const lines = src.split('\n');
        let buf = [], fence = null;
        const flush = (code) => { if (buf.length) out.push({ code, text: buf.join('\n') }); buf = []; };
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const m = line.match(/^\s{0,3}(`{3,}|~{3,})/);
            if (!fence && m) {
                flush(false); fence = m[1]; buf.push(line);
            } else if (fence && new RegExp(`^\\s{0,3}${fence[0] === '`' ? '`' : '~'}{${fence.length},}\\s*$`).test(line)) {
                buf.push(line); flush(true); fence = null;
            } else {
                buf.push(line);
            }
        }
        flush(!!fence);
        // re-join with newlines between segments
        const res = [];
        out.forEach((seg, i) => {
            res.push(seg);
            if (i < out.length - 1) res.push({ code: false, text: '\n' });
        });
        // inline code inside text segments
        const final = [];
        for (const seg of res) {
            if (seg.code) { final.push(seg); continue; }
            let last = 0;
            const re = /(`+)([\s\S]*?[^`])\1(?!`)/g;
            let mm;
            while ((mm = re.exec(seg.text))) {
                if (mm.index > last) final.push({ code: false, text: seg.text.slice(last, mm.index) });
                final.push({ code: true, text: mm[0] });
                last = mm.index + mm[0].length;
            }
            if (last < seg.text.length) final.push({ code: false, text: seg.text.slice(last) });
        }
        return final;
    }

    function readBraced(text, start) {
        // text[start] === '{' ; returns index after the matching '}' or -1
        let depth = 0;
        for (let i = start; i < text.length; i++) {
            const c = text[i];
            if (c === '\\') { i++; continue; }
            if (c === '{') depth++;
            else if (c === '}') { depth--; if (depth === 0) return i + 1; }
            else if (c === '\n' && text[i + 1] === '\n') return -1;
        }
        return -1;
    }

    function extractMath(text, store) {
        const re = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\\(ce|pu)\{|\\\$|\$(?!\s)((?:\\.|[^$\\\n])+?)(?<!\s)\$(?!\d)/g;
        let out = '', last = 0, m;
        while ((m = re.exec(text))) {
            out += text.slice(last, m.index);
            if (m[0] === '\\$') { out += '\\$'; last = re.lastIndex; continue; }
            let tex, display = false;
            if (m[1] !== undefined) { tex = m[1]; display = true; }
            else if (m[2] !== undefined) { tex = m[2]; display = true; }
            else if (m[3] !== undefined) { tex = m[3]; }
            else if (m[4] !== undefined) {
                const end = readBraced(text, re.lastIndex - 1);
                if (end < 0) { out += m[0]; last = re.lastIndex; continue; }
                tex = text.slice(m.index, end);
                re.lastIndex = end;
            } else { tex = m[5]; }
            store.push({ tex, display });
            out += display ? `\n\n${TOKEN(store.length - 1)}\n\n` : TOKEN(store.length - 1);
            last = re.lastIndex;
        }
        return out + text.slice(last);
    }

    function renderMath({ tex, display }) {
        if (!window.katex) return `<code>${P.esc(tex)}</code>`;
        try {
            return katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: 'ignore', trust: false, output: 'htmlAndMathml' });
        } catch (e) {
            return `<code class="math-error" title="${P.esc(e.message)}">${P.esc(tex)}</code>`;
        }
    }

    let purifyHooked = false;
    function sanitize(html) {
        if (!window.DOMPurify) return P.esc(html);
        if (!purifyHooked) {
            DOMPurify.addHook('afterSanitizeAttributes', node => {
                if (node.tagName === 'A' && /^https?:/i.test(node.getAttribute('href') || '')) {
                    node.setAttribute('target', '_blank');
                    node.setAttribute('rel', 'noopener noreferrer');
                }
            });
            purifyHooked = true;
        }
        return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
    }

    function toHtml(src) {
        if (!window.marked) return `<pre>${P.esc(src)}</pre>`;
        const store = [];
        const prepared = splitCode(src || '').map(s => s.code ? s.text : extractMath(s.text, store)).join('');
        let html = marked.parse(prepared, { gfm: true, breaks: false });
        html = sanitize(html);
        html = html.replace(/<p>\s*(PKMATH\d+X)\s*<\/p>/g, '$1');
        html = html.replace(/PKMATH(\d+)X/g, (_, i) => {
            const item = store[+i];
            return item ? (item.display ? `<div class="math-display">${renderMath(item)}</div>` : renderMath(item)) : '';
        });
        return html;
    }

    function render(el, src) {
        el.innerHTML = toHtml(src);
        if (window.hljs) el.querySelectorAll('pre code').forEach(b => { try { hljs.highlightElement(b); } catch (e) {} });
        el.querySelectorAll('table').forEach(t => {
            if (!t.parentElement.classList.contains('table-wrap')) {
                const w = document.createElement('div'); w.className = 'table-wrap';
                t.replaceWith(w); w.appendChild(t);
            }
        });
    }

    return { render, toHtml };
})();
