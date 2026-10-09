/*
 * Telemetria: carga de CSV (postprocesado) y tiempo real (SSE desde la Pi).
 * Ambos modos alimentan la misma vista: estadisticas + graficas del sensor.
 */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  const LIVE_MAX = 12000;   // muestras guardadas en vivo (~5 min a 40 Hz)

  const view = { ds: null, sensor: null, opt: {}, group: null, charts: {}, hists: {}, derived: null };
  const live = { es: null, ds: null, session: null, cols: [], lastT: -Infinity, paused: false, dirty: false, lastDraw: 0 };

  // --------------------------------------------------------------- tema ---

  const THEMES = ['auto', 'light', 'dark'];
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function applyTheme(th) {
    if (th === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', th);
    $('#theme').textContent = 'Tema: ' + { auto: 'auto', light: 'claro', dark: 'oscuro' }[th];
    redrawAll();
  }
  let theme = store('tele-theme') || 'auto';
  $('#theme').addEventListener('click', () => {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    store('tele-theme', theme); applyTheme(theme);
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawAll);

  function redrawAll() {
    if (view.group) view.group.draw();
    Object.values(view.hists).forEach(h => h.draw());
  }

  // ----------------------------------------------------------- pestanas ---

  function showTab(name) {
    document.querySelectorAll('[role=tab]').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === name));
    $('#pane-file').hidden = name !== 'file';
    $('#pane-live').hidden = name !== 'live';
  }
  document.querySelectorAll('[role=tab]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

  // --------------------------------------------------------------- vista ---

  function buildView(ds, sensor, { zoomable = true } = {}) {
    if (view.group) view.group.destroy();
    Object.values(view.hists).forEach(h => h.destroy());
    if (view.sensor !== sensor) {
      view.opt = {};
      sensor.options.forEach(o => { view.opt[o.id] = store('tele-opt-' + sensor.id + '-' + o.id) || o.value; });
    }
    Object.assign(view, { ds, sensor, group: new Plot.ChartGroup(), charts: {}, hists: {} });
    view.group.zoomable = zoomable;
    view.group.onRange(updateRange);

    renderOptions();
    const tBox = $('#charts-time'), hBox = $('#charts-hist');
    for (const c of sensor.charts(ds)) {
      if (c.type === 'time') view.charts[c.key] = view.group.add(new Plot.TimeChart(tBox, c));
      else view.hists[c.key] = new Plot.Histogram(hBox, c);
    }
    hBox.hidden = !Object.keys(view.hists).length;
    $('#view').hidden = false;
    recompute();
  }

  function renderOptions() {
    const box = $('#options');
    box.innerHTML = '';
    for (const o of view.sensor.options) {
      const lab = document.createElement('label');
      lab.className = 'field';
      lab.textContent = o.label + ' ';
      const sel = document.createElement('select');
      for (const [v, txt] of o.choices) sel.add(new Option(txt, v, false, v === view.opt[o.id]));
      sel.addEventListener('change', () => {
        view.opt[o.id] = sel.value;
        store('tele-opt-' + view.sensor.id + '-' + o.id, sel.value);
        recompute();
      });
      lab.appendChild(sel);
      box.appendChild(lab);
    }
  }

  function recompute() {
    const { ds, sensor } = view;
    view.derived = sensor.derive(ds, view.opt);
    for (const [k, c] of Object.entries(view.charts)) c.setData(ds.t, view.derived[k]);
    updateRange();
    view.group.draw();
  }

  function rangeIdx() {
    const t = view.ds.t, r = view.group.range;
    if (!r) return [0, t.length];
    return [Plot.lowerBound(t, r[0]), Plot.lowerBound(t, r[1] + 1e-9)];
  }

  function updateRange() {
    const { ds, sensor, derived } = view;
    const [i0, i1] = rangeIdx();
    const r = view.group.range;
    $('#range-label').textContent = ds.live
      ? 'Últimos ' + $('#win').value + ' s' + (live.paused ? ' (en pausa)' : '')
      : r ? 'Tramo ' + r[0].toFixed(2) + ' – ' + r[1].toFixed(2) + ' s' : 'Todo el registro';
    $('#reset-zoom').hidden = !r || (ds.live && !live.paused);

    const tiles = sensor.stats(ds, derived, i0, i1, view.opt);
    if (ds.live) {
      const first = Object.keys(view.charts)[0], y = derived[first];
      let now = NaN;
      for (let i = y.length - 1; i >= 0 && i >= y.length - 20; i--) if (y[i] === y[i]) { now = y[i]; break; }
      const c = view.charts[first].opts;
      tiles.unshift({ label: 'Ahora · ' + c.title, value: now === now ? now.toFixed(1) : '—', unit: c.unit, sub: 't ' + (ds.t.length ? ds.t[ds.t.length - 1].toFixed(1) : 0) + ' s', now: true });
    }
    renderTiles(tiles);

    const hd = sensor.histograms(derived, i0, i1, view.opt);
    for (const [k, h] of Object.entries(view.hists)) {
      const d = hd[k] || { edges: [], values: [] };
      h.setData(d.edges, d.values);
      h.draw();
    }
  }

  function renderTiles(tiles) {
    const box = $('#tiles');
    box.innerHTML = '';
    for (const t of tiles) {
      const d = document.createElement('div');
      d.className = 'tile' + (t.warn ? ' warn' : '') + (t.now ? ' now' : '');
      const l = document.createElement('span'); l.textContent = t.label;
      const b = document.createElement('b'); b.textContent = t.value;
      if (t.unit) { const u = document.createElement('small'); u.textContent = ' ' + t.unit; b.appendChild(u); }
      d.append(l, b);
      if (t.sub) { const s = document.createElement('em'); s.textContent = t.sub; d.appendChild(s); }
      box.appendChild(d);
    }
  }

  $('#reset-zoom').addEventListener('click', () => view.group && view.group.setRange(null));

  function showHeader(title, sub, meta) {
    $('#view-title').textContent = title;
    $('#view-sub').textContent = sub;
    const dl = $('#meta-list');
    dl.innerHTML = '';
    const entries = Object.entries(meta || {}).filter(([k]) => k !== 'cols');
    for (const [k, v] of entries) {
      const dt = document.createElement('dt'); dt.textContent = k.replace(/_/g, ' ');
      const dd = document.createElement('dd'); dd.textContent = v;
      dl.append(dt, dd);
    }
    $('#meta').hidden = !entries.length;
  }

  // ----------------------------------------------------------------- CSV ---

  function parseCSV(text) {
    const lines = text.split(/\r?\n/).filter(l => l.trim() !== '');
    if (lines.length < 2) throw new Error('el CSV no tiene datos');
    const h0 = lines[0];
    const delim = (h0.match(/;/g) || []).length > (h0.match(/,/g) || []).length ? ';' : ',';
    const header = h0.split(delim).map(s => s.trim().replace(/^"|"$/g, ''));
    const tKey = header.includes('t_s') ? 't_s' : header[0];
    const tIdx = header.indexOf(tKey);
    const n = lines.length - 1;
    const cols = header.map(() => new Float64Array(n));
    let m = 0;
    for (let r = 1; r <= n; r++) {
      const p = lines[r].split(delim);
      const tv = p[tIdx] === undefined || p[tIdx].trim() === '' ? NaN : Number(p[tIdx]);
      if (tv !== tv) continue;   // fila sin tiempo: se descarta
      for (let j = 0; j < header.length; j++) {
        const s = p[j];
        cols[j][m] = s === undefined || s.trim() === '' ? NaN : Number(s);
      }
      m++;
    }
    const out = {};
    header.forEach((k, j) => { out[k] = cols[j].subarray(0, m); });
    const t = out[tKey];
    delete out[tKey];
    return { header, t, cols: out };
  }

  function parseMeta(text) {
    const meta = {};
    if (!text) return meta;
    for (const line of text.split(/\r?\n/)) {
      const k = line.indexOf(':');
      if (k > 0) meta[line.slice(0, k).trim()] = line.slice(k + 1).trim();
    }
    return meta;
  }

  function openCSV(name, text, metaText) {
    let parsed;
    try { parsed = parseCSV(text); } catch (e) { return fileMsg('No se pudo leer ' + name + ': ' + e.message, true); }
    disconnect();
    const sensor = Sensors.detect(parsed.header);
    const ds = { name, sensor: sensor.id, t: parsed.t, cols: parsed.cols, meta: parseMeta(metaText) };
    showHeader(name, sensor.name + ' · ' + ds.t.length + ' muestras', ds.meta);
    buildView(ds, sensor);
    fileMsg('');
  }

  function fileMsg(txt, err) {
    const m = $('#file-msg');
    m.textContent = txt; m.hidden = !txt; m.classList.toggle('err', !!err);
  }

  async function openFiles(list) {
    const files = [...list];
    const csv = files.find(f => /\.csv$/i.test(f.name)) || files.find(f => !/\.meta\.txt$/i.test(f.name));
    if (!csv) return fileMsg('Selecciona un fichero .csv', true);
    const meta = files.find(f => f !== csv && /\.meta\.txt$/i.test(f.name));
    openCSV(csv.name, await csv.text(), meta ? await meta.text() : null);
  }

  const drop = $('#drop');
  $('#file').addEventListener('change', e => { if (e.target.files.length) openFiles(e.target.files); e.target.value = ''; });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); openFiles(e.dataTransfer.files); });

  // Datos de ejemplo: misma forma que el backend 'sim' del script + baches.
  $('#demo').addEventListener('click', () => {
    const rows = ['t_s,echo_us,dist_mm,rel_mm'];
    const v = 343.4, ref = 250;
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let t = 0; t < 60; t += 0.025 + (rnd() - 0.5) * 0.002) {
      let d = ref + 40 * Math.sin(2 * Math.PI * 0.4 * t) + 8 * Math.sin(2 * Math.PI * 7 * t) + (rnd() - 0.5) * 2;
      const bump = t % 9;      // un bache cada 9 s: compresion rapida y extension
      if (bump < 0.6) d -= 70 * Math.sin(Math.PI * bump / 0.6) * Math.exp(-bump * 3);
      if (rnd() < 0.01) { rows.push(t.toFixed(4) + ',,,'); continue; }
      const us = d * 2000 / v;
      rows.push([t.toFixed(4), us.toFixed(0), d.toFixed(1), (d - ref).toFixed(1)].join(','));
    }
    openCSV('ejemplo_suspension.csv', rows.join('\n'),
      'backend: ejemplo\nperiodo_ms: 25\ntemp_c: 20\nreferencia_mm: 250.00');
  });

  // --------------------------------------------------------- servidor Pi ---

  function serverBase() {
    let s = $('#server').value.trim().replace(/\/+$/, '');
    if (s && !/^https?:\/\//.test(s)) s = 'http://' + s;
    return s;
  }
  $('#server').value = store('tele-server') || (location.protocol === 'http:' ? location.origin : '');
  $('#server').addEventListener('change', () => { store('tele-server', $('#server').value.trim()); listPiFiles(); });

  async function listPiFiles() {
    const base = serverBase(), box = $('#pi-files');
    if (!base) { box.hidden = true; return; }
    try {
      const r = await fetch(base + '/api/files');
      if (!r.ok) throw new Error(r.status);
      const files = await r.json();
      const ul = $('#pi-list');
      ul.innerHTML = '';
      for (const f of files) {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.className = 'link';
        b.textContent = f.name;
        b.addEventListener('click', () => loadPiFile(base, f));
        const s = document.createElement('span');
        s.textContent = new Date(f.mtime * 1000).toLocaleString() + ' · ' + (f.size / 1024).toFixed(0) + ' kB';
        li.append(b, s);
        ul.appendChild(li);
      }
      if (!files.length) ul.innerHTML = '<li class="muted">No hay CSV en la carpeta de datos.</li>';
      box.hidden = false;
    } catch (e) {
      box.hidden = true;   // no estamos servidos por la Pi: solo carga local
    }
  }
  $('#pi-refresh').addEventListener('click', listPiFiles);

  async function loadPiFile(base, f) {
    try {
      const enc = encodeURIComponent(f.name);
      const text = await (await fetch(base + '/files/' + enc)).text();
      const meta = f.meta ? await (await fetch(base + '/files/' + enc + '.meta.txt')).text() : null;
      openCSV(f.name, text, meta);
    } catch (e) { fileMsg('No se pudo descargar ' + f.name, true); }
  }

  // --------------------------------------------------------- tiempo real ---

  function setStatus(txt, cls) {
    const s = $('#live-status');
    s.textContent = txt; s.className = 'status ' + (cls || '');
  }

  function connect() {
    const base = serverBase();
    if (!base) return setStatus('Indica la dirección de la Raspberry', 'err');
    if (location.protocol === 'https:' && base.startsWith('http:'))
      return setStatus('El navegador bloquea http desde una página https: abre la web desde la Pi', 'err');
    store('tele-server', $('#server').value.trim());
    disconnect();
    live.session = null;
    live.es = new EventSource(base + '/stream');
    setStatus('Conectando…');
    $('#connect').textContent = 'Desconectar';
    live.es.onopen = () => setStatus(live.session ? 'En vivo' : 'Conectado · esperando sesión', 'ok');
    live.es.onerror = () => setStatus('Sin conexión · reintentando…', 'err');
    live.es.addEventListener('meta', e => {
      const m = JSON.parse(e.data);
      if (!m.session) return setStatus('Conectado · calibrando / esperando sesión', 'ok');
      if (m.session !== live.session) startLiveSession(m);
      setStatus('En vivo', 'ok');
    });
    live.es.onmessage = e => appendRows(JSON.parse(e.data).rows);
  }

  function disconnect() {
    if (live.es) { live.es.close(); live.es = null; }
    $('#connect').textContent = 'Conectar';
    $('#pause').disabled = true;
    setStatus('Desconectado');
    if (live.paused) togglePause();
  }

  function startLiveSession(m) {
    const sensor = Sensors.byId(m.sensor) || Sensors.detect(m.cols);
    live.session = m.session;
    live.cols = m.cols.slice(1);
    live.lastT = -Infinity;
    const cols = {};
    live.cols.forEach(c => { cols[c] = []; });
    live.ds = { name: m.session, sensor: sensor.id, t: [], cols, meta: m, live: true };
    showHeader('En vivo · ' + m.session, sensor.name, m);
    buildView(live.ds, sensor, { zoomable: false });
    $('#pause').disabled = false;
  }

  function appendRows(rows) {
    const ds = live.ds;
    if (!ds) return;
    for (const r of rows) {
      if (!(r[0] > live.lastT)) continue;   // descarta lo repetido al reconectar
      live.lastT = r[0];
      ds.t.push(r[0]);
      live.cols.forEach((c, j) => { const v = r[j + 1]; ds.cols[c].push(v == null ? NaN : v); });
    }
    if (ds.t.length > LIVE_MAX) {
      const k = ds.t.length - LIVE_MAX * 0.8;
      ds.t.splice(0, k);
      live.cols.forEach(c => ds.cols[c].splice(0, k));
    }
    live.dirty = true;
  }

  function liveFrame(now) {
    requestAnimationFrame(liveFrame);
    if (!live.dirty || live.paused || view.ds !== live.ds || now - live.lastDraw < 66) return;
    live.dirty = false; live.lastDraw = now;
    const t = live.ds.t;
    if (!t.length) return;
    const end = t[t.length - 1], win = +$('#win').value;
    view.group.range = [Math.max(t[0], end - win), Math.max(end, t[0] + win * 0.1)];
    recompute();
  }
  requestAnimationFrame(liveFrame);

  function togglePause() {
    live.paused = !live.paused;
    $('#pause').textContent = live.paused ? 'Seguir' : 'Pausar';
    if (view.group && view.ds === live.ds) {
      view.group.zoomable = live.paused;   // en pausa se puede ampliar
      if (!live.paused) live.dirty = true;
      updateRange();
    }
  }

  $('#connect').addEventListener('click', () => (live.es ? disconnect() : connect()));
  $('#pause').addEventListener('click', togglePause);
  $('#win').addEventListener('change', () => { live.dirty = true; });

  // ---------------------------------------------------------------- init ---

  applyTheme(theme);
  listPiFiles();
  if (location.hash === '#live') showTab('live');
})();
