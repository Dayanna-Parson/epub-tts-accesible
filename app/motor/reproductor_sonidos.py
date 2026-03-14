# ANCLAJE_INICIO: REPRODUCTOR_SONIDOS
"""
reproductor_sonidos.py
───────────────────────
Infraestructura de sonidos portables usando wxPython.

Motor principal: wx.adv.Sound
  · Parte de wxPython, que YA ES dependencia obligatoria de la app.
  · Funciona en cualquier Windows independientemente del driver de audio,
    configuración del sistema o versión de Python.
  · Reproduce WAV de forma asíncrona (SOUND_ASYNC) sin bloquear la UI.
  · IMPORTANTE: Play() debe llamarse desde el hilo principal de wx.
    Para llamadas desde hilos de fondo usar wx.CallAfter(reproducir, SONIDO).

Motor fallback: winsound (stdlib de Python en Windows)
  · Se usa si wx.adv.Sound falla por algún motivo inesperado.

Inicialización en dos fases:
  1. Al importar: _precargar_rutas() → guarda rutas en _CACHE_RUTA (sin wx).
  2. Primer reproducir(): _inicializar_wx() → crea objetos wx.adv.Sound.
     Esto ocurre siempre DESPUÉS de que wx.App esté activo.

Archivos en /recursos/sonidos/ (WAV 16-bit, 44100 Hz):
  app_ready, rec_start, rec_end, progress, list_nav, move_up, move_down,
  open_folder, success, click, error, clear

Uso:
    from app.motor.reproductor_sonidos import reproducir, CLICK, ERROR
    reproducir(CLICK)                          # desde hilo principal
    wx.CallAfter(reproducir, PROGRESS)         # desde hilo de fondo
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

# ── Cachés ────────────────────────────────────────────────────────────────────
_CACHE_RUTA:    dict[str, str]   = {}   # nombre → ruta absoluta  (llenado al importar)
_CACHE_SONIDOS: dict[str, object] = {}  # nombre → wx.adv.Sound   (llenado en primer uso)
_wx_cache_listo = False


# ── Fase 1: cargar rutas al importar (sin wx todavía) ────────────────────────

def _precargar_rutas() -> None:
    if not os.path.isdir(_RUTA_SONIDOS):
        logger.warning("[Sonidos] Directorio no encontrado: %s", _RUTA_SONIDOS)
        return
    for archivo in os.listdir(_RUTA_SONIDOS):
        if archivo.lower().endswith(".wav"):
            nombre = archivo[:-4]
            _CACHE_RUTA[nombre] = os.path.join(_RUTA_SONIDOS, archivo)
    logger.debug("[Sonidos] %d archivos disponibles en %s", len(_CACHE_RUTA), _RUTA_SONIDOS)

_precargar_rutas()


# ── Fase 2: crear objetos wx.adv.Sound (lazy, tras wx.App) ───────────────────

def _inicializar_wx() -> None:
    global _wx_cache_listo
    if _wx_cache_listo:
        return
    try:
        import wx
        import wx.adv
    except ImportError:
        logger.warning("[Sonidos] wx no disponible — usando fallback winsound")
        _wx_cache_listo = True
        return

    ok = 0
    for nombre, ruta in _CACHE_RUTA.items():
        try:
            s = wx.adv.Sound(ruta)
            if s.IsOk():
                _CACHE_SONIDOS[nombre] = s
                ok += 1
            else:
                logger.warning("[Sonidos] wx.adv.Sound rechazó '%s'", nombre)
        except Exception as exc:
            logger.warning("[Sonidos] Error cargando '%s': %s", nombre, exc)

    logger.debug("[Sonidos] %d/%d sonidos listos en wx.adv.Sound", ok, len(_CACHE_RUTA))
    _wx_cache_listo = True


# ── API pública ───────────────────────────────────────────────────────────────

def reproducir(nombre_sonido: str) -> None:
    """
    Reproduce el sonido indicado de forma asíncrona.

    Debe llamarse desde el hilo principal de wx.
    Desde hilos de fondo: wx.CallAfter(reproducir, NOMBRE_SONIDO).
    """
    # Inicialización lazy (primera llamada, wx.App ya activo)
    if not _wx_cache_listo:
        _inicializar_wx()

    # ── Motor principal: wx.adv.Sound ─────────────────────────────────────
    sound = _CACHE_SONIDOS.get(nombre_sonido)
    if sound is not None:
        try:
            import wx.adv
            sound.Play(wx.adv.SOUND_ASYNC)
            return
        except Exception as exc:
            logger.debug("[Sonidos] wx.adv.Sound.Play falló ('%s'): %s", nombre_sonido, exc)

    # ── Fallback: winsound en hilo daemon ─────────────────────────────────
    ruta = _CACHE_RUTA.get(nombre_sonido)
    if ruta:
        threading.Thread(
            target=_play_winsound, args=(ruta, nombre_sonido), daemon=True
        ).start()


def _play_winsound(ruta: str, nombre: str) -> None:
    """Fallback: winsound.PlaySound desde un hilo daemon."""
    try:
        import winsound
        winsound.PlaySound(ruta, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    except Exception as exc:
        logger.warning("[Sonidos] winsound también falló ('%s'): %s", nombre, exc)
# ANCLAJE_FIN: REPRODUCTOR_SONIDOS
