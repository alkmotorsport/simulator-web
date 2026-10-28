"""
Velocidad de rueda con sensor Hall KY-003 (A3144) e iman(es) en la rueda.

CSV (a 'hz' fijos): t_s, pulsos, periodo_ms, rpm, kmh, dist_m
  pulsos      acumulados desde que arranco el modulo
  periodo_ms  tiempo entre los dos ultimos pulsos
  kmh         0 si no llega ningun pulso en 'timeout_s'

Modulo HW-477 / KY-003 (trae LED y resistencia: S da 4,6 V sin iman).
Conexion: + a 5 V (pin 2), - a GND (pin 14) y S a GPIO27 (trasera, pin 13) o
GPIO22 (delantera, pin 15) por un divisor junto a la Pi: 10 kOhm en serie y
22 kOhm del GPIO a GND (~3,15 V sin iman). GPIO sin pull-up ni pull-down.
El A3144 baja la senal a 0 V al pasar el iman (flanco de bajada).

Autodeteccion: con el pull-down interno activado un momento, la senal en
reposo solo se lee alta si el modulo esta alimentado y conectado.

Sensor A3144 suelto (3 patas, sin placa): "conexion": "directo". Pata 1 a
5 V, pata 2 a GND y pata 3 (salida) directa al GPIO, sin resistencias: la
salida es de colector abierto (solo lleva la senal a GND, nunca da 5 V) y el
pull-up interno de la Pi la sube a 3,3 V. Asi no se puede autodetectar
(sin iman se lee alto aunque el sensor no este): se activa a mano.
"""

import collections
import random

from .base import Modulo, pc
from . import sim


class _HallPigpio:
    def __init__(self, pi, gpio, directo=False):
        import pigpio
        self.pigpio, self.pi = pigpio, pi
        pi.set_mode(gpio, pigpio.INPUT)
        # modulo: nivel fijado por el divisor; directo: colector abierto + pull-up
        pi.set_pull_up_down(gpio, pigpio.PUD_UP if directo else pigpio.PUD_OFF)
        pi.set_glitch_filter(gpio, 100)              # ignora pulsos < 100 us
        self.gpio = gpio
        self.ticks = collections.deque(maxlen=2)
        self.pulsos = 0
        self.cb = pi.callback(gpio, pigpio.FALLING_EDGE, self._flanco)

    def _flanco(self, gpio, nivel, tick):
        self.ticks.append(tick)
        self.pulsos += 1

    def estado(self):
        """(pulsos, periodo en s o None, s desde el ultimo pulso o None)."""
        ticks = list(self.ticks)
        if not ticks:
            return self.pulsos, None, None
        ahora = self.pi.get_current_tick()
        hace = self.pigpio.tickDiff(ticks[-1], ahora) / 1e6
        per = self.pigpio.tickDiff(ticks[0], ticks[1]) / 1e6 if len(ticks) == 2 else None
        return self.pulsos, per, hace

    def cerrar(self):
        self.cb.cancel()
        self.pi.set_glitch_filter(self.gpio, 0)


class _HallSim:
    def __init__(self, modulo):
        self.m = modulo
        self.pulsos = 0
        self.fase = 0.0
        self.t_prev = None
        self.per = None
        self.t_ult = None

    def estado(self):
        c = self.m.cfg
        t = self.m.reloj()
        p = sim.pista(t)
        kmh = p["kmh"] * (1 + c["sim_desliz"] * max(0.0, p["acel_g"]))
        if self.t_prev is not None:
            self.fase += kmh / 3.6 * (t - self.t_prev) / c["perimetro_m"] * c["imanes"]
            while self.fase >= 1:
                self.fase -= 1
                self.pulsos += 1
                self.t_ult = t
                self.per = c["perimetro_m"] / c["imanes"] / max(kmh / 3.6, 0.1) \
                    * (1 + random.gauss(0, 0.002))
        self.t_prev = t
        return self.pulsos, self.per, None if self.t_ult is None else t - self.t_ult

    def cerrar(self):
        pass


class Rueda(Modulo):
    TIPO = "rueda"
    NOMBRE = "Velocidad de rueda (Hall)"
    COLS = ["t_s", "pulsos", "periodo_ms", "rpm", "kmh", "dist_m"]
    DEFECTOS = {
        "gpio": 27,
        "conexion": "modulo",    # modulo (KY-003 + divisor) | directo (A3144 suelto)
        "imanes": 1,             # imanes por vuelta de rueda
        "perimetro_m": 1.95,     # calibrar: distancia recorrida en una vuelta
        "hz": 20.0,
        "timeout_s": 2.0,        # sin pulsos en este tiempo = parada
        "sim_desliz": 0.0,       # solo --sim: deslizamiento al acelerar
    }

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._dev = None

    def pines(self):
        fis = {27: 13, 22: 15}.get(self.cfg["gpio"])
        return f"GPIO{self.cfg['gpio']}" + (f" (pin {fis})" if fis else "") + \
            (" · directo, pull-up interno" if self._directo() else " · divisor 10k + 22k")

    def _directo(self):
        return self.cfg.get("conexion") == "directo"

    def meta(self):
        return {k: v for k, v in super().meta().items() if not k.startswith("sim_")}

    def detectar(self):
        import pigpio
        pi, g = self.hw.pi(), self.cfg["gpio"]
        if self._directo():
            return ("manual", "sensor directo: sin autodeteccion (pasa un iman para probarlo)")
        pi.set_mode(g, pigpio.INPUT)
        pi.set_pull_up_down(g, pigpio.PUD_DOWN)
        try:
            pi.read(g)
            nivel = sum(pi.read(g) for _ in range(5))
        finally:
            pi.set_pull_up_down(g, pigpio.PUD_OFF)
        if nivel == 5:
            return ("si", "senal alta en reposo: modulo conectado")
        if nivel == 0:
            return ("no", f"GPIO{g} a 0: modulo sin alimentar o sin conectar "
                          "(o el iman justo delante)")
        return ("no", f"GPIO{g} inestable: revisa el cableado")

    def bucle(self):
        self._medir(_HallPigpio(self.hw.pi(), self.cfg["gpio"], self._directo()))

    def simular(self):
        self._medir(_HallSim(self))

    def liberar(self):
        if self._dev is not None:
            self._dev.cerrar()
            self._dev = None

    def _medir(self, dev):
        self._dev = dev
        c = self.cfg
        avance = c["perimetro_m"] / c["imanes"]      # m por pulso
        periodo = 1.0 / c["hz"]
        self.estado = "activo"
        proximo = pc()
        while not self.parar.is_set():
            proximo = self.esperar_periodo(proximo, periodo)
            if self.parar.is_set():
                break
            pulsos, per, hace = dev.estado()
            t = self.reloj()
            # parada si no llegan pulsos (o tardan mucho mas que el ultimo periodo)
            if per is None or hace is None or hace > max(c["timeout_s"], 1.5 * per):
                rpm = kmh = 0.0
            else:
                rpm = 60.0 / per / c["imanes"]
                kmh = avance / per * 3.6
            self.publicar(t, [pulsos, None if per is None else round(per * 1000, 2),
                              round(rpm, 1), round(kmh, 2), round(pulsos * avance, 2)])
