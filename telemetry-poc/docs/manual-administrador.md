# Telemetría ALK Motorsport — Manual del administrador

Este manual es para quien gestiona los **sistemas de telemetría** (uno por
moto), los **usuarios** y las **credenciales**. A cada usuario se le entrega el
*Manual de usuario*.

**Resumen:** cada sistema de telemetría arranca solo al encenderlo, en vivo y
sin grabar. Sus usuarios lo manejan desde la app, estén donde estén, con su
usuario y contraseña. Cada sesión grabada se sube **cifrada** al repo privado
`alkmotorsport/telemetry-data` y se consulta también desde la app.

---

## 1. Direcciones

| Para qué | Dirección | Desde dónde |
| --- | --- | --- |
| **App** (usuarios): sus sistemas, en vivo, grabar, sesiones | <https://motorsport.amorgante.es/telemetry-poc/web/> | Desde cualquier sitio |
| **Portal de administración**: invitar, cambiar contraseñas, borrar usuarios | <https://motorsport.amorgante.es/telemetry-poc/web/admin.html> | Desde cualquier sitio, con el token de admin |
| **Web de un sistema en su wifi** (sin internet) | `https://<ip-del-sistema>:8081` (Bultaco Mercurio: `https://192.168.68.41:8081`) | Solo desde la wifi del sistema. Hay que aceptar el aviso del certificado |

La dirección en la wifi de cada sistema aparece en el portal, en
**Sistemas de telemetría** («en su wifi»).

## 2. Cómo funciona

- **Acceso por internet:** al arrancar, cada sistema abre un **túnel** de
  Cloudflare (gratuito, sin abrir puertos en ningún router) que le da una
  dirección pública del tipo `https://palabras-al-azar.trycloudflare.com`.
  Cambia en cada arranque, pero el sistema la anuncia en el repo de datos y la
  app la encuentra sola. Para esto el sistema necesita internet: en casa, por
  la wifi; en el circuito, con un móvil compartiendo datos.
- **Usuarios:** un usuario puede tener uno o varios sistemas y solo ve los
  suyos. Las contraseñas no se guardan en ningún sitio: la contraseña descifra
  en el dispositivo del usuario la clave de cada sistema suyo, y con esa clave
  la app demuestra al sistema que es usuario suyo (la contraseña no viaja).
- **Datos:** las sesiones se cifran en el propio sistema antes de subirlas.
  Solo los usuarios de ese sistema pueden descifrarlas.
- **Subida de sesiones:** automática al parar una grabación, al arrancar el
  sistema y cada 10 minutos (si hay pendientes y hay internet).

## 3. Dar de alta un usuario

1. Entra en el **portal de administración** y pega el **token de admin**
   (apartado 7). Pulsa **Conectar**.
2. En **Nueva invitación**: escribe el **usuario** (minúsculas, números, punto,
   guion o guion bajo; de 2 a 32 caracteres), elige el **sistema** y la
   **caducidad**, y pulsa **Crear link**.
3. **Copia el link en ese momento:** solo se muestra una vez.
4. Envía al usuario:
   - el **link de invitación**;
   - el **Manual de usuario**;
   - si lo va a usar sin cobertura (circuito), la **dirección del sistema en
     su wifi** (apartado 1).
5. El usuario abre el link con el sistema **encendido y con internet** y elige
   su contraseña. En el portal pasa de *Invitaciones pendientes* a *Usuarios*.

El alta la hace el propio sistema: por eso tiene que estar encendido. Sin
internet, la página de alta deja poner su dirección en la wifi.

### Dar otro sistema a un usuario que ya existe

Crea una invitación con **su mismo nombre de usuario** y el sistema nuevo.
Pídele que use la misma contraseña, para que al entrar le salgan todos.

### Contraseña olvidada

En **Usuarios → Cambiar contraseña** (si tiene varios sistemas, hay un botón
por sistema). Genera un link nuevo que se usa igual que el de alta.

### Borrar un usuario

En **Usuarios → Borrar**. Deja de poder entrar en la app y en la web de sus
sistemas (en cuanto cada sistema se actualiza: cada 10 minutos o al
reiniciarlo). Si ya había entrado alguna vez, podría seguir leyendo las sesiones
subidas hasta ese día, porque conocía la clave.

### Invitaciones pendientes

Salen en **Invitaciones pendientes** con su caducidad. Puedes **borrar** las
que no se vayan a usar.

