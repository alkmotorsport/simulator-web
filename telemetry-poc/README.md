# Telemetría de moto: guía de uso

Una Raspberry Pi en la moto lee los sensores. Arranca sola al encenderla y,
con tu usuario, la manejas **desde cualquier sitio** con la app: modo en vivo,
grabar sesiones y activar sensores. Cada sesión grabada se sube **cifrada** al
repo privado `alkmotorsport/telemetry-data`, y la consultas también desde la app.

## Las direcciones

| Para qué | URL | Desde dónde |
|---|---|---|
| **App**: todo. Tus raspis, en vivo, grabar y sesiones | https://motorsport.amorgante.es/telemetry-poc/web/ | Desde cualquier sitio. En el móvil, «Añadir a pantalla de inicio» |
| **Portal de admin**: invitar usuarios, cambiar contraseñas, borrar usuarios | https://motorsport.amorgante.es/telemetry-poc/web/admin.html | Desde cualquier sitio, con el token de admin |
| **Web de la raspi en su wifi** (plan B, sin internet) | https://192.168.68.41:8081 | Solo desde la wifi de la raspi. Aviso de certificado: acéptalo |

Cómo llega la app a la raspi: al arrancar, la raspi abre un **túnel** de
Cloudflare (gratis, sin abrir puertos) que le da una dirección pública del tipo
`https://palabras-al-azar.trycloudflare.com`. Cambia en cada arranque, pero la
raspi la anuncia en el repo de datos y la app la encuentra sola. Para esto la
raspi necesita internet: en casa, por la wifi; en el circuito, compartiendo
datos desde el móvil.

## Uso diario

1. **Enciende la raspi.** La telemetría arranca sola, en vivo y **sin grabar**.
   En 1 o 2 minutos aparece «en línea» en la app (*Tus raspis*).
2. En la app: **Entrar** con tu usuario, y en tu raspi **En vivo**.
3. **● Grabar** empieza una sesión, **■ Parar grabación** la cierra. Al
   cerrarla se sube sola al repo (si no hay internet, en cuanto lo haya).
4. Para ver sesiones grabadas: en tu raspi, **Sesiones**, y elige una.
5. **Apaga la raspi con `sudo poweroff`** (o desde SSH), no desenchufándola:
   así, si estabas grabando, la sesión se cierra y se sube bien.

