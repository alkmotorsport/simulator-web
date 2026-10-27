#!/usr/bin/env python3
"""
Sube las sesiones grabadas al repo privado de datos (GitHub), cifradas, y da
de alta a los usuarios invitados por el administrador.

Cada Raspberry tiene una clave propia (AES-256) que nunca sale de ella. Con
esa clave cifra cada sesion (gzip + AES-GCM) antes de hacer push. Un usuario
es la misma clave cifrada con su contrasena (PBKDF2-SHA256): entrar en la app
es descifrarla, asi que solo ve los datos de su Raspberry.

Repo de datos (lo leen la app y el portal de admin):
  usuarios/<usuario>.json         {"usuario", "raspis": {<raspi>: clave de esa raspi
                                  cifrada con su contrasena}} (uno puede tener varias)
  invitaciones/<id>.json          alta pendiente: usuario, raspi, sha256(secreto)
  raspis/<raspi>/raspi.json       nombre y direcciones: la publica (tunel) y la local
  raspis/<raspi>/indice.enc       lista de sesiones (cifrada)
  raspis/<raspi>/sesiones/<s>.enc una sesion: sus CSV y sesion.json (cifrada)

En la Pi (fuera del repo de codigo, solo root):
  /etc/telemetria/sincro.json     repo y nombre de esta raspi
  /etc/telemetria/clave           la clave de los datos: si se pierde, lo subido
                                  solo se recupera con la contrasena de un usuario
  /etc/telemetria/token           token de GitHub (fine-grained, solo el repo de
                                  datos, Contents: Read and write): push por HTTPS
  /var/lib/telemetria/            copia del repo y lo ya subido
(Con un repo git@... en vez de https se usa la clave SSH /etc/telemetria/deploy_key.)

Uso:
  sudo python3 sincro.py iniciar --raspi moto1 --nombre "Moto de Alberto"
  sudo python3 sincro.py token        # poner o renovar el token (caduca)
  sudo python3 sincro.py ahora        # subir ya lo pendiente
  sudo python3 sincro.py estado
  sudo python3 sincro.py recuperar --usuario alberto   # rehace /etc/telemetria/clave
telemetria.py lo arranca solo si existe /etc/telemetria/sincro.json.
"""

import argparse
import base64
import getpass
import gzip
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime

CONF_DIR = os.environ.get("TELEMETRIA_CONF", "/etc/telemetria")   # (otro, para pruebas)
VAR_DIR = os.environ.get("TELEMETRIA_VAR", "/var/lib/telemetria")
REPO_DEF = "https://github.com/alkmotorsport/telemetry-data.git"
RAMA = "main"
ITER = 600000                  # PBKDF2: recomendacion OWASP para SHA-256
MAGIA = b"TLM1"                # cabecera de los .enc: version del formato
PASS_MIN = 10
MAX_ENC = 95 * 1024 * 1024     # GitHub rechaza ficheros de mas de 100 MB
PERIODO = 600                  # s entre reintentos (sin internet en el circuito)
TITULO_MAX = 80                # nombre y descripcion de una sesion de la nube
NOTA_MAX = 500
BORRADA = "borrada"             # en subidas.json: borrada de la nube a proposito
ID_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


def b64(b):
    return base64.b64encode(b).decode()


def unb64(s):
    return base64.b64decode(s)


# --------------------------------------------------------------- cifrado ---
# El mismo formato lo descifra web/cripto.js.

def _aesgcm(clave):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise RuntimeError("falta cryptography (sudo apt install python3-cryptography)")
    return AESGCM(clave)


def cifrar(clave, datos, ruta):
    """gzip + AES-GCM. 'ruta' (dentro del repo) va como dato asociado: un
    fichero copiado a otra ruta no se descifra."""
    iv = os.urandom(12)
    return MAGIA + iv + _aesgcm(clave).encrypt(iv, gzip.compress(datos, 6), ruta.encode())


