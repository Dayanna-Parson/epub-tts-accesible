import re


def limpiar_para_lectura(texto):
    """
    Limpia el texto extraído de un EPUB para lectura accesible con NVDA.

    Transformaciones aplicadas:
    1. Une palabras cortadas con guion al final de línea (e.g., "cami-\\nando" → "caminando")
    2. Elimina espacios o tabuladores múltiples internos
    3. Reune signos de puntuación separados de la palabra anterior
       (e.g., "frase ." → "frase.", "palabra ," → "palabra,")
    4. Reduce TODAS las secuencias de saltos de línea a uno solo (sin líneas en blanco)
       → NVDA no anunciará "blank" al navegar entre párrafos

    El resultado es un texto de flujo continuo con párrafos separados por un único
    salto de línea, lo que permite que NVDA lo lea sin interrupciones vacías.
    """
    if not texto:
        return texto

    # 1. Unir palabras cortadas con guion al final de línea
    texto = re.sub(r'-\n(\w)', r'\1', texto)

    # 2. Eliminar espacios o tabuladores múltiples internos
    texto = re.sub(r'[ \t]{2,}', ' ', texto)

    # 3. Re-unir signos de puntuación separados de la palabra anterior.
    #    Captura: palabra seguida de espacio(s) seguida de signo de puntuación.
    #    Resultado: la puntuación se adhiere a la palabra sin espacio intermedio.
    texto = re.sub(r'(\w) +([.,;:])', r'\1\2', texto)

    # 4. Reducir cualquier secuencia de saltos de línea a uno solo.
    #    Esto elimina las líneas en blanco que NVDA anuncia como "blank"
    #    al navegar párrafo a párrafo con las flechas de cursor.
    texto = re.sub(r'\n+', '\n', texto)

    return texto.strip()
