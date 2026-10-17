"""
MPU6050: acelerometro y giroscopio de 6 ejes (I2C 0x68).

CSV: t_s, ax_g, ay_g, az_g, gx_dps, gy_dps, gz_dps, incl_deg, cabeceo_deg
  Ejes de la moto: x hacia delante, y a la izquierda, z hacia arriba.
  incl_deg     inclinacion en curva, + a la derecha (derivada)
  cabeceo_deg  + morro arriba (derivada)

Conexion: VCC 3,3 V (pin 1), GND (pin 6), SDA (pin 3), SCL (pin 5).
Si el sensor no va montado con sus ejes como los de la moto, 'ejes' dice que
eje del sensor apunta a cada eje de la moto, p. ej. "-y,x,z".

Al arrancar (y con la accion Calibrar) mide 2 s con la moto vertical y
quieta: quita el sesgo del giroscopio y pone a cero inclinacion y cabeceo.

Inclinacion: filtro complementario (giroscopio a corto plazo). La referencia
a largo plazo sale del acelerometro, que en una curva mantenida marca ~0
(la fuerza resultante va alineada con la moto); si hay velocidad de rueda
(fuente_vel), se usa la de una curva coordinada: atan(v * giro / g).
"""

import math
import random
import time

from .base import Modulo, pc
from . import sim

REG_PWR = 0x6B
REG_DLPF = 0x1A
REG_GYRO = 0x1B
REG_ACC = 0x1C
REG_DATOS = 0x3B
REG_WHOAMI = 0x75
ESCALA_ACC = 8192.0     # LSB/g a +-4 g
ESCALA_GYRO = 65.5      # LSB/(grado/s) a +-500 grados/s
G = 9.81


def _s16(hi, lo):
    v = (hi << 8) | lo
    return v - 65536 if v & 0x8000 else v


def _mapa_ejes(txt):
    """'-y,x,z' -> [(1, -1), (0, 1), (2, 1)]: (indice del sensor, signo)."""
    out = []
    for p in txt.replace(" ", "").split(","):
        signo = -1 if p.startswith("-") else 1
        out.append(("xyz".index(p.lstrip("+-")), signo))
    if len(out) != 3 or len({i for i, _ in out}) != 3:
        raise ValueError(f"ejes no valido: {txt}")
    return out


class _MPU:
    def __init__(self, hw, addr):
        self.hw, self.addr = hw, addr
        bus = hw.i2c()
        with hw.lock_i2c:
            bus.write_byte_data(addr, REG_PWR, 0x00)    # despertar, reloj interno
        time.sleep(0.05)
        with hw.lock_i2c:
            bus.write_byte_data(addr, REG_PWR, 0x01)    # reloj del giroscopio X
            bus.write_byte_data(addr, REG_DLPF, 0x03)   # filtro ~44 Hz
            bus.write_byte_data(addr, REG_GYRO, 0x08)   # +-500 grados/s
            bus.write_byte_data(addr, REG_ACC, 0x08)    # +-4 g

    def leer(self):
        """(ax, ay, az) en g y (gx, gy, gz) en grados/s, ejes del sensor."""
        with self.hw.lock_i2c:
            b = self.hw.i2c().read_i2c_block_data(self.addr, REG_DATOS, 14)
        a = [_s16(b[i], b[i + 1]) / ESCALA_ACC for i in (0, 2, 4)]
        g = [_s16(b[i], b[i + 1]) / ESCALA_GYRO for i in (8, 10, 12)]
        return a, g


class _MPUSim:
    """Genera lo que mediria el sensor montado en la moto de sim.pista()."""

    def __init__(self, modulo):
        self.m = modulo

    def leer(self):
        p = sim.pista(self.m.reloj())
        fi = math.radians(p["incl_deg"])
        th = math.radians(p["cabeceo_deg"])
        w = p["giro_rad_s"]
        vib = lambda s: random.gauss(0, s)
        ax = p["acel_g"] + math.sin(th) + vib(0.03)
        ay = vib(0.03)                               # curva coordinada
        az = 1 / math.cos(fi) + vib(0.05)
        gx = p["dincl_dps"] + vib(0.8)
        gz = math.degrees(w * math.cos(fi)) + vib(0.5)
        gy = math.degrees(w * math.sin(fi)) + vib(0.5)
        return [ax, ay, az], [gx, gy, gz]


