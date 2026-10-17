"""
Pulsador de vuelta y cambio de pagina.

  1 pulsacion  = pagina siguiente
  2 seguidas   = pagina anterior
  3 seguidas   = vuelta

CSV (solo cuando hay pulsaciones): t_s, pulsaciones, vuelta, t_vuelta_s
  vuelta      numero de vuelta tras la pulsacion (0 = antes de la primera)
  t_vuelta_s  duracion de la vuelta que acaba de cerrarse

Conexion: GPIO17 (pin 11) y GND (pin 9), sin resistencias (pull-up interno).
No hay forma de saber si esta conectado: se activa a mano.
"""

from .base import Modulo
from . import sim


class Boton(Modulo):
    TIPO = "boton"
    NOMBRE = "Pulsador de vuelta"
    COLS = ["t_s", "pulsaciones", "vuelta", "t_vuelta_s"]
    DETECTABLE = False
    DEFECTOS = {"gpio": 17, "ventana_s": 0.6, "rebote_ms": 20}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.vuelta = 0
        self.t_vuelta = None
        self.pagina = 0
        self._cb = None

    def pines(self):
        return f"GPIO{self.cfg['gpio']} (pin 11) · GND (pin 9)"

    def bucle(self):
        import pigpio
        pi, g = self.hw.pi(), self.cfg["gpio"]
        pi.set_mode(g, pigpio.INPUT)
        pi.set_pull_up_down(g, pigpio.PUD_UP)
        pi.set_glitch_filter(g, int(self.cfg["rebote_ms"] * 1000))
        pulsos = []
        self._cb = pi.callback(g, pigpio.FALLING_EDGE,
                               lambda *_: pulsos.append(self.reloj()))
        self.estado = "activo"
        while not self.parar.wait(0.05):
            if pulsos and self.reloj() - pulsos[-1] > self.cfg["ventana_s"]:
                n = len(pulsos)
                del pulsos[:n]
                self._pulsacion(self.reloj(), n)

    def simular(self):
        # una vuelta cada sim.VUELTA_S: 3 pulsaciones en la linea de meta
        self.estado = "activo"
        vista = sim.pista(self.reloj())["vuelta"]
        while not self.parar.wait(0.1):
            v = sim.pista(self.reloj())["vuelta"]
            if v != vista:
                vista = v
                self._pulsacion(self.reloj(), 3)

    def liberar(self):
        if self._cb is not None:
            self._cb.cancel()
            self.hw.pi().set_glitch_filter(self.cfg["gpio"], 0)
            self._cb = None

    def _pulsacion(self, t, n):
        t_vuelta = None
        if n >= 3:
            if self.t_vuelta is not None:
                t_vuelta = round(t - self.t_vuelta, 3)
            self.t_vuelta = t
            self.vuelta += 1
        elif n == 2:
            self.pagina -= 1
        else:
            self.pagina += 1
        self.publicar(t, [n, self.vuelta, t_vuelta])
        self.vivo({"vuelta": self.vuelta, "pagina": self.pagina,
                   "t_vuelta_s": t_vuelta})
