#!/usr/bin/env python3
"""
Alertas de suspension en LEDs, en modo semaforo.

  RGB1   compresion   verde normal | ambar > --comp-ambar | rojo parpadeo > --comp-rojo
  RGB2   oscilacion   verde estable | ambar oscilacion | rojo parpadeo oscilacion fuerte
  WS2812 barra de compresion (verde -> ambar -> rojo, como unas luces de cambio);
         toda la tira en ambar/roja parpadeando si hay oscilacion.
  Ambos RGB + tira en azul: calibrando (fijo) o sensor sin eco (parpadeo).

Deteccion de oscilacion: paso alto (media exponencial) sobre la compresion;
se cuentan cruces por cero con histeresis y se mide la amplitud de cada medio
ciclo. Es alerta si los ultimos --osc-ciclos ciclos tienen todos su periodo
dentro de [--osc-fmin, --osc-fmax] y la amplitud supera el umbral. Un bache
aislado (1 ciclo amortiguado) no salta; un rebote mal amortiguado o un bombeo
sostenido, si.

Limite fisico: con el HC-SR04 a ~40 Hz solo se ven oscilaciones hasta ~16 Hz
(Nyquist). El chatter de MotoGP (~17-25 Hz) necesita un potenciometro lineal o
un acelerometro a >= 200 Hz; esta logica sirve igual cambiando la fuente.

Todo corre en un hilo aparte: el bucle de muestreo solo hace push().

Pines por defecto (BCM) del Adeept Motor HAT V2.0: RGB1 22,23,24  RGB2 10,9,25
(anodo comun: activo a nivel bajo)  WS2812 en GPIO12. Compruebalos con:
  sudo python3 telemetry-suspensiones.py --test-leds
"""

import math
import statistics
import threading
import time
from collections import deque

COLORES = ("off", "verde", "ambar", "rojo", "azul")
NIVEL_COLOR = ("verde", "ambar", "rojo")


def lista_pines(txt):
    pines = [int(p) for p in txt.split(",")]
    if len(pines) != 3:
        raise ValueError("hacen falta 3 pines R,G,B")
    return pines


# ------------------------------------------------------------- salidas ---

class RGB:
    """LED RGB de 3 pines, todo/nada por canal (ambar = rojo + verde)."""
    MEZCLA = {"off": (0, 0, 0), "verde": (0, 1, 0), "ambar": (1, 1, 0),
              "rojo": (1, 0, 0), "azul": (0, 0, 1)}

    def __init__(self, pines, activo_bajo):
        import RPi.GPIO as GPIO
        self.G = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in pines:
            GPIO.setup(p, GPIO.OUT)
        self.pines, self.activo_bajo, self.actual = pines, activo_bajo, None
        self.poner("off")

    def poner(self, color):
        if color == self.actual:
            return
        for p, on in zip(self.pines, self.MEZCLA[color]):
            self.G.output(p, bool(on) != self.activo_bajo)
        self.actual = color

    def cerrar(self):
        self.poner("off")


class Tira:
    """Tira WS2812 (rpi_ws281x; necesita sudo)."""
    RGB = {"off": (0, 0, 0), "verde": (0, 255, 0), "ambar": (255, 120, 0),
           "rojo": (255, 0, 0), "azul": (0, 40, 255)}

    def __init__(self, n, pin, brillo):
        from rpi_ws281x import Color, PixelStrip
        canal = 1 if pin in (13, 19, 41, 45, 53) else 0
        self.s = PixelStrip(n, pin, 800000, 10, False, brillo, canal)
        self.s.begin()
        self.color = {k: Color(*v) for k, v in self.RGB.items()}
        self.n, self.actual = n, None
        self.poner(["off"] * n)

    def poner(self, colores):
        if colores == self.actual:
            return
        for i, c in enumerate(colores):
            self.s.setPixelColor(i, self.color[c])
        self.s.show()
        self.actual = list(colores)

    def cerrar(self):
        self.poner(["off"] * self.n)


