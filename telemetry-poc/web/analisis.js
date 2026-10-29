/*
 * Analizar trazas: reglas fijas que explican lo que se ve en una sesion con
 * la teoria del simulador de la formacion (https://motorsport.amorgante.es).
 * Mismas formulas y mismos valores de referencia que sus capitulos; cada
 * hallazgo enlaza al suyo (#lean, #grip, #load...).
 *
 *   Analisis.analizar(sets, rango) -> [{nivel, tema, titulo, texto, ref, t}]
 *     sets   [{def, ds, derived}] de la vista (derived = lo que pintan las graficas)
 *     rango  [t0, t1] visible o null (toda la sesion)
 *     nivel  'aviso' | 'info' | 'ok';  t = instante para «Ver» (o null)
 *
 * La moto: la ficha de la sesion (pestana Moto: peso, batalla, neumaticos,
 * frenos...); lo que falte sale de la moto de ejemplo de la web y se dice.
 *
 * Primero cada sensor por separado y despues las correlaciones entre ellos
 * (IMU con rueda, suspension, disco de freno...). Sin datos de un sensor, sus
 * reglas no salen.
 */
(function (global) {
  'use strict';

  const G = 9.81;
  const WEB = 'https://motorsport.amorgante.es/#';
  // valores por defecto de la web (la moto de cada simulacion)
  const WEB_REF = {
    m: 220, h: 0.60, L: 1.40,                       // 2.3 transferencia de carga
    mu: { calle: 1.0, deportivo: 1.2, competicion: 1.5 },   // margen de agarre
    disco: { m: 1.5, cp: 460, limite: 500 },        // 6.2 acero en calle
    cd: 0.65, area: 0.55, rho: 1.225,               // 5.1 naked
    ks: 35000, ms: 75, kt: 150000, mu_ns: 18,       // 3.6 masa suspendida
    ondulado: 5,                                     // resonancia: ondulado de 5 m
  };
  const FS = Math.sqrt(WEB_REF.ks / WEB_REF.ms) / (2 * Math.PI);
  const FU = Math.sqrt((WEB_REF.ks + WEB_REF.kt) / WEB_REF.mu_ns) / (2 * Math.PI);
  const NEUMATICO = { calle: 'de calle', deportivo: 'deportivo', competicion: 'de competición' };
  // C_D y A por carroceria (los casos de la web: naked y MotoGP carenada)
  const AERO = { naked: [0.65, 0.55], semicarenada: [0.65, 0.48], carenada: [0.70, 0.44] };

  // la moto de este analisis (configurar): REF con lo de la ficha encima
  let REF = WEB_REF, STOPPIE_G = WEB_REF.L / (2 * WEB_REF.h), MOTO = {};

  function configurar(moto) {
    const f = MOTO = moto || {};
    REF = Object.assign({}, WEB_REF);
    if (f.peso_seco_kg) REF.m = f.peso_seco_kg + (f.piloto_kg || 75) + (f.deposito_l ? f.deposito_l / 2 * 0.74 : 0);
    if (f.batalla_m) REF.L = f.batalla_m;
    if (f.altura_cm_m) REF.h = f.altura_cm_m;
    REF.neum = f.neumaticos || 'calle';
    REF.muMoto = WEB_REF.mu[REF.neum];
    if (AERO[f.carroceria]) [REF.cd, REF.area] = AERO[f.carroceria];
    REF.tambor = f.freno_del_tipo === 'tambor';
    if (f.freno_del_tipo === 'disco') {
      const carbono = f.freno_del_material === 'carbono';
      REF.disco = { m: f.freno_del_disco_kg || WEB_REF.disco.m, n: f.freno_del_discos || 2,
                    cp: carbono ? 1200 : 460, limite: carbono ? 1000 : 500, material: carbono ? 'carbono' : 'acero' };
    } else REF.disco = Object.assign({ n: 2, material: 'acero' }, WEB_REF.disco);
    STOPPIE_G = REF.L / (2 * REF.h);
  }
  /** «con tu moto (…)» o «con la moto de ejemplo de la web (…)» para m, h y L. */
  function conMoto() {
    const d = [['m', MOTO.peso_seco_kg, n0(REF.m) + ' kg'], ['h', MOTO.altura_cm_m, n2(REF.h) + ' m'], ['L', MOTO.batalla_m, n2(REF.L) + ' m']];
    const propios = d.filter(x => x[1]).map(x => x[0] + ' ' + x[2]), web = d.filter(x => !x[1]).map(x => x[0] + ' ' + x[2]);
    if (!propios.length) return 'con la moto de ejemplo de la web (' + web.join(', ') + ')';
    return 'con tu moto (' + propios.join(', ') + ')' + (web.length ? ' y, de la web, ' + web.join(', ') : '');
  }
  const THETA = mu => Math.atan(mu) * 180 / Math.PI;

  // ------------------------------------------------------------ utilidades ---

  const n1 = v => fmt(v, 1), n2 = v => fmt(v, 2), n0 = v => fmt(v, 0);
  function fmt(v, d) { return v === v && isFinite(v) ? v.toFixed(d).replace('.', ',') : '—'; }
  function hms(s) {
    if (!(s === s)) return '—';
    const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = Math.floor(s % 60);
    return h ? h + ' h ' + String(m).padStart(2, '0') + ' min' : m ? m + ' min ' + String(x).padStart(2, '0') + ' s' : n1(s) + ' s';
  }
  function idx(t, r) { return r ? [Plot.lowerBound(t, r[0]), Plot.lowerBound(t, r[1] + 1e-9)] : [0, t.length]; }
  function lb(t, x) { return Plot.lowerBound(t, x); }

  /** Valor de y en el instante x (el de la muestra mas cercana anterior), o NaN. */
  function en(t, y, x, maxDt = 1) {
    const i = Math.min(t.length - 1, lb(t, x));
    for (let j = i; j >= Math.max(0, i - 1); j--) if (Math.abs(t[j] - x) <= maxDt && y[j] === y[j]) return y[j];
    return NaN;
  }

  /** Maximo (o minimo con signo -1) y su instante. */
  function extremo(t, y, i0, i1, signo = 1) {
    let best = NaN, tb = NaN;
    for (let i = i0; i < i1; i++) {
      const v = y[i] * signo;
      if (v === v && !(v <= best)) { best = v; tb = t[i]; }
    }
    return { v: best * signo, t: tb };
  }

  function cuantil(vals, p) {
    if (!vals.length) return NaN;
    const s = Float64Array.from(vals).sort();
    return s[Math.min(s.length - 1, Math.floor(p * s.length))];
  }

  /**
   * Tramos en los que cond(i) se cumple al menos 'minDur' s seguidos
   * (cortes de menos de 'hueco' s no lo rompen). -> [{i0, i1, t0, t1}]
   */
  function tramos(t, i0, i1, cond, minDur, hueco = 0.2) {
    const out = [];
    let a = -1, ultimo = -1;
    for (let i = i0; i <= i1; i++) {
      const ok = i < i1 && cond(i);
      if (ok) { if (a < 0) a = i; ultimo = i; continue; }
      if (a >= 0 && (i >= i1 || t[i] - t[ultimo] > hueco)) {
        if (t[ultimo] - t[a] >= minDur) out.push({ i0: a, i1: ultimo + 1, t0: t[a], t1: t[ultimo] });
        a = -1;
      }
    }
    return out;
  }

  // ------------------------------------------------------------- hallazgos ---

  function nuevo() {
    const lista = [];
    const add = (nivel, tema, titulo, texto, ref, t) => lista.push({ nivel, tema, titulo, texto, ref: ref || null, t: t === t ? t : null });
    return { lista, add };
  }

  // ---------------------------------------------------- calidad de datos ---

  function calidad(S, r, add) {
    // huecos de todos los sensores en una sola linea (uno por sensor era una lista larga)
    const con = [];
    let total = 0, peorTodo = 0, tPeorTodo = NaN;
    for (const s of S.todos) {
      const t = s.ds.t, [i0, i1] = idx(t, r);
      if (i1 - i0 < 2) continue;
      let huecos = 0, peor = 0;
      for (let i = i0 + 1; i < i1; i++) {
        const dt = t[i] - t[i - 1];
        if (dt > 0.5) {
          huecos++;
          if (dt > peor) peor = dt;
          if (dt > peorTodo) { peorTodo = dt; tPeorTodo = t[i - 1]; }
        }
      }
      if (huecos) { con.push(s.ds.name + ' ' + huecos + ' (máx ' + n1(peor) + ' s)'); total += huecos; }
    }
    if (con.length) add('info', 'Datos', total + ' huecos sin lecturas en ' + con.length + (con.length === 1 ? ' sensor' : ' sensores'),
      con.join(' · ') + '. Ahí la gráfica se corta y las cifras no cuentan ese tiempo; el tiempo marcado es el más largo.', null, tPeorTodo);

    const imu = S.imu;
    if (imu) {
      const d = imu.derived, ds = imu.ds, t = ds.t, [i0, i1] = idx(t, r);
      if (d.tumbada) add('info', 'Datos', 'Ángulos del acelerómetro/giroscopio recalculados (caja a ' + n0(d.tumbada) + '°)',
        'La sesión se grabó antes de que la calibración nivelara los ejes. Con la caja tumbada, la inclinación salía de dos ejes que miden casi 0 y daba picos falsos. La app gira los ejes y repite el cálculo: lo que ves ya está corregido.', null, null);
      if (ds.imu && ds.imu.corte >= 0) add('aviso', 'Datos', 'La caja se movió a ' + hms(t[ds.imu.corte]),
        'Desde ahí la caja queda quieta con la gravedad a más de 35° de como estaba al calibrar: se cogió, se soltó o la moto está caída. Esos datos ya no dicen nada de la moto y no se usan.', null, t[ds.imu.corte]);
      // tope del sensor (+-4 g): golpes o caja rigida/suelta
      const c = ds.cols;
      let sat = 0, n = 0, tSat = NaN;
      for (let i = i0; i < i1; i++) {
        const a = Math.max(Math.abs(c.ax_g[i]), Math.abs(c.ay_g[i]), Math.abs(c.az_g[i]));
        if (a !== a) continue;
        n++;
        if (a >= 3.95) { sat++; if (tSat !== tSat) tSat = t[i]; }
      }
      if (sat) add('aviso', 'Datos', 'El acelerómetro llega a su tope (±4 g) en ' + sat + ' lecturas',
        'Son golpes o vibración del motor que no caben en la escala del sensor (' + n2(100 * sat / n) + ' % de las lecturas). Suele ser la caja atornillada rígida al chasis o algo suelta: un soporte con goma lo reduce y mejora todas las medidas del acelerómetro/giroscopio.', null, tSat);
      // vibracion y muestreo (Nyquist)
      const vib = [];
      for (let i = i0; i < i1; i++) if (d.vib[i] > 0.1) vib.push(d.vib[i]);
      const hz = +(ds.meta && ds.meta.hz) || 100;
      if (vib.length > 100) {
        const med = cuantil(vib, 0.5);
        add(med > 0.3 ? 'aviso' : 'info', 'Datos', 'Vibración en marcha: ' + n2(med) + ' g RMS (mediana)',
          'El motor vibra a decenas o cientos de Hz y el acelerómetro/giroscopio muestrea a ' + n0(hz) + ' Hz: lo que pase de ' + n0(hz / 2) + ' Hz no se puede ver bien (Nyquist: fs ≥ 2·f) y reaparece como una señal lenta falsa (aliasing). Por eso la aceleración longitudinal se promedia en 0,5 s.' +
          (med > 0.3 ? ' Con tanta vibración, la frenada y la aceleración de pico pueden llevar algo de ruido.' : ''), 'nyq', null);
      }
    }

    const su = S.suspension;
    if (su) {
      const t = su.ds.t, [i0, i1] = idx(t, r), dist = su.ds.cols.dist_mm;
      let perd = 0;
      for (let i = i0; i < i1; i++) if (dist[i] !== dist[i]) perd++;
      const hz = (i1 - i0 - 1) / ((t[i1 - 1] - t[i0]) || 1);
      if (i1 - i0 > 10 && perd / (i1 - i0) > 0.05) add('aviso', 'Datos', 'Suspensión: ' + n0(100 * perd / (i1 - i0)) + ' % de lecturas sin eco',
        'El ultrasonido no recibe su rebote: objetivo mal orientado, demasiado cerca o lejos, o suciedad.', null, null);
      if (hz > 0 && hz < 2 * FU) add('info', 'Datos', 'Suspensión a ' + n0(hz) + ' Hz: se ve la carrocería, no la rueda',
        'Con los valores de la web, la carrocería oscila a f_s = √(ks/ms)/2π ≈ ' + n1(FS) + ' Hz y la rueda a f_u ≈ ' + n0(FU) + ' Hz. Para ver la rueda hacen falta ≥ ' + n0(2 * FU) + ' Hz (Nyquist); a ' + n0(hz) + ' Hz solo es fiable el movimiento lento.', 'nyq', null);
    }
  }

  // ------------------------------------------------------------- en curva ---

  function curva(S, r, add) {
    const imu = S.imu;
    if (!imu) return;
    const d = imu.derived, t = imu.ds.t, [i0, i1] = idx(t, r);
    const der = extremo(t, d.incl_deg, i0, i1, 1), izq = extremo(t, d.incl_deg, i0, i1, -1);
    if (!(der.v === der.v)) return;
    const rueda = S.rueda;

    for (const [lado, e] of [['derecha', der], ['izquierda', izq]]) {
      const th = Math.abs(e.v);
      if (!(th > 5)) continue;
      const lat = Math.tan(th * Math.PI / 180);
      let txt = 'tan θ = a_lat / g: a ' + n1(th) + '° el neumático da ' + n2(lat) + ' g lateral (no depende de la masa). ';
      // velocidad y radio de la curva: con rueda, exacto; si no, con el giro
      let v = rueda ? en(rueda.ds.t, rueda.derived.kmh, e.t) / 3.6 : NaN, como = 'con la velocidad de rueda';
      if (!(v > 2)) {
        const j0 = lb(t, e.t - 0.25), j1 = lb(t, e.t + 0.25);
        let s = 0, c = 0;
        for (let j = j0; j < j1; j++) {
          const w = Math.hypot(d.gy_dps[j], d.gz_dps[j]);   // giro alrededor de la vertical
          if (w === w) { s += w; c++; }
        }
        const w = c ? s / c * Math.PI / 180 : NaN;   // giro de la moto (rad/s)
        v = w > 0.05 ? G * lat / w : NaN;
        como = 'estimado con el giro de la moto, sin sensor de rueda';
      }
      if (v > 2) txt += 'Ibas a ≈ ' + n0(v * 3.6) + ' km/h, así que el radio de la curva era r = v²/(g·tan θ) ≈ ' + n0(v * v / (G * lat)) + ' m (' + como + '). ';
      const nivel = th > THETA(REF.mu.competicion) ? 'aviso' : 'info';
      if (th > THETA(REF.mu.competicion))
        txt += 'Es más de lo que da incluso un neumático de competición (μ 1,5 → ' + n0(THETA(1.5)) + '°): lo más probable es un error de medida (caja suelta o mal calibrada).';
      else txt += 'Con un neumático ' + NEUMATICO[REF.neum] + ' (μ ≈ ' + n1(REF.muMoto) + ') el máximo teórico es atan μ = ' + n0(THETA(REF.muMoto)) + '°: ' +
        (th < THETA(REF.muMoto) ? 'te quedaban ' + n0(THETA(REF.muMoto) - th) + '° de margen.' : 'estás en el límite de tu neumático.');
      add(nivel, 'En curva', 'Inclinación máxima a la ' + lado + ': ' + n1(th) + '°', txt, 'lean', e.t);
    }

    // simetria: cuanto te tumbas a cada lado cuando de verdad tumbas
    const D = [], I = [];
    for (let i = i0; i < i1; i++) { const v = d.incl_deg[i]; if (v > 5) D.push(v); else if (v < -5) I.push(-v); }
    if (D.length > 200 && I.length > 200) {
      const pd = cuantil(D, 0.95), pi = cuantil(I, 0.95), ratio = Math.min(pd, pi) / Math.max(pd, pi);
      if (ratio < 0.75) add('info', 'En curva', 'Te tumbas más a la ' + (pd > pi ? 'derecha' : 'izquierda'),
        'En las curvas habituales (95 % del tiempo tumbado) llegas a ' + n0(pd) + '° a la derecha y ' + n0(pi) + '° a la izquierda. Puede ser el trazado (más curvas de un lado) o que te cueste más un lado.', 'lean', null);
    }

    // circulo de friccion (g-g)
    const gc = { v: NaN, t: NaN };
    let sobre = 0, n = 0;
    for (let i = i0; i < i1; i++) {
      const g = Math.hypot(d.lat[i], d.ax_f[i]);
      if (g !== g) continue;
      n++;
      if (g > 0.5) sobre++;
      if (!(g <= gc.v)) { gc.v = g; gc.t = t[i]; }
    }
    if (gc.v === gc.v) {
      const u = gc.v / REF.muMoto;
      add(u > 0.9 ? 'aviso' : 'info', 'En curva', 'Agarre usado: ' + n0(100 * u) + ' % de un neumático ' + NEUMATICO[REF.neum],
        'En el círculo de fricción, la aceleración total es √(a_lat² + a_long²) y no puede pasar de μ·g. Tu máximo fue ' + n2(gc.v) + ' g; con μ ≈ ' + n1(REF.muMoto) + ' (' + NEUMATICO[REF.neum].replace('de ', '') + ') el límite es ' + n1(REF.muMoto) + ' g' +
        (u > 1 ? ': lo pasa. O el neumático da más (deportivo μ 1,2, competición 1,5) o el pico es un golpe o ruido; míralo con «Ver». '
          : u > 0.9 ? ': estuviste muy cerca. ' : '. ') + 'Pasaste el ' + n1(n ? 100 * sobre / n : NaN) + ' % del tiempo por encima de 0,5 g. En el diagrama g-g se ve cuánto del círculo usas.', 'grip', gc.t);
    }

    // frenar ya tumbado (trail braking)
    const tb = tramos(t, i0, i1, i => d.ax_f[i] < -0.2 && Math.abs(d.incl_deg[i]) > 15, 0.5);
    if (tb.length) {
      let peor = null;
      for (const x of tb) {
        const e = extremo(t, d.ax_f, x.i0, x.i1, -1);
        if (!peor || e.v < peor.a) peor = { a: e.v, t: e.t, th: Math.abs(en(t, d.incl_deg, e.t)) };
      }
      const u = Math.tan(peor.th * Math.PI / 180) / REF.muMoto;
      const disp = u < 1 ? REF.muMoto * Math.sqrt(1 - u * u) : 0;
      add('info', 'En curva', 'Frenas ya tumbado ' + tb.length + ' veces',
        'Frenar dentro de la curva gasta del mismo agarre que el giro: a_long,máx = μ·g·√(1 − u²), con u = a_lat/(μ·g). En la más fuerte frenabas a ' + n2(-peor.a) + ' g con ' + n0(peor.th) + '° de inclinación; con μ ≈ ' + n1(REF.muMoto) + ' ahí quedaban ' + n2(disp) + ' g de frenada posible.', 'grip', peor.t);
    }
  }

  // ------------------------------------------------- frenada y aceleracion ---

  function frenada(S, r, add) {
    const imu = S.imu;
    if (imu) {
      const d = imu.derived, t = imu.ds.t, [i0, i1] = idx(t, r);
      const fr = tramos(t, i0, i1, i => d.ax_f[i] < -0.2, 0.5);
      const fmax = extremo(t, d.ax_f, i0, i1, -1), amax = extremo(t, d.ax_f, i0, i1, 1);
      if (fmax.v < -0.1) {
        const a = -fmax.v, pct = 50 + 100 * REF.h / REF.L * a, dW = REF.h / REF.L * REF.m * a * G;
        add(a > STOPPIE_G * 0.85 ? 'aviso' : 'info', 'Frenada', 'Frenada máxima: ' + n2(a) + ' g' + (fr.length ? ' (' + fr.length + ' frenadas de más de 0,2 g)' : ''),
          'Al frenar, la inercia pasa carga a la rueda delantera: ΔW = (h/L)·m·|a| = ' + n0(dW) + ' N ' + conMoto() + '. ' +
          (a >= STOPPIE_G ? 'Supera el límite de stoppie del modelo, g·L/2h = ' + n2(STOPPIE_G) + ' g: con esta geometría la trasera se habría levantado. O la moto real tiene el centro de masas más bajo o la batalla más larga, o el pico es ruido. '
            : 'La delantera llevaba ≈ ' + n0(pct) + ' % del peso. La trasera se levanta (stoppie) hacia g·L/2h = ' + n2(STOPPIE_G) + ' g. ') + 'Referencias: emergencia en calle 1,2–1,3 g; MotoGP ~1,5 g.', 'load', fmax.t);
      }
      if (amax.v > 0.1) {
        const a = amax.v, pct = 50 + 100 * REF.h / REF.L * a;
        add(a > STOPPIE_G * 0.85 ? 'aviso' : 'info', 'Frenada', 'Aceleración máxima: ' + n2(a) + ' g',
          'Al acelerar la carga pasa a la trasera: llevaba ≈ ' + n0(Math.min(100, pct)) + ' % del peso. La delantera se levanta (wheelie) cuando la transferencia iguala su carga estática, también hacia ' + n2(STOPPIE_G) + ' g con esta geometría. Una salida de curva fuerte en MotoGP ronda 1 g.', 'load', amax.t);
      }
    }

    const ru = S.rueda;
    if (!ru) return;
    const t = ru.ds.t, kmh = ru.derived.kmh, [i0, i1] = idx(t, r);
    const vmax = extremo(t, kmh, i0, i1, 1);
    if (vmax.v > 5) {
      const v = vmax.v / 3.6, F = 0.5 * REF.rho * v * v * REF.cd * REF.area, P = F * v / 735.5;
      add('info', 'Velocidad', 'Velocidad máxima: ' + n0(vmax.v) + ' km/h',
        'A esa velocidad el aire empuja con F_D = ½·ρ·v²·C_D·A ≈ ' + n0(F) + ' N y vencerlo pide P = F_D·v ≈ ' + n0(P) + ' CV (' + (MOTO.carroceria ? MOTO.carroceria : 'naked de la web') + ': C_D ' + n2(REF.cd) + ', A ' + n2(REF.area) + ' m²).' +
        (MOTO.potencia_cv ? ' Tu motor da ' + n1(MOTO.potencia_cv) + ' CV: ' + (P > MOTO.potencia_cv * 0.9 ? 'ibas casi al límite de lo que puede empujar.' : 'el aire se llevaba el ' + n0(100 * P / MOTO.potencia_cv) + ' %.') : '') +
        (MOTO.vmax_kmh ? ' Velocidad máxima de la ficha: ' + n0(MOTO.vmax_kmh) + ' km/h' + (vmax.v > MOTO.vmax_kmh * 1.1 ? ' (la medida la supera: revisa el perímetro de rueda en la ficha).' : '.') : '') + ' La potencia crece con v³.', 'aero', vmax.t);
    }
    // frenadas segun la rueda: la de mas energia
    const v = Float64Array.from(kmh, x => x / 3.6), dv = new Float64Array(v.length).fill(NaN);
    for (let i = i0 + 1; i < i1; i++) {
      const j = lb(t, t[i] - 0.5);
      if (j < i && t[i] - t[j] > 0.2 && v[i] === v[i] && v[j] === v[j]) dv[i] = (v[i] - v[j]) / (t[i] - t[j]);
    }
    const ev = tramos(t, i0, i1, i => dv[i] < -1.5, 0.5, 0.3);
    let mayor = null;
    for (const x of ev) {
      const v1 = Math.max(v[Math.max(i0, lb(t, x.t0 - 0.5))] || 0, v[x.i0] || 0), v2 = v[x.i1 - 1];
      if (!(v1 > v2)) continue;
      const E = 0.5 * REF.m * (v1 * v1 - v2 * v2);
      if (!mayor || E > mayor.E) mayor = { E, v1, v2, t0: x.t0, t1: x.t1, a: (v1 - v2) / Math.max(0.1, x.t1 - x.t0 + 0.5) / G };
    }
    if (mayor) {
      const dT = mayor.E / (REF.disco.n * REF.disco.m * REF.disco.cp);
      let txt = 'De ' + n0(mayor.v1 * 3.6) + ' a ' + n0(mayor.v2 * 3.6) + ' km/h (' + n2(mayor.a) + ' g de media). Energía E = ½·m·(v₁² − v₂²) ≈ ' + n0(mayor.E / 1000) + ' kJ (m ≈ ' + n0(REF.m) + ' kg). ' +
        (REF.tambor
          ? 'Con freno de tambor' + (MOTO.freno_del_mm ? ' de ' + n0(MOTO.freno_del_mm) + ' mm' : '') + ', ese calor se queda en el tambor, que lo evacua peor que un disco: en frenadas seguidas pierde eficacia antes (fading). El modelo del disco de la web no aplica.'
          : 'Si toda fuera a ' + (REF.disco.n === 1 ? 'el disco delantero' : 'los ' + REF.disco.n + ' discos delanteros') + ' de ' + REF.disco.material + ' (' + n1(REF.disco.m) + ' kg, cp ' + REF.disco.cp + '), subirían ΔT = E/(n·m·cp) ≈ ' + n0(dT) + ' °C (cota superior: no cuenta el aire ni el freno trasero).');
      const ir = S.disco;
      if (ir) {
        const T0 = en(ir.ds.t, ir.derived.obj_c, mayor.t0, 2);
        const e = extremo(ir.ds.t, ir.derived.obj_c, lb(ir.ds.t, mayor.t0), lb(ir.ds.t, mayor.t1 + 15), 1);
        if (T0 === T0 && e.v === e.v) txt += ' El sensor IR del disco midió de ' + n0(T0) + ' a ' + n0(e.v) + ' °C (+' + n0(e.v - T0) + ' °C): ' +
          (e.v - T0 > dT * 1.3 ? 'más que la cota: revisa la emisividad o a qué apunta el sensor.' : e.v - T0 < dT * 0.3 ? 'mucho menos que la cota: el freno trasero, el motor y el aire se llevan buena parte, o el sensor no mira la pista de frenado.' : 'del orden de la cota, como predice el modelo.');
      }
      add('info', 'Frenada', 'Frenada más fuerte según la rueda', txt, 'brake', mayor.t0);
    }

    // IMU frente a rueda: deben dar la misma deceleracion
    if (S.imu && mayor) {
      const d = S.imu.derived, ti = S.imu.ds.t;
      const j0 = lb(ti, mayor.t0), j1 = lb(ti, mayor.t1);
      let s = 0, c = 0;
      for (let j = j0; j < j1; j++) if (d.ax_f[j] === d.ax_f[j]) { s += d.ax_f[j]; c++; }
      const aImu = c ? -s / c : NaN, aRueda = mayor.a;
      if (aImu === aImu && Math.abs(aImu - aRueda) > 0.3 * Math.max(aImu, aRueda, 0.1))
        add('aviso', 'Correlación', 'El acelerómetro/giroscopio y la rueda no cuentan la misma frenada',
          'En esa frenada la rueda da ' + n2(aRueda) + ' g de media y el acelerómetro ' + n2(aImu) + ' g. Deberían coincidir: si la rueda da más, puede haberse bloqueado o patinar; si da menos, revisa el diámetro de rueda configurado o la calibración del acelerómetro/giroscopio.', 'stop', mayor.t0);
    }
  }

  // ------------------------------------------------------------ suspension ---

  function suspension(S, r, add) {
    const su = S.suspension;
    if (!su) return;
    const t = su.ds.t, tr = su.derived.travel, [i0, i1] = idx(t, r);
    const cmax = extremo(t, tr, i0, i1, 1), emax = extremo(t, tr, i0, i1, -1);
    if (!(cmax.v === cmax.v)) return;
    add('info', 'Suspensión', 'Recorrido usado: de ' + n0(emax.v) + ' a +' + n0(cmax.v) + ' mm',
      'Compresión máxima de ' + n0(cmax.v) + ' mm sobre la referencia en reposo. Si nunca te acercas al final del recorrido, la suspensión va dura o precargada de más; si llegas a menudo, blanda.', 'quarter', cmax.t);
    // frecuencia dominante: cruces por la media movil de 1 s (quita frenadas
    // y aceleraciones, que son mas lentas); solo si sale en un rango fisico
    const hz = (i1 - i0 - 1) / ((t[i1 - 1] - t[i0]) || 1);
    const w = Math.max(3, Math.round(hz)), base = Sensors.smooth(tr, w), lis = Sensors.smooth(tr, 3);
    let cruces = 0, dur = 0, prev = 0;
    for (let i = i0 + 1; i < i1; i++) {
      const x = lis[i] - base[i];
      if (x !== x) { prev = 0; continue; }
      const sg = Math.abs(x) < 1 ? 0 : Math.sign(x);
      if (sg && prev && sg !== prev) cruces++;
      if (sg) prev = sg;
      if (t[i] - t[i - 1] < 0.5) dur += t[i] - t[i - 1];
    }
    let f = dur > 5 ? cruces / (2 * dur) : NaN;
    if (!(f >= 0.8 && f <= 8)) f = NaN;
    if (f === f) add('info', 'Suspensión', 'Oscila sobre todo a ≈ ' + n1(f) + ' Hz',
      'La web calcula la frecuencia de la carrocería con f_s = √(ks/ms)/2π: ' + n1(Math.sqrt(28000 / 105) / (2 * Math.PI)) + ' Hz en la trail cargada, ' + n1(FS) + ' Hz con los valores por defecto y ' + n1(Math.sqrt(50000 / 60) / (2 * Math.PI)) + ' Hz en la de carreras. ' +
      (f < 2 ? 'Por debajo: muelle blando o mucha masa encima.' : f > 5 ? 'Por encima: muelle duro, o se mezcla con el movimiento de la rueda.' : 'Está en ese rango.') +
      ' En asfalto ondulado cada ' + REF.ondulado + ' m la resonancia llega a v = f·λ ≈ ' + n0(f * REF.ondulado * 3.6) + ' km/h.', 'res', null);

    // correlacion con la IMU: al frenar la trasera se descarga y se extiende
    if (S.imu) {
      const d = S.imu.derived, ti = S.imu.ds.t, [j0, j1] = idx(ti, r);
      const fr = tramos(ti, j0, j1, i => d.ax_f[i] < -0.25, 0.5);
      let sf = 0, cf = 0, sn = 0, cn = 0;
      for (let i = i0; i < i1; i++) {
        const v = tr[i];
        if (v !== v) continue;
        if (fr.some(x => t[i] >= x.t0 && t[i] <= x.t1)) { sf += v; cf++; } else { sn += v; cn++; }
      }
      if (cf > 10 && cn > 10) {
        const dif = sf / cf - sn / cn;
        add(dif > 0 ? 'aviso' : 'info', 'Correlación', 'Al frenar la trasera ' + (dif < 0 ? 'se extiende ' : 'se comprime ') + n0(Math.abs(dif)) + ' mm de media',
          'Con transferencia de carga ΔW = (h/L)·m·|a|, al frenar la trasera pierde peso y su suspensión se extiende. ' +
          (dif < 0 ? 'Es lo que se ve: cuadra con la teoría.' : 'Aquí se comprime: revisa el sentido del montaje del sensor (opción «Montaje» del bloque).'), 'load', fr.length ? fr[0].t0 : null);
      }
    }
  }

  // --------------------------------------------------------- temperaturas ---

  function temperaturas(S, r, add) {
    const ir = S.disco;
    if (ir) {
      const t = ir.ds.t, [i0, i1] = idx(t, r), e = extremo(t, ir.derived.obj_c, i0, i1, 1);
      if (e.v === e.v) {
        const lim = REF.disco.limite, u = e.v / lim;
        add(u > 0.8 ? 'aviso' : 'info', 'Frenos', 'Disco de freno: máximo ' + n0(e.v) + ' °C',
          'El límite orientativo de un disco de ' + REF.disco.material + ' en la web es ' + lim + ' °C (a partir de ahí empieza el fading). ' +
          (u > 0.8 ? 'Estás cerca: en frenadas repetidas el calor se acumula si no da tiempo a enfriar (T_sig = T_amb + (T_pico − T_amb)·e^(−t/τ)).' : 'Vas con margen (' + n0(100 * u) + ' % del límite).'), u > 0.8 ? 'rep' : 'brake', e.t);
      }
    }
    for (const s of S.temp) {
      const t = s.ds.t, [i0, i1] = idx(t, r), y = s.derived.temp_c || s.derived.obj_c;
      if (!y) continue;
      const e = extremo(t, y, i0, i1, 1);
      if (e.v === e.v) add('info', 'Temperaturas', s.ds.name + ': máximo ' + n0(e.v) + ' °C', 'Pulsa «Ver» para ir al momento del máximo.', null, e.t);
    }
  }

  // --------------------------------------------------------------- vueltas ---

  function vueltas(S, r, add) {
    const b = S.boton;
    if (!b) return;
    const t = b.ds.t, [i0, i1] = idx(t, r), tv = b.derived.t_vuelta_s;
    if (!tv) return;
    const L = [], tt = [];
    for (let i = i0; i < i1; i++) if (tv[i] === tv[i] && tv[i] > 0) { L.push(tv[i]); tt.push(t[i]); }
    if (L.length < 2) return;
    const m = L.reduce((a, x) => a + x, 0) / L.length;
    const sd = Math.sqrt(L.reduce((a, x) => a + (x - m) * (x - m), 0) / L.length);
    const kb = L.indexOf(Math.min(...L));
    add(sd / m > 0.03 ? 'info' : 'ok', 'Vueltas', L.length + ' vueltas: mejor ' + n2(L[kb]) + ' s, media ' + n2(m) + ' s',
      'Dispersión ' + n2(sd) + ' s (' + n1(100 * sd / m) + ' %). ' + (sd / m > 0.03 ? 'Ritmo irregular: compara la mejor con las demás en el g-g.' : 'Ritmo muy regular.'), null, tt[kb]);
  }

  // ----------------------------------------------------------------- todo ---

  function agrupar(sets) {
    const S = { todos: sets, temp: [] };
    for (const s of sets) {
      if (!s.derived) continue;
      const id = s.def.id;
      if (id === 'imu' && !S.imu) S.imu = s;
      else if (id === 'rueda' && (!S.rueda || /tras/.test(s.ds.id))) S.rueda = s;
      else if (id === 'suspension' && !S.suspension) S.suspension = s;
      else if (id === 'boton' && !S.boton) S.boton = s;
      else if (id === 'infrarrojos' && /fren|disco/i.test((s.ds.meta && s.ds.meta.apunta_a) || '') && !S.disco) S.disco = s;
      else if (id === 'termopar' || id === 'infrarrojos') S.temp.push(s);
    }
    return S;
  }

  const ORDEN_NIVEL = { aviso: 0, info: 1, ok: 2 };
  const TEMAS = ['Moto', 'Datos', 'En curva', 'Frenada', 'Velocidad', 'Correlación', 'Suspensión', 'Frenos', 'Temperaturas', 'Vueltas'];

  function ficha(add) {
    const f = MOTO;
    if (!Object.keys(f).length) {
      add('info', 'Moto', 'Sin ficha de la moto: se usa la moto de ejemplo de la formación',
        'Peso, batalla, neumáticos y frenos son los de la web (220 kg, 1,40 m, neumático de calle, discos de acero). Rellena la pestaña Moto en vivo y las sesiones que grabes después se analizarán con tu moto.', null, null);
      return;
    }
    const faltan = [['peso_seco_kg', 'peso'], ['batalla_m', 'batalla'], ['altura_cm_m', 'altura del centro de masas'], ['neumaticos', 'neumáticos'], ['perimetro_tras_m', 'perímetro de rueda'], ['susp_tras_mm', 'recorrido de suspensión']]
      .filter(([k]) => f[k] == null).map(([, t]) => t);
    add('ok', 'Moto', 'Analizado con: ' + (f.nombre || 'tu moto'),
      'Masa en marcha ≈ ' + n0(REF.m) + ' kg' + (f.peso_seco_kg ? ' (' + n0(f.peso_seco_kg) + ' en seco + ' + n0(f.piloto_kg || 75) + ' piloto' + (f.deposito_l ? ' + medio depósito' : '') + ')' : '') +
      '; neumático ' + NEUMATICO[REF.neum] + ' (μ ≈ ' + n1(REF.muMoto) + '); freno delantero ' + (REF.tambor ? 'de tambor' : 'de disco') +
      (faltan.length ? '. Sin dato (se usa el de la web o no se calcula): ' + faltan.join(', ') + '.' : '.'), null, null);
  }

  function analizar(sets, rango, moto) {
    configurar(moto);
    const S = agrupar(sets), { lista, add } = nuevo();
    ficha(add);
    for (const regla of [calidad, curva, frenada, suspension, temperaturas, vueltas]) {
      try { regla(S, rango, add); } catch (e) { console.error('analisis', regla.name, e); }
    }
    return lista.sort((a, b) => TEMAS.indexOf(a.tema) - TEMAS.indexOf(b.tema) || ORDEN_NIVEL[a.nivel] - ORDEN_NIVEL[b.nivel]);
  }

  global.Analisis = { analizar, WEB };
})(window);
