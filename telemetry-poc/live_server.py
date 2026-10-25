#!/usr/bin/env python3
"""
Servidor web + tiempo real para la telemetria. Solo libreria estandar.

  /                 la web de ./web (sesiones grabadas y tiempo real)
  /stream           Server-Sent Events: 'estado' (modulos y sesion), 'vivo'
                    (semaforo, tira...) y mensajes con las muestras nuevas
                    de cada modulo: {"d": {"suspension": [[t, ...], ...]}}
  /api/vivo?c=<id>  lo mismo por consultas (el tunel retiene el SSE):
                    {"estado", "vivos", "d"} con lo nuevo para ese cliente
  /api/estado       estado actual de los modulos (JSON)
  /api/sesiones     sesiones guardadas en la carpeta de datos
  /files/<ruta>     CSV / sesion.json de una sesion, para postprocesar
  /api/ajustes      GET / POST: ajustes de la web (orden de los bloques,
                    opciones...) guardados en ajustes_web.json
  POST /api/...     control desde la web (solo con el maestro, telemetria.py):
                    modulo/<id> {"activo": true|false|"auto"},
                    modulo/<id>/accion {"accion": "calibrar"},
                    sesion/borrar {"nombre"}, nube/borrar {"id"} (borrar sesiones),
                    detectar, auto, grabar {"grabar": true|false},
                    alta/consultar {"inv"}, alta {"inv", "secreto", "password"}
                    (alta de un usuario invitado: ver sincro.py)

Con 'acceso' (telemetria.py, si la raspi tiene repo de datos) todo pide
entrar con un usuario de la raspi salvo la pagina, /api/raspi, el login y el
alta: ver acceso.py.

Suelto, para revisar sesiones guardadas en la Raspberry sin registrar:
  python3 live_server.py --dir datos --port 8081
  python3 live_server.py --dir datos --https      # para usarla desde tu dominio

HTTPS: con --https se genera (una vez, con openssl) un certificado autofirmado
en ./certs. En cada navegador hay que abrir https://<ip-de-la-pi>:8081/ una vez
y aceptar el aviso; despues la web de tu dominio ya puede conectar.
"""

import argparse
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(AQUI, "web")
CERT_DIR = os.path.join(AQUI, "certs")
AJUSTES = os.path.join(AQUI, "ajustes_web.json")
# fichero suelto (CSV antiguos) o dentro de la carpeta de una sesion
NOMBRE_OK = re.compile(r"^(?:[\w\-]+/)?[\w\-][\w.\-]*\.(?:csv|json|meta\.txt)$")
BACKLOG = 4000       # muestras por modulo que recibe un cliente al conectar
CLIENTE_OK = re.compile(r"^[\w-]{8,64}$")


