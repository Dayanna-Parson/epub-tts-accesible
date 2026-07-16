# ANCLAJE_INICIO: TROCEADOR_PDF
"""
troceador_pdf.py
─────────────────
Extractor de texto para PDF, con la misma interfaz pública que
TroceadorEpub (cargar / extraer_capitulos_texto /
extraer_texto_completo_con_fronteras), para que el Creador de
Audiolibros pueda usar cualquiera de los dos sin distinguir el formato
más allá de elegir la clase.

Capítulos: se usa el índice de contenidos embebido del PDF
(documento.get_toc(), vía PyMuPDF/fitz) cuando existe, tomando el rango
de páginas entre cada entrada y la siguiente. Si el PDF no tiene índice
de contenidos (habitual en PDF escaneados o mal generados), se trata
como un único bloque "Documento completo" con todas las páginas — el
modo "Por capítulos" sigue funcionando, solo que con una entrada.
"""

import fitz

from app.motor.limpiador_lectura import limpiar_para_lectura


def _texto_de_paginas(documento, pagina_inicio: int, pagina_fin: int) -> str:
    """Concatena el texto de las páginas [pagina_inicio, pagina_fin) (0-based, fin exclusivo)."""
    bloques = []
    for num in range(pagina_inicio, pagina_fin):
        if 0 <= num < documento.page_count:
            texto_pagina = documento[num].get_text("text")
            if texto_pagina and texto_pagina.strip():
                bloques.append(texto_pagina)
    return "\n\n".join(bloques)


class TroceadorPdf:
    """
    Motor de extracción de texto de PDF para el Creador de Audiolibros.
    Sin dependencias wx.
    """

    def __init__(self):
        self._ruta_pdf: str = ""
        self._documento = None
        self._cortes: list = []   # lista de dicts: titulo, pagina_inicio, pagina_fin (0-based)

    def cargar(self, ruta_pdf: str) -> list:
        """
        Abre el PDF y calcula los cortes por capítulo a partir de su índice
        de contenidos (TOC). Devuelve la lista de cortes, con la misma forma
        que TroceadorEpub.cargar(): título, display, nivel, es_padre.
        """
        self._ruta_pdf = ruta_pdf
        self._documento = fitz.open(ruta_pdf)

        toc = self._documento.get_toc()  # lista de [nivel, titulo, pagina(1-based)]
        total_paginas = self._documento.page_count

        self._cortes = []
        if toc:
            # Páginas en TOC son 1-based; se normalizan a 0-based aquí.
            entradas = [(max(0, pagina - 1), (titulo or "").strip(), nivel) for nivel, titulo, pagina in toc]
            entradas.sort(key=lambda e: e[0])
            for i, (pagina_inicio, titulo, nivel) in enumerate(entradas):
                pagina_fin = entradas[i + 1][0] if i + 1 < len(entradas) else total_paginas
                if pagina_fin <= pagina_inicio:
                    pagina_fin = pagina_inicio + 1
                self._cortes.append({
                    "titulo": titulo or f"Página {pagina_inicio + 1}",
                    "pagina_inicio": pagina_inicio,
                    "pagina_fin": pagina_fin,
                    "nivel": max(0, nivel - 1),
                })
        else:
            self._cortes.append({
                "titulo": "Documento completo",
                "pagina_inicio": 0,
                "pagina_fin": total_paginas,
                "nivel": 0,
            })

        return [
            {
                "titulo": c["titulo"],
                "display": ("    " * c["nivel"]) + c["titulo"],
                "nivel": c["nivel"],
                "es_padre": False,
                "pos_inicio": 0,
            }
            for c in self._cortes
        ]

    def extraer_capitulos_texto(self, indices_seleccionados: list = None) -> list:
        """
        Devuelve una lista de (titulo_capitulo, texto_limpio) para los
        índices indicados (o todos si no se especifica), en el mismo
        formato que TroceadorEpub.extraer_capitulos_texto().
        """
        indices = (
            sorted(indices_seleccionados) if indices_seleccionados is not None
            else list(range(len(self._cortes)))
        )
        resultado = []
        for idx in indices:
            corte = self._cortes[idx]
            texto = _texto_de_paginas(self._documento, corte["pagina_inicio"], corte["pagina_fin"])
            texto = limpiar_para_lectura(texto, self._ruta_pdf).strip()
            resultado.append((corte["titulo"], texto))
        return resultado

    def extraer_texto_completo_con_fronteras(self, indices_seleccionados: list = None):
        """
        Igual que TroceadorEpub.extraer_texto_completo_con_fronteras(): concatena
        los capítulos indicados y devuelve también las fronteras de carácter
        donde empieza cada uno, para el corte por cuota del modo "libro completo".
        """
        capitulos = self.extraer_capitulos_texto(indices_seleccionados)
        texto_completo = ""
        fronteras = []
        for _titulo, texto in capitulos:
            if not texto:
                continue
            if texto_completo:
                texto_completo += "\n\n"
            fronteras.append(len(texto_completo))
            texto_completo += texto
        return texto_completo, fronteras
# ANCLAJE_FIN: TROCEADOR_PDF
