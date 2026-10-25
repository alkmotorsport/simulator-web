/*
 * Usuarios y sesiones del repo de datos (modo consulta, sin la Pi delante).
 *   - Entrar: usuarios/<usuario>.json tiene la clave de su raspi cifrada con
 *     su contrasena; si descifra, se listan y abren sus sesiones de la nube.
 *   - Activar (link del admin, #alta=<id>.<secreto>): en la app se abre la web
 *     de la raspi del usuario; alli elige la contrasena y la raspi hace el alta.
 */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  const T = window.Telemetria;
  const CFG = window.TELEMETRIA || {};
  const APP_URL = 'https://motorsport.amorgante.es/telemetry-poc/web/';
  const repo = CFG.token ? Repo.crear(CFG) : null;
  let cuenta = null;     // {usuario, raspi, nombre, clave: CryptoKey}

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
  const almacen = recordar => recordar ? localStorage : sessionStorage;
  function guardado() {
    for (const s of [localStorage, sessionStorage]) {
      try { const v = s.getItem('tele-cuenta'); if (v) return JSON.parse(v); } catch (e) { /* sin almacenamiento */ }
    }
    return null;
  }
  function olvidar() {
    for (const s of [localStorage, sessionStorage]) { try { s.removeItem('tele-cuenta'); } catch (e) { /* nada */ } }
  }

  /** Por que no se puede entrar aqui, o '' si se puede. */
  function sinLogin() {
    if (!Cripto.disponible()) return T.servedByPi
      ? 'En la web de la raspi (http) el navegador no permite descifrar: aquí ves sus sesiones locales y el modo en vivo. Para tus sesiones de la nube usa la app.'
      : 'Este navegador no permite descifrar (hace falta https y un navegador actual).';
    if (!repo) return 'Esta copia de la web no tiene acceso al repo de datos. Usa la app.';
    return '';
  }

  // ------------------------------------------------------------- cabecera ---

  function pintarCuenta() {
    $('#cuenta-sum').textContent = cuenta ? cuenta.usuario + ' · ' + cuenta.nombre : '';
    $('#cuenta-btn').textContent = cuenta ? 'Salir' : 'Entrar';
    $('#nube').hidden = !cuenta;
  }

  $('#cuenta-btn').addEventListener('click', () => {
    if (cuenta) {
      cuenta = null; olvidar(); pintarCuenta();
      $('#nube-list').innerHTML = '';
      return;
    }
    const box = $('#login');
    box.hidden = !box.hidden;
    const motivo = sinLogin();
    $('#login-form').hidden = !!motivo;
    if (motivo) {
      const m = msg('#login-msg', motivo, false);
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
      const u = /^[a-z0-9][a-z0-9._-]{1,31}$/.test(usuario) ? await repo.json('usuarios/' + usuario + '.json') : null;
      let raw = null;
      if (u) raw = await Cripto.abrirClave(u, pass).catch(() => null);
      if (!raw) throw new Error('Usuario o contraseña incorrectos.');
      const r = await repo.json('raspis/' + u.raspi + '/raspi.json').catch(() => null);
      const datos = { usuario, raspi: u.raspi, nombre: (r && r.nombre) || u.raspi, clave: Cripto.b64(raw) };
      usarDireccion(r);
      try { almacen($('#login-keep').checked).setItem('tele-cuenta', JSON.stringify(datos)); } catch (err) { /* solo esta pestana */ }
      await abrir(datos);
      $('#login').hidden = true;
      $('#login-pass').value = '';
      msg('#login-msg', '');
      T.showTab('file');
    } catch (err) {
      msg('#login-msg', err.message, true);
    } finally { btn.disabled = false; }
  });

  /** La raspi anuncia su direccion actual en el repo: manda sobre la que
   *  recuerde el navegador (la IP puede cambiar). */
  function usarDireccion(r) {
    const srv = $('#server');
    if (!r || !r.direccion || srv.value.trim().replace(/\/+$/, '') === r.direccion) return;
    srv.value = r.direccion;
    srv.dispatchEvent(new Event('change'));
  }

  async function abrir(datos) {
    cuenta = Object.assign({}, datos, { clave: await Cripto.importar(Cripto.ub64(datos.clave)) });
    pintarCuenta();
    listar();
  }

  // ------------------------------------------------- sesiones de la nube ---

  async function listar() {
    if (!cuenta) return;
    const ul = $('#nube-list');
    msg('#nube-msg', 'Cargando sesiones…');
    try {
      // si el admin ha borrado el usuario, fuera
      if (!(await repo.info('usuarios/' + cuenta.usuario + '.json'))) {
        cuenta = null; olvidar(); pintarCuenta();
        return msg('#file-msg', 'Tu usuario ya no existe: habla con el administrador.', true);
      }
      repo.json('raspis/' + cuenta.raspi + '/raspi.json').then(usarDireccion).catch(() => {});
      const ri = 'raspis/' + cuenta.raspi + '/indice.enc';
      const buf = await repo.raw(ri);
      const lista = buf ? (await Cripto.descifrarJSON(cuenta.clave, buf, ri)).sesiones : [];
      ul.innerHTML = '';
      for (const s of lista) {
        const li = el('li', '', ul);
        const b = el('button', 'link', li, s.nombre);
        b.addEventListener('click', () => abrirSesion(s));
        el('span', '', li, s.sensores.length + (s.sensores.length === 1 ? ' sensor · ' : ' sensores · ') +
          (s.inicio ? new Date(s.inicio).toLocaleString() : '') + ' · ' + (s.bytes / 1024).toFixed(0) + ' kB' +
          (s.simulada ? ' · simulada' : '') + (s.fin ? '' : ' · cortada'));
      }
      msg('#nube-msg', lista.length ? '' : 'Tu raspi aún no ha subido ninguna sesión.');
    } catch (e) {
      msg('#nube-msg', 'No se pudieron cargar: ' + e.message, true);
    }
  }
  $('#nube-refresh').addEventListener('click', listar);

  async function abrirSesion(s) {
    T.showTab('file');
    T.fileMsg('Descargando ' + s.nombre + '…');
    try {
      const rel = 'raspis/' + cuenta.raspi + '/sesiones/' + s.id + '.enc';
      const buf = await repo.raw(rel);
      if (!buf) throw new Error('no está en el repo');
      const p = await Cripto.descifrarJSON(cuenta.clave, buf, rel);
      T.openFiles(s.nombre, Object.entries(p.ficheros).map(([name, text]) => ({ name, text })));
    } catch (e) {
      T.fileMsg('No se pudo abrir ' + s.nombre + ': ' + e.message, true);
    }
  }

  // ------------------------------------------------------------ activar ---

  const USADA = 'Esta invitación ya se ha usado (o no existe). Si ya elegiste tu contraseña, tu cuenta está lista: pulsa «Entrar» arriba con tu usuario.';

  /** Invitacion usada o inexistente: nada que rellenar, solo como entrar. */
  function altaUsada() {
    $('#alta-txt').textContent = '';
    $('#alta-ir').hidden = true;
    $('#alta-form').hidden = true;
    history.replaceState(null, '', location.pathname);
    const m = msg('#alta-msg', USADA);
    if (T.servedByPi) { m.textContent = USADA.replace('pulsa «Entrar» arriba', 'entra en la app') + ' '; const a = el('a', '', m, 'Abrir la app'); a.href = APP_URL; }
  }

  async function alta(inv, secreto) {
    const box = $('#alta');
    box.hidden = false;
    $('#alta-form').hidden = true;
    $('#alta-ir').hidden = true;
    if (T.servedByPi) return altaEnPi(inv, secreto);

    // en la app: hay que ir a la raspi (mismo wifi), que es quien hace el alta
    $('#alta-txt').textContent = 'Conéctate a la wifi de tu moto y abre tu raspi para elegir la contraseña. Si el navegador avisa del certificado, acéptalo: es el de tu raspi.';
    $('#alta-ir').hidden = false;
    const dir = $('#alta-dir');
    try { dir.value = localStorage.getItem('tele-server') || ''; } catch (e) { dir.value = ''; }   // si no hay repo
    if (repo) try {
      const i = await repo.json('invitaciones/' + inv + '.json');
      if (!i) return altaUsada();
      const r = await repo.json('raspis/' + i.raspi + '/raspi.json');
      $('#alta-txt').textContent = 'Usuario ' + i.usuario + ' en ' + ((r && r.nombre) || i.raspi) +
        '. Conéctate a la wifi de la moto y abre la raspi para elegir tu contraseña. Si el navegador avisa del certificado, acéptalo: es el de tu raspi.';
      if (r && r.direccion) dir.value = r.direccion;   // la actual, no la que recuerde el navegador
    } catch (e) { /* sin repo: el usuario pone la direccion */ }
    $('#alta-abrir').onclick = () => {
      let base = dir.value.trim().replace(/\/+$/, '');
      if (!base) return msg('#alta-msg', 'Pon la dirección de la raspi (p. ej. https://192.168.1.50:8081)', true);
      if (!/^https?:\/\//.test(base)) base = 'https://' + base;
      location.href = base + '/#alta=' + inv + '.' + secreto;
    };
  }

  async function altaEnPi(inv, secreto) {
    const api = (ruta, cuerpo) => fetch(location.origin + ruta, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo),
    }).then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || 'HTTP ' + r.status); return j; });
    $('#alta-txt').textContent = 'Comprobando la invitación en la raspi…';
    let info;
    try { info = await api('/api/alta/consultar', { inv }); } catch (e) {
      if (/ya se ha usado/.test(e.message)) return altaUsada();
      $('#alta-txt').textContent = '';
      return msg('#alta-msg', e.message, true);
    }
    $('#alta-txt').textContent = (info.cambio ? 'Nueva contraseña para ' : 'Alta de ') + info.usuario + ' en ' + info.nombre_raspi + '.';
    $('#alta-user').value = info.usuario;
    $('#alta-pass').minLength = $('#alta-pass2').minLength = info.pass_min;
    $('#alta-pass').placeholder = 'mínimo ' + info.pass_min + ' caracteres';
    $('#alta-form').hidden = false;
    $('#alta-form').onsubmit = async e => {
      e.preventDefault();
      if ($('#alta-pass').value !== $('#alta-pass2').value) return msg('#alta-msg', 'Las contraseñas no coinciden.', true);
      $('#alta-go').disabled = true;
      msg('#alta-msg', 'Guardando en el repo de datos…');
      try {
        const j = await api('/api/alta', { inv, secreto, password: $('#alta-pass').value });
        $('#alta-form').hidden = true;
        history.replaceState(null, '', location.pathname);
        const m = msg('#alta-msg', j.mensaje + ': ');
        const a = el('a', '', m, 'abrir la app'); a.href = APP_URL;
      } catch (err) {
        msg('#alta-msg', err.message, true);
      } finally { $('#alta-go').disabled = false; }
    };
  }

  // ---------------------------------------------------------------- init ---

  const m = /^#alta=([0-9a-f]+)\.([\w-]+)$/.exec(location.hash);
  if (m) alta(m[1], m[2]);
  const g = guardado();
  if (g && !sinLogin()) abrir(g).catch(() => olvidar());
  else pintarCuenta();
})();
