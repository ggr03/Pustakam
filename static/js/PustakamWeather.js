/*
 * Pustakam (पुस्तकम्) — weather in the status bar (Open-Meteo, no API key).
 * Each saved city shows icon, °C/°F and a short description. Click a city for
 * local date/time, feels-like, humidity, wind, air quality (US AQI) and UV index.
 * Cities are saved on the server, so they follow you to every browser.
 * Drag the chips to reorder.
 */
const PustakamWeather = (() => {
    const CACHE_MS = 15 * 60 * 1000;
    let cities = [];
    let cache = {};
    let geoResults = {};
    let geoTimer = null;
    let dragIndex = null;
    let openKey = null;

    const WMO = {
        0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
        45: 'Fog', 48: 'Rime fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Dense drizzle',
        56: 'Freezing drizzle', 57: 'Freezing drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
        66: 'Freezing rain', 67: 'Freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow',
        77: 'Snow grains', 80: 'Light showers', 81: 'Showers', 82: 'Violent showers',
        85: 'Snow showers', 86: 'Heavy snow showers', 95: 'Thunderstorm', 96: 'Thunderstorm, hail', 99: 'Thunderstorm, hail',
    };

    function icon(code, isDay = true) {
        if (code === 0) return isDay ? '☀️' : '🌙';
        if (code === 1 || code === 2) return isDay ? '⛅' : '☁️';
        if (code === 3) return '☁️';
        if (code === 45 || code === 48) return '🌫️';
        if (code >= 51 && code <= 67) return '🌧️';
        if (code >= 71 && code <= 77) return '❄️';
        if (code >= 80 && code <= 82) return '🌦️';
        if (code >= 85 && code <= 86) return '🌨️';
        if (code >= 95) return '⛈️';
        return '🌡️';
    }

    function aqiInfo(aqi) {
        if (aqi === null || aqi === undefined || aqi === '--') return ['—', 'aqi-na'];
        if (aqi <= 50) return ['Good', 'aqi-good'];
        if (aqi <= 100) return ['Moderate', 'aqi-mod'];
        if (aqi <= 150) return ['Unhealthy for sensitive', 'aqi-usg'];
        if (aqi <= 200) return ['Unhealthy', 'aqi-bad'];
        if (aqi <= 300) return ['Very unhealthy', 'aqi-vbad'];
        return ['Hazardous', 'aqi-haz'];
    }

    function uvInfo(uv) {
        if (uv === null || uv === undefined) return '—';
        if (uv < 3) return 'Low'; if (uv < 6) return 'Moderate'; if (uv < 8) return 'High';
        if (uv < 11) return 'Very high'; return 'Extreme';
    }

    const key = c => `${c.lat.toFixed(3)},${c.lon.toFixed(3)}`;
    const shortName = c => (c.city || '').split(',')[0].trim();
    const cToF = c => Math.round(c * 1.8 + 32);

    async function fetchWeather(c) {
        const k = key(c);
        if (cache[k] && Date.now() - cache[k].t < CACHE_MS) return cache[k].d;
        const tz = encodeURIComponent(c.tz || 'auto');
        const wUrl = `https://api.open-meteo.com/v1/forecast?latitude=${c.lat}&longitude=${c.lon}&current=temperature_2m,apparent_temperature,wind_speed_10m,relative_humidity_2m,uv_index,is_day,weather_code&daily=temperature_2m_max,temperature_2m_min&forecast_days=1&timezone=${tz}`;
        const aUrl = `https://air-quality-api.open-meteo.com/v1/air-quality?latitude=${c.lat}&longitude=${c.lon}&current=us_aqi&timezone=${tz}`;
        try {
            const [w, a] = await Promise.all([fetch(wUrl), fetch(aUrl).catch(() => null)]);
            const d = await w.json();
            d.airQuality = a && a.ok ? await a.json() : null;
            cache[k] = { d, t: Date.now() };
            return d;
        } catch (e) {
            return cache[k] ? cache[k].d : null;
        }
    }

    function localTime(c, withDate = false) {
        const now = new Date();
        try {
            const time = now.toLocaleTimeString('en-GB', { timeZone: c.tz, hour: '2-digit', minute: '2-digit', hour12: false });
            if (!withDate) return time;
            const parts = new Intl.DateTimeFormat('en-CA', { timeZone: c.tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
            const wd = now.toLocaleDateString('en-US', { timeZone: c.tz, weekday: 'long' });
            return `${wd} ${parts} · ${time}`;
        } catch (e) { return ''; }
    }

    // ---------------------------------------------------------------- render
    function renderStrip() {
        const strip = document.getElementById('wx-strip');
        strip.innerHTML = '';
        cities.forEach((c, i) => {
            const chip = document.createElement('button');
            chip.className = 'wx-chip';
            chip.draggable = true;
            chip.dataset.index = i;
            chip.title = `${c.city} — click for details, drag to reorder`;
            chip.innerHTML = `<span class="wx-ico">⏳</span><span class="wx-name">${P.esc(shortName(c))}${c.cc ? `<small>${P.esc(c.cc)}</small>` : ''}</span><span class="wx-temp">…</span>`;
            chip.addEventListener('click', (e) => { e.stopPropagation(); togglePopover(i, chip); });
            chip.addEventListener('dragstart', (e) => { dragIndex = i; e.dataTransfer.effectAllowed = 'move'; chip.classList.add('dragging'); });
            chip.addEventListener('dragend', () => { chip.classList.remove('dragging'); dragIndex = null; strip.querySelectorAll('.drag-over').forEach(x => x.classList.remove('drag-over')); });
            chip.addEventListener('dragover', (e) => { e.preventDefault(); chip.classList.add('drag-over'); });
            chip.addEventListener('dragleave', () => chip.classList.remove('drag-over'));
            chip.addEventListener('drop', (e) => {
                e.preventDefault();
                if (dragIndex === null || dragIndex === i) return;
                const [m] = cities.splice(dragIndex, 1);
                cities.splice(i, 0, m);
                save(); renderStrip();
            });
            strip.appendChild(chip);
            fillChip(c, chip);
        });
    }

    async function fillChip(c, chip) {
        const d = await fetchWeather(c);
        if (!d || !d.current) { chip.querySelector('.wx-temp').textContent = 'n/a'; chip.querySelector('.wx-ico').textContent = '🌡️'; return; }
        const cur = d.current;
        const tC = Math.round(cur.temperature_2m);
        chip.querySelector('.wx-ico').textContent = icon(cur.weather_code, cur.is_day === 1);
        chip.querySelector('.wx-temp').innerHTML = `${tC}°C<span class="wx-f">${cToF(cur.temperature_2m)}°F</span>`;
        const brief = WMO[cur.weather_code] || '';
        chip.title = `${c.city}: ${brief}, ${tC}°C / ${cToF(cur.temperature_2m)}°F — click for details`;
        chip.insertAdjacentHTML('beforeend', `<span class="wx-brief">${P.esc(brief)}</span>`);
    }

    async function togglePopover(i, anchor) {
        const pop = document.getElementById('wx-popover');
        const c = cities[i];
        if (!pop.hidden && openKey === key(c)) { closePopover(); return; }
        openKey = key(c);
        pop.innerHTML = '<div class="wx-pop-loading">Fetching weather…</div>';
        pop.hidden = false;
        position(pop, anchor);
        const d = await fetchWeather(c);
        if (openKey !== key(c)) return;
        if (!d || !d.current) { pop.innerHTML = '<div class="wx-pop-loading">Weather unavailable right now.</div>'; return; }
        const cur = d.current;
        const aqi = d.airQuality?.current?.us_aqi;
        const [aqiTxt, aqiCls] = aqiInfo(aqi);
        const hi = d.daily?.temperature_2m_max?.[0], lo = d.daily?.temperature_2m_min?.[0];
        const windKmh = cur.wind_speed_10m;
        const uv = cur.uv_index;
        pop.innerHTML = `
            <button class="wx-pop-close" title="Remove city" data-remove="${i}">✕</button>
            <div class="wx-pop-head">
                <div>
                    <div class="wx-pop-city">${P.esc(shortName(c))}${c.cc ? ` <span class="wx-cc">${P.esc(c.cc)}</span>` : ''}</div>
                    <div class="wx-pop-sub">${P.esc(c.city)}</div>
                    <div class="wx-pop-time" data-tz-clock>${P.esc(localTime(c, true))}</div>
                </div>
            </div>
            <div class="wx-pop-main">
                <span class="wx-pop-icon">${icon(cur.weather_code, cur.is_day === 1)}</span>
                <div>
                    <div class="wx-pop-temp">${Math.round(cur.temperature_2m)}°C <span>(${cToF(cur.temperature_2m)}°F)</span></div>
                    <div class="wx-pop-brief">${P.esc(WMO[cur.weather_code] || '')}</div>
                    <div class="wx-pop-feels">Feels like ${Math.round(cur.apparent_temperature)}°C (${cToF(cur.apparent_temperature)}°F)
                        ${hi !== undefined ? ` · H ${Math.round(hi)}° L ${Math.round(lo)}°` : ''}</div>
                </div>
            </div>
            <div class="wx-metrics">
                <div class="wx-metric" title="Humidity"><span>💧</span><b>${cur.relative_humidity_2m}%</b><small>Humidity</small></div>
                <div class="wx-metric" title="Wind speed"><span>💨</span><b>${(windKmh / 1.60934).toFixed(1)} mph</b><small>${Math.round(windKmh)} km/h</small></div>
                <div class="wx-metric ${aqiCls}" title="US Air Quality Index"><span>🍃</span><b>${aqi ?? '—'}</b><small>AQI · ${aqiTxt}</small></div>
                <div class="wx-metric" title="UV index"><span>🔆</span><b>${uv !== null && uv !== undefined ? uv.toFixed(1) : '—'}</b><small>UV · ${uvInfo(uv)}</small></div>
            </div>`;
        pop.querySelector('[data-remove]').addEventListener('click', (e) => {
            e.stopPropagation();
            cities.splice(i, 1); save(); renderStrip(); closePopover();
        });
        position(pop, anchor);
    }

    function position(pop, anchor) {
        const r = anchor.getBoundingClientRect();
        const w = pop.offsetWidth || 300;
        let left = Math.min(window.innerWidth - w - 10, Math.max(10, r.left + r.width / 2 - w / 2));
        pop.style.left = `${left}px`;
        pop.style.bottom = `${window.innerHeight - r.top + 8}px`;
    }

    function closePopover() {
        const pop = document.getElementById('wx-popover');
        pop.hidden = true; openKey = null;
    }

    // ---------------------------------------------------------------- search & add
    async function geocode(q) {
        try {
            const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=10&language=en&format=json`);
            const d = await r.json();
            const list = document.getElementById('wx-city-list');
            geoResults = {}; list.innerHTML = '';
            (d.results || []).forEach(x => {
                const label = [x.name, x.admin1, x.country].filter(Boolean).join(', ');
                geoResults[label.toLowerCase()] = { city: label, country: x.country || '', cc: x.country_code || '', tz: x.timezone || 'UTC', lat: x.latitude, lon: x.longitude };
                const o = document.createElement('option'); o.value = label; list.appendChild(o);
            });
        } catch (e) { /* offline */ }
    }

    function tryAdd() {
        const input = document.getElementById('wx-search');
        const q = input.value.trim().toLowerCase();
        if (!q) return;
        const loc = geoResults[q] || Object.values(geoResults).find(g => g.city.toLowerCase().startsWith(q));
        if (!loc) { P.toast('Pick a city from the suggestions list', 'warn'); return; }
        if (!cities.some(c => key(c) === key(loc))) {
            if (cities.length >= 12) { P.toast('Up to 12 cities can be shown', 'warn'); return; }
            cities.push(loc); save(); renderStrip();
            P.toast(`Added ${shortName(loc)}`, 'ok');
        }
        input.value = ''; input.blur();
    }

    function save() {
        P.api('/api/weather/cities', { method: 'POST', json: { cities } }).catch(() => P.toast('Could not save cities', 'error'));
    }

    // ---------------------------------------------------------------- clock (ISO date)
    function tickClock() {
        const now = new Date();
        document.getElementById('sb-date-day').textContent = P.isoDate(now);
        document.getElementById('sb-date-time').textContent = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
        const popClock = document.querySelector('#wx-popover [data-tz-clock]');
        if (popClock && openKey) {
            const c = cities.find(x => key(x) === openKey);
            if (c) popClock.textContent = localTime(c, true);
        }
    }

    function init(saved) {
        cities = Array.isArray(saved) ? saved.filter(c => typeof c.lat === 'number') : [];
        renderStrip();
        tickClock();
        setInterval(tickClock, 15000);
        setInterval(() => { cache = {}; renderStrip(); }, CACHE_MS);
        const input = document.getElementById('wx-search');
        input.addEventListener('input', () => {
            const q = input.value.trim();
            if (geoResults[q.toLowerCase()]) { tryAdd(); return; }  // picked from datalist
            clearTimeout(geoTimer);
            if (q.length >= 2) geoTimer = setTimeout(() => geocode(q), 300);
        });
        input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); tryAdd(); } if (e.key === 'Escape') input.blur(); });
        document.addEventListener('click', (e) => {
            const pop = document.getElementById('wx-popover');
            if (!pop.hidden && !pop.contains(e.target)) closePopover();
        });
        window.addEventListener('resize', closePopover);
    }

    return { init };
})();
