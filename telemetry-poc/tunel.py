"""
Tunel rapido de Cloudflare (trycloudflare.com): da a la web de la raspi una
direccion publica con HTTPS valido sin abrir puertos ni tener dominio. La
raspi abre la conexion hacia fuera, asi que vale en casa y en el circuito
(con el movil compartiendo datos).

La direccion cambia en cada arranque de cloudflared: se avisa con
al_cambiar(url) y telemetria.py la anuncia en el repo de datos (raspi.json),
de donde la toman la app y el portal de admin. Solo se avisa cuando ya
responde por Cloudflare: si un navegador la consulta antes de existir, su DNS
recuerda "no existe" durante minutos.

Limitaciones del tunel rapido: sin garantias de Cloudflare, y retiene el
streaming (SSE); por eso la app usa /api/vivo (consultas) cuando va por el
tunel. Instalacion en la Pi (binario oficial, ARM):
  curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
  sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared
"""

import re
import shutil
import subprocess
import threading
import time
import urllib.request

URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunel:
    def __init__(self, puerto, https, al_cambiar):
        self.origen = "{}://localhost:{}".format("https" if https else "http", puerto)
        self.https = https
        self.al_cambiar = al_cambiar
        self.url = None
        self.proc = None
        self.parado = False

    def arrancar(self):
        if not shutil.which("cloudflared"):
            print("Tunel desactivado: falta cloudflared (ver tunel.py)")
            return self
        threading.Thread(target=self._bucle, daemon=True, name="tunel").start()
        return self

    def detener(self):
        self.parado = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _cambiar(self, url):
        if url != self.url:
            self.url = url
            try:
                self.al_cambiar(url)
            except Exception as e:
                print("\n[tunel] " + str(e))

    def _cuando_responda(self, url, proc, limite=180):
        t0 = time.monotonic()
        while time.monotonic() - t0 < limite and proc.poll() is None and not self.parado:
            try:
                urllib.request.urlopen(url + "/api/raspi", timeout=10).read()
                print("\nTunel: " + url)
                self._cambiar(url)
                return
            except Exception:
                time.sleep(3)
        print("\n[tunel] {} no responde: se reintenta".format(url))
        if proc.poll() is None:
            proc.terminate()                # otro cloudflared, otra direccion

    def _bucle(self):
        espera = 5
        while not self.parado:
            orden = ["cloudflared", "tunnel", "--no-autoupdate", "--url", self.origen]
            if self.https:
                orden.append("--no-tls-verify")     # el certificado local es autofirmado
            t0 = time.monotonic()
            try:
                self.proc = subprocess.Popen(orden, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT,
                                             universal_newlines=True)
                for linea in self.proc.stdout:
                    m = URL.search(linea)
                    if m:
                        threading.Thread(target=self._cuando_responda, args=(m.group(0), self.proc),
                                         daemon=True).start()
                self.proc.wait()
            except OSError as e:
                print("\n[tunel] " + str(e))
            self._cambiar(None)
            if self.parado:
                break
            # sin internet cloudflared sale enseguida: reintentos cada vez mas espaciados
            espera = 5 if time.monotonic() - t0 > 300 else min(espera * 2, 120)
            time.sleep(espera)
