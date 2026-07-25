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
import json
import locale
import logging
import os
import sys

from app.config_rutas import RAIZ_RECURSOS, ruta_config

logger = logging.getLogger(__name__)

DOMINIO = "epub_tts"
IDIOMA_POR_DEFECTO = "es"
IDIOMAS_DISPONIBLES = ("es", "en")

# Variable de entorno para forzar un idioma en pruebas locales, sin tener
# que cambiar el idioma completo de Windows (por ejemplo, para probar un
# .mo en inglés estando el sistema operativo en español):
#   set EPUB_TTS_IDIOMA=en   (cmd)
#   $env:EPUB_TTS_IDIOMA="en"  (PowerShell)
VARIABLE_ENTORNO_IDIOMA = "EPUB_TTS_IDIOMA"

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


def _idioma_desde_ajustes() -> str:
    """
    Lee `configuraciones/ajustes.json` en busca de una clave "idioma"
    fijada manualmente por la persona usuaria (selector pendiente en
    Ajustes). Si no existe el archivo, la clave o es inválida, no hay
    idioma forzado desde ajustes.
    """
    try:
        ruta = ruta_config("ajustes.json")
        if not os.path.exists(ruta):
            return None
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
        idioma = datos.get("idioma")
        if idioma in IDIOMAS_DISPONIBLES:
            return idioma
    except Exception:
        logger.exception("No se pudo leer el idioma desde ajustes.json")
    return None


def _resolver_idioma(idioma: str = None) -> str:
    """
    Orden de prioridad para elegir el idioma activo:
      1. Parámetro explícito pasado a inicializar().
      2. Variable de entorno EPUB_TTS_IDIOMA (pruebas locales sin cambiar
         el idioma del sistema operativo completo).
      3. Clave "idioma" en configuraciones/ajustes.json.
      4. Idioma detectado del sistema operativo Windows.
    """
    if idioma in IDIOMAS_DISPONIBLES:
        return idioma

    idioma_entorno = os.environ.get(VARIABLE_ENTORNO_IDIOMA)
    if idioma_entorno:
        idioma_entorno = idioma_entorno.strip().lower()
        if idioma_entorno in IDIOMAS_DISPONIBLES:
            return idioma_entorno
        logger.warning(
            "Idioma '%s' en %s no está soportado; se ignora",
            idioma_entorno, VARIABLE_ENTORNO_IDIOMA,
        )

    idioma_ajustes = _idioma_desde_ajustes()
    if idioma_ajustes:
        return idioma_ajustes

    return _detectar_idioma_sistema()


def inicializar(idioma: str = None) -> None:
    """
    Instala la traducción activa. Ver `_resolver_idioma()` para el orden
    de prioridad con el que se elige el idioma cuando no se fuerza uno
    explícitamente. Si no hay archivo .mo para el idioma elegido, se cae a
    una traducción nula (el texto original en español se muestra tal cual).
    Segura de llamar más de una vez.
    """
    global _traduccion
    idioma_elegido = _resolver_idioma(idioma)
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
