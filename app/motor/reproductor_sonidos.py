# ANCLAJE_INICIO: REPRODUCTOR_SONIDOS
"""
reproductor_sonidos.py
───────────────────────
Infraestructura de sonidos de baja latencia.

Estrategia:
  1. Al importar el módulo, todos los .wav se leen a RAM (_CACHE_BYTES).
     También se guarda la ruta absoluta en _CACHE_RUTA como último recurso.
  2. Cada llamada a reproducir() hace solo un lookup en dict (sin I/O de disco).
  3. Ruta de reproducción (en orden):
       a) winsound.PlaySound(bytes, SND_MEMORY|SND_ASYNC|SND_NODEFAULT)
          — sin hilos, retorno inmediato; máxima latencia baja.
          — Si falla (algunos entornos Windows no admiten SND_ASYNC+SND_MEMORY):
       b) hilo daemon + SND_MEMORY (bloqueante dentro del hilo).
          — Los datos siguen siendo bytes en RAM, sin disco.
          — Si también falla (driver incompatible):
       c) hilo daemon + SND_FILENAME desde la ruta en caché.

Sin excepciones visibles; los fallos se registran en el log de la app.

Archivos en /recursos/sonidos/ (WAV 16-bit, 44100 Hz):
  app_ready, rec_start, rec_end, progress, list_nav, move_up, move_down,
  open_folder, success, click, error, clear

Uso:
    from app.motor.reproductor_sonidos import reproducir, CLICK, LIST_NAV
    reproducir(CLICK)   # instantáneo, no bloquea
"""

import os
import logging
import threading

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

# Alias de compatibilidad
REC_STOP     = REC_END
REC_PROGRESS = PROGRESS
PROCESO      = PROGRESS
VOZ_NUEVA    = SUCCESS
APP_UPDATE   = SUCCESS

# ── Cachés  ───────────────────────────────────────────────────────────────────
_CACHE_BYTES: dict[str, bytes] = {}   # nombre → datos WAV en RAM
_CACHE_RUTA:  dict[str, str]  = {}   # nombre → ruta absoluta (fallback final)


def _poblar_cache() -> None:
    """Lee todos los .wav del directorio de sonidos a memoria al arrancar."""
    if not os.path.isdir(_RUTA_SONIDOS):
        logger.warning("[Sonidos] Directorio no encontrado: %s", _RUTA_SONIDOS)
        return

    cargados = 0
    for archivo in os.listdir(_RUTA_SONIDOS):
        if not archivo.lower().endswith(".wav"):
            continue
        nombre = archivo[:-4]
        ruta   = os.path.join(_RUTA_SONIDOS, archivo)
        _CACHE_RUTA[nombre] = ruta
        try:
            with open(ruta, "rb") as f:
                _CACHE_BYTES[nombre] = f.read()
            cargados += 1
        except OSError as exc:
            logger.warning("[Sonidos] No se pudo leer %s: %s", archivo, exc)

    logger.info("[Sonidos] %d/%d archivos en caché RAM (%s)",
                cargados, cargados, _RUTA_SONIDOS)


_poblar_cache()   # una sola vez al importar el módulo


# ── API pública ───────────────────────────────────────────────────────────────

def reproducir(nombre_sonido: str) -> None:
    """
    Reproduce el sonido desde RAM sin bloquear el hilo de la UI.
    Tres niveles de fallback garantizan que el sonido se escuche
    aunque la configuración de Windows no admita SND_ASYNC+SND_MEMORY.
    """
    datos = _CACHE_BYTES.get(nombre_sonido)
    ruta  = _CACHE_RUTA.get(nombre_sonido)

    if not datos and not ruta:
        # Sonido no cargado — ocurre si el .wav no existe en disco
        return

    # ── Nivel A: SND_MEMORY + SND_ASYNC (sin hilo, máxima velocidad) ─────
    if datos:
        try:
            import winsound
            winsound.PlaySound(
                datos,
                winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return   # éxito: salida rápida
        except Exception as exc:
            logger.debug(
                "[Sonidos] SND_MEMORY|SND_ASYNC no disponible para '%s': %s",
                nombre_sonido, exc,
            )

    # ── Nivel B: SND_MEMORY bloqueante en hilo daemon ─────────────────────
    if datos:
        threading.Thread(
            target=_play_memory, args=(datos, nombre_sonido), daemon=True
        ).start()
        return

    # ── Nivel C: SND_FILENAME desde ruta en caché (último recurso) ────────
    if ruta:
        threading.Thread(
            target=_play_filename, args=(ruta, nombre_sonido), daemon=True
        ).start()


# ── Implementaciones privadas ─────────────────────────────────────────────────

def _play_memory(datos: bytes, nombre: str) -> None:
    """Reproduce bytes WAV de forma bloqueante (dentro de un hilo daemon)."""
    try:
        import winsound
        winsound.PlaySound(datos, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception as exc:
        logger.warning("[Sonidos] _play_memory falló para '%s': %s", nombre, exc)


def _play_filename(ruta: str, nombre: str) -> None:
    """Fallback final: reproduce desde ruta en disco (dentro de un hilo daemon)."""
    try:
        import winsound
        winsound.PlaySound(ruta, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    except Exception as exc:
        logger.warning("[Sonidos] _play_filename falló para '%s': %s", nombre, exc)
# ANCLAJE_FIN: REPRODUCTOR_SONIDOS
