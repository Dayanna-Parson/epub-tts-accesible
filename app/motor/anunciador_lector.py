# ANCLAJE_INICIO: ANUNCIADOR_LECTOR_PANTALLA
"""
Anuncios de accesibilidad enviados directamente al lector de pantalla activo
(NVDA, JAWS, SAPI...) mediante accessible_output3, sin mover el foco ni
simular controles ocultos.

Sustituye al patrón _anunciador (toque de foco a un TextCtrl oculto) en el
diálogo del Asistente de Biblioteca: ese patrón hace que NVDA anuncie el rol
del control ("edición, solo lectura") y a veces se percibe como si saltara
una ventana flotante — molesto en una conversación donde llegan mensajes
seguidos. accessible_output3 habla el texto tal cual, sin ese ruido.

Import perezoso y a prueba de fallos: si la librería no está instalada, si
no hay ningún lector de pantalla activo, o si algo falla al hablar, no debe
romper la app — como mucho, ese anuncio en concreto no se escucha.
"""
import logging

logger = logging.getLogger(__name__)

_salida = None
_intentado = False


def _obtener_salida():
    global _salida, _intentado
    if _intentado:
        return _salida
    _intentado = True
    try:
        import accessible_output3.outputs.auto
        _salida = accessible_output3.outputs.auto.Auto()
    except Exception:
        logger.exception("No se pudo inicializar accessible_output3")
        _salida = None
    return _salida


def hablar(texto: str, interrumpir: bool = False):
    """
    Envía `texto` al lector de pantalla activo. Sin efecto (ni error) si no
    hay ninguno en ejecución o si la librería no está disponible.
    """
    if not texto:
        return
    salida = _obtener_salida()
    if salida is None:
        return
    try:
        salida.speak(texto, interrupt=interrumpir)
    except Exception:
        logger.exception("Error al hablar con el lector de pantalla")
# ANCLAJE_FIN: ANUNCIADOR_LECTOR_PANTALLA
