# ANCLAJE_INICIO: GESTOR_PDF
"""
gestor_pdf.py
──────────────
Extracción de texto y estructura de un PDF para la pestaña Lectura, con
la misma forma de retorno que extraer_datos_epub() de gestor_epub.py,
para que pestana_lectura.py pueda cargar EPUB y PDF por el mismo camino
sin duplicar el árbol de índice, la navegación por encabezados ni el
guardado de posición de lectura.

Capítulos / navegación H·Shift+H: se usa el índice de contenidos
embebido del PDF (documento.get_toc(), vía PyMuPDF/fitz) cuando existe.
Si el PDF no tiene índice (habitual en PDF escaneados o mal generados),
se genera un índice sintético de una entrada por página ("Página N"),
para que la navegación por capítulo siga disponible aunque sea a nivel
de página — mismo criterio que Bookworm en este mismo caso.

No hay texto con negrita/cursiva/subrayado embebido de forma fiable en
PDF como en el HTML de un EPUB, así que spans_estilo se devuelve vacío.
"""

import os

import fitz

from app.motor.limpiador_lectura import limpiar_para_lectura


def extraer_datos_pdf(ruta_pdf):
    """
    Extrae el texto completo y la estructura de índice de un PDF.

    Retorna la misma forma que extraer_datos_epub():
        - texto_completo (str)
        - datos_indice (list)     [{'title', 'offset', 'children'}, ...]
        - posiciones_capitulos (dict)   {titulo: posicion_caracter}
        - posiciones_encabezados (list) [{'nivel', 'texto', 'pos'}, ...]
        - spans_estilo (list)     siempre vacío para PDF
    """
    if not os.path.exists(ruta_pdf):
        raise FileNotFoundError(f"No se encontró el archivo: {ruta_pdf}")

    try:
        documento = fitz.open(ruta_pdf)
    except Exception as e:
        raise Exception(f"Error al leer el formato PDF: {e}")

    texto_completo = ""
    posiciones_inicio_pagina = []  # índice = página 0-based, valor = offset en texto_completo (crudo)

    for num in range(documento.page_count):
        posiciones_inicio_pagina.append(len(texto_completo))
        texto_pagina = documento[num].get_text("text")
        if texto_pagina and texto_pagina.strip():
            texto_completo += texto_pagina.strip() + "\n\n"

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

    # Limpieza final para lectura accesible con NVDA — igual que gestor_epub.py.
    # A diferencia del EPUB, aquí no se reubican encabezados tras la limpieza
    # buscando su propio texto (el título de un marcador PDF no siempre
    # aparece literal en el cuerpo de la página); las posiciones se calculan
    # sobre el texto crudo, con un margen de imprecisión aceptable frente a
    # no tener navegación por capítulo en absoluto.
    texto_completo = limpiar_para_lectura(texto_completo, ruta_libro=ruta_pdf)

    return texto_completo, datos_indice, posiciones_capitulos, posiciones_encabezados, []
# ANCLAJE_FIN: GESTOR_PDF
