#!/usr/bin/env python3
"""
Telemetria de suspension con sensor de ultrasonidos (HC-SR04)
Raspberry Pi 3 Model B + Adeept Motor HAT V2.0.

Muestrea lo mas rapido que permite el sensor, sin imprimir por muestra y
con escritura por bloques. Cada ejecucion crea su propio CSV con marca de
tiempo, mas un .meta.txt con los parametros de la sesion.

CSV: t_s, echo_us, dist_mm, rel_mm
  t_s      segundos desde el inicio (reloj monotono, 4 decimales)
  echo_us  ancho bruto del pulso de eco (permite recalcular todo despues)
  dist_mm  distancia al objetivo, compensada por temperatura
  rel_mm   dist_mm menos la referencia medida en reposo al arrancar
           (negativo = el objetivo se acerca al sensor)
  Las muestras sin eco quedan con echo_us/dist_mm/rel_mm vacios, para que
  los huecos se vean en los datos.

Uso:
  python3 telemetria_suspension.py                      # registra hasta Ctrl+C
  python3 telemetria_suspension.py --duracion 60        # 60 s
  python3 telemetria_suspension.py --periodo-ms 20 --max-cm 60
  python3 telemetria_suspension.py --temp 30            # temperatura ambiente
  python3 telemetria_suspension.py --resumen            # analiza el ultimo CSV
  python3 telemetria_suspension.py --resumen fichero.csv
  python3 telemetria_suspension.py --backend sim        # prueba sin hardware
  python3 telemetria_suspension.py --live               # + web en vivo en :8081
  python3 telemetria_suspension.py --live 9000 --dir datos
  python3 telemetria_suspension.py --live --https       # usable desde tu dominio
  python3 telemetria_suspension.py --test-leds          # probar RGB1/RGB2
  python3 telemetria_suspension.py --leds --live        # alertas semaforo
  python3 telemetria_suspension.py --leds --comp-ambar 25 --comp-rojo 40
  (umbrales y logica de alertas: ver alertas.py; la tira WS2812 es el shift
   light de RPM, ver shiftlight.py)

Web (--live): abre http://<ip-de-la-pi>:8081/ desde el movil o el portatil.
  Pestana "Tiempo real" para ver la sesion en curso y "Archivo CSV" para
  postprocesar los CSV guardados en --dir (o cualquiera que arrastres).
  Al terminar la captura la web sigue activa hasta un segundo Ctrl+C.
  Con --https: abre una vez https://<ip-de-la-pi>:8081/ en cada navegador y
  acepta el certificado; despues la web de tu dominio puede conectar.

Backends:
  pigpio    (recomendado) temporizacion por hardware, resolucion de 1 us.
            sudo apt install pigpio python3-pigpio ; sudo systemctl enable --now pigpiod
  gpio      RPi.GPIO con espera activa; mas jitter (~100 us = ~1.7 cm).
  sim       datos simulados para probar el flujo.
  auto      pigpio si el demonio esta activo; si no, gpio.

Numeros de pin en BCM (GPIO), no posicion fisica.
"""

import argparse
import csv
import glob
import math
import os
import random
import signal
import statistics
import sys
import time
from datetime import datetime

import alertas

pc = time.perf_counter


def velocidad_sonido(temp_c):
    """Velocidad del sonido en m/s segun la temperatura del aire."""
    return 331.3 + 0.606 * temp_c


# ------------------------------------------------------------- backends ---

class SensorPigpio:
    nombre = "pigpio"

    def __init__(self, trig, echo):
        import pigpio
        self.pigpio = pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpiod no esta activo (sudo systemctl start pigpiod)")
        self.trig = trig
        self.pi.set_mode(trig, pigpio.OUTPUT)
        self.pi.set_mode(echo, pigpio.INPUT)
        self.pi.write(trig, 0)
        self.t_subida = None
        self.dt_us = None
        self.cb = self.pi.callback(echo, pigpio.EITHER_EDGE, self._flanco)

    def _flanco(self, gpio, nivel, tick):
        if nivel == 1:
            self.t_subida = tick
        elif nivel == 0 and self.t_subida is not None:
            self.dt_us = self.pigpio.tickDiff(self.t_subida, tick)
            self.t_subida = None

    def medir_us(self, timeout_s):
        self.dt_us = None
        self.t_subida = None
        self.pi.gpio_trigger(self.trig, 10, 1)  # pulso de 10 us
        limite = pc() + timeout_s
        while self.dt_us is None and pc() < limite:
            time.sleep(0.0002)
        return self.dt_us

    def cerrar(self):
        self.cb.cancel()
        self.pi.stop()


