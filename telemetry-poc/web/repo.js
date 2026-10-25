/*
 * Acceso al repo de datos por la API de GitHub (lectura con el token de la
 * app; el portal de admin usa su propio token con escritura).
 */
const Repo = (function () {
  'use strict';

  function crear({ repo, token, rama = 'main', api = 'https://api.github.com' }) {
    const ruta = p => api + '/repos/' + repo + '/contents/' + p.split('/').map(encodeURIComponent).join('/');

    async function pedir(p, { accept = 'application/vnd.github+json', method = 'GET', body, query = true, url } = {}) {
      const r = await fetch(url || ruta(p) + (query ? '?ref=' + encodeURIComponent(rama) : ''), {
        method, cache: 'no-store',
        headers: Object.assign({ Accept: accept, 'X-GitHub-Api-Version': '2022-11-28' },
          token ? { Authorization: 'Bearer ' + token } : {}, body ? { 'Content-Type': 'application/json' } : {}),
        body: body ? JSON.stringify(body) : undefined,
      });
      if (r.status === 404) return null;
      if (r.status === 401) throw new Error('token del repo no válido o caducado');
      if (r.status === 403 && r.headers.get('x-ratelimit-remaining') === '0') throw new Error('límite de peticiones a GitHub: espera unos minutos');
      if (!r.ok) throw new Error('GitHub ' + r.status + ': ' + ((await r.json().catch(() => ({}))).message || ''));
      return r;
    }

    return {
      repo,
      /** Contenido de un fichero (ArrayBuffer) o null si no existe. Por la API
       *  de blobs: la de contenidos toma algunos binarios pequenos por texto
       *  UTF-16 y los convierte a UTF-8 (los .enc dejan de descifrar). */
      async raw(p) {
        const meta = await this.info(p);
        if (!meta || !meta.sha) return null;
        const r = await pedir(p, { accept: 'application/vnd.github.raw+json', url: api + '/repos/' + repo + '/git/blobs/' + meta.sha });
        return r && r.arrayBuffer();
      },
      async json(p) { const b = await this.raw(p); return b && JSON.parse(new TextDecoder().decode(b)); },
      /** Entradas de una carpeta ([] si no existe). */
      async listar(dir) { const r = await pedir(dir); return r ? r.json() : []; },
      /** Metadatos (sha) de un fichero, o null. */
      async info(p) { const r = await pedir(p); return r && r.json(); },
      async poner(p, texto, mensaje, sha) {
        const content = Cripto.b64(new TextEncoder().encode(texto));
        return (await pedir(p, { method: 'PUT', query: false, body: Object.assign({ message: mensaje, content, branch: rama }, sha ? { sha } : {}) })).json();
      },
      async borrar(p, sha, mensaje) {
        return pedir(p, { method: 'DELETE', query: false, body: { message: mensaje, sha, branch: rama } });
      },
    };
  }

  return { crear };
})();