## 4. Uso diario de un sistema

- **Encender:** basta con dar corriente. La telemetría arranca sola, en vivo y
  **sin grabar**; en 1 o 2 minutos sale «en línea» en la app.
- **Grabar:** desde la app, **● Grabar** y **■ Parar grabación**. Al parar, la
  sesión se sube sola.
- **Apagar:** con `sudo poweroff` (por SSH), no desenchufándolo: así, si estaba
  grabando, la sesión se cierra y se sube (espera hasta 4 minutos).
- **Sin internet:** los usuarios se conectan a su wifi y abren su web (apartado
  1). Lo grabado se sube cuando haya red.

Comandos útiles (`ssh pi@192.168.68.41` en Bultaco Mercurio):

```sh
systemctl status telemetria          # ¿está en marcha?
journalctl -u telemetria -f          # ver lo que hace (Ctrl+C para salir)
sudo systemctl restart telemetria    # reiniciar
cd ~/telemetry/simulator-web/telemetry-poc
sudo python3 sincro.py estado        # sesiones pendientes de subir
sudo python3 sincro.py ahora         # subirlas ya
```

## 5. Sesiones

Los usuarios ven y borran sus sesiones desde la app (ver el *Manual de
usuario*):

- **Nombre y descripción** de las sesiones de la nube: los pone el usuario con
  **Editar**; los guarda el sistema (en línea) en el índice cifrado.
- **Borrar de la nube:** lo hace el sistema, que tiene que estar en línea. Su
  copia en el sistema, si la hay, se queda y ya no se vuelve a subir.
- **Borrar del sistema:** borra la copia local. Si no estaba subida, se
  pierde (la app avisa). La sesión que se está grabando no se puede borrar.

Una sesión de horas pesa mucho (3,5 h de IMU son unos 76 MB): mejor abrirla en
un ordenador.

## 6. Sistemas de telemetría

El portal lista en **Sistemas de telemetría** cada sistema configurado, sus
usuarios, su dirección por internet (si su túnel está activo) y su dirección
en la wifi.

### Montar un sistema nuevo

1. Instala las dependencias (Raspberry Pi OS) y el túnel de Cloudflare:

   ```sh
   sudo apt install git python3-cryptography pigpio python3-pigpio python3-smbus python3-spidev openssl i2c-tools
   sudo systemctl enable --now pigpiod
   curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
   sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared
   ```

   (`cloudflared-linux-arm64` si lleva un sistema operativo de 64 bits.) El
   resto del hardware (I2C, SPI, LED) está explicado en `requirements.txt`.
2. Instala el código y el servicio:

   ```sh
   mkdir -p ~/telemetry && cd ~/telemetry
   sudo git clone https://github.com/alkmotorsport/simulator-web.git
   cd simulator-web/telemetry-poc
   sudo sh systemd/instalar.sh
   ```

3. Crea un **token para ese sistema** (apartado 7): `telemetry-data`,
   *Contents: Read and write*, con el nombre `telemetria-raspi-<id>`.
4. Conéctalo al repo de datos. El **id** es corto, en minúsculas y **no se
   puede cambiar después**:

   ```sh
   sudo python3 sincro.py iniciar --raspi <id> --nombre "Nombre visible"
   ```

   Te pide el token sin mostrarlo.
5. Guarda la **copia de su clave de datos** (apartado 8) y reinicia la
   telemetría (`sudo systemctl restart telemetria`). En 1 o 2 minutos aparece en
   el portal con su dirección por internet. Ya puedes invitar a sus usuarios.

## 7. Credenciales

| Credencial | Permisos | Dónde está | Caduca |
| --- | --- | --- | --- |
| Token de **lectura** | `telemetry-data`, Contents: Read-only | Secreto `DATOS_TOKEN` del repo `simulator-web`; la publicación lo mete en la web | 26/10/2027 |
| Token de **admin** | `telemetry-data`, Contents: Read and write | Tu gestor de contraseñas; se pega en el portal | Ver en GitHub (cambia al regenerarlo) |
| Token de **cada sistema** | `telemetry-data`, Contents: Read and write | `/etc/telemetria/token` en el sistema (solo root) | Ver en GitHub |
| **Clave de datos** de cada sistema | Descifra todas sus sesiones | `/etc/telemetria/clave` en el sistema | No caduca: **guarda una copia** |

