/*
 * Registro de sensores.
 *
 * Un dataset es { name, sensor, t, cols: {columna: valores}, meta }, con
 * huecos como NaN. Cada sensor define:
 *   id, name          identificador (el mismo que manda el script en vivo)
 *   detect(header)    true si reconoce las columnas de un CSV
 *   options           controles de la barra (select) -> valores en opt
 *   derive(ds, opt)   canales calculados: { clave: array alineado con ds.t }
 *   charts(ds)        graficas: {type:'time'|'hist', key, title, unit, ...}
 *   histograms(d, i0, i1, opt)  { clave: {edges, values} } del tramo visible
 *   stats(ds, d, i0, i1, opt)   [{label, value, unit?, sub?}] del tramo visible
 *
 * Para un sensor nuevo: anade un objeto a SENSORS (antes de 'generic').
 */
(function (global) {
  'use strict';

  // --------------------------------------------------------- utilidades ---

  function finite(arr, i0 = 0, i1 = arr.length) {
    const out = [];
    for (let i = i0; i < i1; i++) { const v = arr[i]; if (v === v) out.push(v); }
    return out;
  }
  function median(a) {
    if (!a.length) return NaN;
    const s = Float64Array.from(a).sort(), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function percentile(a, p) {
    if (!a.length) return NaN;
    const s = Float64Array.from(a).sort();
    return s[Math.min(s.length - 1, Math.floor(p * s.length))];
  }
  function mean(a) { let s = 0; for (const v of a) s += v; return a.length ? s / a.length : NaN; }
  function minmax(a) {
    let lo = Infinity, hi = -Infinity;
    for (const v of a) { if (v < lo) lo = v; if (v > hi) hi = v; }
    return [lo, hi];
  }

  /** Media movil centrada de w muestras que ignora los NaN (y los conserva). */
  function smooth(y, w) {
    const n = y.length, out = new Float64Array(n);
    if (w <= 1) { for (let i = 0; i < n; i++) out[i] = y[i]; return out; }
    const h = w >> 1;
    for (let i = 0; i < n; i++) {
      if (y[i] !== y[i]) { out[i] = NaN; continue; }
      let s = 0, c = 0;
      for (let j = Math.max(0, i - h); j <= Math.min(n - 1, i + h); j++) {
        const v = y[j]; if (v === v) { s += v; c++; }
      }
      out[i] = s / c;
    }
    return out;
  }

  /** Derivada hacia atras, como el --resumen del script (dt valido < maxDt). */
  function derivative(t, y, maxDt) {
    const n = y.length, out = new Float64Array(n).fill(NaN);
    let pt = NaN, py = NaN;
    for (let i = 0; i < n; i++) {
      const v = y[i];
      if (v !== v) { pt = NaN; continue; }
      const dt = t[i] - pt;
      if (dt > 0 && dt < maxDt) out[i] = (v - py) / dt;
      pt = t[i]; py = v;
    }
    return out;
  }

  /** Histograma en % con bins de ancho 'nice' entre lo y hi. */
  function histogram(vals, lo, hi, targetBins) {
    if (!vals.length || !(hi > lo)) return { edges: [], values: [] };
    const w = Plot.niceStep(hi - lo, targetBins);
    const a = Math.floor(lo / w) * w, b = Math.ceil(hi / w) * w;
    const n = Math.max(1, Math.round((b - a) / w));
    const counts = new Array(n).fill(0);
    for (const v of vals) {
      const k = Math.floor((v - a) / w);
      if (k >= 0 && k < n) counts[k]++;
      else if (k === n) counts[n - 1]++;
    }
    const edges = Array.from({ length: n + 1 }, (_, k) => a + k * w);
    return { edges, values: counts.map(c => 100 * c / vals.length) };
  }

  function timing(t, i0, i1) {
    const n = i1 - i0;
    const dur = n > 1 ? t[i1 - 1] - t[i0] : 0;
    const dts = [];
    for (let i = i0 + 1; i < i1; i++) dts.push(t[i] - t[i - 1]);
    return { n, dur, hz: dur > 0 ? (n - 1) / dur : NaN, dtMed: median(dts), dtMax: dts.length ? minmax(dts)[1] : NaN };
  }

  const f = (v, d = 1) => (v === v && isFinite(v) ? v.toFixed(d) : '—');
  const sg = (v, d = 0) => (v === v && isFinite(v) ? (v > 0 ? '+' : '') + v.toFixed(d) : '—');

  // ---------------------------------------------------------- suspension ---

  /** Umbrales de alerta de los LEDs (meta.txt o meta en vivo), si los hay. */
  function umbrales(meta) {
    const out = [];
    const a = parseFloat(meta && meta.comp_ambar_mm), r = parseFloat(meta && meta.comp_rojo_mm);
    if (a === a) out.push({ y: a, color: '--status-warning', label: 'ámbar ' + a + ' mm' });
    if (r === r) out.push({ y: r, color: '--status-err', label: 'rojo ' + r + ' mm' });
    return out;
  }

  const suspension = {
    id: 'suspension',
    name: 'Suspensión · ultrasonidos HC-SR04',
    detect: h => ['t_s', 'dist_mm', 'rel_mm'].every(c => h.includes(c)),

    options: [
      {
        id: 'mount', label: 'Montaje', value: 'closer',
        choices: [
          ['closer', 'Al comprimir, el objetivo se acerca'],
          ['farther', 'Al comprimir, el objetivo se aleja'],
        ],
      },
      {
        id: 'smooth', label: 'Suavizado velocidad', value: '3',
        choices: [['1', 'Sin filtro'], ['3', '3 muestras'], ['5', '5 muestras'], ['9', '9 muestras']],
      },
    ],

    derive(ds, opt) {
      const rel = ds.cols.rel_mm, n = rel.length;
      // recorrido > 0 = compresion, segun como este montado el sensor
      const s = opt.mount === 'farther' ? 1 : -1;
      const travel = new Float64Array(n);
      for (let i = 0; i < n; i++) travel[i] = s * rel[i];
      const vel = derivative(ds.t, smooth(travel, +opt.smooth), 0.2);
      return { travel, vel, dist: ds.cols.dist_mm };
    },

    charts: ds => [
      { type: 'time', key: 'travel', title: 'Recorrido', unit: 'mm', note: '+ compresión · − extensión · marcas = sin eco', color: '--series-1', zero: true, gaps: true, height: 230, lines: umbrales(ds.meta) },
      { type: 'time', key: 'vel', title: 'Velocidad', unit: 'mm/s', note: '+ compresión · − extensión', color: '--series-7', zero: true, decimals: 0 },
      { type: 'time', key: 'dist', title: 'Distancia medida', unit: 'mm', note: 'dato bruto del sensor', color: '--series-3', gaps: true, height: 150 },
      { type: 'hist', key: 'velHist', title: 'Histograma de velocidad', unit: 'mm/s', note: '% de tiempo', colorFor: c => (c >= 0 ? '--series-2' : '--series-1') },
      { type: 'hist', key: 'travelHist', title: 'Histograma de recorrido', unit: 'mm', note: '% de tiempo', colorFor: () => '--series-1' },
    ],

    histograms(d, i0, i1) {
      const v = finite(d.vel, i0, i1);
      const lim = percentile(v.map(Math.abs), 0.995);
      const tr = finite(d.travel, i0, i1);
      const [lo, hi] = minmax(tr);
      return {
        velHist: lim > 0 ? histogram(v, -lim, lim, 24) : { edges: [], values: [] },
        travelHist: histogram(tr, lo, hi, 20),
      };
    },

    stats(ds, d, i0, i1) {
      const tm = timing(ds.t, i0, i1);
      let lost = 0; for (let i = i0; i < i1; i++) if (ds.cols.dist_mm[i] !== ds.cols.dist_mm[i]) lost++;
      const dist = finite(ds.cols.dist_mm, i0, i1);
      const tr = finite(d.travel, i0, i1);
      const v = finite(d.vel, i0, i1);
      const [dlo, dhi] = minmax(dist), [tlo, thi] = minmax(tr), [vlo, vhi] = minmax(v);
      const comp = v.filter(x => x > 0), ext = v.filter(x => x < 0);
      return [
        { label: 'Duración', value: f(tm.dur, 1), unit: 's', sub: tm.n + ' muestras' },
        { label: 'Tasa real', value: f(tm.hz, 1), unit: 'Hz', sub: 'dt med ' + f(tm.dtMed * 1000, 1) + ' · máx ' + f(tm.dtMax * 1000, 0) + ' ms' },
        { label: 'Sin eco', value: f(tm.n ? 100 * lost / tm.n : NaN, 1), unit: '%', sub: lost + ' muestras', warn: tm.n && lost / tm.n > 0.05 },
        { label: 'Recorrido usado', value: f(thi - tlo, 1), unit: 'mm', sub: 'de ' + sg(tlo, 1) + ' a ' + sg(thi, 1) },
        { label: 'Distancia', value: f(mean(dist), 1), unit: 'mm', sub: 'media · ' + f(dlo, 0) + '–' + f(dhi, 0) },
        { label: 'Vel. máx compresión', value: f(vhi > 0 ? vhi : NaN, 0), unit: 'mm/s', sub: 'media ' + f(mean(comp), 0) },
        { label: 'Vel. máx extensión', value: f(vlo < 0 ? -vlo : NaN, 0), unit: 'mm/s', sub: 'media ' + f(-mean(ext), 0) },
        { label: 'Tiempo comprimiendo', value: f(v.length ? 100 * comp.length / v.length : NaN, 0), unit: '%', sub: 'resto en extensión/quieto' },
      ];
    },
  };

  // ------------------------------------------------------------ generico ---
  // Cualquier CSV con una columna de tiempo: una grafica por columna numerica.

  const generic = {
    id: 'generic',
    name: 'CSV genérico',
    detect: () => true,
    options: [],
    derive: ds => ds.cols,
    charts: ds => Object.keys(ds.cols).map(k => {
      const unit = (k.match(/_([a-z%/]+)$/i) || [])[1] || '';
      return { type: 'time', key: k, title: k, unit, color: '--series-1', gaps: true, height: 170 };
    }),
    histograms: () => ({}),
    stats(ds, d, i0, i1) {
      const tm = timing(ds.t, i0, i1);
      const out = [
        { label: 'Duración', value: f(tm.dur, 1), unit: 's', sub: tm.n + ' muestras' },
        { label: 'Tasa real', value: f(tm.hz, 1), unit: 'Hz', sub: 'dt med ' + f(tm.dtMed * 1000, 1) + ' ms' },
      ];
      for (const k of Object.keys(ds.cols)) {
        const v = finite(ds.cols[k], i0, i1), [lo, hi] = minmax(v);
        out.push({ label: k, value: f(mean(v), 2), sub: 'media · ' + f(lo, 2) + ' … ' + f(hi, 2) });
      }
      return out;
    },
  };

  const SENSORS = [suspension, generic];

  function byId(id) { return SENSORS.find(s => s.id === id); }
  function detect(header) { return SENSORS.find(s => s.detect(header)); }

  global.Sensors = { SENSORS, byId, detect, smooth, derivative, histogram };
})(window);
