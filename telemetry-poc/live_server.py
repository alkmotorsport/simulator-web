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
"""

import argparse
import json
import os
import re
import socket
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
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


class LiveServer:
    def __init__(self, port=8081, data_dir=".", backlog_s=30.0, rate_hz=40.0,
                 web_dir=WEB_DIR):
        self.port = port
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

            def end_headers(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def do_GET(self):
                ruta = urlparse(self.path).path
                if ruta == "/stream":
                    return srv._stream(self)
                if ruta == "/api/files":
                    return srv._lista(self)
                if ruta.startswith("/files/"):
                    return srv._fichero(self, unquote(ruta[len("/files/"):]))
                return super().do_GET()

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.cerrando = True
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def url(self):
        return f"http://{ip_local()}:{self.port}/"

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
    args = p.parse_args()
    srv = LiveServer(args.port, data_dir=args.dir).start()
    print(f"Web en {srv.url()}  (CSV de {srv.data_dir}). Ctrl+C para parar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
