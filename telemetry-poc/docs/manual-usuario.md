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
   sin cobertura de internet (ver el apartado 11).

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
- **Configuración** (la caja bajo los botones de Conectar y Grabar): sus
  pestañas están **cerradas** para no ocupar sitio; pulsa una para abrirla y
  otra vez para cerrarla. En **Sesiones** salen solo **Moto** y **Parámetros
  de la sesión**.
  - **Sensores:** lista de lo conectado a la moto. El tick activa o desactiva
    cada sensor; **auto** quiere decir que se activa solo si se detecta
    conectado. Algunos tienen acciones, como **Calibrar** (con la moto quieta).
    - **Acelerómetro/giroscopio (inclinación y cabeceo):** la caja puede ir en cualquier postura
      (tumbada, de lado…), pero **bien sujeta**: si se mueve, los ángulos dejan
      de valer. Pulsa **Calibrar** con la moto **recta y quieta** cada vez que
      cambies la caja de sitio. El sistema también calibra solo al encenderse,
      así que enciéndelo con la moto recta.
  - **Pantalla y luces:** qué hacen las luces, las alertas y qué datos salen
    en la página RESUMEN (apartado 7).
  - **Moto:** la ficha de tu moto (apartado 8).
  - **Parámetros de la sesión:** los ajustes técnicos de cada sensor.
- **⛶ Pantalla completa** (junto a **⚙ Ajustes**): deja solo el logo, el
  título y los bloques de sensores (sin los botones de la cabecera), y pone el
  navegador a pantalla completa (en el iPhone, solo lo de la página).
  **✕ Salir de pantalla completa** (o Esc) lo devuelve todo.
- **Pantalla y luces de la moto:** salen como **bloques** más de la vista en
  vivo, con lo mismo que se ve en la moto en ese momento. Se mueven con **⠿**
  y se ocultan con su casilla, como los sensores.
- **Bloque del acelerómetro/giroscopio:** el **diagrama g-g** sale el primero (ver el
  apartado 9); debajo, inclinación, aceleraciones, cabeceo y **vibración
  vertical**.

## 6. La pantalla y el botón del cuadro

La pantalla muestra **una página por dato**, en grande. Solo salen las páginas
de los sensores que están funcionando: velocidad, suspensión, inclinación,
fuerzas G, temperaturas (bujía, aceite, disco), vuelta, deslizamiento entre
ruedas, resumen y sistema.

- **Pulsación corta:** página siguiente. La pantalla **no cambia sola**: se
  queda en la que elijas.
- **Pulsación larga** (mantén 1 segundo): **marca vuelta** (en la línea de
  meta). La página **VUELTA** enseña el tiempo de la vuelta y la diferencia
  con tu mejor vuelta.
- **Mantenido 10 segundos: apagar.** A los 3 segundos la pantalla cuenta
  atrás («SIGUE PULSANDO… PARA APAGAR»); si sueltas antes, no pasa nada
  (solo queda marcada la vuelta del primer segundo). A los 10 segundos, si
  está grabando, para la grabación («ESPERE · GUARDANDO DATOS») y después
  apaga el sistema («APAGANDO»; las luces en ámbar). Quita la corriente
  cuando el **LED verde de la raspi se apague**: así no se estropea la
  tarjeta.
- **Cabecera:** el nombre de la página y su número (por ejemplo `3/7`). Un
  **punto parpadeando** quiere decir que está **grabando**; un **«!»**, que
  hay una alerta grave reconocida que sigue activa (apartado 7).
- **Si salta una alerta**, la pantalla cambia sola a la página de ese dato
  (apartado 7). Con una pulsación corta la reconoces y vuelves a tu página.
- **FUERZAS G:** el círculo de fricción con el punto actual y su rastro. La
  aceleración lateral sale de la inclinación (la caja mide casi 0 en curva,
  porque la moto se tumba).

## 7. Luces y alertas

Las 3 luces del cuadro son una **extensión de la pantalla**: muestran el dato
de la página que estás viendo. Si cambias de página, las luces cambian con
ella.

