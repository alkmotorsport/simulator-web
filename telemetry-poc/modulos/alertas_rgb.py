"""
Alertas de suspension en dos LEDs RGB, en modo semaforo.

  RGB1   compresion   verde normal | ambar > comp_ambar | rojo parpadeo > comp_rojo
  RGB2   oscilacion   verde estable | ambar oscilacion | rojo parpadeo oscilacion fuerte
  Ambos en azul: calibrando (fijo) o sensor sin eco (parpadeo).
La web replica el semaforo aunque no haya LEDs conectados.

Lee la suspension del modulo 'fuente' (rel_mm). Si las luces resultan ser
WS2812, iran en la cadena de la tira; esto es para LED RGB de 4 pines
(3 GPIO con su resistencia cada uno).

Deteccion de oscilacion: paso alto (media exponencial) sobre la compresion;
se cuentan cruces por cero con histeresis y se mide la amplitud de cada medio
ciclo. Es alerta si los ultimos osc_ciclos ciclos tienen todos su periodo
dentro de [osc_fmin, osc_fmax] y la amplitud supera el umbral. Un bache
aislado (1 ciclo amortiguado) no salta; un rebote mal amortiguado o un bombeo
sostenido, si. Con el HC-SR04 a ~40 Hz solo se ven oscilaciones hasta ~16 Hz.
"""

import math
import statistics
import time
import types
from collections import deque

from .base import Modulo

NIVEL_COLOR = ("verde", "ambar", "rojo")


def lista_pines(txt):
    pines = [int(p) for p in str(txt).split(",")]
    if len(pines) != 3:
        raise ValueError("hacen falta 3 pines R,G,B")
    return pines


class RGB:
    """LED RGB de 3 pines, todo/nada por canal (ambar = rojo + verde)."""
    MEZCLA = {"off": (0, 0, 0), "verde": (0, 1, 0), "ambar": (1, 1, 0),
              "rojo": (1, 0, 0), "azul": (0, 0, 1)}

    def __init__(self, pi, pines, activo_bajo):
        import pigpio
        for p in pines:
            pi.set_mode(p, pigpio.OUTPUT)
        self.pi, self.pines, self.activo_bajo, self.actual = pi, pines, activo_bajo, None
        self.poner("off")

    def poner(self, color):
        if color == self.actual:
            return
        for p, on in zip(self.pines, self.MEZCLA[color]):
            self.pi.write(p, int(bool(on) != self.activo_bajo))
        self.actual = color

    def cerrar(self):
        self.poner("off")


class Detector:
    """Calcula niveles instantaneos (0 verde, 1 ambar, 2 rojo) por muestra."""

    def __init__(self, a, rate_hz):
        self.a = a
        self.signo = -1 if a.montaje == "acerca" else 1
        nyq = 0.4 * rate_hz
        self.fmax = min(a.osc_fmax, nyq)
        self.fmin = min(a.osc_fmin, self.fmax * 0.8)
        # Paso alto a fmin/2 para quitar transferencias de carga y frenadas;
        # el ruido lo filtra la histeresis (un paso bajo a 40 Hz se comeria
        # la propia oscilacion).
        self.tau_lento = 1 / (2 * math.pi * self.fmin / 2)
        self.ventana = (a.osc_ciclos + 1) / self.fmin
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

    def niveles(self, t):
        a = self.a
        c = self.comp
        nc = 0 if not c == c else 2 if c >= a.comp_rojo else 1 if c >= a.comp_ambar else 0
        no = 2 if self.osc_amp >= a.osc_rojo else 1 if self.osc_amp >= a.osc_ambar else 0
        recientes = [ok for tt, ok in self.ecos if t - tt <= 1.0]
        perdidas = sum(1 for ok in recientes if not ok)
        sensor_ok = len(recientes) >= 5 and perdidas / len(recientes) < 0.3
        return nc, no, sensor_ok


