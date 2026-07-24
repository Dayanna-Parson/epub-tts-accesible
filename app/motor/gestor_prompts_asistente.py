# ANCLAJE_INICIO: PERSISTENCIA_PROMPTS_ASISTENTE
"""
Plantillas de prompt de sistema del Asistente de Biblioteca, guardadas por
el usuario para distintas ocasiones (recomendaciones, análisis crítico,
resúmenes rápidos...).

Cada plantilla es un archivo .txt independiente en
configuraciones/asistente_biblioteca/plantillas/<nombre>.txt, con el texto
del prompt tal cual (sin JSON ni escapado) — para que se puedan editar
directamente desde fuera de la app, con cualquier editor de texto. El
nombre de la plantilla es el propio nombre de archivo (sin ".txt").

Cuál es la plantilla activa se guarda aparte, en activo.json (un único
dato pequeño, no encaja en "una plantilla = un archivo"). Escritura
atómica (temp + os.replace) en ambos casos, mismo patrón que
gestor_chat_biblioteca.py y diccionario_pronunciacion.py.
"""
import glob
import json
import logging
import os

from app.config_rutas import ruta_config_asistente
from app.servicios.cliente_gemini import INSTRUCCION_SISTEMA_DEFECTO

logger = logging.getLogger(__name__)

NOMBRE_DEFECTO = "Por defecto"

_CARACTERES_PROHIBIDOS = '<>:"/\\|?*'
_RUTA_ACTIVO = ruta_config_asistente("activo.json")
_RUTA_PROMPTS_JSON_LEGACY = ruta_config_asistente("prompts_asistente.json")


def _carpeta_plantillas() -> str:
    return ruta_config_asistente("plantillas")


def _nombre_archivo_seguro(nombre: str) -> str:
    limpio = "".join(c for c in nombre if c not in _CARACTERES_PROHIBIDOS).strip()
    return limpio or "plantilla"


def _ruta_plantilla(nombre: str) -> str:
    return os.path.join(_carpeta_plantillas(), _nombre_archivo_seguro(nombre) + ".txt")


def _escribir_atomico(ruta: str, contenido: str):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    ruta_tmp = ruta + ".tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        f.write(contenido)
    os.replace(ruta_tmp, ruta)


def _migrar_json_legacy_si_hace_falta():
    """
    Migración de la versión anterior (todas las plantillas en un único
    prompts_asistente.json) a un archivo .txt por plantilla. Se ejecuta una
    sola vez: si ya hay algún .txt en plantillas/, no vuelve a mirar el
    JSON viejo.
    """
    if not os.path.exists(_RUTA_PROMPTS_JSON_LEGACY):
        return
    try:
        with open(_RUTA_PROMPTS_JSON_LEGACY, "r", encoding="utf-8") as f:
            datos = json.loads(f.read() or "{}")
        for prompt in datos.get("prompts", []):
            _escribir_atomico(_ruta_plantilla(prompt["nombre"]), prompt.get("texto", ""))
        if datos.get("activo"):
            _escribir_atomico(_RUTA_ACTIVO, json.dumps({"activo": datos["activo"]}, ensure_ascii=False))
        os.remove(_RUTA_PROMPTS_JSON_LEGACY)
        logger.info("Plantillas del Asistente de Biblioteca migradas a archivos .txt individuales")
    except Exception:
        logger.exception("Error al migrar prompts_asistente.json al nuevo formato por archivos")


def listar_prompts() -> list:
    """Lista de {"nombre", "texto"} con todas las plantillas guardadas."""
    carpeta = _carpeta_plantillas()
    if not os.path.isdir(carpeta):
        _migrar_json_legacy_si_hace_falta()
    plantillas = []
    for ruta in sorted(glob.glob(os.path.join(carpeta, "*.txt"))):
        nombre = os.path.splitext(os.path.basename(ruta))[0]
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                texto = f.read()
        except Exception:
            logger.exception("Error al leer la plantilla %s", ruta)
            continue
        if texto.strip():
            plantillas.append({"nombre": nombre, "texto": texto})
    if not plantillas:
        guardar_prompt(NOMBRE_DEFECTO, INSTRUCCION_SISTEMA_DEFECTO)
        fijar_prompt_activo(NOMBRE_DEFECTO)
        plantillas = [{"nombre": NOMBRE_DEFECTO, "texto": INSTRUCCION_SISTEMA_DEFECTO}]
    # NOMBRE_DEFECTO siempre primero si existe; el resto, alfabético.
    plantillas.sort(key=lambda p: (p["nombre"] != NOMBRE_DEFECTO, p["nombre"].lower()))
    return plantillas


def _nombre_activo_guardado():
    try:
        if os.path.exists(_RUTA_ACTIVO):
            with open(_RUTA_ACTIVO, "r", encoding="utf-8") as f:
                return json.loads(f.read() or "{}").get("activo")
    except Exception:
        logger.exception("Error al leer activo.json")
    return None


def obtener_prompt_activo() -> dict:
    """Plantilla marcada como activa (o la primera, si la marcada ya no existe)."""
    plantillas = listar_prompts()
    nombre_activo = _nombre_activo_guardado()
    for prompt in plantillas:
        if prompt["nombre"] == nombre_activo:
            return prompt
    return plantillas[0]


def fijar_prompt_activo(nombre: str):
    if any(p["nombre"] == nombre for p in listar_prompts()):
        try:
            _escribir_atomico(_RUTA_ACTIVO, json.dumps({"activo": nombre}, ensure_ascii=False))
        except Exception:
            logger.exception("Error al guardar activo.json")


def guardar_prompt(nombre: str, texto: str):
    """Crea una plantilla nueva, o actualiza el texto si ya existía ese nombre."""
    try:
        _escribir_atomico(_ruta_plantilla(nombre), texto)
    except Exception:
        logger.exception("Error al guardar la plantilla %s", nombre)


def borrar_prompt(nombre: str) -> bool:
    """
    Borra el archivo .txt de una plantilla. Siempre debe quedar al menos
    una: si nombre es la última, no hace nada y devuelve False.
    """
    if len(listar_prompts()) <= 1:
        return False
    era_la_activa = _nombre_activo_guardado() == nombre
    ruta = _ruta_plantilla(nombre)
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
    except Exception:
        logger.exception("Error al borrar la plantilla %s", nombre)
        return False
    if era_la_activa:
        restantes = listar_prompts()
        if restantes:
            fijar_prompt_activo(restantes[0]["nombre"])
    return True
# ANCLAJE_FIN: PERSISTENCIA_PROMPTS_ASISTENTE