def crear_salidas(args, avisar=print):
    """RGB1, RGB2 y tira; la que no este disponible queda en None."""
    out = []
    for nombre, txt in (("RGB1", args.rgb1), ("RGB2", args.rgb2)):
        try:
            out.append(RGB(lista_pines(txt), not args.rgb_activo_alto))
        except Exception as e:  # sin RPi.GPIO (portatil) o pines mal
            avisar(f"Aviso: {nombre} no disponible ({e}).")
            out.append(None)
    tira = None
    if args.ws_num > 0:
        try:
            tira = Tira(args.ws_num, args.ws_pin, args.ws_brillo)
        except Exception as e:
            avisar(f"Aviso: WS2812 no disponible ({e}). "
                   "pip install rpi_ws281x y ejecuta con sudo.")
    out.append(tira)
    return out


# ----------------------------------------------------------- deteccion ---

class Detector:
    """Calcula niveles instantaneos (0 verde, 1 ambar, 2 rojo) por muestra."""

    def __init__(self, args, rate_hz):
        self.a = args
        self.signo = -1 if args.montaje == "acerca" else 1
        nyq = 0.4 * rate_hz
        self.fmax = min(args.osc_fmax, nyq)
        if args.osc_fmax > nyq:
            print(f"Aviso: --osc-fmax {args.osc_fmax:g} Hz no se puede ver a "
                  f"{rate_hz:.0f} Hz de muestreo; uso {self.fmax:.1f} Hz.")
        self.fmin = min(args.osc_fmin, self.fmax * 0.8)
        # Paso alto a fmin/2 para quitar transferencias de carga y frenadas;
        # el ruido lo filtra la histeresis (un paso bajo a 40 Hz se comeria
        # la propia oscilacion).
        self.tau_lento = 1 / (2 * math.pi * self.fmin / 2)
        self.ventana = (args.osc_ciclos + 1) / self.fmin
        self.ecos = deque()        # (t, hubo_eco) del ultimo segundo
        self.cruces = deque()      # (t, amplitud del medio ciclo anterior)
        self.t_prev = None
        self.comp = math.nan
        self.osc_amp = self.osc_hz = 0.0
        self._reset(0.0)

    def _reset(self, x):
        self.lento = x
        self.lado = 0
        self.pico = 0.0
        self.cruces.clear()

    def muestra(self, t, rel):
        a = self.a
        self.ecos.append((t, rel is not None))
        while self.ecos and t - self.ecos[0][0] > 1.0:
            self.ecos.popleft()
        if rel is None:
            return
        x = self.signo * rel                      # > 0 = compresion
        if self.t_prev is None or t - self.t_prev > 0.2:
            self._reset(x)
        else:
            dt = t - self.t_prev
            self.lento += (x - self.lento) * dt / (self.tau_lento + dt)
        self.t_prev = t
        self.comp = x

        banda = x - self.lento
        self.pico = max(self.pico, abs(banda))
        h = a.osc_histeresis
        if self.lado >= 0 and banda < -h or self.lado <= 0 and banda > h:
            if self.lado != 0:
                self.cruces.append((t, self.pico))
            self.lado = 1 if banda > 0 else -1
            self.pico = abs(banda)
        while self.cruces and t - self.cruces[0][0] > self.ventana:
            self.cruces.popleft()

        # Oscilacion = los ultimos 'ciclos' ciclos completos, todos con un
        # semiperiodo dentro de la banda, y el ultimo cruce reciente.
        self.osc_amp = self.osc_hz = 0.0
        n_min = 2 * a.osc_ciclos + 1
        cr = self.cruces
        if len(cr) >= n_min and t - cr[-1][0] < 1 / self.fmin:
            ult = list(cr)[-n_min:]
            semis = [b[0] - a_[0] for a_, b in zip(ult, ult[1:])]
            lo, hi = 0.5 / (self.fmax * 1.15), 0.5 / self.fmin
            if all(lo <= s <= hi for s in semis):
                self.osc_hz = 0.5 / statistics.mean(semis)
                self.osc_amp = statistics.median(p for _, p in ult[1:])

    def niveles(self):
        a = self.a
        c = self.comp
        nc = 0 if not c == c else 2 if c >= a.comp_rojo else 1 if c >= a.comp_ambar else 0
        no = 2 if self.osc_amp >= a.osc_rojo else 1 if self.osc_amp >= a.osc_ambar else 0
        perdidas = sum(1 for _, ok in self.ecos if not ok)
        sensor_ok = len(self.ecos) < 5 or perdidas / len(self.ecos) < 0.3
        return nc, no, sensor_ok


