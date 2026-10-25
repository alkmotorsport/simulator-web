# Telemetría ALK Motorsport — Manual de usuario

El **sistema de telemetría** va montado en la moto y lee sus sensores
(suspensión, ruedas, inclinación, temperaturas…). Con la **app** ves esos datos
en vivo desde cualquier sitio, grabas sesiones y las consultas después.

Este manual explica qué tienes que pedir al administrador, cómo activar tu
cuenta y cómo usar la app.

---

## 1. Qué necesitas pedir al administrador

Pide al administrador:

1. **Un nombre de usuario.** Lo elige él: en minúsculas, sin espacios (por
   ejemplo `carlos` o `carlos.lopez`).
2. **Un link de invitación** para tu sistema de telemetría (el de tu moto).
   - Te lo mandará por mensaje o correo.
   - **Solo sirve una vez** y **caduca** (normalmente a los 7 días). Si caduca
     o lo pierdes, pide otro.
   - Si vas a usar **varios sistemas** (varias motos), te mandará un link por
     cada uno. Usa la misma contraseña en todos.
3. **La dirección del sistema en su wifi** (por ejemplo
   `https://192.168.1.50:8081`). Solo hace falta si vas a usarlo en sitios
   sin cobertura de internet (ver el apartado 8).

Tu contraseña la eliges tú al activar la cuenta. **Nadie más la conoce, ni
siquiera el administrador.**

## 2. Activar tu cuenta

Necesitas tener el **sistema de telemetría encendido y con internet** (en
casa, conectado a la wifi; en el circuito, con el móvil compartiendo datos).
Tras encenderlo, espera 1 o 2 minutos.

1. Abre el **link de invitación** en el móvil o el ordenador.
2. Espera a que salga **«Alta de *tu usuario* en *nombre del sistema*»**.
3. Escribe tu **contraseña** dos veces (**mínimo 10 caracteres**) y pulsa
   **Guardar contraseña**.
4. Tras unos segundos saldrá **«Usuario … listo»**. Ya puedes entrar (apartado 4).

Si algo no va:

| Mensaje | Qué hacer |
| --- | --- |
| «No encuentro … por internet» | El sistema está apagado o sin internet. Enciéndelo, espera 2 minutos y recarga la página. Si estás junto a la moto sin internet, conéctate a la wifi del sistema, pon su dirección (apartado 1, punto 3) y pulsa **Conectar** |
| «Esta invitación ya se ha usado (o no existe)» | Si ya elegiste contraseña, tu cuenta está lista: entra. Si no, pide otro link |
| «La invitación ha caducado» | Pide otro link al administrador |

## 3. Instalar la app

La app es una página web que se puede instalar como una aplicación más:

**<https://motorsport.amorgante.es/telemetry-poc/web/>**

- **iPhone / iPad:** ábrela en **Safari** → botón **Compartir** →
  **Añadir a pantalla de inicio**.
- **Android:** ábrela en **Chrome** → menú **⋮** → **Instalar aplicación** (o
  **Añadir a pantalla de inicio**).
- **Ordenador:** ábrela en Chrome o Edge y, si quieres, pulsa el icono de
  instalar de la barra de direcciones. También vale usarla sin instalar.

## 4. Entrar

1. Abre la app y pulsa **Entrar** (arriba a la derecha).
2. Escribe tu **usuario** y tu **contraseña**.
3. Deja marcado **Recordar en este dispositivo** si es tu móvil o tu
   ordenador. En un equipo compartido, desmárcalo y pulsa **Salir** al terminar.

Al entrar verás **Tus sistemas de telemetría**: uno por cada moto a la que
tienes acceso, con su estado:

- **en línea:** encendido y con internet. Puedes usar el modo en vivo.
- **apagado o sin internet:** solo puedes ver las sesiones ya subidas a la
  nube. Pulsa **Actualizar** tras encenderlo.

Cada sistema tiene dos botones, **En vivo** y **Sesiones**. El que está en
**naranja** es lo que ves en ese momento.

## 5. En vivo

Pulsa **En vivo** en tu sistema (tiene que estar «en línea»).

- **Datos en vivo:** un bloque por sensor con las cifras («Ahora», máximos,
  medias…) y sus gráficas. Por internet llegan unas 4 actualizaciones por
  segundo; con mala cobertura, menos.
- **Ventana:** cuántos segundos se ven en las gráficas (5, 10, 30 o 60).
- **Pausar:** congela las gráficas para mirarlas con calma (arrastra para
  ampliar un tramo). **Seguir** vuelve al vivo.
- **● Grabar / ■ Parar grabación:** el sistema arranca **sin grabar**; solo se
  graba una sesión cuando pulsas **Grabar**. Al parar, la sesión se sube sola a
  la nube (si no hay internet, en cuanto lo haya).
