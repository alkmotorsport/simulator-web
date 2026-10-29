#!/usr/bin/env python3
"""
Wifi del sistema sin SSH: si al encender no hay ninguna wifi conocida, la raspi
crea la suya y, al conectarse un movil, le abre una pagina (portal cautivo,
como en los hoteles) para darle la wifi o el punto de acceso del movil. Desde
ahi se conecta sola a esa red cada vez que la tenga cerca.

  1. Arranca: espera hasta ESPERA_S a que NetworkManager conecte a una red
     conocida (la de casa, un punto de acceso guardado...).
  2. Si no: mira las redes de alrededor (la Zero tiene una sola antena: no
     puede buscar mientras da su wifi) y crea la suya, "Telemetria-<raspi>",
     con clave. La pantalla de la moto ensena nombre y clave.
  3. El movil se conecta y se le abre la pagina: elige la red (o la escribe:
     un punto de acceso apagado no sale en la lista) y su clave.
  4. La raspi apaga su wifi y busca esa red durante INTENTAR_S (da tiempo a
     encender el punto de acceso). Si no la encuentra, vuelve a dar la suya.
  5. Sin nadie conectado a su wifi, cada REVISAR_S la apaga un momento por si
     ya hay una red conocida (se ha encendido el punto de acceso, se vuelve a casa).

Desde la app ("Anadir wifi") se puede pedir la wifi propia aunque haya red:
telemetria.py crea PEDIR y este servicio la levanta.

Estado para la pantalla y la app: ESTADO (json). Va como servicio aparte
(systemd/telemetria-wifi.service), como root: usa nmcli.
  sudo python3 wifi.py            # lo que hace el servicio
  sudo python3 wifi.py --ap       # dar ya la wifi propia (pruebas)
"""

import argparse
import html
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

RUN = "/run/telemetria"
ESTADO = os.path.join(RUN, "wifi.json")
PEDIR = os.path.join(RUN, "wifi-pedir")
CONF = "/etc/telemetria/wifi.json"              # nombre y clave de la wifi propia
DNSMASQ = "/etc/NetworkManager/dnsmasq-shared.d/telemetria-portal.conf"
AP = "telemetria-ap"                            # conexion de NetworkManager
IP = "10.42.0.1"
PUERTO = 80
IFACE = "wlan0"
ESPERA_S = 60          # al arrancar, tiempo para conectar a una red conocida
INTENTAR_S = 120       # buscando la red nueva (encender el punto de acceso)
REVISAR_S = 180        # sin clientes en la wifi propia: mirar si hay red conocida
PEDIDA_S = 600         # wifi propia pedida desde la app: como mucho este tiempo


def nmcli(*args, timeout=40, check=False):
    r = subprocess.run(["nmcli"] + list(args), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or "nmcli fallo")
    return r


def guardar_estado(**e):
    os.makedirs(RUN, exist_ok=True)
    tmp = ESTADO + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dict(e, t=time.time()), f)
    os.replace(tmp, ESTADO)


def conectado():
    """Nombre de la red a la que esta conectado wlan0 como cliente, o None."""
    r = nmcli("-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "dev", "show", IFACE)
    estado = dict(l.split(":", 1) for l in r.stdout.splitlines() if ":" in l)
    con = estado.get("GENERAL.CONNECTION", "")
    if estado.get("GENERAL.STATE", "").startswith("100") and con and con != AP:
        return red_de(con) or con
    return None


def red_de(con):
    r = nmcli("-t", "-g", "802-11-wireless.ssid", "con", "show", con)
    return r.stdout.strip() or None


def redes_cerca():
    """[(ssid, senal, segura)] de mas a menos senal, sin repetir."""
    nmcli("dev", "wifi", "rescan", "ifname", IFACE)
    time.sleep(4)
    r = nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "ifname", IFACE)
    vistas = {}
    for l in r.stdout.splitlines():
        partes = re.split(r"(?<!\\):", l)
        if len(partes) < 3:
            continue
        ssid = partes[0].replace("\\:", ":")
        if not ssid or ssid == conf()["ssid"]:
            continue
        senal = int(partes[1] or 0)
        if ssid not in vistas or senal > vistas[ssid][0]:
            vistas[ssid] = (senal, partes[2] not in ("", "--"))
    return sorted(((s, v[0], v[1]) for s, v in vistas.items()), key=lambda x: -x[1])