- **Modo barra:** una luz por nivel, que se van encendiendo como un
  indicador (por ejemplo, en INCLINACIÓN: verde a partir de 20°, ámbar a
  partir de 30° y rojo a partir de 40°).
- **Modo estado:** las 3 del mismo color según el valor (por ejemplo, en
  TEMP BUJÍA: azul en frío, verde en rango, ámbar si sube, rojo parpadeando
  si es crítica).

**Las alertas mandan sobre todo:** estés en la página que estés, la pantalla
salta a la del dato y las 3 luces avisan.

- **Momentánea** (tope de suspensión, vuelta marcada, mejor vuelta en
  morado): dura unos segundos y vuelve sola a tu página. Si se repite enseguida
  (por ejemplo, topes seguidos en asfalto malo), no vuelve a cambiar la
  pantalla durante un rato: solo destellan las luces.
- **Grave** (bujía, aceite o disco muy calientes, sensor con fallo): se queda
  mientras dure. Con una **pulsación corta** la reconoces: vuelves a tu
  página con un **«!»** en la cabecera. Si sigue activa, vuelve a saltar a los
  2 minutos. Cuando el valor vuelve a lo normal, se quita sola.
- Si saltan varias a la vez, manda la grave y, entre iguales, la que esté más
  arriba en la lista.

**Colores:** rojo, ámbar, verde, azul, morado y blanco. **Efectos:** fijo,
parpadeo lento, parpadeo rápido y destello.

### Cambiar las luces y las alertas

En **En vivo**, abre la pestaña **Pantalla y luces**:

- **Luces por página:** para cada página de la pantalla, el **dato**, el **modo**
  (barra o estado), el color **sin nivel** (normalmente apagadas) y los
  **niveles** (valor, color y efecto). En modo estado manda el primer nivel que
  se cumple, de arriba abajo. Quita el tick de una página para dejar sus
  luces apagadas.
- **Alertas:** nombre, dato, condición, tipo (**momentánea** o **grave**), la
  página que enseña, el color y el efecto. En las momentáneas, cuánto dura y
  cuánto espera antes de repetir; en las graves, cada cuánto recuerda. El
  **margen al soltar** evita que una alerta se encienda y apague sin parar
  justo en el umbral. Con **↑ ↓** cambias la prioridad.
- **Plantillas:** **Recomendada**, **Solo alertas** (luces apagadas en marcha
  normal) o **Todo apagado**, como punto de partida.
- **Página RESUMEN:** qué dato va en cada una de sus 6 casillas (velocidad,
  inclinación, G, frenada, aceleración, suspensión en mm o en %,
  temperaturas, número de vuelta, mejor vuelta o diferencia con la mejor), o
  dejarla vacía.
- **Probar** enciende las luces de la moto un momento con ese color y efecto.
- **Guardar** lo aplica al momento en la moto, sin reiniciar.

Los valores de la plantilla recomendada son **de partida**: ajusta las
temperaturas y los límites a tu moto después de tus primeras sesiones.

## 8. La ficha de tu moto

En **En vivo**, pestaña **Moto**: peso en seco, piloto, depósito, batalla,
altura del centro de masas, recorrido de la suspensión trasera, llantas y
perímetro de la rueda trasera, neumáticos, frenos (tambor o disco), carrocería,
motor y notas. **Todo es opcional** y debajo se ve lo que se deduce (masa en
marcha, límite de stoppie, inclinación máxima teórica…).

- Al **Guardar**, el **perímetro de la rueda** corrige ya la velocidad y la
  distancia del sensor de rueda, y el **recorrido de la suspensión**, el % y el
  tope de la pantalla, las luces y las alertas.
- Cada sesión **guarda una copia** de la ficha al empezar a grabar: si cambias
  algo (otro neumático, otra suspensión), las sesiones antiguas se siguen
  analizando con la moto que eran. En **Sesiones**, la pestaña **Moto** enseña
  la ficha con la que se grabó (sin poder cambiarla).
