"""
Pantalla OLED del cuadro: Waveshare 2,42" SSD1309 de 128x64 por SPI1.

Una pagina por dato, con un valor grande y una linea secundaria, en estilo de
cuadro de competicion. Solo salen las paginas de los sensores que estan
funcionando (plug and play). Cada pulsacion corta del pulsador pasa a la
pagina siguiente; si no, se queda fija (o rota sola cada 'rotar_s', si se
pone en telemetria.json). Las luces (tira WS2812) siguen a la pagina y las
alertas mandan sobre todo: ver luces.py. La web muestra una
copia en vivo de lo que se ve en la pantalla.

Demo de la pantalla sola, con datos simulados y una pagina cada 2 s:
  sudo python3 telemetria.py --demo-pantalla
  python3 telemetria.py --demo-pantalla --png carpeta   # PNG, sin pantalla

Sin pantalla conectada se puede activar igual con el tick de la web: funciona
como pantalla virtual, con los datos reales, y se ve solo en la web.

Conexion (SPI1): VCC 3,3 V (pin 1), GND (pin 39), DIN GPIO20 (pin 38),
CLK GPIO21 (pin 40), CS GPIO12 (pin 32), DC GPIO25 (pin 22), RST GPIO13 (pin 33).
En /boot/config.txt: dtoverlay=spi1-1cs,cs0_pin=12   (y reiniciar)
Bus a 1 MHz por los 1,8 m de cable. Necesita luma.oled: sudo pip3 install luma.oled
Otra pantalla de luma (sh1107, ssd1306...) o por I2C: cambia 'driver',
'interfaz' y los pines en telemetria.json; las paginas son de 128x64.

Fuentes (OFL, en ./fuentes): Silkscreen para rotulos (pixel, nitida a 8 px)
y Rajdhani Bold para las cifras grandes.
"""

import math
import os
import random
import socket
import time
from collections import deque

from .base import Modulo, pc
from . import luces as luces_mod
from . import sim

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTES = os.path.join(AQUI, "fuentes")
LOGO = os.path.join(AQUI, "web", "logo.jpg")
W, H = 128, 64
CUERPO = 10          # primera fila bajo la cabecera
PIE = 56             # fila de la linea secundaria
INF = float("inf")


def esperar_seguro(parar, seg):
    """Espera 'seg' s con un reloj que no salta. Event.wait en Python 3.7 usa
    la hora del sistema: si se corrige de golpe al tener internet (la Pi no
    tiene reloj con pila), la espera acaba antes de tiempo."""
    fin = time.monotonic() + seg
    while not parar.is_set() and time.monotonic() < fin:
        parar.wait(min(0.1, fin - time.monotonic()))


# ---------------------------------------------------------------- datos ---

class Datos:
    """Ultimo valor de cada canal, cuando llego y sus extremos."""

    def __init__(self):
        self.v, self.t, self.max, self.min = {}, {}, {}, {}
        self.gg = deque(maxlen=40)          # rastro del diagrama g-g (lateral, longitudinal)
        self.t_gg = -INF
        self.topes = 0
        self.en_tope = False

    def poner(self, k, valor, t):
        if valor is None:
            return
        self.v[k], self.t[k] = valor, t
        if valor > self.max.get(k, -INF):
            self.max[k] = valor
        if valor < self.min.get(k, INF):
            self.min[k] = valor

    def hay(self, k, ahora, edad=2.0):
        return k in self.t and ahora - self.t[k] <= edad

    def get(self, k, defecto=None):
        return self.v.get(k, defecto)


def fmt_vuelta(s, dec=2):
    if s is None:
        return "-:--." + "-" * dec
    m, s = divmod(max(0.0, s), 60)
    return f"{int(m)}:{s:0{3 + dec}.{dec}f}"


def fmt(v, d=0, signo=False):
    if v is None:
        return "--"
    return f"{v:+.{d}f}" if signo else f"{v:.{d}f}"


# -------------------------------------------------------------- dibujo ---

