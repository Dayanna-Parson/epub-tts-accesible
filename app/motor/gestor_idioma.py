# ANCLAJE_INICIO: GESTOR_IDIOMA
"""
Internacionalización de las cadenas visibles al usuario final mediante
gettext (librería estándar), con detección del idioma de Windows al
arrancar y fallback automático a español si no hay traducción disponible.

No se inyecta `_` en builtins: cada módulo debe importar `traducir`
explícitamente (normalmente como `from app.motor.gestor_idioma import
traducir as _`). Inyectar en builtins puede fallar de forma silenciosa en
subprocesos (el proceso puente de SAPI5 32 bits) o en diálogos de wxPython
que se instancian antes de que el intérprete principal haya terminado de
inicializarse, así que se evita por completo.

Esta regla solo afecta a las cadenas de interfaz. El código interno
(variables, funciones, clases, logs) sigue en español, sin excepción.
"""
import gettext
import locale
import logging
import os
import sys

from app.config_rutas import RAIZ_RECURSOS

logger = logging.getLogger(__name__)

DOMINIO = "epub_tts"
IDIOMA_POR_DEFECTO = "es"
IDIOMAS_DISPONIBLES = ("es", "en")

_traduccion = None


def _ruta_locale():
    return os.path.join(RAIZ_RECURSOS, "locale")


def _detectar_idioma_sistema() -> str:
    """
    Detecta el idioma de la interfaz de Windows. Si no se puede determinar,
    o el resultado no está entre los idiomas soportados, cae a español.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            codigo = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            idioma = locale.windows_locale.get(codigo)
        else:
            idioma, _codificacion = locale.getdefaultlocale()
    except Exception:
        logger.exception("No se pudo detectar el idioma del sistema")
        idioma = None

    if not idioma:
        return IDIOMA_POR_DEFECTO

    idioma_base = idioma.split("_")[0].lower()
    if idioma_base in IDIOMAS_DISPONIBLES:
        return idioma_base
    return IDIOMA_POR_DEFECTO


def inicializar(idioma: str = None) -> None:
    """
    Instala la traducción activa. Si `idioma` es None, se detecta el idioma
    del sistema operativo. Si no hay archivo .mo para ese idioma, se cae a
    una traducción nula (el texto original en español se muestra tal cual).
    Segura de llamar más de una vez.
    """
    global _traduccion
    idioma_elegido = idioma or _detectar_idioma_sistema()
    try:
        _traduccion = gettext.translation(
            DOMINIO,
            localedir=_ruta_locale(),
            languages=[idioma_elegido, IDIOMA_POR_DEFECTO],
            fallback=True,
        )
    except Exception:
        logger.exception("No se pudo inicializar la traducción; usando texto original")
        _traduccion = gettext.NullTranslations()


def traducir(texto: str) -> str:
    """
    Devuelve `texto` traducido al idioma activo, o el propio texto en
    español si no hay traducción cargada o no existe una entrada para él.
    """
    if _traduccion is None:
        inicializar()
    return _traduccion.gettext(texto)


# Alias corto pensado para importarse como `from ... import traducir as _`.
_ = traducir
# ANCLAJE_FIN: GESTOR_IDIOMA
