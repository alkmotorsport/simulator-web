#!/usr/bin/env python3
"""
Shift light de RPM para el cuadro: tira WS2812 de 4 modulos x 3 LEDs (12).

Patron (tipo cuadro de carreras):
  rpm < --rpm-inicio        apagado
  inicio .. cambio          se llena por modulos: 1-2 verde, 3 ambar, 4 rojo
  rpm >= --rpm-cambio       toda la tira parpadea en azul: CAMBIA
  rpm >= --rpm-limite       toda la tira parpadea rapido en rojo: corte
--patron centro: se llena desde los dos extremos hacia el centro (rojo en
el medio), como muchos cuadros de MotoGP.

Aun no hay sensor de RPM: este modulo solo muestra un valor. Cuando lo haya:
    from shiftlight import ShiftLight
    sl = ShiftLight(args)      # args de anadir_argumentos()
    sl.mostrar(rpm)            # llamarlo a 20-50 Hz desde el bucle del sensor
    sl.cerrar()

Pruebas:
  sudo python3 shiftlight.py --demo            # sube y baja marchas
  sudo python3 shiftlight.py --rpm 11000       # valor fijo
  python3 shiftlight.py --demo                 # sin tira (portatil): en consola

La WS2812 va en GPIO12 (PWM): necesita sudo, rpi_ws281x y el audio analogico
desactivado (dtparam=audio=off en /boot/firmware/config.txt). Los 4 modulos
encadenados: OUT de cada uno -> IN del siguiente; solo el primero al HAT.
"""

import argparse
import math
import time

ZONAS = ((0.5, "verde"), (0.75, "ambar"), (1.0, "rojo"))   # fraccion de la tira


class Tira:
    """Tira WS2812 (rpi_ws281x; necesita sudo)."""
    RGB = {"off": (0, 0, 0), "verde": (0, 255, 0), "ambar": (255, 120, 0),
           "rojo": (255, 0, 0), "azul": (0, 60, 255)}

    def __init__(self, n, pin, brillo):
        from rpi_ws281x import Color, PixelStrip
        canal = 1 if pin in (13, 19, 41, 45, 53) else 0
        self.s = PixelStrip(n, pin, 800000, 10, False, brillo, canal)
        self.s.begin()
        self.color = {k: Color(*v) for k, v in self.RGB.items()}
        self.n, self.actual = n, None
        self.poner(["off"] * n)

    def poner(self, colores):
        if colores == self.actual:
            return
        for i, c in enumerate(colores):
            self.s.setPixelColor(i, self.color[c])
        self.s.show()
        self.actual = list(colores)

    def cerrar(self):
        self.poner(["off"] * self.n)


class Consola:
    """Sustituto sin hardware: dibuja la tira en la terminal."""
    ANSI = {"off": "\033[90m○", "verde": "\033[92m●", "ambar": "\033[93m●",
            "rojo": "\033[91m●", "azul": "\033[94m●"}

    def __init__(self, n, modulo=3):
        self.n, self.modulo, self.extra = n, modulo, ""

    def poner(self, colores):
        grupos = [" ".join(self.ANSI[c] for c in colores[i:i + self.modulo])
                  for i in range(0, self.n, self.modulo)]
        print("\r  " + "  ".join(grupos) + "\033[0m  " + self.extra + "   ",
              end="", flush=True)

    def cerrar(self):
        self.poner(["off"] * self.n)
        print()