Si la raspi no tiene internet (circuito sin cobertura): conéctate a su wifi y
abre su web (https://<ip-de-la-raspi>:8081). Pide el mismo usuario y
contraseña, y funciona sin internet. Lo grabado se subirá cuando tenga red.

Comandos útiles (`ssh pi@192.168.68.41`):
```sh
systemctl status telemetria          # ¿está en marcha?
journalctl -u telemetria -f          # ver lo que hace (Ctrl+C para salir)
sudo systemctl restart telemetria    # reiniciarla
cd ~/telemetry/simulator-web/telemetry-poc
sudo python3 sincro.py estado        # sesiones pendientes de subir
sudo python3 sincro.py ahora         # subirlas ya
```

## Usuarios

Cada usuario ve **solo sus raspis**: su web en vivo y sus sesiones. Un usuario
puede tener varias raspis. Las contraseñas no se guardan en ningún sitio: la
contraseña descifra la clave de cada raspi suya, y con esa clave la app
demuestra a la raspi que eres usuario suyo (la contraseña no viaja).

### Dar de alta un usuario (o a ti mismo)
1. En el **portal de admin**, en *Nueva invitación*, pon el usuario, elige la
   raspi y pulsa **Crear link**.
2. **Copia el link en ese momento**: solo se muestra una vez. Caduca a los 7
   días (puedes elegir otra duración).
3. Quien lo reciba lo abre **desde cualquier sitio**, con esa raspi encendida y
   con internet, y elige su contraseña (mínimo 10 caracteres). Debe salir
   «Usuario … listo».
4. A partir de ahí entra en la **app** con su usuario y contraseña.

El alta la hace la propia raspi: por eso tiene que estar encendida. Si no tiene
internet, la página deja poner su dirección en la wifi.

Para dar **otra raspi a un usuario que ya existe**, crea una invitación con su
mismo nombre de usuario y la raspi nueva. Usa la misma contraseña para que al
entrar le salgan todas.

### Olvido de contraseña
En el portal: *Usuarios → Cambiar contraseña* (si tiene varias raspis, hay un
botón por raspi). Genera un link nuevo que se usa igual que el de alta.

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
- La web de la raspi es pública por el túnel, pero solo enseña la página:
  todo lo demás (vivo, grabar, sesiones, ajustes) pide ser usuario de esa
  raspi. Si borras un usuario, la raspi le corta el acceso en cuanto se
  actualiza (cada 10 minutos, o al reiniciarla).
- La raspi lleva Raspbian Buster, que ya no recibe actualizaciones de
  seguridad: conviene no dejarla encendida y conectada sin necesidad.

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

1. Dependencias (Raspberry Pi OS) y el túnel de Cloudflare:
   ```sh
   sudo apt install git python3-cryptography pigpio python3-pigpio python3-smbus python3-spidev openssl i2c-tools
   sudo systemctl enable --now pigpiod
   curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
   sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared
   ```
   (`cloudflared-linux-arm64` si la Pi lleva un sistema de 64 bits.)
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
5. Guarda la copia de su clave de datos (ver arriba) y reinicia la telemetría
   (`sudo systemctl restart telemetria`). En 1 o 2 minutos aparece en el portal
   de admin con su dirección por internet. Ya puedes invitar a sus usuarios.

## Problemas frecuentes

| Qué pasa | Qué hacer |
|---|---|
| Tu raspi sale «apagada o sin internet» | ¿Está encendida y con internet? Tras encenderla tarda 1 o 2 minutos. Pulsa *Actualizar* en *Tus raspis*. En la Pi: `journalctl -u telemetria -f` debe mostrar «Tunel: https://…» |
| El vivo va a saltos o se corta | Por internet llegan unas 4 actualizaciones por segundo; con mala cobertura, menos. En la wifi de la raspi (su web) va más fluido |
| La web de la raspi dice «Entra con un usuario de …» | Es normal: pulsa **Entrar** con tu usuario |
| La app dice «Usuario o contraseña incorrectos» y es correcta | ¿Se completó el alta? En el portal, el usuario debe salir en *Usuarios*, no en *Invitaciones pendientes* |
| «Esta invitación ya se ha usado» | Si ya elegiste contraseña, la cuenta está lista: entra en la app |
| Una sesión no aparece en la app | En la Pi: `sudo python3 sincro.py estado`. Si sale pendiente, `sudo python3 sincro.py ahora` |
| La web de la raspi no responde en su wifi | ¿Está en marcha (`systemctl status telemetria`)? ¿Ha cambiado de IP (portal → *Raspis*, «en su wifi»)? |
| El navegador avisa del certificado otra vez | La raspi cambió de IP y generó un certificado nuevo: acéptalo de nuevo |
| El portal o la app muestran algo antiguo tras publicar | Recarga con Cmd+Shift+R |
| Sesión muy larga (horas) | Pesa mucho (3,5 h de IMU son unos 76 MB): ábrela mejor en el portátil |

## Cómo está hecho (para quien lo toque)

- `telemetria.py`: el programa de la Pi (sensores, grabación y web).
  `live_server.py`: la web de la Pi y su API. `acceso.py`: el login en la web
  de la Pi (reto y firma con la clave de la raspi). `tunel.py`: el túnel de
  Cloudflare y el anuncio de su dirección.
- `sincro.py`: cifrado (gzip + AES-256-GCM), subida al repo de datos por
  HTTPS y altas de usuario. El formato está descrito al principio del fichero.
- `systemd/`: el servicio y su instalador.
- `web/`: la app (la misma en la Pi y publicada). `cuenta.js` gestiona el
  login, tus raspis, las sesiones de la nube y el alta; `cripto.js` el descifrado;
  `repo.js` el acceso a GitHub; `admin.html` y `admin.js` el portal; `sw.js` y
  `manifest.webmanifest` la app instalable.
- `../.github/workflows/pages.yml`: publica la web y mete el token de lectura.
- Repo de datos: `usuarios/<usuario>.json` (sus raspis), `invitaciones/<id>.json`
  y `raspis/<id>/` (con `raspi.json` —sus direcciones—, `indice.enc` y
  `sesiones/*.enc`).
- El vivo va por streaming (SSE) en la wifi y por consultas a `/api/vivo` por
  el túnel, porque el túnel rápido retiene el streaming.
