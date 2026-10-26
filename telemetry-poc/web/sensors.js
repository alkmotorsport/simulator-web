/*
 * Registro de sensores: como se ve cada tipo de modulo de la Pi.
 *
 * Un dataset es { id, name, sensor, t, cols: {columna: valores}, meta, ctx },
 * con huecos como NaN; ctx = metas de todos los modulos de la sesion (p. ej.
 * los umbrales de las alertas). Cada tipo define:
 *   id, name          el TIPO del modulo en Python (modulos/*.py)
 *   detect(header)    true si reconoce las columnas de un CSV suelto
 *   options           controles de la barra (select) -> valores en opt
 *   derive(ds, opt)   canales calculados: { clave: array alineado con ds.t }
 *   charts(ds)        graficas: {type:'time'|'hist', key, title, unit, ...}
 *   histograms(d, i0, i1, opt)  { clave: {edges, values} } del tramo visible
 *   stats(ds, d, i0, i1, opt)   [{label, value, unit?, sub?}] del tramo visible
 *
 * Para un sensor nuevo: anade un objeto a SENSORS (antes de 'generic') con el
 * mismo id que el TIPO de su modulo en Python.
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

  /**
   * RMS respecto a la media local en una ventana centrada de 'seg' segundos
   * (ignora los NaN y los conserva): cuanto vibra la senal en cada momento.
   */
  function rmsMovil(t, y, seg) {
    const n = y.length, out = new Float64Array(n).fill(NaN);
    let a = 0, b = 0, s = 0, s2 = 0, c = 0;   // ventana [a, b)
    for (let i = 0; i < n; i++) {
      if (y[i] !== y[i]) continue;
      while (b < n && t[b] <= t[i] + seg / 2) { const v = y[b++]; if (v === v) { s += v; s2 += v * v; c++; } }
      while (t[a] < t[i] - seg / 2) { const v = y[a++]; if (v === v) { s -= v; s2 -= v * v; c--; } }
      const m = s / c;
      out[i] = Math.sqrt(Math.max(0, s2 / c - m * m));
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

  /** Umbrales de compresion de sesiones antiguas (modulo de 2 LEDs RGB, ya retirado, o meta.txt). */
  function umbrales(ds) {
    const out = [];
    let meta = ds.meta;
    for (const m of Object.values(ds.ctx || {}))
      if (m.tipo === 'alertas_rgb' && m.meta && m.meta.fuente === ds.id) meta = m.meta;
    const a = parseFloat(meta && meta.comp_ambar_mm), r = parseFloat(meta && meta.comp_rojo_mm);
    if (a === a) out.push({ y: a, color: '--status-warning', label: 'ámbar ' + a + ' mm' });
    if (r === r) out.push({ y: r, color: '--status-err', label: 'rojo ' + r + ' mm' });
    return out;
  }

  const suspension = {
    id: 'suspension',
    name: 'Suspensión trasera · ultrasonidos',
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
      { type: 'time', key: 'travel', title: 'Recorrido', unit: 'mm', note: '+ compresión · − extensión · marcas = sin eco', color: '--series-1', zero: true, gaps: true, height: 230, lines: umbrales(ds) },
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

  // ----------------------------------------------------------------- IMU ---

  /**
   * Sesiones grabadas antes de nivelar los ejes al calibrar (meta sin 'giro'):
   * con la caja inclinada, aceleraciones y angulos salen en los ejes de la
   * caja y la inclinacion da picos falsos. Se recalcula como hoy en la Pi
   * (modulos/imu.py): giro que lleva la gravedad de la calibracion a +Z y el
   * mismo filtro complementario, sin la velocidad de rueda.
   * Devuelve null si no hace falta (o no se puede).
   */
  function imuNivelada(ds) {
    const m = ds.meta || {}, c = ds.cols;
    if (ds.live || 'giro' in m || !Array.isArray(m.cero_deg) || !c.ax_g || !c.gz_dps) return null;
    const r0 = m.cero_deg[0] * Math.PI / 180, p0 = m.cero_deg[1] * Math.PI / 180;
    const x = Math.sin(p0), y = Math.cos(p0) * Math.sin(r0), z = Math.cos(p0) * Math.cos(r0);
    const tumbada = Math.acos(Math.max(-1, Math.min(1, z))) * 180 / Math.PI;
    if (tumbada < 20) return null;           // casi recta: lo grabado vale
    // giro mas corto de (x, y, z) a +Z (Rodrigues), como _nivelar() en Python
    const k = z < -0.9999 ? 0 : 1 / (1 + z);
    const R = z < -0.9999 ? [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
      : [[1 - k * x * x, -k * x * y, -x], [-k * x * y, 1 - k * y * y, -y], [x, y, z]];
    const n = ds.t.length, out = {};
    for (const key of ['ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps', 'incl_deg', 'cabeceo_deg'])
      out[key] = new Float64Array(n).fill(NaN);
    const alfa = +m.alfa || 0.98, GIRO_MIN = 8 * Math.PI / 180, RAD = Math.PI / 180;
    let incl = 0, cab = 0, fy = 0, fz = 0, tp = NaN;
    for (let i = 0; i < n; i++) {
      const a = [c.ax_g[i], c.ay_g[i], c.az_g[i]], g = [c.gx_dps[i], c.gy_dps[i], c.gz_dps[i]];
      if (a.some(v => v !== v) || g.some(v => v !== v)) continue;
      const A = R.map(f => f[0] * a[0] + f[1] * a[1] + f[2] * a[2]);
      const G = R.map(f => f[0] * g[0] + f[1] * g[1] + f[2] * g[2]);
      const [ax, ay, az] = A, gx = G[0] * RAD, gy = G[1] * RAD, gz = G[2] * RAD;
      fy += 0.03 * (gy - fy); fz += 0.03 * (gz - fz);
      const inclRef = Math.abs(fz) > GIRO_MIN
        ? Math.max(-1.2, Math.min(1.2, Math.atan(fy / fz))) : Math.atan2(ay, az);
      const cabRef = Math.atan2(ax, Math.hypot(ay, az));
      const t = ds.t[i];
      if (tp !== tp) { incl = inclRef; cab = cabRef; }
      else if (t - tp <= 0.2) {
        const dt = t - tp, dCab = -gy * Math.cos(incl) + gz * Math.sin(incl);
        incl = alfa * (incl + gx * dt) + (1 - alfa) * inclRef;
        cab = alfa * (cab + dCab * dt) + (1 - alfa) * cabRef;
      }   // hueco de lecturas: se sigue con lo que habia
      tp = t;
      out.ax_g[i] = ax; out.ay_g[i] = ay; out.az_g[i] = az;
      out.gx_dps[i] = G[0]; out.gy_dps[i] = G[1]; out.gz_dps[i] = G[2];
      out.incl_deg[i] = incl / RAD; out.cabeceo_deg[i] = cab / RAD;
    }
    out.tumbada = tumbada;
    return out;
  }

  /**
   * Indice desde el que la caja ya no esta como al calibrar (se ha cogido,
   * soltado o la moto esta caida), o -1. Senal: caja quieta >= 1 s con la
   * gravedad a mas de 35 grados de +Z. Se corta en el ultimo momento en calma
   * (giro < 10 grados/s durante 2 s) antes de ese movimiento.
   */
  function cajaMovida(t, d) {
    const n = t.length, cos35 = Math.cos(35 * Math.PI / 180);
    const giro = i => Math.max(Math.abs(d.gx_dps[i]), Math.abs(d.gy_dps[i]), Math.abs(d.gz_dps[i]));
    let q0 = -1;
    for (let i = 0; i < n; i++) {
      const a = Math.hypot(d.ax_g[i], d.ay_g[i], d.az_g[i]);
      const quieta = a > 0.9 && a < 1.1 && giro(i) < 5 && d.az_g[i] / a < cos35;
      if (!quieta) { q0 = -1; continue; }
      if (q0 < 0) q0 = i;
      if (t[i] - t[q0] < 1) continue;
      let calma = q0;   // hacia atras: inicio del movimiento
      for (let j = q0; j >= 0; j--) {
        if (giro(j) >= 10) calma = j;
        else if (t[calma] - t[j] >= 2) break;
      }
      return Math.max(0, calma - 1);
    }
    return -1;
  }

  /** Columnas de la IMU (recalculadas si hace falta) sin lo de despues de mover la caja. */
  function imuDatos(ds) {
    const base = imuNivelada(ds), d = base || ds.cols;
    const corte = ds.live ? -1 : cajaMovida(ds.t, d);
    if (corte < 0) return { d: base, corte: -1 };
    const out = base || {};
    for (const k of ['ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps', 'incl_deg', 'cabeceo_deg']) {
      const v = base ? base[k] : Float64Array.from(ds.cols[k]);
      v.fill(NaN, corte);
      out[k] = v;
    }
    return { d: out, corte };
  }

  /**
   * Aceleracion lateral real (g) a partir de la inclinacion: en curva la moto
   * se tumba hasta que la resultante va por su eje, asi que la caja mide ~0
   * lateral; la que da el neumatico es tan(inclinacion) (web, Modulo 2.2).
   */
  function lateralDeIncl(incl) {
    const n = incl.length, out = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const v = incl[i];
      out[i] = v === v && Math.abs(v) < 70 ? Math.tan(v * Math.PI / 180) : NaN;
    }
    return out;
  }

  /** Mapa de densidad g-g del tramo: bins de 0,025 g hasta 1 / 1,5 / 2 g. */
  function ggGrid(lat, lon, i0, i1) {
    let m = 0, c = 0;
    for (let i = i0; i < i1; i++) {
      const x = lat[i], y = lon[i];
      if (x === x && y === y) { c++; m = Math.max(m, Math.abs(x), Math.abs(y)); }
    }
    if (!c) return { edges: [], values: [] };
    const lim = m <= 0.95 ? 1 : m <= 1.45 ? 1.5 : 2, n = Math.round(2 * lim / 0.025);
    const values = new Float64Array(n * n), k = n / (2 * lim);
    for (let i = i0; i < i1; i++) {
      const x = lat[i], y = lon[i];
      if (x !== x || y !== y) continue;
      const ix = Math.min(n - 1, Math.max(0, Math.floor((x + lim) * k)));
      const iy = Math.min(n - 1, Math.max(0, Math.floor((y + lim) * k)));
      values[iy * n + ix] += 100 / c;
    }
    return { edges: Array.from({ length: n + 1 }, (_, j) => -lim + j / k), values };
  }

  const imu = {
    id: 'imu',
    name: 'IMU · MPU6050',
    detect: h => ['ax_g', 'gz_dps'].every(c => h.includes(c)),
    options: [],
    derive(ds) {
      // en vivo los datos crecen: tal cual (ahi la vibracion se ve en directo)
      if (ds.live) return Object.assign({}, ds.cols,
        { ax_f: ds.cols.ax_g, lat: lateralDeIncl(ds.cols.incl_deg), vib: rmsMovil(ds.t, ds.cols.az_g, 1), live: true });
      if (ds.imu === undefined) {   // una vez por sesion
        ds.imu = imuDatos(ds);
        // una frenada dura segundos: la media de 0,5 s quita la vibracion del
        // motor (picos de hasta 4 g, el tope del sensor, y aliasing a 100 Hz)
        // sin aplanar el inicio y el final de cada frenada
        const d = ds.imu.d || ds.cols, w = Math.max(1, Math.round(0.5 * (+(ds.meta && ds.meta.hz) || 100)));
        ds.imu.f = { ax_f: smooth(d.ax_g, w), lat: lateralDeIncl(d.incl_deg), vib: rmsMovil(ds.t, d.az_g, 1) };
      }
      return Object.assign({}, ds.imu.d || ds.cols, ds.imu.f);
    },
    charts: () => [
      { type: 'time', key: 'incl_deg', title: 'Inclinación', unit: '°', note: '+ derecha · − izquierda', color: '--series-1', zero: true, height: 190 },
      { type: 'time', key: 'ax_f', title: 'Aceleración longitudinal', unit: 'g', note: '+ acelera · − frena · media 0,5 s', color: '--series-2', zero: true, decimals: 2, height: 160 },
      { type: 'time', key: 'lat', title: 'Aceleración lateral', unit: 'g', note: '+ derecha · tan(inclinación): la caja mide ~0 en curva', color: '--series-3', zero: true, decimals: 2, height: 140 },
      { type: 'time', key: 'cabeceo_deg', title: 'Cabeceo', unit: '°', note: '+ morro arriba', color: '--series-7', zero: true, height: 140 },
      { type: 'time', key: 'vib', title: 'Vibración vertical', unit: 'g RMS', note: 'RMS en 1 s · motor, asfalto y golpes', color: '--series-7', zero: true, decimals: 2, height: 140 },
      { type: 'hist', key: 'inclHist', title: 'Tiempo por inclinación', unit: '°', note: '% de tiempo', colorFor: c => (c >= 0 ? '--series-1' : '--series-2') },
      { type: 'gg', key: 'gg', title: 'Diagrama g-g', unit: 'g', note: 'círculo de fricción · más oscuro = más tiempo', color: '--series-1', height: 300 },
    ],
    histograms(d, i0, i1) {
      const v = finite(d.incl_deg, i0, i1);
      const lim = Math.max(5, percentile(v.map(Math.abs), 0.995));
      const gg = ggGrid(d.lat, d.ax_f, i0, i1);
      if (d.live && i1 > i0) gg.ahora = [d.lat[i1 - 1], d.ax_f[i1 - 1]];
      return { inclHist: histogram(v, -lim, lim, 24), gg };
    },
    stats(ds, d, i0, i1) {
      const tm = timing(ds.t, i0, i1);
      const [ilo, ihi] = minmax(finite(d.incl_deg, i0, i1));
      const [alo, ahi] = minmax(finite(d.ax_f, i0, i1));
      const [ylo, yhi] = minmax(finite(d.lat, i0, i1));
      let gmax = NaN, tg = NaN;
      for (let i = i0; i < i1; i++) {
        const g = Math.hypot(d.lat[i], d.ax_f[i]);
        if (g === g && !(g <= gmax)) { gmax = g; tg = ds.t[i]; }
      }
      const az = finite(d.az_g, i0, i1), azm = mean(az);
      let s = 0; for (const v of az) s += (v - azm) * (v - azm);
      const recalc = [];
      if (d.tumbada) recalc.push({
        label: 'Ángulos recalculados', value: f(d.tumbada, 0), unit: '° caja',
        sub: 'grabada antes de nivelar los ejes al calibrar', warn: true,
      });
      if (ds.imu && ds.imu.corte >= 0) recalc.push({
        label: 'Caja movida', value: f(ds.t[ds.imu.corte], 0), unit: 's',
        sub: 'desde ahí no vale: se descarta', warn: true,
      });
      return recalc.concat([
        { label: 'Tasa real', value: f(tm.hz, 0), unit: 'Hz', sub: tm.n + ' muestras' },
        { label: 'Incl. máx derecha', value: f(ihi > 0 ? ihi : NaN, 1), unit: '°' },
        { label: 'Incl. máx izquierda', value: f(ilo < 0 ? -ilo : NaN, 1), unit: '°' },
        { label: 'Frenada máx', value: f(alo < 0 ? -alo : NaN, 2), unit: 'g' },
        { label: 'Aceleración máx', value: f(ahi > 0 ? ahi : NaN, 2), unit: 'g' },
        { label: 'Lateral máx', value: f(Math.max(-ylo, yhi), 2), unit: 'g', sub: 'tan(inclinación)' },
        { label: 'G combinada máx', value: f(gmax, 2), unit: 'g', sub: 'a los ' + f(tg, 0) + ' s · neumático de calle ≈ 1 g' },
        { label: 'Vibración vertical', value: f(az.length ? Math.sqrt(s / az.length) : NaN, 3), unit: 'g RMS' },
      ]);
    },
  };

  // --------------------------------------------------------------- rueda ---

  const rueda = {
    id: 'rueda',
    name: 'Velocidad de rueda · Hall',
    detect: h => ['kmh', 'pulsos'].every(c => h.includes(c)),
    options: [],
    derive: ds => ({ kmh: ds.cols.kmh, rpm: ds.cols.rpm, dist: ds.cols.dist_m }),
    charts: () => [
      { type: 'time', key: 'kmh', title: 'Velocidad', unit: 'km/h', color: '--series-3', zero: true, height: 170 },
    ],
    histograms: () => ({}),
    stats(ds, d, i0, i1) {
      const v = finite(d.kmh, i0, i1), mov = v.filter(x => x > 2);
      const dist = finite(d.dist, i0, i1);
      return [
        { label: 'Vel. máx', value: f(minmax(v)[1], 1), unit: 'km/h' },
        { label: 'Vel. media en marcha', value: f(mean(mov), 1), unit: 'km/h' },
        { label: 'Distancia', value: f(dist.length ? dist[dist.length - 1] - dist[0] : NaN, 0), unit: 'm', sub: 'en el tramo visible' },
        { label: 'Parado', value: f(v.length ? 100 * (v.length - mov.length) / v.length : NaN, 0), unit: '%' },
      ];
    },
  };

  // ------------------------------------------------------- temperaturas ---

  function tempStats(t, v, i0, i1, extra) {
    const vals = finite(v, i0, i1), [lo, hi] = minmax(vals);
    let last = NaN;
    for (let i = i1 - 1; i >= i0; i--) if (v[i] === v[i]) { last = v[i]; break; }
    const lost = (i1 - i0) - vals.length;
    return [
      { label: 'Última', value: f(last, 1), unit: '°C' },
      { label: 'Máxima', value: f(hi, 1), unit: '°C' },
      { label: 'Mínima', value: f(lo, 1), unit: '°C' },
      { label: 'Media', value: f(mean(vals), 1), unit: '°C' },
      { label: 'Sin lectura', value: f(i1 > i0 ? 100 * lost / (i1 - i0) : NaN, 0), unit: '%', sub: extra, warn: lost > 0.05 * (i1 - i0) },
    ];
  }

  const termopar = {
    id: 'termopar',
    name: 'Sonda K · MAX6675',
    detect: h => h.length === 2 && h.includes('temp_c'),
    options: [],
    derive: ds => ds.cols,
    charts: () => [
      { type: 'time', key: 'temp_c', title: 'Temperatura', unit: '°C', color: '--series-2', gaps: true, height: 160, gapMax: 1 },
    ],
    histograms: () => ({}),
    stats: (ds, d, i0, i1) => tempStats(ds.t, d.temp_c, i0, i1, 'sonda abierta'),
  };

  const infrarrojos = {
    id: 'infrarrojos',
    name: 'Temperatura IR · MLX90614',
    detect: h => h.includes('obj_c'),
    options: [],
    derive: ds => ds.cols,
    charts: ds => [
      { type: 'time', key: 'obj_c', title: 'Temperatura ' + ((ds.meta && ds.meta.apunta_a) || 'objetivo'), unit: '°C', color: '--series-2', gaps: true, height: 160, gapMax: 0.5 },
      { type: 'time', key: 'amb_c', title: 'Temperatura del sensor', unit: '°C', color: '--series-7', height: 110, gapMax: 0.5 },
    ],
    histograms: () => ({}),
    stats: (ds, d, i0, i1) => tempStats(ds.t, d.obj_c, i0, i1, 'error de lectura'),
  };

  // ---------------------------------------------------------------- boton ---

  const boton = {
    id: 'boton',
    name: 'Pulsador de vuelta',
    detect: h => h.includes('pulsaciones'),
    options: [],
    derive: ds => ds.cols,
    charts: () => [],
    histograms: () => ({}),
    stats(ds, d, i0, i1) {
      // solo hay filas al pulsar: lo acumulado hasta el final de lo visible
      // (en vivo, hasta ahora), no solo lo que cae dentro de la ventana
      const laps = finite(d.t_vuelta_s, 0, i1), [best] = minmax(laps);
      const v = finite(d.vuelta, 0, i1);
      let cortas = 0;
      for (let i = 0; i < i1; i++) if (d.pulsaciones[i] === 1) cortas++;
      return [
        { label: 'Vueltas', value: v.length ? String(v[v.length - 1]) : '0' },
        { label: 'Pulsaciones', value: String(cortas), sub: 'cortas (cambio de página)' },
        { label: 'Mejor vuelta', value: f(best, 2), unit: 's' },
        { label: 'Última vuelta', value: f(laps[laps.length - 1], 2), unit: 's' },
        { label: 'Media', value: f(mean(laps), 2), unit: 's', sub: laps.length + ' completas' },
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

  // ------------------------------------------------- salidas (en vivo) ---
  // Pantalla y luces del cuadro como bloques de la vista en vivo (app.js pinta
  // su contenido): sin cifras ni graficas, pero se mueven y ocultan como los demas.

  const salida = {
    id: 'salida',
    name: 'Salida del cuadro',
    detect: () => false,
    options: [],
    derive: () => ({}),
    charts: () => [],
    histograms: () => ({}),
    stats: () => [],
  };

  const SENSORS = [suspension, imu, rueda, termopar, infrarrojos, boton, salida, generic];

  function byId(id) { return SENSORS.find(s => s.id === id); }
  function detect(header) { return SENSORS.find(s => s.detect(header)); }

  global.Sensors = { SENSORS, byId, detect, smooth, derivative, histogram };
})(window);
