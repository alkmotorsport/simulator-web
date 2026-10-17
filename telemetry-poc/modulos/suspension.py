"""
Suspension trasera con ultrasonidos HC-SR04.

CSV: t_s, echo_us, dist_mm, rel_mm
  echo_us  ancho bruto del pulso de eco (permite recalcular todo despues)
  dist_mm  distancia al objetivo, compensada por temperatura
  rel_mm   dist_mm menos la referencia medida en reposo al arrancar
           (negativo = el objetivo se acerca al sensor)
  Sin eco: echo_us/dist_mm/rel_mm vacios, para que los huecos se vean.

Conexion sin HAT: VCC 5 V (pin 4), GND (pin 6), TRIG GPIO23 (pin 16) y ECHO
GPIO24 (pin 18) a traves de un divisor 2 x 10 kOhm (el ECHO sale a 5 V).
Temporizacion por hardware con pigpio (resolucion de 1 us).
"""

import math
import random
import statistics
import time

from .base import Modulo, pc
from . import sim


def velocidad_sonido(temp_c):
    """Velocidad del sonido en m/s segun la temperatura del aire."""
    return 331.3 + 0.606 * temp_c


class _EcoPigpio:
    def __init__(self, pi, trig, echo):
        import pigpio
        self.pigpio, self.pi, self.trig = pigpio, pi, trig
        pi.set_mode(trig, pigpio.OUTPUT)
        pi.set_mode(echo, pigpio.INPUT)
        pi.set_pull_up_down(echo, pigpio.PUD_DOWN)
        pi.write(trig, 0)
        self.t_subida = None
        self.dt_us = None
        self.cb = pi.callback(echo, pigpio.EITHER_EDGE, self._flanco)

    def _flanco(self, gpio, nivel, tick):
        if nivel == 1:
            self.t_subida = tick
        elif nivel == 0 and self.t_subida is not None:
            self.dt_us = self.pigpio.tickDiff(self.t_subida, tick)
            self.t_subida = None

    def medir_us(self, timeout_s):
        self.dt_us = None
        self.t_subida = None
        self.pi.gpio_trigger(self.trig, 10, 1)  # pulso de 10 us
        limite = pc() + timeout_s
        while self.dt_us is None and pc() < limite:
            time.sleep(0.0002)
        return self.dt_us

    def cerrar(self):
        self.cb.cancel()
        self.pi.write(self.trig, 0)


class _EcoSim:
    def __init__(self, modulo, v):
        self.m, self.v = modulo, v

    def medir_us(self, timeout_s):
        t = self.m.reloj()
        p = sim.pista(t)
        # trasera: se hunde al acelerar, se extiende al frenar, carga en curva
        comp = (25 * p["acel_g"] + 8 * min(1.0, abs(math.tan(math.radians(p["incl_deg"]))))
                + sim.baches(t) + 4 * math.sin(2 * math.pi * 1.3 * t))
        signo = -1 if self.m.cfg["montaje"] == "acerca" else 1
        d_mm = 250 + signo * comp + random.gauss(0, 1.0)
        if random.random() < 0.01:
            time.sleep(timeout_s)
            return None
        us = d_mm * 2000 / self.v
        time.sleep(us * 1e-6 + 0.0005)
        return us

    def cerrar(self):
        pass


