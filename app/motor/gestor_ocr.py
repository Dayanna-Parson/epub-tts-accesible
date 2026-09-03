# ANCLAJE_INICIO: GESTOR_OCR
"""
gestor_ocr.py
─────────────
Reconocimiento óptico de caracteres para páginas de PDF sin texto propio
(documentos escaneados). Arquitectura pensada para varios motores
intercambiables, igual que hace un lector de referencia consultado en el
diseño de esta función:

- "windows": Windows.Media.Ocr vía winsdk. Gratis, sin binario que empaquetar,
  sin conexión ni cuota. Implementado en esta fase.
- "tesseract": pendiente de una fase posterior (binario portable en /bin/).
- "gemini": pendiente de una fase posterior (reutilizará cliente_gemini.py
  para las páginas más complejas: tablas, gráficos, texto dentro de imágenes).

La configuración vive en ajustes.json junto al resto de preferencias
generales, con el mismo patrón de lectura perezosa y escritura atómica que
ya usa reproductor_sonidos.py para sus propias preferencias.
"""

import asyncio
import json
import logging
import os

from app.config_rutas import ruta_config, CONFIG_DIR

logger = logging.getLogger(__name__)

MOTOR_NINGUNO = "ninguno"
MOTOR_WINDOWS = "windows"
MOTOR_TESSERACT = "tesseract"
MOTOR_GEMINI = "gemini"

MOTORES_IMPLEMENTADOS = (MOTOR_WINDOWS,)

TOPE_PAGINAS_POR_DEFECTO = 100

_config_cargada = False
_CONFIG = {
    "ocr_activado": False,
    "ocr_motor": MOTOR_NINGUNO,
    "ocr_idioma": "es",
    "ocr_tope_paginas": TOPE_PAGINAS_POR_DEFECTO,
}


def _leer_ajustes_json() -> dict:
    try:
        with open(ruta_config("ajustes.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Error al leer ajustes.json para la configuración de OCR")
        return {}


def _escribir_ajustes_json(cambios: dict) -> None:
    try:
        ruta = ruta_config("ajustes.json")
        datos = {}
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
        datos.update(cambios)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        ruta_tmp = ruta + ".tmp"
        with open(ruta_tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=4)
        os.replace(ruta_tmp, ruta)
    except Exception:
        logger.exception("Error al guardar la configuración de OCR en ajustes.json")


def _cargar_config() -> None:
    global _config_cargada
    if _config_cargada:
        return
    _config_cargada = True
    datos = _leer_ajustes_json()
    _CONFIG["ocr_activado"] = datos.get("ocr_activado", False)
    _CONFIG["ocr_motor"] = datos.get("ocr_motor", MOTOR_NINGUNO)
    _CONFIG["ocr_idioma"] = datos.get("ocr_idioma", "es")
    _CONFIG["ocr_tope_paginas"] = datos.get("ocr_tope_paginas", TOPE_PAGINAS_POR_DEFECTO)


def obtener_config_ocr() -> dict:
    _cargar_config()
    return dict(_CONFIG)


def fijar_config_ocr(**cambios) -> None:
    """Actualiza una o varias claves (ocr_activado, ocr_motor, ocr_idioma,
    ocr_tope_paginas) en memoria y las persiste todas juntas."""
    _cargar_config()
    _CONFIG.update(cambios)
    _escribir_ajustes_json(dict(_CONFIG))


def motor_disponible(motor: str) -> bool:
    """
    Comprueba si el motor indicado puede usarse ahora mismo en este equipo.
    No lanza excepción: una librería que falte es un caso esperado, no un
    error de programa.
    """
    if motor == MOTOR_WINDOWS:
        try:
            import winsdk.windows.media.ocr  # noqa: F401
        except Exception:
            return False
        return True
    # Tesseract y Gemini se implementan en una fase posterior.
    return False


def reconocer_pagina(datos_png: bytes, motor: str, idioma: str = "es") -> str:
    """
    Reconoce el texto de una imagen de página (PNG en memoria) con el motor
    indicado. Devuelve cadena vacía si el motor no está disponible o no
    reconoce nada — un fallo de OCR en una sola página nunca debe abortar
    la extracción de todo el PDF.
    """
    if motor == MOTOR_WINDOWS:
        return _reconocer_pagina_windows(datos_png, idioma)
    logger.warning("Motor de OCR «%s» no implementado todavía", motor)
    return ""


def _reconocer_pagina_windows(datos_png: bytes, idioma: str) -> str:
    try:
        import winsdk.windows.globalization as ws_globalizacion
        import winsdk.windows.graphics.imaging as ws_imagenes
        import winsdk.windows.media.ocr as ws_ocr
        import winsdk.windows.storage.streams as ws_flujos
    except ImportError:
        logger.warning(
            "winsdk no está instalado: el motor de OCR de Windows no está disponible"
        )
        return ""

    async def _reconocer_async():
        flujo = ws_flujos.InMemoryRandomAccessStream()
        escritor = ws_flujos.DataWriter(flujo)
        escritor.write_bytes(datos_png)
        await escritor.store_async()
        await escritor.flush_async()
        flujo.seek(0)

        decodificador = await ws_imagenes.BitmapDecoder.create_async(flujo)
        mapa_bits = await decodificador.get_software_bitmap_async()

        idioma_ocr = ws_globalizacion.Language(idioma)
        if ws_ocr.OcrEngine.is_language_supported(idioma_ocr):
            motor_ocr = ws_ocr.OcrEngine.try_create_from_language(idioma_ocr)
        else:
            motor_ocr = ws_ocr.OcrEngine.try_create_from_user_profile_languages()
        if motor_ocr is None:
            logger.warning(
                "No hay ningún idioma de OCR de Windows instalado que sirva para «%s»", idioma
            )
            return ""

        resultado = await motor_ocr.recognize_async(mapa_bits)
        return resultado.text or ""

    try:
        return asyncio.run(_reconocer_async())
    except Exception:
        logger.exception("Fallo al reconocer una página con el motor de OCR de Windows")
        return ""
# ANCLAJE_FIN: GESTOR_OCR
