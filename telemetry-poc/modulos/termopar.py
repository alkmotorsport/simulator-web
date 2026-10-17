"""
Sonda K con MAX6675 por SPI (bujia en CE0, aceite en CE1).

CSV: t_s, temp_c   (vacio si la sonda esta abierta / desconectada)

Conexion: 3,3 V (pin 17), GND (pin 25), SO (pin 21), SCK (pin 23) y CS pin 24
(CE0) o pin 26 (CE1). Los dos modulos comparten SO y SCK.
Hace falta el SPI activado: sudo raspi-config nonint do_spi 0 (y reiniciar).

El MAX6675 convierte en ~220 ms: se lee a 4 Hz como mucho.
Formato de la lectura (16 bits): D15 siempre 0, D14..D3 temperatura en pasos
de 0,25 C, D2 = 1 si el termopar esta abierto, D1 siempre 0.
"""

import os
import random

from .base import Modulo, pc
from . import sim


class _MAX6675:
    def __init__(self, ce):
        try:
            import spidev
        except ImportError:
            raise RuntimeError("falta spidev (sudo apt install python3-spidev)")
        if not os.path.exists(f"/dev/spidev0.{ce}"):
            raise RuntimeError("SPI desactivado (sudo raspi-config nonint do_spi 0 y reinicia)")
        self.spi = spidev.SpiDev()
        self.spi.open(0, ce)
        self.spi.max_speed_hz = 1000000
        self.spi.mode = 0

    def crudo(self):
        b = self.spi.readbytes(2)
        return (b[0] << 8) | b[1]

    def leer(self):
        """Grados C, o None si el termopar esta abierto."""
        r = self.crudo()
        if r & 0x4:
            return None
        return (r >> 3) * 0.25

    def cerrar(self):
        self.spi.close()


class _MAX6675Sim:
    """Calentamiento con la rodadura: sube hacia una temperatura de regimen."""

    def __init__(self, modulo):
        self.m = modulo
        self.temp = None

    def leer(self):
        c = self.m.cfg
        p = sim.pista(self.m.reloj())
        objetivo = c["sim_base"] + c["sim_rango"] * (p["kmh"] / 160.0)
        if self.temp is None:
            self.temp = c["sim_base"] * 0.6
        self.temp += (objetivo - self.temp) * 0.25 / c["sim_tau"]
        return round((self.temp + random.gauss(0, 0.4)) * 4) / 4

    def cerrar(self):
        pass


class Termopar(Modulo):
    TIPO = "termopar"
    NOMBRE = "Sonda K (MAX6675)"
    COLS = ["t_s", "temp_c"]
    DEFECTOS = {
        "ce": 0, "hz": 4.0,
        # solo para --sim
        "sim_base": 150.0, "sim_rango": 40.0, "sim_tau": 60.0,
    }

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._dev = None

    def pines(self):
        pin = {0: 24, 1: 26}.get(self.cfg["ce"], "?")
        return f"SPI CE{self.cfg['ce']} (pin {pin}) · SO pin 21 · SCK pin 23"

    def meta(self):
        return {k: v for k, v in super().meta().items() if not k.startswith("sim_")}

    def detectar(self):
        dev = _MAX6675(self.cfg["ce"])
        try:
            r = dev.crudo()
        finally:
            dev.cerrar()
        # sin modulo, SO queda flotando: todo ceros o todo unos
        if r in (0x0000, 0xFFFF) or r & 0x8002:
            return ("no", f"sin respuesta en CE{self.cfg['ce']} (0x{r:04X})")
        if r & 0x4:
            return ("si", "modulo presente, pero la sonda esta abierta")
        return ("si", f"{(r >> 3) * 0.25:.1f} C")

    def bucle(self):
        self._medir(_MAX6675(self.cfg["ce"]))

    def simular(self):
        self._medir(_MAX6675Sim(self))

    def liberar(self):
        if self._dev is not None:
            self._dev.cerrar()
            self._dev = None

    def _medir(self, dev):
        self._dev = dev
        periodo = 1.0 / min(self.cfg["hz"], 4.5)
        self.estado = "activo"
        proximo = pc()
        while not self.parar.is_set():
            proximo = self.esperar_periodo(proximo, periodo)
            if self.parar.is_set():
                break
            temp = dev.leer()
            t = self.reloj()
            if temp is None:
                self.aviso = "sonda abierta o desconectada"
                self.publicar(t, [None], perdida=True)
            else:
                self.aviso = None
                self.publicar(t, [temp])
