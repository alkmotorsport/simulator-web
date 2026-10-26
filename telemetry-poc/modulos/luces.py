"""
Luces del cuadro (tira WS2812) y alertas, configurables desde la web.

Dos niveles:
  indicadores  las luces describen la pagina que se ve en la pantalla:
               cada pagina tiene un dato y unos niveles, en modo
                 "barra"   un nivel por LED (se llena como un indicador)
                 "estado"  todas del color del primer nivel que se cumple
  alertas      mandan sobre todo: la pantalla salta a la pagina del dato y
               todas las luces muestran la alerta.
                 "momentanea"  unos segundos ('seg') y vuelve a donde estaba;
                               no vuelve a saltar hasta pasado 'espera_s'
                               (mientras, solo destellan las luces)
                 "grave"       mientras dure; una pulsacion corta la
                               reconoce (vuelve a tu pagina, '!' en la
                               cabecera) y salta otra vez a los 'recordar_s'
                               si sigue activa

Configuracion (telemetria.json, modulos.pantalla.luces; la web la edita):
  {"paginas": {"incl": {"dato": "incl_abs", "modo": "barra", "reposo": "off",
                        "niveles": [{"op": ">", "valor": 20, "color": "verde",
                                     "efecto": "fijo"}, ...]}, ...},
   "alertas": [{"nombre": "...", "dato": "t_bujia", "op": ">", "valor": 250,
                "tipo": "grave", "color": "rojo", "efecto": "rapido",
                "pagina": "bujia", "seg": 3, "espera_s": 30, "hist": 5}, ...]}

Cada luz sale como (color, efecto); la tira calcula el parpadeo a su ritmo.

"resumen": los 6 datos de la pagina RESUMEN de la pantalla (RESUMEN; "" =
casilla vacia), en orden: fila de arriba y fila de abajo.
"""

import copy
import math

COLORES = ["rojo", "ambar", "verde", "azul", "morado", "blanco"]
EFECTOS = ["fijo", "lento", "rapido", "destello"]
OPS = [">", "<"]
TIPOS = ["momentanea", "grave"]
OFF = ("off", "fijo")

# dato -> (nombre, unidad, pagina de la pantalla donde se ve)
CATALOGO = {
    "kmh": ("Velocidad", "km/h", "vel"),
    "comp_pct": ("Compresión de la suspensión", "% recorrido", "susp"),
    "tope": ("Tope de suspensión (al hacer tope)", "", "susp"),
    "incl_abs": ("Inclinación (a cualquier lado)", "°", "incl"),
    "g_comb": ("G combinada (agarre usado)", "g", "g"),
    "frenada": ("Frenada", "g", "g"),
    "aceleracion": ("Aceleración", "g", "g"),
    "t_bujia": ("Temperatura bujía", "°C", "bujia"),
    "t_aceite": ("Temperatura aceite", "°C", "aceite"),
    "t_ir": ("Temperatura disco", "°C", "disco"),
    "delta": ("Diferencia con la mejor vuelta", "s", "vuelta"),
    "vuelta_nueva": ("Vuelta marcada (al marcarla)", "", "vuelta"),
    "mejor_vuelta": ("Mejor vuelta (al marcarla)", "", "vuelta"),
    "sensores_mal": ("Sensores con fallo", "", "sistema"),
}
EVENTOS = {"tope", "vuelta_nueva", "mejor_vuelta"}   # valen 1 un momento

# pagina RESUMEN: dato -> (rotulo en la pantalla, decimales, nombre en la web)
RESUMEN = {
    "kmh": ("VEL", 0, "Velocidad"),
    "incl_abs": ("INCL", 0, "Inclinación"),
    "g_comb": ("G", 2, "G combinada"),
    "frenada": ("FRENO", 2, "Frenada (g)"),
    "aceleracion": ("ACEL", 2, "Aceleración (g)"),
    "comp_mm": ("SUSP", 0, "Suspensión (mm)"),
    "comp_pct": ("SUSP%", 0, "Suspensión (% recorrido)"),
    "t_bujia": ("BUJIA", 0, "Temperatura bujía"),
    "t_aceite": ("ACEITE", 0, "Temperatura aceite"),
    "t_ir": ("DISCO", 0, "Temperatura disco"),
    "vuelta": ("VUELTA", 0, "Número de vuelta"),
    "t_mejor": ("MEJOR", 0, "Mejor vuelta (s)"),
    "delta": ("DELTA", 1, "Diferencia con la mejor (s)"),
}
RESUMEN_DEFECTO = ["kmh", "incl_abs", "g_comb", "comp_mm", "t_bujia", "t_aceite"]
SI_NO = EVENTOS | {"sensores_mal"}                    # en la web: "cuando ocurre"


