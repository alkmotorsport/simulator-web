/*
 * Cifrado de los datos del repo: el mismo formato que escribe la Pi
 * (sincro.py). WebCrypto solo existe en contexto seguro (https o localhost):
 * la web servida por la Pi en http no puede descifrar.
 *   .enc   'TLM1' + iv (12) + AES-GCM(gzip(datos)), dato asociado = su ruta
 *   usuario: {raspis: {<raspi>: clave de esa raspi cifrada con PBKDF2(contrasena)}}
 *   acceso a la web de una raspi: firma de su reto con su clave (acceso.py)
 */
const Cripto = (function () {
  'use strict';

  const te = new TextEncoder();
  const ub64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const b64 = b => { let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000)); return btoa(s); };
  const disponible = () => !!(window.isSecureContext && window.crypto && crypto.subtle && window.DecompressionStream);

  /** {raspi: entrada} de un fichero de usuario (tambien el formato antiguo, de una raspi). */
  function entradas(u) {
    if (u.raspis) return u.raspis;
    if (u.raspi) return { [u.raspi]: u };
    return {};
  }

  /** Clave de una raspi (bytes) a partir de su entrada; falla si la contrasena no es. */
  async function abrirClave(usuario, raspi, e, password) {
    const base = await crypto.subtle.importKey('raw', te.encode(password), 'PBKDF2', false, ['deriveKey']);
    const kek = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', hash: 'SHA-256', salt: ub64(e.sal), iterations: e.iter },
      base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    const raw = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: ub64(e.iv), additionalData: te.encode('usuario:' + usuario + '|raspi:' + raspi) },
      kek, ub64(e.clave));
    return new Uint8Array(raw);
  }

  async function hmacSha256(clave, texto) {
    const k = await crypto.subtle.importKey('raw', clave, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    return new Uint8Array(await crypto.subtle.sign('HMAC', k, te.encode(texto)));
  }

  /** Respuesta al reto de la web de una raspi (acceso.py): prueba que tienes su clave. */
  async function firmar(raw, reto, usuario) {
    const k = await hmacSha256(raw, 'telemetria-acceso');
    return [...await hmacSha256(k, reto + '|' + usuario)].map(x => x.toString(16).padStart(2, '0')).join('');
  }

  const importar = raw => crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);

  async function descifrar(clave, buf, ruta) {
    const b = new Uint8Array(buf);
    if (String.fromCharCode(b[0], b[1], b[2], b[3]) !== 'TLM1') throw new Error('formato desconocido');
    const gz = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b.subarray(4, 16), additionalData: te.encode(ruta) }, clave, b.subarray(16));
    const plano = new Blob([gz]).stream().pipeThrough(new DecompressionStream('gzip'));
    return new Uint8Array(await new Response(plano).arrayBuffer());
  }

  async function descifrarJSON(clave, buf, ruta) {
    return JSON.parse(new TextDecoder().decode(await descifrar(clave, buf, ruta)));
  }

  /** n bytes aleatorios en base64url (para el secreto de las invitaciones). */
  function aleatorio(n) {
    return b64(crypto.getRandomValues(new Uint8Array(n))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  async function sha256hex(s) {
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', te.encode(s)));
    return [...h].map(x => x.toString(16).padStart(2, '0')).join('');
  }

  return { disponible, entradas, abrirClave, firmar, importar, descifrar, descifrarJSON, aleatorio, sha256hex, b64, ub64 };
})();
