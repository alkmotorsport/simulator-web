"""
MLX90614 (GY-906): temperatura sin contacto por infrarrojos (I2C 0x5A).

CSV: t_s, obj_c, amb_c
  obj_c  temperatura del punto al que apunta (disco, neumatico, escape...)
  amb_c  temperatura del propio sensor

Conexion: los mismos 4 pines I2C que el MPU6050, a 3,3 V.
El metal brillante da lecturas bajas: pinta de negro mate el punto apuntado.
"""

import random

from .base import Modulo, pc
from . import sim

RAM_AMB = 0x06
RAM_OBJ = 0x07


def _a_celsius(raw):
    return raw * 0.02 - 273.15


class _MLX:
    def __init__(self, hw, addr):
        self.hw, self.addr = hw, addr

    def leer(self):
        bus = self.hw.i2c()
        with self.hw.lock_i2c:
            obj = bus.read_word_data(self.addr, RAM_OBJ)
            amb = bus.read_word_data(self.addr, RAM_AMB)
        if obj & 0x8000:            # bit de error del MLX
            return None, _a_celsius(amb)
        return _a_celsius(obj), _a_celsius(amb)


class _MLXSim:
    """Disco de freno: se calienta en cada frenada y se enfria en recta."""

    def __init__(self, modulo):
        self.m = modulo
        self.temp = 40.0
        self.t_prev = None

    def leer(self):
        t = self.m.reloj()
        dt = 0.1 if self.t_prev is None else t - self.t_prev
        self.t_prev = t
        p = sim.pista(t)
        self.temp += (25 * p["frenada"] * p["kmh"] / 100.0 - (self.temp - 30) * 0.03) * dt
        return self.temp + random.gauss(0, 0.3), 28 + random.gauss(0, 0.05)


class Infrarrojos(Modulo):
    TIPO = "infrarrojos"
    NOMBRE = "Temperatura IR (MLX90614)"
    COLS = ["t_s", "obj_c", "amb_c"]
    DEFECTOS = {"direccion": 0x5A, "hz": 10.0, "apunta_a": "disco de freno"}

    def pines(self):
        return f"I2C 0x{self.cfg['direccion']:02X} · SDA pin 3 · SCL pin 5"

    def meta(self):
        m = super().meta()
        m["direccion"] = f"0x{self.cfg['direccion']:02X}"
        return m

    def detectar(self):
        addr = self.cfg["direccion"]
        if not self.hw.i2c_presente(addr):
            return ("no", f"nada en I2C 0x{addr:02X}")
        obj, amb = _MLX(self.hw, addr).leer()
        if not -40 <= amb <= 125:
            return ("no", f"responde en 0x{addr:02X} pero no parece un MLX90614")
        return ("si", f"ambiente {amb:.1f} C")

    def bucle(self):
        self._medir(_MLX(self.hw, self.cfg["direccion"]))

    def simular(self):
        self._medir(_MLXSim(self))

    def _medir(self, dev):
        periodo = 1.0 / self.cfg["hz"]
        self.estado = "activo"
        proximo = pc()
        while not self.parar.is_set():
            proximo = self.esperar_periodo(proximo, periodo)
            if self.parar.is_set():
                break
            try:
                obj, amb = dev.leer()
            except (OSError, IOError):
                obj = amb = None
            t = self.reloj()
            if obj is None:
                self.publicar(t, [None, None if amb is None else round(amb, 2)],
                              perdida=True)
            else:
                self.publicar(t, [round(obj, 2), round(amb, 2)])
