#!/usr/bin/env python3
"""
Telemetria de moto: programa maestro.

Carga el catalogo de modulos (modulos/__init__.py), detecta cuales estan
conectados a la Raspberry y arranca los activos, cada uno en su hilo. Lo que
publica cada sensor va a la vez a:
  - la grabacion: una carpeta por sesion en --dir con un CSV por sensor,
    todos con el mismo reloj (t_s), y un sesion.json con los parametros;
  - la web (tiempo real y control: activar sensores, calibrar, grabar);
  - las salidas suscritas (LEDs de alerta, barra WS2812).
Un sensor que no esta (p. ej. sin sonda de aceite) no se ejecuta ni aparece
en la telemetria. Si la raspi tiene repo de datos (sincro.py), cada sesion
terminada se sube cifrada a GitHub.

Uso:
  sudo python3 telemetria.py                  # autodetecta, web en :8081, graba
  sudo python3 telemetria.py --https          # web usable desde tu dominio
  sudo python3 telemetria.py --no-grabar      # graba solo al pulsar Grabar en la web
  sudo python3 telemetria.py --detectar       # dice que hay conectado y sale
  sudo python3 telemetria.py --demo-pantalla  # solo la pantalla OLED, datos simulados
  python3 telemetria.py --demo-pantalla --png carpeta   # sus paginas en PNG
  python3 telemetria.py --sim                 # todo simulado (portatil, sin Pi)
  sudo python3 telemetria.py --https --no-grabar --tunel   # como el servicio:
                                              # web publica por tunel, solo usuarios

Activar o forzar modulos: con el tick de la web, o en telemetria.json
(ver modulos/__init__.py). sudo hace falta para la tira WS2812.
"""

import argparse
import csv
import json
import os
import re
import shutil
import signal
import sys
import threading
import time
from datetime import datetime

import modulos
import sincro
from modulos import luces as luces_mod
from modulos import moto as moto_mod
from modulos.pantalla import PAGINAS
from acceso import Acceso
from live_server import LiveServer
from tunel import Tunel
from modulos.base import pc

AQUI = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------ configuracion ---

def leer_config(ruta):
    if not os.path.exists(ruta):
        return {"modulos": {}}
    with open(ruta, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("modulos", {})
    return cfg


def guardar_config(ruta, cfg):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, ruta)


# --------------------------------------------------------------- grabacion ---