- **Analizar trazas** usa esa ficha (masa, batalla, agarre del neumático,
  frenos de tambor o de disco, potencia, velocidad máxima…) y dice qué datos
  faltan; lo que falte lo toma de la moto de ejemplo de la formación.
- El **perímetro** se mide fácil: marca el suelo y la rueda, empuja la moto
  una vuelta de rueda y mide la distancia.

## 9. Sesiones

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
  - **Bloque del acelerómetro/giroscopio:**
    - **Diagrama g-g** (círculo de fricción): aceleración lateral en
      horizontal y longitudinal en vertical; más oscuro = más tiempo ahí. Los
      círculos van cada 0,25 g (un neumático de calle da hasta ≈ 1 g). Al
      pasar el dedo o el ratón dice el % de tiempo de cada zona.
    - La **aceleración lateral** sale de la inclinación (tan θ) y la
      **longitudinal** va promediada en 0,5 s, para que la vibración del motor
      no parezca frenadas.
    - **Vibración vertical:** cuánto vibra la caja en cada momento (motor,
      asfalto y golpes). Si es alta todo el rato, revisa cómo va sujeta.
    - **Ángulos recalculados:** las sesiones grabadas antes de la mejora de la
      calibración, con la caja inclinada, se corrigen solas al abrirlas.
    - **Caja movida:** si la caja cambió de postura (se cogió, se soltó o la
      moto se cayó), los datos desde ese momento no se usan y se avisa.
