# ANCLAJE_INICIO: CLIENTE_GEMINI
import logging
import re

import requests

from app.config_rutas import cargar_claves

logger = logging.getLogger(__name__)

_URL_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = 30

# Instrucción de sistema: pide a Gemini que se apoye en la búsqueda web para no
# alucinar datos sobre libros (tramas, autores, ediciones, disponibilidad).
# Es explícita al prohibir inventar títulos/autores/sagas cuando no encuentra
# datos reales, porque sin esta advertencia el modelo tiende a "completar"
# con una sinopsis o un autor plausibles en vez de admitir que no los conoce.
INSTRUCCION_SISTEMA_DEFECTO = (
    "Eres el Asistente de Biblioteca de una aplicación de audiolibros para "
    "personas ciegas. Ayudas con recomendaciones, dudas sobre autores, tramas "
    "y ediciones de libros. Antes de citar cualquier dato concreto (argumento, "
    "autor, año, edición, disponibilidad, número de libro en una saga), "
    "verifícalo con la búsqueda web en fuentes fiables como Goodreads, "
    "Amazon o la web del propio autor o editorial — nunca lo inventes ni lo "
    "completes de memoria. Presta especial cuidado a los NOMBRES PROPIOS: "
    "escribe el título del libro/saga y el nombre del autor exactamente como "
    "aparecen en la fuente que consultes, sin adaptarlos ni 'corregirlos'. "
    "Si tras buscar no encuentras un libro, autor o saga con ese nombre "
    "exacto, dilo explícitamente ('No he encontrado ese título/autor exacto, "
    "¿podrías confirmarme el nombre?') en vez de responder con una sinopsis "
    "o una biografía inventadas para algo parecido. Responde en español, de "
    "forma clara y breve, pensando en que la respuesta puede leerse con un "
    "lector de pantalla."
)
# ANCLAJE_FIN: CLIENTE_GEMINI


# ANCLAJE_INICIO: CLIENTE_GEMINI_LISTA_MODELOS
def _clave_api():
    return cargar_claves().get("gemini", {}).get("api_key", "").strip()


# Aunque soporten generateContent, estas variantes son especializadas
# (texto a voz, generación de imagen/vídeo, embeddings...) y no sirven
# para una conversación de varios turnos: Gemini responde 400
# "Multiturn chat is not enabled for models/..." si se les habla como a
# un modelo de chat normal. Se descartan por nombre para no ofrecerlas
# nunca como candidatas, ni en el modo automático ni en el combo manual
# de Ajustes.
_FRAGMENTOS_NO_CHAT = ("tts", "image", "imagen", "embedding", "aqa", "veo", "learnlm")


def _es_modelo_chat_de_texto(nombre: str) -> bool:
    nombre_min = nombre.lower()
    return not any(fragmento in nombre_min for fragmento in _FRAGMENTOS_NO_CHAT)


