# Telemetría de moto: guía de uso

Una Raspberry Pi en la moto lee los sensores. Mientras preparas la moto la ves
**en vivo** desde la wifi, y cada sesión grabada se sube **cifrada** al repo
privado `alkmotorsport/telemetry-data`, desde donde la consultas con la app
estés donde estés.

## Las tres direcciones

| Para qué | URL | Desde dónde |
|---|---|---|
| **App**: entrar con tu usuario y ver las sesiones grabadas | https://motorsport.amorgante.es/telemetry-poc/web/ | Desde cualquier sitio. En el móvil, «Añadir a pantalla de inicio» |
| **Raspi**: modo en vivo, grabar, activar sensores, dar de alta usuarios | https://192.168.68.41:8081 | Solo desde la misma wifi que la raspi, con la telemetría arrancada |
| **Portal de admin**: invitar usuarios, cambiar contraseñas, borrar usuarios | https://motorsport.amorgante.es/telemetry-poc/web/admin.html | Desde cualquier sitio, con el token de admin |

- La raspi usa un certificado autofirmado. La primera vez en cada dispositivo
  sale un aviso de seguridad: acéptalo (Chrome: *Configuración avanzada →
  Acceder*; Safari: *Mostrar detalles → visitar este sitio web*).
- Si la raspi cambia de IP, la nueva aparece en el portal de admin, en
  **Raspis**, y la app la usa sola al entrar.

## Uso diario

Conéctate a la Pi con `ssh pi@192.168.68.41`.

```sh
sudo systemctl start telemetria      # arrancar (empieza a grabar)
sudo systemctl stop telemetria       # parar: cierra la sesión y la sube
systemctl status telemetria          # ¿está en marcha?
journalctl -u telemetria -f          # ver lo que hace (Ctrl+C para salir)
```

- **No arranca sola al encender la Pi**: se lanza a mano. Sigue en marcha
  aunque cierres la sesión SSH.
- **Graba nada más arrancar.** Desde la web de la raspi puedes parar y empezar
  grabaciones con el botón ● Grabar.
- **Subida al repo:** cada sesión se sube al terminarla (con el botón o al
  parar el servicio). Al parar, espera hasta 4 minutos a que termine la subida.
  Si no hay internet (en el circuito), se sube sola en el siguiente arranque
  con red. Para subir a mano lo pendiente:
  ```sh
  cd ~/telemetry/simulator-web/telemetry-poc
  sudo python3 sincro.py estado      # qué falta por subir
  sudo python3 sincro.py ahora       # subirlo ya
  ```
- **Apaga la Pi con `sudo poweroff`**, no desenchufándola: así la sesión se
  cierra bien.

## Usuarios

Cada usuario ve **solo las sesiones de su raspi**. Las contraseñas no se
guardan en ningún sitio: la contraseña descifra la clave de su raspi.

### Dar de alta un usuario (o a ti mismo)
1. En el **portal de admin**, en *Nueva invitación*, pon el usuario, elige la
   raspi (la dirección se rellena sola) y pulsa **Crear link**.
2. **Copia el link en ese momento**: solo se muestra una vez. Caduca a los 7
   días (puedes elegir otra duración).
3. Quien lo reciba lo abre **conectado a la wifi de la moto, con la telemetría
   arrancada**, acepta el aviso del certificado y elige su contraseña (mínimo
   10 caracteres). Debe salir «Usuario … listo».
4. A partir de ahí entra en la **app** con su usuario y contraseña, desde
   cualquier sitio.

El alta la hace la propia raspi, por eso hay que estar en su wifi.

### Olvido de contraseña
En el portal: *Usuarios → Cambiar contraseña*. Genera un link nuevo que se
usa igual que el de alta.

### Borrar un usuario
En el portal: *Usuarios → Borrar*. Deja de poder entrar. Aviso: si ya había
entrado alguna vez, podría seguir leyendo las sesiones subidas hasta ese día.

### Usuarios actuales
- `alknopfler`, de la raspi `alknopfler-bultaco1` («Bultaco Mercurio»).

## Credenciales: qué hay y dónde está

| Credencial | Permisos | Dónde está | Caduca |
|---|---|---|---|
| Token de **lectura** | `telemetry-data`, Contents: Read-only | Secreto `DATOS_TOKEN` de `simulator-web`; el despliegue lo mete en la web | 26/10/2027 |
| Token de **admin** | `telemetry-data`, Contents: Read and write | Tu gestor de contraseñas; se pega en el portal | Mira la fecha en GitHub (al regenerarlo cambia) |
| Token de la **raspi** | `telemetry-data`, Contents: Read and write | `/etc/telemetria/token` en la Pi (solo root) | Mira la fecha en GitHub |
| **Clave de datos** de la raspi | Descifra todas sus sesiones | `/etc/telemetria/clave` en la Pi | No caduca: **guarda una copia** |

Los tokens se gestionan en https://github.com/settings/personal-access-tokens.
Todos son *fine-grained*, con owner `alkmotorsport` y acceso solo a
`telemetry-data`.

### Cuando caduque un token
- **Lectura:** la app deja de cargar sesiones. Créalo de nuevo (o
  *Regenerate token*) y cambia el secreto `DATOS_TOKEN` en
  https://github.com/alkmotorsport/simulator-web/settings/secrets/actions.
  Después relanza el workflow «Publicar web» (pestaña *Actions → Run
  workflow*) o haz cualquier push.
