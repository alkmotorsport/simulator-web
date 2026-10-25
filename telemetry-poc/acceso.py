"""
Acceso a la web de la raspi: solo entran sus usuarios (los del repo de datos).

Sin contrasenas por la red y sin depender del reloj (la Pi no tiene reloj
fiable hasta que tiene internet): reto y respuesta con la clave de la raspi,
que conocen la Pi y la app de cada usuario suyo (la descifra al entrar).

  GET  /api/raspi          {raspi, nombre, acceso}        (publico)
  GET  /api/usuario/<u>    su clave cifrada, para entrar desde la web de la Pi
  GET  /api/reto           {reto}                          (valido 60 s, un uso)
  POST /api/entrar         {usuario, reto, firma} -> {sesion}
       firma = hex(HMAC-SHA256(k, reto + "|" + usuario)),
       k = HMAC-SHA256(clave de la raspi, "telemetria-acceso")
La sesion (12 h) va en 'Authorization: Bearer <sesion>' o en ?s=<sesion>
(EventSource no deja poner cabeceras). Mismo calculo en web/cuenta.js.
"""

import hashlib
import hmac
import secrets
import threading
import time

DURACION = 12 * 3600
RETO_S = 60


class Acceso:
    def __init__(self, clave, raspi, nombre, existe_usuario):
        self.k = hmac.new(clave, b"telemetria-acceso", hashlib.sha256).digest()
        self.raspi = raspi
        self.nombre = nombre
        self.existe_usuario = existe_usuario   # usuario -> bool (repo de datos)
        self.lock = threading.Lock()
        self.retos = {}                        # reto -> caduca (monotonic)
        self.sesiones = {}                     # sesion -> (usuario, caduca)

    def _purgar(self, ahora):
        self.retos = {r: c for r, c in self.retos.items() if c > ahora}
        self.sesiones = {s: v for s, v in self.sesiones.items() if v[1] > ahora}

    def reto(self):
        r = secrets.token_hex(16)
        with self.lock:
            ahora = time.monotonic()
            self._purgar(ahora)
            if len(self.retos) > 1000:          # que nadie llene la memoria
                raise ValueError("demasiados intentos: espera un minuto")
            self.retos[r] = ahora + RETO_S
        return {"reto": r}

    def entrar(self, usuario, reto, firma):
        with self.lock:
            caduca = self.retos.pop(reto or "", None)
        if caduca is None or caduca < time.monotonic():
            raise PermissionError("reto caducado: vuelve a intentarlo")
        esperada = hmac.new(self.k, "{}|{}".format(reto, usuario).encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(esperada, str(firma or "")) or \
                not self.existe_usuario(usuario):
            raise PermissionError("no eres usuario de esta raspi")
        s = secrets.token_urlsafe(32)
        with self.lock:
            self.sesiones[s] = (usuario, time.monotonic() + DURACION)
        return {"sesion": s, "usuario": usuario, "dura_s": DURACION}

    def usuario(self, sesion):
        """Usuario de una sesion valida, o None (tambien si ya lo han borrado)."""
        if not sesion:
            return None
        with self.lock:
            v = self.sesiones.get(sesion)
        if v is None or v[1] < time.monotonic() or not self.existe_usuario(v[0]):
            return None
        return v[0]

    def info(self):
        return {"raspi": self.raspi, "nombre": self.nombre, "acceso": True}