- **Sensores y salidas:** lista de lo conectado a la moto. El tick activa o
  desactiva cada sensor; **auto** quiere decir que se activa solo si se detecta
  conectado. Algunos tienen acciones, como **Calibrar** (con la moto quieta).
- **Salidas del cuadro:** la app muestra lo mismo que los LED y la pantalla
  de la moto.

## 6. Sesiones

Pulsa **Sesiones** en tu sistema.

- **Sesiones en la nube:** las grabaciones ya subidas. Se ven desde cualquier
  sitio, aunque el sistema esté apagado.
- **Sesiones guardadas en el sistema:** las que hay en el propio sistema
  (solo si está «en línea»). Cada una indica **en la nube** o **sin subir**.
- Pulsa el nombre de una sesión para abrirla. Debajo salen sus bloques y
  gráficas:
  - Todas las gráficas comparten el eje de tiempo: el cursor marca el mismo
    instante en todos los sensores.
  - **Arrastra en horizontal** sobre una gráfica para ampliar un tramo (las
    cifras se recalculan para ese tramo). **Doble clic** o **Ver todo** para
    volver.
  - Con un tramo ampliado, arriba sale una **barra con toda la sesión**:
    arrastra la parte resaltada (o toca otro punto de la barra) para moverte
    en el tiempo sin perder el zoom. **◀ ▶** avanzan o retroceden media
    ventana. En el portátil también vale deslizar en horizontal en el
    trackpad.
  - Con las **casillas** de arriba ocultas o muestras sensores; con **⠿**
    arrastras un bloque para cambiar el orden. **⚙ Ajustes** guarda ese orden
    y las opciones.
- **Borrar** (pide confirmación y no se puede deshacer):
  - **De la nube:** lo borra tu sistema, así que tiene que estar «en línea».
    Su copia en el sistema, si la hay, no se borra.
  - **Del sistema:** borra la copia guardada en la moto. Si pone **sin subir**,
    se perderá para siempre. La sesión que se está grabando no se puede borrar.
- Al final de la página puedes abrir **CSV del ordenador** o la **sesión de
  ejemplo**.

## 7. Encender y apagar el sistema

- **Encender:** basta con dar corriente. En 1 o 2 minutos sale «en línea»
  en la app (si tiene internet).
- **Apagar:** pide al administrador cómo hacerlo en tu moto. Si se corta la
  corriente mientras graba, la sesión puede quedar **cortada** (se guarda lo
  grabado hasta ese momento).

## 8. Sin cobertura de internet (circuito)

Si el sistema no tiene internet, la app no lo encuentra («apagado o sin
internet»). Puedes usarlo igualmente **junto a la moto**:

1. Conecta el móvil a la **wifi del sistema**.
2. Abre en el navegador su **dirección en la wifi** (apartado 1, punto 3).
3. La primera vez en cada dispositivo sale un **aviso de seguridad del
   certificado**: acéptalo (Chrome: *Configuración avanzada → Acceder*;
   Safari: *Mostrar detalles → visitar este sitio web*).
4. Pulsa **Entrar** con tu mismo usuario y contraseña. Funciona sin internet.

Lo que grabes se subirá a la nube en cuanto el sistema tenga internet.

## 9. Contraseña olvidada

Pide al administrador un **link de cambio de contraseña**. Se usa igual que el
de alta (apartado 2).

## 10. Privacidad y seguridad

- Tus sesiones viajan y se guardan **cifradas**. Solo las ven los usuarios de
  tu sistema de telemetría.
- Tu contraseña **no se envía** a ningún sitio ni se guarda: sirve para
  descifrar la clave de tu sistema en tu propio dispositivo.
- Por internet, solo los usuarios de un sistema pueden verlo o manejarlo.
- No compartas tu contraseña. Si crees que alguien la conoce, pide un cambio
  de contraseña.

## 11. Problemas frecuentes

| Qué pasa | Qué hacer |
| --- | --- |
| «Usuario o contraseña incorrectos» | Revisa mayúsculas y minúsculas. Si no activaste la cuenta, hazlo primero (apartado 2) |
| Mi sistema sale «apagado o sin internet» | ¿Está encendido y con internet? Tras encenderlo tarda 1 o 2 minutos. Pulsa **Actualizar** |
| El vivo va a saltos | Por internet llegan unas 4 actualizaciones por segundo; con poca cobertura, menos. Junto a la moto, usa su wifi (apartado 8) |
| No veo una sesión que grabé | Se sube al pulsar **Parar grabación** y cuando el sistema tiene internet. Mira en **Sesiones guardadas en el sistema** si pone «sin subir» |
| La app muestra algo antiguo | Cierra y vuelve a abrir la app, o recarga la página |
| La web del sistema pide «Entra con un usuario de …» | Es normal: pulsa **Entrar** con tu usuario |
