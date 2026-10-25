# ANCLAJE_INICIO: CATALOGO_VOCES_LOCALES
"""
Catálogo compartido de voces locales SAPI5 (64 y 32 bits), calculado una
sola vez por sesión y reutilizado por todas las pestañas.

Enumerar las voces de 32 bits obliga a lanzar auxiliar_sapi32.exe (un
ejecutable --onefile que se descomprime entero antes de responder), pedirle
la lista y cerrarlo; las de 64 bits recorren tres categorías del registro
con objetos COM. Lectura, Creador de Audiolibros, Grabación, Ajustes → Voces
SAPI5 y el diálogo de proveedor alternativo hacían cada uno su propia
enumeración, en el hilo principal, al arrancar y otra vez cada vez que se
marcaba o desmarcaba una voz favorita — de ahí los parones al entrar en las
listas de voces. Las voces instaladas no cambian durante una sesión normal;
si se instala una nueva, basta con reiniciar la app o llamar a
invalidar_catalogo().

Solo debe llamarse desde el hilo principal: los objetos COM de SAPI5 se
crean en el apartment del hilo que llama.
"""
import logging

logger = logging.getLogger(__name__)

_voces_64 = None
_voces_32 = None


def _copiar(lista):
    # Copia superficial de cada voz: quien la recibe suele añadirle claves
    # propias (es_nueva, proveedor_id...) y no debe ensuciar el catálogo.
    return [dict(voz) for voz in lista]


def obtener_voces_sapi5_64():
    """Voces SAPI5 de 64 bits del sistema (estándar, OneCore y modernas)."""
    global _voces_64
    if _voces_64 is None:
        try:
            from app.servicios.cliente_sapi5 import ClienteSapi5
            _voces_64 = ClienteSapi5().obtener_voces()
        except Exception:
            logger.exception("[CatalogoVocesLocales] Error al enumerar voces SAPI5 de 64 bits")
            return []
    return _copiar(_voces_64)


def obtener_voces_sapi5_32():
    """
    Voces SAPI5 de 32 bits a través del proceso puente. Lista vacía si
    auxiliar_sapi32.exe no está disponible (y entonces no se reintenta en
    toda la sesión).
    """
    global _voces_32
    if _voces_32 is None:
        try:
            from app.servicios.cliente_sapi32_bridge import ClienteSapi32Bridge
            puente = ClienteSapi32Bridge()
            try:
                _voces_32 = puente.obtener_voces() if puente.conectado else []
            finally:
                puente.cerrar()
        except Exception:
            logger.exception("[CatalogoVocesLocales] Error al enumerar voces SAPI5 de 32 bits")
            return []
    return _copiar(_voces_32)


def invalidar_catalogo():
    """Fuerza a volver a enumerar las voces locales en la próxima consulta."""
    global _voces_64, _voces_32
    _voces_64 = None
    _voces_32 = None
# ANCLAJE_FIN: CATALOGO_VOCES_LOCALES
