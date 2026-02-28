import re


def limpiar_texto(texto):
    """
    Limpia el texto extraído de un EPUB eliminando artefactos de formato:
    - Une palabras cortadas con guion al final de línea (e.g., "cami-\nnando" → "caminando")
    - Elimina líneas en blanco excesivas (más de una consecutiva)
    - Normaliza espacios internos múltiples
    """
    if not texto:
        return texto

    # 1. Unir palabras cortadas con guion al final de línea
    texto = re.sub(r'-\n(\w)', r'\1', texto)

    # 2. Eliminar espacios o tabuladores múltiples internos
    texto = re.sub(r'[ \t]{2,}', ' ', texto)

    # 3. Reducir más de dos saltos de línea consecutivos a exactamente dos
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto.strip()
