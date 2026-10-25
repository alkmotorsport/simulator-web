/*
 * Portal de admin: escribe en el repo de datos con el token del admin.
 * Una invitacion guarda solo el sha256 de su secreto; el secreto va en el
 * link (tras el #, no llega a ningun servidor) y lo comprueba la raspi.
 */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  const CFG = window.TELEMETRIA || {};
  const ID_OK = /^[a-z0-9][a-z0-9._-]{1,31}$/;
  let repo = null;
  const estado = { raspis: [], usuarios: [], invs: [] };

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
  }
  function store(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { return null; }
  }
  const fecha = s => s ? new Date(s).toLocaleString() : '—';

  $('#repo-name').textContent = CFG.repo;
  if (!Cripto.disponible()) msg('#tok-msg', 'Abre el portal por https (la web publicada), no desde la raspi.', true);

  $('#tok-form').addEventListener('submit', e => { e.preventDefault(); conectar($('#tok').value.trim()); });
  $('#tok-forget').addEventListener('click', () => {
    store('tele-admin-token', null); $('#tok').value = ''; repo = null;
    $('#panel-admin').hidden = true; msg('#tok-msg', 'Token borrado de este navegador.');
  });

  async function conectar(token) {
    if (!token) return msg('#tok-msg', 'Pega el token.', true);
    repo = Repo.crear(Object.assign({}, CFG, { token }));
    msg('#tok-msg', 'Conectando…');
    try {
      await cargar();
      store('tele-admin-token', token);
      $('#tok').value = token;
      $('#panel-admin').hidden = false;
      msg('#tok-msg', 'Conectado a ' + CFG.repo + '.');
    } catch (e) {
      repo = null;
      $('#panel-admin').hidden = true;
      msg('#tok-msg', 'No puedo leer el repo: ' + e.message, true);
    }
  }

  async function leerDir(dir, filtro) {
    const ents = (await repo.listar(dir)).filter(filtro);
    return Promise.all(ents.map(async f => Object.assign({ _sha: f.sha, _ruta: f.path }, await repo.json(f.path))));
  }

  async function cargar() {
    const [dirs, usuarios, invs] = await Promise.all([
      repo.listar('raspis'),
      leerDir('usuarios', f => f.type === 'file' && f.name.endsWith('.json')),
      leerDir('invitaciones', f => f.type === 'file' && f.name.endsWith('.json')),
    ]);
    estado.raspis = (await Promise.all(dirs.filter(d => d.type === 'dir')
      .map(d => repo.json(d.path + '/raspi.json').then(r => r || { id: d.name })))).sort((a, b) => a.id.localeCompare(b.id));
    estado.usuarios = usuarios.sort((a, b) => a.usuario.localeCompare(b.usuario));
    estado.invs = invs.map(i => Object.assign(i, { _id: i._ruta.split('/').pop().replace(/\.json$/, '') }))
      .sort((a, b) => b.caduca - a.caduca);
    pintar();
  }
  $('#reload').addEventListener('click', () => cargar().catch(e => msg('#inv-msg', e.message, true)));

  function nombreRaspi(id) {
    const r = estado.raspis.find(x => x.id === id);
    return r ? r.nombre + (r.nombre !== id ? ' (' + id + ')' : '') : id + ' (no existe)';
  }

  function fila(ul, titulo, sub, botones) {
    const li = el('li', '', ul);
    const d = el('div', '', li);
    el('b', '', d, titulo);
    el('span', '', d, ' ' + sub);
    const acc = el('div', 'bar', li);
    for (const [txt, fn, cls] of botones) {
      const b = el('button', 'small ' + (cls || 'ghost'), acc, txt);
      b.addEventListener('click', async () => {
        b.disabled = true;
        try { await fn(); } catch (e) { msg('#inv-msg', e.message, true); } finally { b.disabled = false; }
      });
    }
  }

  function pintar() {
    const sel = $('#inv-raspi'), prev = sel.value;
    sel.innerHTML = '';
    for (const r of estado.raspis) sel.add(new Option(nombreRaspi(r.id), r.id, false, r.id === prev));

    const uu = $('#users');
    uu.innerHTML = '';
    for (const u of estado.usuarios) {
      fila(uu, u.usuario, '· ' + nombreRaspi(u.raspi) + ' · alta ' + fecha(u.creado), [
        ['Cambiar contraseña', () => invitar(u.usuario, u.raspi, 7, true)],
        ['Borrar', () => borrar(u._ruta, u._sha, 'el usuario ' + u.usuario +
          '. Deja de poder entrar, pero si ya tenía la clave de su raspi podría seguir leyendo lo subido hasta ahora'), 'danger'],
      ]);
    }
    if (!estado.usuarios.length) el('li', 'muted', uu, 'Aún no hay usuarios.');

    const ui = $('#invs');
    ui.innerHTML = '';
    const ahora = Date.now() / 1000;
    for (const i of estado.invs) {
      const cad = i.caduca < ahora ? 'caducada' : 'caduca ' + fecha(i.caduca * 1000);
      fila(ui, i.usuario, '· ' + nombreRaspi(i.raspi) + (i.cambio ? ' · cambio de contraseña' : '') + ' · ' + cad,
        [['Borrar', () => borrar(i._ruta, i._sha, 'la invitación de ' + i.usuario), 'danger']]);
    }
    if (!estado.invs.length) el('li', 'muted', ui, 'No hay invitaciones pendientes.');

    const ur = $('#raspis');
    ur.innerHTML = '';
    for (const r of estado.raspis) {
      const n = estado.usuarios.filter(u => u.raspi === r.id).length;
      fila(ur, r.nombre || r.id, '· id ' + r.id + ' · ' + n + (n === 1 ? ' usuario' : ' usuarios') +
        (r.direccion ? ' · ' + r.direccion : ''), []);
    }
    if (!estado.raspis.length) el('li', 'muted', ur, 'Ninguna raspi configurada todavía.');
  }

  async function borrar(ruta, sha, que) {
    if (!confirm('¿Borrar ' + que + '?')) return;
    await repo.borrar(ruta, sha, 'admin: borra ' + ruta);
    await cargar();
  }

  async function invitar(usuario, raspi, dias, cambio) {
    const existe = estado.usuarios.some(u => u.usuario === usuario);
    if (existe && !cambio) throw new Error('Ya existe el usuario ' + usuario + ': usa «Cambiar contraseña».');
    const otra = estado.usuarios.find(u => u.usuario === usuario && u.raspi !== raspi);
    if (otra) throw new Error(usuario + ' es de otra raspi (' + otra.raspi + ').');
    const id = [...crypto.getRandomValues(new Uint8Array(8))].map(x => x.toString(16).padStart(2, '0')).join('');
    const secreto = Cripto.aleatorio(32);
    const inv = {
      usuario, raspi, hash: await Cripto.sha256hex(secreto), cambio: !!cambio,
      caduca: Math.floor(Date.now() / 1000) + dias * 86400, creada: new Date().toISOString(),
    };
    await repo.poner('invitaciones/' + id + '.json', JSON.stringify(inv, null, 2) + '\n',
      'admin: invitación para ' + usuario + ' en ' + raspi);
    const app = new URL('./', location.href).href;
    $('#inv-link').value = app + '#alta=' + id + '.' + secreto;
    $('#inv-out').hidden = false;
    msg('#inv-msg', 'Link para ' + usuario + (cambio ? ' (cambio de contraseña)' : '') +
      '. Mándaselo: solo se muestra ahora, caduca en ' + dias + (dias === 1 ? ' día.' : ' días.'));
    await cargar();
  }

  $('#inv-form').addEventListener('submit', async e => {
    e.preventDefault();
    const usuario = $('#inv-user').value.trim().toLowerCase();
    if (!ID_OK.test(usuario)) return msg('#inv-msg', 'Usuario: minúsculas, números, punto, guion o guion bajo (2 a 32).', true);
    if (!$('#inv-raspi').value) return msg('#inv-msg', 'No hay ninguna raspi configurada.', true);
    $('#inv-out').hidden = true;
    try { await invitar(usuario, $('#inv-raspi').value, +$('#inv-dias').value, false); $('#inv-user').value = ''; } catch (err) { msg('#inv-msg', err.message, true); }
  });

  $('#inv-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('#inv-link').value); msg('#inv-msg', 'Link copiado.'); } catch (e) { $('#inv-link').select(); }
  });

  const t = store('tele-admin-token');
  if (t && Cripto.disponible()) conectar(t);
})();
