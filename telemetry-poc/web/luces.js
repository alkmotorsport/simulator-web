/*
 * Cuadro «Luces y alertas» (en Sensores y salidas): edita lo que hacen las
 * luces WS2812 en cada pagina de la pantalla y las alertas, y lo guarda en el
 * sistema (POST /api/luces; el formato esta en modulos/luces.py).
 *
 *   LucesCfg.abrir(caja, { leer, enviar, cerrar })
 *     leer()                 -> promesa con lo de GET /api/luces
 *     enviar(ruta, cuerpo)   -> POST a la raspi (lanza Error con su mensaje)
 *     cerrar()               -> boton Cerrar (pliega la pestana)
 */
(function (global) {
  'use strict';

  const NOMBRE_COLOR = { off: 'apagada', rojo: 'rojo', ambar: 'ámbar', verde: 'verde', azul: 'azul', morado: 'morado', blanco: 'blanco' };
  const NOMBRE_EFECTO = { fijo: 'fijo', lento: 'parpadeo lento', rapido: 'parpadeo rápido', destello: 'destello' };
  const OPS = { '>': 'más de', '<': 'menos de' };

  function el(tag, cls, parent, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function campo(parent, etiqueta, control, cls) {
    const l = el('label', 'field' + (cls ? ' ' + cls : ''), parent, etiqueta);
    l.appendChild(control);
    return control;
  }
  function select(opciones, valor, onChange) {
    const s = el('select');
    for (const [v, t] of opciones) s.add(new Option(t, v, false, String(v) === String(valor)));
    s.addEventListener('change', () => onChange(s.value));
    return s;
  }
  function numero(valor, onChange, paso = 'any') {
    const i = el('input');
    i.type = 'number'; i.step = paso; i.value = valor; i.inputMode = 'decimal';
    i.addEventListener('input', () => { if (i.value !== '') onChange(+i.value); });
    return i;
  }
  /** Selector de color con su muestra al lado. */
  function selColor(valor, onChange, conOff) {
    const caja = el('span', 'sel-color');
    const sw = el('i', 'led-sw ' + valor, caja);
    const ops = (conOff ? ['off'] : []).concat(info.colores).map(c => [c, NOMBRE_COLOR[c]]);
    caja.appendChild(select(ops, valor, v => { sw.className = 'led-sw ' + v; onChange(v); }));
    return caja;
  }

  let info = null, cfg = null, caja = null, io = null, pestana = 'paginas';

  async function abrir(contenedor, ayudantes) {
    caja = contenedor; io = ayudantes;
    caja.innerHTML = '';
    el('p', 'muted', caja, 'Cargando…');
    try {
      info = await io.leer();
      cfg = JSON.parse(JSON.stringify(info.config));
      pintar();
    } catch (e) {
      caja.innerHTML = '';
      el('p', 'msg err', caja, 'No se pudo leer la configuración: ' + e.message);
    }
  }

  function msg(txt, err) {
    const m = caja.querySelector('.luces-msg');
    m.textContent = txt; m.hidden = !txt; m.classList.toggle('err', !!err);
  }

  async function probar(color, efecto) {
    try { await io.enviar('/api/luces/probar', { color, efecto }); msg('Probando ' + NOMBRE_COLOR[color] + ' · ' + NOMBRE_EFECTO[efecto] + ' en las luces.'); }
    catch (e) { msg('No se pudo probar: ' + e.message, true); }
  }

  function pintar() {
    caja.innerHTML = '';
    const cab = el('div', 'luces-head', caja);
    el('h3', '', cab, 'Luces y alertas');
    const acc = el('div', 'bar', cab);
    const plant = select([['', 'Plantillas…']].concat(Object.entries(info.plantillas).map(([k, p]) => [k, p.nombre])), '', k => {
      if (!k) return;
      if (!confirm('¿Cargar la plantilla «' + info.plantillas[k].nombre + '»? Se sustituye lo que hay en este cuadro (no se guarda hasta pulsar Guardar).')) { pintar(); return; }
      cfg = JSON.parse(JSON.stringify(info.plantillas[k].config));
      pintar(); msg('Plantilla cargada: pulsa Guardar para aplicarla.');
    });
    acc.appendChild(plant);
    const guardar = el('button', 'small', acc, 'Guardar');
    guardar.addEventListener('click', async () => {
      guardar.disabled = true;
      try { await io.enviar('/api/luces', { config: cfg }); msg('Guardado: ya se aplica en la moto.'); }
      catch (e) { msg('No se pudo guardar: ' + e.message, true); }
      guardar.disabled = false;
    });
    el('button', 'ghost small', acc, 'Cerrar').addEventListener('click', () => (io.cerrar ? io.cerrar() : (caja.hidden = true)));
    el('p', 'muted', caja, 'Las luces muestran el dato de la página que se ve en la pantalla. Las alertas mandan sobre todo: '
      + 'la pantalla salta a su página y todas las luces avisan. Una alerta grave se reconoce con una pulsación corta.'
      + (info.tira ? '' : ' La tira de luces no está en marcha: actívala para verlas en la moto.'));
    const m = el('p', 'msg luces-msg', caja); m.hidden = true;

    const tabs = el('div', 'tabs', caja);
    for (const [id, txt] of [['paginas', 'Luces por página'], ['alertas', 'Alertas'], ['resumen', 'Página RESUMEN']]) {
      const b = el('button', '', tabs, txt);
      b.type = 'button'; b.setAttribute('aria-selected', pestana === id);
      b.addEventListener('click', () => { pestana = id; pintar(); });
    }
    if (pestana === 'paginas') pintarPaginas(el('div', 'luces-lista', caja));
    else if (pestana === 'alertas') pintarAlertas(el('div', 'luces-lista', caja));
    else pintarResumen(el('div', 'luces-lista', caja));
  }

  const dato = id => info.catalogo.find(d => d.id === id) || { nombre: id, unidad: '' };
  const opsDatos = () => info.catalogo.map(d => [d.id, d.nombre + (d.unidad ? ' (' + d.unidad + ')' : '')]);

  /** Una fila de condicion: [mas de|menos de] [valor] unidad · color · efecto · Probar. */
  function filaNivel(parent, n, unidad, titulo, onQuitar, d) {
    const f = el('div', 'nivel', parent);
    if (titulo) el('b', 'nivel-tit', f, titulo);
    if (d && d.si_no) {
      // alertas de si/no (tope, vuelta, sensor con fallo): sin umbral que elegir
      n.op = '>'; n.valor = 0.5;
      const l = el('span', 'field', f, 'Cuándo');
      el('b', 'cuando', l, d.evento ? 'cuando ocurre' : 'si hay alguno');
    } else {
      campo(f, 'Si', select(Object.entries(OPS), n.op, v => { n.op = v; }));
      const u = campo(f, 'Valor' + (unidad ? ' (' + unidad + ')' : ''), numero(n.valor, v => { n.valor = v; }));
      u.classList.add('num');
    }
    campo(f, 'Color', selColor(n.color, v => { n.color = v; }));
    campo(f, 'Efecto', select(Object.entries(NOMBRE_EFECTO).filter(([k]) => info.efectos.includes(k)), n.efecto, v => { n.efecto = v; }));
    const b = el('div', 'nivel-acc', f);
    el('button', 'ghost small', b, 'Probar').addEventListener('click', () => probar(n.color, n.efecto));
    if (onQuitar) el('button', 'ghost small', b, '✕').addEventListener('click', onQuitar);
    return f;
  }

  function pintarPaginas(box) {
    for (const p of info.paginas) {
      const c = cfg.paginas[p.id];
      const sec = el('section', 'luces-item', box);
      const h = el('div', 'luces-item-head', sec);
      const lab = el('label', '', h);
      const cb = el('input', '', lab); cb.type = 'checkbox'; cb.checked = !!c;
      lab.append(' ' + p.titulo);
      cb.addEventListener('change', () => {
        if (cb.checked) cfg.paginas[p.id] = { dato: (info.catalogo.find(d => d.pagina === p.id) || info.catalogo[0]).id, modo: 'barra', reposo: 'off', niveles: [] };
        else delete cfg.paginas[p.id];
        pintar();
      });
      if (!c) { el('span', 'muted', h, 'luces apagadas en esta página'); continue; }
      const fila = el('div', 'bar', sec);
      campo(fila, 'Dato', select(opsDatos(), c.dato, v => { c.dato = v; pintar(); }), 'grow');
      campo(fila, 'Modo', select([['barra', 'barra (una luz por nivel)'], ['estado', 'estado (todas igual)']], c.modo, v => { c.modo = v; pintar(); }));
      campo(fila, 'Sin nivel', selColor(c.reposo || 'off', v => { c.reposo = v; }, true));
      const u = dato(c.dato).unidad;
      c.niveles.forEach((n, i) => {
        const tit = c.modo === 'barra' ? 'Luz ' + (i + 1) : i === 0 ? 'Primero' : 'Si no';
        filaNivel(sec, n, u, tit, () => { c.niveles.splice(i, 1); pintar(); });
      });
      const max = c.modo === 'barra' ? (info.leds || 3) : 8;
      if (c.niveles.length < max) {
        const add = el('button', 'ghost small', sec, c.modo === 'barra' ? '+ luz' : '+ nivel');
        add.addEventListener('click', () => {
          const ult = c.niveles[c.niveles.length - 1];
          c.niveles.push({ op: ult ? ult.op : '>', valor: ult ? ult.valor : 0, color: 'verde', efecto: 'fijo' });
          pintar();
        });
      }
      if (c.modo === 'estado') el('p', 'hint', sec, 'Manda el primer nivel que se cumple, de arriba abajo.');
    }
  }

  function pintarAlertas(box) {
    el('p', 'hint', box, 'Orden = prioridad: si saltan varias, manda la grave y, entre iguales, la de más arriba.');
    cfg.alertas.forEach((a, i) => {
      const sec = el('section', 'luces-item', box);
      const h = el('div', 'luces-item-head', sec);
      const nom = el('input', 'nombre', h); nom.value = a.nombre || ''; nom.placeholder = 'Nombre';
      nom.addEventListener('input', () => { a.nombre = nom.value; });
      const mv = el('span', 'bar', h);
      const mover = d => () => { const j = i + d; if (j < 0 || j >= cfg.alertas.length) return; cfg.alertas.splice(j, 0, cfg.alertas.splice(i, 1)[0]); pintar(); };
      el('button', 'ghost small', mv, '↑').addEventListener('click', mover(-1));
      el('button', 'ghost small', mv, '↓').addEventListener('click', mover(1));
      el('button', 'ghost small', mv, '✕').addEventListener('click', () => { cfg.alertas.splice(i, 1); pintar(); });

      const fila = el('div', 'bar', sec);
      campo(fila, 'Dato', select(opsDatos(), a.dato, v => { a.dato = v; a.pagina = dato(v).pagina; pintar(); }), 'grow');
      campo(fila, 'Tipo', select([['momentanea', 'momentánea'], ['grave', 'grave']], a.tipo, v => { a.tipo = v; pintar(); }));
      campo(fila, 'Muestra la página', select(info.paginas.map(p => [p.id, p.titulo]), a.pagina || dato(a.dato).pagina, v => { a.pagina = v; }));
      filaNivel(sec, a, dato(a.dato).unidad, null, null, dato(a.dato));
      const t = el('div', 'bar', sec);
      if (a.tipo === 'momentanea') {
        campo(t, 'Durante (s)', numero(a.seg != null ? a.seg : 3, v => { a.seg = v; }, 0.5)).classList.add('num');
        campo(t, 'No repetir en (s)', numero(a.espera_s != null ? a.espera_s : 30, v => { a.espera_s = v; }, 1)).classList.add('num');
      } else {
        campo(t, 'Recordar a los (s)', numero(a.recordar_s != null ? a.recordar_s : 120, v => { a.recordar_s = v; }, 1)).classList.add('num');
      }
      if (!dato(a.dato).si_no)
        campo(t, 'Margen al soltar' + (dato(a.dato).unidad ? ' (' + dato(a.dato).unidad + ')' : ''), numero(a.hist || 0, v => { a.hist = v; })).classList.add('num');
    });
    el('button', 'ghost small', box, '+ alerta').addEventListener('click', () => {
      const d = info.catalogo[0];
      cfg.alertas.push({ nombre: '', dato: d.id, op: '>', valor: 0, tipo: 'momentanea', color: 'rojo', efecto: 'destello', pagina: d.pagina, seg: 3, espera_s: 30, hist: 0 });
      pintar();
    });
  }

  /** Los 6 datos de la pagina RESUMEN, colocados como en la pantalla (3 x 2). */
  function pintarResumen(box) {
    el('p', 'hint', box, 'Elige qué dato va en cada casilla de la página RESUMEN de la pantalla. '
      + 'Si un dato no tiene sensor en marcha, sale «--».');
    if (!Array.isArray(cfg.resumen)) cfg.resumen = ['', '', '', '', '', ''];
    while (cfg.resumen.length < 6) cfg.resumen.push('');
    const rejilla = el('div', 'resumen-rejilla', box);
    const ops = [['', '(vacía)']].concat(info.resumen_opciones.map(o => [o.id, o.nombre + ' · ' + o.rotulo]));
    cfg.resumen.forEach((k, i) => {
      const celda = el('label', 'field resumen-celda', rejilla, (i < 3 ? 'Arriba ' : 'Abajo ') + (i % 3 + 1));
      celda.appendChild(select(ops, k, v => { cfg.resumen[i] = v; }));
    });
  }

  global.LucesCfg = { abrir };
})(window);
