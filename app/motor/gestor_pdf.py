# ANCLAJE_INICIO: GESTOR_PDF
"""
gestor_pdf.py
──────────────
Extracción de texto y estructura de un PDF para la pestaña Lectura, con
la misma forma de retorno que extraer_datos_epub() de gestor_epub.py,
para que pestana_lectura.py pueda cargar EPUB y PDF por el mismo camino
sin duplicar el árbol de índice, la negrita de encabezados ni el
guardado de posición de lectura.

Capítulos / negrita de encabezados: se usa el índice de contenidos
embebido del PDF (documento.get_toc(), vía PyMuPDF/fitz) cuando existe.
Si el PDF no tiene índice (habitual en PDF escaneados o mal generados),
se genera un índice sintético de una entrada por página ("Página N"),
para que la navegación por capítulo siga disponible aunque sea a nivel
de página — mismo criterio que Bookworm en este mismo caso.

No hay texto con negrita/cursiva/subrayado embebido de forma fiable en
PDF como en el HTML de un EPUB, así que spans_estilo se devuelve vacío.
"""

import logging
import os

import fitz

from app.motor import gestor_ocr
from app.motor.limpiador_lectura import limpiar_para_lectura

logger = logging.getLogger(__name__)


def extraer_datos_pdf(ruta_pdf, callback_progreso_ocr=None):
    """
    Extrae el texto completo y la estructura de índice de un PDF.

    callback_progreso_ocr(pagina_actual, total_paginas_ocr): si se indica,
    se llama antes de reconocer cada página con OCR — pensado para que
    pestana_lectura.py anuncie el progreso con AnunciadorVoz. No se llama
    en absoluto si el OCR está desactivado o no hace falta.

    Retorna la misma forma que extraer_datos_epub():
        - texto_completo (str)
        - datos_indice (list)     [{'title', 'offset', 'children'}, ...]
        - posiciones_capitulos (dict)   {titulo: posicion_caracter}
        - posiciones_encabezados (list) [{'nivel', 'texto', 'pos'}, ...]
        - spans_estilo (list)     siempre vacío para PDF
        - posiciones_imagenes (list) [{'texto': '', 'pos'}, ...] — un PDF no
          trae texto alternativo, así que el marcador es genérico "[Imagen]".
        - posiciones_enlaces (list)  [{'texto', 'pos'}, ...] — texto visible
          dentro del rectángulo del enlace.
        - posiciones_tablas (list)   [{'texto', 'pos'}, ...] — texto de la
          primera celda no vacía. Vacío si la versión de PyMuPDF instalada
          no trae find_tables().
    """
    if not os.path.exists(ruta_pdf):
        raise FileNotFoundError(f"No se encontró el archivo: {ruta_pdf}")

    try:
        documento = fitz.open(ruta_pdf)
    except Exception as e:
        raise Exception(f"Error al leer el formato PDF: {e}")

    # Cada página se limpia individualmente (en vez de concatenar todo en
    # crudo y limpiar una sola vez al final) para poder registrar el offset
    # de inicio de cada página ya sobre el texto definitivo. Antes las
    # posiciones se calculaban sobre el texto sin limpiar y no se
    # reubicaban después (a diferencia de gestor_epub.py, donde sí se
    # reubican buscando el propio texto del encabezado) porque el título de
    # un marcador de PDF no siempre aparece literal en el cuerpo de la
    # página — limpiando página a página se evita el problema de raíz: la
    # posición registrada ya es la definitiva, sin necesidad de reubicar nada.
    texto_completo = ""
    posiciones_inicio_pagina = []  # índice = página 0-based, valor = offset en texto_completo (ya limpio)
    posiciones_imagenes = []
    posiciones_enlaces = []
    posiciones_tablas = []

    # OCR de páginas sin texto propio (escaneadas). El recuento de páginas
    # candidatas se hace en una pasada previa barata (solo get_text, sin
    # reconocer nada todavía) para poder anunciar "página X de Y" con
    # sentido, y respetar el tope configurado sin reconocer de más.
    config_ocr = gestor_ocr.obtener_config_ocr()
    motor_ocr = config_ocr["ocr_motor"]
    ocr_activo = (
        config_ocr["ocr_activado"]
        and motor_ocr != gestor_ocr.MOTOR_NINGUNO
        and gestor_ocr.motor_disponible(motor_ocr)
    )
    tope_ocr = config_ocr["ocr_tope_paginas"]
    total_paginas_ocr = 0
    if ocr_activo:
        for num in range(documento.page_count):
            if not (documento[num].get_text("text") or "").strip():
                total_paginas_ocr += 1
                if total_paginas_ocr >= tope_ocr:
                    break
    contador_ocr = 0

    for num in range(documento.page_count):
        pagina = documento[num]
        texto_pagina = pagina.get_text("text")
        pagina_reconocida_por_ocr = False

        if ocr_activo and not texto_pagina.strip() and contador_ocr < tope_ocr:
            contador_ocr += 1
            pagina_reconocida_por_ocr = True
            if callback_progreso_ocr is not None:
                try:
                    callback_progreso_ocr(contador_ocr, total_paginas_ocr)
                except Exception:
                    logger.exception("Fallo en callback_progreso_ocr")
            try:
                datos_png = pagina.get_pixmap(dpi=200).tobytes("png")
                texto_pagina = gestor_ocr.reconocer_pagina(
                    datos_png, motor_ocr, config_ocr["ocr_idioma"]
                )
            except Exception:
                logger.exception(
                    "Fallo al renderizar/reconocer con OCR la página %s de %s", num + 1, ruta_pdf
                )
                texto_pagina = ""

        # Un PDF no trae alt: se usa un marcador genérico, uno por imagen
        # incrustada en la página, insertado al final del texto de la
        # página (no se conoce su posición real dentro del flujo de texto).
        # Si la página se acaba de reconocer por OCR, la imagen incrustada
        # ES el propio escaneado de la página — marcarla aparte solo
        # repetiría como "[Imagen]" un texto que ya se acaba de leer entero.
        num_imagenes_pagina = 0 if pagina_reconocida_por_ocr else len(pagina.get_images(full=True))
        if num_imagenes_pagina:
            texto_pagina += "\n" + "\n".join(["[Imagen]"] * num_imagenes_pagina)

        texto_limpio_pagina = (
            limpiar_para_lectura(texto_pagina, ruta_libro=ruta_pdf).strip()
            if texto_pagina and texto_pagina.strip() else ""
        )
        if texto_limpio_pagina:
            if texto_completo:
                texto_completo += "\n\n"
            offset_pagina = len(texto_completo)
            posiciones_inicio_pagina.append(offset_pagina)
            texto_completo += texto_limpio_pagina

            pos_busqueda = offset_pagina
            for _ in range(num_imagenes_pagina):
                pos = texto_completo.find("[Imagen]", pos_busqueda)
                if pos >= 0:
                    posiciones_imagenes.append({'texto': '', 'pos': pos})
                    pos_busqueda = pos + 1

            for enlace in pagina.get_links():
                rect_enlace = enlace.get("from")
                if not rect_enlace:
                    continue
                texto_enlace = pagina.get_textbox(fitz.Rect(rect_enlace)).strip()
                if texto_enlace:
                    pos = texto_completo.find(texto_enlace[:50], offset_pagina)
                    if pos >= 0:
                        posiciones_enlaces.append({'texto': texto_enlace, 'pos': pos})

            # find_tables() solo existe en versiones recientes de PyMuPDF;
            # si no está disponible, se omiten las tablas sin romper el
            # resto de la extracción.
            if hasattr(pagina, "find_tables"):
                try:
                    for tabla in pagina.find_tables().tables:
                        texto_celda = ""
                        for fila in tabla.extract():
                            for celda in fila:
                                if celda and celda.strip():
                                    texto_celda = celda.strip()
                                    break
                            if texto_celda:
                                break
                        if texto_celda:
                            pos = texto_completo.find(texto_celda[:50], offset_pagina)
                            if pos >= 0:
                                posiciones_tablas.append({'texto': texto_celda, 'pos': pos})
                except Exception:
                    logger.exception(
                        "fallo al detectar tablas en la página %s de %s", num + 1, ruta_pdf
                    )
        else:
            # Página sin texto (portada, imagen escaneada...): su "inicio"
            # coincide con la posición actual, no aporta contenido propio.
            posiciones_inicio_pagina.append(len(texto_completo))

    toc = documento.get_toc()  # [[nivel, titulo, pagina_1_based], ...]

    posiciones_capitulos = {}
    posiciones_encabezados = []

    def _offset_de_pagina(pagina_1_based):
        idx = max(0, min(documento.page_count - 1, pagina_1_based - 1))
        return posiciones_inicio_pagina[idx] if posiciones_inicio_pagina else 0

    if toc:
        # Construir árbol jerárquico a partir de los niveles planos del TOC.
        datos_indice = []
        pila = []  # [(nivel, nodo)] — para anidar hijos bajo su padre más reciente
        for nivel, titulo, pagina in toc:
            titulo = (titulo or "").strip() or f"Página {pagina}"
            offset = _offset_de_pagina(pagina)

            # Título único: si se repite (habitual con TOC mal generados),
            # se distingue con el número de página para no pisar la entrada
            # anterior en posiciones_capitulos.
            titulo_unico = titulo
            sufijo = 2
            while titulo_unico in posiciones_capitulos:
                titulo_unico = f"{titulo} ({sufijo})"
                sufijo += 1

            nodo = {"title": titulo_unico, "offset": offset, "children": []}
            posiciones_capitulos[titulo_unico] = offset
            posiciones_encabezados.append({"nivel": nivel, "texto": titulo_unico, "pos": offset})

            while pila and pila[-1][0] >= nivel:
                pila.pop()
            if pila:
                pila[-1][1]["children"].append(nodo)
            else:
                datos_indice.append(nodo)
            pila.append((nivel, nodo))
    else:
        # Sin índice de contenidos: una entrada sintética por página, igual
        # que hace Bookworm cuando el PDF no trae TOC embebido.
        datos_indice = []
        for num in range(documento.page_count):
            titulo = f"Página {num + 1}"
            offset = posiciones_inicio_pagina[num]
            datos_indice.append({"title": titulo, "offset": offset, "children": []})
            posiciones_capitulos[titulo] = offset
            posiciones_encabezados.append({"nivel": 1, "texto": titulo, "pos": offset})

    # El texto ya salió limpio página a página (ver el bucle de arriba), así
    # que las posiciones registradas en posiciones_capitulos/posiciones_encabezados
    # son exactas sobre texto_completo — a diferencia de antes, no hace
    # falta ningún paso de limpieza global ni de reubicación posterior.
    return (
        texto_completo, datos_indice, posiciones_capitulos, posiciones_encabezados,
        [], posiciones_imagenes, posiciones_enlaces, posiciones_tablas,
    )
# ANCLAJE_FIN: GESTOR_PDF
