"""
Vuelta simulada comun a todos los modulos en --sim.

Todos leen la misma pista en funcion del reloj comun, asi que los datos son
coherentes entre si (al frenar baja la velocidad, la IMU marca deceleracion,
la trasera se extiende y el disco se calienta) y las correlaciones de la web
se pueden probar sin hardware.
"""

import math

VUELTA_S = 60.0
G = 9.81

# (s dentro de la vuelta, km/h): rectas, frenadas y curvas
VELOCIDAD = [(0, 60), (10, 160), (13, 60), (20, 60), (28, 140), (30, 70),
             (38, 70), (48, 150), (51, 60), (60, 60)]
# (s, inclinacion en grados; + = a la derecha)
INCLINACION = [(0, 0), (12.5, 0), (14, 40), (19, 40), (20.5, 0), (29.5, 0),
               (31, -35), (37, -35), (38.5, 0), (50.5, 0), (52, 30), (58.5, 30),
               (60, 0)]


def _interp(puntos, x):
    """Interpolacion suave (coseno) entre puntos (x, y) ordenados."""
    for (x0, y0), (x1, y1) in zip(puntos, puntos[1:]):
        if x0 <= x <= x1:
            f = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + (y1 - y0) * (1 - math.cos(math.pi * f)) / 2
    return puntos[-1][1]


def pista(t):
    """Estado de la moto en el instante t (s del reloj comun)."""
    x = t % VUELTA_S
    kmh = _interp(VELOCIDAD, x)
    dv = (_interp(VELOCIDAD, (x + 0.05) % VUELTA_S) -
          _interp(VELOCIDAD, (x - 0.05) % VUELTA_S)) / 0.1
    acel_g = dv / 3.6 / G
    incl = _interp(INCLINACION, x)
    dincl = (_interp(INCLINACION, (x + 0.05) % VUELTA_S) -
             _interp(INCLINACION, (x - 0.05) % VUELTA_S)) / 0.1
    v = kmh / 3.6
    # curva coordinada: giro (CCW +) que corresponde a esa inclinacion
    giro = -G * math.tan(math.radians(incl)) / max(v, 1.0)
    return {
        "kmh": kmh, "acel_g": acel_g, "incl_deg": incl, "dincl_dps": dincl,
        "giro_rad_s": giro, "cabeceo_deg": 2.5 * acel_g,
        "frenada": max(0.0, -acel_g), "vuelta": int(t // VUELTA_S),
    }


def baches(t):
    """Compresion extra (mm) por baches: uno seco cada 9 s."""
    f = t % 9
    if 0 <= f < 1:
        return 45 * math.sin(math.pi / 2 * min(1, f / 0.05)) ** 2 * math.exp(-5 * f)
    return 0.0
