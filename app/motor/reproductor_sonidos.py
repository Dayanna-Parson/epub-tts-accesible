# ANCLAJE_INICIO: REPRODUCTOR_SONIDOS
"""
reproductor_sonidos.py
───────────────────────
Infraestructura de sonidos de la aplicación.

Características:
  · Reproducción asíncrona (hilo daemon) → nunca bloquea la UI.
  · Sin excepciones si el archivo .wav no existe.
  · Sin excepciones si winsound no está disponible (Linux/Mac).
  · Las constantes canónicas se pueden importar directamente para
    evitar cadenas literales dispersas por el código.

Archivos esperados en /recursos/sonidos/  (WAV 16-bit, 44100 Hz):
  app_ready.wav     ventana principal completamente cargada y lista
  rec_start.wav     inicio de grabación multivoz
  rec_end.wav       fin de grabación multivoz (éxito real)
  progress.wav      tick rítmico durante proceso largo (modo no dividido)
  list_nav.wav      navegación con flechas en listas y árboles
  move_up.wav       nodo o elemento movido hacia arriba
  move_down.wav     nodo o elemento movido hacia abajo
  open_folder.wav   apertura de diálogo o carpeta
  success.wav       proceso largo completado con éxito
  click.wav         clic en botón simple o cambio de pestaña
  error.wav         error en cualquier operación
  clear.wav         borrado o limpieza de elementos

Uso:
    from app.motor.reproductor_sonidos import reproducir, CLICK, ERROR
    reproducir(CLICK)   # no bloquea, no lanza excepción
"""

import os
import threading

from app.config_rutas import RAIZ

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

# Alias de compatibilidad con código previo
REC_STOP     = REC_END
REC_PROGRESS = PROGRESS
PROCESO      = PROGRESS
VOZ_NUEVA    = SUCCESS
APP_UPDATE   = SUCCESS


# ── API pública ───────────────────────────────────────────────────────────────

def reproducir(nombre_sonido: str):
    """
    Reproduce <nombre_sonido>.wav de forma asíncrona.
    No hace nada si el archivo no existe o winsound no está disponible.
    """
    ruta = os.path.join(_RUTA_SONIDOS, f"{nombre_sonido}.wav")
    if not os.path.exists(ruta):
        return
    threading.Thread(target=_play_wav, args=(ruta,), daemon=True).start()


# ── Implementación privada ────────────────────────────────────────────────────

def _play_wav(ruta: str):
    """Reproduce un WAV de forma bloqueante (ejecutado dentro de hilo daemon)."""
    try:
        import winsound
        winsound.PlaySound(
            ruta,
            winsound.SND_FILENAME | winsound.SND_NODEFAULT,
        )
    except Exception:
        pass
# ANCLAJE_FIN: REPRODUCTOR_SONIDOS
