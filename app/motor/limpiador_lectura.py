import re


def limpiar_para_lectura(texto):
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

    # 7. Limpiar residuos: espacios múltiples y espacios adyacentes a saltos de línea
    texto = re.sub(r'  +', ' ', texto)
    texto = re.sub(r' *\n *', '\n', texto)

    return texto.strip()
