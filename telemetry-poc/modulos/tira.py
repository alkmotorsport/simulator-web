"""
Cadena de LEDs WS2812 del cuadro: barra proporcional a un valor de otro
modulo (por defecto la velocidad de la rueda trasera; con un sensor de RPM
del motor, sirve de shift light cambiando 'fuente' y 'campo').

Patron (tipo cuadro de carreras):
  valor < inicio        apagado
  inicio .. cambio      se llena: 1/2 verde, 3/4 ambar, ultimo cuarto rojo
  valor >= cambio       toda la tira parpadea en azul (aviso)
  valor >= limite       toda la tira parpadea rapido en rojo
patron "centro": se llena desde los dos extremos hacia el centro.
Al arrancar, mientras la pantalla ensena el logo ('arranque_s'), prueba los
LEDs como un semaforo: 3 pasadas de rojo, de ambar y de verde recorriendo la tira.
La web replica la tira aunque no haya LEDs conectados.

Conexion: 5 V (pin 4), GND (pin 20), datos GPIO18 (pin 12) con 330 Ohm en
serie. Necesita sudo, rpi_ws281x y el audio analogico desactivado
(dtparam=audio=off en /boot/config.txt). No se puede autodetectar.
"""

import math
import time

from .base import Modulo
from .pantalla import esperar_seguro

ZONAS = ((0.5, "verde"), (0.75, "ambar"), (1.0, "rojo"))   # fraccion de la tira


class Tira:
    """Tira WS2812 (rpi_ws281x; necesita sudo)."""
    RGB = {"off": (0, 0, 0), "verde": (0, 255, 0), "ambar": (255, 120, 0),
           "rojo": (255, 0, 0), "azul": (0, 60, 255)}

    def __init__(self, n, pin, brillo):
        try:
            from rpi_ws281x import Color, PixelStrip
        except ImportError:
            raise RuntimeError("falta rpi_ws281x (sudo pip3 install rpi_ws281x)")
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


def colores(c, valor, en_cambio, ahora):
    """Lista de colores de la tira para un valor; devuelve (colores, en_cambio)."""
    n = int(c["num"])
    # histeresis para que no tiemble justo en el punto de cambio
    if valor >= c["cambio"]:
        en_cambio = True
    elif valor < c["cambio"] - c["histeresis"]:
        en_cambio = False
    if valor >= c["limite"]:
        return ["rojo" if int(ahora * 10) % 2 == 0 else "off"] * n, en_cambio
    if en_cambio:
        return ["azul" if int(ahora * 6) % 2 == 0 else "off"] * n, en_cambio
    frac = (valor - c["inicio"]) / (c["cambio"] - c["inicio"])
    if frac <= 0:
        return ["off"] * n, en_cambio

    def zona(f):
        return next(col for lim, col in ZONAS if f <= lim + 1e-9)

    if c["patron"] == "centro":
        mitad = math.ceil(n / 2)
        k = min(mitad, math.ceil(frac * mitad))
        out = ["off"] * n
        for i in range(k):
            out[i] = out[n - 1 - i] = zona((i + 1) / mitad)
        return out, en_cambio
    k = min(n, math.ceil(frac * n))
    return [zona((i + 1) / n) if i < k else "off" for i in range(n)], en_cambio


class TiraLeds(Modulo):
    TIPO = "tira"
    NOMBRE = "Barra de LEDs WS2812"
    CLASE = "salida"
    COLS = []
    DETECTABLE = False
    DEFECTOS = {
        "fuente": "rueda_tras", "campo": "kmh", "unidad": "km/h",
        "inicio": 30.0, "cambio": 140.0, "limite": 170.0, "histeresis": 3.0,
        "patron": "lineal",        # lineal | centro
        "gpio": 18, "num": 12, "brillo": 80,
        "arranque_s": 8.0,         # prueba de LEDs al arrancar (como el logo; 0 = no)
    }
    ACCIONES = {"probar": "Barrido de prueba"}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.tira = None
        self._probar = False

    def pines(self):
        return f"datos GPIO{self.cfg['gpio']} (pin 12) · {self.cfg['num']} LEDs"

    def accion(self, nombre):
        if nombre != "probar":
            return super().accion(nombre)
        self._probar = True
        return "barrido de prueba"

    def bucle(self):
        c = self.cfg
        if not c["inicio"] < c["cambio"] <= c["limite"]:
            raise ValueError("hace falta inicio < cambio <= limite")
        self.tira = Tira(int(c["num"]), int(c["gpio"]), int(c["brillo"]))
        self._ejecutar()

    def simular(self):
        self._ejecutar()

    def liberar(self):
        if self.tira is not None:
            self.tira.cerrar()
            self.tira = None

    def _ejecutar(self):
        c = self.cfg
        ultimo = [None, -1e9]          # valor, t
        self.escuchar(c["fuente"], c["campo"],
                      lambda t, v: ultimo.__setitem__(slice(0, 2), [v, t]))
        en_cambio = False
        self.estado = "activo"
        self._arranque()
        while not self.parar.wait(0.02):
            ahora = time.monotonic()
            if self._probar:
                self._probar = False
                self._barrido()
                continue
            valor, t = ultimo
            if valor is None or self.reloj() - t > 1.0:
                cols, valor = ["off"] * int(c["num"]), None
            else:
                cols, en_cambio = colores(c, valor, en_cambio, ahora)
            self._mostrar(cols, valor)

    def _arranque(self):
        """Semaforo: 3 pasadas de cada color, un LED encendido que recorre la tira."""
        n, dur = int(self.cfg["num"]), float(self.cfg["arranque_s"])
        pasos = [(col, i) for col in ("rojo", "ambar", "verde") for _ in range(3) for i in range(n + 1)]
        dt = dur / len(pasos) if dur > 0 else 0
        for col, i in pasos if dt else []:
            if self.parar.is_set():
                return
            self._mostrar([col if j == i else "off" for j in range(n)], None)   # i == n: hueco
            esperar_seguro(self.parar, dt)
        self._mostrar(["off"] * n, None)

    def _barrido(self):
        c = self.cfg
        t0 = time.monotonic()
        en_cambio = False
        while not self.parar.is_set() and time.monotonic() - t0 < 4:
            f = (time.monotonic() - t0) / 4
            valor = c["inicio"] + f * 1.1 * (c["limite"] - c["inicio"])
            cols, en_cambio = colores(c, valor, en_cambio, time.monotonic())
            self._mostrar(cols, valor)
            self.parar.wait(0.02)

    def _mostrar(self, cols, valor):
        if self.tira is not None:
            try:
                self.tira.poner(cols)
            except Exception as e:
                self.aviso = f"WS2812: {e}"
                self.tira = None
        self.vivo({"leds": cols, "valor": None if valor is None else round(valor, 1),
                   "unidad": self.cfg["unidad"]})
