"""
Catalogo de modulos de la telemetria.

Cada entrada es (id, clase, configuracion por defecto). Los pines son los del
documento "Telemetria de moto clasica: sensores y correlaciones" (Pi sin HAT).
Cualquier valor se puede cambiar en telemetria.json sin tocar el codigo:

  {"modulos": {"suspension": {"activo": true, "max_cm": 60},
               "temp_aceite": {"activo": false},
               "temp_escape": {"tipo": "termopar", "ce": 1}}}

'activo': "auto" (por defecto: arranca si se detecta), true o false.
Un id que no este en el catalogo crea un modulo nuevo del 'tipo' indicado.
"""

from collections import OrderedDict

from .alertas_rgb import AlertasRGB
from .base import Hardware, Modulo
from .boton import Boton
from .imu import IMU
from .infrarrojos import Infrarrojos
from .pantalla import Pantalla
from .rueda import Rueda
from .suspension import Suspension
from .termopar import Termopar
from .tira import TiraLeds

TIPOS = {c.TIPO: c for c in (Suspension, IMU, Infrarrojos, Termopar, Rueda,
                             Boton, AlertasRGB, TiraLeds, Pantalla)}

CATALOGO = [
    ("suspension", Suspension, {}),
    ("imu", IMU, {}),
    ("rueda_tras", Rueda, {"nombre": "Rueda trasera (Hall)", "gpio": 27,
                           "sim_desliz": 0.08}),
    ("rueda_del", Rueda, {"nombre": "Rueda delantera (Hall)", "gpio": 22}),
    ("temp_bujia", Termopar, {"nombre": "Temperatura bujia (sonda K)", "ce": 0}),
    ("temp_aceite", Termopar, {"nombre": "Temperatura aceite (sonda K)", "ce": 1,
                               "sim_base": 70.0, "sim_rango": 25.0, "sim_tau": 200.0}),
    ("ir", Infrarrojos, {}),
    ("boton", Boton, {}),
    ("alertas", AlertasRGB, {}),
    ("tira", TiraLeds, {}),
    ("pantalla", Pantalla, {}),
]


def crear(config, hw, bus):
    """Modulos del catalogo + los extra de la configuracion, en orden."""
    out = OrderedDict()
    for id_, cls, base in CATALOGO:
        cfg = dict(base)
        cfg.update(config.get(id_, {}))
        out[id_] = cls(id_, cfg, hw, bus)
    for id_, cfg in config.items():
        if id_ in out:
            continue
        cls = TIPOS.get(cfg.get("tipo"))
        if cls is None:
            print(f"Aviso: {id_} en la configuracion sin 'tipo' valido; se ignora.")
            continue
        out[id_] = cls(id_, cfg, hw, bus)
    return out


__all__ = ["CATALOGO", "TIPOS", "Hardware", "Modulo", "crear"]