Los tokens se gestionan en <https://github.com/settings/personal-access-tokens>.
Todos son *fine-grained*, con propietario `alkmotorsport` y acceso solo al repo
`telemetry-data`. Si la organización exige aprobarlos, se aprueban en
*alkmotorsport → Settings → Personal access tokens → Pending requests*.

### Cuando caduca un token

- **Lectura:** la app deja de cargar sesiones. Regenéralo, cambia el secreto
  `DATOS_TOKEN` en
  <https://github.com/alkmotorsport/simulator-web/settings/secrets/actions> y
  relanza el workflow «Publicar web» (pestaña *Actions → Run workflow*).
- **Admin:** el portal da error de permisos. Regenéralo y pégalo en el portal.
- **Sistema:** sus sesiones dejan de subirse (`sincro.py estado` muestra
  pendientes). Regenéralo e instálalo sin que se vea:

  ```sh
  ssh -t pi@192.168.68.41 'cd ~/telemetry/simulator-web/telemetry-poc && sudo python3 sincro.py token'
  ```

## 8. Copia de la clave de datos

```sh
ssh pi@192.168.68.41 'sudo base64 /etc/telemetria/clave'
```

Guarda el resultado en el gestor de contraseñas. Si se pierde la tarjeta SD, la
clave también se recupera con la contraseña de cualquier usuario de ese
sistema:

```sh
sudo python3 sincro.py recuperar --usuario <usuario>
```

## 9. Seguridad

- Cualquiera puede abrir el portal, pero sin el token de admin no ve ni cambia
  nada: lo impide GitHub. El portal recuerda el token en ese navegador; en un
  equipo ajeno, pulsa **Olvidar** al terminar.
- El token de lectura va dentro de la web publicada, así que en la práctica es
  público. Solo permite leer, y lo que se lee está cifrado (se ven los nombres
  de usuario, los ids de sistema y las fechas).
- La web de cada sistema es pública por el túnel, pero solo enseña la página:
  todo lo demás (vivo, grabar, sesiones, ajustes) exige ser usuario de ese
  sistema.
- Bultaco Mercurio lleva Raspbian Buster, que ya no recibe actualizaciones de
  seguridad: conviene no dejarlo encendido y conectado sin necesidad.
- Si un token o una contraseña se han compartido por error, regenéralos.

## 10. Actualizar el código

Haz commit y push a `main` del repo `simulator-web`. El workflow «Publicar web»
publica la web en unos 40 segundos (pestaña *Actions*). Después, en cada
sistema:

```sh
cd ~/telemetry/simulator-web
sudo git pull
sudo sh telemetry-poc/systemd/instalar.sh       # solo si cambió el servicio
sudo systemctl restart telemetria
```

Si `git pull` se queja de cambios locales y no se tocó nada a mano en el
sistema: `sudo git reset --hard origin/main` (no borra `datos/`, `certs/` ni
`telemetria.json`).

Si cambias `index.html` o `admin.html`, sube también el número `?v=…` de sus
scripts, para que los navegadores no sigan usando la versión anterior.

## 11. Problemas frecuentes

| Qué pasa | Qué hacer |
| --- | --- |
| Un sistema sale «apagado o sin internet» | ¿Está encendido y con internet? Tras encenderlo tarda 1 o 2 minutos. En el sistema, `journalctl -u telemetria -f` debe mostrar «Tunel: https://…» |
| El vivo va a saltos o se corta | Por internet llegan unas 4 actualizaciones por segundo; con poca cobertura, menos. En la wifi del sistema va más fluido |
| Un usuario dice «Usuario o contraseña incorrectos» | ¿Completó el alta? En el portal debe salir en *Usuarios*, no en *Invitaciones pendientes* |
| «Esta invitación ya se ha usado» | Si ya eligió contraseña, la cuenta está lista |
| Una sesión no aparece en la app | En el sistema: `sudo python3 sincro.py estado`; si sale pendiente, `sudo python3 sincro.py ahora` |
| La web del sistema no responde en su wifi | ¿Está en marcha (`systemctl status telemetria`)? ¿Ha cambiado de IP (portal → *Sistemas de telemetría*)? |
| El navegador avisa otra vez del certificado | El sistema cambió de IP y generó un certificado nuevo: hay que aceptarlo de nuevo |
| El portal o la app muestran algo antiguo | Recarga con Cmd+Shift+R (en el móvil, cerrar y abrir la app) |
