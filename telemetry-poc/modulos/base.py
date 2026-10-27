"""
Base de los modulos de telemetria (sensores y salidas).

Un modulo es una pieza enchufable. El maestro (telemetria.py) lo crea con su
configuracion, le pregunta si esta conectado (detectar) y, si esta activo, lo
arranca en su propio hilo. Lo que mide lo entrega con publicar(); el maestro
lo reparte a la grabacion, a la web y a los modulos suscritos (las salidas).

Para anadir un sensor: subclase de Modulo con
  TIPO, NOMBRE, CLASE     'sensor' (graba un CSV) o 'salida' (LEDs, pantalla)
  COLS                    columnas del CSV; la primera siempre t_s
  DEFECTOS                parametros configurables (pines, frecuencia...)
  DETECTABLE              False si no hay forma de saber si esta conectado
  ACCIONES                {nombre: texto del boton} para la web
  detectar()  -> (estado, detalle), estado 'si' | 'no' | 'error'
  bucle()     lee el hardware y publica hasta que self.parar este activo
  simular()   lo mismo sin hardware (--sim)
  pines(), meta(), accion(nombre), liberar()   opcionales
y anadirlo a CATALOGO en modulos/__init__.py.

Numeros de pin en BCM (GPIO), no posicion fisica.
"""

import threading
import time

pc = time.perf_counter


class Hardware:
    """Acceso compartido al hardware de la Pi: pigpio, I2C y SPI.

    Las librerias se importan al usarlas: en un portatil (--sim) no hacen
    falta. Una sola conexion a pigpiod y un solo bus I2C para todos los
    modulos; el I2C se usa siempre con lock_i2c (lo comparten varios hilos).
    """

    def __init__(self, sim=False):
        self.sim = sim
        self._pi = None
        self._i2c = None
        self.lock_i2c = threading.Lock()

    def pi(self):
        if self._pi is None:
            import pigpio
            pi = pigpio.pi()
            if not pi.connected:
                raise RuntimeError("pigpiod no esta activo "
                                   "(sudo systemctl enable --now pigpiod)")
            self._pi = pi
        return self._pi

    def i2c(self):
        if self._i2c is None:
            try:
                from smbus2 import SMBus
            except ImportError:
                try:
                    from smbus import SMBus
                except ImportError:
                    raise RuntimeError("falta smbus (sudo apt install python3-smbus)")
            try:
                self._i2c = SMBus(1)
            except (OSError, IOError):
                raise RuntimeError("I2C desactivado (sudo raspi-config nonint do_i2c 0)")
        return self._i2c

    def i2c_presente(self, addr, reg=None, intentos=3):
        """True si algun dispositivo responde en esa direccion I2C (o, con
        'reg', al leer ese registro: la MPU6050 a veces solo contesta asi).
        Varios intentos: con cables largos el bus falla a veces (un NACK
        suelto no quiere decir que no este)."""
        bus = self.i2c()
        for i in range(intentos):
            with self.lock_i2c:
                try:
                    if reg is not None:
                        bus.read_byte_data(addr, reg)
                    else:   # alternando: algunos (MLX90614) solo contestan a leer un registro
                        bus.read_byte(addr) if i % 2 else bus.read_byte_data(addr, 0)
                    return True
                except (OSError, IOError):
                    pass
            time.sleep(0.02)
        return False

    def cerrar(self):
        if self._pi is not None:
            self._pi.stop()
            self._pi = None
        if self._i2c is not None:
            self._i2c.close()
            self._i2c = None


class Modulo:
    TIPO = ""
    NOMBRE = ""
    CLASE = "sensor"
    COLS = ["t_s"]
    DEFECTOS = {}
    DETECTABLE = True
    ACCIONES = {}

    def __init__(self, id_, cfg, hw, bus):
        self.id = id_
        self.cfg = {"activo": "auto"}
        self.cfg.update(self.DEFECTOS)
        self.cfg.update(cfg or {})
        self.nombre = self.cfg.get("nombre") or self.NOMBRE
        self.hw = hw
        self.bus = bus
        self.parar = threading.Event()
        self.hilo = None
        self.estado = "parado"      # parado | arrancando | calibrando | activo | error
        self.error = None
        self.aviso = None           # problema no fatal (sonda abierta, sin eco...)
        self.deteccion = ("manual", "sin autodeteccion") if not self.DETECTABLE \
            else ("pendiente", "")
        self.n = 0                  # muestras publicadas
        self.perdidas = 0           # muestras sin dato valido
        self.meta_ver = 0           # sube cuando cambia meta() (p. ej. al calibrar)
        self._subs = []

    # ------------------------------------------------------ ciclo de vida ---

    def corriendo(self):
        return self.hilo is not None and self.hilo.is_alive()

    def arrancar(self):
        if self.corriendo():
            return
        self.parar.clear()
        self.error = self.aviso = None
        self.estado = "arrancando"
        self.hilo = threading.Thread(target=self._correr, name=self.id, daemon=True)
        self.hilo.start()

    def detener(self, timeout=2.0):
        self.parar.set()
        if self.hilo is not None:
            self.hilo.join(timeout)

    def _correr(self):
        try:
            if self.hw.sim:
                self.simular()
            else:
                self.bucle()
            self.estado = "parado"
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
            self.estado = "error"
            print(f"\n[{self.id}] error: {self.error}")
        finally:
            for s in self._subs:
                self.bus.desuscribir(s)
            self._subs = []
            try:
                self.liberar()
            except Exception:
                pass

    # ------------------------------------------------- para las subclases ---

    def detectar(self):
        return ("manual", "sin autodeteccion")

    def bucle(self):
        raise NotImplementedError

    def simular(self):
        raise NotImplementedError

    def liberar(self):
        """Suelta el hardware al parar (pines, callbacks, ficheros)."""

    def pines(self):
        return ""

    def meta(self):
        """Parametros que acompanan a los datos (sesion.json y la web)."""
        return {k: v for k, v in self.cfg.items() if k not in ("activo", "nombre")}

    def accion(self, nombre):
        raise ValueError(f"accion desconocida: {nombre}")

    # ------------------------------------------------------- utilidades ---

    def reloj(self):
        """Segundos del reloj comun a todos los modulos."""
        return self.bus.reloj()

    def publicar(self, t, valores, perdida=False):
        """Una fila: t del reloj comun y valores en el orden de COLS[1:]."""
        self.n += 1
        if perdida:
            self.perdidas += 1
        self.bus.publicar(self, t, valores)

    def escuchar(self, fuente, columna, fn):
        """Llama fn(t, valor) con cada muestra de 'columna' del modulo 'fuente'
        (mientras ese modulo este activo). Se anula sola al parar."""
        self._subs.append(self.bus.suscribir(fuente, columna, fn))

    def vivo(self, estado):
        """Estado instantaneo de una salida para la web (semaforo, tira...)."""
        self.bus.set_vivo(self.id, estado)

    def esperar_periodo(self, proximo, periodo):
        """Espera hasta 'proximo' sin rafagas si hay retraso; devuelve el siguiente."""
        ahora = pc()
        if ahora < proximo:
            self.parar.wait(proximo - ahora)
        return max(proximo + periodo, pc())