def ip_local():
    """IP de la interfaz de red principal (no envia trafico)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def certificado_autofirmado(cert=None, key=None):
    """Devuelve (cert, key); si no se indican, crea uno en ./certs con openssl."""
    if cert and key:
        return cert, key
    cert = os.path.join(CERT_DIR, "telemetria.crt")
    key = os.path.join(CERT_DIR, "telemetria.key")
    ip = ip_local()
    if os.path.exists(cert) and os.path.exists(key):
        if _cubre_ip(cert, ip):
            return cert, key
        print(f"El certificado no es para la IP actual ({ip}): se hace otro "
              "(habra que aceptarlo de nuevo en cada navegador)")
    os.makedirs(CERT_DIR, exist_ok=True)
    host = socket.gethostname().split(".")[0]
    san = f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:{host}.local,DNS:localhost"
    print(f"Generando certificado autofirmado en {CERT_DIR} ...")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key, "-out", cert, "-days", "3650",
                    "-subj", "/CN=telemetria", "-addext", san],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chmod(key, 0o600)
    return cert, key


def _cubre_ip(cert, ip):
    r = subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-text"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    return r.returncode != 0 or re.search(r"IP Address:" + re.escape(ip) + r"\b", r.stdout) is not None


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Conexiones cortadas o TLS rechazado (certificado aun no aceptado en
        # ese navegador): normal, sin traza.
        if isinstance(sys.exc_info()[1], OSError):
            return
        super().handle_error(request, client_address)


class LiveServer:
    def __init__(self, port=8081, data_dir=".", web_dir=WEB_DIR, https=False,
                 cert=None, key=None, control=None, acceso=None):
        self.port = port
        self.tls = certificado_autofirmado(cert, key) if https else None
        self.data_dir = os.path.realpath(data_dir)
        self.web_dir = web_dir
        self.control = control      # el maestro: atiende los POST de la web
        self.acceso = acceso        # acceso.Acceso, o None: web abierta
        self.clientes = {}          # /api/vivo: id -> lo que ya tiene ese cliente
        self.lock = threading.Lock()
        self.bufs = {}              # id de modulo -> deque de filas
        self.seqs = {}              # id de modulo -> filas publicadas
        self.estado = {}
        self.estado_ver = 0
        self.vivos = {}             # id -> (version, estado instantaneo)
        self.vivo_ver = 0
        self.cerrando = False
        self.httpd = None

    # ------------------------------------------------- API para el maestro ---

    def publish(self, mod, fila):
        """Una muestra de un modulo: [t, valores...] en el orden de sus cols."""
        with self.lock:
            buf = self.bufs.get(mod)
            if buf is None:
                buf = self.bufs[mod] = deque(maxlen=BACKLOG)
                self.seqs[mod] = 0
            buf.append(fila)
            self.seqs[mod] += 1

    def set_estado(self, estado):
        """Estado de los modulos y de la grabacion; se envia solo si cambia."""
        with self.lock:
            if estado != self.estado:
                self.estado = estado
                self.estado_ver += 1

    def set_vivo(self, mod, estado):
        """Estado instantaneo de una salida (semaforo, tira); solo si cambia."""
        with self.lock:
            if self.vivos.get(mod, (0, None))[1] != estado:
                self.vivo_ver += 1
                self.vivos[mod] = (self.vivo_ver, estado)

    # -------------------------------------------------------------- server ---

    def start(self):
        srv = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=srv.web_dir, **k)

            def log_message(self, *a):
                pass

            def setup(self):
                if isinstance(self.request, ssl.SSLSocket):
                    self.request.settimeout(10)
                    self.request.do_handshake()
                    self.request.settimeout(None)
                super().setup()

            def end_headers(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                # Chrome: permite que una web publica (tu dominio) hable con
                # un equipo de la red local.
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                # '*' no incluye Authorization: hay que nombrarla
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()

            def _query(self):
                return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

            def _autorizado(self):
                if srv.acceso is None:
                    return True
                cab = self.headers.get("Authorization") or ""
                sesion = cab[7:].strip() if cab.startswith("Bearer ") else self._query().get("s")
                if srv.acceso.usuario(sesion):
                    return True
                srv._json(self, {"error": "entra con tu usuario de este sistema", "acceso": True}, 401)
                return False

            def do_GET(self):
                ruta = urlparse(self.path).path
                # publico: la pagina, quien es esta raspi y el login
                if ruta == "/api/raspi":
                    return srv._json(self, srv.acceso.info() if srv.acceso else {"acceso": False})
                if ruta == "/api/reto" and srv.acceso:
                    return srv._json(self, srv.acceso.reto())
                if ruta.startswith("/api/usuario/") and srv.control is not None:
                    u = srv.control.usuario_para_web(unquote(ruta[len("/api/usuario/"):]))
                    return srv._json(self, u or {"error": "no existe"}, 200 if u else 404)
                if (ruta.startswith("/api/") or ruta.startswith("/files/") or
                        ruta == "/stream") and not self._autorizado():
                    return
                if ruta == "/stream":
                    return srv._stream(self)
                if ruta == "/api/vivo":
                    return srv._vivo(self, self._query())
                if ruta == "/api/estado":
                    with srv.lock:
                        estado = srv.estado
                    return srv._json(self, estado)
                if ruta == "/api/ajustes":
                    return srv._leer_ajustes(self)
                if ruta in ("/api/sesiones", "/api/files"):
                    return srv._lista(self)
                if ruta.startswith("/files/"):
                    return srv._fichero(self, unquote(ruta[len("/files/"):]))
                return super().do_GET()

            def do_POST(self):
                ruta = urlparse(self.path).path
                if ruta == "/api/entrar" and srv.acceso:
                    try:
                        c = self._cuerpo()
                        return srv._json(self, srv.acceso.entrar(c.get("usuario"), c.get("reto"), c.get("firma")))
                    except (ValueError, PermissionError) as e:
                        return srv._json(self, {"error": str(e)}, 403)
                # el alta se protege con el secreto de la invitacion
                if not ruta.startswith("/api/alta") and not self._autorizado():
                    return
                if ruta == "/api/ajustes":
                    return srv._guardar_ajustes(self)
                if srv.control is None or not ruta.startswith("/api/"):
                    return srv._json(self, {"error": "solo con telemetria.py"}, 404)
                try:
                    return srv._json(self, srv.control.peticion(ruta, self._cuerpo()))
                except (KeyError, ValueError) as e:
                    return srv._json(self, {"error": str(e)}, 400)
                except RuntimeError as e:       # git / repo de datos
                    return srv._json(self, {"error": str(e)}, 503)

            def _cuerpo(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 65536:
                    raise ValueError("peticion demasiado grande")
                return json.loads(self.rfile.read(n) or b"{}") if n else {}

        self.httpd = _Servidor(("0.0.0.0", self.port), Handler)
        if self.tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*self.tls)
            # El handshake se hace en el hilo de cada peticion, no en accept().
            self.httpd.socket = ctx.wrap_socket(
                self.httpd.socket, server_side=True,
                do_handshake_on_connect=False)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.cerrando = True
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def url(self):
        return f"{'https' if self.tls else 'http'}://{ip_local()}:{self.port}/"

    def esperar(self, aviso):
        """Bloquea sirviendo la web hasta Ctrl+C / SIGTERM."""
        print(aviso)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _pendiente(self, cli):
        """Lo que le falta a un cliente: estado, vivos y filas nuevas. La
        primera vez, como mucho cli['max'] filas por modulo (historico)."""
        with self.lock:
            estado = None
            if cli["estado"] != self.estado_ver:
                estado, cli["estado"] = self.estado, self.estado_ver
            vivos = {m: e for m, (v, e) in self.vivos.items() if v > cli["vivo"]}
            cli["vivo"] = self.vivo_ver
            datos = {}
            for m, buf in self.bufs.items():
                nuevas = min(self.seqs[m] - cli["seqs"].get(m, 0), len(buf))
                if m not in cli["seqs"]:
                    nuevas = min(nuevas, cli.get("max", BACKLOG))
                if nuevas > 0:
                    datos[m] = list(buf)[-nuevas:]
                cli["seqs"][m] = self.seqs[m]
            return estado, vivos, datos

    def _stream(self, h):
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.end_headers()
        cli = {"estado": -1, "vivo": 0, "seqs": {}}
        ult_envio = time.monotonic()
        try:
            while not self.cerrando:
                estado, vivos, datos = self._pendiente(cli)
                trozos = []
                if estado is not None:
                    trozos.append(b"event: estado\ndata: " +
                                  json.dumps(estado).encode() + b"\n\n")
                if vivos:
                    trozos.append(b"event: vivo\ndata: " +
                                  json.dumps(vivos).encode() + b"\n\n")
                if datos:
                    trozos.append(b"data: " + json.dumps(
                        {"d": datos}, separators=(",", ":")).encode() + b"\n\n")
                ahora = time.monotonic()
                if not trozos and ahora - ult_envio > 5:
                    trozos.append(b": ping\n\n")  # mantiene viva la conexion
                if trozos:
                    h.wfile.write(b"".join(trozos))
                    h.wfile.flush()
                    ult_envio = ahora
                time.sleep(0.05)  # ~20 envios/s, varias muestras por envio
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _vivo(self, h, q):
        """Una consulta del modo en vivo: lo nuevo desde la anterior de ese
        cliente. Clientes sin consultar en 60 s se olvidan."""
        cid = q.get("c", "")
        if not CLIENTE_OK.match(cid):
            return self._json(h, {"error": "falta c=<id de cliente>"}, 400)
        ahora = time.monotonic()
        with self.lock:
            self.clientes = {k: v for k, v in self.clientes.items() if ahora - v["visto"] < 60}
            cli = self.clientes.get(cid)
            if cli is None:
                if len(self.clientes) >= 50:
                    return self._json(h, {"error": "demasiados clientes"}, 503)
                cli = self.clientes[cid] = {"estado": -1, "vivo": 0, "seqs": {},
                                            "max": max(0, min(int(q.get("n", 400)), BACKLOG))}
            cli["visto"] = ahora
        estado, vivos, datos = self._pendiente(cli)
        out = {"d": datos}
        if estado is not None:
            out["estado"] = estado
        if vivos:
            out["vivos"] = vivos
        self._json(h, out)

    def _json(self, h, obj, code=200):
        cuerpo = json.dumps(obj).encode()
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(cuerpo)))
        h.end_headers()
        h.wfile.write(cuerpo)

    def _leer_ajustes(self, h):
        try:
            with open(AJUSTES, encoding="utf-8") as f:
                return self._json(h, json.load(f))
        except (OSError, ValueError):
            return self._json(h, {})

    def _guardar_ajustes(self, h):
        n = int(h.headers.get("Content-Length") or 0)
        if not 0 < n <= 65536:
            return self._json(h, {"error": "ajustes vacios o demasiado grandes"}, 400)
        try:
            ajustes = json.loads(h.rfile.read(n))
            if not isinstance(ajustes, dict):
                raise ValueError("se esperaba un objeto JSON")
        except ValueError as e:
            return self._json(h, {"error": str(e)}, 400)
        tmp = AJUSTES + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ajustes, f, indent=2, ensure_ascii=False)
        os.replace(tmp, AJUSTES)
        return self._json(h, {"ok": True})

    def _lista(self, h):
        """Sesiones (carpetas con sesion.json o CSV) y CSV sueltos antiguos."""
        out = []
        # ya en la nube: la web avisa al borrar una que todavia no lo esta
        subidas = self.control.subidas() if self.control is not None else None
        if os.path.isdir(self.data_dir):
            for nombre in os.listdir(self.data_dir):
                ruta = os.path.join(self.data_dir, nombre)
                if os.path.isdir(ruta):
                    csvs = sorted(f for f in os.listdir(ruta) if f.endswith(".csv"))
                    if not csvs:
                        continue
                    out.append({
                        "name": nombre, "kind": "sesion", "files": csvs,
                        "json": os.path.exists(os.path.join(ruta, "sesion.json")),
                        "size": sum(os.path.getsize(os.path.join(ruta, f)) for f in csvs),
                        "mtime": max(os.path.getmtime(os.path.join(ruta, f)) for f in csvs),
                        "subida": None if subidas is None else nombre in subidas})
                elif nombre.endswith(".csv"):
                    st = os.stat(ruta)
                    out.append({"name": nombre, "kind": "csv", "size": st.st_size,
                                "mtime": st.st_mtime,
                                "meta": os.path.exists(ruta + ".meta.txt")})
        out.sort(key=lambda f: f["mtime"], reverse=True)
        self._json(h, out)

    def _fichero(self, h, nombre):
        ruta = os.path.realpath(os.path.join(self.data_dir, nombre))
        if (not NOMBRE_OK.match(nombre) or ".." in nombre or
                not ruta.startswith(self.data_dir + os.sep) or not os.path.isfile(ruta)):
            return self._json(h, {"error": "no encontrado"}, 404)
        with open(ruta, "rb") as f:
            cuerpo = f.read()
        h.send_response(200)
        h.send_header("Content-Type", "application/json" if nombre.endswith(".json")
                      else "text/plain; charset=utf-8")
        h.send_header("Content-Length", str(len(cuerpo)))
        h.end_headers()
        h.wfile.write(cuerpo)


def main():
    p = argparse.ArgumentParser(description="Web de telemetria (sin registrar)")
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--dir", default="datos", help="carpeta de las sesiones (def. datos)")
    p.add_argument("--https", action="store_true",
                   help="servir por HTTPS (certificado autofirmado en ./certs)")
    p.add_argument("--cert", help="certificado propio (PEM) en vez del autofirmado")
    p.add_argument("--key", help="clave privada del certificado propio")
    args = p.parse_args()
    srv = LiveServer(args.port, data_dir=args.dir, https=args.https or bool(args.cert),
                     cert=args.cert, key=args.key).start()
    srv.esperar(f"Web en {srv.url()}  (sesiones de {srv.data_dir}). Ctrl+C para parar.")


if __name__ == "__main__":
    main()