def listar_modelos() -> list:
    """
    Consulta GET /v1beta/models y devuelve los nombres de modelo (sin el
    prefijo "models/") que soportan generateContent y sirven para chat de
    texto de varios turnos (ver _FRAGMENTOS_NO_CHAT). Se llama en cada
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
            if "generateContent" not in metodos:
                continue
            nombre = modelo.get("name", "")
            nombre = nombre.split("/", 1)[-1] if "/" in nombre else nombre
            if _es_modelo_chat_de_texto(nombre):
                modelos.append(nombre)
        token_pagina = datos.get("nextPageToken")
        if not token_pagina:
            break
        parametros = {"key": api_key, "pageSize": 100, "pageToken": token_pagina}
    return modelos


def _version_de_modelo(nombre: str) -> float:
    """
    Extrae el primer número de versión del nombre ("gemini-2.5-flash" → 2.5,
    "gemini-3-pro" → 3.0). Sin número reconocible, se manda al final.
    """
    coincidencia = re.search(r"(\d+(?:\.\d+)?)", nombre)
    return float(coincidencia.group(1)) if coincidencia else -1.0


def _candidatos_automaticos(modelos, analisis_profundo=False) -> list:
    """
    Modo "Automático": Flash para preguntas rápidas, Pro para análisis
    profundos, y siempre la versión más reciente sin nombres escritos a
    fuego en el código — se calcula en cada llamada a partir de lo que
    devuelva /v1beta/models en ese momento, así que si Google publica
    mañana una versión nueva, se usa sin tocar nada aquí. Google también
    va retirando versiones concretas (p. ej. "gemini-2.5-flash") aunque
    sigan apareciendo un tiempo en /models, así que en vez de un único
    nombre se devuelve una lista de candidatos en orden de preferencia:
      1. El alias estable "gemini-flash-latest"/"gemini-pro-latest", si la
         cuenta lo tiene (Google lo mantiene apuntando siempre al modelo
         vigente).
      2. El resto de modelos cuyo nombre contiene "flash"/"pro", del
         número de versión más alto al más bajo.
      3. Si el objetivo era Flash, los modelos "pro" (y viceversa) —
         por si la cuota del día se agotó para toda la familia Flash,
         algo que sí puede pasar en la capa gratuita.
      4. Cualquier otro modelo con generateContent, como último recurso.
    enviar_mensaje() los prueba en este orden y sigue al siguiente si uno
    devuelve 404 (retirado) o 429 (cuota agotada para ese modelo en
    concreto — en la capa gratuita cada modelo tiene su propia cuota).
    """
    if not modelos:
        raise ValueError("La cuenta de Gemini no tiene modelos disponibles.")
    objetivo = "pro" if analisis_profundo else "flash"
    otro_objetivo = "flash" if analisis_profundo else "pro"
    alias = f"gemini-{objetivo}-latest"

    def _coincidencias(fragmento):
        return sorted(
            (m for m in modelos if fragmento in m.lower() and m not in candidatos),
            key=_version_de_modelo, reverse=True,
        )

    candidatos = [alias] if alias in modelos else []
    candidatos += _coincidencias(objetivo)
    candidatos += _coincidencias(otro_objetivo)
    candidatos += sorted(
        (m for m in modelos if m not in candidatos),
        key=_version_de_modelo, reverse=True,
    )
    return candidatos
# ANCLAJE_FIN: CLIENTE_GEMINI_LISTA_MODELOS


# ANCLAJE_INICIO: CLIENTE_GEMINI_ENVIO_MENSAJE
_ENCABEZADOS_CONTEXTO = {
    "libro": "Libro seleccionado en la Biblioteca:",
    "saga": "Saga seleccionada en la Biblioteca:",
    "categoria": "Género/categoría seleccionado en la Biblioteca:",
    "resumen": "Resumen de la Biblioteca del usuario (tenlo en cuenta para tus recomendaciones):",
}


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
    encabezado = _ENCABEZADOS_CONTEXTO.get(contexto_libro.get("tipo", "libro"), _ENCABEZADOS_CONTEXTO["libro"])
    return encabezado + "\n" + "\n".join(partes)


def enviar_mensaje(historial, mensaje_usuario, contexto_libro=None,
                    modelo=None, analisis_profundo=False, busqueda_web=True,
                    instruccion_sistema=None) -> str:
    """
    Envía un mensaje a Gemini con el historial previo y, si lo hay, el
    contexto del libro seleccionado (solo metadatos, nunca el texto del
    libro). Devuelve el texto de la respuesta.

    historial: lista de dicts {"rol": "usuario"|"asistente", "texto": str},
    ya cargada desde chat_biblioteca.json por gestor_chat_biblioteca.

    instruccion_sistema: texto de la plantilla activa (ver
    gestor_prompts_asistente.py); si es None, se usa
    INSTRUCCION_SISTEMA_DEFECTO.

    Se llama siempre desde un hilo secundario (ver DIALOGO_ASISTENTE_BIBLIOTECA).
    """
    api_key = _clave_api()
    if not api_key:
        raise ValueError("No hay ninguna clave de Gemini configurada.")

    datos_gemini = cargar_claves().get("gemini", {})
    modelo_elegido = modelo or datos_gemini.get("modelo", "auto")
    modo_automatico = not modelo_elegido or modelo_elegido == "auto"
    candidatos_modelo = (
        _candidatos_automaticos(listar_modelos(), analisis_profundo)
        if modo_automatico else [modelo_elegido]
    )

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
        "system_instruction": {"parts": [{"text": instruccion_sistema or INSTRUCCION_SISTEMA_DEFECTO}]},
        "contents": contenidos,
        # Temperatura baja: menos "creatividad" al citar títulos, autores o
        # tramas reales — sigue dejando margen para recomendar y charlar,
        # pero reduce que el modelo rellene huecos con datos inventados.
        "generationConfig": {"temperature": 0.4},
    }
    if busqueda_web:
        cuerpo["tools"] = [{"google_search": {}}]

    # 404 (modelo retirado) y 429 (cuota agotada) pasan al siguiente
    # candidato en modo automático: en la capa gratuita cada modelo tiene
    # su propia cuota, así que un 429 en uno no implica que otro también
    # esté agotado. Cualquier otro código (401 clave inválida, 400
    # petición mal formada...) no tiene sentido reintentarlo con otro
    # modelo y se propaga tal cual.
    _CODIGOS_REINTENTABLES = (404, 429)

    datos = None
    ultimo_error = None
    for indice, nombre_modelo in enumerate(candidatos_modelo):
        url = f"{_URL_BASE}/models/{nombre_modelo}:generateContent"
        resp = requests.post(url, params={"key": api_key}, json=cuerpo, timeout=_TIMEOUT)
        es_ultimo = indice == len(candidatos_modelo) - 1
        if resp.status_code in _CODIGOS_REINTENTABLES and modo_automatico and not es_ultimo:
            logger.warning(
                "Modelo Gemini '%s' devolvió %s, probando el siguiente candidato",
                nombre_modelo, resp.status_code,
            )
            continue
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logger.error("Error de Gemini con el modelo '%s': %s", nombre_modelo, resp.text)
            ultimo_error = e
            break
        datos = resp.json()
        break

    if datos is None:
        if ultimo_error is not None:
            if ultimo_error.response is not None and ultimo_error.response.status_code == 429:
                raise ValueError(
                    "Se agotó la cuota gratuita de Gemini para todos los modelos disponibles. "
                    "Consulta tu plan y facturación en https://ai.google.dev/gemini-api/docs/rate-limits, "
                    "o espera a que se renueve la cuota."
                )
            raise ultimo_error
        raise ValueError(
            "Ninguno de los modelos disponibles de Gemini respondió. "
            "Prueba a comprobar la clave de nuevo en Ajustes para actualizar la lista."
        )

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