# -------------------------------------------------------------- alertas ---

class Alertas(threading.Thread):
    HOLD = (0.0, 0.3, 1.0)    # s que se mantiene ambar / rojo para que se vea

    def __init__(self, args, rate_hz, live=None, salidas=None):
        super().__init__(daemon=True)
        self.a = args
        self.det = Detector(args, rate_hz)
        self.rgb1, self.rgb2, self.tira = salidas or crear_salidas(args)
        self.live = live
        self.cola = deque()
        self.parar = threading.Event()
        self.modo = "calibrando"
        self.hasta = {"comp": [0, 0, 0], "osc": [0, 0, 0]}
        self.estado = {}

    # API desde el bucle de muestreo (deque.append es seguro entre hilos)
    def push(self, t, rel):
        self.cola.append((t, rel))

    def listo(self):
        self.modo = "activo"

    def stop(self):
        self.parar.set()
        self.join(timeout=1)
        for s in (self.rgb1, self.rgb2, self.tira):
            if s:
                s.cerrar()

    def texto(self):
        e = self.estado
        if not e or self.modo != "activo":
            return ""
        if not e["sensor_ok"]:
            return "LED: SIN ECO"
        osc = (f"±{e['osc_amp']:.1f}mm {e['osc_hz']:.0f}Hz"
               if e["nivel_osc"] else "")
        return f"COMP {e['color_comp']:5} OSC {e['color_osc']:5} {osc}"

    def run(self):
        self._autotest()
        while not self.parar.is_set():
            while self.cola:
                self.det.muestra(*self.cola.popleft())
            self._actualizar(time.monotonic())
            self.parar.wait(0.04)          # ~25 Hz de refresco

    def _autotest(self):
        """Barrido rojo -> ambar -> verde al arrancar, como un cuadro de mandos."""
        for c in ("rojo", "ambar", "verde"):
            self._pintar(c, c, [c] * (self.tira.n if self.tira else 0))
            time.sleep(0.25)

    def _nivel_mostrado(self, clave, nivel, ahora):
        h = self.hasta[clave]
        if nivel:
            h[nivel] = max(h[nivel], ahora + self.HOLD[nivel])
        return max([n for n in (2, 1) if h[n] > ahora] or [0])

    def _actualizar(self, ahora):
        parpadeo = int(ahora * 4) % 2 == 0
        n_tira = self.tira.n if self.tira else 0
        if self.modo == "calibrando":
            self._pintar("azul", "azul", ["azul"] * n_tira)
            self.estado = {"modo": "calibrando"}
            self._publicar()
            return

        nc, no, sensor_ok = self.det.niveles()
        vc = self._nivel_mostrado("comp", nc, ahora)
        vo = self._nivel_mostrado("osc", no, ahora)
        col_c, col_o = NIVEL_COLOR[vc], NIVEL_COLOR[vo]
        self.estado = {"modo": "activo", "sensor_ok": sensor_ok,
                       "comp": round(self.det.comp, 1) if self.det.comp == self.det.comp else None,
                       "nivel_comp": vc, "nivel_osc": vo,
                       "color_comp": col_c, "color_osc": col_o,
                       "osc_amp": round(self.det.osc_amp, 1),
                       "osc_hz": round(self.det.osc_hz, 1)}

        if not sensor_ok:
            c = "azul" if parpadeo else "off"
            self._pintar(c, c, [c] * n_tira)
        else:
            led_c = "off" if vc == 2 and not parpadeo else col_c
            led_o = "off" if vo == 2 and not parpadeo else col_o
            if vo:   # la oscilacion manda en la tira
                tira = [led_o] * n_tira
            else:
                tira = self._barra(self.det.comp, n_tira)
            self._pintar(led_c, led_o, tira)
        self._publicar()

    def _barra(self, comp, n):
        """Barra de compresion: LEDs encendidos ~ comp / comp_rojo."""
        a = self.a
        if not n or not comp == comp:
            return ["off"] * n
        # Cuantos LEDs = cuanta compresion; color = mismo nivel que RGB1, para
        # que con pocos LEDs la barra y el semaforo nunca se contradigan.
        llenos = max(1, min(n, math.ceil(comp / a.comp_rojo * n)))
        color = ("rojo" if comp >= a.comp_rojo else
                 "ambar" if comp >= a.comp_ambar else "verde")
        return [color] * llenos + ["off"] * (n - llenos)

    def _pintar(self, c1, c2, tira):
        try:
            if self.rgb1:
                self.rgb1.poner(c1)
            if self.rgb2:
                self.rgb2.poner(c2)
            if self.tira:
                self.tira.poner(tira)
        except Exception as e:   # un LED nunca debe tirar la captura
            print(f"\nAviso LEDs: {e}")
            self.rgb1 = self.rgb2 = self.tira = None

    def _publicar(self):
        if self.live:
            self.live.set_estado(self.estado)


