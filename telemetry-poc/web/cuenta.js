/*
 * Cuenta: entrar con usuario y contrasena, tus raspis y tus sesiones.
 *   - Entrar: usuarios/<usuario>.json guarda la clave de cada raspi suya
 *     cifrada con su contrasena. Las que descifra son "tus raspis".
 *   - Cada raspi: sus sesiones de la nube (repo de datos) y, si esta
 *     encendida, el modo en vivo. Su web pide entrar: se responde a su reto
 *     con su clave (acceso.py), sin mandar la contrasena.
 *   - Alta (link del admin, #alta=<id>.<secreto>): la app busca la raspi de
 *     la invitacion (por internet o en la wifi) y alli se elige la contrasena.
 * En la app publicada los usuarios salen del repo; en la web de una raspi,
 * de la propia raspi (asi se puede entrar sin internet).
 */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  const T = window.Telemetria;
  const CFG = window.TELEMETRIA || {};
  const APP_URL = 'https://motorsport.amorgante.es/telemetry-poc/web/';
  const ID_OK = /^[a-z0-9][a-z0-9._-]{1,31}$/;
  const repo = CFG.token ? Repo.crear(CFG) : null;
  let cuenta = null;     // {usuario, raspis: [{id, nombre, raw, clave, direccion, local}], sel}

  function el(tag, cls, parent, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function msg(sel, txt, err) {
    const m = $(sel);
    m.textContent = txt; m.hidden = !txt; m.classList.toggle('err', !!err);
    return m;
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  const almacen = recordar => recordar ? localStorage : sessionStorage;
  function guardado() {
    for (const s of [localStorage, sessionStorage]) {
      try { const v = JSON.parse(s.getItem('tele-cuenta') || 'null'); if (v && v.raspis) return v; } catch (e) { /* sin almacenamiento */ }
    }
    return null;
  }
  function olvidar() {
    for (const s of [localStorage, sessionStorage]) { try { s.removeItem('tele-cuenta'); } catch (e) { /* nada */ } }
  }

  /** JSON de una web (la raspi): error con su mensaje, y timeout. */
  async function pedir(url, { body, headers, timeout = 8000 } = {}) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeout);
    try {
      const r = await fetch(url, {
        method: body ? 'POST' : 'GET', signal: ctl.signal, cache: 'no-store',
        headers: Object.assign(body ? { 'Content-Type': 'application/json' } : {}, headers || {}),
        body: body ? JSON.stringify(body) : undefined,
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { const e = new Error(j.error || 'HTTP ' + r.status); e.status = r.status; throw e; }
      return j;
    } finally { clearTimeout(t); }
  }

  // De donde salen usuarios y raspis: el repo (app publicada) o la raspi
  // que sirve esta web (sin internet tambien vale).
  const fuente = repo ? {
    usuario: u => repo.json('usuarios/' + u + '.json'),
    raspi: id => repo.json('raspis/' + id + '/raspi.json').catch(() => null),
  } : T.servedByPi ? {
    usuario: u => pedir(location.origin + '/api/usuario/' + u).catch(e => { if (e.status === 404) return null; throw e; }),
    raspi: async () => { const i = await pedir(location.origin + '/api/raspi'); return { id: i.raspi, nombre: i.nombre, direccion: location.origin }; },
  } : null;

  function sinLogin() {
    if (!Cripto.disponible()) return 'Este navegador no permite descifrar: abre la app por https con un navegador actual.';
    if (!fuente) return 'Esta copia de la web no tiene acceso al repo de datos. Usa la app.';
    return '';
  }

  // ---------------------------------------------------- acceso a una raspi ---

  const sesiones = {};    // base -> sesion (null: raspi abierta, sin usuarios)
  const pendientes = {};

  /** Sesion en la web de la raspi de 'base' (reto + firma con su clave). */
  function sesion(base) {
    if (base in sesiones) return Promise.resolve(sesiones[base]);
    if (!pendientes[base]) {
      pendientes[base] = (async () => {
        const info = await pedir(base + '/api/raspi');
        if (!info.acceso) return (sesiones[base] = null);
        const r = cuenta && cuenta.raspis.find(x => x.id === info.raspi);
        if (!r) throw new Error('Entra con un usuario de ' + (info.nombre || 'esta raspi'));
        const { reto } = await pedir(base + '/api/reto');
        const firma = await Cripto.firmar(r.raw, reto, cuenta.usuario);
        const j = await pedir(base + '/api/entrar', { body: { usuario: cuenta.usuario, reto, firma } });
        return (sesiones[base] = j.sesion);
      })().finally(() => { delete pendientes[base]; });
    }
    return pendientes[base];
  }

  // app.js usa esto en cada peticion a la raspi
  window.TelemetriaAcceso = {
    async cabeceras(base) { const s = await sesion(base); return s ? { Authorization: 'Bearer ' + s } : {}; },
    sesion,
    olvidar(base) { delete sesiones[base]; },
  };

  /** Primera direccion de la raspi que responde: la publica (tunel) o la de la wifi. */
  async function probar(r) {
    for (const base of [...new Set([r.direccion, r.local].filter(Boolean))]) {
      try { await pedir(base + '/api/raspi', { timeout: 5000 }); return base; } catch (e) { /* la siguiente */ }
    }
    return null;
  }

  // -------------------------------------------------------------- cabecera ---

  function pintarCuenta() {
    $('#cuenta-sum').textContent = cuenta ? cuenta.usuario : '';
    $('#cuenta-btn').textContent = cuenta ? 'Salir' : 'Entrar';
    $('#raspis').hidden = !cuenta;
    $('#nube').hidden = !cuenta || !repo;
    // con cuenta, el modo se elige con los botones de tu raspi y la direccion la pone la app
    document.querySelector('.tabs').hidden = !!cuenta;
    $('#conn-box').hidden = !!cuenta;
    $('#otras').open = !cuenta;
  }

  $('#cuenta-btn').addEventListener('click', () => {
    if (cuenta) {
      cuenta = null; olvidar(); pintarCuenta();
      Object.keys(sesiones).forEach(b => delete sesiones[b]);
      T.desconectar();
      $('#nube-list').innerHTML = '';
      return;
    }
    const box = $('#login');
    box.hidden = !box.hidden;
    const motivo = sinLogin();
    $('#login-form').hidden = !!motivo;
    if (motivo) {
      const m = msg('#login-msg', motivo);
      if (T.servedByPi) { const a = el('a', '', null, 'Abrir la app'); a.href = APP_URL; m.append(' ', a); }
    } else { msg('#login-msg', ''); $('#login-user').focus(); }
  });

  $('#login-form').addEventListener('submit', async e => {
    e.preventDefault();
    const usuario = $('#login-user').value.trim().toLowerCase(), pass = $('#login-pass').value;
    const btn = $('#login-go');
    btn.disabled = true;
    msg('#login-msg', 'Comprobando…');
    try {
      const u = ID_OK.test(usuario) ? await fuente.usuario(usuario) : null;
      const raspis = [];
      // la contrasena abre las raspis en las que la eligio (puede tener varias)
      for (const [id, ent] of Object.entries(u ? Cripto.entradas(u) : {})) {
        const raw = await Cripto.abrirClave(usuario, id, ent, pass).catch(() => null);
        if (!raw) continue;
        const r = (await fuente.raspi(id)) || {};
        raspis.push({ id, nombre: r.nombre || id, clave: Cripto.b64(raw), direccion: r.direccion, local: r.local });
      }
      if (!raspis.length) throw new Error('Usuario o contraseña incorrectos.');
      const datos = { usuario, raspis };
      try { almacen($('#login-keep').checked).setItem('tele-cuenta', JSON.stringify(datos)); } catch (err) { /* solo esta pestana */ }
      await abrir(datos);
      $('#login').hidden = true;
      $('#login-pass').value = '';
      msg('#login-msg', '');
    } catch (err) {
      msg('#login-msg', err.message, true);
    } finally { btn.disabled = false; }
  });

  async function abrir(datos) {
    const raspis = await Promise.all(datos.raspis.map(async r => {
      const raw = Cripto.ub64(r.clave);
      return Object.assign({}, r, { raw, clave: await Cripto.importar(raw) });
    }));
    cuenta = { usuario: datos.usuario, raspis };
    cuenta.sel = raspis.find(r => r.id === store('tele-raspi')) || raspis[0];
    pintarCuenta();
    await refrescar();
    pintarRaspis();
    if (T.servedByPi) { T.listarPi(); T.conectar(location.origin); }   // la web de esta raspi
    else { T.showTab('file'); listar(); }                               // la app empieza en Sesiones
  }

  /** Direcciones al dia (cambian en cada arranque del tunel); si el admin ha
   *  borrado el usuario, fuera. */
  async function refrescar() {
    if (!repo || !cuenta) return;
    try {
      if (!(await repo.info('usuarios/' + cuenta.usuario + '.json'))) {
        cuenta = null; olvidar(); pintarCuenta();
        msg('#file-msg', 'Tu usuario ya no existe: habla con el administrador.', true);
        return;
      }
      await Promise.all(cuenta.raspis.map(async r => {
        const i = await fuente.raspi(r.id);
        if (i) Object.assign(r, { nombre: i.nombre || r.nombre, direccion: i.direccion, local: i.local });
      }));
    } catch (e) { /* sin red: lo guardado */ }
  }

  // ------------------------------------------------------------ tus raspis ---

  function pintarRaspis() {
    if (!cuenta) return;
    const ul = $('#raspis-list');
    ul.innerHTML = '';
    for (const r of cuenta.raspis) {
      const li = el('li', 'raspi' + (r === cuenta.sel ? ' sel' : ''), ul);
      const txt = el('div', 'raspi-txt', li);
      el('b', '', txt, r.nombre);
      const est = el('span', 'muted', txt, ' · comprobando…');
      const acc = el('div', 'bar modo', li);
      const vivo = el('button', 'small', acc, 'En vivo');
      const ses = el('button', 'small', acc, 'Sesiones');
      r.botones = { vivo, ses };
      vivo.disabled = true;
      ses.addEventListener('click', () => elegir(r, false));
      vivo.addEventListener('click', () => elegir(r, true));
      probar(r).then(base => {
        r.base = base;
        est.textContent = base ? (base === r.local && base !== r.direccion ? ' · en línea (wifi)' : ' · en línea') : ' · apagada o sin internet';
        est.className = base ? 'ok' : 'muted';
        vivo.disabled = !base;
        if (base && r === cuenta.sel && !T.servedByPi) T.usarRaspi(base);
      });
    }
    pintarModo();
  }

  /** El boton del modo visible, en naranja; el resto en blanco. */
  function pintarModo() {
    if (!cuenta) return;
    const tab = T.pestana();
    for (const r of cuenta.raspis) {
      if (!r.botones) continue;
      const sel = r === cuenta.sel;
      r.botones.vivo.className = 'small' + (sel && tab === 'live' ? '' : ' ghost');
      r.botones.ses.className = 'small' + (sel && tab === 'file' ? '' : ' ghost');
      r.botones.vivo.setAttribute('aria-pressed', sel && tab === 'live');
      r.botones.ses.setAttribute('aria-pressed', sel && tab === 'file');
    }
  }
  addEventListener('tele-pestana', pintarModo);
  $('#raspis-refresh').addEventListener('click', async () => { await refrescar(); pintarRaspis(); listar(); });

  function elegir(r, vivo) {
    const otra = r !== cuenta.sel;
    cuenta.sel = r;
    store('tele-raspi', r.id);
    if (otra) pintarRaspis();
    if (r.base) T.usarRaspi(r.base);
    if (vivo) {
      // ya conectado a esta raspi: solo cambia lo que se ve
      if (r.base && (otra || T.serverBase() !== r.base || !T.conectado())) T.conectar(r.base);
      else T.showTab('live');
    } else {
      T.showTab('file');
      if (otra || !$('#nube-list').children.length) listar();
      if (T.servedByPi) T.listarPi();
    }
  }

  // ------------------------------------------------- sesiones de la nube ---

  async function listar() {
    if (!cuenta || !repo) return;
    const r = cuenta.sel, ul = $('#nube-list');
    $('#nube-tit').textContent = 'Sesiones en la nube · ' + r.nombre;
    msg('#nube-msg', 'Cargando sesiones…');
    try {
      const ri = 'raspis/' + r.id + '/indice.enc';
      const buf = await repo.raw(ri);
      const lista = buf ? (await Cripto.descifrarJSON(r.clave, buf, ri)).sesiones : [];
      ul.innerHTML = '';
      for (const s of lista) {
        const li = el('li', '', ul);
        const b = el('button', 'link', li, s.nombre);
        b.addEventListener('click', () => abrirSesion(r, s));
        el('span', '', li, s.sensores.length + (s.sensores.length === 1 ? ' sensor · ' : ' sensores · ') +
          (s.inicio ? new Date(s.inicio).toLocaleString() : '') + ' · ' + (s.bytes / 1024).toFixed(0) + ' kB' +
          (s.simulada ? ' · simulada' : '') + (s.fin ? '' : ' · cortada'));
        const x = el('button', 'ghost small borrar', li, 'Borrar');
        x.title = 'Borrar de la nube (lo hace tu raspi: tiene que estar en línea)';
        x.addEventListener('click', () => borrarDeNube(r, s, li, x));
      }
      msg('#nube-msg', lista.length ? '' : 'Esta raspi aún no ha subido ninguna sesión.');
    } catch (e) {
      msg('#nube-msg', 'No se pudieron cargar: ' + e.message, true);
    }
  }
  $('#nube-refresh').addEventListener('click', listar);

  /** El repo solo lo puede escribir la raspi: se le pide a ella. */
  async function borrarDeNube(r, s, li, boton) {
    if (!r.base) return msg('#nube-msg', 'Para borrar de la nube, ' + r.nombre + ' tiene que estar encendida y con internet.', true);
    if (!confirm('¿Borrar ' + s.nombre + ' de la nube?\n\nNo se puede deshacer. Si sigue guardada en la raspi, esa copia no se borra.')) return;
    boton.disabled = true;
    msg('#nube-msg', 'Borrando ' + s.nombre + '…');
    try {
      const h = await window.TelemetriaAcceso.cabeceras(r.base);
      const j = await pedir(r.base + '/api/nube/borrar', { body: { id: s.id }, headers: h, timeout: 60000 });
      li.remove();
      msg('#nube-msg', j.mensaje + '.');
    } catch (e) {
      boton.disabled = false;
      msg('#nube-msg', 'No se pudo borrar: ' + e.message, true);
    }
  }

  async function abrirSesion(r, s) {
    T.showTab('file');
    T.fileMsg('Descargando ' + s.nombre + '…');
    try {
      const rel = 'raspis/' + r.id + '/sesiones/' + s.id + '.enc';
      const buf = await repo.raw(rel);
      if (!buf) throw new Error('no está en el repo');
      const p = await Cripto.descifrarJSON(r.clave, buf, rel);
      T.openFiles(s.nombre, Object.entries(p.ficheros).map(([name, text]) => ({ name, text })));
    } catch (e) {
      T.fileMsg('No se pudo abrir ' + s.nombre + ': ' + e.message, true);
    }
  }

  // ----------------------------------------------------------------- alta ---

  const USADA = 'Esta invitación ya se ha usado (o no existe). Si ya elegiste tu contraseña, tu cuenta está lista: pulsa «Entrar» arriba.';

  function altaUsada() {
    $('#alta-txt').textContent = '';
    $('#alta-ir').hidden = true;
    $('#alta-form').hidden = true;
    history.replaceState(null, '', location.pathname);
    msg('#alta-msg', USADA);
  }

  /** La invitacion la canjea su raspi: se busca por internet o en la wifi. */
  async function alta(inv, secreto) {
    $('#alta').hidden = false;
    $('#alta-form').hidden = true;
    $('#alta-ir').hidden = true;
    if (T.servedByPi) return altaEn(location.origin, inv, secreto);
    $('#alta-txt').textContent = 'Buscando tu raspi…';
    let r = null;
    if (repo) try {
      const i = await repo.json('invitaciones/' + inv + '.json');
      if (!i) return altaUsada();
      r = (await repo.json('raspis/' + i.raspi + '/raspi.json')) || { nombre: i.raspi };
      const base = await probar(r);
      if (base) return altaEn(base, inv, secreto);
    } catch (e) { /* abajo: a mano */ }
    // apagada o sin internet: en su wifi, con su direccion local
    $('#alta-txt').textContent = 'No encuentro ' + ((r && r.nombre) || 'tu raspi') + ' por internet. Enciéndela ' +
      '(con internet) y recarga esta página, o conéctate a su wifi y pulsa «Conectar».';
    $('#alta-dir').value = (r && r.local) || '';
    $('#alta-ir').hidden = false;
    $('#alta-abrir').onclick = () => {
      let base = $('#alta-dir').value.trim().replace(/\/+$/, '');
      if (!base) return msg('#alta-msg', 'Pon la dirección de la raspi (p. ej. https://192.168.1.50:8081)', true);
      if (!/^https?:\/\//.test(base)) base = 'https://' + base;
      altaEn(base, inv, secreto);
    };
  }

  async function altaEn(base, inv, secreto) {
    $('#alta-txt').textContent = 'Comprobando la invitación en la raspi…';
    msg('#alta-msg', '');
    let info;
    try { info = await pedir(base + '/api/alta/consultar', { body: { inv }, timeout: 30000 }); } catch (e) {
      if (/ya se ha usado/.test(e.message)) return altaUsada();
      $('#alta-txt').textContent = '';
      const m = msg('#alta-msg', e.status ? e.message : 'No conecto con ' + base + '.', true);
      if (!e.status && base.startsWith('https://') && !/trycloudflare\.com$/.test(new URL(base).hostname)) {
        const a = el('a', '', null, 'ábrela y acepta el aviso del certificado');
        a.href = base + '/'; a.target = '_blank'; a.rel = 'noopener';
        m.append(' Si es la primera vez en este dispositivo, ', a, ', y vuelve a pulsar «Conectar».');
      }
      return;
    }
    $('#alta-ir').hidden = true;
    $('#alta-txt').textContent = (info.cambio ? 'Nueva contraseña para ' : 'Alta de ') + info.usuario + ' en ' + info.nombre_raspi + '.';
    $('#alta-user').value = info.usuario;
    $('#alta-pass').minLength = $('#alta-pass2').minLength = info.pass_min;
    $('#alta-pass').placeholder = 'mínimo ' + info.pass_min + ' caracteres';
    $('#alta-form').hidden = false;
    $('#alta-form').onsubmit = async e => {
      e.preventDefault();
      if ($('#alta-pass').value !== $('#alta-pass2').value) return msg('#alta-msg', 'Las contraseñas no coinciden.', true);
      $('#alta-go').disabled = true;
      msg('#alta-msg', 'Guardando…');
      try {
        const j = await pedir(base + '/api/alta', { body: { inv, secreto, password: $('#alta-pass').value }, timeout: 60000 });
        $('#alta-form').hidden = true;
        history.replaceState(null, '', location.pathname);
        $('#alta-txt').textContent = '';
        msg('#alta-msg', j.mensaje + '. Pulsa «Entrar» arriba con tu usuario y esa contraseña.');
        $('#login-user').value = info.usuario;
      } catch (err) {
        msg('#alta-msg', err.message, true);
      } finally { $('#alta-go').disabled = false; }
    };
  }

  // ---------------------------------------------------------------- init ---

  const m = /^#alta=([0-9a-f]+)\.([\w-]+)$/.exec(location.hash);
  if (m) alta(m[1], m[2]);
  const g = guardado();
  if (g && !sinLogin()) abrir(g).catch(() => { olvidar(); pintarCuenta(); });
  else pintarCuenta();
})();