- **Analizar trazas** (arriba, junto a la barra de tiempo): explica lo que se
  ve en el tramo visible (o en toda la sesión) con la teoría de la
  [formación](https://motorsport.amorgante.es): inclinación y radio de las
  curvas, agarre usado (círculo de fricción), frenadas y transferencia de
  carga, temperatura del disco, suspensión… y cruza los sensores entre sí
  (por ejemplo, la frenada del acelerómetro con la de la rueda). Avisa también de
  datos dudosos (caja movida, vibración, huecos). **Ver** lleva a ese momento
  en las gráficas y **Teoría en la formación** abre el capítulo. Si amplías
  otro tramo, pulsa **Analizar el tramo visible**.
- **Editar** (solo en las de la nube): ponle un **nombre** (por ejemplo
  «Jarama · tanda 2») y una **descripción** (reglajes, condiciones de pista…).
  Se ven en la lista y como título al abrirla. Lo guarda tu sistema, así que
  tiene que estar «en línea» para editar.
- **Borrar** (pide confirmación y no se puede deshacer):
  - **De la nube:** lo borra tu sistema, así que tiene que estar «en línea».
    Su copia en el sistema, si la hay, no se borra.
  - **Del sistema:** borra la copia guardada en la moto. Si pone **sin subir**,
    se perderá para siempre. La sesión que se está grabando no se puede borrar.
- Al final de la página puedes abrir **CSV del ordenador** o la **sesión de
  ejemplo**.

## 10. Encender y apagar el sistema

- **Encender:** basta con dar corriente. Durante unos **8 segundos** la
  pantalla enseña el **logo** y las luces hacen una **prueba tipo semáforo**
  (pasadas en rojo, ámbar y verde): en ese tiempo arrancan los sensores y el
  acelerómetro/giroscopio se calibra, así que deja la moto **recta y quieta** hasta que salga la
  primera página. En 1 o 2 minutos sale «en línea» en la app (si tiene
  internet).
- **Apagar:** pide al administrador cómo hacerlo en tu moto. Si se corta la
  corriente mientras graba, la sesión puede quedar **cortada** (se guarda lo
  grabado hasta ese momento).

## 11. La wifi del sistema (punto de acceso del móvil, circuito)

El sistema se conecta solo a las **wifis que tiene guardadas** (la de casa,
el punto de acceso de tu móvil...). Para darle una nueva **no hace falta
ningún cable ni ordenador**:

1. **Si al encender no encuentra ninguna wifi conocida** (en 1 minuto), el
   sistema crea **su propia wifi**: `Telemetria-<moto>`. La pantalla lo dice:
   «CONECTA EL MÓVIL A TELEMETRIA-… · CLAVE …». También se puede pedir con
   la app, en *Configuración → Wifi → Añadir una wifi* (la conexión de ese
   momento se corta).
2. Con el **punto de acceso del móvil apagado**, conecta el móvil a esa wifi
   con la clave de la pantalla. Se abre sola una página (si no, abre
   `http://10.42.0.1` en el navegador).
3. Elige la red o **escribe el nombre exacto de tu punto de acceso** (apagado
   no sale en la lista; en iPhone es el nombre del teléfono) y su clave, y
   pulsa **Guardar y conectar**.
4. Desconéctate de la wifi del sistema y **enciende el punto de acceso**. La
   pantalla dice «BUSCANDO…» y, en cuanto lo encuentra, «CONECTADA A …». Si
   en 2 minutos no lo encuentra (clave mal, punto de acceso apagado), vuelve
   a dar su wifi para repetirlo.

Desde entonces se conecta solo a ese punto de acceso cada vez que esté
encendido: la app, el túnel y la subida a la nube van igual que en casa. Con
una pulsación corta del botón se quita el aviso de wifi de la pantalla; la IP
del sistema sale en la página **SISTEMA**.

**Sin ninguna red** (ni punto de acceso): el sistema da su wifi y puedes
usarlo **junto a la moto**. Conéctate a ella, abre `https://10.42.0.1:8081`,
acepta el aviso del certificado (la primera vez en cada dispositivo) y pulsa
**Entrar** con tu usuario: funciona sin internet. Lo que grabes se sube a la
nube cuando el sistema vuelva a tener internet.

## 12. Contraseña olvidada

Pide al administrador un **link de cambio de contraseña**. Se usa igual que el
de alta (apartado 2).

## 13. Privacidad y seguridad

- Tus sesiones viajan y se guardan **cifradas**. Solo las ven los usuarios de
  tu sistema de telemetría.
- Tu contraseña **no se envía** a ningún sitio ni se guarda: sirve para
  descifrar la clave de tu sistema en tu propio dispositivo.
- Por internet, solo los usuarios de un sistema pueden verlo o manejarlo.
- No compartas tu contraseña. Si crees que alguien la conoce, pide un cambio
  de contraseña.

## 14. Problemas frecuentes

| Qué pasa | Qué hacer |
| --- | --- |
| «Usuario o contraseña incorrectos» | Revisa mayúsculas y minúsculas. Si no activaste la cuenta, hazlo primero (apartado 2) |
| Mi sistema sale «apagado o sin internet» | ¿Está encendido y con internet? Tras encenderlo tarda 1 o 2 minutos. Pulsa **Actualizar** |
| El vivo va a saltos | Por internet llegan unas 4 actualizaciones por segundo; con poca cobertura, menos. Junto a la moto, usa su wifi (apartado 11) |
| No veo una sesión que grabé | Se sube al pulsar **Parar grabación** y cuando el sistema tiene internet. Mira en **Sesiones guardadas en el sistema** si pone «sin subir» |
| La app muestra algo antiguo | Cierra y vuelve a abrir la app, o recarga la página |
| La web del sistema pide «Entra con un usuario de …» | Es normal: pulsa **Entrar** con tu usuario |
| La pantalla ha cambiado sola de página | Ha saltado una alerta (apartado 7). Si es grave, una pulsación corta la reconoce y vuelves a tu página |
| Hay un «!» en la cabecera de la pantalla | Una alerta grave reconocida sigue activa: mira su dato. Volverá a saltar a los 2 minutos si sigue así |
| Las luces no se encienden | Activa la tira en la pestaña **Sensores**. En una página sin luces configuradas (o con el dato por debajo del primer nivel) es normal que estén apagadas. Pulsa **Probar** en la pestaña **Pantalla y luces** para comprobarlas |
| La velocidad no cuadra con el velocímetro | Mide el perímetro de la rueda trasera y ponlo en la pestaña **Moto** |
| La inclinación da valores imposibles | Pulsa **Calibrar** con la moto recta y quieta, y revisa que la caja vaya bien sujeta |
