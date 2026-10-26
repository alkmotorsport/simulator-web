/*
 * Pestana «Moto»: la ficha de la moto del sistema (en vivo, editable y se
 * guarda en la raspi: POST /api/moto) o la de una sesion grabada (solo
 * lectura: va en su sesion.json). Campos y limites: modulos/moto.py.
 * El analisis (analisis.js) la usa en vez de la moto de ejemplo de la web.
 *
 *   MotoCfg.abrir(caja, ficha, { guardar })   guardar(ficha) -> promesa; sin el, solo lectura
 */
(function (global) {
  'use strict';

  // [titulo, [[campo, etiqueta, tipo, unidad|opciones, ayuda]]]
  const GRUPOS = [
    ['Moto', [
      ['nombre', 'Nombre', 'txt', null, 'Marca, modelo y año'],
    ]],
    ['Motor', [
      ['motor_tiempos', 'Ciclo', 'opc', [['2T', '2 tiempos'], ['4T', '4 tiempos']]],
      ['refrigeracion', 'Refrigeración', 'opc', [['aire', 'aire'], ['agua', 'líquida']]],
      ['cilindrada_cc', 'Cilindrada', 'num', 'cc'],
      ['potencia_cv', 'Potencia', 'num', 'CV'],
      ['potencia_rpm', 'a', 'num', 'rpm'],
      ['velocidades', 'Velocidades', 'num', ''],
      ['vmax_kmh', 'Velocidad máxima', 'num', 'km/h'],
    ]],
    ['Pesos', [
      ['peso_seco_kg', 'Peso en seco', 'num', 'kg'],
      ['piloto_kg', 'Piloto equipado', 'num', 'kg', 'Si no lo pones, se cuentan 75 kg'],
      ['deposito_l', 'Depósito', 'num', 'l', 'Se cuenta medio depósito de gasolina'],
    ]],
    ['Chasis y suspensión', [
      ['batalla_m', 'Batalla (entre ejes)', 'num', 'm', 'Se mide con una cinta de eje a eje'],
      ['altura_cm_m', 'Altura del centro de masas', 'num', 'm', 'Difícil de medir: si no lo sabes, déjalo vacío'],
      ['susp_tras_mm', 'Recorrido útil suspensión trasera', 'num', 'mm', 'Para el % de compresión y el tope (pantalla, luces y alertas)'],
    ]],
    ['Ruedas y neumáticos', [
      ['rueda_del_pulg', 'Llanta delantera', 'num', '"'],
      ['rueda_tras_pulg', 'Llanta trasera', 'num', '"'],
      ['perimetro_tras_m', 'Perímetro rueda trasera', 'num', 'm', 'Marca el suelo, empuja la moto una vuelta de rueda y mide. Corrige la velocidad del sensor'],
      ['neumaticos', 'Neumáticos', 'opc', [['calle', 'calle (μ ≈ 1,0)'], ['deportivo', 'deportivos (μ ≈ 1,2)'], ['competicion', 'competición (μ ≈ 1,5)']]],
    ]],
    ['Frenos', [
      ['freno_del_tipo', 'Delantero', 'opc', [['tambor', 'tambor'], ['disco', 'disco']]],
      ['freno_del_mm', 'Diámetro delantero', 'num', 'mm'],
      ['freno_del_discos', 'Discos delanteros', 'num', '', 'Solo con disco'],
      ['freno_del_disco_kg', 'Masa de cada disco', 'num', 'kg', 'Solo con disco'],
      ['freno_del_material', 'Material del disco', 'opc', [['acero', 'acero'], ['carbono', 'carbono']]],
      ['freno_tras_tipo', 'Trasero', 'opc', [['tambor', 'tambor'], ['disco', 'disco']]],
      ['freno_tras_mm', 'Diámetro trasero', 'num', 'mm'],
    ]],
    ['Aerodinámica', [
      ['carroceria', 'Carrocería', 'opc', [['naked', 'naked (sin carenado)'], ['semicarenada', 'semicarenada'], ['carenada', 'carenada']]],
    ]],
    ['Notas', [
      ['notas', 'Notas', 'area', null, 'Carburador, reglajes, cambios…'],
    ]],
  ];

  function el(tag, cls, parent, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  /** Lo que el analisis sacara de la ficha (se recalcula al escribir). */
  function derivados(f) {
    const out = [];
    if (f.peso_seco_kg) {
      const piloto = f.piloto_kg || 75, gasolina = f.deposito_l ? f.deposito_l / 2 * 0.74 : 0;
      out.push('Masa en marcha ≈ ' + Math.round(f.peso_seco_kg + piloto + gasolina) + ' kg (' + f.peso_seco_kg + ' en seco + ' + piloto + ' piloto' + (gasolina ? ' + ' + Math.round(gasolina) + ' de gasolina' : '') + ')');
    }
    if (f.batalla_m) {
      const h = f.altura_cm_m || 0.6;
      out.push('Stoppie / wheelie hacia ' + (f.batalla_m / (2 * h)).toFixed(2).replace('.', ',') + ' g (g·L/2h' + (f.altura_cm_m ? '' : ', con h = 0,60 m de la web') + ')');
    }
    const mu = { calle: 1, deportivo: 1.2, competicion: 1.5 }[f.neumaticos];
    if (mu) out.push('Inclinación máxima teórica ≈ ' + Math.round(Math.atan(mu) * 180 / Math.PI) + '° (atan μ)');
    if (f.freno_del_tipo === 'tambor') out.push('Freno de tambor: el análisis no estima temperatura de disco');
    return out;
  }

  function abrir(caja, ficha, opciones = {}) {
    const f = Object.assign({}, ficha || {});
    const editable = !!opciones.guardar;
    caja.innerHTML = '';
    el('p', 'muted', caja, editable
      ? 'La ficha de la moto de este sistema. Se guarda en él y se copia en cada sesión al empezar a grabar: «Analizar trazas» la usa en vez de la moto de ejemplo de la formación. Todo es opcional.'
      : (Object.keys(f).length ? 'La moto con la que se grabó esta sesión (se edita en vivo, pestaña Moto).'
        : 'Esta sesión se grabó sin ficha de la moto: el análisis usa la moto de ejemplo de la formación. La ficha se rellena en vivo, pestaña Moto.'));
    if (!editable && !Object.keys(f).length) return;
    const form = el('div', 'moto-form', caja);
    const der = el('ul', 'moto-der', null);
    const pintarDer = () => { der.innerHTML = ''; derivados(f).forEach(t => el('li', '', der, t)); der.hidden = !der.children.length; };
    for (const [titulo, campos] of GRUPOS) {
      const visibles = editable ? campos : campos.filter(c => f[c[0]] != null && f[c[0]] !== '');
      if (!visibles.length) continue;
      const fs = el('fieldset', 'moto-grupo', form);
      el('legend', '', fs, titulo);
      for (const [k, etiqueta, tipo, extra, ayuda] of visibles) {
        const lab = el('label', 'field' + (tipo === 'txt' || tipo === 'area' ? ' grow' : ''), fs, etiqueta + (tipo === 'num' && extra ? ' (' + extra + ')' : ''));
        let c;
        if (!editable) {
          const v = f[k];
          c = el('b', 'moto-valor', lab, tipo === 'opc' ? ((extra.find(o => o[0] === v) || [v, v])[1]) : String(v).replace('.', ','));
          continue;
        }
        if (tipo === 'opc') {
          c = el('select', '', lab);
          c.add(new Option('—', ''));
          for (const [v, t] of extra) c.add(new Option(t, v, false, f[k] === v));
        } else if (tipo === 'area') {
          c = el('textarea', '', lab); c.rows = 2; c.value = f[k] || '';
        } else {
          c = el('input', tipo === 'num' ? 'num' : '', lab);
          c.type = tipo === 'num' ? 'number' : 'text';
          if (tipo === 'num') { c.step = 'any'; c.inputMode = 'decimal'; }
          c.value = f[k] != null ? f[k] : '';
        }
        if (ayuda) c.title = ayuda;
        if (ayuda) el('small', 'ayuda', lab, ayuda);
        c.addEventListener(tipo === 'opc' ? 'change' : 'input', () => {
          const v = c.value.trim();
          if (v === '') delete f[k];
          else f[k] = tipo === 'num' ? +v : v;
          pintarDer();
        });
      }
    }
    caja.appendChild(der);
    pintarDer();
    if (!editable) return;
    const bar = el('div', 'bar', caja);
    const b = el('button', 'small', bar, 'Guardar');
    const msg = el('span', 'msg', bar);
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        const r = await opciones.guardar(f);
        const NOMBRES = { perimetro_m: 'perímetro de rueda en el sensor de velocidad', recorrido_mm: 'recorrido de suspensión en la pantalla y las alertas' };
        const ap = Object.values((r && r.aplicado) || {}).flatMap(a => Object.keys(a).map(k => NOMBRES[k] || k));
        msg.textContent = 'Guardada' + (ap.length ? '; ya se usa el ' + ap.join(' y el ') : '') + '. Las próximas sesiones la llevarán.';
        msg.classList.remove('err');
      } catch (e) {
        msg.textContent = 'No se pudo guardar: ' + e.message; msg.classList.add('err');
      }
      b.disabled = false;
    });
  }

  global.MotoCfg = { abrir };
})(window);
