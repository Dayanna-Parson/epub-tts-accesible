# ANCLAJE_INICIO: CLIENTE_GEMINI
import logging

import requests

from app.config_rutas import cargar_claves

logger = logging.getLogger(__name__)

_URL_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = 30

# Instrucción de sistema: pide a Gemini que se apoye en la búsqueda web para no
# alucinar datos sobre libros (tramas, autores, ediciones, disponibilidad).
_INSTRUCCION_SISTEMA = (
    "Eres el Asistente de Biblioteca de una aplicación de audiolibros para "
    "personas ciegas. Ayudas con recomendaciones, dudas sobre autores, tramas "
    "y ediciones de libros. Cuando cites datos concretos (argumento, autor, año, "
    "edición, disponibilidad), apóyate en la búsqueda web para verificarlos en "
    "fuentes fiables como Goodreads o tiendas de libros como Kindle España, en "
    "vez de inventarlos de memoria. Responde en español, de forma clara y breve, "
    "pensando en que la respuesta puede leerse con un lector de pantalla."
)
# ANCLAJE_FIN: CLIENTE_GEMINI


# ANCLAJE_INICIO: CLIENTE_GEMINI_LISTA_MODELOS
def _clave_api():
    return cargar_claves().get("gemini", {}).get("api_key", "").strip()


def listar_modelos() -> list:
    """
    Consulta GET /v1beta/models y devuelve los nombres de modelo (sin el
    prefijo "models/") que soportan generateContent. Se llama en cada
    comprobación de clave para que la lista se actualice sola cuando Google
    publique modelos nuevos, sin tocar código.
    """
    api_key = _clave_api()
    if not api_key:
        raise ValueError("No hay ninguna clave de Gemini configurada.")

    modelos = []
    url = f"{_URL_BASE}/models"
    parametros = {"key": api_key, "pageSize": 100}
    while True:
        resp = requests.get(url, params=parametros, timeout=_TIMEOUT)
        resp.raise_for_status()
        datos = resp.json()
        for modelo in datos.get("models", []):
            metodos = modelo.get("supportedGenerationMethods", [])
            if "generateContent" in metodos:
                nombre = modelo.get("name", "")
                modelos.append(nombre.split("/", 1)[-1] if "/" in nombre else nombre)
        token_pagina = datos.get("nextPageToken")
        if not token_pagina:
            break
        parametros = {"key": api_key, "pageSize": 100, "pageToken": token_pagina}
    return modelos


def _elegir_modelo_automatico(modelos, analisis_profundo=False):
    """
    Modo "Automático": Flash para preguntas rápidas, Pro para análisis
    profundos. Si no encuentra ninguno con ese nombre, usa el primero que
    haya devuelto la API (siempre soporta generateContent).
    """
    if not modelos:
        raise ValueError("La cuenta de Gemini no tiene modelos disponibles.")
    objetivo = "pro" if analisis_profundo else "flash"
    for nombre in modelos:
        if objetivo in nombre.lower():
            return nombre
    return modelos[0]
# ANCLAJE_FIN: CLIENTE_GEMINI_LISTA_MODELOS


# ANCLAJE_INICIO: CLIENTE_GEMINI_ENVIO_MENSAJE
def _construir_contexto_libro(contexto_libro):
    if not contexto_libro:
        return None
    partes = []
    if contexto_libro.get("titulo"):
        partes.append(f"Título: {contexto_libro['titulo']}")
    if contexto_libro.get("autor"):
        partes.append(f"Autor: {contexto_libro['autor']}")
    if contexto_libro.get("categoria"):
        partes.append(f"Categoría/etiquetas: {contexto_libro['categoria']}")
    if contexto_libro.get("estado"):
        partes.append(f"Estado de lectura: {contexto_libro['estado']}")
    if not partes:
        return None
    return "Libro seleccionado en la Biblioteca:\n" + "\n".join(partes)


def enviar_mensaje(historial, mensaje_usuario, contexto_libro=None,
                    modelo=None, analisis_profundo=False, busqueda_web=True) -> str:
    """
    Envía un mensaje a Gemini con el historial previo y, si lo hay, el
    contexto del libro seleccionado (solo metadatos, nunca el texto del
    libro). Devuelve el texto de la respuesta.

    historial: lista de dicts {"rol": "usuario"|"asistente", "texto": str},
    ya cargada desde chat_biblioteca.json por gestor_chat_biblioteca.

    Se llama siempre desde un hilo secundario (ver DIALOGO_ASISTENTE_BIBLIOTECA).
    """
    api_key = _clave_api()
    if not api_key:
        raise ValueError("No hay ninguna clave de Gemini configurada.")

    datos_gemini = cargar_claves().get("gemini", {})
    modelo_elegido = modelo or datos_gemini.get("modelo", "auto")
    if not modelo_elegido or modelo_elegido == "auto":
        modelo_elegido = _elegir_modelo_automatico(listar_modelos(), analisis_profundo)

    contenidos = []
    contexto_texto = _construir_contexto_libro(contexto_libro)
    if contexto_texto:
        contenidos.append({"role": "user", "parts": [{"text": contexto_texto}]})
        contenidos.append({"role": "model", "parts": [{"text": "Entendido, tendré en cuenta ese libro."}]})
    for turno in historial:
        rol = "model" if turno.get("rol") == "asistente" else "user"
        contenidos.append({"role": rol, "parts": [{"text": turno.get("texto", "")}]})
    contenidos.append({"role": "user", "parts": [{"text": mensaje_usuario}]})

    cuerpo = {
        "system_instruction": {"parts": [{"text": _INSTRUCCION_SISTEMA}]},
        "contents": contenidos,
    }
    if busqueda_web:
        cuerpo["tools"] = [{"google_search": {}}]

    url = f"{_URL_BASE}/models/{modelo_elegido}:generateContent"
    resp = requests.post(url, params={"key": api_key}, json=cuerpo, timeout=_TIMEOUT)
    resp.raise_for_status()
    datos = resp.json()

    candidatos = datos.get("candidates", [])
    if not candidatos:
        motivo = datos.get("promptFeedback", {}).get("blockReason", "desconocido")
        raise ValueError(f"Gemini no devolvió respuesta (motivo: {motivo}).")

    partes = candidatos[0].get("content", {}).get("parts", [])
    texto = "".join(p.get("text", "") for p in partes).strip()
    if not texto:
        raise ValueError("Gemini devolvió una respuesta vacía.")
    return texto
# ANCLAJE_FIN: CLIENTE_GEMINI_ENVIO_MENSAJE
