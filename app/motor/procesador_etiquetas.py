"""
procesador_etiquetas.py
-----------------------
Motor de análisis y fragmentación de texto etiquetado para producción multivoz.

Formato de etiqueta: {{@nombre}}  (case-insensitive)
Texto sin etiqueta inicial → asignado automáticamente a @narrador.
"""

import re

# Patrón de detección de etiquetas {{@nombre}} — insensible a mayúsculas
_PATRON_ETIQUETA = re.compile(r'\{\{@(\w+)\}\}', re.IGNORECASE)

# Caracteres prohibidos en nombres de archivo en Windows
_CHARS_PROHIBIDOS = '\\/:*?"<>|'


def normalizar_etiqueta(nombre: str) -> str:
    """Convierte el nombre de etiqueta a minúsculas sin espacios extremos."""
    return nombre.strip().lower()


def limpiar_nombre_archivo(nombre: str) -> str:
    """
    Elimina caracteres prohibidos en Windows de un nombre de archivo o carpeta.
    Reemplaza cada carácter inválido por '_' y limpia guiones bajos sobrantes.
    """
    resultado = nombre
    for char in _CHARS_PROHIBIDOS:
        resultado = resultado.replace(char, '_')
    return resultado.strip('_ ').strip()


def escanear_etiquetas(texto: str) -> list:
    """
    Detecta todas las etiquetas únicas presentes en el texto, en orden de aparición.

    Returns:
        Lista de nombres de etiqueta normalizados (minúsculas), sin duplicados.
        Ejemplo: ['narrador', 'rey', 'soldado']
    """
    etiquetas = []
    vistas = set()
    for m in _PATRON_ETIQUETA.finditer(texto):
        nombre = normalizar_etiqueta(m.group(1))
        if nombre not in vistas:
            etiquetas.append(nombre)
            vistas.add(nombre)
    return etiquetas


def fragmentar_texto(texto: str) -> list:
    """
    Divide el texto en fragmentos atómicos (etiqueta, contenido).

    Reglas:
    - Cada fragmento corresponde exactamente a una etiqueta.
    - El texto anterior a la primera etiqueta se asigna a 'narrador'.
    - Cada contenido se limpia con .strip() para eliminar silencios innecesarios.
    - No se divide por caracteres ni palabras: la unidad mínima es la etiqueta.

    Returns:
        Lista de tuplas [(etiqueta_normalizada, contenido_limpio), ...]
        Solo incluye fragmentos con contenido no vacío.
    """
    fragmentos = []

    # re.split con grupo capturador intercala: [pre, etiq1, texto1, etiq2, texto2, ...]
    partes = re.split(r'\{\{@(\w+)\}\}', texto, flags=re.IGNORECASE)

    # partes[0] → texto anterior a la primera etiqueta
    if partes[0].strip():
        fragmentos.append(('narrador', partes[0].strip()))

    # Procesar pares (nombre_etiqueta, contenido)
    i = 1
    while i < len(partes) - 1:
        etiqueta = normalizar_etiqueta(partes[i])
        contenido = partes[i + 1].strip()
        if contenido:
            fragmentos.append((etiqueta, contenido))
        i += 2

    return fragmentos
