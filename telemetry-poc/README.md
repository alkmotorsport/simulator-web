# Telemetría de moto: guía de uso

El sistema de telemetría de la moto lee los sensores. Arranca solo al encenderlo y,
con tu usuario, la manejas **desde cualquier sitio** con la app: modo en vivo,
grabar sesiones y activar sensores. Cada sesión grabada se sube **cifrada** al
repo privado `alkmotorsport/telemetry-data`, y la consultas también desde la app.

## Las direcciones

| Para qué | URL | Desde dónde |
|---|---|---|
| **App**: todo. Tus sistemas de telemetría, en vivo, grabar y sesiones | https://motorsport.amorgante.es/telemetry-poc/web/ | Desde cualquier sitio. En el móvil, «Añadir a pantalla de inicio» |
| **Portal de admin**: invitar usuarios, cambiar contraseñas, borrar usuarios | https://motorsport.amorgante.es/telemetry-poc/web/admin.html | Desde cualquier sitio, con el token de admin |
| **Web del sistema en su wifi** (plan B, sin internet) | https://192.168.68.41:8081 | Solo desde la wifi del sistema. Aviso de certificado: acéptalo |

Cómo llega la app al sistema: al arrancar, el sistema abre un **túnel** de
Cloudflare (gratis, sin abrir puertos) que le da una dirección pública del tipo
`https://palabras-al-azar.trycloudflare.com`. Cambia en cada arranque, pero el
sistema la anuncia en el repo de datos y la app la encuentra sola. Para esto el
sistema necesita internet: en casa, por la wifi; en el circuito, compartiendo
datos desde el móvil.

## Uso diario

1. **Enciende el sistema.** La telemetría arranca sola, en vivo y **sin grabar**.
   En 1 o 2 minutos aparece «en línea» en la app (*Tus sistemas de telemetría*).
2. En la app: **Entrar** con tu usuario, y en tu sistema **En vivo**.
3. **● Grabar** empieza una sesión, **■ Parar grabación** la cierra. Al
   cerrarla se sube sola al repo (si no hay internet, en cuanto lo haya).
4. Para ver sesiones grabadas: en tu sistema, **Sesiones**, y elige una.
   Arriba están las de la nube; debajo, las guardadas en el propio sistema
   («en la nube» o «sin subir»).
5. **Borrar** (pide confirmación, no se puede deshacer):
   - *De la nube*: lo hace tu sistema, así que tiene que estar en línea. Su
     copia en el sistema, si la hay, se queda y ya no se vuelve a subir.
   - *Del sistema*: borra su copia local. Si sale «sin subir», avisa de que
     se perderá. La que se está grabando no se puede borrar.
6. **Apaga el sistema con `sudo poweroff`** (o desde SSH), no desenchufándola:
   así, si estabas grabando, la sesión se cierra y se sube bien.

