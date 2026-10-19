"""
Pantalla OLED 1,5" SH1107 128x128 (I2C 0x3C) del cuadro.

Paginas de cuadro de competicion; solo salen las de los sensores que estan
funcionando (plug and play). El pulsador cambia de pagina (1 = siguiente,
2 = anterior); sin pulsador, rotan solas cada 'rotar_s'. La web muestra una
copia en vivo de lo que se ve en la pantalla.

Demo de la pantalla sola, con datos simulados y una pagina cada 2 s:
  sudo python3 telemetria.py --demo-pantalla
  python3 telemetria.py --demo-pantalla --png carpeta   # PNG, sin pantalla

Sin pantalla conectada se puede activar igual con el tick de la web: funciona
como pantalla virtual, con los datos reales, y se ve solo en la web.

Conexion: VCC 3,3 V (pin 1), GND (pin 6), SDA (pin 3), SCL (pin 5).
Necesita luma.oled: sudo pip3 install luma.oled
Cada imagen completa son 2 KB por I2C (~0,2 s a 100 kHz): se refresca a
pocos fps y se reparte el bus con el MPU6050 pagina a pagina.

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
from . import sim

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTES = os.path.join(AQUI, "fuentes")
LOGO = os.path.join(AQUI, "web", "logo.jpg")
W = H = 128
INF = float("inf")


# ---------------------------------------------------------------- datos ---

class Datos:
    """Ultimo valor de cada canal, cuando llego y sus extremos."""

    def __init__(self):
        self.v, self.t, self.max, self.min = {}, {}, {}, {}
        self.gg = deque(maxlen=48)          # rastro del diagrama g-g
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


def fmt_vuelta(s):
    if s is None:
        return "-:--.--"
    m, s = divmod(max(0.0, s), 60)
    return f"{int(m)}:{s:05.2f}"


def fmt(v, d=0, signo=False):
    if v is None:
        return "--"
    return f"{v:+.{d}f}" if signo else f"{v:.{d}f}"


# -------------------------------------------------------------- dibujo ---

class Lienzo:
    """Imagen 1 bit de 128x128 con ayudas de dibujo (compatibles con Pillow 5)."""

    def __init__(self):
        from PIL import ImageFont
        f = lambda n, s: ImageFont.truetype(os.path.join(FUENTES, n), s)
        self.px = f("Silkscreen-Regular.ttf", 8)        # rotulos
        self.pxb = f("Silkscreen-Bold.ttf", 8)
        self.n = {s: f("Rajdhani-Bold.ttf", s) for s in (18, 22, 26, 30, 36, 44, 64)}
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

    def alto(self, txt, font):
        _, t, _, b = self.caja(font, txt)
        return b - t

    def texto(self, x, y, txt, font, alin="i", color=1):
        """y = borde superior visible; alin i(zq) | c(entro) | d(cha) respecto a x."""
        l, t, r, b = self.caja(font, txt)
        w = r - l
        x0 = x if alin == "i" else x - w // 2 if alin == "c" else x - w
        self.d.text((x0 - l, y - t), txt, font=font, fill=color)
        return w

    def rect(self, x0, y0, x1, y1, relleno=1, borde=None):
        self.d.rectangle((x0, y0, x1, y1), fill=relleno, outline=borde)

    def linea(self, pts, ancho=1, color=1):
        self.d.line(pts, fill=color, width=ancho)

    def punteada(self, x0, y0, x1, y1, paso=3):
        n = max(abs(x1 - x0), abs(y1 - y0)) // paso
        for i in range(n + 1):
            self.d.point((x0 + (x1 - x0) * i // max(n, 1), y0 + (y1 - y0) * i // max(n, 1)), fill=1)

    def cabecera(self, titulo, derecha=""):
        self.rect(0, 0, W - 1, 10)
        self.texto(2, 2, titulo, self.pxb, color=0)
        if derecha:
            self.texto(W - 3, 2, derecha, self.px, "d", color=0)

    def puntos(self, i, n, y=H - 3):
        """Indicador de pagina abajo."""
        x = W // 2 - (n * 6 - 2) // 2
        for k in range(n):
            if k == i:
                self.rect(x + k * 6, y - 1, x + k * 6 + 3, y + 1)
            else:
                self.d.point((x + k * 6 + 1, y), fill=1)

    def grados(self, x, y, r=2):
        self.d.ellipse((x, y, x + 2 * r, y + 2 * r), outline=1)

    def barra_h(self, x0, y0, x1, y1, frac, marca=None):
        self.rect(x0, y0, x1, y1, relleno=0, borde=1)
        w = int((x1 - x0 - 3) * max(0.0, min(1.0, frac)))
        if w > 0:
            self.rect(x0 + 2, y0 + 2, x0 + 2 + w, y1 - 2)
        if marca is not None:
            xm = x0 + 2 + int((x1 - x0 - 3) * max(0.0, min(1.0, marca)))
            self.linea([(xm, y0 - 2), (xm, y1 + 2)])

    def invertir(self, x0, y0, x1, y1):
        """Invierte una zona (avisos)."""
        from PIL import ImageChops
        zona = self.im.crop((x0, y0, x1 + 1, y1 + 1))
        self.im.paste(ImageChops.invert(zona.convert("L")).convert("1"), (x0, y0))
        from PIL import ImageDraw
        self.d = ImageDraw.Draw(self.im)


# -------------------------------------------------------------- paginas ---
# Cada pagina: (id, titulo, disponible(D, ahora), dibujar(L, D, ahora, cfg)).

def _parpadeo(ahora, hz=3):
    return int(ahora * hz * 2) % 2 == 0


def pag_velocidad(L, D, ahora, c):
    kmh = D.get("kmh", 0.0)
    vmax = c["vel_max"]
    # barra de segmentos tipo luces de cambio; la zona alta solo en contorno
    n, zona_roja = 16, 11
    llenos = int(math.ceil(min(1.0, kmh / vmax) * n))
    aviso = kmh >= c["vel_aviso"]
    for i in range(n):
        x0 = i * 8
        on = i < llenos and (not aviso or _parpadeo(ahora))
        if on:
            L.rect(x0, 14, x0 + 6, 21)
        elif i >= zona_roja:
            L.rect(x0, 14, x0 + 6, 21, relleno=0, borde=1)
        else:
            L.rect(x0 + 2, 17, x0 + 4, 18)
    txt = fmt(kmh)
    L.texto(W // 2 + 2, 27, txt, L.n[64], "c")
    L.texto(W - 2, 80, "KM/H", L.pxb, "d")
    # pie: maxima y tiempo de vuelta
    L.linea([(0, 91), (W - 1, 91)])
    L.linea([(63, 94), (63, 118)])
    L.texto(2, 95, "MAX", L.px)
    L.texto(60, 104, fmt(D.max.get("kmh")), L.n[18], "d")
    L.texto(67, 95, "VUELTA", L.px)
    tv = (ahora - D.get("t_ini_vuelta")) if D.get("t_ini_vuelta") is not None else None
    L.texto(W - 2, 104, fmt_vuelta(tv), L.n[18], "d")


def pag_suspension(L, D, ahora, c):
    rec = c["recorrido_mm"]
    comp = D.get("comp_mm", 0.0)
    y0, y1, x0, x1 = 15, 117, 8, 30
    alto = y1 - y0
    yv = lambda mm: y1 - int(alto * max(0.0, min(1.0, mm / rec)))
    # zona de tope (ultimo 10 %) rayada
    yt = yv(rec * c["tope_frac"])
    for y in range(y0 + 1, yt):
        for x in range(x0 + 1, x1):
            if (x + y) % 4 == 0:
                L.d.point((x, y), fill=1)
    L.rect(x0, y0, x1, yt, relleno=0, borde=1)
    L.rect(x0, y0, x1, y1, relleno=0, borde=1)
    # escala cada 10 mm
    for mm in range(0, int(rec) + 1, 10):
        y = yv(mm)
        L.linea([(x0 - (4 if mm % 50 == 0 else 2), y), (x0 - 1, y)])
    # recorrido actual
    yc = yv(comp)
    if comp > 0:
        L.rect(x0 + 2, yc, x1 - 2, y1 - 2)
    # maximo de la sesion: triangulo a la derecha
    mx = D.max.get("comp_mm")
    if mx is not None:
        ym = yv(mx)
        L.d.polygon([(x1 + 2, ym), (x1 + 6, ym - 3), (x1 + 6, ym + 3)], fill=1)
    # cifras
    L.texto(40, 15, "COMPRESION", L.px)
    L.texto(40, 26, fmt(comp), L.n[44])
    L.texto(W - 2, 26, "MM", L.pxb, "d")
    filas = [("MAX", f"{fmt(mx)} MM"),
             ("USO", f"{fmt(100 * (mx or 0) / rec)} %"),
             ("VEL", f"{fmt(D.get('susp_vel'), signo=True)}"),
             ("TOPES", str(D.topes))]
    for i, (k, v) in enumerate(filas):
        y = 70 + i * 12
        L.texto(40, y, k, L.px)
        L.texto(W - 2, y, v, L.pxb, "d")
    if D.en_tope and _parpadeo(ahora):
        L.invertir(36, 13, W - 1, 64)


def pag_inclinacion(L, D, ahora, c):
    incl = D.get("incl", 0.0)
    cx, cy, r = 64, 118, 60
    lim = 60.0
    ang = lambda g: math.radians(-90 + g * 90.0 / lim)     # 0 grados = arriba
    pt = lambda g, rr: (cx + rr * math.cos(ang(g)), cy + rr * math.sin(ang(g)))
    # sector barrido desde la vertical hasta la inclinacion actual
    a0, a1 = sorted((-90, -90 + max(-lim, min(lim, incl)) * 90.0 / lim))
    if a1 - a0 > 0.5:
        L.d.pieslice((cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8), a0, a1, fill=1)
    L.d.arc((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=1)
    for g in range(-60, 61, 15):
        largo = 7 if g % 30 == 0 else 4
        L.linea([pt(g, r), pt(g, r - largo)], 2 if g % 30 == 0 else 1)
    for g in (-60, -30, 30, 60):
        x, y = pt(g, r - 14)
        dentro = min(0, incl) <= g <= max(0, incl)       # bajo el sector relleno
        L.texto(int(x), int(y) - 3, str(abs(g)), L.px, "c", color=0 if dentro else 1)
    # aguja
    L.linea([pt(incl, 10), pt(incl, r - 3)], 3)
    L.d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=1)
    # maximos a cada lado: triangulos fuera del arco
    for k in ("incl",):
        for g in (D.max.get(k), D.min.get(k)):
            if g is None or abs(g) < 3:
                continue
            x, y = pt(max(-lim, min(lim, g)), r + 4)
            L.d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=1)
    # cifra grande arriba con el lado
    txt = fmt(abs(incl))
    w = L.texto(W // 2, 14, txt, L.n[44], "c")
    L.grados(W // 2 + w // 2 + 2, 15, 3)
    lado = "DER" if incl > 1 else "IZQ" if incl < -1 else ""
    if lado:
        L.texto(W // 2 + w // 2 + 4, 26, lado, L.pxb)
        flecha = [(4, 32), (12, 26), (12, 38)] if incl < 0 else [(W - 5, 32), (W - 13, 26), (W - 13, 38)]
        L.d.polygon(flecha, fill=1)
    L.texto(2, 14, f"I {fmt(abs(D.min.get('incl') or 0))}", L.px)
    L.texto(W - 2, 14, f"D {fmt(max(0, D.max.get('incl') or 0))}", L.px, "d")


def pag_g(L, D, ahora, c):
    ax, ay = D.get("ax", 0.0), D.get("ay", 0.0)
    cx, cy, r = 44, 72, 42
    gmax = c["g_escala"]
    # anillos 0,5 y 1 g punteados, cruz y circulo exterior
    L.d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=1)
    for frac in (0.5 / gmax, 1.0 / gmax):
        rr = r * frac
        for k in range(0, 360, 10):
            L.d.point((cx + rr * math.cos(math.radians(k)), cy + rr * math.sin(math.radians(k))), fill=1)
    L.punteada(cx - r, cy, cx + r, cy)
    L.punteada(cx, cy - r, cx, cy + r)
    L.texto(cx + 2, cy - int(r / gmax) - 8, "1G", L.px)
    # rastro y punto actual (arriba = acelera, abajo = frena, lados = lateral)
    xy = lambda lat, lon: (cx + r * max(-1, min(1, lat / gmax)), cy - r * max(-1, min(1, lon / gmax)))
    for lat, lon in D.gg:
        x, y = xy(lat, lon)
        L.d.point((x, y), fill=1)
    x, y = xy(ay, ax)
    L.d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=1)
    L.d.ellipse((x - 7, y - 7, x + 7, y + 7), outline=1)
    L.texto(1, 14, "ACEL", L.px)
    L.d.polygon([(4, 23), (1, 27), (7, 27)], fill=1)
    L.texto(1, 114, "FRENO", L.px)
    L.d.polygon([(4, 112), (1, 108), (7, 108)], fill=1)
    # columna derecha: total y maximos
    x0 = 92
    L.linea([(x0 - 3, 13), (x0 - 3, 120)])
    L.texto(x0, 14, "G", L.px)
    L.texto(W - 1, 22, f"{math.hypot(ax, ay):.2f}", L.n[22], "d")
    for i, (k, v) in enumerate((("FRENO", -(D.min.get("ax") or 0)),
                                ("ACEL", D.max.get("ax") or 0),
                                ("LAT", max(abs(D.min.get("ay") or 0), D.max.get("ay") or 0)))):
        y = 50 + i * 24
        L.texto(x0, y, k, L.px)
        L.texto(W - 1, y + 9, f"{max(0, v):.2f}", L.n[18], "d")


TEMPS = (("t_bujia", "BUJIA"), ("t_aceite", "ACEITE"), ("t_ir", "DISCO"))


def pag_temperaturas(L, D, ahora, c):
    filas = [(k, n) for k, n in TEMPS if D.hay(k, ahora)]
    alto = (H - 16) // max(1, len(filas))
    for i, (k, nombre) in enumerate(filas):
        y = 13 + i * alto
        tmin, tmax, alarma = c["rango_" + k]
        v = D.get(k)
        L.texto(2, y + 2, nombre, L.pxb)
        L.texto(2, y + 12, f"MAX {fmt(D.max.get(k))}", L.px)
        L.texto(W - 9, y, fmt(v), L.n[30], "d")
        L.grados(W - 7, y + 1, 2)
        L.barra_h(2, y + alto - 9, W - 3, y + alto - 3, (v - tmin) / (tmax - tmin),
                  marca=(alarma - tmin) / (tmax - tmin))
        if i:
            L.punteada(0, y - 2, W - 1, y - 2, 2)
        if v >= alarma and _parpadeo(ahora):
            L.invertir(0, y - 1, W - 1, y + alto - 2)


def pag_vuelta(L, D, ahora, c):
    n = D.get("vuelta", 0)
    t_ini = D.get("t_ini_vuelta")
    actual = ahora - t_ini if t_ini is not None else None
    ult, mejor = D.get("t_ultima"), D.get("t_mejor")
    # numero de vuelta en caja invertida
    L.rect(0, 13, 36, 50)
    L.texto(18, 16, "VUELTA", L.px, "c", color=0)
    L.texto(18, 26, str(n), L.n[26], "c", color=0)
    L.texto(W - 2, 15, "ACTUAL", L.px, "d")
    L.texto(W - 2, 26, fmt_vuelta(actual), L.n[26], "d")
    # delta de la ultima vuelta frente a la mejor anterior
    delta = D.get("delta")
    L.texto(2, 57, "DELTA", L.px)
    txt = "--" if delta is None else f"{delta:+.2f}"
    mejora = delta is not None and delta < 0
    if mejora:
        L.rect(0, 66, W - 1, 96)
    L.texto(W // 2, 70, txt, L.n[30], "c", color=0 if mejora else 1)
    if not mejora:
        L.rect(0, 66, W - 1, 96, relleno=0, borde=1)
    L.texto(2, 102, "ULTIMA", L.px)
    L.texto(W - 2, 102, fmt_vuelta(ult), L.pxb, "d")
    L.texto(2, 113, "MEJOR", L.px)
    L.texto(W - 2, 113, fmt_vuelta(mejor), L.pxb, "d")


def pag_ruedas(L, D, ahora, c):
    vd, vt = D.get("kmh_del", 0.0), D.get("kmh_tras", 0.0)
    L.texto(32, 14, "DELANTERA", L.px, "c")
    L.texto(96, 14, "TRASERA", L.px, "c")
    L.texto(32, 24, fmt(vd), L.n[36], "c")
    L.texto(96, 24, fmt(vt), L.n[36], "c")
    L.linea([(64, 14), (64, 58)])
    desliz = 100.0 * (vt - vd) / vd if vd > 5 else 0.0
    # barra centrada -10 .. +10 %
    y0, y1 = 68, 80
    L.rect(2, y0, W - 3, y1, relleno=0, borde=1)
    frac = max(-1.0, min(1.0, desliz / c["desliz_escala"]))
    xm = W // 2
    xf = xm + int((W // 2 - 5) * frac)
    if xf != xm:
        L.rect(min(xm, xf), y0 + 2, max(xm, xf), y1 - 2)
    L.linea([(xm, y0 - 3), (xm, y1 + 3)])
    L.texto(3, y1 + 3, "-", L.px)
    L.texto(W - 3, y1 + 3, "+", L.px, "d")
    L.texto(W // 2, 86, "DESLIZAMIENTO", L.px, "c")
    L.texto(W // 2, 96, f"{desliz:+.1f}%", L.n[22], "c")
    if abs(desliz) >= c["desliz_aviso"] and _parpadeo(ahora):
        L.invertir(0, 84, W - 1, 120)


def pag_resumen(L, D, ahora, c):
    celdas = [("VEL", "kmh", 0, "KM/H"), ("INCL", "incl", 0, "°"),
              ("G", "_g", 2, ""), ("SUSP", "comp_mm", 0, "MM"),
              ("BUJIA", "t_bujia", 0, "°C"), ("ACEITE", "t_aceite", 0, "°C")]
    for i, (rot, k, d, u) in enumerate(celdas):
        x, y = (i % 2) * 64, 13 + (i // 2) * 36
        if k == "_g":
            v = math.hypot(D.get("ax", 0), D.get("ay", 0)) if D.hay("ax", ahora) else None
        else:
            v = D.get(k) if D.hay(k, ahora) else None
            if k == "incl" and v is not None:
                v = abs(v)
        L.texto(x + 3, y + 2, rot, L.px)
        if u and v is not None:
            L.texto(x + 61, y + 2, u.replace("°", "").replace("C", "C"), L.px, "d")
        L.texto(x + 60, y + 12, "--" if v is None else f"{v:.{d}f}", L.n[22], "d")
    for y in (48, 84):
        L.punteada(0, y, W - 1, y, 2)
    L.punteada(63, 13, 63, 119, 2)


def pag_sistema(L, D, ahora, c):
    filas = D.get("_sistema") or []
    for i, (nombre, ok, txt) in enumerate(filas[:8]):
        y = 14 + i * 11
        if ok:
            L.d.ellipse((2, y, 7, y + 5), fill=1)
        else:
            L.d.ellipse((2, y, 7, y + 5), outline=1)
        L.texto(11, y, nombre, L.px)
        L.texto(W - 2, y, txt, L.px, "d")
    L.linea([(0, 104), (W - 1, 104)])
    L.texto(2, 108, D.get("_ip", "--"), L.px)
    if D.get("_rec"):
        if _parpadeo(ahora, 1):
            L.d.ellipse((W - 30, 107, W - 24, 113), fill=1)
        L.texto(W - 2, 108, "REC", L.pxb, "d")


def _alguna(*ks):
    return lambda D, ahora: any(D.hay(k, ahora) for k in ks)


PAGINAS = [
    ("vel", "VELOCIDAD", _alguna("kmh"), pag_velocidad),
    ("susp", "SUSPENSION", _alguna("comp_mm"), pag_suspension),
    ("incl", "INCLINACION", _alguna("incl"), pag_inclinacion),
    ("g", "FUERZAS G", lambda D, a: D.hay("ax", a) and D.hay("ay", a), pag_g),
    ("temp", "TEMPERATURAS", _alguna("t_bujia", "t_aceite", "t_ir"), pag_temperaturas),
    ("vuelta", "VUELTA", lambda D, a: "vuelta" in D.v, pag_vuelta),
    ("ruedas", "RUEDAS", lambda D, a: D.hay("kmh_del", a) and D.hay("kmh_tras", a), pag_ruedas),
    ("resumen", "RESUMEN", lambda D, a: sum(D.hay(k, a) for k in ("kmh", "incl", "ax", "comp_mm", "t_bujia", "t_aceite")) >= 2, pag_resumen),
    ("sistema", "SISTEMA", lambda D, a: True, pag_sistema),
]

DEFECTOS = {
    "direccion": 0x3C,
    "girar": 0,               # 0-3: pantalla girada 0/90/180/270 grados
    "contraste": 255,
    "virtual": True,          # sin pantalla fisica, seguir y verla solo en la web
    "fps": 5.0,
    "rotar_s": 5.0,           # cambia de pagina sola si no se usa el pulsador (0 = no)
    "recorrido_mm": 100.0,    # recorrido util de la suspension (escala y % de uso)
    "tope_frac": 0.9,         # por encima de esto cuenta como tope
    "vel_max": 200.0, "vel_aviso": 180.0,
    "g_escala": 1.5,
    "desliz_escala": 10.0, "desliz_aviso": 8.0,
    "rango_t_bujia": [0, 300, 250],     # min, max de la barra y alarma (C)
    "rango_t_aceite": [0, 150, 120],
    "rango_t_ir": [0, 500, 400],
}


def splash(L, ahora=0.0):
    """Pantalla de arranque: logo en 1 bit + rotulo."""
    from PIL import Image, ImageOps
    L.nuevo()
    try:
        im = Image.open(LOGO).convert("L").resize((W, W), Image.LANCZOS)
        im = ImageOps.autocontrast(im).point(lambda v: 255 if v > 110 else 0).convert("1")
        L.im.paste(im.crop((3, 30, W - 3, 86)), (3, 14))  # sin el rotulo pequeno ni bordes
        from PIL import ImageDraw
        L.d = ImageDraw.Draw(L.im)
    except OSError:
        L.texto(W // 2, 40, "ALK", L.n[44], "c")
    L.linea([(14, 80), (W - 15, 80)])
    L.texto(W // 2, 87, "TELEMETRIA", L.pxb, "c")
    # bandera a cuadros abajo
    for i in range(0, W, 6):
        for j in range(2):
            if (i // 6 + j) % 2 == 0:
                L.rect(i, 112 + j * 6, i + 5, 117 + j * 6)
    return L.im


def dibujar(L, D, pagina, ahora, cfg, n_paginas=None, indice=None, derecha=""):
    pid, titulo, _, fn = pagina
    L.nuevo()
    L.cabecera(titulo, derecha)
    fn(L, D, ahora, cfg)
    if n_paginas:
        L.puntos(indice, n_paginas)
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
        from luma.core.interface.serial import i2c
        from luma.oled.device import sh1107
    except ImportError:
        raise RuntimeError("falta luma.oled (sudo pip3 install luma.oled)")
    addr = int(cfg["direccion"])
    try:
        dev = sh1107(i2c(port=1, address=addr), width=W, height=H, rotate=int(cfg["girar"]))
    except Exception as e:
        if "not found" not in str(e) and not isinstance(e, OSError):
            raise
        raise RuntimeError(
            f"la pantalla no responde en I2C 0x{addr:02X} (sudo i2cdetect -y 1). Revisa: "
            "SDA al pin 3 y SCL al pin 5 (prueba a cruzarlos), 3,3 V y GND en la propia "
            "pantalla, y que el modulo sea I2C de 4 pines (los de 7 pines suelen venir "
            "en SPI). Sin pantalla: --demo-pantalla --png carpeta")
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
    D.poner("ay", lat + random.gauss(0, 0.02), t)
    D.gg.append((D.get("ay"), D.get("ax")))
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


def demo(png=None, periodo=2.0, cfg=None):
    """Pantalla sola con datos simulados: una pagina cada 'periodo' s."""
    c = dict(DEFECTOS)
    c.update(cfg or {})
    L = Lienzo()
    D = Datos()
    vueltas = []
    D.v["_sistema"] = [("SUSPENSION", True, "40HZ"), ("IMU", True, "100HZ"),
                       ("RUEDA TRAS", True, "20HZ"), ("RUEDA DEL", True, "20HZ"),
                       ("BUJIA", True, "4HZ"), ("ACEITE", False, "SONDA"),
                       ("DISCO IR", True, "10HZ"), ("BOTON", False, "--")]
    D.v["_ip"] = ip_local()
    D.v["_rec"] = True
    n = len(PAGINAS)

    if png:
        from PIL import Image
        os.makedirs(png, exist_ok=True)
        # simula 2 vueltas para tener maximos y rastro, y foto de cada pagina
        momentos = {"vel": 9.5, "susp": 6.05, "incl": 16, "g": 11.5, "temp": 7.0,
                    "vuelta": 130, "ruedas": 8, "resumen": 16, "sistema": 30}
        hoja = Image.new("1", (W * 5 + 4 * 6, H * 2 + 6), 0)
        imgs = [("splash", splash(L).copy())]
        for i, pag in enumerate(PAGINAS):
            D2, vs = Datos(), []
            D2.v.update({k: v for k, v in D.v.items() if k.startswith("_")})
            t_obj = momentos.get(pag[0], 10)
            t = max(0.0, t_obj - 120) if t_obj > 120 else 0.0
            while t <= t_obj:
                alimentar_sim(D2, t, vs)
                t += 0.05
            imgs.append((pag[0], dibujar(L, D2, pag, t_obj, c, n, i, "V3").copy()))
        for k, (nombre, im) in enumerate(imgs):
            im.save(os.path.join(png, f"{k:02d}_{nombre}.png"))
            hoja.paste(im, ((k % 5) * (W + 6), (k // 5) * (H + 6)))
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
            dev.display(dibujar(L, D, PAGINAS[i], t, c, n, i, f"V{D.get('vuelta')}"))
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
    NOMBRE = "Pantalla OLED 1,5\" (SH1107)"
    CLASE = "salida"
    COLS = []
    DEFECTOS = DEFECTOS
    ACCIONES = {"siguiente": "Pagina siguiente", "anterior": "Pagina anterior"}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.dev = None
        self.D = Datos()
        self.pagina = 0
        self._mover = 0
        self.t_cambio = 0.0
        self.t_manual = -1e9     # ultima vez que se cambio de pagina a mano

    def pines(self):
        return f"I2C 0x{int(self.cfg['direccion']):02X} · SDA pin 3 · SCL pin 5"

    def meta(self):
        m = super().meta()
        m["direccion"] = f"0x{int(self.cfg['direccion']):02X}"
        return m

    def accion(self, nombre):
        if nombre not in ("siguiente", "anterior"):
            return super().accion(nombre)
        self._mover += 1 if nombre == "siguiente" else -1
        self.t_manual = self.reloj()
        return "cambiando de pagina"

    def detectar(self):
        addr = int(self.cfg["direccion"])
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
        elif clave == "kmh_tras" or clave == "kmh_del":
            D.poner(clave, v, t)
            if clave == "kmh_tras" or not D.hay("kmh_tras", t):
                D.poner("kmh", v, t)
        elif clave == "ay":
            D.poner("ay", v, t)
            D.gg.append((v, D.get("ax", 0.0)))
        elif clave == "puls":
            if v in (1, 2):
                self._mover += 1 if v == 1 else -1
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
            txt = "ERROR" if m.estado == "error" else "CALIB" if m.estado == "calibrando" \
                else f"{hz:.0f}HZ"
            out.append((m.id.upper().replace("_", " ")[:12], ok, txt))
        return out

    def _ejecutar(self):
        import base64
        import io
        c = self.cfg
        for fuente, col, clave in MAPA:
            if fuente in self.bus.modulos:
                self.escuchar(fuente, col, lambda t, v, k=clave: self._dato(k, t, v))
        L = Lienzo()
        self.estado = "activo"
        self.aviso = getattr(self, "_aviso_virtual", None)
        self._mostrar(splash(L))
        self.parar.wait(1.5)
        ult_png = 0.0
        while not self.parar.is_set():
            ahora = self.reloj()
            D = self.D
            D.v["_sistema"] = self._sistema()
            D.v["_ip"] = ip_local() if int(ahora) % 10 == 0 or "_ip" not in D.v else D.v["_ip"]
            D.v["_rec"] = getattr(getattr(self.bus, "grabador", None), "sesion", None) is not None
            disp = [p for p in PAGINAS if p[2](D, ahora)]
            ids = [p[0] for p in disp]
            auto = c["rotar_s"] > 0 and ahora - self.t_manual > 30
            if auto and ahora - self.t_cambio >= c["rotar_s"]:
                self._mover += 1
            actual = self._pid if getattr(self, "_pid", None) in ids else ids[0]
            i = ids.index(actual)
            if self._mover:
                i = (i + self._mover) % len(ids)
                self._mover = 0
                self.t_cambio = ahora
            self._pid = ids[i]
            v = D.get("vuelta")
            im = dibujar(L, D, disp[i], ahora, c, len(disp), i,
                         f"V{v}" if v is not None else "")
            self._mostrar(im)
            # copia para la web, ~2 por segundo
            if ahora - ult_png >= 0.5:
                ult_png = ahora
                buf = io.BytesIO()
                im.save(buf, "PNG")
                self.vivo({"png": base64.b64encode(buf.getvalue()).decode(),
                           "pagina": self._pid})
            self.parar.wait(1.0 / c["fps"])

    def _mostrar(self, im):
        if self.dev is not None:
            try:
                self.dev.display(im)
            except (OSError, IOError) as e:
                self.aviso = f"I2C: {e}"