class SensorGPIO:
    nombre = "RPi.GPIO"

    def __init__(self, trig, echo):
        import RPi.GPIO as GPIO
        self.G = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(trig, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(echo, GPIO.IN)
        self.trig, self.echo = trig, echo

    def medir_us(self, timeout_s):
        G, echo = self.G, self.echo
        G.output(self.trig, True)
        time.sleep(0.00001)
        G.output(self.trig, False)
        limite = pc() + timeout_s
        t0 = pc()
        while G.input(echo) == 0:
            t0 = pc()
            if t0 > limite:
                return None
        t1 = t0
        while G.input(echo) == 1:
            t1 = pc()
            if t1 > limite:
                return None
        return (t1 - t0) * 1e6

    def cerrar(self):
        self.G.cleanup()


class SensorSim:
    nombre = "simulado"

    def __init__(self, velocidad):
        self.v = velocidad
        self.t0 = pc()

    @staticmethod
    def compresion(t):
        """Vuelta tipo de 12 s: frenada, bache y una racha de oscilacion."""
        c = 10 * math.sin(2 * math.pi * 0.3 * t)            # transferencias
        f = t % 12
        if 2 <= f < 4:                                      # frenada fuerte
            c += 52 * math.sin(math.pi * (f - 2) / 2)
        if 6 <= f < 7:                                      # bache seco
            c += 70 * math.sin(math.pi / 2 * min(1, (f - 6) / 0.05)) ** 2 \
                * math.exp(-5 * (f - 6))
        if 8 <= f < 9.5:                                    # oscilacion 9 Hz
            c += 7 * math.sin(math.pi * (f - 8) / 1.5) * math.sin(2 * math.pi * 9 * f)
        return c

    def medir_us(self, timeout_s):
        t = pc() - self.t0
        # al comprimir el objetivo se acerca (--montaje acerca)
        d_mm = 250 - self.compresion(t) + random.gauss(0, 1.0)
        if random.random() < 0.01:
            time.sleep(timeout_s)
            return None
        us = d_mm * 2000 / self.v
        time.sleep(us * 1e-6 + 0.0005)
        return us

    def cerrar(self):
        pass


def crear_sensor(args, velocidad):
    if args.backend == "sim":
        return SensorSim(velocidad)
    if args.backend in ("auto", "pigpio"):
        try:
            return SensorPigpio(args.trig, args.echo)
        except Exception as e:
            if args.backend == "pigpio":
                sys.exit(f"pigpio no disponible: {e}")
            print(f"Aviso: pigpio no disponible ({e}).\n"
                  "       Uso RPi.GPIO: mas jitter en la medida.\n")
    try:
        return SensorGPIO(args.trig, args.echo)
    except ImportError:
        sys.exit("No encuentro RPi.GPIO ni pigpio. Instala: "
                 "sudo apt install python3-rpi.gpio pigpio python3-pigpio")


# ------------------------------------------------------------- registro ---

def registrar(args):
    v = velocidad_sonido(args.temp)
    sensor = crear_sensor(args, v)
    # Un timeout corto = ciclo mas rapido. Ida y vuelta al maximo + margen.
    timeout_s = 2 * (args.max_cm / 100.0) / v + 0.002
    periodo = args.periodo_ms / 1000.0

    def a_mm(us):
        return us * v / 2000.0

    def parar(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, parar)

    live = None
    if args.live:
        from live_server import LiveServer
        live = LiveServer(args.live, data_dir=args.dir, rate_hz=1 / periodo,
                          https=args.https or bool(args.cert),
                          cert=args.cert, key=args.key).start()
        print(f"Web en vivo: {live.url()}\n")

    leds = None
    if args.leds:
        leds = alertas.Alertas(args, 1 / periodo, live)
        leds.start()

    f = None
    try:
        # Referencia en reposo
        ref = 0.0
        if args.cero_seg > 0:
            print(f"Calibrando referencia ({args.cero_seg:g} s). "
                  "Deja la moto quieta...")
            vals, fin = [], pc() + args.cero_seg
            while pc() < fin:
                us = sensor.medir_us(timeout_s)
                if us is not None:
                    vals.append(a_mm(us))
                time.sleep(periodo)
            if len(vals) < 3:
                sys.exit("Sin lecturas en la calibracion: revisa conexion y "
                         "que haya un objetivo dentro de --max-cm.")
            ref = statistics.median(vals)
            print(f"  referencia: {ref:.1f} mm "
                  f"(dispersion {statistics.pstdev(vals):.2f} mm)")

        os.makedirs(args.dir, exist_ok=True)
        base = datetime.now().strftime("suspension_%Y%m%d_%H%M%S")
        ruta = os.path.join(args.dir, base + ".csv")
        with open(ruta + ".meta.txt", "w", encoding="utf-8") as m:
            m.write(f"inicio: {datetime.now().isoformat(timespec='seconds')}\n"
                    f"backend: {sensor.nombre}\n"
                    f"trig_bcm: {args.trig}\necho_bcm: {args.echo}\n"
                    f"periodo_ms: {args.periodo_ms}\nmax_cm: {args.max_cm}\n"
                    f"temp_c: {args.temp}\nvelocidad_sonido_m_s: {v:.1f}\n"
                    f"referencia_mm: {ref:.2f}\n")
            if leds:
                m.write(f"montaje: {args.montaje}\n"
                        f"comp_ambar_mm: {args.comp_ambar}\n"
                        f"comp_rojo_mm: {args.comp_rojo}\n"
                        f"osc_banda_hz: {leds.det.fmin:g}-{leds.det.fmax:g}\n"
                        f"osc_ciclos: {args.osc_ciclos}\n"
                        f"osc_ambar_mm: {args.osc_ambar}\n"
                        f"osc_rojo_mm: {args.osc_rojo}\n")
        if leds:
            leds.listo()
        if live:
            live.set_meta(sensor="suspension", session=base, csv=base + ".csv",
                          cols=["t_s", "echo_us", "dist_mm", "rel_mm"],
                          backend=sensor.nombre, periodo_ms=args.periodo_ms,
                          max_cm=args.max_cm, temp_c=args.temp,
                          referencia_mm=round(ref, 2),
                          **({"montaje": args.montaje,
                              "comp_ambar_mm": args.comp_ambar,
                              "comp_rojo_mm": args.comp_rojo} if leds else {}))

        f = open(ruta, "w", newline="", buffering=1 << 16, encoding="utf-8")
        w = csv.writer(f)
        w.writerow(["t_s", "echo_us", "dist_mm", "rel_mm"])
        print(f"\nRegistrando en {ruta}  [{sensor.nombre}, "
              f"objetivo {1 / periodo:.0f} Hz]. Ctrl+C para parar.\n")

        buf = []
        t_ini = pc()
        proximo = t_ini
        n = perdidas = 0
        n_seg = 0
        ult_vuelco = ult_fsync = ult_estado = t_ini
        ultima = None

        while True:
            ahora = pc()
            if ahora < proximo:
                time.sleep(proximo - ahora)
            t = pc()
            if args.duracion and t - t_ini >= args.duracion:
                break

            us = sensor.medir_us(timeout_s)
            n += 1
            n_seg += 1
            if us is None:
                perdidas += 1
                buf.append([f"{t - t_ini:.4f}", "", "", ""])
                if live:
                    live.publish([round(t - t_ini, 4), None, None, None])
                if leds:
                    leds.push(t - t_ini, None)
            else:
                d = a_mm(us)
                ultima = d
                buf.append([f"{t - t_ini:.4f}", f"{us:.0f}",
                            f"{d:.1f}", f"{d - ref:.1f}"])
                if live:
                    live.publish([round(t - t_ini, 4), round(us),
                                  round(d, 1), round(d - ref, 1)])
                if leds:
                    leds.push(t - t_ini, d - ref)

            proximo = max(proximo + periodo, pc())  # sin rafagas si hay retraso

            ahora = pc()
            if ahora - ult_vuelco >= 1.0:
                w.writerows(buf)
                buf.clear()
                f.flush()
                ult_vuelco = ahora
                if ahora - ult_fsync >= 5.0:
                    os.fsync(f.fileno())
                    ult_fsync = ahora
            if ahora - ult_estado >= 1.0:
                hz = n_seg / (ahora - ult_estado)
                est = f"{ultima:6.1f} mm" if ultima is not None else "  sin eco"
                print(f"\r  t={ahora - t_ini:7.1f}s  {hz:5.1f} Hz  "
                      f"{est}  perdidas {100 * perdidas / n:4.1f}%  "
                      f"{leds.texto() if leds else ''}   ",
                      end="", flush=True)
                n_seg = 0
                ult_estado = ahora
    except KeyboardInterrupt:
        pass
    finally:
        if f is not None:
            try:
                w.writerows(buf)
                f.flush()
                os.fsync(f.fileno())
            finally:
                f.close()
        if leds:
            leds.stop()   # antes que el sensor: RPi.GPIO.cleanup() suelta los pines
        sensor.cerrar()

    if f is not None:
        print(f"\n\nGuardado: {os.path.abspath(ruta)}\n")
        resumen(ruta)
    if live:
        # La web sigue activa para abrir el CSV completo desde el navegador.
        live.fin_sesion()
        live.esperar(f"\nLa web sigue en {live.url()} para revisar la sesion. "
                     "Ctrl+C para salir.")


# -------------------------------------------------------------- resumen ---

def resumen(ruta):
    if ruta == "ultimo":
        candidatos = glob.glob("suspension_*.csv") + glob.glob("*/suspension_*.csv")
        if not candidatos:
            sys.exit("No encuentro ningun suspension_*.csv; indica el fichero.")
        ruta = max(candidatos, key=os.path.getmtime)
    if not os.path.exists(ruta):
        sys.exit(f"No existe {ruta}")

    ts, ds, rels = [], [], []
    with open(ruta, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts.append(float(r["t_s"]))
            if r["dist_mm"] == "":
                ds.append(None)
                rels.append(None)
            else:
                ds.append(float(r["dist_mm"]))
                rels.append(float(r["rel_mm"]))
    n = len(ts)
    if n < 2:
        sys.exit(f"{ruta}: muy pocas filas")

    dur = ts[-1] - ts[0]
    dts = [b - a for a, b in zip(ts, ts[1:])]
    perdidas = sum(1 for d in ds if d is None)
    validos = [x for x in rels if x is not None]
    dvals = [x for x in ds if x is not None]

    vels, prev = [], None
    for t, d in zip(ts, ds):
        if d is None:
            prev = None
            continue
        if prev is not None and 0 < t - prev[0] < 0.2:
            vels.append((d - prev[1]) / (t - prev[0]))
        prev = (t, d)

    print(f"Fichero:   {ruta}")
    print(f"Duracion:  {dur:.1f} s   Muestras: {n}")
    print(f"Tasa real: {(n - 1) / dur:.1f} Hz   "
          f"(dt mediano {1000 * statistics.median(dts):.1f} ms, "
          f"dt maximo {1000 * max(dts):.0f} ms)")
    print(f"Perdidas:  {perdidas} ({100 * perdidas / n:.1f}%)")
    if validos:
        print(f"Distancia: min {min(dvals):.1f} | max {max(dvals):.1f} | "
              f"media {statistics.mean(dvals):.1f} mm")
        print(f"Relativa:  min {min(validos):+.1f} | max {max(validos):+.1f} mm "
              f"(recorrido total {max(validos) - min(validos):.1f} mm)")
    if vels:
        print(f"Velocidad: max acercamiento {min(vels):+.0f} mm/s | "
              f"max alejamiento {max(vels):+.0f} mm/s")


# ----------------------------------------------------------------- main ---

def main():
    p = argparse.ArgumentParser(
        description="Telemetria de suspension con ultrasonidos")
    p.add_argument("--trig", type=int, default=11, help="pin BCM TRIG (def. 11)")
    p.add_argument("--echo", type=int, default=8, help="pin BCM ECHO (def. 8)")
    p.add_argument("--backend", choices=["auto", "pigpio", "gpio", "sim"],
                   default="auto")
    p.add_argument("--periodo-ms", type=float, default=25.0,
                   help="tiempo entre disparos en ms (def. 25 = 40 Hz)")
    p.add_argument("--max-cm", type=float, default=100.0,
                   help="distancia maxima esperada; fija el timeout (def. 100)")
    p.add_argument("--temp", type=float, default=20.0,
                   help="temperatura del aire en C para el sonido (def. 20)")
    p.add_argument("--cero-seg", type=float, default=2.0,
                   help="segundos de calibracion en reposo; 0 = sin referencia")
    p.add_argument("--duracion", type=float, default=0.0,
                   help="segundos a registrar; 0 = hasta Ctrl+C")
    p.add_argument("--dir", default=".", help="carpeta de salida (def. .)")
    p.add_argument("--resumen", nargs="?", const="ultimo", metavar="CSV",
                   help="resumir un CSV (o el ultimo) y salir")
    p.add_argument("--live", nargs="?", const=8081, type=int, metavar="PUERTO",
                   help="servir la web y emitir en tiempo real (def. 8081)")
    p.add_argument("--https", action="store_true",
                   help="web por HTTPS con certificado autofirmado (./certs)")
    p.add_argument("--cert", help="certificado propio (PEM) para --live")
    p.add_argument("--key", help="clave privada del certificado propio")
    alertas.anadir_argumentos(p)
    args = p.parse_args()

    if args.leds and args.cero_seg <= 0:
        p.error("--leds necesita la referencia en reposo (--cero-seg > 0): "
                "los umbrales son mm de compresion sobre esa referencia")
    if args.test_leds:
        alertas.test_leds(args)
    elif args.resumen:
        resumen(args.resumen)
    else:
        registrar(args)


if __name__ == "__main__":
    main()