def valores(D, ahora, cfg, sensores_mal=0):
    """Valor actual de cada dato del catalogo (None si no hay o es viejo)."""
    v = {}
    hay = lambda k: D.hay(k, ahora)
    v["kmh"] = D.get("kmh") if hay("kmh") else None
    if hay("comp_mm"):
        v["comp_pct"] = 100.0 * D.get("comp_mm") / cfg["recorrido_mm"]
        v["tope"] = 1.0 if D.en_tope else 0.0
    if hay("incl"):
        incl = D.get("incl")
        v["incl_abs"] = abs(incl)
        lat = math.tan(math.radians(incl)) if abs(incl) < 70 else None
        if hay("ax_f"):
            ax = D.get("ax_f")
            v["frenada"], v["aceleracion"] = max(0.0, -ax), max(0.0, ax)
            if lat is not None:
                v["g_comb"] = math.hypot(ax, lat)
    for k in ("t_bujia", "t_aceite", "t_ir"):
        v[k] = D.get(k) if hay(k) else None
    if D.get("delta") is not None:
        v["delta"] = D.get("delta")
    t_v = D.t.get("t_ini_vuelta")
    reciente = t_v is not None and ahora - t_v < 1.0 and (D.get("vuelta") or 0) > 1
    v["vuelta_nueva"] = 1.0 if reciente else 0.0
    v["mejor_vuelta"] = 1.0 if reciente and (D.get("delta") or 0) < 0 else 0.0
    v["sensores_mal"] = float(sensores_mal)
    v["comp_mm"] = D.get("comp_mm") if hay("comp_mm") else None
    v["vuelta"] = D.get("vuelta")
    v["t_mejor"] = D.get("t_mejor")
    return v


def _cumple(op, x, umbral, hist=0.0, activa=False):
    """Condicion con histeresis: una vez activa, se suelta 'hist' mas alla."""
    if x is None:
        return False
    if op == "<":
        return x < (umbral + hist if activa else umbral)
    return x > (umbral - hist if activa else umbral)


# ------------------------------------------------------------- plantillas ---

def _niv(op, valor, color, efecto="fijo"):
    return {"op": op, "valor": valor, "color": color, "efecto": efecto}


PLANTILLAS = {
    "recomendada": {
        "nombre": "Recomendada",
        "paginas": {
            "vel": {"dato": "kmh", "modo": "barra", "reposo": "off",
                    "niveles": [_niv(">", 60, "verde"), _niv(">", 100, "ambar"), _niv(">", 140, "rojo", "lento")]},
            "susp": {"dato": "comp_pct", "modo": "barra", "reposo": "off",
                     "niveles": [_niv(">", 50, "verde"), _niv(">", 75, "ambar"), _niv(">", 90, "rojo")]},
            "incl": {"dato": "incl_abs", "modo": "barra", "reposo": "off",
                     "niveles": [_niv(">", 20, "verde"), _niv(">", 30, "ambar"), _niv(">", 40, "rojo")]},
            "g": {"dato": "g_comb", "modo": "barra", "reposo": "off",
                  "niveles": [_niv(">", 0.4, "verde"), _niv(">", 0.6, "ambar"), _niv(">", 0.8, "rojo")]},
            "bujia": {"dato": "t_bujia", "modo": "estado", "reposo": "off",
                      "niveles": [_niv(">", 250, "rojo", "rapido"), _niv(">", 220, "ambar"),
                                  _niv("<", 100, "azul"), _niv(">", 100, "verde")]},
            "aceite": {"dato": "t_aceite", "modo": "estado", "reposo": "off",
                       "niveles": [_niv(">", 120, "rojo", "rapido"), _niv(">", 110, "ambar"),
                                   _niv("<", 60, "azul"), _niv(">", 60, "verde")]},
            "disco": {"dato": "t_ir", "modo": "estado", "reposo": "off",
                      "niveles": [_niv(">", 400, "rojo", "rapido"), _niv(">", 320, "ambar"), _niv(">", 0, "verde")]},
            "vuelta": {"dato": "delta", "modo": "estado", "reposo": "off",
                       "niveles": [_niv("<", 0, "verde"), _niv(">", 0, "rojo")]},
            "sistema": {"dato": "sensores_mal", "modo": "estado", "reposo": "off",
                        "niveles": [_niv(">", 0.5, "rojo", "lento"), _niv("<", 0.5, "verde")]},
        },
        "alertas": [
            {"nombre": "Bujía muy caliente", "dato": "t_bujia", "op": ">", "valor": 250, "tipo": "grave",
             "color": "rojo", "efecto": "rapido", "hist": 10},
            {"nombre": "Aceite muy caliente", "dato": "t_aceite", "op": ">", "valor": 120, "tipo": "grave",
             "color": "rojo", "efecto": "rapido", "hist": 3},
            {"nombre": "Disco al límite", "dato": "t_ir", "op": ">", "valor": 400, "tipo": "grave",
             "color": "rojo", "efecto": "rapido", "hist": 20},
            {"nombre": "Sensor con fallo", "dato": "sensores_mal", "op": ">", "valor": 0.5, "tipo": "grave",
             "color": "rojo", "efecto": "lento"},
            {"nombre": "Tope de suspensión", "dato": "tope", "op": ">", "valor": 0.5, "tipo": "momentanea",
             "color": "rojo", "efecto": "destello", "seg": 3, "espera_s": 30},
            {"nombre": "Mejor vuelta", "dato": "mejor_vuelta", "op": ">", "valor": 0.5, "tipo": "momentanea",
             "color": "morado", "efecto": "destello", "seg": 4, "espera_s": 0},
            {"nombre": "Vuelta marcada", "dato": "vuelta_nueva", "op": ">", "valor": 0.5, "tipo": "momentanea",
             "color": "verde", "efecto": "destello", "seg": 3, "espera_s": 0},
        ],
    },
    "solo_alertas": {"nombre": "Solo alertas (luces apagadas en marcha normal)", "paginas": {}, "alertas": None},
    "apagadas": {"nombre": "Todo apagado", "paginas": {}, "alertas": []},
}
for _p in PLANTILLAS.values():
    _p["resumen"] = list(RESUMEN_DEFECTO)
