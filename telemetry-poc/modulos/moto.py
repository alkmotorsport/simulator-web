"""
Ficha de la moto de este sistema (telemetria.json, "moto"): la edita la app
(pestana Moto) y se copia en cada sesion al empezar a grabar, para analizarla
con la moto que era entonces (web/analisis.js). Todos los campos son
opcionales: lo que falte, el analisis lo toma de la moto de ejemplo de la
formacion y lo dice.

Dos campos se aplican tambien en la raspi al guardar:
  perimetro_tras_m  -> rueda_tras.perimetro_m (velocidad y distancia del Hall)
  susp_tras_mm      -> pantalla.recorrido_mm  (% de compresion y tope)
"""

# campo -> ("num", min, max) | ("txt", largo) | ("opc", [opciones])
CAMPOS = {
    "nombre": ("txt", 80),
    "motor_tiempos": ("opc", ["2T", "4T"]),
    "refrigeracion": ("opc", ["aire", "agua"]),
    "cilindrada_cc": ("num", 20, 3000),
    "potencia_cv": ("num", 0.5, 400),
    "potencia_rpm": ("num", 500, 25000),
    "velocidades": ("num", 1, 8),
    "vmax_kmh": ("num", 10, 400),
    "peso_seco_kg": ("num", 30, 400),
    "piloto_kg": ("num", 20, 200),
    "deposito_l": ("num", 1, 40),
    "batalla_m": ("num", 0.9, 2.0),
    "altura_cm_m": ("num", 0.3, 1.0),
    "susp_tras_mm": ("num", 20, 350),
    "rueda_del_pulg": ("num", 8, 23),
    "rueda_tras_pulg": ("num", 8, 23),
    "perimetro_tras_m": ("num", 0.8, 2.6),
    "neumaticos": ("opc", ["calle", "deportivo", "competicion"]),
    "freno_del_tipo": ("opc", ["tambor", "disco"]),
    "freno_del_mm": ("num", 80, 400),
    "freno_del_discos": ("num", 1, 2),
    "freno_del_disco_kg": ("num", 0.2, 5),
    "freno_del_material": ("opc", ["acero", "carbono"]),
    "freno_tras_tipo": ("opc", ["tambor", "disco"]),
    "freno_tras_mm": ("num", 80, 400),
    "carroceria": ("opc", ["naked", "semicarenada", "carenada"]),
    "notas": ("txt", 500),
}


def validar(d):
    """Ficha limpia: solo campos conocidos y con valores validos (los vacios se quitan)."""
    if not isinstance(d, dict):
        raise ValueError("ficha de la moto no valida")
    out = {}
    for k, v in d.items():
        if k not in CAMPOS:
            raise ValueError(f"campo desconocido: {k}")
        if v is None or v == "":
            continue
        tipo = CAMPOS[k]
        if tipo[0] == "num":
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k}: tiene que ser un numero")
            if not tipo[1] <= v <= tipo[2]:
                raise ValueError(f"{k}: fuera de rango ({tipo[1]}-{tipo[2]})")
            out[k] = int(v) if v == int(v) else v
        elif tipo[0] == "opc":
            if v not in tipo[1]:
                raise ValueError(f"{k}: valor no valido")
            out[k] = v
        else:
            out[k] = str(v).strip()[:tipo[1]]
    return out


def aplicar(ficha, modulos, cfg_modulos):
    """Lleva a los modulos lo que les afecta. Devuelve {modulo: {ajuste: valor}}."""
    cambios = {}
    for campo, mod, ajuste in (("perimetro_tras_m", "rueda_tras", "perimetro_m"),
                               ("susp_tras_mm", "pantalla", "recorrido_mm")):
        if campo in ficha and mod in modulos:
            modulos[mod].cfg[ajuste] = ficha[campo]       # en marcha: se usa al momento
            cfg_modulos.setdefault(mod, {})[ajuste] = ficha[campo]
            cambios.setdefault(mod, {})[ajuste] = ficha[campo]
    return cambios