class ShiftLight:
    def __init__(self, args, avisar=print):
        a = args
        if not a.rpm_inicio < a.rpm_cambio <= a.rpm_limite:
            raise ValueError("hace falta rpm-inicio < rpm-cambio <= rpm-limite")
        self.a = a
        self.n = a.ws_num
        self.en_cambio = False
        try:
            self.tira = Tira(a.ws_num, a.ws_pin, a.ws_brillo)
        except Exception as e:
            avisar(f"Aviso: WS2812 no disponible ({e}); muestro en consola.")
            self.tira = Consola(a.ws_num)

    def colores(self, rpm, ahora):
        """Lista de colores de la tira para unas rpm."""
        a, n = self.a, self.n
        # histeresis para que no tiemble justo en el punto de cambio
        if rpm >= a.rpm_cambio:
            self.en_cambio = True
        elif rpm < a.rpm_cambio - a.rpm_histeresis:
            self.en_cambio = False

        if rpm >= a.rpm_limite:
            return ["rojo" if int(ahora * 10) % 2 == 0 else "off"] * n
        if self.en_cambio:
            return ["azul" if int(ahora * 6) % 2 == 0 else "off"] * n
        frac = (rpm - a.rpm_inicio) / (a.rpm_cambio - a.rpm_inicio)
        if frac <= 0:
            return ["off"] * n

        def zona(f):
            return next(c for lim, c in ZONAS if f <= lim + 1e-9)

        if a.patron == "centro":
            mitad = math.ceil(n / 2)
            k = min(mitad, math.ceil(frac * mitad))
            out = ["off"] * n
            for i in range(k):
                c = zona((i + 1) / mitad)
                out[i] = out[n - 1 - i] = c
            return out
        k = min(n, math.ceil(frac * n))
        return [zona((i + 1) / n) if i < k else "off" for i in range(n)]

    def mostrar(self, rpm, ahora=None):
        cols = self.colores(rpm, time.monotonic() if ahora is None else ahora)
        if isinstance(self.tira, Consola):
            self.tira.extra = f"{rpm:6.0f} rpm"
        self.tira.poner(cols)

    def cerrar(self):
        self.tira.cerrar()


def anadir_argumentos(p):
    g = p.add_argument_group("shift light de RPM (WS2812)")
    g.add_argument("--rpm-inicio", type=float, default=8000,
                   help="rpm a las que se enciende el primer LED (def. 8000)")
    g.add_argument("--rpm-cambio", type=float, default=12000,
                   help="punto de cambio: toda la tira en azul (def. 12000)")
    g.add_argument("--rpm-limite", type=float, default=13000,
                   help="corte de encendido: rojo rapido (def. 13000)")
    g.add_argument("--rpm-histeresis", type=float, default=150,
                   help="rpm por debajo del cambio para dejar de avisar (def. 150)")
    g.add_argument("--patron", choices=["lineal", "centro"], default="lineal",
                   help="llenado de izquierda a derecha o hacia el centro")
    g.add_argument("--ws-pin", type=int, default=12, help="GPIO de la WS2812 (def. 12)")
    g.add_argument("--ws-num", type=int, default=12,
                   help="LEDs en total (def. 12 = 4 modulos de 3)")
    g.add_argument("--ws-brillo", type=int, default=80,
                   help="brillo 0-255 (def. 80; sube para pleno sol)")


def demo(sl, a):
    """Simula aceleraciones con cambios de marcha y una frenada."""
    t0 = time.monotonic()
    rango = a.rpm_limite - a.rpm_inicio
    while True:
        t = (time.monotonic() - t0) % 14
        if t < 10:                       # 4 marchas de 2.5 s
            f = (t % 2.5) / 2.5
            rpm = a.rpm_inicio - 0.3 * rango + f * 1.35 * rango
        else:                            # reduccion
            rpm = a.rpm_limite - (t - 10) / 4 * 1.2 * rango
        sl.mostrar(rpm)
        time.sleep(0.02)


def main():
    p = argparse.ArgumentParser(description="Shift light de RPM en WS2812")
    anadir_argumentos(p)
    p.add_argument("--demo", action="store_true", help="barrido de prueba")
    p.add_argument("--rpm", type=float, help="mostrar un valor fijo")
    a = p.parse_args()
    try:
        sl = ShiftLight(a)
    except ValueError as e:
        p.error(str(e))
    try:
        if a.rpm is not None:
            while True:
                sl.mostrar(a.rpm)
                time.sleep(0.02)
        else:
            demo(sl, a)
    except KeyboardInterrupt:
        pass
    finally:
        sl.cerrar()


if __name__ == "__main__":
    main()
