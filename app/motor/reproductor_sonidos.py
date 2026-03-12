# ANCLAJE_INICIO: REPRODUCTOR_SONIDOS
"""
reproductor_sonidos.py
───────────────────────
Infraestructura de sonidos de la aplicación.

Características:
  · Reproducción asíncrona (hilo daemon) → nunca bloquea la UI.
  · Sin excepciones si el archivo .wav no existe.
  · Sin excepciones si winsound no está disponible (Linux/Mac).
  · Las constantes canónicas (REC_START, ERROR, …) se pueden importar
    directamente para evitar cadenas literales dispersas por el código.

Archivos esperados en /recursos/sonidos/:
  rec_start.wav     inicio de grabación
  rec_stop.wav      fin de grabación
  rec_progress.wav  tick de progreso durante grabación
  proceso.wav       operación de larga duración en proceso
  voz_nueva.wav     nueva voz detectada al comparar con APIs
  app_update.wav    actualización de la aplicación disponible
  error.wav         error en cualquier operación

Uso:
    from app.motor.reproductor_sonidos import reproducir, PROCESO, ERROR
    reproducir(PROCESO)   # no bloquea, no lanza excepción
"""

import os
import threading

from app.config_rutas import RAIZ

_RUTA_SONIDOS = os.path.join(RAIZ, "recursos", "sonidos")

# ── Constantes canónicas ──────────────────────────────────────────────────────
REC_START    = "rec_start"
REC_STOP     = "rec_stop"
REC_PROGRESS = "rec_progress"
PROCESO      = "proceso"
VOZ_NUEVA    = "voz_nueva"
APP_UPDATE   = "app_update"
ERROR        = "error"


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
