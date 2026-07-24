# ANCLAJE_INICIO: PERSISTENCIA_CHAT_BIBLIOTECA
"""
Persistencia del historial de conversación del Asistente de Biblioteca.

Formato de chat_biblioteca.json:
    {
      "general": [
        {"rol": "usuario", "texto": "..."},
        {"rol": "asistente", "texto": "..."}
      ],
      "<id_libro>": [
        {"rol": "usuario", "texto": "..."},
        {"rol": "asistente", "texto": "..."}
      ]
    }

"general" es la clave usada cuando el chat se abre sin ningún libro
seleccionado en la Biblioteca. El resto de claves son el id_libro de
biblioteca.db (como str, para que la clave sea válida en JSON).

Solo se guardan metadatos y los mensajes escritos en la conversación —
nunca el texto completo del libro (ver CLIENTE_GEMINI_ENVIO_MENSAJE).
"""
import json
import logging
import os

from app.config_rutas import ruta_carpeta_asistente, ruta_config_asistente

logger = logging.getLogger(__name__)

_RUTA = ruta_config_asistente("chat_biblioteca.json")

CLAVE_GENERAL = "general"


def ruta_carpeta():
    """Carpeta donde vive chat_biblioteca.json — para sugerir como destino
    por defecto al exportar una conversación a mano (Guardar conversación...)."""
    return ruta_carpeta_asistente()


def _cargar_todo() -> dict:
    try:
        if os.path.exists(_RUTA):
            with open(_RUTA, "r", encoding="utf-8") as f:
                contenido = f.read().strip()
            if contenido:
                return json.loads(contenido)
    except Exception:
        logger.exception("Error al leer chat_biblioteca.json")
    return {}


def _guardar_todo(datos: dict):
    os.makedirs(os.path.dirname(_RUTA), exist_ok=True)
    ruta_tmp = _RUTA + ".tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta_tmp, _RUTA)


def clave_para_libro(id_libro) -> str:
    """Normaliza id_libro a la clave de string usada en el JSON."""
    return str(id_libro) if id_libro is not None else CLAVE_GENERAL


def cargar_historial(id_libro=None) -> list:
    """
    Devuelve el historial (lista de {"rol", "texto"}) para el libro dado,
    o el historial general si id_libro es None. Lectura en el hilo
    principal: es un archivo pequeño, no requiere hilo secundario.
    """
    datos = _cargar_todo()
    return list(datos.get(clave_para_libro(id_libro), []))


def agregar_turno(id_libro, rol: str, texto: str):
    """
    Añade un turno ({"rol": rol, "texto": texto}) al historial del libro
    (o general) y persiste de forma atómica (temp + rename).
    """
    clave = clave_para_libro(id_libro)
    try:
        datos = _cargar_todo()
        datos.setdefault(clave, []).append({"rol": rol, "texto": texto})
        _guardar_todo(datos)
    except Exception:
        logger.exception("Error al guardar turno en chat_biblioteca.json")


def borrar_historial(id_libro=None):
    """Elimina el historial de un libro (o el general) del JSON."""
    clave = clave_para_libro(id_libro)
    try:
        datos = _cargar_todo()
        if clave in datos:
            del datos[clave]
            _guardar_todo(datos)
    except Exception:
        logger.exception("Error al borrar historial en chat_biblioteca.json")
# ANCLAJE_FIN: PERSISTENCIA_CHAT_BIBLIOTECA