Si el sistema no tiene internet (circuito sin cobertura): conéctate a su wifi y
abre su web (https://<ip-del-sistema>:8081). Pide el mismo usuario y
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

Cada usuario ve **solo sus sistemas**: su web en vivo y sus sesiones. Un usuario
puede tener varios sistemas. Las contraseñas no se guardan en ningún sitio: la
contraseña descifra la clave de cada sistema suyo, y con esa clave la app
demuestra al sistema que eres usuario suyo (la contraseña no viaja).

### Dar de alta un usuario (o a ti mismo)
1. En el **portal de admin**, en *Nueva invitación*, pon el usuario, elige el
   sistema y pulsa **Crear link**.
2. **Copia el link en ese momento**: solo se muestra una vez. Caduca a los 7
   días (puedes elegir otra duración).
3. Quien lo reciba lo abre **desde cualquier sitio**, con ese sistema encendido y
   con internet, y elige su contraseña (mínimo 10 caracteres). Debe salir
   «Usuario … listo».
4. A partir de ahí entra en la **app** con su usuario y contraseña.

El alta la hace el propio sistema: por eso tiene que estar encendido. Si no tiene
internet, la página deja poner su dirección en la wifi.

Para dar **otro sistema a un usuario que ya existe**, crea una invitación con su
mismo nombre de usuario y la sistema nuevo. Usa la misma contraseña para que al
entrar le salgan todas.

### Olvido de contraseña
En el portal: *Usuarios → Cambiar contraseña* (si tiene varios sistemas, hay un
botón por sistema). Genera un link nuevo que se usa igual que el de alta.

### Borrar un usuario
En el portal: *Usuarios → Borrar*. Deja de poder entrar. Aviso: si ya había
entrado alguna vez, podría seguir leyendo las sesiones subidas hasta ese día.

### Usuarios actuales
- `alknopfler`, del sistema `alknopfler-bultaco1` («Bultaco Mercurio»).

## Credenciales: qué hay y dónde está

| Credencial | Permisos | Dónde está | Caduca |
|---|---|---|---|
| Token de **lectura** | `telemetry-data`, Contents: Read-only | Secreto `DATOS_TOKEN` de `simulator-web`; el despliegue lo mete en la web | 26/10/2027 |
| Token de **admin** | `telemetry-data`, Contents: Read and write | Tu gestor de contraseñas; se pega en el portal | Mira la fecha en GitHub (al regenerarlo cambia) |
| Token del **sistema** | `telemetry-data`, Contents: Read and write | `/etc/telemetria/token` en el sistema (solo root) | Mira la fecha en GitHub |
| **Clave de datos** del sistema | Descifra todas sus sesiones | `/etc/telemetria/clave` en el sistema | No caduca: **guarda una copia** |

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
- **Sistema:** las sesiones dejan de subirse (`sincro.py estado` muestra
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
ese sistema:
```sh
sudo python3 sincro.py recuperar --usuario alknopfler
```

### Sobre la seguridad
- Cualquiera puede abrir el portal de admin, pero sin el token de admin no ve
  ni cambia nada: lo impide GitHub. El portal recuerda el token en ese
  navegador; en un equipo ajeno, pulsa **Olvidar** al terminar.
- El token de lectura está dentro de la web publicada, así que en la práctica
  es público. Solo permite leer, y lo que se lee está cifrado (se ven los
  nombres de usuario, los ids de sistema y las fechas).
- La web del sistema es pública por el túnel, pero solo enseña la página:
  todo lo demás (vivo, grabar, sesiones, ajustes) pide ser usuario de ese
  sistema. Si borras un usuario, el sistema le corta el acceso en cuanto se
  actualiza (cada 10 minutos, o al reiniciarlo).
- El sistema lleva Raspbian Buster, que ya no recibe actualizaciones de
  seguridad: conviene no dejarlo encendido y conectada sin necesidad.

## Actualizar el código

Desde tu Mac, haz commit y push a `main`. El workflow «Publicar web» publica
la web en unos 40 segundos (lo puedes seguir en la pestaña *Actions*).

Después, en el sistema:
```sh
cd ~/telemetry/simulator-web
sudo git pull
sudo sh telemetry-poc/systemd/instalar.sh       # solo si cambió el servicio
sudo systemctl restart telemetria
```
Si `git pull` se queja de cambios locales, y no tocaste nada a mano en el sistema:
`sudo git reset --hard origin/main` (no borra `datos/`, `certs/` ni
`telemetria.json`).

Si cambias `index.html` o `admin.html`, sube también el número `?v=…` de sus
scripts. Así los navegadores no siguen usando la versión anterior guardada.

## Montar un sistema nuevo

1. Dependencias (Raspberry Pi OS) y el túnel de Cloudflare:
   ```sh
   sudo apt install git python3-cryptography pigpio python3-pigpio python3-smbus python3-spidev openssl i2c-tools
   sudo systemctl enable --now pigpiod
   curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
   sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared
   ```
   (`cloudflared-linux-arm64` si el sistema lleva un sistema de 64 bits.)
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
   Te pide el token sin mostrarlo. Al terminar, el sistema aparece en el portal
   de admin.
5. Guarda la copia de su clave de datos (ver arriba) y reinicia la telemetría
   (`sudo systemctl restart telemetria`). En 1 o 2 minutos aparece en el portal
   de admin con su dirección por internet. Ya puedes invitar a sus usuarios.

## Problemas frecuentes

| Qué pasa | Qué hacer |
|---|---|
| Tu sistema sale «apagado o sin internet» | ¿Está encendido y con internet? Tras encenderlo tarda 1 o 2 minutos. Pulsa *Actualizar* en *Tus sistemas de telemetría*. En la Pi: `journalctl -u telemetria -f` debe mostrar «Tunel: https://…» |
| El vivo va a saltos o se corta | Por internet llegan unas 4 actualizaciones por segundo; con mala cobertura, menos. En la wifi del sistema (su web) va más fluido |
| La web del sistema dice «Entra con un usuario de …» | Es normal: pulsa **Entrar** con tu usuario |
| La app dice «Usuario o contraseña incorrectos» y es correcta | ¿Se completó el alta? En el portal, el usuario debe salir en *Usuarios*, no en *Invitaciones pendientes* |
| «Esta invitación ya se ha usado» | Si ya elegiste contraseña, la cuenta está lista: entra en la app |
| Una sesión no aparece en la app | En el sistema: `sudo python3 sincro.py estado`. Si sale pendiente, `sudo python3 sincro.py ahora` |
| La web del sistema no responde en su wifi | ¿Está en marcha (`systemctl status telemetria`)? ¿Ha cambiado de IP (portal → *Sistemas de telemetría*, «en su wifi»)? |
| El navegador avisa del certificado otra vez | El sistema cambió de IP y generó un certificado nuevo: acéptalo de nuevo |
| El portal o la app muestran algo antiguo tras publicar | Recarga con Cmd+Shift+R |
| Sesión muy larga (horas) | Pesa mucho (3,5 h de IMU son unos 76 MB): ábrela mejor en el portátil |

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
