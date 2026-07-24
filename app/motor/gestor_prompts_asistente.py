# ANCLAJE_INICIO: PERSISTENCIA_PROMPTS_ASISTENTE
"""
Plantillas de prompt de sistema del Asistente de Biblioteca, guardadas por
el usuario para distintas ocasiones (recomendaciones, análisis crítico,
resúmenes rápidos...). Persistencia en configuraciones/prompts_asistente.json,
escritura atómica (temp + os.replace), mismo patrón que
gestor_chat_biblioteca.py y diccionario_pronunciacion.py.
"""
import json
import logging
import os

from app.config_rutas import ruta_config_asistente
from app.servicios.cliente_gemini import INSTRUCCION_SISTEMA_DEFECTO

logger = logging.getLogger(__name__)

_RUTA = ruta_config_asistente("prompts_asistente.json")

NOMBRE_DEFECTO = "Por defecto"


def _valores_por_defecto() -> dict:
    return {
        "prompts": [{"nombre": NOMBRE_DEFECTO, "texto": INSTRUCCION_SISTEMA_DEFECTO}],
        "activo": NOMBRE_DEFECTO,
    }


def _cargar_todo() -> dict:
    try:
        if os.path.exists(_RUTA):
            with open(_RUTA, "r", encoding="utf-8") as f:
                contenido = f.read().strip()
            if contenido:
                datos = json.loads(contenido)
                if datos.get("prompts"):
                    return datos
    except Exception:
        logger.exception("Error al leer prompts_asistente.json")
    return _valores_por_defecto()


def _guardar_todo(datos: dict):
    os.makedirs(os.path.dirname(_RUTA), exist_ok=True)
    ruta_tmp = _RUTA + ".tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta_tmp, _RUTA)


def listar_prompts() -> list:
    """Lista de {"nombre", "texto"} con todas las plantillas guardadas."""
    return list(_cargar_todo()["prompts"])


def obtener_prompt_activo() -> dict:
    """Plantilla marcada como activa (o la primera, si la marcada ya no existe)."""
    datos = _cargar_todo()
    nombre_activo = datos.get("activo", NOMBRE_DEFECTO)
    for prompt in datos["prompts"]:
        if prompt["nombre"] == nombre_activo:
            return prompt
    return datos["prompts"][0]


def fijar_prompt_activo(nombre: str):
    datos = _cargar_todo()
    if any(p["nombre"] == nombre for p in datos["prompts"]):
        datos["activo"] = nombre
        _guardar_todo(datos)


def guardar_prompt(nombre: str, texto: str):
    """Crea una plantilla nueva, o actualiza el texto si ya existía ese nombre."""
    datos = _cargar_todo()
    for prompt in datos["prompts"]:
        if prompt["nombre"] == nombre:
            prompt["texto"] = texto
            break
    else:
        datos["prompts"].append({"nombre": nombre, "texto": texto})
    _guardar_todo(datos)


def borrar_prompt(nombre: str) -> bool:
    """
    Borra una plantilla. Siempre debe quedar al menos una: si nombre es la
    última, no hace nada y devuelve False.
    """
    datos = _cargar_todo()
    if len(datos["prompts"]) <= 1:
        return False
    datos["prompts"] = [p for p in datos["prompts"] if p["nombre"] != nombre]
    if datos.get("activo") == nombre:
        datos["activo"] = datos["prompts"][0]["nombre"]
    _guardar_todo(datos)
    return True
# ANCLAJE_FIN: PERSISTENCIA_PROMPTS_ASISTENTE
