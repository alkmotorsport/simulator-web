#!/usr/bin/env python3
"""
Servidor web + tiempo real para la telemetria. Solo libreria estandar.

  /             la web de ./web (graficas de CSV y en vivo)
  /stream       muestras en tiempo real como Server-Sent Events
  /api/files    lista de CSV guardados en la carpeta de datos
  /files/<f>    descarga de un CSV (o su .meta.txt) para postprocesado

Se usa desde el script de captura (--live) o suelto, para revisar sesiones
guardadas en la Raspberry sin registrar:
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
from urllib.parse import unquote, urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(AQUI, "web")
CERT_DIR = os.path.join(AQUI, "certs")
NOMBRE_OK = re.compile(r"^[\w.\-]+\.(csv|meta\.txt)$")


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
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    os.makedirs(CERT_DIR, exist_ok=True)
    host = socket.gethostname().split(".")[0]
    san = f"subjectAltName=IP:{ip_local()},IP:127.0.0.1,DNS:{host}.local,DNS:localhost"
    print(f"Generando certificado autofirmado en {CERT_DIR} ...")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key, "-out", cert, "-days", "3650",
                    "-subj", "/CN=telemetria", "-addext", san],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chmod(key, 0o600)
    return cert, key


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Conexiones cortadas o TLS rechazado (certificado aun no aceptado en
        # ese navegador): normal, sin traza.
        if isinstance(sys.exc_info()[1], OSError):
            return
        super().handle_error(request, client_address)


class LiveServer:
    def __init__(self, port=8081, data_dir=".", backlog_s=30.0, rate_hz=40.0,
                 web_dir=WEB_DIR, https=False, cert=None, key=None):
        self.port = port
        self.tls = certificado_autofirmado(cert, key) if https else None
        self.data_dir = os.path.abspath(data_dir)
        self.web_dir = web_dir
        self.lock = threading.Lock()
        # Historial reciente: un cliente que (re)conecta rellena la grafica.
        self.buf = deque(maxlen=max(100, int(backlog_s * rate_hz)))
        self.seq = 0
        self.meta = {}
        self.meta_ver = 0
        self.cerrando = False
        self.httpd = None

    # ------------------------------------------------ API para el registro ---

    def set_meta(self, **meta):
        """Anuncia una sesion nueva (sensor, columnas, parametros)."""
        with self.lock:
            self.meta = meta
            self.meta_ver += 1
            self.buf.clear()

    def fin_sesion(self):
        """Marca la sesion como terminada (el CSV ya esta completo)."""
        with self.lock:
            self.meta = dict(self.meta, ended=True)
            self.meta_ver += 1

    def publish(self, fila):
        """Una muestra: lista de numeros o None, en el orden de meta['cols']."""
        with self.lock:
            self.buf.append(fila)
            self.seq += 1

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
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def do_GET(self):
                ruta = urlparse(self.path).path
                if ruta == "/stream":
                    return srv._stream(self)
                if ruta == "/api/files":
                    return srv._lista(self)
                if ruta.startswith("/files/"):
                    return srv._fichero(self, unquote(ruta[len("/files/"):]))
                return super().do_GET()

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

    def _pendiente(self, seq_cli, ver_cli):
        with self.lock:
            meta = None
            nuevas = self.seq - seq_cli
            if ver_cli != self.meta_ver:
                meta = self.meta
                nuevas = len(self.buf)
            nuevas = min(nuevas, len(self.buf))
            filas = list(self.buf)[-nuevas:] if nuevas > 0 else []
            return meta, self.meta_ver, filas, self.seq

    def _stream(self, h):
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.end_headers()
        seq, ver = 0, -1
        ult_envio = time.monotonic()
        try:
            while not self.cerrando:
                meta, ver, filas, seq = self._pendiente(seq, ver)
                trozos = []
                if meta is not None:
                    trozos.append(b"event: meta\ndata: " +
                                  json.dumps(meta).encode() + b"\n\n")
                if filas:
                    trozos.append(b"data: " + json.dumps(
                        {"rows": filas}, separators=(",", ":")).encode() + b"\n\n")
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

    def _json(self, h, obj, code=200):
        cuerpo = json.dumps(obj).encode()
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(cuerpo)))
        h.end_headers()
        h.wfile.write(cuerpo)

    def _lista(self, h):
        out = []
        if os.path.isdir(self.data_dir):
            for nombre in os.listdir(self.data_dir):
                if not nombre.endswith(".csv"):
                    continue
                st = os.stat(os.path.join(self.data_dir, nombre))
                out.append({"name": nombre, "size": st.st_size,
                            "mtime": st.st_mtime,
                            "meta": os.path.exists(os.path.join(
                                self.data_dir, nombre + ".meta.txt"))})
        out.sort(key=lambda f: f["mtime"], reverse=True)
        self._json(h, out)

    def _fichero(self, h, nombre):
        ruta = os.path.join(self.data_dir, nombre)
        if not NOMBRE_OK.match(nombre) or not os.path.isfile(ruta):
            return self._json(h, {"error": "no encontrado"}, 404)
        with open(ruta, "rb") as f:
            cuerpo = f.read()
        h.send_response(200)
        h.send_header("Content-Type", "text/plain; charset=utf-8")
        h.send_header("Content-Length", str(len(cuerpo)))
        h.end_headers()
        h.wfile.write(cuerpo)


def main():
    p = argparse.ArgumentParser(description="Web de telemetria (sin registrar)")
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--dir", default=".", help="carpeta con los CSV (def. .)")
    p.add_argument("--https", action="store_true",
                   help="servir por HTTPS (certificado autofirmado en ./certs)")
    p.add_argument("--cert", help="certificado propio (PEM) en vez del autofirmado")
    p.add_argument("--key", help="clave privada del certificado propio")
    args = p.parse_args()
    srv = LiveServer(args.port, data_dir=args.dir, https=args.https or bool(args.cert),
                     cert=args.cert, key=args.key).start()
    srv.esperar(f"Web en {srv.url()}  (CSV de {srv.data_dir}). Ctrl+C para parar.")


if __name__ == "__main__":
    main()