class Lienzo:
    """Imagen 1 bit de 128x64 con ayudas de dibujo (compatibles con Pillow 5)."""

    def __init__(self):
        from PIL import ImageFont
        f = lambda n, s: ImageFont.truetype(os.path.join(FUENTES, n), s)
        self.px = f("Silkscreen-Regular.ttf", 8)        # rotulos
        self.pxb = f("Silkscreen-Bold.ttf", 8)
        self.n = {s: f("Rajdhani-Bold.ttf", s) for s in (18, 22, 30, 36, 44, 52)}
        self.im = self.d = None

    def nuevo(self):
        from PIL import Image, ImageDraw
        self.im = Image.new("1", (W, H), 0)
        self.d = ImageDraw.Draw(self.im)

    @staticmethod
    def caja(font, txt):
        if hasattr(font, "getbbox"):                    # Pillow >= 8
            return font.getbbox(txt)
        w, h = font.getsize(txt)
        ox, oy = font.getoffset(txt)
        return ox, oy, w, h

    def ancho(self, txt, font):
        l, _, r, _ = self.caja(font, txt)
        return r - l

    def texto(self, x, y, txt, font, alin="i", color=1):
        """y = borde superior visible; alin i(zq) | c(entro) | d(cha) respecto a x."""
        l, t, r, b = self.caja(font, txt)
        w = r - l
        x0 = x if alin == "i" else x - w // 2 if alin == "c" else x - w
        self.d.text((x0 - l, y - t), txt, font=font, fill=color)
        return w

    def rect(self, x0, y0, x1, y1, relleno=1, borde=None):
        # ordenado y sin tamano negativo: Pillow >= 9 lo rechaza con ValueError
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        self.d.rectangle((x0, y0, x1, y1), fill=relleno, outline=borde)

    def linea(self, pts, ancho=1, color=1):
        self.d.line(pts, fill=color, width=ancho)

    def punteada(self, x0, y0, x1, y1, paso=3):
        n = max(abs(x1 - x0), abs(y1 - y0)) // paso
        for i in range(n + 1):
            self.d.point((x0 + (x1 - x0) * i // max(n, 1), y0 + (y1 - y0) * i // max(n, 1)), fill=1)

    def cabecera(self, titulo, derecha=""):
        self.rect(0, 0, W - 1, 8)
        self.texto(2, 2, titulo, self.pxb, color=0)
        if derecha:
            self.texto(W - 2, 2, derecha, self.px, "d", color=0)

    def pie(self, izq="", der="", fuente=None):
        f = fuente or self.px
        if izq:
            self.texto(0, PIE + 1, izq, f)
        if der:
            self.texto(W - 1, PIE + 1, der, f, "d")

    def grados(self, x, y, r=2):
        self.d.ellipse((x, y, x + 2 * r, y + 2 * r), outline=1)

    def segmentos(self, y0, y1, frac, n=16, roja=11, parpadeo_on=True):
        """Barra de segmentos tipo luces de cambio; la zona alta en contorno."""
        llenos = int(math.ceil(max(0.0, min(1.0, frac)) * n))
        paso = W // n
        for i in range(n):
            x0 = i * paso
            if i < llenos and parpadeo_on:
                self.rect(x0, y0, x0 + paso - 2, y1)
            elif i >= roja:
                self.rect(x0, y0, x0 + paso - 2, y1, relleno=0, borde=1)
            else:
                self.d.point((x0 + paso // 2 - 1, (y0 + y1) // 2), fill=1)

    def invertir(self, x0, y0, x1, y1):
        """Invierte una zona (avisos)."""
        from PIL import ImageChops, ImageDraw
        zona = self.im.crop((x0, y0, x1 + 1, y1 + 1))
        self.im.paste(ImageChops.invert(zona.convert("L")).convert("1"), (x0, y0))
        self.d = ImageDraw.Draw(self.im)


def _parpadeo(ahora, hz=3):
    return int(ahora * hz * 2) % 2 == 0


def grande(L, x, txt, alin="d", tam=52, y=CUERPO + 3):
    """Cifra principal de la pagina."""
    return L.texto(x, y, txt, L.n[tam], alin)


# -------------------------------------------------------------- paginas ---
# Cada pagina: (id, titulo, disponible(D, ahora), dibujar(L, D, ahora, cfg)).

def pag_velocidad(L, D, ahora, c):
    kmh = D.get("kmh", 0.0)
    aviso = kmh >= c["vel_aviso"]
    L.segmentos(CUERPO + 1, CUERPO + 5, kmh / c["vel_max"],
                parpadeo_on=not aviso or _parpadeo(ahora))
    grande(L, 100, fmt(kmh), y=CUERPO + 10, tam=44)
    L.texto(W - 1, CUERPO + 34, "KM/H", L.pxb, "d")
    tv = (ahora - D.get("t_ini_vuelta")) if D.get("t_ini_vuelta") is not None else None
    L.pie(f"MAX {fmt(D.max.get('kmh'))}", fmt_vuelta(tv, 1) if tv is not None else "")


def pag_suspension(L, D, ahora, c):
    rec = c["recorrido_mm"]
    comp = D.get("comp_mm", 0.0)
    x0, x1, y0, y1 = 0, 11, CUERPO, H - 1
    alto = y1 - y0
    yv = lambda mm: y1 - int(alto * max(0.0, min(1.0, mm / rec)))
    yt = yv(rec * c["tope_frac"])
    for y in range(y0 + 1, yt):                       # zona de tope rayada
        for x in range(x0 + 1, x1):
            if (x + y) % 3 == 0:
                L.d.point((x, y), fill=1)
    L.rect(x0, y0, x1, y1, relleno=0, borde=1)
    L.linea([(x0, yt), (x1, yt)])
    yc = yv(comp)
    if yc < y1 - 2:
        L.rect(x0 + 2, yc, x1 - 2, y1 - 2)
    mx = D.max.get("comp_mm")
    if mx is not None:
        ym = yv(mx)
        L.d.polygon([(x1 + 2, ym), (x1 + 5, ym - 3), (x1 + 5, ym + 3)], fill=1)
    grande(L, 108, fmt(comp))
    L.texto(W - 1, CUERPO + 14, "MM", L.pxb, "d")
    L.texto(W - 1, PIE + 1, f"MAX {fmt(mx)} {fmt(100 * (mx or 0) / rec)}% T{D.topes}", L.px, "d")
    if D.en_tope and _parpadeo(ahora):
        L.invertir(16, CUERPO, W - 1, H - 1)


def pag_inclinacion(L, D, ahora, c):
    incl = D.get("incl", 0.0)
    lim = 60.0
    # medio reloj a la derecha
    cx, cy, r = 101, H - 2, 26
    ang = lambda g: math.radians(-90 + max(-lim, min(lim, g)) * 90.0 / lim)
    pt = lambda g, rr: (cx + rr * math.cos(ang(g)), cy + rr * math.sin(ang(g)))
    a0, a1 = sorted((-90, math.degrees(ang(incl))))
    if a1 - a0 > 0.5:
        L.d.pieslice((cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4), a0, a1, fill=1)
    L.d.arc((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=1)
    for g in range(-60, 61, 30):
        L.linea([pt(g, r), pt(g, r - (4 if g else 6))], 1)
    L.linea([pt(incl, 4), pt(incl, r - 2)], 2)
    for g in (D.max.get("incl"), D.min.get("incl")):
        if g is not None and abs(g) >= 3:
            x, y = pt(g, r + 2)
            L.d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=1)
    # cifra y lado
    w = L.texto(0, CUERPO + 3, fmt(abs(incl)), L.n[52])
    L.grados(w + 2, CUERPO + 4, 3)
    lado = "DER" if incl > 1 else "IZQ" if incl < -1 else ""
    if lado:
        L.texto(w + 2, CUERPO + 14, lado, L.pxb)
    L.pie(f"I{fmt(abs(min(0, D.min.get('incl') or 0)))} D{fmt(max(0, D.max.get('incl') or 0))}")


def pag_g(L, D, ahora, c):
    # lateral = tan(inclinacion): en curva la caja mide ~0 lateral
    ax, ay = D.get("ax_f", 0.0), D.get("lat", 0.0)
    cx, cy, r = 27, 36, 26
    gmax = c["g_escala"]
    L.d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=1)
    rr = r / gmax
    for k in range(0, 360, 12):
        L.d.point((cx + rr * math.cos(math.radians(k)), cy + rr * math.sin(math.radians(k))), fill=1)
    L.punteada(cx - r, cy, cx + r, cy)
    L.punteada(cx, cy - r, cx, cy + r)
    xy = lambda lat, lon: (cx + r * max(-1, min(1, lat / gmax)), cy - r * max(-1, min(1, lon / gmax)))
    for lat, lon in list(D.gg):          # copia: la IMU lo va llenando mientras
        L.d.point(xy(lat, lon), fill=1)
    x, y = xy(ay, ax)
    L.d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=1)
    L.d.ellipse((x - 5, y - 5, x + 5, y + 5), outline=1)
    # total y maximos
    L.texto(60, CUERPO + 1, "G", L.px)
    L.texto(W - 1, CUERPO + 1, f"{math.hypot(ax, ay):.2f}", L.n[30], "d")
    filas = (("FRENO", -(D.min.get("ax_f") or 0)), ("ACEL", D.max.get("ax_f") or 0),
             ("LAT", max(abs(D.min.get("lat") or 0), D.max.get("lat") or 0)))
    for i, (k, v) in enumerate(filas):
        y = CUERPO + 26 + i * 9
        L.texto(60, y, k, L.px)
        L.texto(W - 1, y, f"{max(0, v):.2f}", L.pxb, "d")


def _pag_temp(clave):
    def pag(L, D, ahora, c):
        tmin, tmax, alarma = c["rango_" + clave]
        v = D.get(clave)
        frac = (v - tmin) / (tmax - tmin)
        L.segmentos(CUERPO + 1, CUERPO + 5, frac, roja=int(16 * (alarma - tmin) / (tmax - tmin)))
        grande(L, 106, fmt(v), y=CUERPO + 10, tam=44)
        L.grados(109, CUERPO + 11, 2)
        L.texto(W - 1, CUERPO + 11, "C", L.pxb, "d")
        L.pie(f"MAX {fmt(D.max.get(clave))}", f"ALARMA {alarma}")
        if v is not None and v >= alarma and _parpadeo(ahora):
            L.invertir(0, CUERPO, W - 1, H - 1)
    return pag


def pag_vuelta(L, D, ahora, c):
    t_ini = D.get("t_ini_vuelta")
    actual = ahora - t_ini if t_ini is not None else None
    L.texto(W // 2, CUERPO + 4, fmt_vuelta(actual, 1), L.n[44], "c")
    delta = D.get("delta")
    L.texto(0, PIE + 1, f"V{D.get('vuelta', 0)} MEJ {fmt_vuelta(D.get('t_mejor'))}", L.px)
    if delta is not None:
        txt = f"{delta:+.2f}"
        w = L.ancho(txt, L.pxb)
        if delta < 0:                                  # mejora: caja invertida
            L.rect(W - w - 4, PIE - 1, W - 1, H - 1)
            L.texto(W - 2, PIE + 1, txt, L.pxb, "d", color=0)
        else:
            L.texto(W - 1, PIE + 1, txt, L.pxb, "d")


def pag_ruedas(L, D, ahora, c):
    vd, vt = D.get("kmh_del", 0.0), D.get("kmh_tras", 0.0)
    desliz = 100.0 * (vt - vd) / vd if vd > 5 else 0.0
    L.texto(W // 2, CUERPO + 2, f"{desliz:+.1f}%", L.n[36], "c")
    y0, y1 = CUERPO + 32, CUERPO + 38
    L.rect(0, y0, W - 1, y1, relleno=0, borde=1)
    frac = max(-1.0, min(1.0, desliz / c["desliz_escala"]))
    xm = W // 2
    xf = xm + int((W // 2 - 3) * frac)
    if abs(xf - xm) > 0:
        L.rect(xm, y0 + 2, xf, y1 - 2)
    L.linea([(xm, y0 - 2), (xm, y1 + 2)])
    L.pie(f"DEL {fmt(vd)}", f"TRAS {fmt(vt)}")
    if abs(desliz) >= c["desliz_aviso"] and _parpadeo(ahora):
        L.invertir(0, CUERPO, W - 1, CUERPO + 30)


def _resumen(c):
    """Los 6 datos de la pagina RESUMEN (se eligen en la web, con las luces)."""
    r = (c.get("luces") or {}).get("resumen") or luces_mod.RESUMEN_DEFECTO
    return (list(r) + [""] * 6)[:6]


def pag_resumen(L, D, ahora, c):
    v = luces_mod.valores(D, ahora, c)
    for i, k in enumerate(_resumen(c)):
        x, y = (i % 3) * 43, CUERPO + (i // 3) * 27
        if not k:
            continue
        rot, d, _ = luces_mod.RESUMEN[k]
        x_ = v.get(k)
        L.texto(x + 1, y + 1, rot, L.px)
        L.texto(x + 39, y + 10, "--" if x_ is None else f"{x_:.{d}f}", L.n[22], "d")
    L.punteada(0, CUERPO + 26, W - 1, CUERPO + 26, 2)
    for x in (42, 85):
        L.punteada(x, CUERPO, x, H - 1, 2)


def pag_sistema(L, D, ahora, c):
    filas = D.get("_sistema") or []
    for i, (nombre, ok, txt) in enumerate(filas[:8]):
        x, y = (i // 4) * 64, CUERPO + 1 + (i % 4) * 11
        if ok:
            L.d.ellipse((x, y + 1, x + 4, y + 5), fill=1)
        else:
            L.d.ellipse((x, y + 1, x + 4, y + 5), outline=1)
        L.texto(x + 7, y, nombre[:5], L.px)
        L.texto(x + 61, y, txt[:3], L.px, "d")
    L.texto(0, PIE + 1, D.get("_ip", "--"), L.px)
    if D.get("_rec"):
        if _parpadeo(ahora, 1):
            L.d.ellipse((W - 24, PIE + 1, W - 19, PIE + 6), fill=1)
        L.texto(W - 1, PIE + 1, "REC", L.pxb, "d")


def _alguna(*ks):
    return lambda D, ahora: any(D.hay(k, ahora) for k in ks)


PAGINAS = [
    ("vel", "VELOCIDAD", _alguna("kmh"), pag_velocidad),
    ("susp", "SUSPENSION", _alguna("comp_mm"), pag_suspension),
    ("incl", "INCLINACION", _alguna("incl"), pag_inclinacion),
    ("g", "FUERZAS G", lambda D, a: D.hay("ax_f", a) and D.hay("lat", a), pag_g),
    ("bujia", "TEMP BUJIA", _alguna("t_bujia"), _pag_temp("t_bujia")),
    ("aceite", "TEMP ACEITE", _alguna("t_aceite"), _pag_temp("t_aceite")),
    ("disco", "TEMP DISCO", _alguna("t_ir"), _pag_temp("t_ir")),
    ("vuelta", "VUELTA", lambda D, a: "vuelta" in D.v, pag_vuelta),
    ("ruedas", "DESLIZAMIENTO", lambda D, a: D.hay("kmh_del", a) and D.hay("kmh_tras", a), pag_ruedas),
    ("resumen", "RESUMEN", lambda D, a: sum(D.hay(k, a) for k in ("kmh", "incl", "ax_f", "comp_mm", "t_bujia", "t_aceite", "t_ir")) >= 2, pag_resumen),
    ("sistema", "SISTEMA", lambda D, a: True, pag_sistema),
]

DEFECTOS = {
    # Waveshare 2,42" SSD1309 por SPI1 (PDF, seccion 6)
    "driver": "ssd1309",      # clase de luma.oled.device: ssd1309, ssd1306, sh1106...
    "interfaz": "spi",        # spi | i2c
    "spi_puerto": 1, "spi_disp": 0,      # /dev/spidev1.0 (CS en GPIO12 por el overlay)
    "gpio_dc": 25, "gpio_rst": 13,
    "spi_hz": 1000000,        # 1 MHz: 1,8 m de cable
    "direccion": 0x3C,        # solo con interfaz i2c
    "girar": 0,               # 0-3: pantalla girada 0/90/180/270 grados
    "contraste": 255,
    "virtual": True,          # sin pantalla fisica, seguir y verla solo en la web
    "fps": 5.0,               # la Zero va justa de CPU: a simple vista no se nota
    "rotar_s": 0.0,           # > 0: cambia de pagina sola cada tantos s sin usar el pulsador
    "logo_s": 8.0,            # logo al arrancar, mientras arrancan y calibran los sensores
    "recorrido_mm": 100.0,    # recorrido util de la suspension (escala y % de uso)
    "tope_frac": 0.9,         # por encima de esto cuenta como tope
    "vel_max": 200.0, "vel_aviso": 180.0,
    "g_escala": 1.5,
    "desliz_escala": 10.0, "desliz_aviso": 8.0,
    "rango_t_bujia": [0, 300, 250],     # min, max de la barra y alarma (C)
    "rango_t_aceite": [0, 150, 120],
    "rango_t_ir": [0, 500, 400],
    "luces": None,            # luces y alertas (luces.py); None = plantilla recomendada
}


def splash(L, ahora=0.0):
    """Pantalla de arranque: logo en 1 bit + rotulo + bandera a cuadros."""
    from PIL import Image, ImageDraw, ImageOps
    L.nuevo()
    try:
        im = Image.open(LOGO).convert("L").resize((128, 128), Image.LANCZOS)
        im = ImageOps.autocontrast(im).point(lambda v: 255 if v > 110 else 0).convert("1")
        L.im.paste(im.crop((8, 36, 120, 70)), (8, 0))   # emblema a su tamano
        L.d = ImageDraw.Draw(L.im)
    except OSError:
        L.texto(W // 2, 4, "ALK", L.n[30], "c")
    L.texto(W // 2, 36, "ALK MOTORSPORT", L.pxb, "c")
    for i in range(0, W, 4):                           # bandera a cuadros
        for j in range(2):
            if (i // 4 + j) % 2 == 0:
                L.rect(i, 46 + j * 3, i + 3, 48 + j * 3)
    L.texto(W // 2, 57, "TELEMETRIA", L.px, "c")
    return L.im


def aviso(L, titulo, lineas):
    """Pantalla de aviso a toda pantalla (apagar, guardando...)."""
    L.nuevo()
    L.cabecera(titulo)
    y0 = 9 + (55 - 12 * len(lineas)) // 2
    for i, txt in enumerate(lineas):
        L.texto(W // 2, y0 + 12 * i + 2, txt, L.pxb, "c")
    return L.im


def dibujar(L, D, pagina, ahora, cfg, n_paginas=None, indice=None, rec=False, marca=False):
    """rec: punto de grabando en la cabecera; marca: '!' de alerta reconocida."""
    pid, titulo, _, fn = pagina
    L.nuevo()
    derecha = (f"{indice + 1}/{n_paginas}" if n_paginas else "")
    if marca:
        derecha = "! " + derecha
    L.cabecera(titulo, derecha)
    if rec and _parpadeo(ahora, 1):
        x = W - 9 - (L.ancho(derecha, L.px) + 3 if derecha else 0)
        L.d.ellipse((x, 2, x + 4, 6), fill=0)
    try:
        fn(L, D, ahora, cfg)
    except Exception as e:      # una pagina rota no debe tumbar la pantalla
        L.nuevo()
        L.cabecera(titulo, derecha)
        L.texto(W // 2, 22, "ERROR EN PAGINA", L.pxb, "c")
        L.texto(W // 2, 36, type(e).__name__[:20].upper(), L.px, "c")
        print(f"\n[pantalla] error dibujando {pid}: {e}")
    return L.im


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "sin red"
    finally:
        s.close()


def abrir_oled(cfg):
    try:
        from luma.core.interface.serial import i2c, spi
        import luma.oled.device as dispositivos
    except ImportError:
        raise RuntimeError("falta luma.oled (sudo pip3 install luma.oled)")
    clase = getattr(dispositivos, cfg["driver"], None)
    if clase is None:
        raise RuntimeError(f"luma.oled no tiene el driver {cfg['driver']}")
    try:
        if cfg["interfaz"] == "spi":
            serie = spi(port=int(cfg["spi_puerto"]), device=int(cfg["spi_disp"]),
                        gpio_DC=int(cfg["gpio_dc"]), gpio_RST=int(cfg["gpio_rst"]),
                        bus_speed_hz=int(cfg["spi_hz"]))
        else:
            serie = i2c(port=1, address=int(cfg["direccion"]))
        dev = clase(serie, width=W, height=H, rotate=int(cfg["girar"]))
    except Exception as e:
        if cfg["interfaz"] == "spi":
            dev_spi = f"/dev/spidev{cfg['spi_puerto']}.{cfg['spi_disp']}"
            if not os.path.exists(dev_spi):
                raise RuntimeError(
                    f"no existe {dev_spi}: anade dtoverlay=spi1-1cs,cs0_pin=12 a "
                    "/boot/config.txt y reinicia")
            raise RuntimeError(f"no se pudo abrir la pantalla por SPI ({e})")
        raise RuntimeError(
            f"la pantalla no responde en I2C 0x{int(cfg['direccion']):02X} "
            f"(sudo i2cdetect -y 1): revisa SDA/SCL, 3,3 V y GND ({e})")
    dev.contrast(int(cfg["contraste"]))
    return dev


# -------------------------------------------------------- datos simulados ---

def alimentar_sim(D, t, vueltas):
    """Rellena D con la vuelta simulada (la misma que --sim)."""
    p = sim.pista(t)
    lat = math.tan(math.radians(p["incl_deg"]))
    D.poner("kmh", p["kmh"], t)
    D.poner("kmh_del", p["kmh"], t)
    D.poner("kmh_tras", p["kmh"] * (1 + 0.08 * max(0.0, p["acel_g"])) + random.gauss(0, 0.3), t)
    D.poner("incl", p["incl_deg"] + random.gauss(0, 0.4), t)
    D.poner("ax", p["acel_g"] + random.gauss(0, 0.02), t)
    D.poner("ax_f", D.get("ax"), t)
    D.poner("ay", lat + random.gauss(0, 0.02), t)
    D.poner("lat", lat, t)
    D.gg.append((D.get("lat"), D.get("ax_f")))
    comp = 30 + 25 * p["acel_g"] + 8 * min(1.0, abs(lat)) + sim.baches(t) * 1.4
    poner_comp(D, comp, t, DEFECTOS)
    D.poner("t_bujia", 150 + 40 * p["kmh"] / 160 + 70 * math.sin(t / 9) ** 8, t)
    D.poner("t_aceite", 92 + 6 * math.sin(t / 20), t)
    D.poner("t_ir", 60 + 380 * max(0.0, math.sin(t / 7)) ** 6, t)
    n = int(t // sim.VUELTA_S) + 1
    if D.get("vuelta") != n:
        rnd = random.Random(n)
        D.poner("vuelta", n, t)
        D.poner("t_ini_vuelta", t, t)
        if n > 1:
            vueltas.append(61.2 + rnd.uniform(-0.8, 0.8))
    if vueltas:
        ult = vueltas[-1]
        previas = vueltas[:-1]
        D.poner("t_ultima", ult, t)
        D.poner("t_mejor", min(vueltas), t)
        D.v["delta"] = ult - min(previas) if previas else None
    else:   # para que la demo ensene algo desde el principio
        D.poner("t_ultima", 61.734, t)
        D.poner("t_mejor", 61.312, t)
        D.v["delta"] = -0.42 if int(t // 4) % 2 else 0.31


def poner_comp(D, comp, t, cfg):
    prev = D.get("comp_mm"), D.t.get("comp_mm")
    D.poner("comp_mm", comp, t)
    if prev[0] is not None and 0 < t - prev[1] < 0.3:
        D.poner("susp_vel", (comp - prev[0]) / (t - prev[1]), t)
    tope = comp >= cfg["recorrido_mm"] * cfg["tope_frac"]
    if tope and not D.en_tope:
        D.topes += 1
    D.en_tope = tope


SISTEMA_DEMO = [("SUSP", True, "40"), ("ACEL", True, "50"), ("RTRAS", True, "20"),
                ("RDEL", True, "20"), ("BUJIA", True, "4"), ("ACEIT", False, "!"),
                ("DISCO", True, "10"), ("BOTON", False, "--")]


def demo(png=None, periodo=2.0, cfg=None):
    """Pantalla sola con datos simulados: una pagina cada 'periodo' s."""
    c = dict(DEFECTOS)
    c.update(cfg or {})
    L = Lienzo()
    D = Datos()
    vueltas = []
    D.v.update({"_sistema": SISTEMA_DEMO, "_ip": ip_local(), "_rec": True})
    n = len(PAGINAS)

    if png:
        from PIL import Image
        os.makedirs(png, exist_ok=True)
        # simula hasta un momento interesante de cada pagina y guarda la foto
        momentos = {"vel": 9.5, "susp": 6.05, "incl": 16, "g": 11.5, "bujia": 7.0,
                    "aceite": 20, "disco": 11, "vuelta": 130, "ruedas": 8,
                    "resumen": 16, "sistema": 30}
        imgs = [("splash", splash(L).copy())]
        for i, pag in enumerate(PAGINAS):
            D2, vs = Datos(), []
            D2.v.update({k: v for k, v in D.v.items() if k.startswith("_")})
            t_obj = momentos.get(pag[0], 10)
            t = max(0.0, t_obj - 120) if t_obj > 120 else 0.0
            while t <= t_obj:
                alimentar_sim(D2, t, vs)
                t += 0.05
            imgs.append((pag[0], dibujar(L, D2, pag, t_obj, c, n, i).copy()))
        cols = 3
        filas = (len(imgs) + cols - 1) // cols
        hoja = Image.new("1", (cols * (W + 6) - 6, filas * (H + 6) - 6), 0)
        for k, (nombre, im) in enumerate(imgs):
            im.save(os.path.join(png, f"{k:02d}_{nombre}.png"))
            hoja.paste(im, ((k % cols) * (W + 6), (k // cols) * (H + 6)))
        hoja.save(os.path.join(png, "hoja.png"))
        print(f"PNG en {os.path.abspath(png)}")
        return

    try:
        dev = abrir_oled(c)
    except RuntimeError as e:
        raise SystemExit(f"Error: {e}")
    print("Demo de la pantalla: una pagina cada %g s. Ctrl+C para salir." % periodo)
    try:
        dev.display(splash(L))
        time.sleep(periodo)
        t0 = pc()
        while True:
            t = pc() - t0
            alimentar_sim(D, t, vueltas)
            i = int(t / periodo) % n
            dev.display(dibujar(L, D, PAGINAS[i], t, c, n, i))
            time.sleep(1.0 / c["fps"])
    except KeyboardInterrupt:
        pass
    finally:
        dev.clear()


# --------------------------------------------------------------- modulo ---

# (modulo fuente, columna, clave en Datos)
MAPA = [
    ("suspension", "rel_mm", "rel"), ("imu", "incl_deg", "incl"),
    ("imu", "ax_g", "ax"), ("imu", "ay_g", "ay"),
    ("rueda_tras", "kmh", "kmh_tras"), ("rueda_del", "kmh", "kmh_del"),
    ("temp_bujia", "temp_c", "t_bujia"), ("temp_aceite", "temp_c", "t_aceite"),
    ("ir", "obj_c", "t_ir"), ("boton", "pulsaciones", "puls"),
    ("boton", "vuelta", "vuelta"), ("boton", "t_vuelta_s", "t_vuelta"),
]


class Pantalla(Modulo):
    TIPO = "pantalla"
    NOMBRE = "Pantalla OLED 2,42\" (SSD1309)"
    CLASE = "salida"
    COLS = []
    DEFECTOS = DEFECTOS
    ACCIONES = {"siguiente": "Pagina siguiente", "anterior": "Pagina anterior"}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.dev = None
        self.D = Datos()
        self._mover = 0
        self._pid = None
        self.t_cambio = 0.0
        self.t_manual = -1e9     # ultima vez que se cambio de pagina a mano
        self._aviso_virtual = None
        self._pulsado = 0        # pulsaciones cortas pendientes (las atiende el bucle)
        self._luces_nuevas = None
        self.motor = None
        self.alerta = None       # nombre de la alerta que se ve ahora
        self.mensaje = None      # (titulo, lineas): aviso que tapa las paginas (al apagar)

    def pines(self):
        c = self.cfg
        if c["interfaz"] == "spi":
            return (f"SPI{c['spi_puerto']} · DIN GPIO20 · CLK GPIO21 · CS GPIO12 · "
                    f"DC GPIO{c['gpio_dc']} · RST GPIO{c['gpio_rst']}")
        return f"I2C 0x{int(c['direccion']):02X} · SDA pin 3 · SCL pin 5"

    def meta(self):
        m = super().meta()
        m["direccion"] = f"0x{int(self.cfg['direccion']):02X}"
        return m

    def avisar(self, titulo, lineas):
        """Aviso fijo en pantalla (y luces en ambar) hasta que se pare el modulo."""
        self.mensaje = (titulo, list(lineas))

    def set_luces(self, cfg):
        """Configuracion nueva desde la web (ya validada); se aplica al momento."""
        self.cfg["luces"] = cfg
        self._luces_nuevas = cfg

    def accion(self, nombre):
        if nombre not in ("siguiente", "anterior"):
            return super().accion(nombre)
        if nombre == "siguiente":
            self._pulsado += 1          # como una pulsacion corta: reconoce alertas
        else:
            self._mover -= 1
        self.t_manual = self.reloj()
        return "cambiando de pagina"

    def detectar(self):
        c = self.cfg
        if c["interfaz"] == "spi":
            # por SPI la pantalla no contesta: solo se puede ver si el bus existe
            dev_spi = f"/dev/spidev{c['spi_puerto']}.{c['spi_disp']}"
            if not os.path.exists(dev_spi):
                return ("no", f"SPI{c['spi_puerto']} sin activar "
                              "(dtoverlay=spi1-1cs,cs0_pin=12 en /boot/config.txt)")
            return ("manual", f"{dev_spi} listo; por SPI no se puede saber si esta "
                              "conectada: activala con el tick")
        addr = int(c["direccion"])
        if self.hw.i2c_presente(addr):
            return ("si", f"responde en 0x{addr:02X}")
        return ("no", f"nada en I2C 0x{addr:02X}")

    def bucle(self):
        try:
            self.dev = abrir_oled(self.cfg)
        except RuntimeError as e:
            if not self.cfg.get("virtual", True):
                raise
            # sin la pantalla fisica: se dibuja igual y se ve en la web
            self.dev = None
            self._aviso_virtual = f"pantalla virtual (solo en la web): {e}"
        self._ejecutar()

    def simular(self):
        self._ejecutar()

    def liberar(self):
        if self.dev is not None:
            try:
                if self.mensaje is None:     # al apagar se queda el aviso
                    self.dev.clear()
            except Exception:
                pass
            self.dev = None

    # ------------------------------------------------------------------------

    def _dato(self, clave, t, v):
        D = self.D
        if v is None:
            return
        if clave == "rel":
            fuente = self.bus.modulos.get("suspension")
            signo = -1 if fuente is None or fuente.cfg.get("montaje") == "acerca" else 1
            poner_comp(D, signo * v, t, self.cfg)
        elif clave in ("kmh_tras", "kmh_del"):
            D.poner(clave, v, t)
            if clave == "kmh_tras" or not D.hay("kmh_tras", t):
                D.poner("kmh", v, t)
        elif clave == "ax":
            # media de ~0,5 s: la vibracion del motor no cuenta como frenada
            prev, tp = D.get("ax_f"), D.t.get("ax_f")
            k = 1.0 if prev is None or not 0 < t - tp < 1 else min(1.0, (t - tp) / 0.5)
            D.poner("ax", v, t)
            D.poner("ax_f", v if prev is None else prev + k * (v - prev), t)
            if D.hay("lat", t, 0.5) and (not D.gg or t - D.t_gg >= 0.1):   # rastro a 10 Hz
                D.gg.append((D.get("lat"), D.get("ax_f")))
                D.t_gg = t
        elif clave == "incl":
            D.poner("incl", v, t)
            if abs(v) < 70:
                D.poner("lat", math.tan(math.radians(v)), t)
        elif clave == "ay":
            D.poner("ay", v, t)
        elif clave == "puls":
            if v == 1:
                self._pulsado += 1
                self.t_manual = t
        elif clave == "vuelta":
            if v != D.get("vuelta"):
                D.poner("t_ini_vuelta", t, t)
            D.poner("vuelta", v, t)
        elif clave == "t_vuelta":
            mejor_previa = D.get("t_mejor")
            D.poner("t_ultima", v, t)
            D.v["delta"] = v - mejor_previa if mejor_previa is not None else None
            D.poner("t_mejor", min(v, mejor_previa if mejor_previa is not None else INF), t)
        else:
            D.poner(clave, v, t)

    def _sistema(self):
        out = []
        for m in self.bus.modulos.values():
            if m.CLASE != "sensor" or not (m.corriendo() or m.estado == "error"):
                continue
            hz = self.bus._ritmo.get(m.id, (0, 0))[0] if hasattr(self.bus, "_ritmo") else 0
            ok = m.estado == "activo" and not m.aviso
            txt = "ERR" if m.estado == "error" else "CAL" if m.estado == "calibrando" \
                else "!" if m.aviso else f"{hz:.0f}"
            corto = {"imu": "ACEL", "suspension": "SUSP", "rueda_tras": "RTRAS", "rueda_del": "RDEL",
                     "temp_bujia": "BUJIA", "temp_aceite": "ACEIT", "ir": "DISCO"}
            out.append((corto.get(m.id, m.id.upper()), ok, txt))
        return out

    def _ejecutar(self):
        import base64
        import io
        c = self.cfg
        for fuente, col, clave in MAPA:
            if fuente in self.bus.modulos:
                self.escuchar(fuente, col, lambda t, v, k=clave: self._dato(k, t, v))
        L = Lienzo()
        self.motor = luces_mod.Motor(self._luces_iniciales())
        self.estado = "activo"
        self.aviso = self._aviso_virtual
        self._mostrar(splash(L))
        esperar_seguro(self.parar, c["logo_s"])
        ult_png = 0.0
        while not self.parar.is_set():
            ahora = self.reloj()
            D = self.D
            D.v["_sistema"] = self._sistema()
            if "_ip" not in D.v or int(ahora) % 10 == 0:
                D.v["_ip"] = ip_local()
            D.v["_rec"] = getattr(getattr(self.bus, "grabador", None), "sesion", None) is not None
            tira = self.bus.modulos.get("tira")
            boton = self.bus.modulos.get("boton")
            t_puls = getattr(boton, "t_pulsado", None)
            if self.mensaje is None and t_puls is not None and ahora - t_puls >= 3:
                quedan = max(0, math.ceil(boton.cfg["apagar_s"] - (ahora - t_puls)))
                self._mostrar(aviso(L, "APAGAR", ["SIGUE PULSANDO", f"{quedan} S", "PARA APAGAR"]))
                self.parar.wait(0.1)
                continue
            if self.mensaje is not None:
                if tira is not None and tira.corriendo():
                    tira.externo([("ambar", "lento")] * int(tira.cfg["num"]))
                self._mostrar(aviso(L, *self.mensaje))
                self.parar.wait(0.2)
                continue
            disp = [p for p in PAGINAS if p[2](D, ahora)]
            ids = [p[0] for p in disp]
            if self._luces_nuevas is not None:
                self.motor.cargar(self._luces_nuevas)
                self._luces_nuevas = None
            # alertas: mandan sobre la pagina elegida (que no se pierde)
            v = luces_mod.valores(D, ahora, c, self._sensores_mal())
            manda, marca = self.motor.actualizar(v, ahora)
            while self._pulsado:
                self._pulsado -= 1
                if not self.motor.reconocer(ahora):       # sin alerta: pagina siguiente
                    self._mover += 1
                else:
                    manda, marca = self.motor.actualizar(v, ahora)
            if c["rotar_s"] > 0 and ahora - self.t_manual > 30 and \
                    ahora - self.t_cambio >= c["rotar_s"]:
                self._mover += 1
            i = ids.index(self._pid) if self._pid in ids else 0
            if self._mover:
                i = (i + self._mover) % len(ids)
                self._mover = 0
                self.t_cambio = ahora
            self._pid = ids[i]
            ver = i
            if manda is not None and manda[1] and manda[0]["pagina"] in ids:
                ver = ids.index(manda[0]["pagina"])
            self.alerta = manda[0]["nombre"] if manda is not None else None
            if tira is not None and tira.corriendo():
                tira.externo(self.motor.luces(ids[ver], v, int(tira.cfg["num"]), manda))
            im = dibujar(L, D, disp[ver], ahora, c, len(disp), ver, rec=D.v["_rec"], marca=marca)
            self._mostrar(im)
            # copia para la web, ~2 por segundo (solo si alguien la mira: PNG cuesta CPU)
            live = getattr(self.bus, "live", None)
            if ahora - ult_png >= 0.5 and (live is None or live.hay_clientes()):
                ult_png = ahora
                buf = io.BytesIO()
                im.save(buf, "PNG")
                self.vivo({"png": base64.b64encode(buf.getvalue()).decode(),
                           "pagina": ids[ver], "alerta": self.alerta})
            self.parar.wait(1.0 / c["fps"])

    def _luces_iniciales(self):
        # validada tambien la plantilla: rellena lo que el motor necesita (pagina de cada alerta...)
        paginas = [p[0] for p in PAGINAS]
        cfg = self.cfg.get("luces")
        if cfg is None:
            return luces_mod.validar(luces_mod.por_defecto(), paginas)
        try:
            return luces_mod.validar(cfg, paginas)
        except ValueError as e:
            print(f"[pantalla] luces en telemetria.json no validas ({e}): uso la plantilla recomendada")
            return luces_mod.validar(luces_mod.por_defecto(), paginas)

    def _sensores_mal(self):
        return sum(1 for m in self.bus.modulos.values()
                   if m.CLASE == "sensor" and m.estado == "error")

    def _mostrar(self, im):
        if self.dev is not None:
            try:
                self.dev.display(im)
            except (OSError, IOError) as e:
                self.aviso = f"pantalla: {e}"
