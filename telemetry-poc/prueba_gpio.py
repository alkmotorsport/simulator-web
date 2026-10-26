#!/usr/bin/env python3
"""
Comprueba que los GPIO siguen sanos (por ejemplo el GPIO24 si el ECHO del
ultrasonidos llego a recibir 5 V).

Con NADA conectado al pin: activa el pull-up interno y tiene que leer 1;
activa el pull-down y tiene que leer 0. Un pin que no sigue a sus
resistencias internas esta danado (o tiene algo conectado).

  python3 prueba_gpio.py            # GPIO24 (ECHO)
  python3 prueba_gpio.py 24 23 27   # los que digas (numeracion BCM)
  python3 prueba_gpio.py --todos    # todos los GPIO del proyecto

Usa pigpio (sudo systemctl start pigpiod). Deja los pines como entradas sin
pull al terminar.
"""

import argparse
import sys
import time

# GPIO (BCM) del proyecto y para que se usan
PROYECTO = {
    4: "libre", 5: "libre", 6: "libre", 12: "pantalla CS",
    13: "pantalla RST", 16: "libre", 17: "boton", 18: "WS2812",
    20: "pantalla DIN", 21: "pantalla CLK", 22: "Hall delantero",
    23: "ultrasonidos TRIG", 24: "ultrasonidos ECHO", 25: "pantalla DC",
    26: "libre", 27: "Hall trasero",
}


def probar(pi, pigpio, g):
    pi.set_mode(g, pigpio.INPUT)
    lecturas = {}
    for nombre, pud in (("pull-up", pigpio.PUD_UP), ("pull-down", pigpio.PUD_DOWN)):
        pi.set_pull_up_down(g, pud)
        time.sleep(0.02)
        lecturas[nombre] = [pi.read(g) for _ in range(5)]
    pi.set_pull_up_down(g, pigpio.PUD_OFF)
    arriba, abajo = lecturas["pull-up"], lecturas["pull-down"]
    ok = all(v == 1 for v in arriba) and all(v == 0 for v in abajo)
    return ok, sum(arriba), sum(abajo)


def main():
    p = argparse.ArgumentParser(description="Comprobar GPIO sin nada conectado")
    p.add_argument("gpio", nargs="*", type=int, help="GPIO en numeracion BCM (def. 24)")
    p.add_argument("--todos", action="store_true", help="todos los GPIO del proyecto")
    a = p.parse_args()
    pines = sorted(PROYECTO) if a.todos else (a.gpio or [24])

    try:
        import pigpio
    except ImportError:
        sys.exit("Falta pigpio (sudo apt install python3-pigpio)")
    pi = pigpio.pi()
    if not pi.connected:
        sys.exit("pigpiod no esta activo (sudo systemctl start pigpiod)")

    print("Desconecta todo lo que vaya a estos pines antes de probar.\n")
    malos = 0
    try:
        for g in pines:
            ok, n_arriba, n_abajo = probar(pi, pigpio, g)
            uso = PROYECTO.get(g, "")
            estado = "OK" if ok else "FALLA"
            detalle = "" if ok else (f"  (con pull-up leyo 1 en {n_arriba}/5, "
                                     f"con pull-down leyo 1 en {n_abajo}/5)")
            print(f"  GPIO{g:<3} {uso:20} {estado}{detalle}")
            malos += not ok
    finally:
        pi.stop()
    print()
    if malos:
        print(f"{malos} pin(es) no siguen a sus resistencias internas: o tienen algo "
              "conectado o estan danados. Desconecta y repite; si sigue fallando, "
              "usa otro GPIO.")
    else:
        print("Todos los pines responden bien.")
    return 1 if malos else 0


if __name__ == "__main__":
    sys.exit(main())
