/*
 * Telemetria: tiempo real (desde la Pi, con control de los modulos) y
 * sesiones grabadas (una carpeta con un CSV por sensor). Ambos modos
 * alimentan la misma vista: un bloque por sensor (cifras + graficas), todas
 * las graficas temporales con el mismo eje, cursor y zoom.
 * La Pi pide entrar con un usuario suyo: cada peticion lleva la sesion que
 * consigue cuenta.js (window.TelemetriaAcceso). En la wifi el vivo va por SSE;
 * por internet (tunel, que retiene el SSE) por consultas a /api/vivo.
 */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  const LIVE_KEEP_S = 300;  // segundos de cada sensor que se guardan en vivo
  // orden de los bloques en la vista (por tipo de sensor)
  const ORDEN = ['salida', 'suspension', 'rueda', 'imu', 'termopar', 'infrarrojos', 'boton', 'generic'];

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function el(tag, cls, parent, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  function storedList(k) { try { return JSON.parse(store(k) || '[]'); } catch (e) { return []; } }
  let hidden = new Set(storedList('tele-hidden'));
  let userOrder = storedList('tele-orden');   // ids de los bloques en el orden elegido
  const view = { sets: [], group: null, live: false, fichero: null };
  let tab = 'live';        // pestana visible: 'live' o 'file'
  let lastFile = null;     // ultima sesion abierta: {title, sub, sets}
  let analizado = null;    // tramo de Analizar trazas: [t0, t1] o 'todo'
  const live = {
    es: null, estado: null, sets: {}, salidas: {}, ctx: {}, vivos: {}, rows: {}, key: '',
    paused: false, dirty: false, lastDraw: 0, lastSession: null, control: true,
  };

  // --------------------------------------------------------------- tema ---

  const THEMES = ['auto', 'light', 'dark'];
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
    view.sets.forEach(s => Object.values(s.hists).forEach(h => h.draw()));
  }

  // ----------------------------------------------------------- pestanas ---

  /** Cada pestana ensena solo lo suyo: en vivo, los datos en vivo; en
   *  Sesiones, la sesion abierta. Al volver, lo que habia. */
  function showTab(name) {
    tab = name;
    document.querySelectorAll('[role=tab]').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === name));
    $('#pane-file').hidden = name !== 'file';
    $('#pane-live').hidden = name !== 'live';
    if (name === 'live') {
      if (live.es && !view.live) showLive();
    } else if (lastFile && view.fichero !== lastFile) {
      mostrarFichero(lastFile);
    } else if (!lastFile && view.live) {
      buildView([]);
    }
    $('#view').hidden = !view.sets.length || (name === 'live') !== view.live;
    $('#file-vacio').hidden = name !== 'file' || !!lastFile;
    dispatchEvent(new CustomEvent('tele-pestana', { detail: name }));   // cuenta.js: botones de tu raspi
  }

  function mostrarFichero(f) {
    buildView(f.sets);
    view.fichero = f;
    showHeader(f.title, f.sub, f.sets.map(s => [s.name, s.meta]));
  }

  /** Una sesion (CSV, de la Pi, de la nube o la de ejemplo): a la pestana Sesiones. */
  function abrirSesionEnVista(title, sub, sets, moto) {
    lastFile = { title, sub, sets, moto: moto || null };
    $('#otras').open = false;     // con una sesion abierta, lo de abrir CSV se pliega
    showTab('file');
  }
  document.querySelectorAll('[role=tab]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

  // --------------------------------------------------------------- vista ---

  /** Orden de los bloques: el que haya elegido el usuario y, si no, por tipo. */
  function orden(a, b) {
    const ua = userOrder.indexOf(a.ds.id), ub = userOrder.indexOf(b.ds.id);
    if (ua >= 0 || ub >= 0) return (ua < 0 ? Infinity : ua) - (ub < 0 ? Infinity : ub) || 0;
    const ka = ORDEN.indexOf(a.def.id), kb = ORDEN.indexOf(b.def.id);
    return ka - kb || a.ds.id.localeCompare(b.ds.id);
  }

  function loadOpts(def, ds) {
    const opt = {};
    def.options.forEach(o => { opt[o.id] = store('tele-opt-' + def.id + '-' + o.id) || o.value; });
    // si la sesion dice como esta montado el sensor, manda eso
    if (ds.meta && ds.meta.montaje && 'mount' in opt)
      opt.mount = ds.meta.montaje === 'aleja' ? 'farther' : 'closer';
    return opt;
  }

  /** Vista con un bloque por dataset. Conserva opciones de los que ya estaban. */
  function buildView(datasets, { isLive = false, zoomable = true, reloadOpts = false } = {}) {
    const prev = {};
    if (!reloadOpts) view.sets.forEach(s => { prev[s.ds.id] = s; });
    if (!isLive || !view.live) clearRange();
    if (isLive !== view.live || !isLive) cerrarAnalisis();
    view.live = isLive;
    view.sets = datasets.map(ds => {
      const def = Sensors.byId(ds.sensor) || Sensors.detect(Object.keys(ds.cols));
      const old = prev[ds.id];
      return { ds, def, opt: old && old.def === def ? old.opt : loadOpts(def, ds), charts: {}, hists: {}, derived: null, el: null };
    }).sort(orden);
    renderChips();
    renderBlocks(zoomable);
    $('#view').hidden = !view.sets.length;
    recomputeAll();
  }

  function clearRange() { if (view.group) view.group.range = null; }

  function renderChips() {
    const box = $('#chips');
    box.innerHTML = '';
    box.hidden = view.sets.length < 2;
    for (const s of view.sets) {
      const lab = el('label', 'chip', box);
      const cb = el('input', '', lab);
      cb.type = 'checkbox';
      cb.checked = !hidden.has(s.ds.id);
      lab.append(' ' + s.ds.name);
      cb.addEventListener('change', () => {
        if (cb.checked) hidden.delete(s.ds.id); else hidden.add(s.ds.id);
        store('tele-hidden', JSON.stringify([...hidden]));
        renderBlocks(view.group.zoomable);
        recomputeAll();
      });
    }
  }

  function renderBlocks(zoomable) {
    const range = view.group ? view.group.range : null;
    if (view.group) view.group.destroy();
    view.sets.forEach(s => Object.values(s.hists).forEach(h => h.destroy()));
    view.group = new Plot.ChartGroup();
    view.group.zoomable = zoomable;
    view.group.range = range;
    view.group.onRange(updateRange);

    const box = $('#blocks');
    box.innerHTML = '';
    for (const s of view.sets) {
      s.charts = {}; s.hists = {}; s.el = null;
      if (hidden.has(s.ds.id)) continue;
      const sec = el('section', 'block', box);
      sec.dataset.id = s.ds.id;
      const head = el('div', 'block-head', sec);
      const tit = el('div', 'block-title', head);
      const grip = el('button', 'grip', tit, '⠿');
      grip.title = 'Arrastra para mover el bloque';
      grip.setAttribute('aria-label', 'Mover ' + s.ds.name);
      dragBlock(grip, sec);
      // plegar el bloque entero tocando su nombre (se recuerda en este navegador)
      const h3 = el('h3', 'plegable', tit, s.ds.name);
      h3.setAttribute('role', 'button');
      h3.tabIndex = 0;
      const kPleg = 'tele-plegado-' + s.ds.id;
      const plegar = p => { sec.classList.toggle('plegado', p); h3.setAttribute('aria-expanded', String(!p)); };
      plegar(store(kPleg) === '1');
      const alternar = () => {
        const p = !sec.classList.contains('plegado');
        plegar(p);
        try { if (p) localStorage.setItem(kPleg, '1'); else localStorage.removeItem(kPleg); } catch (e) { /* sin almacenamiento */ }
      };
      h3.addEventListener('click', alternar);
      h3.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alternar(); } });
      if (s.def.name !== s.ds.name) el('p', 'muted', tit, s.def.name);
      const opts = el('div', 'bar', head);
      const tiles = el('div', 'tiles', sec);
      if (s.def.id === 'salida') {          // pantalla o luces: lo pinta renderOutputs
        const out = el('div', 'out-body', sec);
        if (s.ds.salida === 'tira') { el('div', 'strip', out); el('p', 'muted', out); }
        else { const i = el('img', 'oled', out); i.alt = 'Pantalla del cuadro'; }
        s.el = { sec, tiles, opts, out };
        continue;
      }
      // el diagrama g-g va el primero, antes de las graficas de tiempo
      const gBox = el('div', 'charts', sec), tBox = el('div', 'charts', sec), hBox = el('div', 'charts hist', sec);
      // compacto en pantalla grande (mas sensores a la vista); en el movil, a su tamano
      const escala = matchMedia('(max-width: 640px)').matches ? 1 : 0.75;
      for (const c0 of s.def.charts(s.ds)) {
        const c = Object.assign({}, c0, { height: Math.round((c0.height || 200) * escala), id: s.ds.id + ':' + c0.key });
        if (c.type === 'time') s.charts[c.key] = view.group.add(new Plot.TimeChart(tBox, c));
        else s.hists[c.key] = new (c.type === 'gg' ? Plot.GG : Plot.Histogram)(c.type === 'gg' ? gBox : hBox, c);
      }
      tBox.hidden = !Object.keys(s.charts).length;
      gBox.hidden = !s.def.charts(s.ds).some(c => c.type === 'gg');
      hBox.hidden = !s.def.charts(s.ds).some(c => c.type === 'hist');
      s.el = { sec, tiles, opts };
      renderOptions(s);
    }
    // nunca mas columnas que bloques: con pocos sensores, todo el ancho
    box.style.columnCount = Math.max(1, box.children.length);
  }

  /**
   * Arrastrar un bloque por su asa: se mueve en vivo entre los demas (raton y
   * tactil) y al soltar se guarda el orden.
   */
  function dragBlock(grip, sec) {
    grip.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      e.preventDefault();
      // en window y no con captura: al mover el bloque en el DOM se pierde la captura
      sec.classList.add('dragging');
      document.body.classList.add('dragging-block');
      const box = sec.parentNode;
      const move = ev => {
        const under = document.elementFromPoint(ev.clientX, ev.clientY);
        const tgt = under && under.closest('.block');
        if (tgt && tgt !== sec && tgt.parentNode === box) {
          const r = tgt.getBoundingClientRect();
          box.insertBefore(sec, ev.clientY < r.top + r.height / 2 ? tgt : tgt.nextSibling);
        }
        // desplaza la pagina al acercarse a los bordes
        if (ev.clientY < 60) window.scrollBy(0, -20);
        else if (ev.clientY > innerHeight - 60) window.scrollBy(0, 20);
      };
      const end = () => {
        removeEventListener('pointermove', move);
        removeEventListener('pointerup', end);
        removeEventListener('pointercancel', end);
        sec.classList.remove('dragging');
        document.body.classList.remove('dragging-block');
        saveOrder([...box.children].map(b => b.dataset.id));
      };
      addEventListener('pointermove', move);
      addEventListener('pointerup', end);
      addEventListener('pointercancel', end);
    });
  }

  function saveOrder(ids) {
    // los que no estan en pantalla (ocultos u otra sesion) conservan su sitio relativo
    userOrder = ids.concat(userOrder.filter(id => !ids.includes(id)));
    store('tele-orden', JSON.stringify(userOrder));
    view.sets.sort(orden);
    renderChips();
  }

  // -------------------------------------------------------------- ajustes ---

  function getSettings() {
    const opciones = {};
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k.startsWith('tele-opt-')) opciones[k.slice(9)] = localStorage.getItem(k);
      }
    } catch (e) { /* sin almacenamiento: solo lo de esta pagina */ }
    return {
      tipo: 'ajustes-telemetria', version: 1, guardado: new Date().toISOString(),
      orden: userOrder, ocultos: [...hidden], opciones, ventana: $('#win').value, tema: theme,
    };
  }

  function applySettings(a) {
    if (!a || typeof a !== 'object' || (a.tipo && a.tipo !== 'ajustes-telemetria')) throw new Error('no es un fichero de ajustes');
    userOrder = Array.isArray(a.orden) ? a.orden.map(String) : [];
    hidden = new Set(Array.isArray(a.ocultos) ? a.ocultos.map(String) : []);
    store('tele-orden', JSON.stringify(userOrder));
    store('tele-hidden', JSON.stringify([...hidden]));
    for (const [k, v] of Object.entries(a.opciones || {})) store('tele-opt-' + k, String(v));
    if (a.ventana && [...$('#win').options].some(o => o.value === String(a.ventana))) $('#win').value = String(a.ventana);
    if (THEMES.includes(a.tema)) { theme = a.tema; store('tele-theme', theme); applyTheme(theme); }
    if (view.sets.length) {
      buildView(view.sets.map(s => s.ds), { isLive: view.live, zoomable: view.group.zoomable, reloadOpts: true });
      live.dirty = true;
    }
  }

  function setMsg(txt, err) {
    const m = $('#set-msg');
    m.textContent = txt; m.hidden = !txt; m.classList.toggle('err', !!err);
  }

  $('#set-save-pi').addEventListener('click', async () => {
    const base = serverBase();
    if (!base) return setMsg('Entra con tu usuario y elige tu sistema de telemetría', true);
    try {
      const r = await piFetch('/api/ajustes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(getSettings()) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'HTTP ' + r.status);
      setMsg('Guardados en el sistema: cualquier navegador puede cargarlos.');
    } catch (e) { setMsg('No se pudieron guardar en el sistema: ' + e.message, true); }
  });

  $('#set-load-pi').addEventListener('click', async () => {
    const base = serverBase();
    if (!base) return setMsg('Entra con tu usuario y elige tu sistema de telemetría', true);
    try {
      const r = await piFetch('/api/ajustes');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const a = await r.json();
      if (!Object.keys(a).length) return setMsg('El sistema aún no tiene ajustes guardados.', true);
      applySettings(a);
      setMsg('Ajustes cargados del sistema' + (a.guardado ? ' (guardados ' + new Date(a.guardado).toLocaleString() + ')' : '') + '.');
    } catch (e) { setMsg('No se pudieron cargar: ' + e.message, true); }
  });

  $('#set-export').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(getSettings(), null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'ajustes-telemetria.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    setMsg('');
  });

  $('#set-import').addEventListener('change', async e => {
    const f = e.target.files[0];
    e.target.value = '';
    if (!f) return;
    try { applySettings(JSON.parse(await f.text())); setMsg('Ajustes cargados de ' + f.name + '.'); } catch (err) { setMsg('No se pudo cargar ' + f.name + ': ' + err.message, true); }
  });

  $('#set-reset').addEventListener('click', () => {
    userOrder = [];
    store('tele-orden', '[]');
    if (view.sets.length) buildView(view.sets.map(s => s.ds), { isLive: view.live, zoomable: view.group.zoomable });
    live.dirty = true;
    setMsg('Orden por defecto (por tipo de sensor).');
  });

  function renderOptions(s) {
    for (const o of s.def.options) {
      const lab = el('label', 'field', s.el.opts, o.label + ' ');
      const sel = el('select', '', lab);
      for (const [v, txt] of o.choices) sel.add(new Option(txt, v, false, v === s.opt[o.id]));
      sel.addEventListener('change', () => {
        s.opt[o.id] = sel.value;
        store('tele-opt-' + s.def.id + '-' + o.id, sel.value);
        recompute(s);
        updateRange();
        view.group.draw();
      });
    }
  }

  function recompute(s) {
    s.derived = s.def.derive(s.ds, s.opt);
    for (const [k, c] of Object.entries(s.charts)) c.setData(s.ds.t, s.derived[k]);
  }

  function recomputeAll() {
    view.sets.forEach(s => { if (s.el) recompute(s); });
    updateRange();
    view.group.draw();
  }

  function rangeIdx(t) {
    const r = view.group.range;
    if (!r) return [0, t.length];
    return [Plot.lowerBound(t, r[0]), Plot.lowerBound(t, r[1] + 1e-9)];
  }

  function updateRange() {
    const r = view.group.range;
    $('#range-label').textContent = view.live
      ? 'Últimos ' + $('#win').value + ' s' + (live.paused ? ' (en pausa)' : '')
      : r ? 'Tramo ' + r[0].toFixed(2) + ' – ' + r[1].toFixed(2) + ' s' : 'Todo el registro';
    $('#reset-zoom').hidden = !r || (view.live && !live.paused);
    $('#analizar').hidden = view.live && !live.paused;
    if (analizado) $('#analisis-otra').hidden = mismoTramo(analizado, tramoActual());
    pintarNav(r);

    for (const s of view.sets) {
      if (!s.el) continue;
      const [i0, i1] = rangeIdx(s.ds.t);
      const tiles = s.def.stats(s.ds, s.derived, i0, i1, s.opt);
      const first = Object.keys(s.charts)[0];
      if (view.live && first) {
        const y = s.derived[first];
        let now = NaN;
        for (let i = y.length - 1; i >= 0 && i >= y.length - 20; i--) if (y[i] === y[i]) { now = y[i]; break; }
        const c = s.charts[first].opts;
        tiles.unshift({ label: 'Ahora · ' + c.title, value: now === now ? now.toFixed(c.decimals) : '—', unit: c.unit, now: true });
      }
      renderTiles(s.el.tiles, tiles);
      const hd = s.def.histograms(s.derived, i0, i1, s.opt);
      for (const [k, h] of Object.entries(s.hists)) {
        const d = hd[k] || { edges: [], values: [] };
        h.setData(d.edges, d.values, d.ahora);
        h.draw();
      }
    }
  }

  // ------------------------------------------------ navegar por el tiempo ---
  // Con un tramo ampliado: pista con toda la sesion y la ventana visible, que
  // se arrastra (dedo o raton); botones de media ventana; trackpad horizontal.

  let navRaf = 0, navPend = null;

  function pintarNav(r) {
    const ok = !!r && view.group.zoomable && !(view.live && !live.paused);
    $('#nav').hidden = !ok;
    if (!ok) return;
    const [e0, e1] = view.group.extent(), sp = (e1 - e0) || 1;
    const v = $('#nav-ventana');
    v.style.left = Math.max(0, (r[0] - e0) / sp * 100) + '%';
    v.style.width = Math.min(100, (r[1] - r[0]) / sp * 100) + '%';
  }

  /** Lleva el tramo ampliado a 'inicio', con la misma anchura y sin salir de los datos. */
  function moverTramo(inicio) {
    const g = view.group, r = navPend || (g && g.range);
    if (!r) return;
    const [e0, e1] = g.extent(), w = r[1] - r[0];
    const a = Math.min(Math.max(inicio, e0), e1 - w);
    navPend = [a, a + w];
    if (!navRaf) navRaf = requestAnimationFrame(() => {
      navRaf = 0;
      const p = navPend; navPend = null;
      if (p && view.group.range) view.group.setRange(p);
    });
  }

  $('#nav-pista').addEventListener('pointerdown', e => {
    const g = view.group, r = g && g.range;
    if (!r) return;
    e.preventDefault();
    const pista = e.currentTarget;
    pista.setPointerCapture(e.pointerId);
    const caja = pista.getBoundingClientRect(), [e0, e1] = g.extent();
    const tEn = x => e0 + (x - caja.left) / caja.width * (e1 - e0);
    // se agarra la ventana por donde se toca; fuera de ella, salta a ese punto
    const ancla = e.target.id === 'nav-ventana' ? tEn(e.clientX) - r[0] : (r[1] - r[0]) / 2;
    if (e.target.id !== 'nav-ventana') moverTramo(tEn(e.clientX) - ancla);
    const mover = ev => moverTramo(tEn(ev.clientX) - ancla);
    const fin = () => {
      pista.removeEventListener('pointermove', mover);
      pista.removeEventListener('pointerup', fin);
      pista.removeEventListener('pointercancel', fin);
    };
    pista.addEventListener('pointermove', mover);
    pista.addEventListener('pointerup', fin);
    pista.addEventListener('pointercancel', fin);
  });
  const paso = dir => () => { const r = view.group && view.group.range; if (r) moverTramo(r[0] + dir * (r[1] - r[0]) / 2); };
  $('#nav-izq').addEventListener('click', paso(-1));
  $('#nav-der').addEventListener('click', paso(1));
  $('#blocks').addEventListener('wheel', e => {
    const r = view.group && view.group.range;
    if (!r || $('#nav').hidden || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;   // vertical: scroll normal
    e.preventDefault();
    const ancho = e.target.closest('.chart-wrap') ? e.target.closest('.chart-wrap').clientWidth : 600;
    const cur = navPend || r;
    moverTramo(cur[0] + e.deltaX / ancho * (cur[1] - cur[0]));
  }, { passive: false });

  function renderTiles(box, tiles) {
    box.innerHTML = '';
    for (const t of tiles) {
      const d = el('div', 'tile' + (t.warn ? ' warn' : '') + (t.now ? ' now' : ''), box);
      el('span', '', d, t.label);
      const b = el('b', '', d, t.value);
      if (t.unit) el('small', '', b, ' ' + t.unit);
      if (t.sub) el('em', '', d, t.sub);
    }
  }

  $('#reset-zoom').addEventListener('click', () => view.group && view.group.setRange(null));

  // ----------------------------------------------------- analizar trazas ---
  // Reglas de analisis.js sobre el tramo visible. El resultado se queda fijo
  // aunque se amplie o se mueva (para poder ir a cada momento con «Ver»); si
  // el tramo cambia, se ofrece analizar el nuevo.

  function tramoActual() { return view.group && view.group.range ? view.group.range.slice() : 'todo'; }
  function mismoTramo(a, b) { return a === b || (Array.isArray(a) && Array.isArray(b) && Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6); }

  function analizar() {
    const tramo = tramoActual();
    const lista = Analisis.analizar(view.sets.filter(s => s.derived && s.def.id !== 'salida'), tramo === 'todo' ? null : tramo, motoActual());
    analizado = tramo;
    $('#analisis-tramo').textContent = tramo === 'todo' ? '· toda la sesión' : '· tramo ' + tramo[0].toFixed(1) + ' – ' + tramo[1].toFixed(1) + ' s';
    const box = $('#analisis-lista');
    box.innerHTML = '';
    if (!lista.length) el('p', 'muted', box, 'No hay datos suficientes en este tramo para sacar conclusiones.');
    let tema = '';
    for (const h of lista) {
      if (h.tema !== tema) { tema = h.tema; el('h4', '', box, tema); }
      const d = el('div', 'hallazgo ' + h.nivel, box);
      el('b', '', d, h.titulo);
      el('p', '', d, h.texto);
      if (h.t === null && !h.ref) continue;
      const acc = el('div', 'acciones', d);
      if (h.t !== null) el('button', 'ghost small', acc, 'Ver').addEventListener('click', () => verInstante(h.t));
      if (h.ref) {
        const a = el('a', '', acc, 'Teoría en la formación ↗');
        a.href = Analisis.WEB + h.ref; a.target = '_blank'; a.rel = 'noopener';
      }
    }
    $('#analisis').hidden = false;
    $('#analisis-otra').hidden = true;
  }

  /** Amplia 20 s alrededor de t (sin salir de los datos). */
  function verInstante(t) {
    const [e0, e1] = view.group.extent(), w = Math.min(20, e1 - e0);
    const a = Math.min(Math.max(t - w / 2, e0), e1 - w);
    view.group.setRange([a, a + w]);
    $('#blocks').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function cerrarAnalisis() { analizado = null; $('#analisis').hidden = true; }

  $('#analizar').addEventListener('click', analizar);
  $('#analisis-otra').addEventListener('click', analizar);
  $('#analisis-cerrar').addEventListener('click', cerrarAnalisis);

  function showHeader(title, sub, metas) {
    $('#view-title').textContent = title;
    $('#view-sub').textContent = sub;
    const box = $('#meta-list');
    box.innerHTML = '';
    let n = 0;
    for (const [name, meta] of metas) {
      const entries = Object.entries(meta || {}).filter(([k]) => k !== 'cols');
      if (!entries.length) continue;
      n++;
      el('h4', '', box, name);
      const dl = el('dl', '', box);
      for (const [k, v] of entries) {
        el('dt', '', dl, k.replace(/_/g, ' '));
        el('dd', '', dl, Array.isArray(v) ? v.join(' · ') : v === null ? '—' : String(v));
      }
    }
    const tabParams = document.querySelector('[data-cfg="params"]');
    tabParams.hidden = !n;
    if (!n && cfgAbierta === 'params') abrirCfg(null);
    pintarCfgTabs();
    if (cfgAbierta === 'moto') abrirMoto();       // otra vista: su ficha
  }

  // ------------------------------------------------- pantalla completa ---
  // Solo la cabecera y los bloques de sensores (en vivo), y el navegador a
  // pantalla completa donde lo deja (en el iPhone, solo lo de la pagina).

  function modoCompleto(on) {
    document.body.classList.toggle('modo-completo', on);
    $('#completa').textContent = on ? '✕ Salir de pantalla completa' : '⛶ Pantalla completa';
    $('#completa').title = on ? 'Volver a ver los controles' : 'Solo los sensores, a toda la pantalla';
    const raiz = document.documentElement;
    if (on && raiz.requestFullscreen && !document.fullscreenElement) raiz.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    window.scrollTo(0, 0);
  }
  $('#completa').addEventListener('click', () => modoCompleto(!document.body.classList.contains('modo-completo')));
  // salir con Esc o con el gesto del sistema tambien quita el modo
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && document.body.classList.contains('modo-completo')) modoCompleto(false);
  });

  // ------------------------------------------------- pestanas de ajustes ---
  // Sensores · Pantalla y luces · Moto · Parametros de la sesion: plegables,
  // todas cerradas al empezar; pulsar la abierta la cierra. Las dos primeras
  // solo en vivo (hablan con el sistema).

  let cfgAbierta = null;

  function abrirCfg(id) {
    cfgAbierta = id;
    document.querySelectorAll('.cfg-tabs button').forEach(b => b.setAttribute('aria-expanded', b.dataset.cfg === id));
    document.querySelectorAll('.cfg-panel').forEach(p => { p.hidden = p.id !== 'cfg-' + id; });
    if (id === 'luces') {
      LucesCfg.abrir($('#luces-cfg'), {
        leer: async () => {
          const r = await piFetch('/api/luces');
          if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'HTTP ' + r.status);
          return r.json();
        },
        enviar: api,
        cerrar: () => abrirCfg(null),
      });
    } else if (id === 'moto') {
      abrirMoto();
    } else if (id === 'wifi') {
      pintarWifi();
    }
  }

  /** Pestana Wifi: red actual (wifi.py) y pedir la wifi propia para anadir otra. */
  function pintarWifi() {
    const w = live.estado && live.estado.wifi;
    const MODOS = { cliente: 'Conectada a', ap: 'Dando su propia wifi', conectando: 'Buscando', buscando: 'Buscando redes', sin_red: 'Sin red' };
    $('#wifi-estado').textContent = !w ? 'El servicio de wifi no está en este sistema.'
      : (MODOS[w.modo] || w.modo) + (w.ssid ? ' ' + w.ssid : '') + '.';
    $('#wifi-propia').disabled = !w;
  }
  $('#wifi-propia').addEventListener('click', async () => {
    if (!confirm('La moto dejará la red actual y creará su propia wifi: esta conexión se cortará. Conéctate a la wifi de la moto (nombre y clave en su pantalla) y elige la red nueva. ¿Seguir?')) return;
    try {
      await api('/api/wifi', { accion: 'propia' });
      $('#wifi-msg').textContent = 'En unos segundos la moto da su wifi: mira su pantalla.';
      $('#wifi-msg').classList.remove('err');
    } catch (e) {
      $('#wifi-msg').textContent = 'No se pudo: ' + e.message;
      $('#wifi-msg').classList.add('err');
    }
  });

  /** Ficha de la moto de lo que se ve: la del sistema en vivo o la de la sesion. */
  function motoActual() {
    if (view.live) return (live.estado && live.estado.moto) || null;
    return (view.fichero && view.fichero.moto) || null;
  }

  function abrirMoto() {
    const caja = $('#moto-cfg');
    if (view.live && live.estado && live.control) {
      MotoCfg.abrir(caja, live.estado.moto, {
        guardar: async f => {
          const r = await api('/api/moto', { moto: f });
          live.estado.moto = f;
          return r;
        },
      });
    } else {
      MotoCfg.abrir(caja, motoActual());
    }
  }

  /** Que pestanas se ven: las del sistema solo en vivo y con control. */
  function pintarCfgTabs() {
    const vivo = view.live && !!live.estado;
    $('#completa').hidden = !vivo;
    if (!vivo && document.body.classList.contains('modo-completo')) modoCompleto(false);
    document.querySelectorAll('.cfg-tabs .solo-vivo').forEach(b => { b.hidden = !vivo || !live.control; });
    const abierta = document.querySelector('.cfg-tabs [data-cfg="' + cfgAbierta + '"]');
    if (cfgAbierta && (!abierta || abierta.hidden)) abrirCfg(null);
  }

  document.querySelectorAll('.cfg-tabs button').forEach(b => b.addEventListener('click', () =>
    abrirCfg(cfgAbierta === b.dataset.cfg ? null : b.dataset.cfg)));

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

  /**
   * files: [{name, text}] con los CSV, y opcionalmente sesion.json y .meta.txt.
   * Devuelve {sets, avisos}. El tipo de cada CSV sale de sesion.json o, si no
   * esta, de sus columnas.
   */
  function datasetsFromFiles(files) {
    const sjFile = files.find(f => /\.json$/i.test(f.name));
    let sj = null;
    if (sjFile) { try { sj = JSON.parse(sjFile.text); } catch (e) { sj = null; } }
    const ctx = (sj && sj.modulos) || {};
    const csvs = files.filter(f => /\.csv$/i.test(f.name));
    const metaTxt = files.find(f => /\.meta\.txt$/i.test(f.name));
    const sets = [], avisos = [];
    for (const f of csvs) {
      let p;
      try { p = parseCSV(f.text); } catch (e) { avisos.push(f.name + ': ' + e.message); continue; }
      const id = f.name.replace(/\.csv$/i, '');
      const info = ctx[id];
      const def = (info && Sensors.byId(info.tipo)) || Sensors.detect(p.header);
      const meta = info ? info.meta : metaTxt && csvs.length === 1 ? parseMeta(metaTxt.text) : {};
      sets.push({ id, name: info ? info.nombre : f.name, sensor: def.id, t: p.t, cols: p.cols, meta, ctx });
    }
    return { sets, avisos, sj };
  }

  function openFiles(title, files, nota) {
    const { sets, avisos, sj } = datasetsFromFiles(files);
    if (!sets.length) return fileMsg('No hay ningún CSV con datos' + (avisos.length ? ' (' + avisos.join('; ') + ')' : ''), true);
    if (live.paused) togglePause();
    const sub = sets.length + (sets.length === 1 ? ' sensor' : ' sensores') +
      (sj && sj.inicio ? ' · ' + sj.inicio.replace('T', ' ') : '') + (sj && sj.simulada ? ' · simulada' : '') +
      (nota ? ' — ' + nota : '');
    abrirSesionEnVista(title, sub, sets, sj && sj.moto);
    fileMsg(avisos.length ? 'Sin datos: ' + avisos.join('; ') : '');
  }

  function fileMsg(txt, err) {
    const m = $('#file-msg');
    m.textContent = txt; m.hidden = !txt; m.classList.toggle('err', !!err);
  }

  async function openLocalFiles(list) {
    const files = await Promise.all([...list].map(async f => ({ name: f.name, text: await f.text() })));
    const csvs = files.filter(f => /\.csv$/i.test(f.name));
    if (!csvs.length) return fileMsg('Selecciona al menos un fichero .csv', true);
    openFiles(csvs.length === 1 ? csvs[0].name : csvs.length + ' ficheros', files);
  }

  const drop = $('#drop');
  $('#file').addEventListener('change', e => { if (e.target.files.length) openLocalFiles(e.target.files); e.target.value = ''; });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); openLocalFiles(e.dataTransfer.files); });

  // Sesion de ejemplo: la misma vuelta que el modo --sim de la Pi (modulos/sim.py).
  $('#demo').addEventListener('click', () => {
    const VEL = [[0, 60], [10, 160], [13, 60], [20, 60], [28, 140], [30, 70], [38, 70], [48, 150], [51, 60], [60, 60]];
    const INC = [[0, 0], [12.5, 0], [14, 40], [19, 40], [20.5, 0], [29.5, 0], [31, -35], [37, -35], [38.5, 0], [50.5, 0], [52, 30], [58.5, 30], [60, 0]];
    const ip = (pts, x) => {
      for (let k = 0; k < pts.length - 1; k++) {
        const [x0, y0] = pts[k], [x1, y1] = pts[k + 1];
        if (x >= x0 && x <= x1) return y0 + (y1 - y0) * (1 - Math.cos(Math.PI * (x - x0) / (x1 - x0))) / 2;
      }
      return pts[pts.length - 1][1];
    };
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const noise = s => (rnd() - 0.5) * 2 * s;
    const pista = t => {
      const x = t % 60, kmh = ip(VEL, x);
      return { kmh, acel: (ip(VEL, (x + 0.05) % 60) - ip(VEL, (x + 59.95) % 60)) / 0.1 / 3.6 / 9.81, incl: ip(INC, x) };
    };
    const DUR = 120, mk = (id, sensor, name, cols, hz, fn, meta) => {
      const t = [], c = {};
      cols.forEach(k => { c[k] = []; });
      for (let s = 0; s < DUR; s += 1 / hz) {
        const v = fn(s, pista(s));
        t.push(s); cols.forEach((k, j) => c[k].push(v[j]));
      }
      return { id, name, sensor, t, cols: c, meta: meta || {} };
    };
    let fase = 0, tPrev = 0, disco = 40;
    const sets = [
      mk('suspension', 'suspension', 'Suspensión trasera (ultrasonidos)', ['echo_us', 'dist_mm', 'rel_mm'], 40, (s, p) => {
        const f9 = s % 9, bache = f9 < 1 ? 45 * Math.exp(-5 * f9) * Math.min(1, f9 / 0.05) : 0;
        const comp = 25 * p.acel + 8 * Math.min(1, Math.abs(Math.tan(p.incl * Math.PI / 180))) + bache + noise(1);
        if (rnd() < 0.01) return [NaN, NaN, NaN];
        const d = 250 - comp;
        return [d * 2000 / 343.4, d, -comp];
      }, { referencia_mm: 250, montaje: 'acerca' }),
      mk('rueda_tras', 'rueda', 'Rueda trasera (Hall)', ['pulsos', 'periodo_ms', 'rpm', 'kmh', 'dist_m'], 20, (s, p) => {
        const kmh = p.kmh * (1 + 0.08 * Math.max(0, p.acel));
        fase += kmh / 3.6 * (s - tPrev) / 1.95; tPrev = s;
        return [Math.floor(fase), 1950 / (kmh / 3.6), kmh / 3.6 / 1.95 * 60, kmh, Math.floor(fase) * 1.95];
      }),
      mk('imu', 'imu', 'Acelerómetro / giroscopio MPU6050', ['ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps', 'incl_deg', 'cabeceo_deg'], 50, (s, p) => {
        const fi = p.incl * Math.PI / 180, w = -9.81 * Math.tan(fi) / Math.max(p.kmh / 3.6, 1);
        return [p.acel + noise(0.03), noise(0.03), 1 / Math.cos(fi) + noise(0.05), noise(0.8),
          w * Math.sin(fi) * 57.3 + noise(0.5), w * Math.cos(fi) * 57.3 + noise(0.5), p.incl + noise(0.5), 2.5 * p.acel + noise(0.2)];
      }),
      mk('ir', 'infrarrojos', 'Temperatura IR (MLX90614)', ['obj_c', 'amb_c'], 10, (s, p) => {
        disco += (25 * Math.max(0, -p.acel) * p.kmh / 100 - (disco - 30) * 0.03) * 0.1;
        return [disco + noise(0.3), 28 + noise(0.05)];
      }, { apunta_a: 'disco de freno' }),
      mk('temp_bujia', 'termopar', 'Temperatura bujía (sonda K)', ['temp_c'], 4, (s, p) => [Math.round((150 + 40 * p.kmh / 160 - 60 * Math.exp(-s / 40) + noise(0.4)) * 4) / 4]),
    ];
    abrirSesionEnVista('Sesión de ejemplo', sets.length + ' sensores · 2 vueltas simuladas', sets);
    fileMsg('');
  });

  // --------------------------------------------------------- servidor Pi ---

  function serverBase() {
    let s = $('#server').value.trim().replace(/\/+$/, '');
    if (s && !/^https?:\/\//.test(s)) s = location.protocol + '//' + s;
    return s;
  }
  // la sirve la propia raspi: por su puerto (wifi) o por su tunel
  const servedByPi = location.protocol.startsWith('http') && !/github\.io$/.test(location.hostname) &&
    (location.port !== '' || /\.trycloudflare\.com$/.test(location.hostname));
  $('#server').value = store('tele-server') || (servedByPi ? location.origin : '');
  $('#server').addEventListener('change', () => { store('tele-server', $('#server').value.trim()); listPiFiles(); });
  $('#check').addEventListener('click', () => { store('tele-server', $('#server').value.trim()); listPiFiles(); });

  /** Problema conocido de la conexion con la Pi, o '' si no se detecta. */
  function mixedContent(base) {
    return location.protocol === 'https:' && base.startsWith('http:')
      ? 'Desde la app (https) el navegador no deja hablar con el sistema por http.' : '';
  }

  /** Enlace para abrir la web de la propia raspi (mismo wifi): alli va el modo en vivo. */
  function piLink(p, base) {
    const a = document.createElement('a');
    a.href = base + '/'; a.textContent = 'Abre la web del sistema';
    p.append(' ', a, ' para el modo en vivo (o arráncalo con --https).');
  }

  function setConn(txt, cls, certBase) {
    $('#conn-sum').textContent = cls === 'ok' ? '· ' + serverBase() + ' · accesible'
      : cls === 'err' ? '· ' + (serverBase() || 'sin dirección') + ' · sin conexión' : '';
    if (cls === 'err') $('#conn-box').open = true;   // que se vea el motivo
    const p = $('#conn-status');
    p.hidden = !txt;
    p.className = 'status ' + (cls || '');
    p.textContent = txt;
    if (certBase) {
      const a = document.createElement('a');
      a.href = certBase + '/'; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = 'abre ' + certBase + ' y acepta el certificado';
      p.append(' Si el sistema usa certificado autofirmado, ', a, ' y vuelve a pulsar «Comprobar».');
    }
  }

  /** Peticion a la raspi con la sesion de tu usuario; si ha caducado, se rehace una vez. */
  async function piFetch(path, opts = {}, base = serverBase()) {
    const A = window.TelemetriaAcceso;
    for (let intento = 0; intento < 2; intento++) {
      const headers = Object.assign({}, opts.headers || {}, A ? await A.cabeceras(base) : {});
      const r = await fetch(base + path, Object.assign({}, opts, { headers, cache: 'no-store' }));
      if (r.status !== 401 || !A) return r;
      A.olvidar(base);
    }
    throw new Error('entra con tu usuario de este sistema');
  }

  /** Raspi en la misma red (va por SSE) o por internet (consultas). */
  function esLocal(base) {
    const h = new URL(base).hostname;
    return /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h) || h.endsWith('.local');
  }

  let piSessions = [];
  async function listPiFiles() {
    const base = serverBase(), box = $('#pi-files');
    if (!base) { box.hidden = true; setConn(''); return; }
    const mixed = mixedContent(base);
    if (mixed) { box.hidden = true; setConn(mixed, 'err'); piLink($('#conn-status'), base); return; }
    try {
      const r = await piFetch('/api/sesiones', {}, base);
      if (r.status === 401) { box.hidden = true; setConn('Entra con tu usuario para ver este sistema.'); return; }
      if (!r.ok) throw new Error(r.status);
      piSessions = await r.json();
      const ul = $('#pi-list');
      ul.innerHTML = '';
      for (const f of piSessions) {
        const li = el('li', '', ul);
        const b = el('button', 'link', li, f.name);
        b.addEventListener('click', () => loadPiEntry(base, f));
        el('span', '', li, (f.kind === 'sesion' ? f.files.length + (f.files.length === 1 ? ' sensor · ' : ' sensores · ') : 'CSV antiguo · ') +
          new Date(f.mtime * 1000).toLocaleString() + ' · ' + (f.size / 1024).toFixed(0) + ' kB' +
          (f.subida === true ? ' · en la nube' : f.subida === false ? ' · sin subir' : ''));
        if (f.kind === 'sesion') {
          const x = el('button', 'ghost small borrar', li, 'Borrar');
          x.title = 'Borrar la copia guardada en el sistema';
          x.addEventListener('click', () => borrarDeRaspi(f, li, x));
        }
      }
      if (!piSessions.length) el('li', 'muted', ul, 'No hay sesiones en la carpeta de datos.');
      box.hidden = false;
      setConn('Sistema accesible · ' + piSessions.length + ' sesiones guardadas', 'ok');
    } catch (e) {
      box.hidden = true;
      if (/^Entra/.test(e.message)) return setConn(e.message + '.');
      setConn('No conecto con ' + base + '.', 'err', base.startsWith('https:') && esLocal(base) ? base : null);
    }
  }
  $('#pi-refresh').addEventListener('click', listPiFiles);

  async function borrarDeRaspi(f, li, boton) {
    const aviso = f.subida === false
      ? '\n\n⚠ Esta sesión AÚN NO está en la nube: si la borras, se pierde.'
      : f.subida ? '\n\nLa copia de la nube no se borra.' : '';
    if (!confirm('¿Borrar ' + f.name + ' del sistema?' + aviso + '\n\nNo se puede deshacer.')) return;
    boton.disabled = true;
    try {
      const j = await api('/api/sesion/borrar', { nombre: f.name });
      li.remove();
      fileMsg(j.mensaje + '.');
    } catch (e) {
      boton.disabled = false;
      fileMsg('No se pudo borrar: ' + e.message, true);
    }
  }

  async function fetchText(base, path) {
    const r = await piFetch(path, {}, base);
    if (!r.ok) throw new Error(r.status);
    return r.text();
  }

  async function loadPiEntry(base, f) {
    const url = n => '/files/' + n.split('/').map(encodeURIComponent).join('/');
    showTab('file');
    fileMsg('Descargando ' + f.name + '…');
    try {
      let files;
      if (f.kind === 'sesion') {
        const names = f.files.map(n => f.name + '/' + n);
        if (f.json) names.push(f.name + '/sesion.json');
        files = await Promise.all(names.map(async n => ({ name: n.split('/')[1], text: await fetchText(base, url(n)) })));
      } else {
        files = [{ name: f.name, text: await fetchText(base, url(f.name)) }];
        if (f.meta) files.push({ name: f.name + '.meta.txt', text: await fetchText(base, url(f.name + '.meta.txt')).catch(() => '') });
      }
      openFiles(f.name, files);
    } catch (e) {
      fileMsg('No se pudo descargar ' + f.name, true);
    }
  }

  async function api(path, body) {
    const r = await piFetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (r.status === 404) live.control = false;
      throw new Error(j.error || 'HTTP ' + r.status);
    }
    return j;
  }

  async function control(path, body, what) {
    try {
      const j = await api(path, body);
      if (j.mensaje) setStatus(what + ': ' + j.mensaje, 'ok');
    } catch (e) {
      setStatus(what + ': ' + e.message, 'err');
    }
  }

  // --------------------------------------------------------- tiempo real ---

  function setStatus(txt, cls) {
    const s = $('#live-status');
    s.textContent = txt; s.className = 'status ' + (cls || '');
  }

  async function connect() {
    const base = serverBase();
    if (!base) return setStatus('Entra con tu usuario y elige tu sistema de telemetría', 'err');
    const mixed = mixedContent(base);
    if (mixed) { setStatus(mixed, 'err'); piLink($('#live-status'), base); return; }
    store('tele-server', $('#server').value.trim());
    disconnect();
    live.sets = {}; live.salidas = {}; live.vivos = {}; live.key = ''; live.control = true;
    const con = live.es = { close() { con.cerrada = true; } };   // ya cuenta como conectado
    setStatus('Conectando…');
    $('#connect').textContent = 'Desconectar';
    showTab('live');
    let s = null;
    try { s = window.TelemetriaAcceso ? await window.TelemetriaAcceso.sesion(base) : null; } catch (e) {
      if (live.es !== con) return;
      disconnect();
      setStatus(/^Entra/.test(e.message) ? e.message + ' (botón «Entrar» arriba).' : 'No conecto con ' + base + '.', 'err');
      if (!/^Entra/.test(e.message)) listPiFiles();   // arriba el motivo / enlace al certificado
      return;
    }
    if (live.es !== con || con.cerrada) return;
    live.es = esLocal(base) ? streamSSE(base, s) : sondeo(base);
  }

  /** En la misma red: Server-Sent Events (EventSource no deja cabeceras: sesion en ?s=). */
  function streamSSE(base, s) {
    const es = new EventSource(base + '/stream' + (s ? '?s=' + encodeURIComponent(s) : ''));
    es.onopen = () => setStatus('En vivo', 'ok');
    es.onerror = () => {
      setStatus('Sin conexión · reintentando…', 'err');
      if (!live.estado) listPiFiles();
    };
    es.addEventListener('estado', e => onEstado(JSON.parse(e.data)));
    es.addEventListener('vivo', e => { Object.assign(live.vivos, JSON.parse(e.data)); renderOutputs(); });
    es.onmessage = e => appendRows(JSON.parse(e.data).d);
    return es;
  }

  /** Por internet: consultas a /api/vivo (~4 por segundo) con lo nuevo desde la anterior. */
  function sondeo(base) {
    const c = { cerrada: false, close() { c.cerrada = true; } };
    const id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    let fallos = 0;
    (async () => {
      while (!c.cerrada) {
        const t0 = performance.now();
        try {
          const r = await piFetch('/api/vivo?c=' + id + '&n=400', {}, base);
          if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'HTTP ' + r.status);
          const j = await r.json();
          if (c.cerrada) break;
          if (fallos && live.estado) onEstado(live.estado);   // quita el aviso de error
          fallos = 0;
          if (j.estado) onEstado(j.estado);
          if (j.vivos) { Object.assign(live.vivos, j.vivos); renderOutputs(); }
          if (j.d && Object.keys(j.d).length) appendRows(j.d);
        } catch (e) {
          if (c.cerrada) break;
          fallos++;
          setStatus('Sin conexión · reintentando…', 'err');
        }
        const espera = fallos ? Math.min(5000, 500 * fallos) : 250;
        await new Promise(res => setTimeout(res, Math.max(0, espera - (performance.now() - t0))));
      }
    })();
    return c;
  }

  function disconnect() {
    if (live.es) { live.es.close(); live.es = null; }
    live.estado = null;
    $('#connect').textContent = 'Conectar';
    $('#pause').disabled = true;
    $('#rec').disabled = true;
    pintarCfgTabs();
    $('#open-full').disabled = !live.lastSession;
    setStatus('Desconectado');
    if (live.paused) togglePause();
  }

  function modInfo(id) {
    return live.estado && live.estado.modulos.find(m => m.id === id);
  }

  /** Dataset en vivo de un modulo (se crea al ver sus columnas). */
  function ensureSet(id) {
    if (live.sets[id]) return live.sets[id];
    const m = modInfo(id);
    if (!m || !m.cols.length) return null;
    const cols = {};
    m.cols.slice(1).forEach(c => { cols[c] = []; });
    live.sets[id] = { id, name: m.nombre, sensor: m.tipo, t: [], cols, meta: m.meta, ctx: live.ctx, live: true, lastT: -Infinity };
    return live.sets[id];
  }

  function ensureSalida(m) {
    if (!live.salidas[m.id]) live.salidas[m.id] = { id: m.id, name: m.nombre, sensor: 'salida', salida: m.tipo, t: [], cols: {}, meta: {}, ctx: live.ctx, live: true, lastT: -Infinity };
    return live.salidas[m.id];
  }

  function onEstado(e) {
    live.estado = e;
    live.ctx = {};
    for (const m of e.modulos) live.ctx[m.id] = { tipo: m.tipo, nombre: m.nombre, meta: m.meta };
    for (const m of e.modulos) {
      const s = live.sets[m.id];
      if (s) { s.meta = m.meta; s.ctx = live.ctx; s.name = m.nombre; }
    }
    if (e.sesion) live.lastSession = e.sesion.nombre;
    $('#open-full').disabled = !live.lastSession;
    $('#pause').disabled = false;
    setStatus((e.sim ? 'En vivo · SIMULADO' : 'En vivo') +
      (e.sesion ? ' · grabando ' + e.sesion.nombre + ' (' + Math.round(e.sesion.duracion_s) + ' s)' : ' · sin grabar'), 'ok');
    renderRec(e);
    renderPanel(e);
    renderOutputs();
    if (tab === 'live') showLive();     // en Sesiones no se toca la sesion abierta
  }

  /** Pone en la vista los sensores que estan en marcha (si han cambiado). */
  function showLive() {
    if (!live.estado) return;
    const ids = live.estado.modulos.filter(m => m.corriendo && m.cols.length).map(m => m.id);
    const datos = ids.map(ensureSet).filter(Boolean);
    // pantalla y luces: bloques sin datos que replican el cuadro
    const salidas = live.estado.modulos.filter(m => m.corriendo && m.clase === 'salida').map(ensureSalida);
    const sets = datos.concat(salidas);
    const key = ids.concat(salidas.map(s => s.id)).join(',');
    if (key === live.key && view.live) {
      // solo cambian metas (p. ej. umbrales): se repinta con el siguiente frame
      live.dirty = true;
      return;
    }
    live.key = key;
    buildView(sets, { isLive: true, zoomable: live.paused });
    view.fichero = null;
    showHeader('En vivo', datos.length ? datos.length + (datos.length === 1 ? ' sensor activo' : ' sensores activos')
      : 'Ningún sensor en marcha: actívalos en la pestaña Sensores', datos.map(s => [s.name, s.meta]));
    $('#view').hidden = false;
    renderOutputs();
    live.dirty = true;
  }

  function appendRows(d) {
    for (const [id, rows] of Object.entries(d)) {
      const s = ensureSet(id);
      if (!s) continue;
      const names = Object.keys(s.cols);
      for (const r of rows) {
        if (!(r[0] > s.lastT)) continue;   // descarta lo repetido al reconectar
        s.lastT = r[0];
        s.t.push(r[0]);
        names.forEach((c, j) => { const v = r[j + 1]; s.cols[c].push(v == null ? NaN : v); });
      }
      const k = Plot.lowerBound(s.t, s.lastT - LIVE_KEEP_S);
      if (k > 500) { s.t.splice(0, k); names.forEach(c => s.cols[c].splice(0, k)); }
    }
    live.dirty = true;
  }

  function liveFrame(now) {
    requestAnimationFrame(liveFrame);
    if (!live.dirty || live.paused || !view.live || now - live.lastDraw < 66) return;
    live.dirty = false; live.lastDraw = now;
    let end = -Infinity, start = Infinity;
    for (const s of view.sets) if (s.ds.t.length) { end = Math.max(end, s.ds.lastT); start = Math.min(start, s.ds.t[0]); }
    if (!(end > -Infinity)) return;
    const win = +$('#win').value;
    view.group.range = [Math.max(start, end - win), Math.max(end, start + win * 0.1)];
    recomputeAll();
  }
  requestAnimationFrame(liveFrame);

  function togglePause() {
    live.paused = !live.paused;
    $('#pause').textContent = live.paused ? 'Seguir' : 'Pausar';
    if (view.group && view.live) {
      view.group.zoomable = live.paused;   // en pausa se puede ampliar
      if (!live.paused) live.dirty = true;
      updateRange();
    }
  }

  // ------------------------------------------------ panel de modulos ---

  const DETECCION = {
    si: 'Detectado', no: 'No detectado', manual: 'Sin autodetección: actívalo a mano',
    error: 'Error al detectar', pendiente: '',
  };

  function modStatus(m) {
    if (m.estado === 'error') return ['err', 'Error: ' + m.error];
    if (m.corriendo) {
      const aviso = m.aviso ? ' · ⚠ ' + m.aviso : '';
      if (m.estado === 'calibrando') return ['cal', 'Calibrando · moto quieta' + aviso];
      if (m.clase === 'salida') return [m.aviso ? 'warn' : 'ok', 'En marcha' + aviso];
      if (m.tipo === 'boton') return ['ok', 'Esperando pulsaciones' + aviso];
      const perd = m.perdidas_pct >= 1 ? ' · ' + m.perdidas_pct.toFixed(0) + '% sin dato' : '';
      return [m.aviso || m.perdidas_pct > 10 ? 'warn' : 'ok', m.hz.toFixed(m.hz < 10 ? 1 : 0) + ' Hz' + perd + aviso];
    }
    const [d, det] = m.deteccion;
    const txt = (DETECCION[d] || d) + (det && d !== 'manual' ? ' · ' + det : '');
    return [d === 'si' ? 'idle' : d === 'manual' ? 'manual' : 'off', 'Parado · ' + txt];
  }

  function renderPanel(e) {
    pintarCfgTabs();
    const marcha = e.modulos.filter(m => m.corriendo).length;
    const errores = e.modulos.filter(m => m.estado === 'error').length;
    $('#panel-sum').textContent = '· ' + marcha + '/' + e.modulos.length +
      (errores ? ' · ' + errores + (errores === 1 ? ' con error' : ' con errores') : '');
    const ul = $('#mods');
    const order = ['sensor', 'salida'];
    const ids = e.modulos.map(m => m.clase + ':' + m.id).join(',');
    if (ul.dataset.ids !== ids) {         // la lista cambia poco: se rehace solo entonces
      ul.dataset.ids = ids;
      ul.innerHTML = '';
      live.rows = {};
      for (const clase of order) {
        const mods = e.modulos.filter(m => m.clase === clase);
        if (!mods.length) continue;
        el('li', 'mods-group', ul, clase === 'sensor' ? 'Sensores' : 'Salidas del cuadro');
        for (const m of mods) live.rows[m.id] = modRow(ul, m);
      }
    }
    for (const m of e.modulos) updateRow(live.rows[m.id], m);
  }

  function modRow(ul, m) {
    const li = el('li', 'mod', ul);
    const lab = el('label', 'mod-main', li);
    const cb = el('input', '', lab);
    cb.type = 'checkbox';
    const dot = el('i', 'dot', lab);
    const txt = el('span', 'mod-txt', lab);
    const name = el('b', '', txt);
    const pins = el('small', '', txt);
    const status = el('em', '', txt);
    const side = el('div', 'mod-side', li);
    const mode = el('button', 'ghost small mode', side);
    const acts = el('span', 'mod-acts', side);
    const row = { li, cb, dot, name, pins, status, mode, acts, actsKey: null, m };
    cb.addEventListener('change', () => {
      cb.disabled = true;
      control('/api/modulo/' + encodeURIComponent(row.m.id), { activo: cb.checked }, row.m.nombre);
    });
    mode.addEventListener('click', () => {
      if (row.m.activo !== 'auto') control('/api/modulo/' + encodeURIComponent(row.m.id), { activo: 'auto' }, row.m.nombre);
    });
    return row;
  }

  function updateRow(row, m) {
    row.m = m;
    const [cls, txt] = modStatus(m);
    row.li.className = 'mod ' + cls;
    row.cb.checked = m.corriendo;
    row.cb.disabled = !live.control;
    row.dot.className = 'dot ' + cls;
    row.name.textContent = m.nombre;
    row.pins.textContent = m.pines;
    row.status.textContent = txt;
    row.mode.textContent = m.activo === 'auto' ? 'auto' : m.activo ? 'forzado: on' : 'forzado: off';
    row.mode.title = m.activo === 'auto' ? 'Arranca solo si se detecta conectado' : 'Pulsa para volver a automático';
    row.mode.disabled = m.activo === 'auto' || !live.control;
    const key = m.corriendo + '|' + m.acciones.map(a => a.id).join(',');
    if (key !== row.actsKey) {
      row.actsKey = key;
      row.acts.innerHTML = '';
      if (m.corriendo) for (const a of m.acciones) {
        const b = el('button', 'ghost small', row.acts, a.texto);
        b.addEventListener('click', () => control('/api/modulo/' + encodeURIComponent(m.id) + '/accion', { accion: a.id }, m.nombre));
      }
    }
  }

  function renderRec(e) {
    const b = $('#rec');
    b.disabled = !live.control;
    b.textContent = e.sesion ? '■ Parar grabación' : '● Grabar';
    b.classList.toggle('ghost', !e.sesion);
    b.classList.toggle('danger', !!e.sesion);
  }

  $('#rec').addEventListener('click', () => {
    const grabando = !!(live.estado && live.estado.sesion);
    control('/api/grabar', { grabar: !grabando }, grabando ? 'Parar' : 'Grabar').then(listPiFiles);
  });
  $('#detect').addEventListener('click', () => control('/api/detectar', {}, 'Autodetectar'));
  $('#all-auto').addEventListener('click', () => control('/api/auto', {}, 'Todo automático'));

  // ------------------------------------------- salidas (LEDs) en vivo ---

  /** Replica en sus bloques de la vista en vivo la pantalla y las luces del cuadro. */
  function renderOutputs() {
    if (!live.estado || !view.live) return;
    for (const s of view.sets) {
      if (s.def.id !== 'salida' || !s.el) continue;
      const v = live.vivos[s.ds.id];
      if (!v) continue;
      if (s.ds.salida === 'tira') {
        const strip = s.el.out.querySelector('.strip');
        if (strip.children.length !== v.leds.length) { strip.innerHTML = ''; v.leds.forEach(() => el('i', '', strip)); }
        v.leds.forEach((c, i) => { strip.children[i].className = c; });
        s.el.out.querySelector('p').textContent = v.texto || (v.valor == null ? 'sin datos de la fuente' : v.valor + ' ' + v.unidad);
      } else if (v.png) {
        s.el.out.querySelector('img').src = 'data:image/png;base64,' + v.png;
      }
    }
  }

  $('#open-full').addEventListener('click', async () => {
    await listPiFiles();
    const f = piSessions.find(s => s.name === live.lastSession);
    if (f) loadPiEntry(serverBase(), f);
    else setStatus('La sesión ' + live.lastSession + ' aún no tiene datos', 'err');
  });

  $('#connect').addEventListener('click', () => (live.es ? disconnect() : connect()));
  $('#pause').addEventListener('click', togglePause);
  $('#win').addEventListener('change', () => { live.dirty = true; });

  // cuenta.js (usuarios y sesiones del repo de datos) usa la misma vista
  function usarRaspi(base) {
    if (serverBase() === base) return;
    $('#server').value = base;
    store('tele-server', base);
    listPiFiles();
  }
  window.Telemetria = {
    openFiles, showTab, fileMsg, serverBase, servedByPi, usarRaspi, pestana: () => tab,
    conectar(base) { usarRaspi(base); connect(); },
    desconectar: disconnect, listarPi: listPiFiles, conectado: () => !!live.es,
  };

  // ---------------------------------------------------------------- init ---

  applyTheme(theme);
  if (location.hash === '#file') showTab('file');
  // tras cargar cuenta.js, que da la sesion para hablar con la raspi
  addEventListener('DOMContentLoaded', () => {
    listPiFiles();
    if (servedByPi && location.hash !== '#file') connect();
  });
})();