class AlertasRGB(Modulo):
    TIPO = "alertas_rgb"
    NOMBRE = "Alertas de suspension (2 LED RGB)"
    CLASE = "salida"
    COLS = []
    DETECTABLE = False
    DEFECTOS = {
        "fuente": "suspension",
        "rgb1": "5,6,13",          # pines 29, 31, 33 (libres en el esquema)
        "rgb2": "16,20,21",        # pines 36, 38, 40
        "activo_bajo": True,       # anodo comun
        "comp_ambar": 30.0,        # mm de compresion sobre la referencia
        "comp_rojo": 45.0,
        "osc_fmin": 3.0, "osc_fmax": 15.0, "osc_ciclos": 3,
        "osc_ambar": 3.0, "osc_rojo": 6.0, "osc_histeresis": 1.5,
    }
    ACCIONES = {"probar": "Probar colores"}
    HOLD = (0.0, 0.3, 1.0)    # s que se mantiene ambar / rojo para que se vea

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.leds = []
        self._probar = False

    def pines(self):
        return f"RGB1 GPIO {self.cfg['rgb1']} · RGB2 GPIO {self.cfg['rgb2']}"

    def meta(self):
        m = super().meta()
        m["comp_ambar_mm"] = self.cfg["comp_ambar"]
        m["comp_rojo_mm"] = self.cfg["comp_rojo"]
        return m

    def accion(self, nombre):
        if nombre != "probar":
            return super().accion(nombre)
        self._probar = True
        return "recorriendo colores"

    def bucle(self):
        pi = self.hw.pi()
        self.leds = [RGB(pi, lista_pines(self.cfg[k]), self.cfg["activo_bajo"])
                     for k in ("rgb1", "rgb2")]
        self._correr_alertas()

    def simular(self):
        self.leds = []       # solo la web
        self._correr_alertas()

    def liberar(self):
        for l in self.leds:
            l.cerrar()
        self.leds = []

    # ------------------------------------------------------------------------

    def _correr_alertas(self):
        fuente = self.bus.modulo(self.cfg["fuente"])
        params = dict(self.cfg, montaje=fuente.cfg.get("montaje", "acerca"))
        rate = 1000.0 / fuente.cfg.get("periodo_ms", 25.0)
        det = Detector(types.SimpleNamespace(**params), rate)
        cola = deque()
        self.escuchar(fuente.id, "rel_mm", lambda t, v: cola.append((t, v)))
        hasta = {"comp": [0, 0, 0], "osc": [0, 0, 0]}
        self.estado = "activo"
        self._autotest()
        while not self.parar.is_set():
            if self._probar:
                self._probar = False
                self._autotest(completo=True)
            while cola:
                det.muestra(*cola.popleft())
            self._actualizar(det, fuente, hasta, time.monotonic())
            self.parar.wait(0.04)          # ~25 Hz de refresco

    def _autotest(self, completo=False):
        """Barrido rojo -> ambar -> verde al arrancar, como un cuadro de mandos."""
        pasos = [(c, c) for c in ("rojo", "ambar", "verde")]
        if completo:
            pasos += [("azul", "azul"), ("rojo", "off"), ("off", "rojo")]
        for c1, c2 in pasos:
            self._pintar(c1, c2)
            self.vivo({"modo": "prueba", "color_comp": c1, "color_osc": c2})
            if self.parar.wait(0.25 if not completo else 0.8):
                return

    def _nivel_mostrado(self, hasta, clave, nivel, ahora):
        h = hasta[clave]
        if nivel:
            h[nivel] = max(h[nivel], ahora + self.HOLD[nivel])
        return max([n for n in (2, 1) if h[n] > ahora] or [0])

    def _actualizar(self, det, fuente, hasta, ahora):
        parpadeo = int(ahora * 4) % 2 == 0
        if not fuente.corriendo():
            self._pintar("off", "off")
            self.vivo({"modo": "sin_fuente"})
            return
        if fuente.estado == "calibrando":
            self._pintar("azul", "azul")
            self.vivo({"modo": "calibrando"})
            return

        nc, no, sensor_ok = det.niveles(self.reloj())
        vc = self._nivel_mostrado(hasta, "comp", nc, ahora)
        vo = self._nivel_mostrado(hasta, "osc", no, ahora)
        col_c, col_o = NIVEL_COLOR[vc], NIVEL_COLOR[vo]
        self.vivo({"modo": "activo", "sensor_ok": sensor_ok,
                   "comp": round(det.comp, 1) if det.comp == det.comp else None,
                   "nivel_comp": vc, "nivel_osc": vo,
                   "color_comp": col_c, "color_osc": col_o,
                   "osc_amp": round(det.osc_amp, 1), "osc_hz": round(det.osc_hz, 1)})
        if not sensor_ok:
            c = "azul" if parpadeo else "off"
            self._pintar(c, c)
        else:
            self._pintar("off" if vc == 2 and not parpadeo else col_c,
                         "off" if vo == 2 and not parpadeo else col_o)

    def _pintar(self, c1, c2):
        try:
            for led, c in zip(self.leds, (c1, c2)):
                led.poner(c)
        except Exception as e:   # un LED nunca debe tirar la captura
            self.aviso = f"LEDs: {e}"
            self.leds = []