PLANTILLAS["solo_alertas"]["alertas"] = PLANTILLAS["recomendada"]["alertas"]


def por_defecto():
    p = PLANTILLAS["recomendada"]
    return {"paginas": copy.deepcopy(p["paginas"]), "alertas": copy.deepcopy(p["alertas"]),
            "resumen": list(RESUMEN_DEFECTO)}


# ------------------------------------------------------------ validacion ---

def validar(cfg, paginas_validas):
    """Comprueba y normaliza lo que manda la web. ValueError si algo no vale."""
    if not isinstance(cfg, dict):
        raise ValueError("configuracion de luces no valida")

    def nivel(n, donde):
        if n.get("op", ">") not in OPS:
            raise ValueError(f"{donde}: condicion no valida")
        if n.get("color") not in COLORES:
            raise ValueError(f"{donde}: color no valido")
        if n.get("efecto", "fijo") not in EFECTOS:
            raise ValueError(f"{donde}: efecto no valido")
        try:
            valor = float(n["valor"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{donde}: falta el valor")
        return {"op": n.get("op", ">"), "valor": valor, "color": n["color"], "efecto": n.get("efecto", "fijo")}

    resumen = cfg.get("resumen")
    if resumen is None:
        resumen = RESUMEN_DEFECTO
    if not isinstance(resumen, list) or len(resumen) > 6 or any(r not in RESUMEN and r != "" for r in resumen):
        raise ValueError("resumen: hasta 6 datos de la lista")
    out = {"paginas": {}, "alertas": [], "resumen": (list(resumen) + [""] * 6)[:6]}
    for pid, p in (cfg.get("paginas") or {}).items():
        if pid not in paginas_validas:
            raise ValueError(f"pagina desconocida: {pid}")
        if p.get("dato") not in CATALOGO:
            raise ValueError(f"pagina {pid}: dato desconocido")
        if p.get("modo", "barra") not in ("barra", "estado"):
            raise ValueError(f"pagina {pid}: modo no valido")
        if p.get("reposo", "off") not in COLORES + ["off"]:
            raise ValueError(f"pagina {pid}: color de reposo no valido")
        niveles = [nivel(n, f"pagina {pid}") for n in (p.get("niveles") or [])][:12]
        out["paginas"][pid] = {"dato": p["dato"], "modo": p.get("modo", "barra"),
                               "reposo": p.get("reposo", "off"), "niveles": niveles}
    for i, a in enumerate((cfg.get("alertas") or [])[:30]):
        donde = f"alerta {i + 1}"
        if a.get("dato") not in CATALOGO:
            raise ValueError(f"{donde}: dato desconocido")
        if a.get("tipo") not in TIPOS:
            raise ValueError(f"{donde}: tipo no valido")
        n = nivel(a, donde)
        pagina = a.get("pagina") or CATALOGO[a["dato"]][2]
        if pagina not in paginas_validas:
            raise ValueError(f"{donde}: pagina desconocida")
        num = lambda k, d: max(0.0, float(a.get(k, d) or 0))
        out["alertas"].append(dict(n, nombre=str(a.get("nombre") or CATALOGO[a["dato"]][0])[:40],
                                   dato=a["dato"], tipo=a["tipo"], pagina=pagina,
                                   seg=num("seg", 3), espera_s=num("espera_s", 30),
                                   hist=num("hist", 0), recordar_s=num("recordar_s", 120)))
    return out


# ----------------------------------------------------------------- motor ---

class Motor:
    """Decide la pagina forzada por las alertas y el color de cada luz."""

    def __init__(self, cfg):
        self.cargar(cfg)

    def cargar(self, cfg):
        self.cfg = cfg if cfg is not None else por_defecto()
        self.estado = [{"activa": False, "hasta": -1e9, "salto": -1e9, "rec": None}
                       for _ in self.cfg.get("alertas", [])]
        self.indic_activo = {}           # (pagina, nivel) -> activo (histeresis)

    def actualizar(self, v, ahora):
        """Evalua las alertas. Devuelve (alerta que manda o None, '!' en cabecera)."""
        manda, marca = None, False
        for a, e in zip(self.cfg.get("alertas", []), self.estado):
            x = v.get(a["dato"])
            antes = e["activa"]
            e["activa"] = _cumple(a["op"], x, a["valor"], a.get("hist", 0), antes)
            if a["tipo"] == "momentanea":
                if e["activa"] and not antes:                  # flanco: empieza
                    e["hasta"] = ahora + a.get("seg", 3)
                    e["salta"] = ahora - e["salto"] >= a.get("espera_s", 30)
                    if e["salta"]:
                        e["salto"] = ahora
                if ahora < e["hasta"] and manda is None:
                    manda = (a, e.get("salta", False))
            else:
                if not e["activa"]:
                    e["rec"] = None
                    continue
                if e["rec"] is not None and ahora - e["rec"] >= a.get("recordar_s", 120):
                    e["rec"] = None                            # recordar otra vez
                if e["rec"] is not None:
                    marca = True
                elif manda is None or manda[0]["tipo"] != "grave":
                    manda = (a, True)
        return manda, marca

    def reconocer(self, ahora):
        """Pulsacion corta con una alerta en pantalla: la quita. True si habia."""
        hubo = False
        for a, e in zip(self.cfg.get("alertas", []), self.estado):
            if a["tipo"] == "grave" and e["activa"] and e["rec"] is None:
                e["rec"], hubo = ahora, True
            elif a["tipo"] == "momentanea" and ahora < e["hasta"]:
                e["hasta"], hubo = ahora, True
        return hubo

    def luces(self, pagina, v, n, manda=None):
        """Lista de n (color, efecto)."""
        if manda is not None:
            a = manda[0]
            return [(a["color"], a["efecto"])] * n
        p = self.cfg.get("paginas", {}).get(pagina)
        if not p:
            return [OFF] * n
        x = v.get(p["dato"])
        reposo = (p.get("reposo", "off"), "fijo")
        niveles = p.get("niveles", [])
        if p.get("modo") == "estado":
            for k, nv in enumerate(niveles):
                if self._nivel(pagina, k, nv, x):
                    return [(nv["color"], nv["efecto"])] * n
            return [reposo] * n
        out = []
        for i in range(n):
            nv = niveles[i] if i < len(niveles) else None
            out.append((nv["color"], nv["efecto"]) if nv and self._nivel(pagina, i, nv, x) else reposo)
        return out

    def _nivel(self, pagina, k, nv, x):
        # histeresis automatica del 3 % para que la luz no tiemble en el umbral
        clave = (pagina, k)
        activo = _cumple(nv["op"], x, nv["valor"], abs(nv["valor"]) * 0.03, self.indic_activo.get(clave, False))
        self.indic_activo[clave] = activo
        return activo


def encendida(efecto, ahora):
    """Si una luz con ese efecto esta encendida en este instante."""
    if efecto == "lento":
        return int(ahora * 2) % 2 == 0          # 1 Hz
    if efecto == "rapido":
        return int(ahora * 8) % 2 == 0          # 4 Hz
    if efecto == "destello":
        return ahora % 0.6 < 0.12               # flash corto
    return True
