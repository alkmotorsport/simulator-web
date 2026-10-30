"""
Pulsador de vuelta y cambio de pagina.

  pulsacion corta           = pagina siguiente (al soltar)
  pulsacion larga (>= 1 s)  = vuelta (al cumplirse el segundo, sin soltar)
  en la pagina SISTEMA:
    mantenido 3 s           = empieza a grabar, o para si ya grababa ('grabar_s';
                              ahi la pulsacion de 1 s no marca vuelta)
  mantenido 10 s            = para la grabacion y apaga la raspi ('apagar_s';
                              la pantalla avisa desde los 3 s, en SISTEMA desde los 5)

CSV (solo cuando hay pulsaciones): t_s, pulsaciones, vuelta, t_vuelta_s
  pulsaciones 1 = corta, 3 = larga (vuelta; el 3 es por compatibilidad con
              las sesiones de antes, cuando la vuelta eran 3 pulsaciones)
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
    DEFECTOS = {"gpio": 17, "larga_s": 1.0, "grabar_s": 3.0, "apagar_s": 10.0, "rebote_ms": 20}
    PAGINA_GRABAR = "sistema"     # pagina de la pantalla donde el boton graba

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.vuelta = 0
        self.t_vuelta = None
        self.pagina = 0
        self.t_pulsado = None           # desde cuando esta pulsado (lo mira la pantalla)
        self._cb = None

    def pines(self):
        return f"GPIO{self.cfg['gpio']} (pin 11) · GND (pin 9)"

    def bucle(self):
        import pigpio
        pi, g = self.hw.pi(), self.cfg["gpio"]
        pi.set_mode(g, pigpio.INPUT)
        pi.set_pull_up_down(g, pigpio.PUD_UP)
        pi.set_glitch_filter(g, int(self.cfg["rebote_ms"] * 1000))
        bordes = []                     # (nivel, t): 0 = pulsado, 1 = suelto
        self._cb = pi.callback(g, pigpio.EITHER_EDGE,
                               lambda _g, nivel, _t: bordes.append((nivel, self.reloj())))
        self.estado = "activo"
        pulsado, larga = None, False    # cuando se pulso y si ya conto como larga
        apagado = grabado = False
        while not self.parar.wait(0.02):
            while bordes:
                nivel, t = bordes.pop(0)
                if nivel == 0 and pulsado is None:
                    pulsado, larga, grabado = t, False, False
                elif nivel == 1 and pulsado is not None:
                    if not larga:
                        self._pulsacion(t, 1)
                    pulsado = None
            self.t_pulsado = pulsado
            en_grabar = self._en_pagina_grabar()
            if pulsado is not None and not larga and self.reloj() - pulsado >= self.cfg["larga_s"]:
                larga = True
                if not en_grabar:
                    self._pulsacion(self.reloj(), 3)
            if pulsado is not None and en_grabar and not grabado and \
                    self.reloj() - pulsado >= self.cfg["grabar_s"]:
                grabado = True
                self.bus.grabar_alternar()
            if pulsado is not None and not apagado and self.reloj() - pulsado >= self.cfg["apagar_s"]:
                apagado = True
                self.bus.apagar()

    def _en_pagina_grabar(self):
        pantalla = self.bus.modulos.get("pantalla")
        return pantalla is not None and pantalla.corriendo() and \
            getattr(pantalla, "_pid", None) == self.PAGINA_GRABAR

    def simular(self):
        # una vuelta cada sim.VUELTA_S: pulsacion larga en la linea de meta
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
        else:
            self.pagina += 1
        self.publicar(t, [n, self.vuelta, t_vuelta])
        self.vivo({"vuelta": self.vuelta, "pagina": self.pagina,
                   "t_vuelta_s": t_vuelta})
