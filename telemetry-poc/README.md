# Telemetría de moto

Cada moto lleva un **sistema de telemetría** que lee sus sensores. Sus usuarios
lo manejan desde la app (en vivo, grabar y sesiones) estén donde estén, y las
sesiones grabadas se guardan cifradas en el repo privado
`alkmotorsport/telemetry-data`.

- **App:** <https://motorsport.amorgante.es/telemetry-poc/web/>
- **Portal de administración:** <https://motorsport.amorgante.es/telemetry-poc/web/admin.html>

## Manuales

| Para | Manual | PDF |
| --- | --- | --- |
| Usuarios (pilotos, mecánicos…): qué pedir al administrador, activar la cuenta y usar la app | [docs/manual-usuario.md](docs/manual-usuario.md) | [docs/manual-usuario.pdf](docs/manual-usuario.pdf) |
| Administrador: usuarios, sistemas, credenciales, instalación y problemas | [docs/manual-administrador.md](docs/manual-administrador.md) | [docs/manual-administrador.pdf](docs/manual-administrador.pdf) |

Los PDF se generan desde los `.md` con `node docs/generar-pdf.mjs docs web/logo.jpg`
(instrucciones al principio de ese fichero).

## Cómo está hecho (para quien lo toque)

- `telemetria.py`: el programa del sistema (sensores, grabación y web).
  `live_server.py`: la web del sistema y su API. `acceso.py`: el login en la web
  del sistema (reto y firma con la clave del sistema). `tunel.py`: el túnel de
  Cloudflare y el anuncio de su dirección.
- `sincro.py`: cifrado (gzip + AES-256-GCM), subida al repo de datos por
  HTTPS y altas de usuario. El formato está descrito al principio del fichero.
- `systemd/`: el servicio y su instalador.
- `web/`: la app (la misma en el sistema y publicada). `cuenta.js` gestiona el
  login, tus sistemas, las sesiones de la nube y el alta; `cripto.js` el descifrado;
  `repo.js` el acceso a GitHub; `admin.html` y `admin.js` el portal; `sw.js` y
  `manifest.webmanifest` la app instalable.
- `../.github/workflows/pages.yml`: publica la web y mete el token de lectura.
- Repo de datos: `usuarios/<usuario>.json` (sus sistemas), `invitaciones/<id>.json`
  y `raspis/<id>/` (con `raspi.json` —sus direcciones—, `indice.enc` y
  `sesiones/*.enc`).
- El vivo va por streaming (SSE) en la wifi y por consultas a `/api/vivo` por
  el túnel, porque el túnel rápido retiene el streaming.