class Suspension(Modulo):
    TIPO = "suspension"
    NOMBRE = "Suspension trasera (ultrasonidos)"
    COLS = ["t_s", "echo_us", "dist_mm", "rel_mm"]
    DEFECTOS = {
        "trig": 23, "echo": 24,
        "periodo_ms": 25.0,     # 40 Hz
        "max_cm": 100.0,        # distancia maxima esperada; fija el timeout
        "temp_c": 20.0,         # temperatura del aire para el sonido
        "cero_seg": 2.0,        # calibracion en reposo al arrancar
        "montaje": "acerca",    # al comprimir el objetivo se acerca / aleja
    }
    ACCIONES = {"calibrar": "Recalibrar reposo"}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.referencia = None
        self._recalibrar = False
        self._eco = None

    def pines(self):
        return f"TRIG GPIO{self.cfg['trig']} · ECHO GPIO{self.cfg['echo']}"

    def meta(self):
        m = super().meta()
        m["referencia_mm"] = None if self.referencia is None else round(self.referencia, 2)
        m["velocidad_sonido_m_s"] = round(velocidad_sonido(self.cfg["temp_c"]), 1)
        return m

    def accion(self, nombre):
        if nombre != "calibrar":
            return super().accion(nombre)
        self._recalibrar = True
        return "recalibrando: deja la moto quieta"

    def detectar(self):
        # El HC-SR04 siempre devuelve un pulso de eco, aunque no tenga objetivo
        # delante (~38 ms): si no llega ningun flanco, no esta conectado.
        eco = _EcoPigpio(self.hw.pi(), self.cfg["trig"], self.cfg["echo"])
        try:
            for _ in range(4):
                if eco.medir_us(0.06) is not None:
                    return ("si", "responde al disparo")
                time.sleep(0.02)
        finally:
            eco.cerrar()
        return ("no", f"sin eco en GPIO{self.cfg['echo']}: revisa VCC 5 V, "
                      "GND y el divisor del ECHO")

    def bucle(self):
        self._medir(_EcoPigpio(self.hw.pi(), self.cfg["trig"], self.cfg["echo"]))

    def simular(self):
        self._medir(_EcoSim(self, velocidad_sonido(self.cfg["temp_c"])))

    def liberar(self):
        if self._eco is not None:
            self._eco.cerrar()
            self._eco = None

    # ------------------------------------------------------------------------

    def _medir(self, eco):
        self._eco = eco
        c = self.cfg
        v = velocidad_sonido(c["temp_c"])
        # Un timeout corto = ciclo mas rapido. Ida y vuelta al maximo + margen.
        timeout_s = 2 * (c["max_cm"] / 100.0) / v + 0.002
        periodo = c["periodo_ms"] / 1000.0

        def a_mm(us):
            return us * v / 2000.0

        self._recalibrar = c["cero_seg"] > 0
        if not self._recalibrar:
            self.referencia = 0.0
            self.estado = "activo"
        proximo = pc()
        while not self.parar.is_set():
            if self._recalibrar:
                self._recalibrar = False
                self._calibrar(eco, timeout_s, periodo, a_mm)
                proximo = pc()
                continue
            proximo = self.esperar_periodo(proximo, periodo)
            if self.parar.is_set():
                break
            us = eco.medir_us(timeout_s)
            t = self.reloj()
            if us is None:
                self.publicar(t, [None, None, None], perdida=True)
            else:
                d = a_mm(us)
                self.publicar(t, [round(us), round(d, 1),
                                  round(d - self.referencia, 1)])

    def _calibrar(self, eco, timeout_s, periodo, a_mm):
        """Referencia en reposo; reintenta hasta tener lecturas."""
        self.estado = "calibrando"
        while not self.parar.is_set():
            vals, fin = [], pc() + self.cfg["cero_seg"]
            while pc() < fin and not self.parar.is_set():
                us = eco.medir_us(timeout_s)
                if us is not None:
                    vals.append(a_mm(us))
                self.parar.wait(periodo)
            if len(vals) >= 3:
                self.referencia = statistics.median(vals)
                self.aviso = None
                self.meta_ver += 1
                print(f"[{self.id}] referencia {self.referencia:.1f} mm "
                      f"(dispersion {statistics.pstdev(vals):.2f} mm)")
                break
            self.aviso = ("sin lecturas al calibrar: revisa la conexion y que haya "
                          f"un objetivo a menos de {self.cfg['max_cm']:g} cm")
        self.estado = "activo"