def test_leds(args):
    """Recorre los colores para comprobar cableado y polaridad."""
    rgb1, rgb2, tira = crear_salidas(args)
    n = tira.n if tira else 0
    pasos = [("rojo", "rojo"), ("verde", "verde"), ("azul", "azul"),
             ("ambar", "ambar"), ("rojo", "off"), ("off", "rojo")]
    try:
        for c1, c2 in pasos:
            print(f"RGB1 {c1:6} RGB2 {c2:6} tira {c1}")
            for s, c in ((rgb1, c1), (rgb2, c2)):
                if s:
                    s.poner(c)
            if tira:
                tira.poner([c1] * n)
            time.sleep(1.5)
        if tira:
            print("tira: barra 1..N")
            for k in range(1, n + 1):
                tira.poner(["verde"] * k + ["off"] * (n - k))
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for s in (rgb1, rgb2, tira):
            if s:
                s.cerrar()
    print("Si los colores salen invertidos (encendido = apagado), usa --rgb-activo-alto.")


def anadir_argumentos(p):
    g = p.add_argument_group("LEDs de alerta (--leds)")
    g.add_argument("--leds", action="store_true",
                   help="activar las alertas en LEDs (semaforo)")
    g.add_argument("--test-leds", action="store_true",
                   help="recorrer colores para probar el cableado y salir")
    g.add_argument("--montaje", choices=["acerca", "aleja"], default="acerca",
                   help="al comprimir el objetivo se acerca/aleja del sensor (def. acerca)")
    g.add_argument("--comp-ambar", type=float, default=30.0,
                   help="mm de compresion sobre la referencia para ambar (def. 30)")
    g.add_argument("--comp-rojo", type=float, default=45.0,
                   help="mm de compresion para rojo / cerca de hacer tope (def. 45)")
    g.add_argument("--osc-fmin", type=float, default=3.0,
                   help="Hz minimos de oscilacion vigilada (def. 3)")
    g.add_argument("--osc-fmax", type=float, default=15.0,
                   help="Hz maximos (def. 15; limitado a 0.4 x muestreo)")
    g.add_argument("--osc-ciclos", type=int, default=3,
                   help="ciclos seguidos para considerarlo oscilacion (def. 3)")
    g.add_argument("--osc-ambar", type=float, default=3.0,
                   help="amplitud (mm, pico) de oscilacion para ambar (def. 3)")
    g.add_argument("--osc-rojo", type=float, default=6.0,
                   help="amplitud (mm, pico) de oscilacion para rojo (def. 6)")
    g.add_argument("--osc-histeresis", type=float, default=1.5,
                   help="mm de banda muerta contra el ruido del sensor (def. 1.5)")
    g.add_argument("--rgb1", default="22,23,24", help="pines BCM R,G,B de RGB1")
    g.add_argument("--rgb2", default="10,9,25", help="pines BCM R,G,B de RGB2")
    g.add_argument("--rgb-activo-alto", action="store_true",
                   help="LEDs de catodo comun (por defecto anodo comun)")
    g.add_argument("--ws-pin", type=int, default=12, help="GPIO de la WS2812 (def. 12)")
    g.add_argument("--ws-num", type=int, default=12,
                   help="LEDs WS2812 en total; 0 = sin tira "
                        "(def. 12 = 4 modulos de 3 encadenados)")
    g.add_argument("--ws-brillo", type=int, default=60, help="brillo 0-255 (def. 60)")