- **Admin:** el portal da error de permisos. Regenéralo y pégalo en el portal.
- **Raspi:** las sesiones dejan de subirse (`sincro.py estado` muestra
  pendientes). Regenéralo e instálalo sin que se vea:
  ```sh
  ssh -t pi@192.168.68.41 'cd ~/telemetry/simulator-web/telemetry-poc && sudo python3 sincro.py token'
  ```

### Copia de la clave de datos
```sh
ssh pi@192.168.68.41 'sudo base64 /etc/telemetria/clave'
```
Guarda el resultado en el gestor de contraseñas. Si se pierde la tarjeta SD,
la clave también se puede recuperar con la contraseña de cualquier usuario de
esa raspi:
```sh
sudo python3 sincro.py recuperar --usuario alknopfler
```

### Sobre la seguridad
- Cualquiera puede abrir el portal de admin, pero sin el token de admin no ve
  ni cambia nada: lo impide GitHub. El portal recuerda el token en ese
  navegador; en un equipo ajeno, pulsa **Olvidar** al terminar.
- El token de lectura está dentro de la web publicada, así que en la práctica
  es público. Solo permite leer, y lo que se lee está cifrado (se ven los
  nombres de usuario, los ids de raspi y las fechas).
- La web de la raspi está abierta a cualquiera que esté en su wifi.

## Actualizar el código

Desde tu Mac, haz commit y push a `main`. El workflow «Publicar web» publica
la web en unos 40 segundos (lo puedes seguir en la pestaña *Actions*).

Después, en la Pi:
```sh
cd ~/telemetry/simulator-web
sudo git pull
sudo sh telemetry-poc/systemd/instalar.sh       # solo si cambió el servicio
sudo systemctl restart telemetria
```
Si `git pull` se queja de cambios locales, y no tocaste nada a mano en la Pi:
`sudo git reset --hard origin/main` (no borra `datos/`, `certs/` ni
`telemetria.json`).

Si cambias `index.html` o `admin.html`, sube también el número `?v=…` de sus
scripts. Así los navegadores no siguen usando la versión anterior guardada.

## Montar una raspi nueva

1. Dependencias (Raspberry Pi OS):
   ```sh
   sudo apt install git python3-cryptography pigpio python3-pigpio python3-smbus python3-spidev openssl i2c-tools
   sudo systemctl enable --now pigpiod
   ```
   El resto del hardware (I2C, SPI, LEDs) está explicado en `requirements.txt`.
2. Código y servicio:
   ```sh
   mkdir -p ~/telemetry && cd ~/telemetry
   sudo git clone https://github.com/alkmotorsport/simulator-web.git
   cd simulator-web/telemetry-poc
   sudo sh systemd/instalar.sh
   ```
3. Crea un token para ella (como el de admin: `telemetry-data`, Contents: Read
   and write; nómbralo `telemetria-raspi-<id>`).
4. Configura su conexión con el repo de datos. El id es corto, en minúsculas y
   **no se puede cambiar después**:
   ```sh
   sudo python3 sincro.py iniciar --raspi <id> --nombre "Nombre visible"
   ```
   Te pide el token sin mostrarlo. Al terminar, la raspi aparece en el portal
   de admin.
5. Guarda la copia de su clave de datos (ver arriba) y arranca la telemetría.
   Ya puedes invitar a sus usuarios.

## Problemas frecuentes

| Qué pasa | Qué hacer |
|---|---|
| La app dice «Usuario o contraseña incorrectos» y es correcta | ¿Se completó el alta? En el portal, el usuario debe salir en *Usuarios*, no en *Invitaciones pendientes* |
| «Esta invitación ya se ha usado» | Si ya elegiste contraseña, la cuenta está lista: entra en la app |
| Una sesión no aparece en la app | En la Pi: `sudo python3 sincro.py estado`. Si sale pendiente, `sudo python3 sincro.py ahora` |
| La raspi no responde en https://192.168.68.41:8081 | ¿Está en marcha (`systemctl status telemetria`)? ¿Estás en su wifi? ¿Ha cambiado de IP (portal → *Raspis*)? |
| El navegador avisa del certificado otra vez | La raspi cambió de IP y generó un certificado nuevo: acéptalo de nuevo |
| El portal o la app muestran algo antiguo tras publicar | Recarga con Cmd+Shift+R |
| Sesión muy larga (horas) | Pesa mucho (3,5 h de IMU son unos 76 MB): ábrela mejor en el portátil |

## Cómo está hecho (para quien lo toque)

- `telemetria.py`: el programa de la Pi (sensores, grabación y web).
  `live_server.py`: la web de la Pi y su API.
- `sincro.py`: cifrado (gzip + AES-256-GCM), subida al repo de datos por
  HTTPS y altas de usuario. El formato está descrito al principio del fichero.
- `systemd/`: el servicio y su instalador.
- `web/`: la app (la misma en la Pi y publicada). `cuenta.js` gestiona el
  login, las sesiones de la nube y el alta; `cripto.js` el descifrado;
  `repo.js` el acceso a GitHub; `admin.html` y `admin.js` el portal; `sw.js` y
  `manifest.webmanifest` la app instalable.
- `../.github/workflows/pages.yml`: publica la web y mete el token de lectura.
- Repo de datos: `usuarios/<usuario>.json`, `invitaciones/<id>.json` y
  `raspis/<id>/` (con `raspi.json`, `indice.enc` y `sesiones/*.enc`).
