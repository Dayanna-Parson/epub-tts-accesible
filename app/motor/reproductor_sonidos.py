# ANCLAJE_INICIO: REPRODUCTOR_SONIDOS
"""
reproductor_sonidos.py
───────────────────────
Infraestructura de sonidos de baja latencia.

Estrategia de latencia mínima:
  1. Al importar el módulo, todos los .wav se leen a RAM (_CACHE).
  2. Cada reproducción usa winsound.PlaySound(bytes, SND_MEMORY | SND_ASYNC):
       · SND_MEMORY  → datos desde RAM, sin I/O de disco en el evento.
       · SND_ASYNC   → devuelve control de inmediato (no bloquea la UI).
       · SND_NODEFAULT → sin sonido de sistema si falla.
  3. No se crean hilos manuales: el OS gestiona el audio.
  4. Llamadas rápidas sucesivas (e.g. LIST_NAV) interrumpen el anterior
     y arrancan el nuevo al instante → efecto "click" limpio sin cola.

Sin excepciones si el archivo .wav no existe o winsound no está disponible.

Archivos en /recursos/sonidos/ (WAV 16-bit, 44100 Hz):
  app_ready.wav   open_folder.wav   rec_start.wav   rec_end.wav
  progress.wav    list_nav.wav      move_up.wav     move_down.wav
  success.wav     click.wav         error.wav       clear.wav

Uso:
    from app.motor.reproductor_sonidos import reproducir, CLICK, LIST_NAV
    reproducir(CLICK)   # instantáneo, no bloquea
"""

import os
import logging

from app.config_rutas import RAIZ

logger = logging.getLogger(__name__)

_RUTA_SONIDOS = os.path.join(RAIZ, "recursos", "sonidos")

# ── Constantes canónicas ──────────────────────────────────────────────────────
APP_READY   = "app_ready"
REC_START   = "rec_start"
REC_END     = "rec_end"
PROGRESS    = "progress"
LIST_NAV    = "list_nav"
MOVE_UP     = "move_up"
MOVE_DOWN   = "move_down"
OPEN_FOLDER = "open_folder"
SUCCESS     = "success"
CLICK       = "click"
ERROR       = "error"
CLEAR       = "clear"

# Alias de compatibilidad con sesiones anteriores
REC_STOP     = REC_END
REC_PROGRESS = PROGRESS
PROCESO      = PROGRESS
VOZ_NUEVA    = SUCCESS
APP_UPDATE   = SUCCESS

# ── Caché de bytes en RAM  ────────────────────────────────────────────────────
# Cargada una sola vez al importar el módulo.
# Las claves son los nombres sin extensión (= las constantes de arriba).
_CACHE: dict[str, bytes] = {}

def _poblar_cache() -> None:
    """Lee todos los .wav disponibles y los deja en memoria."""
    try:
        if not os.path.isdir(_RUTA_SONIDOS):
            return
        for archivo in os.listdir(_RUTA_SONIDOS):
            if archivo.lower().endswith(".wav"):
                nombre = archivo[:-4]               # quita ".wav"
                ruta   = os.path.join(_RUTA_SONIDOS, archivo)
                try:
                    with open(ruta, "rb") as f:
                        _CACHE[nombre] = f.read()
                except OSError as exc:
                    logger.debug("[Sonidos] No se pudo leer %s: %s", archivo, exc)
    except Exception as exc:
        logger.debug("[Sonidos] Error al poblar caché: %s", exc)

_poblar_cache()   # se ejecuta una sola vez al importar


# ── API pública ───────────────────────────────────────────────────────────────

def reproducir(nombre_sonido: str) -> None:
    """
    Reproduce el sonido indicado desde RAM, sin bloquear y sin hilos manuales.
    No hace nada si el sonido no está en caché o winsound no está disponible.
    """
    datos = _CACHE.get(nombre_sonido)
    if not datos:
        return
    try:
        import winsound
        winsound.PlaySound(
            datos,
            winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except Exception:
        pass
# ANCLAJE_FIN: REPRODUCTOR_SONIDOS
