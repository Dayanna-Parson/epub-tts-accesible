"""
procesador_etiquetas.py
-----------------------
Motor de análisis y fragmentación de texto etiquetado para producción multivoz.

Formato de etiqueta: {{@nombre}}  (case-insensitive)
Texto sin etiqueta inicial → se asigna a la variante de narrador que ya esté
presente en el texto (nar, narrador, narradora, narrator…).
Si el texto no contiene ninguna variante de narrador se usa 'narrador'.
"""

import os
import re

# Patrón de detección de etiquetas {{@nombre}} — insensible a mayúsculas
_PATRON_ETIQUETA = re.compile(r'\{\{@(\w+)\}\}', re.IGNORECASE)

# Variantes reconocidas como "narrador" (minúsculas)
_VARIANTES_NARRADOR = {'nar', 'narrador', 'narradora', 'narrator', 'narr', 'narracion'}


def _limpiar_contenido_fragmento(texto: str) -> str:
    """
    Limpia el texto de un fragmento antes de enviarlo a las voces TTS.

    Elimina:
    - Tabuladores (\\t) — se convierten en espacio para no crear silencios.
    - Doble guion bajo __ al inicio de cualquier línea (marcador tipográfico de
      diálogos / énfasis en Markdown). La voz TTS los leería como «guión guión».
    - Espacios múltiples residuales.

    No afecta al formato de las etiquetas (se llama DESPUÉS de extraer el contenido).
    """
    # Tabuladores → espacio
    texto = texto.replace('\t', ' ')
    # __ (dos o más guiones bajos) al inicio de una línea → eliminar
    texto = re.sub(r'^_{2,}', '', texto, flags=re.MULTILINE)
    # Espacios múltiples residuales → uno solo
    texto = re.sub(r'  +', ' ', texto)
    return texto.strip()


def _detectar_variante_narrador(texto: str) -> str:
    """
    Devuelve la primera variante de narrador encontrada en el texto,
    o 'narrador' si no hay ninguna.
    Así el texto pre-primera-etiqueta queda agrupado con la misma etiqueta
    que el autor ya usa (p.ej. @nar) en lugar de crear una etiqueta extra.
    """
    for m in _PATRON_ETIQUETA.finditer(texto):
        nombre = normalizar_etiqueta(m.group(1))
        if nombre in _VARIANTES_NARRADOR:
            return nombre
    return 'narrador'

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

    # partes[0] → texto anterior a la primera etiqueta.
    # Reutilizamos la variante de narrador que el autor ya usa en el texto
    # para no generar una etiqueta duplicada (ej. 'narrador' + 'nar').
    pre = _limpiar_contenido_fragmento(partes[0])
    if pre:
        etiq_nar = _detectar_variante_narrador(texto)
        fragmentos.append((etiq_nar, pre))

    # Procesar pares (nombre_etiqueta, contenido)
    i = 1
    while i < len(partes) - 1:
        etiqueta = normalizar_etiqueta(partes[i])
        contenido = _limpiar_contenido_fragmento(partes[i + 1])
        if contenido:
            fragmentos.append((etiqueta, contenido))
        i += 2

    return fragmentos


# ANCLAJE_INICIO: LOTE_CARPETA_TXT
# Constante técnica (se compara, no se muestra): la interfaz la traduce.
MOTIVO_VACIO = "vacio"


def _clave_orden_natural(nombre: str) -> list:
    """
    Clave de ordenación "natural": los números del nombre se comparan como
    números ("2. ..." antes que "10. ..."), y el resto, sin distinguir
    mayúsculas, que es como los ordena el Explorador de Windows.
    """
    return [
        (0, int(trozo), "") if trozo.isdigit() else (1, 0, trozo.lower())
        for trozo in re.split(r'(\d+)', nombre)
        if trozo
    ]


def leer_txt_tolerante(ruta: str) -> str:
    """
    Lee un TXT probando UTF-8 (con o sin BOM, el del Bloc de notas) y, si
    no lo es, la codificación ANSI de Windows en español (cp1252). Sin
    quitar el BOM, la voz leería un carácter invisible al principio.
    """
    with open(ruta, 'rb') as f:
        crudo = f.read()
    try:
        return crudo.decode('utf-8-sig')
    except UnicodeDecodeError:
        return crudo.decode('cp1252', errors='replace')


def preparar_lote_carpeta(carpeta: str) -> tuple:
    """
    Prepara la grabación de una carpeta entera de TXT: un audio por archivo.

    Cada TXT se fragmenta igual que un archivo suelto, así que los que no
    llevan ninguna etiqueta quedan enteros con la etiqueta de narrador y
    comparten la misma voz sin tener que escribir {{@narrador}} en cada uno.
    Solo se leen los .txt de la propia carpeta (no las subcarpetas), en
    orden natural de nombre.

    Returns:
        (lote, omitidos)
        lote:     [(nombre_base_sin_extension, fragmentos), ...]
        omitidos: [(nombre_archivo, motivo), ...] — motivo es MOTIVO_VACIO o
                  el texto del error de lectura
    """
    nombres = sorted(
        (n for n in os.listdir(carpeta)
         if n.lower().endswith('.txt') and os.path.isfile(os.path.join(carpeta, n))),
        key=_clave_orden_natural,
    )
    lote, omitidos = [], []
    for nombre in nombres:
        try:
            texto = leer_txt_tolerante(os.path.join(carpeta, nombre))
        except OSError as e:
            omitidos.append((nombre, str(e)))
            continue
        fragmentos = fragmentar_texto(texto)
        if not fragmentos:
            omitidos.append((nombre, MOTIVO_VACIO))
            continue
        lote.append((os.path.splitext(nombre)[0], fragmentos))
    return lote, omitidos


def etiquetas_de_lote(lote: list) -> list:
    """Etiquetas únicas de todo el lote, en orden de primera aparición."""
    vistas, etiquetas = set(), []
    for _nombre_sin_usar, fragmentos in lote:
        for etiqueta, _texto_sin_usar in fragmentos:
            if etiqueta not in vistas:
                vistas.add(etiqueta)
                etiquetas.append(etiqueta)
    return etiquetas
# ANCLAJE_FIN: LOTE_CARPETA_TXT
