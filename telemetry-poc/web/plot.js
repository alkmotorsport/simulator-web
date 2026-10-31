/*
 * Mini libreria de graficas en canvas, sin dependencias (funciona offline).
 *
 *   ChartGroup  sincroniza cursor y zoom entre graficas temporales.
 *   TimeChart   serie temporal; reduce a min/max por pixel, asi que pinta
 *               cientos de miles de muestras sin problema. Los NaN son huecos.
 *   Histogram   barras con los bordes de los bins y su valor (en %).
 *   GG          diagrama g-g (lateral / longitudinal) como mapa de densidad.
 *
 * Los colores se leen de variables CSS en cada repintado, de modo que el
 * tema claro/oscuro se aplica solo con llamar a draw().
 */
(function (global) {
  'use strict';

  const PAD = { l: 54, r: 12, t: 8, b: 24 };

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function niceStep(range, target) {
    if (!(range > 0)) return 1;
    const raw = range / Math.max(1, target);
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const m = raw / p;
    return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
  }

  function ticks(min, max, target) {
    const step = niceStep(max - min, target);
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
      out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    }
    return { values: out, step };
  }

  function fmtTick(v, step) {
    const dec = Math.max(0, Math.min(4, -Math.floor(Math.log10(step) + 1e-9)));
    return v.toFixed(dec);
  }

  /** Primer indice i con t[i] >= x (t ordenado). */
  function lowerBound(t, x) {
    let lo = 0, hi = t.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (t[mid] < x) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  function el(tag, cls, parent) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (parent) parent.appendChild(e);
    return e;
  }

  /** Lienzo base + lienzo superpuesto (cursor/seleccion) con soporte HiDPI. */
  class Surface {
    constructor(container, opts, onResize) {
      this.opts = opts;
      this.root = el('figure', 'chart', container);
      const cap = el('figcaption', '', this.root);
      const title = el('span', 'chart-title', cap);
      title.textContent = opts.title || '';
      if (opts.unit) el('span', 'chart-unit', title).textContent = ' · ' + opts.unit;
      if (opts.note) el('span', 'chart-note', cap).textContent = opts.note;
      this.readout = el('span', 'chart-readout', cap);
      this.wrap = el('div', 'chart-wrap', this.root);
      // opts.id: la grafica se pliega tocando su titulo (y se recuerda en este navegador)
      if (opts.id) {
        const k = 'tele-plegada-' + opts.id;
        title.classList.add('plegable');
        title.setAttribute('role', 'button');
        title.tabIndex = 0;
        const poner = p => {
          this.root.classList.toggle('plegada', p);
          title.setAttribute('aria-expanded', String(!p));
        };
        try { poner(localStorage.getItem(k) === '1'); } catch (e) { poner(false); }
        const cambiar = () => {
          const p = !this.root.classList.contains('plegada');
          poner(p);
          try { if (p) localStorage.setItem(k, '1'); else localStorage.removeItem(k); } catch (e) { /* sin almacenamiento */ }
        };
        title.addEventListener('click', cambiar);
        title.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); cambiar(); } });
      }
      this.wrap.style.height = (opts.height || 200) + 'px';
      this.base = el('canvas', '', this.wrap);
      this.over = el('canvas', 'chart-over', this.wrap);
      this.w = 0; this.h = 0;
      this.ro = new ResizeObserver(() => { this.resize(); onResize(); });
      this.ro.observe(this.wrap);
    }
    resize() {
      const r = this.wrap.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.w = Math.max(10, r.width); this.h = Math.max(10, r.height); this.dpr = dpr;
      for (const c of [this.base, this.over]) {
        c.width = Math.round(this.w * dpr); c.height = Math.round(this.h * dpr);
        // siempre a todo el recuadro: con un tamano viejo se veria en miniatura en una esquina
        c.style.width = '100%'; c.style.height = '100%';
        c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    }
    /** Antes de dibujar: si el recuadro o la escala han cambiado y no se ha
     *  avisado (algunos moviles no lo hacen al cargar), se rehace el lienzo. */
    fit() {
      const r = this.wrap.getBoundingClientRect();
      if (Math.abs(r.width - this.w) > 0.5 || Math.abs(r.height - this.h) > 0.5 ||
          (window.devicePixelRatio || 1) !== this.dpr) this.resize();
    }
    plotRect() {
      return { x: PAD.l, y: PAD.t, w: this.w - PAD.l - PAD.r, h: this.h - PAD.t - PAD.b };
    }
    destroy() { this.ro.disconnect(); this.root.remove(); }
  }

  function drawYAxis(ctx, R, ymin, ymax, colors) {
    const ty = ticks(ymin, ymax, Math.max(2, Math.floor(R.h / 40)));
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    ctx.lineWidth = 1;
    for (const v of ty.values) {
      const y = Math.round(R.y + R.h - (v - ymin) / (ymax - ymin) * R.h) + 0.5;
      ctx.strokeStyle = v === 0 ? colors.axis : colors.grid;
      ctx.beginPath(); ctx.moveTo(R.x, y); ctx.lineTo(R.x + R.w, y); ctx.stroke();
      ctx.fillStyle = colors.muted;
      ctx.fillText(fmtTick(v, ty.step), R.x - 6, y);
    }
  }

  function themeColors() {
    return {
      grid: cssVar('--chart-grid'), axis: cssVar('--chart-axis'),
      muted: cssVar('--sub'), text: cssVar('--text'), surface: cssVar('--card'),
      select: cssVar('--chart-select'), warn: cssVar('--status-warning'),
    };
  }

  // -------------------------------------------------------------- grupo ---

  class ChartGroup {
    constructor() {
      this.charts = [];
      this.range = null;       // [x0, x1] o null = todo
      this.cursor = null;      // x bajo el puntero
      this.zoomable = true;
      this.listeners = [];
    }
    add(c) { this.charts.push(c); c.group = this; return c; }
    onRange(fn) { this.listeners.push(fn); }
    setRange(r) {
      this.range = r;
      this.listeners.forEach(fn => fn(r));
      this.draw();
    }
    setCursor(x) { this.cursor = x; this.charts.forEach(c => c.drawOverlay()); }
    /** Extension total de datos de las graficas del grupo. */
    extent() {
      let a = Infinity, b = -Infinity;
      for (const c of this.charts) {
        const t = c.t; if (!t || !t.length) continue;
        a = Math.min(a, t[0]); b = Math.max(b, t[t.length - 1]);
      }
      return a < b ? [a, b] : [0, 1];
    }
    xRange() { return this.range || this.extent(); }
    draw() { this.charts.forEach(c => c.draw()); }
    destroy() { this.charts.forEach(c => c.destroy()); this.charts = []; }
  }

  // ----------------------------------------------------------- temporal ---

  class TimeChart {
    /**
     * opts: title, unit, note, color (variable CSS), height, decimals,
     *       zero (incluir el 0 en la escala), gaps (marcar muestras perdidas),
     *       gapMax (s sin datos a partir de los cuales se corta la linea)
     */
    constructor(container, opts) {
      this.opts = Object.assign({ height: 200, decimals: 1, gapMax: 0.2 }, opts);
      this.s = new Surface(container, this.opts, () => this.draw());
      this.t = []; this.y = [];
      this.drag = null;
      this._bind();
    }
    setData(t, y) { this.t = t; this.y = y; }
    destroy() { this.s.destroy(); }

    _xOf(x, R, x0, x1) { return R.x + (x - x0) / (x1 - x0) * R.w; }
    _tOf(px, R, x0, x1) { return x0 + (px - R.x) / R.w * (x1 - x0); }

    _bind() {
      const over = this.s.over;
      const pos = e => e.clientX - over.getBoundingClientRect().left;
      over.addEventListener('pointermove', e => {
        const R = this.s.plotRect(), [x0, x1] = this.group.xRange();
        const px = Math.min(R.x + R.w, Math.max(R.x, pos(e)));
        if (this.drag) this.drag.b = px;
        this.group.setCursor(this._tOf(px, R, x0, x1));
      });
      over.addEventListener('pointerleave', () => { if (!this.drag) this.group.setCursor(null); });
      over.addEventListener('pointerdown', e => {
        if (!this.group.zoomable) return;
        over.setPointerCapture(e.pointerId);
        this.drag = { a: pos(e), b: pos(e) };
      });
      over.addEventListener('pointerup', () => {
        const d = this.drag; this.drag = null;
        if (!d) return;
        if (Math.abs(d.b - d.a) > 6) {
          const R = this.s.plotRect(), [x0, x1] = this.group.xRange();
          const a = this._tOf(Math.min(d.a, d.b), R, x0, x1);
          const b = this._tOf(Math.max(d.a, d.b), R, x0, x1);
          this.group.setRange([a, b]);
        } else this.drawOverlay();
      });
      over.addEventListener('dblclick', () => { if (this.group.zoomable) this.group.setRange(null); });
    }

    _visible() {
      const [x0, x1] = this.group.xRange();
      const t = this.t, n = t.length;
      const i0 = Math.max(0, lowerBound(t, x0) - 1);
      const i1 = Math.min(n, lowerBound(t, x1) + 1);
      return { x0, x1, i0, i1 };
    }

    _yRange(i0, i1) {
      const y = this.y, o = this.opts;
      if (o.yRange) return o.yRange;
      let lo = Infinity, hi = -Infinity;
      for (let i = i0; i < i1; i++) {
        const v = y[i];
        if (v === v) { if (v < lo) lo = v; if (v > hi) hi = v; }
      }
      if (o.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
      for (const l of o.lines || []) { lo = Math.min(lo, l.y); hi = Math.max(hi, l.y); }
      if (!(lo <= hi)) { lo = -1; hi = 1; }
      if (hi - lo < (o.minSpan || 1e-6)) { const m = (lo + hi) / 2, s = (o.minSpan || 2) / 2; lo = m - s; hi = m + s; }
      const pad = (hi - lo) * 0.06;
      return [lo - pad, hi + pad];
    }

    draw() {
      const s = this.s; s.fit(); if (!s.w || !this.group) return;
      const ctx = s.base.getContext('2d');
      const C = themeColors();
      ctx.clearRect(0, 0, s.w, s.h);
      const R = s.plotRect();
      const { x0, x1, i0, i1 } = this._visible();
      const [ymin, ymax] = this._yRange(i0, i1);
      this._scale = { x0, x1, ymin, ymax };

      drawYAxis(ctx, R, ymin, ymax, C);
      // eje X (tiempo)
      const tx = ticks(x0, x1, Math.max(2, Math.floor(R.w / 90)));
      ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillStyle = C.muted;
      for (const v of tx.values) {
        const x = Math.round(this._xOf(v, R, x0, x1)) + 0.5;
        ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(x, R.y); ctx.lineTo(x, R.y + R.h); ctx.stroke();
        ctx.fillText(fmtTick(v, tx.step) + ' s', x, R.y + R.h + 6);
      }

      ctx.save();
      ctx.beginPath(); ctx.rect(R.x, R.y, R.w, R.h); ctx.clip();

      // lineas de referencia (umbrales), discontinuas y con etiqueta
      ctx.font = '11px system-ui, sans-serif';
      ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
      for (const l of this.opts.lines || []) {
        const ly = Math.round(R.y + R.h - (l.y - ymin) / (ymax - ymin) * R.h) + 0.5;
        ctx.strokeStyle = cssVar(l.color);
        ctx.setLineDash([5, 4]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(R.x, ly); ctx.lineTo(R.x + R.w, ly); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = C.muted;
        ctx.fillText(l.label, R.x + R.w - 4, ly - 2);
      }

      const t = this.t, y = this.y;
      const sx = R.w / (x1 - x0), sy = R.h / (ymax - ymin);
      const Y = v => R.y + R.h - (v - ymin) * sy;
      const gapMax = this.opts.gapMax;
      const lost = this.opts.gaps ? new Set() : null;

      ctx.beginPath();
      let col = null, cMin = 0, cMax = 0, cFirst = 0, cLast = 0, lastT = -Infinity, broken = true;
      const flush = () => {
        if (col === null) return;
        const X = R.x + col + 0.5;
        if (broken) ctx.moveTo(X, Y(cFirst)); else ctx.lineTo(X, Y(cFirst));
        if (cMin !== cMax) { ctx.lineTo(X, Y(cMin)); ctx.lineTo(X, Y(cMax)); }
        ctx.lineTo(X, Y(cLast));
        broken = false;
      };
      for (let i = i0; i < i1; i++) {
        const v = y[i], ti = t[i];
        if (v !== v) { if (lost) lost.add(Math.floor((ti - x0) * sx)); continue; }
        if (ti - lastT > gapMax) { flush(); col = null; broken = true; }
        const c = Math.floor((ti - x0) * sx);
        if (c !== col) { flush(); col = c; cMin = cMax = cFirst = cLast = v; }
        else { if (v < cMin) cMin = v; if (v > cMax) cMax = v; cLast = v; }
        lastT = ti;
      }
      flush();
      ctx.strokeStyle = cssVar(this.opts.color) || C.text;
      ctx.lineWidth = 1.5; ctx.lineJoin = 'round';
      ctx.stroke();

      if (lost && lost.size) {
        ctx.fillStyle = C.warn;
        for (const c of lost) ctx.fillRect(R.x + c, R.y + R.h - 5, 2, 5);
      }
      ctx.restore();
      this.drawOverlay();
    }

    drawOverlay() {
      const s = this.s; if (!s.w || !this._scale) return;
      const ctx = s.over.getContext('2d');
      ctx.clearRect(0, 0, s.w, s.h);
      const R = s.plotRect(), { x0, x1, ymin, ymax } = this._scale;
      const C = themeColors();

      if (this.drag && Math.abs(this.drag.b - this.drag.a) > 1) {
        ctx.fillStyle = C.select;
        ctx.fillRect(Math.min(this.drag.a, this.drag.b), R.y, Math.abs(this.drag.b - this.drag.a), R.h);
      }

      const cur = this.group.cursor;
      if (cur == null || cur < x0 || cur > x1 || !this.t.length) {
        this.s.readout.textContent = '';
        return;
      }
      const X = Math.round(this._xOf(cur, R, x0, x1)) + 0.5;
      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(X, R.y); ctx.lineTo(X, R.y + R.h); ctx.stroke();

      // muestra mas cercana al cursor
      const t = this.t, y = this.y;
      let i = lowerBound(t, cur);
      if (i > 0 && (i >= t.length || cur - t[i - 1] < t[i] - cur)) i--;
      const v = y[i];
      const u = this.opts.unit ? ' ' + this.opts.unit : '';
      this.s.readout.textContent = 't ' + t[i].toFixed(3) + ' s · ' +
        (v === v ? v.toFixed(this.opts.decimals) + u : 'sin dato');
      if (v === v) {
        const px = this._xOf(t[i], R, x0, x1);
        const py = R.y + R.h - (v - ymin) / (ymax - ymin) * R.h;
        ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = cssVar(this.opts.color); ctx.fill();
        ctx.lineWidth = 2; ctx.strokeStyle = C.surface; ctx.stroke();
      }
    }
  }

  // ---------------------------------------------------------- histograma ---

  class Histogram {
    /** opts: title, unit, note, height, colorFor(centro) -> variable CSS */
    constructor(container, opts) {
      this.opts = Object.assign({ height: 200, colorFor: () => '--series-1' }, opts);
      this.s = new Surface(container, this.opts, () => this.draw());
      this.edges = []; this.values = []; this.hover = -1;
      const over = this.s.over;
      over.addEventListener('pointermove', e => {
        const R = this.s.plotRect(), n = this.values.length;
        const px = e.clientX - over.getBoundingClientRect().left;
        const k = Math.floor((px - R.x) / R.w * n);
        this.hover = k >= 0 && k < n ? k : -1;
        this.drawOverlay();
      });
      over.addEventListener('pointerleave', () => { this.hover = -1; this.drawOverlay(); });
    }
    setData(edges, values) { this.edges = edges; this.values = values; }
    destroy() { this.s.destroy(); }

    draw() {
      const s = this.s; s.fit(); if (!s.w) return;
      const ctx = s.base.getContext('2d');
      const C = themeColors();
      ctx.clearRect(0, 0, s.w, s.h);
      const R = s.plotRect(), n = this.values.length;
      if (!n) { this.drawOverlay(); return; }
      let vmax = 0; for (const v of this.values) vmax = Math.max(vmax, v);
      vmax = vmax > 0 ? vmax * 1.08 : 1;
      drawYAxis(ctx, R, 0, vmax, C);

      const e = this.edges, bw = R.w / n;
      const gap = Math.min(2, bw * 0.25);
      for (let k = 0; k < n; k++) {
        const h = this.values[k] / vmax * R.h;
        if (h <= 0) continue;
        const x = R.x + k * bw + gap / 2, w = Math.max(1, bw - gap);
        ctx.fillStyle = cssVar(this.opts.colorFor((e[k] + e[k + 1]) / 2));
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, R.y + R.h - h, w, h, [Math.min(4, w / 2), Math.min(4, w / 2), 0, 0]);
        else ctx.rect(x, R.y + R.h - h, w, h);
        ctx.fill();
      }
      // etiquetas del eje X sobre los bordes de bin
      const step = niceStep(e[n] - e[0], Math.max(2, Math.floor(R.w / 70)));
      ctx.fillStyle = C.muted; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      for (let v = Math.ceil(e[0] / step) * step; v <= e[n] + 1e-9; v += step) {
        const x = R.x + (v - e[0]) / (e[n] - e[0]) * R.w;
        ctx.fillText(fmtTick(Math.abs(v) < 1e-9 ? 0 : v, step), x, R.y + R.h + 6);
      }
      this.drawOverlay();
    }

    drawOverlay() {
      const s = this.s; if (!s.w) return;
      const ctx = s.over.getContext('2d');
      ctx.clearRect(0, 0, s.w, s.h);
      const k = this.hover;
      if (k < 0 || !this.values.length) { s.readout.textContent = ''; return; }
      const R = s.plotRect(), bw = R.w / this.values.length;
      ctx.fillStyle = themeColors().select;
      ctx.fillRect(R.x + k * bw, R.y, bw, R.h);
      const u = this.opts.unit ? ' ' + this.opts.unit : '';
      const d = Math.abs(this.edges[1] - this.edges[0]) < 1 ? 2 : 0;
      s.readout.textContent = this.edges[k].toFixed(d) + ' … ' + this.edges[k + 1].toFixed(d) +
        u + ' · ' + this.values[k].toFixed(1) + ' %';
    }
  }

  // ------------------------------------------------------------ g-g ---

  class GG {
    /**
     * Diagrama g-g (circulo de friccion) como mapa de densidad: lateral en X
     * (+ derecha), longitudinal en Y (+ acelera). setData(edges, values, ahora):
     * edges de los bins (iguales en X e Y), values[iy * n + ix] en % del tiempo
     * y, en vivo, el punto actual [x, y].
     * opts: title, unit, note, height, color (variable CSS)
     */
    constructor(container, opts) {
      this.opts = Object.assign({ height: 260, color: '--series-1' }, opts);
      this.s = new Surface(container, this.opts, () => this.draw());
      this.edges = []; this.values = []; this.ahora = null; this.hover = null;
      const over = this.s.over;
      over.addEventListener('pointermove', e => {
        const r = over.getBoundingClientRect(), Q = this.cuadro();
        if (!Q) return;
        const ix = Math.floor((e.clientX - r.left - Q.x) / Q.c), iy = Math.floor((Q.y + Q.l - (e.clientY - r.top)) / Q.c);
        this.hover = ix >= 0 && iy >= 0 && ix < Q.n && iy < Q.n ? [ix, iy] : null;
        this.drawOverlay();
      });
      over.addEventListener('pointerleave', () => { this.hover = null; this.drawOverlay(); });
    }
    setData(edges, values, ahora) { this.edges = edges; this.values = values; this.ahora = ahora || null; }
    destroy() { this.s.destroy(); }

    /** Zona cuadrada centrada: x, y (arriba-izquierda), lado l, n bins de c px. */
    cuadro() {
      const s = this.s, n = this.edges.length - 1;
      if (!s.w || n < 1) return null;
      const l = Math.max(10, Math.min(s.w - 70, s.h - 30));
      return { x: (s.w - l) / 2, y: 8, l, n, c: l / n, lo: this.edges[0], hi: this.edges[n] };
    }
    px(Q, gx, gy) {
      return [Q.x + (gx - Q.lo) / (Q.hi - Q.lo) * Q.l, Q.y + Q.l - (gy - Q.lo) / (Q.hi - Q.lo) * Q.l];
    }

    draw() {
      const s = this.s; s.fit(); if (!s.w) return;
      const ctx = s.base.getContext('2d'), C = themeColors();
      ctx.clearRect(0, 0, s.w, s.h);
      const Q = this.cuadro();
      if (!Q) { this.drawOverlay(); return; }
      // densidad: escala logaritmica para que se vea tambien lo poco frecuente
      let vmax = 0; for (const v of this.values) if (v > vmax) vmax = v;
      ctx.fillStyle = cssVar(this.opts.color);
      for (let iy = 0; iy < Q.n; iy++) for (let ix = 0; ix < Q.n; ix++) {
        const v = this.values[iy * Q.n + ix];
        if (!(v > 0)) continue;
        ctx.globalAlpha = 0.15 + 0.85 * Math.log1p(v * 1000) / Math.log1p(vmax * 1000);
        ctx.fillRect(Q.x + ix * Q.c, Q.y + Q.l - (iy + 1) * Q.c, Math.ceil(Q.c), Math.ceil(Q.c));
      }
      ctx.globalAlpha = 1;
      // ejes y circulos cada 0,25 g (con texto los de g entera y media)
      const [cx, cy] = this.px(Q, 0, 0), k = Q.l / (Q.hi - Q.lo);
      ctx.lineWidth = 1; ctx.strokeStyle = C.axis;
      ctx.beginPath(); ctx.moveTo(Q.x, cy); ctx.lineTo(Q.x + Q.l, cy); ctx.moveTo(cx, Q.y); ctx.lineTo(cx, Q.y + Q.l); ctx.stroke();
      ctx.font = '11px system-ui, sans-serif'; ctx.fillStyle = C.muted;
      ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
      for (let g = 0.25; g <= Q.hi + 1e-9; g += 0.25) {
        const entero = Math.abs(g * 2 - Math.round(g * 2)) < 1e-9;
        ctx.strokeStyle = entero ? C.axis : C.grid;
        ctx.beginPath(); ctx.arc(cx, cy, g * k, 0, 2 * Math.PI); ctx.stroke();
        if (entero) ctx.fillText(String(g).replace('.', ',') + ' g', cx + g * k * 0.71 + 2, cy - g * k * 0.71 - 1);
      }
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText('← izquierda · lateral · derecha →', cx, Q.y + Q.l + 4);
      ctx.save(); ctx.translate(Q.x - 8, cy); ctx.rotate(-Math.PI / 2); ctx.textBaseline = 'bottom';
      ctx.fillText('← frena · acelera →', 0, 0); ctx.restore();
      this.drawOverlay();
    }

    drawOverlay() {
      const s = this.s; if (!s.w) return;
      const ctx = s.over.getContext('2d');
      ctx.clearRect(0, 0, s.w, s.h);
      const Q = this.cuadro();
      s.readout.textContent = '';
      if (!Q) return;
      if (this.ahora && this.ahora.every(v => v === v)) {
        const [x, y] = this.px(Q, Math.max(Q.lo, Math.min(Q.hi, this.ahora[0])), Math.max(Q.lo, Math.min(Q.hi, this.ahora[1])));
        ctx.fillStyle = themeColors().warn;
        ctx.beginPath(); ctx.arc(x, y, 5, 0, 2 * Math.PI); ctx.fill();
        s.readout.textContent = 'ahora ' + this.ahora[0].toFixed(2) + ' / ' + this.ahora[1].toFixed(2) + ' g';
      }
      if (!this.hover) return;
      const [ix, iy] = this.hover, e = this.edges, v = this.values[iy * Q.n + ix] || 0;
      ctx.fillStyle = themeColors().select;
      ctx.fillRect(Q.x + ix * Q.c, Q.y + Q.l - (iy + 1) * Q.c, Q.c, Q.c);
      s.readout.textContent = 'lateral ' + ((e[ix] + e[ix + 1]) / 2).toFixed(2) + ' g · longitudinal ' +
        ((e[iy] + e[iy + 1]) / 2).toFixed(2) + ' g · ' + (v < 0.01 && v > 0 ? '<0,01' : v.toFixed(2)) + ' % del tiempo';
    }
  }

  global.Plot = { ChartGroup, TimeChart, Histogram, GG, niceStep, lowerBound };
})(window);
