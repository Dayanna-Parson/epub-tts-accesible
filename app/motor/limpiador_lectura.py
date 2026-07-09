import logging
import re

logger = logging.getLogger(__name__)

# Singleton del diccionario de pronunciación — se crea la primera vez que se necesita
_dic_pronunciacion = None


def _obtener_diccionario():
    global _dic_pronunciacion
    if _dic_pronunciacion is None:
        from app.motor.diccionario_pronunciacion import DiccionarioPronunciacion
        _dic_pronunciacion = DiccionarioPronunciacion()
    return _dic_pronunciacion


def recargar_diccionario_pronunciacion():
    """Invalida la caché del diccionario para que el siguiente texto use el JSON actualizado."""
    global _dic_pronunciacion
    _dic_pronunciacion = None


def _aplicar_reglas_de_biblioteca(texto: str, ruta_libro: str) -> str:
    """
    Reglas de pronunciación con alcance "libro" o "saga" (biblioteca.db),
    por encima de las globales de pronunciacion.json. Si el libro no está
    indexado en la Biblioteca (se abrió directamente desde Lectura, sin
    pasar por Importar carpeta), no hay nada que aplicar y se ignora en
    silencio — no es un error, es un libro fuera de la Biblioteca.
    """
    try:
        from app.motor.gestor_biblioteca import GestorBiblioteca
        gestor = GestorBiblioteca()
        libro = gestor.obtener_libro_por_ruta(ruta_libro)
        if libro is None:
            return texto
        for regla in gestor.listar_reglas_diccionario_para_libro(libro["id"]):
            if not regla["patron_origen"]:
                continue
            patron = r"(?<!\w)" + re.escape(regla["patron_origen"]) + r"(?!\w)"
            texto = re.sub(patron, regla["sustitucion"], texto)
    except Exception:
        logger.exception("[LimpiadorLectura] Error al aplicar reglas de diccionario de la Biblioteca")
    return texto


def limpiar_para_lectura(texto, ruta_libro=None):
    """
    Limpia el texto extraído de un EPUB para lectura accesible con NVDA.

    Transformaciones aplicadas:
    1. Une palabras cortadas con guion al final de línea ("cami-\\nando" → "caminando")
    2. Elimina espacios o tabuladores múltiples internos
    3. Re-une signos de puntuación separados de la palabra anterior
       ("frase ." → "frase.", "palabra ," → "palabra,")
    4. Protege los saltos de párrafo reales (2+ newlines) con un marcador temporal
    5. Une TODAS las líneas dentro de un mismo párrafo en una sola:
       cualquier \\n aislado (no precedido por .!?:;») se reemplaza por espacio.
       Esto evita que palabras como "demokracia" queden solas en una línea.
    6. Restaura los saltos de párrafo reales como \\n simple
    7. Limpia espacios múltiples y espacios pegados a los saltos de línea

    El resultado: párrafos de texto continuo separados por un único \\n.
    NVDA no anunciará "blank" al navegar entre párrafos con las flechas de cursor.
    """
    if not texto:
        return texto

    # 0. Normalizar espacios de no separación (no-break space \xa0 / &nbsp;)
    #    a espacio regular para que los pasos siguientes los traten correctamente
    texto = texto.replace('\xa0', ' ')

    # 1. Unir palabras cortadas con guion al final de línea
    texto = re.sub(r'-\n(\w)', r'\1', texto)

    # 2. Eliminar espacios o tabuladores múltiples internos
    texto = re.sub(r'[ \t]{2,}', ' ', texto)

    # 3. Re-unir signos de puntuación separados de la palabra anterior
    texto = re.sub(r'(\w) +([.,;:])', r'\1\2', texto)

    # 4. Proteger saltos de párrafo reales (2 o más newlines consecutivos)
    #    con un marcador temporal que no aparece en ningún texto normal
    texto = re.sub(r'\n{2,}', '\x01', texto)

    # 5. Unir líneas internas del mismo párrafo (wrapping arbitrario del extractor EPUB).
    #    a) Primero: saltos NO precedidos por puntuación de fin de oración → espacio
    texto = re.sub(r'(?<![.!?:»;])\n', ' ', texto)
    #    b) Después: cualquier \n que quedó (precedido por .!? pero sin doble-\n)
    #       también se une con espacio para garantizar texto totalmente lineal por párrafo
    texto = texto.replace('\n', ' ')

    # 6. Restaurar los marcadores de párrafo como salto de línea simple
    texto = texto.replace('\x01', '\n')

    # 7. Limpiar residuos: espacios múltiples, espacios junto a saltos y saltos múltiples
    texto = re.sub(r'  +', ' ', texto)
    texto = re.sub(r' *\n *', '\n', texto)
    # Un '\n \n' producido cuando dos bloques consecutivos tenían solo whitespace
    # entre ellos resulta en '\n\n' tras el paso anterior (línea en blanco visible).
    # Colapsamos cualquier secuencia de saltos en uno solo.
    texto = re.sub(r'\n+', '\n', texto)

    texto = texto.strip()

    # Aplicar sustituciones de pronunciación definidas por el usuario:
    # primero las globales, luego las de libro/saga si aplica (más
    # específicas, así que van después y pueden refinar lo ya sustituido).
    texto = _obtener_diccionario().aplicar(texto)
    if ruta_libro:
        texto = _aplicar_reglas_de_biblioteca(texto, ruta_libro)

    return texto