def descifrar(clave, blob, ruta):
    if blob[:4] != MAGIA:
        raise ValueError("formato desconocido")
    return gzip.decompress(_aesgcm(clave).decrypt(blob[4:16], blob[16:], ruta.encode()))


def _aad_usuario(usuario, raspi):
    return "usuario:{}|raspi:{}".format(usuario, raspi).encode()


def envolver_clave(clave, usuario, raspi, password):
    """La entrada de una raspi en usuarios/<usuario>.json."""
    sal, iv = os.urandom(16), os.urandom(12)
    kek = hashlib.pbkdf2_hmac("sha256", password.encode(), sal, ITER, 32)
    ct = _aesgcm(kek).encrypt(iv, clave, _aad_usuario(usuario, raspi))
    return {"kdf": "PBKDF2-SHA256", "iter": ITER, "sal": b64(sal), "iv": b64(iv),
            "clave": b64(ct), "creado": datetime.now().isoformat(timespec="seconds")}


def abrir_clave(usuario, raspi, e, password):
    kek = hashlib.pbkdf2_hmac("sha256", password.encode(), unb64(e["sal"]), e["iter"], 32)
    return _aesgcm(kek).decrypt(unb64(e["iv"]), unb64(e["clave"]), _aad_usuario(usuario, raspi))


def entradas(u):
    """{raspi: entrada} de un fichero de usuario (tambien el formato antiguo,
    de una sola raspi, con la entrada en la raiz)."""
    if "raspis" in u:
        return dict(u["raspis"])
    if "raspi" in u:
        return {u["raspi"]: {k: u[k] for k in ("kdf", "iter", "sal", "iv", "clave", "creado") if k in u}}
    return {}


# ---------------------------------------------------------- sincronizador ---

