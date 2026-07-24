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
  open_folder, success, click, error, clear, thinking, page_scrolled

Uso:
    from app.motor.reproductor_sonidos import reproducir, CLICK, ERROR
    reproducir(CLICK)                          # desde hilo principal
    wx.CallAfter(reproducir, PROGRESS)         # desde hilo de fondo

Bucle (thinking.wav mientras se espera una respuesta):
    from app.motor.reproductor_sonidos import iniciar_bucle, detener_bucle, THINKING
    iniciar_bucle(THINKING)
    detener_bucle()

Preferencia global "sonidos_habilitados" (Ajustes → Efectos de sonido):
    from app.motor.reproductor_sonidos import sonidos_habilitados, fijar_sonidos_habilitados
"""

import json
import os
import logging
import threading

from app.config_rutas import RAIZ_RECURSOS, ruta_config, CONFIG_DIR

logger = logging.getLogger(__name__)

_RUTA_SONIDOS = os.path.join(RAIZ_RECURSOS, "recursos", "sonidos")

# ── Constantes canónicas ──────────────────────────────────────────────────────
APP_READY     = "app_ready"
REC_START     = "rec_start"
REC_END       = "rec_end"
PROGRESS      = "progress"
LIST_NAV      = "list_nav"
MOVE_UP       = "move_up"
MOVE_DOWN     = "move_down"
OPEN_FOLDER   = "open_folder"
SUCCESS       = "success"
CLICK         = "click"
ERROR         = "error"
CLEAR         = "clear"
THINKING      = "thinking"
PAGE_SCROLLED = "page_scrolled"

# Sonidos disponibles para el selector de prueba de Ajustes → Efectos de sonido.
SONIDOS_DISPONIBLES = {
    APP_READY:     "Inicio de la aplicación",
    REC_START:     "Inicio de grabación",
    REC_END:       "Fin de grabación",
    PROGRESS:      "Progreso",
    LIST_NAV:      "Navegación por listas",
    MOVE_UP:       "Mover hacia arriba",
    MOVE_DOWN:     "Mover hacia abajo",
    OPEN_FOLDER:   "Abrir carpeta",
    SUCCESS:       "Operación completada",
    CLICK:         "Clic",
    ERROR:         "Error",
    CLEAR:         "Borrar",
    THINKING:      "Asistente pensando (bucle)",
    PAGE_SCROLLED: "Cambio de página en Lectura",
}

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

# ── Preferencia global "sonidos_habilitados" ──────────────────────────────────
# Se guarda en ajustes.json junto al resto de preferencias generales. Se lee
# de forma perezosa (no hace falta al importar el módulo, antes de que exista
# configuraciones/ en una instalación nueva) y se cachea en memoria.
_HABILITADOS = True
_preferencia_cargada = False
_bucle_activo = None  # nombre del sonido en bucle actualmente, o None


def _cargar_preferencia_habilitados() -> None:
    global _HABILITADOS, _preferencia_cargada
    if _preferencia_cargada:
        return
    _preferencia_cargada = True
    try:
        with open(ruta_config("ajustes.json"), "r", encoding="utf-8") as f:
            _HABILITADOS = json.load(f).get("sonidos_habilitados", True)
    except FileNotFoundError:
        pass  # instalación nueva: ajustes.json todavía no existe, se queda en True
    except Exception:
        logger.exception("[Sonidos] Error al leer la preferencia 'sonidos_habilitados'")


def sonidos_habilitados() -> bool:
    _cargar_preferencia_habilitados()
    return _HABILITADOS


def fijar_sonidos_habilitados(valor: bool) -> None:
    """Actualiza la preferencia en memoria y la persiste en ajustes.json."""
    global _HABILITADOS, _preferencia_cargada
    _HABILITADOS = bool(valor)
    _preferencia_cargada = True
    if not _HABILITADOS:
        detener_bucle()
    try:
        ruta = ruta_config("ajustes.json")
        datos = {}
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
        datos["sonidos_habilitados"] = _HABILITADOS
        os.makedirs(CONFIG_DIR, exist_ok=True)
        ruta_tmp = ruta + ".tmp"
        with open(ruta_tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=4)
        os.replace(ruta_tmp, ruta)
    except Exception:
        logger.exception("[Sonidos] Error al guardar la preferencia 'sonidos_habilitados'")


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

def reproducir(nombre_sonido: str, forzar: bool = False) -> None:
    """
    Reproduce el sonido indicado de forma asíncrona.

    Debe llamarse desde el hilo principal de wx.
    Desde hilos de fondo: wx.CallAfter(reproducir, NOMBRE_SONIDO).

    forzar=True ignora la casilla global "Habilitar efectos de sonido" —
    solo lo usa el botón "Probar sonido" de Ajustes, para poder previsualizar
    un efecto incluso con los sonidos desactivados.
    """
    if not forzar and not sonidos_habilitados():
        return

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


# ── Bucle continuo (thinking.wav mientras se espera al Asistente) ────────────

def iniciar_bucle(nombre_sonido: str) -> None:
    """
    Reproduce el sonido indicado en bucle hasta la siguiente llamada a
    detener_bucle(). Solo puede haber un sonido en bucle a la vez.
    Debe llamarse desde el hilo principal de wx.
    """
    global _bucle_activo
    if not sonidos_habilitados():
        return
    if _bucle_activo == nombre_sonido:
        return  # ya está sonando, no reiniciar
    detener_bucle()

    if not _wx_cache_listo:
        _inicializar_wx()

    sound = _CACHE_SONIDOS.get(nombre_sonido)
    if sound is not None:
        try:
            import wx.adv
            if sound.Play(wx.adv.SOUND_ASYNC | wx.adv.SOUND_LOOP):
                _bucle_activo = nombre_sonido
                return
        except Exception as exc:
            logger.debug("[Sonidos] Bucle con wx.adv.Sound falló ('%s'): %s", nombre_sonido, exc)

    # ── Fallback: winsound (SND_LOOP también es asíncrono en background) ──
    ruta = _CACHE_RUTA.get(nombre_sonido)
    if ruta:
        try:
            import winsound
            winsound.PlaySound(
                ruta,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP | winsound.SND_NODEFAULT,
            )
            _bucle_activo = nombre_sonido
        except Exception as exc:
            logger.warning("[Sonidos] Bucle fallback winsound también falló ('%s'): %s", nombre_sonido, exc)


def detener_bucle() -> None:
    """Detiene el sonido en bucle actual, si hay alguno sonando."""
    global _bucle_activo
    if _bucle_activo is None:
        return
    _bucle_activo = None
    try:
        import wx.adv
        wx.adv.Sound.Stop()
    except Exception as exc:
        logger.debug("[Sonidos] Error al detener el bucle con wx.adv.Sound: %s", exc)
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception as exc:
        logger.debug("[Sonidos] Error al detener el bucle con winsound: %s", exc)
# ANCLAJE_FIN: REPRODUCTOR_SONIDOS