def conf():
    """Nombre y clave de la wifi propia: se crean una vez y no cambian."""
    try:
        with open(CONF) as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    nombre = "telemetria"
    try:
        with open("/etc/telemetria/sincro.json") as f:
            s = json.load(f)
        nombre = s.get("nombre") or s.get("raspi") or nombre
    except (OSError, ValueError):
        pass
    corto = re.sub(r"[^A-Za-z0-9]", "", nombre.split()[0] if nombre.split() else nombre)[:12] or "Moto"
    c = {"ssid": "Telemetria-" + corto, "clave": "".join(random.choice("23456789") for _ in range(8))}
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    fd = os.open(CONF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(c, f)
    return c


def clientes_ap():
    r = subprocess.run(["/usr/sbin/iw", "dev", IFACE, "station", "dump"],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.count("Station ")


# ------------------------------------------------------------ wifi propia ---

def subir_ap():
    c = conf()
    os.makedirs(os.path.dirname(DNSMASQ), exist_ok=True)
    with open(DNSMASQ, "w") as f:                  # todo nombre -> la raspi: portal
        f.write(f"address=/#/{IP}\n")
    nmcli("con", "delete", AP)
    nmcli("con", "add", "type", "wifi", "ifname", IFACE, "con-name", AP, "autoconnect", "no",
          "ssid", c["ssid"], "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
          "ipv4.method", "shared", "ipv4.addresses", IP + "/24", "ipv6.method", "disabled",
          "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", c["clave"], check=True)
    nmcli("con", "up", AP, check=True)


def bajar_ap():
    nmcli("con", "down", AP)
    try:
        os.remove(DNSMASQ)
    except OSError:
        pass


def esperar_red(segundos, preferida=None):
    """Hasta 'segundos' esperando a estar conectado (a 'preferida' si se da)."""
    fin = time.monotonic() + segundos
    ult_intento = -1e9
    while time.monotonic() < fin:
        red = conectado()
        if red and (preferida is None or red == preferida):
            return red
        if preferida and time.monotonic() - ult_intento > 15:
            ult_intento = time.monotonic()
            nmcli("con", "up", "wifi-" + preferida, timeout=45)
        time.sleep(3)
    return conectado()


# ------------------------------------------------------------------ portal ---

PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wifi del sistema de telemetria</title><style>
body{{font:16px system-ui,sans-serif;margin:0;padding:16px;background:#111;color:#eee}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:#bbb;line-height:1.4}}
.red{{display:flex;justify-content:space-between;padding:12px;margin:6px 0;background:#222;border-radius:8px;cursor:pointer}}
.red.sel{{outline:2px solid #e8b00c}} input{{width:100%;box-sizing:border-box;font-size:17px;padding:11px;margin:6px 0 12px;border-radius:8px;border:1px solid #444;background:#1b1b1b;color:#eee}}
button{{width:100%;font-size:17px;padding:13px;border:0;border-radius:8px;background:#e8b00c;color:#111;font-weight:600}}
.aviso{{background:#3a2a00;padding:10px;border-radius:8px}} .err{{background:#4a1111;padding:10px;border-radius:8px}}
label{{color:#bbb;font-size:14px}}</style></head><body>
<h1>Wifi del sistema de telemetría</h1>
<p>Elige la red a la que se conectará la moto. Para usar el <b>punto de acceso de tu móvil</b>, escribe su nombre y su clave (si está apagado no sale en la lista): al guardar, desconéctate de esta wifi y enciéndelo.</p>
{mensaje}
<form method="post" action="/guardar">
{redes}
<label>Nombre de la red</label><input name="ssid" id="ssid" autocomplete="off" autocapitalize="none" required>
<label>Clave (vacía si es abierta)</label><input name="clave" type="password" autocomplete="off">
<button>Guardar y conectar</button></form>
<script>document.querySelectorAll('.red').forEach(r=>r.onclick=()=>{{document.querySelectorAll('.red').forEach(x=>x.classList.remove('sel'));r.classList.add('sel');document.getElementById('ssid').value=r.dataset.ssid;}});</script>
</body></html>"""

HECHO = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Guardada</title>
<style>body{{font:16px system-ui,sans-serif;margin:0;padding:16px;background:#111;color:#eee}} p{{line-height:1.4}}</style></head><body>
<h1>Guardada: {ssid}</h1>
<p>La moto deja su wifi y busca <b>{ssid}</b> durante {minutos} minutos.</p>
<p><b>Ahora:</b> desconéctate de esta wifi y, si es el punto de acceso de tu móvil, enciéndelo. La pantalla de la moto dirá «CONECTADA» cuando lo encuentre.</p>
<p>Si no lo encuentra (clave mal escrita, punto de acceso apagado), la moto vuelve a dar su wifi y puedes repetirlo.</p>
</body></html>"""


class Portal:
    def __init__(self):
        self.redes = []
        self.error = ""
        self.pedido = None        # (ssid, clave) que ha mandado el movil
        self.srv = None

    def arrancar(self):
        portal = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _enviar(self, cuerpo, codigo=200):
                b = cuerpo.encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                # cualquier direccion (las comprobaciones de Android/iOS incluidas)
                # da la pagina: asi el movil abre "Iniciar sesion en la red"
                redes = "".join(
                    f'<div class="red" data-ssid="{html.escape(s)}"><span>{html.escape(s)}</span>'
                    f'<span>{"🔒 " if seg else ""}{sen}%</span></div>' for s, sen, seg in portal.redes[:15])
                if not redes:
                    redes = "<p>No se ve ninguna red: escribe el nombre a mano.</p>"
                msg = f'<p class="err">{html.escape(portal.error)}</p>' if portal.error else ""
                self._enviar(PAGINA.format(mensaje=msg, redes=redes))

            def do_POST(self):
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                q = parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
                ssid = (q.get("ssid") or [""])[0].strip()[:32]
                clave = (q.get("clave") or [""])[0][:63]
                if not ssid or (clave and len(clave) < 8):
                    portal.error = "Falta el nombre de la red, o la clave tiene menos de 8 caracteres."
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                portal.error = ""
                self._enviar(HECHO.format(ssid=html.escape(ssid), minutos=INTENTAR_S // 60))
                portal.pedido = (ssid, clave)

        self.srv = ThreadingHTTPServer((IP, PUERTO), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None


def guardar_red(ssid, clave):
    con = "wifi-" + ssid
    nmcli("con", "delete", con)
    args = ["con", "add", "type", "wifi", "ifname", IFACE, "con-name", con, "ssid", ssid,
            "connection.autoconnect", "yes", "connection.autoconnect-priority", "10"]
    if clave:
        args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", clave]
    nmcli(*args, check=True)


# ------------------------------------------------------------------- bucle ---

def modo_ap(portal, pedida=False):
    """Da la wifi propia hasta tener una red. Devuelve la red conectada (o None)."""
    c = conf()
    guardar_estado(modo="buscando")
    portal.redes = redes_cerca()
    subir_ap()
    portal.arrancar()
    guardar_estado(modo="ap", ssid=c["ssid"], clave=c["clave"], ip=IP)
    print(f"Wifi propia {c['ssid']} (clave {c['clave']}): {len(portal.redes)} redes cerca", flush=True)
    t0 = ult = time.monotonic()
    try:
        while True:
            time.sleep(2)
            if portal.pedido:
                ssid, clave = portal.pedido
                portal.pedido = None
                time.sleep(2)                       # que la pagina llegue al movil
                try:
                    guardar_red(ssid, clave)
                except RuntimeError as e:
                    portal.error = f"No se pudo guardar {ssid}: {e}"
                    continue
                portal.parar()
                bajar_ap()
                guardar_estado(modo="conectando", ssid=ssid)
                print(f"Red nueva: {ssid}; buscandola {INTENTAR_S} s", flush=True)
                red = esperar_red(INTENTAR_S, preferida=ssid)
                if red:
                    return red
                portal.error = (f"No se encontró {ssid}: revisa que el punto de acceso esté "
                                "encendido y la clave. Inténtalo otra vez.")
                portal.redes = redes_cerca()
                subir_ap()
                portal.arrancar()
                guardar_estado(modo="ap", ssid=c["ssid"], clave=c["clave"], ip=IP, error=portal.error)
                ult = time.monotonic()
                continue
            ahora = time.monotonic()
            if pedida and ahora - t0 > PEDIDA_S and not clientes_ap():
                return None
            if not pedida and ahora - ult > REVISAR_S and not clientes_ap():
                # nadie configurando: mirar si ya hay una red conocida
                portal.parar()
                bajar_ap()
                guardar_estado(modo="buscando")
                red = esperar_red(40)
                if red:
                    return red
                portal.redes = redes_cerca()
                subir_ap()
                portal.arrancar()
                guardar_estado(modo="ap", ssid=c["ssid"], clave=c["clave"], ip=IP)
                ult = time.monotonic()
    finally:
        portal.parar()
        if not conectado():
            bajar_ap()


def main():
    p = argparse.ArgumentParser(description="Wifi del sistema: red conocida o wifi propia con portal")
    p.add_argument("--ap", action="store_true", help="dar ya la wifi propia")
    a = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("ejecutalo con sudo (usa nmcli)")
    conf()
    portal = Portal()
    pedida = a.ap
    if not pedida:
        guardar_estado(modo="buscando")
        red = esperar_red(ESPERA_S)
    while True:
        if pedida or not conectado():
            try:
                red = modo_ap(portal, pedida)
            except Exception as e:                   # nunca dejar la raspi sin red
                print(f"wifi propia: {e}", flush=True)
                bajar_ap()
                time.sleep(30)
                continue
            pedida = False
            if not red:                              # se acabo sin red nueva: la de antes
                guardar_estado(modo="buscando")
                esperar_red(ESPERA_S)
        red = conectado()
        guardar_estado(modo="cliente", ssid=red)
        if red:
            print(f"Conectada a {red}", flush=True)
        # vigilar: si se pierde la red un buen rato, o la app pide la wifi propia
        perdida = None
        while True:
            time.sleep(5)
            if os.path.exists(PEDIR):
                os.remove(PEDIR)
                pedida = True
                break
            red = conectado()
            if red:
                perdida = None
                guardar_estado(modo="cliente", ssid=red)
            else:
                perdida = perdida or time.monotonic()
                guardar_estado(modo="sin_red")
                if time.monotonic() - perdida > ESPERA_S:
                    break


if __name__ == "__main__":
    main()
