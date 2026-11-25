/*
 * Pustakam (पुस्तकम्) — a unique icon for every notebook, derived from its name.
 * 1. A keyword in the name picks a matching glyph (work → 💼, chemistry → ⚗️ …).
 * 2. Otherwise the notebook's initials are used.
 * 3. The colour (hue + gradient angle + pattern) comes from a hash of the name,
 *    so two notebooks never look the same even when they share a glyph.
 */
const PustakamFolderIcons = (() => {
    const RULES = [
        [/chem|molecul|reaction|lab\b/i, '⚗️'], [/physic|quantum|mechanic/i, '⚛️'],
        [/math|algebra|calculus|geometr|statistic/i, '📐'], [/bio|gene|cell|anatom/i, '🧬'],
        [/scien|research|experiment/i, '🔬'], [/astro|space|planet|star/i, '🔭'],
        [/med|health|doctor|fitness|gym|workout/i, '🩺'], [/code|dev|program|python|script|linux|tech|software/i, '💻'],
        [/work|job|office|career|business/i, '💼'], [/meet|agenda|minutes/i, '🗓️'],
        [/project|launch|startup/i, '🚀'], [/idea|brainstorm|inspir/i, '💡'],
        [/todo|task|checklist|gtd/i, '✅'], [/journal|diary|daily|log\b/i, '📔'],
        [/book|read|library|literat|novel/i, '📚'], [/sanskrit|veda|gita|yoga|spiritual|mantra|sloka|shloka/i, '🪔'],
        [/recipe|cook|food|kitchen|meal/i, '🍳'], [/travel|trip|vacation|holiday|flight/i, '✈️'],
        [/financ|money|budget|tax|invest|bank|expense/i, '💰'], [/shop|buy|grocer|wishlist/i, '🛒'],
        [/music|song|guitar|piano|lyric/i, '🎵'], [/photo|camera|picture/i, '📷'],
        [/art|draw|design|sketch|paint/i, '🎨'], [/game|gaming/i, '🎮'],
        [/family|kids|child|parent/i, '👪'], [/home|house|personal|life/i, '🏠'],
        [/school|study|class|course|lecture|exam|universit|college/i, '🎓'], [/language|vocab|learn/i, '🗣️'],
        [/garden|plant|nature/i, '🌿'], [/car|vehicle|auto/i, '🚗'], [/pet|dog|cat/i, '🐾'],
        [/write|writing|blog|article|draft/i, '✍️'], [/quote|poem|poetry/i, '🪶'],
        [/movie|film|tv|show/i, '🎬'], [/sport|football|cricket|soccer|tennis/i, '🏅'],
        [/secret|password|private|vault/i, '🔐'], [/archive|old|backup/i, '🗄️'],
        [/inbox|unsorted|misc|random/i, '📥'], [/default|general|notes?\b/i, '📒'],
        [/weather|climate/i, '⛅'], [/news/i, '📰'], [/contact|people|friend/i, '📇'],
    ];
    const PATTERNS = ['p-dots', 'p-stripes', 'p-grid', 'p-wave', 'p-glow', 'p-ring'];

    function hash(str) {
        let h = 2166136261;
        for (const ch of str) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619); }
        return h >>> 0;
    }

    function glyphFor(name) {
        for (const [re, g] of RULES) if (re.test(name)) return { glyph: g, emoji: true };
        const words = name.trim().split(/\s+/).filter(Boolean);
        let letters = words.length > 1 ? (words[0][0] + words[1][0]) : (words[0] || '?').slice(0, 2);
        letters = [...letters].slice(0, 2).join('');
        return { glyph: letters.charAt(0).toUpperCase() + letters.slice(1).toLowerCase(), emoji: false };
    }

    function html(name, extraClass = '') {
        const h = hash(name || '?');
        const hue = h % 360;
        const hue2 = (hue + 35 + (h >> 9) % 50) % 360;
        const angle = (h >> 4) % 360;
        const pattern = PATTERNS[(h >> 13) % PATTERNS.length];
        const { glyph, emoji } = glyphFor(name || '?');
        return `<span class="folder-icon ${pattern} ${emoji ? 'is-emoji' : 'is-letter'} ${extraClass}"
                      style="--h:${hue};--h2:${hue2};--a:${angle}deg" aria-hidden="true">
                    <span class="fi-glyph">${P.esc(glyph)}</span></span>`;
    }

    function special(kind) {
        const glyph = { all: '∞', unfiled: '📄', tag: '#' }[kind] || '•';
        return `<span class="folder-icon folder-icon-special fi-${kind}" aria-hidden="true"><span class="fi-glyph">${glyph}</span></span>`;
    }

    return { html, special };
})();