class Grabador:
    """Una carpeta por sesion: <modulo>.csv por sensor + sesion.json."""

    def __init__(self, dir_, maestro):
        self.dir = dir_
        self.m = maestro
        self.lock = threading.Lock()
        self.sesion = None

    def activa(self):
        return self.sesion is not None

    def iniciar(self):
        with self.lock:
            if self.sesion is not None:
                return
            nombre = datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta = os.path.join(self.dir, nombre)
            os.makedirs(ruta, exist_ok=True)
            self.sesion = {"nombre": nombre, "ruta": ruta, "t0": self.m.reloj(),
                           "inicio": datetime.now().isoformat(timespec="seconds"),
                           "ficheros": {},
                           # la moto de ese momento: se analiza con ella aunque luego cambie
                           "moto": dict(self.m.cfg.get("moto") or {})}
            self._json()
        print(f"\nGrabando en {ruta}")

    def parar(self):
        with self.lock:
            s = self.sesion
            if s is None:
                return
            self._volcar(fsync=True)
            for f, _, _ in s["ficheros"].values():
                f.close()
            s["fin"] = datetime.now().isoformat(timespec="seconds")
            self._json()
            self.sesion = None
        print(f"\nSesion guardada: {os.path.abspath(s['ruta'])}")
        if self.m.sincro:
            self.m.sincro.avisar()

    def fila(self, mod, t, valores):
        if self.sesion is None or not mod.COLS:
            return
        with self.lock:
            s = self.sesion
            if s is None:
                return
            fc = s["ficheros"].get(mod.id)
            if fc is None:
                f = open(os.path.join(s["ruta"], mod.id + ".csv"), "w", newline="",
                         buffering=1 << 16, encoding="utf-8")
                w = csv.writer(f)
                w.writerow(mod.COLS)
                fc = s["ficheros"][mod.id] = (f, w, [])
                self._json()
            fc[2].append([f"{t - s['t0']:.4f}"] +
                         ["" if v is None else v for v in valores])

    def volcar(self, fsync=False):
        with self.lock:
            self._volcar(fsync)

    def actualizar_json(self):
        with self.lock:
            if self.sesion is not None:
                self._json()

    def _volcar(self, fsync):
        if self.sesion is None:
            return
        for f, w, buf in self.sesion["ficheros"].values():
            if buf:
                w.writerows(buf)
                buf.clear()
            f.flush()
            if fsync:
                os.fsync(f.fileno())

    def _json(self):
        s = self.sesion
        mods = {}
        for id_ in s["ficheros"]:
            m = self.m.modulos[id_]
            mods[id_] = {"tipo": m.TIPO, "nombre": m.nombre, "fichero": id_ + ".csv",
                         "cols": m.COLS, "meta": m.meta()}
        # las salidas no graban CSV, pero sus umbrales sirven en la web
        for m in self.m.modulos.values():
            if m.CLASE == "salida" and m.corriendo():
                mods[m.id] = {"tipo": m.TIPO, "nombre": m.nombre, "meta": m.meta()}
        datos = {"sesion": s["nombre"], "inicio": s["inicio"], "fin": s.get("fin"),
                 "simulada": self.m.hw.sim, "modulos": mods}
        if s.get("moto"):
            datos["moto"] = s["moto"]
        tmp = os.path.join(s["ruta"], "sesion.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        os.replace(tmp, os.path.join(s["ruta"], "sesion.json"))


# ------------------------------------------------------------------ maestro ---

class Maestro:
    def __init__(self, args):
        self.args = args
        self.t0 = pc()
        self.ruta_cfg = args.config
        self.cfg = leer_config(args.config)
        self.hw = modulos.Hardware(sim=args.sim)
        self.lock = threading.RLock()
        self.subs = {}
        self.modulos = modulos.crear(self.cfg["modulos"], self.hw, self)
        self.grabador = Grabador(args.dir, self)
        self.sincro = None          # repo de datos (sincro.py), si esta configurado
        self.tunel = None
        self.live = None
        self._cont = {m: (0, 0) for m in self.modulos}
        self._ritmo = {m: (0.0, 0.0) for m in self.modulos}

    # ------------------------------------------------- bus de los modulos ---

    def reloj(self):
        return pc() - self.t0

    def modulo(self, id_):
        if id_ not in self.modulos:
            raise ValueError(f"no existe el modulo {id_}")
        return self.modulos[id_]

    def publicar(self, mod, t, valores):
        self.grabador.fila(mod, t, valores)
        if self.live:
            self.live.publish(mod.id, [round(t, 4)] + list(valores))
        for _, idx, fn in self.subs.get(mod.id, ()):
            try:
                fn(t, valores[idx])
            except Exception as e:      # una salida nunca debe tirar un sensor
                print(f"\n[{mod.id}] error en un suscriptor: {e}")

    def suscribir(self, fuente, columna, fn):
        mod = self.modulo(fuente)
        if columna not in mod.COLS[1:]:
            raise ValueError(f"{fuente} no tiene la columna {columna}")
        token = object()
        with self.lock:
            # lista nueva: publicar() recorre la anterior sin bloqueo
            self.subs[fuente] = self.subs.get(fuente, []) + \
                [(token, mod.COLS.index(columna) - 1, fn)]
        return fuente, token

    def desuscribir(self, sub):
        fuente, token = sub
        with self.lock:
            self.subs[fuente] = [s for s in self.subs.get(fuente, []) if s[0] is not token]

    def set_vivo(self, id_, estado):
        if self.live:
            self.live.set_vivo(id_, estado)

    # ----------------------------------------------- deteccion y arranque ---

    def detectar(self):
        for m in self.modulos.values():
            if not m.DETECTABLE or m.corriendo():
                continue
            if self.hw.sim:
                m.deteccion = ("si", "simulado")
                continue
            try:
                m.deteccion = m.detectar()
            except Exception as e:
                m.deteccion = ("error", str(e) or e.__class__.__name__)

    def debe_correr(self, m):
        a = m.cfg.get("activo", "auto")
        if a in (True, "true", "si"):
            return True
        if a in (False, "false", "no"):
            return False
        return self.hw.sim or m.deteccion[0] == "si"

    def aplicar(self):
        """Arranca / para cada modulo segun su 'activo' y la deteccion."""
        with self.lock:
            orden = sorted(self.modulos.values(), key=lambda m: m.CLASE == "salida")
            for m in reversed(orden):            # primero se paran las salidas
                if m.corriendo() and not self.debe_correr(m):
                    m.detener()
            for m in orden:                      # primero arrancan los sensores
                if not m.corriendo() and self.debe_correr(m) and m.estado != "error":
                    m.arrancar()

    def apagar(self):
        """Boton mantenido: cierra la grabacion y apaga la raspi (se puede quitar
        la corriente sin estropear la tarjeta). Al parar, systemd sube la sesion."""
        if getattr(self, "_apagando", False):
            return
        self._apagando = True

        def hilo():
            pantalla = self.modulos.get("pantalla")
            avisar = (lambda *a: pantalla.avisar(*a)) if pantalla is not None else (lambda *a: None)
            if self.grabador.activa():
                avisar("ESPERE", ["GUARDANDO DATOS", "DE LA GRABACION"])
                print("\nBoton mantenido: parando la grabacion")
                self.grabador.parar()
                time.sleep(1.5)
            avisar("APAGANDO", ["DESCONECTA CUANDO", "EL LED VERDE DE LA", "RASPI SE APAGUE"])
            print("\nBoton mantenido: apagando la raspi")
            time.sleep(2)
            if self.hw.sim or os.geteuid() != 0:
                print("(simulado o sin root: no se apaga)")
                return
            import subprocess
            subprocess.run(["systemctl", "poweroff"], check=False)

        threading.Thread(target=hilo, name="apagar", daemon=True).start()

    def set_activo(self, id_, valor):
        m = self.modulo(id_)
        if valor not in (True, False, "auto"):
            raise ValueError("activo: true, false o 'auto'")
        with self.lock:
            m.cfg["activo"] = valor
            self.cfg["modulos"].setdefault(id_, {})["activo"] = valor
            guardar_config(self.ruta_cfg, self.cfg)
            if m.estado == "error":
                m.estado = "parado"              # reintentar al activarlo a mano
            if valor == "auto" and not m.corriendo():
                self.detectar()
        self.aplicar()

    # ------------------------------------------------------------ web ---

    def peticion(self, ruta, cuerpo):
        p = ruta.strip("/").split("/")[1:]       # sin 'api'
        if p == ["detectar"]:
            self.detectar()
            self.aplicar()
        elif p == ["auto"]:                      # todos a automatico
            for id_ in self.modulos:
                self.modulos[id_].cfg["activo"] = "auto"
                self.cfg["modulos"].setdefault(id_, {})["activo"] = "auto"
                if self.modulos[id_].estado == "error":
                    self.modulos[id_].estado = "parado"
            guardar_config(self.ruta_cfg, self.cfg)
            self.detectar()
            self.aplicar()
        elif p in (["alta"], ["alta", "consultar"]):
            if not self.sincro:
                raise ValueError("este sistema no tiene repo de datos (sincro.py iniciar)")
            if p == ["alta"]:
                return self.sincro.alta(cuerpo.get("inv"), cuerpo.get("secreto") or "",
                                        cuerpo.get("password"))
            return self.sincro.consultar_alta(cuerpo.get("inv"))
        elif p == ["sesion", "borrar"]:          # la copia de la raspi
            return self.borrar_sesion(cuerpo.get("nombre"))
        elif p in (["nube", "borrar"], ["nube", "editar"]):   # las del repo de datos
            if not self.sincro:
                raise ValueError("este sistema no tiene repo de datos")
            if p[1] == "editar":
                return self.sincro.editar_en_nube(cuerpo.get("id"), cuerpo.get("titulo"), cuerpo.get("nota"))
            return self.sincro.borrar_de_nube(cuerpo.get("id"))
        elif p == ["luces"]:                     # configuracion de luces y alertas
            return self.guardar_luces(cuerpo.get("config"))
        elif p == ["moto"]:                      # ficha de la moto
            ficha = moto_mod.validar(cuerpo.get("moto"))
            with self.lock:
                self.cfg["moto"] = ficha
                cambios = moto_mod.aplicar(ficha, self.modulos, self.cfg["modulos"])
                guardar_config(self.ruta_cfg, self.cfg)
            self.publicar_estado()
            return {"ok": True, "aplicado": cambios}
        elif p == ["luces", "probar"]:
            color, efecto = cuerpo.get("color"), cuerpo.get("efecto", "fijo")
            if color not in luces_mod.COLORES or efecto not in luces_mod.EFECTOS:
                raise ValueError("color o efecto no valido")
            tira = self.modulos.get("tira")
            if tira is None or not tira.corriendo():
                raise ValueError("la tira de luces no esta en marcha")
            tira.probar(color, efecto)
            return {"ok": True}
        elif p == ["grabar"]:
            if cuerpo.get("grabar"):
                self.grabador.iniciar()
            else:
                self.grabador.parar()
        elif len(p) == 2 and p[0] == "modulo":
            self.set_activo(p[1], cuerpo["activo"])
        elif len(p) == 3 and p[0] == "modulo" and p[2] == "accion":
            m = self.modulo(p[1])
            if not m.corriendo():
                raise ValueError(f"{m.nombre} no esta en marcha")
            msg = m.accion(cuerpo["accion"])
            self.publicar_estado()
            return {"ok": True, "mensaje": msg}
        else:
            raise ValueError(f"ruta desconocida: {ruta}")
        self.publicar_estado()
        return {"ok": True}

    # ------------------------------------------------- luces y alertas ---

    def luces(self):
        """Para el cuadro de la web: configuracion, catalogo y plantillas."""
        pantalla, tira = self.modulos.get("pantalla"), self.modulos.get("tira")
        cfg = pantalla.cfg.get("luces") if pantalla is not None else None
        cfg = dict(cfg) if cfg is not None else luces_mod.por_defecto()
        cfg.setdefault("resumen", list(luces_mod.RESUMEN_DEFECTO))     # guardadas antes de existir
        return {
            "config": cfg,
            "catalogo": [{"id": k, "nombre": n, "unidad": u, "pagina": p,
                          "si_no": k in luces_mod.SI_NO, "evento": k in luces_mod.EVENTOS}
                         for k, (n, u, p) in luces_mod.CATALOGO.items()],
            "paginas": [{"id": p[0], "titulo": p[1]} for p in PAGINAS],
            "colores": luces_mod.COLORES, "efectos": luces_mod.EFECTOS,
            "resumen_opciones": [{"id": k, "nombre": n, "rotulo": r}
                                 for k, (r, _, n) in luces_mod.RESUMEN.items()],
            "plantillas": {k: {"nombre": v["nombre"],
                               "config": {"paginas": v["paginas"], "alertas": v["alertas"],
                                          "resumen": v["resumen"]}}
                           for k, v in luces_mod.PLANTILLAS.items()},
            "leds": int(tira.cfg["num"]) if tira is not None else 0,
            "tira": bool(tira is not None and tira.corriendo()),
            "pantalla": bool(pantalla is not None and pantalla.corriendo()),
        }

    def guardar_luces(self, cfg):
        cfg = luces_mod.validar(cfg, [p[0] for p in PAGINAS])
        with self.lock:
            self.cfg["modulos"].setdefault("pantalla", {})["luces"] = cfg
            guardar_config(self.ruta_cfg, self.cfg)
            pantalla = self.modulos.get("pantalla")
            if pantalla is not None:
                pantalla.set_luces(cfg)
        return {"ok": True}

    def estado(self):
        mods = []
        for m in self.modulos.values():
            hz, perd = self._ritmo[m.id]
            mods.append({
                "id": m.id, "tipo": m.TIPO, "nombre": m.nombre, "clase": m.CLASE,
                "activo": m.cfg.get("activo", "auto"), "corriendo": m.corriendo(),
                "estado": m.estado, "error": m.error, "aviso": m.aviso,
                "deteccion": list(m.deteccion), "detectable": m.DETECTABLE,
                "pines": m.pines(), "cols": m.COLS, "meta": m.meta(),
                "acciones": [{"id": k, "texto": v} for k, v in m.ACCIONES.items()],
                "hz": round(hz, 1), "perdidas_pct": round(perd, 1),
            })
        s = self.grabador.sesion
        return {
            "sim": self.hw.sim, "t": round(self.reloj(), 2), "modulos": mods,
            "moto": self.cfg.get("moto") or {},
            "sesion": None if s is None else {
                "nombre": s["nombre"], "inicio": s["inicio"],
                "duracion_s": round(self.reloj() - s["t0"], 1),
                "ficheros": sorted(s["ficheros"])},
            "sincro": self.sincro.estado() if self.sincro else None,
            "tunel": self.tunel.url if self.tunel else None,
        }

    def publicar_estado(self):
        if self.live:
            est = self.estado()
            est.pop("t")      # que no cambie cada vez solo por el reloj
            self.live.set_estado(est)

    # ------------------------------------------------------------ bucle ---

    def _cada_segundo(self, dt):
        metas = []
        for m in self.modulos.values():
            n0, p0 = self._cont[m.id]
            dn, dp = m.n - n0, m.perdidas - p0
            self._cont[m.id] = (m.n, m.perdidas)
            self._ritmo[m.id] = (dn / dt, 100.0 * dp / dn if dn else 0.0)
            metas.append(m.meta_ver)
        if metas != getattr(self, "_metas", None):
            self._metas = metas
            self.grabador.actualizar_json()
        self.publicar_estado()

    def linea_estado(self):
        partes = []
        for m in self.modulos.values():
            if not m.corriendo() and m.estado != "error":
                continue
            hz, perd = self._ritmo[m.id]
            if m.estado == "error":
                txt = "ERROR"
            elif m.estado == "calibrando":
                txt = "calibrando"
            elif m.CLASE == "salida":
                txt = "on"
            elif m.TIPO == "boton":
                txt = f"{m.n} pulsaciones"
            else:
                txt = f"{hz:.0f}Hz" + (f" {perd:.0f}%perd" if perd >= 1 else "")
            partes.append(f"{m.id} {txt}")
        rec = "● REC " if self.grabador.activa() else ""
        return f"\r  t={self.reloj():7.1f}s  {rec}" + " · ".join(partes) + "   "

    def correr(self):
        a = self.args

        def parar(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, parar)

        os.makedirs(a.dir, exist_ok=True)
        try:
            self.sincro = sincro.cargar(
                a.dir, activa=lambda: self.grabador.sesion and self.grabador.sesion["nombre"])
        except Exception as e:      # sin repo de datos se graba igual, en local
            print(f"Repo de datos desactivado: {e}")
        if self.sincro:
            self.sincro.arrancar()
            print(f"Repo de datos: {self.sincro.cfg['repo']} (raspi {self.sincro.raspi})")
        # con repo de datos, la web solo para los usuarios de esta raspi
        acceso = self.sincro and Acceso(self.sincro.clave, self.sincro.raspi,
                                        self.sincro.cfg.get("nombre") or self.sincro.raspi,
                                        self.sincro.existe_usuario)
        https = a.https or bool(a.cert)
        self.live = LiveServer(a.puerto, data_dir=a.dir, https=https, cert=a.cert, key=a.key,
                               control=self, acceso=acceso or None).start()
        print(f"Web: {self.live.url()}" + ("   [SIMULADO]" if self.hw.sim else "") +
              ("" if acceso else "   (abierta: sin repo de datos no hay usuarios)"))
        if self.sincro:
            self.sincro.local = self.sincro.direccion = self.live.url().rstrip("/")
        if a.tunel:
            if acceso:
                self.tunel = Tunel(a.puerto, https, self._tunel_cambia).arrancar()
            else:
                print("Tunel desactivado: sin usuarios la web quedaria abierta a internet")
        self.detectar()
        imprimir_deteccion(self)
        self.aplicar()
        if not a.no_grabar:
            self.grabador.iniciar()
        self.publicar_estado()

        ult = pc()
        ult_fsync = ult
        try:
            while True:
                time.sleep(1.0)
                ahora = pc()
                self.grabador.volcar(fsync=ahora - ult_fsync >= 5.0)
                if ahora - ult_fsync >= 5.0:
                    ult_fsync = ahora
                self._cada_segundo(ahora - ult)
                ult = ahora
                if sys.stdout.isatty():  # con systemd el \r llenaria el journal
                    print(self.linea_estado(), end="", flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            print("\nParando...")
            for m in sorted(self.modulos.values(), key=lambda m: m.CLASE != "salida"):
                m.detener()
            self.grabador.parar()
            if self.sincro:
                self.sincro.detener()
            if self.tunel:
                self.tunel.detener()
            self.live.stop()
            self.hw.cerrar()
            if self.sincro:
                self.sincro.subir_al_parar()


    def _tunel_cambia(self, url):
        """Nueva direccion publica (o None si se cae): al repo, para la app."""
        if self.sincro:
            self.sincro.direccion = url or self.sincro.local
            self.sincro.avisar()
        self.publicar_estado()

    def borrar_sesion(self, nombre):
        if not re.match(r"^[\w-]+$", nombre or ""):
            raise ValueError("sesion no valida")
        s = self.grabador.sesion
        if s and s["nombre"] == nombre:
            raise ValueError("se esta grabando: para la grabacion antes de borrarla")
        ruta = os.path.join(self.args.dir, nombre)
        if not os.path.isdir(ruta):
            raise ValueError("esa sesion ya no esta en el sistema")
        shutil.rmtree(ruta)
        return {"ok": True, "mensaje": "Borrada del sistema: " + nombre}

    def subidas(self):
        """Sesiones locales ya en la nube (None si no hay repo de datos)."""
        try:
            return self.sincro.al_dia() if self.sincro else None
        except OSError:
            return None

    def usuario_para_web(self, usuario):
        return self.sincro.usuario_para_web(usuario) if self.sincro else None


def imprimir_deteccion(maestro):
    print("\nModulos:")
    for m in maestro.modulos.values():
        est, detalle = m.deteccion
        marca = {"si": "✔", "no": "·", "manual": "?", "error": "✖"}.get(est, " ")
        activo = m.cfg.get("activo", "auto")
        va = "ARRANCA" if maestro.debe_correr(m) else "-"
        print(f"  {marca} {m.id:12} {va:8} activo={str(activo):5}  {m.pines():44} {detalle}")
    print()


def main():
    p = argparse.ArgumentParser(description="Telemetria de moto: programa maestro")
    p.add_argument("--sim", action="store_true",
                   help="todos los modulos simulados (sin hardware)")
    p.add_argument("--detectar", action="store_true",
                   help="detectar los modulos conectados y salir")
    p.add_argument("--demo-pantalla", action="store_true",
                   help="probar solo la pantalla OLED: todas sus paginas con datos "
                        "simulados, una cada --periodo s")
    p.add_argument("--periodo", type=float, default=2.0,
                   help="segundos por pagina en --demo-pantalla (def. 2)")
    p.add_argument("--png", metavar="CARPETA",
                   help="con --demo-pantalla: guardar las paginas en PNG en vez de mostrarlas")
    p.add_argument("--no-grabar", action="store_true",
                   help="no grabar al arrancar (se graba con el boton de la web)")
    p.add_argument("--dir", default=os.path.join(AQUI, "datos"),
                   help="carpeta de las sesiones (def. ./datos)")
    p.add_argument("--config", default=os.path.join(AQUI, "telemetria.json"),
                   help="configuracion de modulos (def. ./telemetria.json)")
    p.add_argument("--puerto", type=int, default=8081, help="puerto de la web (def. 8081)")
    p.add_argument("--tunel", action="store_true",
                   help="web tambien por internet (tunel rapido de Cloudflare, ver tunel.py); "
                        "solo con repo de datos, para que pida usuario")
    p.add_argument("--https", action="store_true",
                   help="web por HTTPS con certificado autofirmado (./certs)")
    p.add_argument("--cert", help="certificado propio (PEM)")
    p.add_argument("--key", help="clave privada del certificado propio")
    args = p.parse_args()

    if args.demo_pantalla:
        from modulos import pantalla
        cfg = leer_config(args.config)["modulos"].get("pantalla", {})
        pantalla.demo(png=args.png, periodo=args.periodo, cfg=cfg)
        return

    maestro = Maestro(args)
    if args.detectar:
        maestro.detectar()
        imprimir_deteccion(maestro)
        maestro.hw.cerrar()
        return
    maestro.correr()


if __name__ == "__main__":
    sys.exit(main())