class IMU(Modulo):
    TIPO = "imu"
    NOMBRE = "IMU MPU6050"
    COLS = ["t_s", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps",
            "incl_deg", "cabeceo_deg"]
    DEFECTOS = {
        "direccion": 0x68,
        "hz": 100.0,
        "ejes": "x,y,z",            # eje del sensor hacia delante, izquierda, arriba
        "alfa": 0.98,               # peso del giroscopio en el filtro complementario
        "cero_seg": 2.0,
        "fuente_vel": "rueda_tras",  # modulo con columna kmh (opcional)
    }
    ACCIONES = {"calibrar": "Calibrar (moto vertical)"}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._recalibrar = False
        self.sesgo = [0.0, 0.0, 0.0]
        self.cero = [0.0, 0.0]      # inclinacion y cabeceo en reposo (rad)
        self.vel = (None, -1e9)     # (m/s, t)

    def pines(self):
        return f"I2C 0x{self.cfg['direccion']:02X} · SDA pin 3 · SCL pin 5"

    def meta(self):
        m = super().meta()
        m["direccion"] = f"0x{self.cfg['direccion']:02X}"
        m["sesgo_gyro_dps"] = [round(x, 3) for x in self.sesgo]
        m["cero_deg"] = [round(math.degrees(x), 2) for x in self.cero]
        return m

    def accion(self, nombre):
        if nombre != "calibrar":
            return super().accion(nombre)
        self._recalibrar = True
        return "calibrando: moto vertical y quieta 2 s"

    def detectar(self):
        addr = self.cfg["direccion"]
        if not self.hw.i2c_presente(addr):
            return ("no", f"nada en I2C 0x{addr:02X}")
        with self.hw.lock_i2c:
            quien = self.hw.i2c().read_byte_data(addr, REG_WHOAMI)
        if quien == 0x68:
            return ("si", "MPU6050 (WHO_AM_I 0x68)")
        return ("si", f"responde en 0x{addr:02X} (WHO_AM_I 0x{quien:02X}, clon o MPU6500)")

    def bucle(self):
        self._medir(_MPU(self.hw, self.cfg["direccion"]))

    def simular(self):
        self._medir(_MPUSim(self))

    # ------------------------------------------------------------------------

    def _a_moto(self, v, mapa):
        return [s * v[i] for i, s in mapa]

    def _velocidad(self, t, kmh):
        if kmh is not None:
            self.vel = (kmh / 3.6, t)

    def _medir(self, mpu):
        c = self.cfg
        mapa = _mapa_ejes(c["ejes"])
        periodo = 1.0 / c["hz"]
        alfa = c["alfa"]
        if c.get("fuente_vel"):
            self.escuchar(c["fuente_vel"], "kmh", self._velocidad)
        self._recalibrar = c["cero_seg"] > 0 and not self.hw.sim
        incl = cab = 0.0
        t_prev = None
        self.estado = "activo"
        proximo = pc()
        while not self.parar.is_set():
            if self._recalibrar:
                self._recalibrar = False
                self._calibrar(mpu, mapa, periodo)
                incl, cab, t_prev = 0.0, 0.0, None
                proximo = pc()
                continue
            proximo = self.esperar_periodo(proximo, periodo)
            if self.parar.is_set():
                break
            try:
                a, g = mpu.leer()
            except (OSError, IOError):
                self.publicar(self.reloj(), [None] * 8, perdida=True)
                continue
            t = self.reloj()
            a = self._a_moto(a, mapa)
            g = [x - b for x, b in zip(self._a_moto(g, mapa), self.sesgo)]
            ax, ay, az = a
            gx, gy, gz = (math.radians(x) for x in g)

            # referencias a largo plazo
            v, tv = self.vel
            if v is not None and t - tv < 1.0 and v > 3:
                w = math.copysign(math.hypot(gy, gz), gz)    # giro de la moto
                incl_ref = -math.atan(v * w / G)
            else:
                incl_ref = math.atan2(ay, az) - self.cero[0]
            cab_ref = math.atan2(ax, math.hypot(ay, az)) - self.cero[1]

            if t_prev is None or t - t_prev > 0.2:
                incl, cab = incl_ref, cab_ref
            else:
                dt = t - t_prev
                d_cab = -gy * math.cos(incl) + gz * math.sin(incl)
                incl = alfa * (incl + gx * dt) + (1 - alfa) * incl_ref
                cab = alfa * (cab + d_cab * dt) + (1 - alfa) * cab_ref
            t_prev = t
            self.publicar(t, [round(ax, 3), round(ay, 3), round(az, 3),
                              round(g[0], 2), round(g[1], 2), round(g[2], 2),
                              round(math.degrees(incl), 2), round(math.degrees(cab), 2)])

    def _calibrar(self, mpu, mapa, periodo):
        self.estado = "calibrando"
        sa, sg, n = [0.0] * 3, [0.0] * 3, 0
        fin = pc() + self.cfg["cero_seg"]
        while pc() < fin and not self.parar.is_set():
            try:
                a, g = mpu.leer()
            except (OSError, IOError):
                continue
            a, g = self._a_moto(a, mapa), self._a_moto(g, mapa)
            sa = [x + y for x, y in zip(sa, a)]
            sg = [x + y for x, y in zip(sg, g)]
            n += 1
            self.parar.wait(periodo)
        if n >= 10:
            ax, ay, az = (x / n for x in sa)
            self.sesgo = [x / n for x in sg]
            self.cero = [math.atan2(ay, az), math.atan2(ax, math.hypot(ay, az))]
            self.aviso = None
            self.meta_ver += 1
            print(f"[{self.id}] calibrado: sesgo {[round(x, 2) for x in self.sesgo]} "
                  f"grados/s, cero {[round(math.degrees(x), 1) for x in self.cero]} grados")
        else:
            self.aviso = "no se pudo calibrar: sin lecturas"
        self.estado = "activo"