class Sincro:
    def __init__(self, data_dir, conf_dir=CONF_DIR, var_dir=VAR_DIR, activa=None):
        self.data_dir = data_dir
        self.conf_dir = conf_dir
        self.repo = os.path.join(var_dir, "repo-datos")
        self.f_subidas = os.path.join(var_dir, "subidas.json")
        self.activa = activa or (lambda: None)   # nombre de la sesion que se graba
        with open(os.path.join(conf_dir, "sincro.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.raspi = self.cfg["raspi"]
        self.direccion = None                    # web publica (tunel) o local: telemetria.py
        self.local = None                        # web en la wifi de la raspi
        self.usuarios = {}                       # usuario -> su entrada para esta raspi
        self.clave = None                        # sin ella solo vale 'recuperar'
        ruta = os.path.join(conf_dir, "clave")
        if os.path.exists(ruta):
            with open(ruta, "rb") as f:
                self.clave = f.read()
            if len(self.clave) != 32:
                raise RuntimeError(ruta + " no es una clave de 32 bytes")
        self.lock = threading.Lock()             # una operacion de git cada vez
        self.evento = threading.Event()
        self.parado = False
        self.ultima = None                       # fecha de la ultima sincro buena
        self.error = None
        self.pendientes = None
        self._leer_usuarios()                    # sin red vale la copia que haya

    # ------------------------------------------------------------- git ---

    def _git(self, *args, cwd=None, check=True):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        opciones = ["-c", "user.name=raspi " + self.raspi,
                    "-c", "user.email=raspi-{}@telemetria".format(self.raspi)]
        if self.cfg["repo"].startswith("https://"):
            # el token va en una cabecera de cada orden: no queda en .git/config
            token = leer_token(self.conf_dir)
            if token:
                auth = b64("x-access-token:{}".format(token).encode())
                opciones += ["-c", "http.extraheader=Authorization: Basic " + auth]
        else:
            clave = os.path.join(self.conf_dir, "deploy_key")
            if os.path.exists(clave):
                env["GIT_SSH_COMMAND"] = ("ssh -i {} -o IdentitiesOnly=yes "
                                          "-o StrictHostKeyChecking=accept-new".format(clave))
        r = subprocess.run(["git"] + opciones + list(args), cwd=cwd or self.repo, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=300)
        if check and r.returncode:
            raise RuntimeError("git {}: {}".format(args[0], r.stdout.strip()[-300:]))
        return r

    def _actualizar(self):
        """Deja la copia local igual que el remoto (lo local se rehace siempre
        desde datos/, asi que no hay nada que fusionar)."""
        if not os.path.isdir(os.path.join(self.repo, ".git")):
            if os.path.exists(self.repo):
                shutil.rmtree(self.repo)
            os.makedirs(os.path.dirname(self.repo), exist_ok=True)
            self._git("clone", "--depth", "1", self.cfg["repo"], self.repo,
                      cwd=os.path.dirname(self.repo))
        self._git("remote", "set-url", "origin", self.cfg["repo"])   # si cambia (ssh -> https)
        r = self._git("fetch", "--depth", "1", "origin", RAMA, check=False)
        if r.returncode == 0:
            self._git("checkout", "-B", RAMA, "FETCH_HEAD")
            self._git("reset", "--hard", "FETCH_HEAD")
            self._git("clean", "-fdq")
        elif "couldn't find remote ref" in r.stdout.lower():
            self._git("checkout", "--orphan", RAMA, check=False)  # repo recien creado
        else:
            raise RuntimeError("git fetch: " + r.stdout.strip()[-300:])
        self._leer_usuarios()

    def _leer_usuarios(self):
        """Copia en memoria de los usuarios de esta raspi: la web los consulta
        sin chocar con git (que rehace la carpeta en cada sincronizacion)."""
        dir_ = self._ruta("usuarios")
        us = {}
        if os.path.isdir(dir_):
            for f in os.listdir(dir_):
                if not f.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(dir_, f), encoding="utf-8") as fh:
                        e = entradas(json.load(fh)).get(self.raspi)
                except (OSError, ValueError):
                    continue
                if e:
                    us[f[:-5]] = e
        self.usuarios = us

    def existe_usuario(self, usuario):
        return usuario in self.usuarios

    def usuario_para_web(self, usuario):
        """Lo que necesita la web de la Pi para entrar: su clave cifrada."""
        e = self.usuarios.get(usuario)
        return e and {"usuario": usuario, "raspis": {self.raspi: e}}

    def _publicar(self, mensaje, preparar):
        """preparar() escribe en la copia; commit + push, y si otra raspi ha
        subido antes se actualiza y se repite."""
        for intento in range(4):
            self._actualizar()
            resultado = preparar()
            self._git("add", "-A")
            if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
                return resultado, False
            self._git("commit", "-q", "-m", mensaje)
            r = self._git("push", "-q", "origin", "HEAD:" + RAMA, check=False)
            if r.returncode == 0:
                return resultado, True
            if "rejected" not in r.stdout and "fetch first" not in r.stdout:
                raise RuntimeError("git push: " + r.stdout.strip()[-300:])
            time.sleep(2 + intento * 3)
        raise RuntimeError("git push: rechazado varias veces")

    def _ruta(self, rel):
        return os.path.join(self.repo, *rel.split("/"))

    def _leer(self, rel):
        try:
            with open(self._ruta(rel), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def _escribir(self, rel, datos):
        ruta = self._ruta(rel)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(datos)

    def _json(self, obj):
        return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()

    # -------------------------------------------------------- sesiones ---

    def _sid(self, nombre):
        """Id de la sesion en el repo: no deja ver la fecha sin la clave."""
        return hmac.new(self.clave, nombre.encode(), hashlib.sha256).hexdigest()[:20]

    def _sesiones_locales(self):
        """{nombre: huella} de las sesiones terminadas en datos/."""
        out = {}
        if not os.path.isdir(self.data_dir):
            return out
        activa = self.activa()
        for nombre in sorted(os.listdir(self.data_dir)):
            ruta = os.path.join(self.data_dir, nombre)
            if nombre == activa or not os.path.isdir(ruta):
                continue
            fich = sorted(f for f in os.listdir(ruta) if f.endswith((".csv", ".json")))
            if not any(f.endswith(".csv") for f in fich):
                continue
            huella = [(f, os.path.getsize(os.path.join(ruta, f)),
                       int(os.path.getmtime(os.path.join(ruta, f)))) for f in fich]
            out[nombre] = hashlib.sha256(repr(huella).encode()).hexdigest()
        return out

    def _leer_subidas(self):
        try:
            with open(self.f_subidas, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _guardar_subidas(self, hechas):
        """{sesion: huella de lo subido, o BORRADA si se borro de la nube}."""
        os.makedirs(os.path.dirname(self.f_subidas), exist_ok=True)
        with open(self.f_subidas + ".tmp", "w", encoding="utf-8") as f:
            json.dump(hechas, f, indent=1)
        os.replace(self.f_subidas + ".tmp", self.f_subidas)

    def al_dia(self):
        """Sesiones locales cuya copia en la nube coincide con la local."""
        hechas = self._leer_subidas()
        return {n for n, h in self._sesiones_locales().items() if hechas.get(n) == h}

    def editar_en_nube(self, sid, titulo, nota):
        """Nombre y descripcion de una sesion de la nube (van en el indice, cifrados)."""
        if not re.match(r"^[0-9a-f]{20}$", sid or ""):
            raise ValueError("sesion no valida")
        titulo = " ".join(str(titulo or "").split())[:TITULO_MAX]
        nota = str(nota or "").strip()[:NOTA_MAX]
        ri = "raspis/{}/indice.enc".format(self.raspi)

        def preparar():
            blob = self._leer(ri)
            sesiones = json.loads(descifrar(self.clave, blob, ri))["sesiones"] if blob else []
            s = next((x for x in sesiones if x["id"] == sid), None)
            if s is None:
                raise ValueError("esa sesion ya no esta en la nube")
            for k, v in (("titulo", titulo), ("nota", nota)):
                if v:
                    s[k] = v
                else:
                    s.pop(k, None)
            self._escribir(ri, cifrar(self.clave, json.dumps({"sesiones": sesiones}, ensure_ascii=False).encode(), ri))
            return s["nombre"]

        with self.lock:
            nombre, _ = self._publicar("raspi {}: edita una sesion".format(self.raspi), preparar)
        return {"ok": True, "titulo": titulo, "nota": nota, "mensaje": "Guardado: " + (titulo or nombre)}

    def borrar_de_nube(self, sid):
        """Quita una sesion del repo de datos (y de su indice). La copia local,
        si la hay, se queda y no se vuelve a subir."""
        if not re.match(r"^[0-9a-f]{20}$", sid or ""):
            raise ValueError("sesion no valida")
        base = "raspis/" + self.raspi

        def preparar():
            ri = base + "/indice.enc"
            blob = self._leer(ri)
            sesiones = json.loads(descifrar(self.clave, blob, ri))["sesiones"] if blob else []
            borrada = [s for s in sesiones if s["id"] == sid]
            if not borrada:
                raise ValueError("esa sesion ya no esta en la nube")
            quedan = [s for s in sesiones if s["id"] != sid]
            self._escribir(ri, cifrar(self.clave, json.dumps({"sesiones": quedan}, ensure_ascii=False).encode(), ri))
            ruta = self._ruta("{}/sesiones/{}.enc".format(base, sid))
            if os.path.exists(ruta):
                os.remove(ruta)
            return borrada[0]["nombre"]

        with self.lock:
            nombre, _ = self._publicar("raspi {}: borra una sesion".format(self.raspi), preparar)
            hechas = self._leer_subidas()
            hechas[nombre] = BORRADA          # su copia local, si la hay, no se vuelve a subir
            self._guardar_subidas(hechas)
        return {"ok": True, "mensaje": "Borrada de la nube: " + nombre}

    def pendientes_locales(self):
        hechas = self._leer_subidas()
        return [n for n, h in self._sesiones_locales().items() if hechas.get(n) not in (h, BORRADA)]

    def sincronizar(self):
        with self.lock:
            locales = self._sesiones_locales()
            hechas = self._leer_subidas()
            nuevas = [n for n, h in locales.items() if hechas.get(n) not in (h, BORRADA)]
            base = "raspis/" + self.raspi

            def preparar():
                ri = base + "/indice.enc"
                blob = self._leer(ri)
                indice = json.loads(descifrar(self.clave, blob, ri)) if blob else {"sesiones": []}
                por_nombre = {s["nombre"]: s for s in indice["sesiones"]}
                for nombre in nuevas:
                    ent = self._empaquetar(base, nombre)
                    if ent:
                        viejo = por_nombre.get(nombre, {})
                        for k in ("titulo", "nota"):        # puestos por los usuarios
                            if viejo.get(k):
                                ent[k] = viejo[k]
                        por_nombre[nombre] = ent
                lista = sorted(por_nombre.values(), key=lambda s: s["nombre"], reverse=True)
                if lista != indice["sesiones"]:
                    self._escribir(ri, cifrar(self.clave, json.dumps(
                        {"sesiones": lista}, ensure_ascii=False).encode(), ri))
                self._raspi_json(base)

            _, subido = self._publicar("raspi {}: {} sesion(es)".format(
                self.raspi, len(nuevas)), preparar)
            for n in nuevas:
                hechas[n] = locales[n]
            self._guardar_subidas(hechas)
            self.ultima = datetime.now().isoformat(timespec="seconds")
            self.error = None
            self.pendientes = 0
            return nuevas if subido else []

    def _empaquetar(self, base, nombre):
        ruta = os.path.join(self.data_dir, nombre)
        ficheros = {}
        for f in sorted(os.listdir(ruta)):
            if f.endswith((".csv", ".json")):
                with open(os.path.join(ruta, f), encoding="utf-8", errors="replace") as fh:
                    ficheros[f] = fh.read()
        sj = {}
        try:
            sj = json.loads(ficheros.get("sesion.json") or "{}")
        except ValueError:
            pass
        rel = "{}/sesiones/{}.enc".format(base, self._sid(nombre))
        datos = json.dumps({"nombre": nombre, "ficheros": ficheros}, ensure_ascii=False).encode()
        blob = cifrar(self.clave, datos, rel)
        if len(blob) > MAX_ENC:
            print("\n[sincro] {}: {} MB cifrada, demasiado para GitHub; no se sube".format(
                nombre, len(blob) >> 20))
            return None
        self._escribir(rel, blob)
        csvs = [f[:-4] for f in ficheros if f.endswith(".csv")]
        return {"id": self._sid(nombre), "nombre": nombre, "inicio": sj.get("inicio"),
                "fin": sj.get("fin"), "simulada": bool(sj.get("simulada")),
                "sensores": csvs, "bytes": sum(len(t) for t in ficheros.values())}

    def _raspi_json(self, base):
        rel = base + "/raspi.json"
        viejo = json.loads(self._leer(rel) or b"{}")
        local = self.local or viejo.get("local") or \
            "https://{}:{}".format(_ip_local(), self.cfg.get("puerto", 8081))
        nuevo = dict(viejo, id=self.raspi, nombre=self.cfg.get("nombre") or self.raspi,
                     direccion=self.direccion or viejo.get("direccion") or local, local=local)
        nuevo.setdefault("creada", datetime.now().isoformat(timespec="seconds"))
        if nuevo != viejo:
            self._escribir(rel, self._json(nuevo))

    # ------------------------------------------------------------ altas ---

    def _invitacion(self, inv, secreto):
        if not re.match(r"^[0-9a-f]{8,32}$", inv or ""):
            raise ValueError("link de invitacion no valido")
        blob = self._leer("invitaciones/{}.json".format(inv))
        if blob is None:
            raise ValueError("la invitacion no existe o ya se ha usado")
        i = json.loads(blob)
        if i.get("raspi") != self.raspi:
            raise ValueError("esta invitacion es para el sistema '{}', y este es '{}'".format(
                i.get("raspi"), self.raspi))
        if i.get("caduca", 0) < time.time():
            raise ValueError("la invitacion ha caducado: pide otra al administrador")
        if secreto is not None and not hmac.compare_digest(
                hashlib.sha256(secreto.encode()).hexdigest(), i.get("hash", "")):
            raise ValueError("link de invitacion no valido")
        return i

    def consultar_alta(self, inv):
        with self.lock:
            self._actualizar()
            i = self._invitacion(inv, None)
            blob = self._leer("usuarios/{}.json".format(i["usuario"]))
            existe = blob is not None and self.raspi in entradas(json.loads(blob))
            return {"usuario": i["usuario"], "raspi": self.raspi,
                    "nombre_raspi": self.cfg.get("nombre") or self.raspi,
                    "cambio": existe, "pass_min": PASS_MIN}

    def alta(self, inv, secreto, password):
        """Crea (o rehace, si la invitacion es de cambio de contrasena) el
        usuario de la invitacion y la borra."""
        if len(password or "") < PASS_MIN:
            raise ValueError("la contrasena debe tener al menos {} caracteres".format(PASS_MIN))
        with self.lock:
            self._actualizar()
            usuario = self._invitacion(inv, secreto)["usuario"]
            if not ID_OK.match(usuario):
                raise ValueError("nombre de usuario no valido en la invitacion")
            entrada = envolver_clave(self.clave, usuario, self.raspi, password)

            def preparar():
                i = self._invitacion(inv, secreto)   # sigue ahi tras actualizar
                viejo = self._leer("usuarios/{}.json".format(usuario))
                ent = entradas(json.loads(viejo)) if viejo else {}
                if self.raspi in ent and not i.get("cambio"):
                    raise ValueError("{} ya es usuario de este sistema".format(usuario))
                ent[self.raspi] = entrada         # sus otras raspis se quedan igual
                self._escribir("usuarios/{}.json".format(usuario),
                               self._json({"usuario": usuario, "raspis": ent}))
                os.remove(self._ruta("invitaciones/{}.json".format(inv)))
                self._raspi_json("raspis/" + self.raspi)

            self._publicar("alta de {} en {}".format(usuario, self.raspi), preparar)
            self._leer_usuarios()
        return {"ok": True, "usuario": usuario,
                "mensaje": "Usuario {} listo: ya puedes entrar en la app".format(usuario)}

    # ------------------------------------------------------------ hilo ---

    def arrancar(self):
        threading.Thread(target=self._bucle, daemon=True, name="sincro").start()
        return self

    def avisar(self):
        """Sincronizar en cuanto se pueda (p. ej. al parar una grabacion)."""
        self.evento.set()

    def detener(self):
        self.parado = True
        self.evento.set()

    def subir_al_parar(self, limite=240):
        """Al cerrar telemetria.py: intenta subir ya la ultima sesion (si no,
        esperaria al siguiente arranque). Sin red falla rapido y no pasa nada."""
        resultado = {}

        def subir():
            try:
                resultado["ok"] = self.sincronizar()
            except Exception as e:
                resultado["error"] = str(e) or e.__class__.__name__

        if not self.pendientes_locales():
            return
        print("Subiendo la sesion al repo de datos (max. {} s)...".format(limite))
        h = threading.Thread(target=subir, daemon=True)
        h.start()
        h.join(limite)
        if "ok" in resultado:
            print("Subida: " + (", ".join(resultado["ok"]) or "nada nuevo"))
        else:
            print("No se pudo subir ({}): se subira en el proximo arranque".format(
                resultado.get("error", "tarda demasiado")))

    def _bucle(self):
        self.evento.wait(15)            # que arranque antes lo demas
        while not self.parado:
            self.evento.clear()
            try:
                subidas = self.sincronizar()
                if subidas:
                    print("\n[sincro] subidas: " + ", ".join(subidas))
            except Exception as e:      # sin internet, repo caido...: se reintenta
                self.error = str(e) or e.__class__.__name__
                try:
                    self.pendientes = len(self.pendientes_locales())
                except OSError:
                    pass
                print("\n[sincro] " + self.error)
            self.evento.wait(PERIODO)

    def estado(self):
        return {"raspi": self.raspi, "ultima": self.ultima, "error": self.error,
                "pendientes": self.pendientes}


def _ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def leer_token(conf_dir):
    try:
        with open(os.path.join(conf_dir, "token"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def guardar_token(conf_dir, token):
    ruta = os.path.join(conf_dir, "token")
    tmp = ruta + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token.strip() + "\n")
    os.replace(tmp, ruta)


def cargar(data_dir, activa=None, conf_dir=CONF_DIR, var_dir=VAR_DIR):
    """El sincronizador si esta raspi esta configurada; si no, None."""
    if not os.path.exists(os.path.join(conf_dir, "sincro.json")):
        return None
    s = Sincro(data_dir, conf_dir, var_dir, activa)
    if s.clave is None:
        raise RuntimeError("falta {}/clave: recuperala con 'sincro.py recuperar'".format(conf_dir))
    return s


# -------------------------------------------------------------------- CLI ---

def _iniciar(a):
    if not ID_OK.match(a.raspi):
        sys.exit("--raspi: minusculas, numeros, '.', '_' o '-' (2 a 32)")
    os.makedirs(a.conf, mode=0o700, exist_ok=True)
    ruta_cfg = os.path.join(a.conf, "sincro.json")
    cfg = {}
    if os.path.exists(ruta_cfg):
        with open(ruta_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("raspi") not in (None, a.raspi):
            sys.exit("esta raspi ya es '{}'; cambiarla dejaria sus usuarios sin datos".format(
                cfg["raspi"]))
    cfg.update(raspi=a.raspi, repo=a.repo, nombre=a.nombre or cfg.get("nombre") or a.raspi)
    with open(ruta_cfg, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    clave = os.path.join(a.conf, "clave")
    if not os.path.exists(clave):        # nunca se sobrescribe
        fd = os.open(clave, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(32))
        print("Clave de datos nueva en " + clave)
    https = a.repo.startswith("https://")
    if https and not leer_token(a.conf):
        if not sys.stdin.isatty():
            sys.exit("falta el token: sudo python3 sincro.py token")
        _pedir_token(a.conf)
    pub = None
    if not https:
        dk = os.path.join(a.conf, "deploy_key")
        if not os.path.exists(dk):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                            "telemetria-" + a.raspi, "-f", dk], check=True)
        with open(dk + ".pub") as f:
            pub = f.read().strip()
    s = Sincro(a.dir, a.conf, a.var)
    try:
        with s.lock:
            s._publicar("raspi {}: alta".format(a.raspi), lambda: s._raspi_json("raspis/" + a.raspi))
        print("Listo: raspi '{}' en {}".format(a.raspi, a.repo))
    except RuntimeError as e:
        print("\nNo puedo escribir en el repo ({}).".format(e))
        if pub:
            print("Anade esta clave como deploy key CON escritura (Allow write access) en\n"
                  "GitHub > repo de datos > Settings > Deploy keys, y vuelve a lanzar esto:\n")
            print("  " + pub + "\n")
        else:
            print("Revisa el token (sudo python3 sincro.py token): fine-grained, owner de la\n"
                  "organizacion, solo el repo de datos, Contents: Read and write.")
        return 1
    print("Guarda una copia de " + clave + " fuera de la Pi.")


def _pedir_token(conf_dir):
    token = getpass.getpass("Token de GitHub para esta raspi (no se ve al pegarlo): ").strip()
    if not token.startswith(("github_pat_", "ghp_")):
        sys.exit("eso no parece un token de GitHub")
    guardar_token(conf_dir, token)
    print("Token guardado en " + os.path.join(conf_dir, "token") + " (solo root)")


def _token(a):
    os.makedirs(a.conf, mode=0o700, exist_ok=True)
    _pedir_token(a.conf)
    try:
        s = cargar(a.dir, conf_dir=a.conf, var_dir=a.var)
    except RuntimeError as e:          # sin clave todavia (sistema nuevo o recuperado)
        print("Token guardado. Falta la clave de datos: " + str(e).split(": ", 1)[-1])
        return
    if s is None:
        return
    if not s.cfg["repo"].startswith("https://"):
        s.cfg["repo"] = REPO_DEF if "telemetry-data" in s.cfg["repo"] else s.cfg["repo"]
        with open(os.path.join(a.conf, "sincro.json"), "w", encoding="utf-8") as f:
            json.dump(s.cfg, f, indent=2, ensure_ascii=False)
        print("Repo cambiado a " + s.cfg["repo"])
    r = s._git("ls-remote", "--heads", s.cfg["repo"], cwd=a.conf, check=False)
    if r.returncode:
        sys.exit("El token no da acceso al repo: " + r.stdout.strip()[-200:])
    print("Token correcto: acceso a " + s.cfg["repo"])


def _recuperar(a):
    s = Sincro(a.dir, a.conf, a.var)
    with s.lock:
        s._actualizar()
    blob = s._leer("usuarios/{}.json".format(a.usuario))
    if blob is None:
        sys.exit("no existe el usuario " + a.usuario)
    e = entradas(json.loads(blob)).get(s.raspi)
    if e is None:
        sys.exit("{} no es usuario de la raspi {}".format(a.usuario, s.raspi))
    try:
        clave = abrir_clave(a.usuario, s.raspi, e, getpass.getpass("Contrasena de {}: ".format(a.usuario)))
    except Exception:
        sys.exit("contrasena incorrecta")
    if s.clave == clave:
        print("La clave ya era esa: nada que hacer.")
        return
    ruta = os.path.join(a.conf, "clave")
    if s.clave is not None:
        os.replace(ruta, ruta + ".vieja")
        print("La clave anterior queda en " + ruta + ".vieja")
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(clave)
    print("Clave recuperada en " + ruta)


def main():
    aqui = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="Sincronizacion con el repo privado de datos")
    p.add_argument("--dir", default=os.path.join(aqui, "datos"), help="carpeta de las sesiones")
    p.add_argument("--conf", default=CONF_DIR, help=argparse.SUPPRESS)
    p.add_argument("--var", default=VAR_DIR, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="orden")
    pi = sub.add_parser("iniciar", help="configurar esta raspi (claves y repo)")
    pi.add_argument("--raspi", required=True, help="id corto y fijo, p. ej. moto1")
    pi.add_argument("--nombre", help="nombre visible, p. ej. 'Moto de Alberto'")
    pi.add_argument("--repo", default=REPO_DEF, help="repo de datos (SSH)")
    sub.add_parser("token", help="poner o renovar el token de GitHub (push por https)")
    sub.add_parser("ahora", help="subir ya las sesiones pendientes")
    sub.add_parser("estado", help="que falta por subir")
    pr = sub.add_parser("recuperar", help="rehacer la clave con la contrasena de un usuario")
    pr.add_argument("--usuario", required=True)
    a = p.parse_args()

    if a.orden == "iniciar":
        return _iniciar(a)
    if a.orden == "recuperar":
        return _recuperar(a)
    if a.orden == "token":
        return _token(a)
    s = cargar(a.dir, conf_dir=a.conf, var_dir=a.var)
    if s is None:
        sys.exit("esta raspi no esta configurada: sudo python3 sincro.py iniciar --raspi <id>")
    if a.orden == "ahora":
        subidas = s.sincronizar()
        print("Subidas: " + ", ".join(subidas) if subidas else "Nada nuevo que subir.")
    else:
        pend = s.pendientes_locales()
        print("raspi {} · repo {}".format(s.raspi, s.cfg["repo"]))
        print("Pendientes de subir: " + (", ".join(pend) if pend else "ninguna"))


if __name__ == "__main__":
    sys.exit(main())
