# ANCLAJE_INICIO: TROCEADOR_EPUB
"""
troceador_epub.py  (v2 — lógica inspirada en EpubSplit de JimmXinu)
────────────────────────────────────────────────────────────────────
Divide un archivo EPUB en múltiples archivos TXT, uno por capítulo o
sección del índice de contenidos.

Mejoras respecto a la versión anterior
────────────────────────────────────────
El algoritmo anterior solo dividía por archivo del spine, lo que hacía
que varios capítulos dentro de un mismo HTML (el caso más habitual en
EPUBs modernos) se fusionaran en un único TXT.

Esta versión crea "puntos de corte" combinando:
  1. Los ítems del spine  (nivel archivo)
  2. Las anclas #anchor del TOC (nivel interno de un mismo archivo)

Referencia: https://github.com/JimmXinu/EpubSplit  (método get_split_lines)

Tipos de índice soportados
───────────────────────────
  · Jerárquico  → Parte I > Capítulo 1, Capítulo 2 …
                  Parte II > Capítulo 3, Capítulo 4 …
  · Plano       → Dedicatoria / Prólogo / Capítulo 1 / Epílogo …

Estructura de salida:
  Grabaciones_Epub-TTS/<NombreLibro>/originales/01_Titulo.txt …

Formato de salida: TXT con cabecera (título + separador) y texto limpio.
"""

import os
import re
import warnings

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from app.config_rutas import RAIZ
from app.motor.limpiador_lectura import limpiar_para_lectura

# Carpeta raíz donde se generan los proyectos de grabación
CARPETA_RAIZ = os.path.join(RAIZ, "Grabaciones_Epub-TTS")

warnings.filterwarnings("ignore", category=UserWarning, module="bs4")


# ── Auxiliares ────────────────────────────────────────────────────────────────

def _nombre_seguro(titulo: str) -> str:
    """Elimina caracteres ilegales en nombres de archivo; máximo 80 chars."""
    limpio = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", titulo).strip()
    return (limpio or "capitulo")[:80]


def _split_html(html_data: str, tagid: str, before: bool) -> str:
    """
    Corta el HTML en el elemento con id=tagid.
    before=False → devuelve la parte DESDE el elemento (inclusive).
    before=True  → devuelve la parte HASTA el elemento (exclusive).

    Port directo de EpubSplit.splitHtml() de JimmXinu.
    """
    sopa = BeautifulSoup(html_data, "html.parser")
    splitpoint = sopa.find(id=tagid)
    if splitpoint is None:
        return html_data

    if before:
        # Conservar contenido ANTES del punto de corte
        for n in list(splitpoint.find_next_siblings()):
            n.extract()
        parent = splitpoint.parent
        while parent and parent.name not in ("body", "[document]", "html"):
            for n in list(parent.find_next_siblings()):
                n.extract()
            parent = parent.parent
        splitpoint.extract()
    else:
        # Conservar contenido DESDE el punto de corte
        for n in list(splitpoint.find_previous_siblings()):
            n.extract()
        parent = splitpoint.parent
        while parent and parent.name not in ("body", "[document]", "html"):
            for n in list(parent.find_previous_siblings()):
                n.extract()
            parent = parent.parent

    return str(sopa)


def _html_a_texto(html_data: str) -> str:
    """Convierte HTML en texto limpio (sin scripts, estilos ni etiquetas)."""
    sopa = BeautifulSoup(html_data, "html.parser")
    for tag in sopa(["script", "style", "head", "title", "meta"]):
        tag.extract()
    lineas = [l.strip() for l in sopa.get_text(separator="\n").splitlines() if l.strip()]
    return "\n\n".join(lineas)


# ═════════════════════════════════════════════════════════════════════════════
class TroceadorEpub:
    """
    Motor de división de EPUB en archivos TXT. Sin dependencias wx.

    Flujo:
        t = TroceadorEpub()
        caps = t.cargar("/ruta/libro.epub")
        # caps → list[dict]  (titulo, display, nivel, es_padre, pos_inicio=0)
        carpeta = TroceadorEpub.carpeta_salida_para("/ruta/libro.epub")
        n = t.dividir([0, 1, 3], carpeta, callback_progreso=fn)
    """

    def __init__(self):
        self._ruta_epub:  str  = ""
        self._libro             = None   # objeto ebooklib
        self._split_lines: list = []     # lista de puntos de corte
        self._items_por_href: dict = {}  # href normalizado → EpubItem

    # ── Carga ─────────────────────────────────────────────────────────────────

    def cargar(self, ruta_epub: str) -> list:
        """
        Lee el EPUB y devuelve la lista de puntos de corte (capítulos/secciones).

        Cada entrada es un dict:
          titulo    str   nombre legible (del TOC o del archivo si no está en el TOC)
          display   str   texto para mostrar en la lista CheckListCtrl
          nivel     int   0 = raíz, 1 = hijo… (para mostrar indentación visual)
          es_padre  bool  True si el TOC lo marcó como sección contenedora
          pos_inicio int  siempre 0 (se usa internamente idx en split_lines)
        """
        if not os.path.exists(ruta_epub):
            raise FileNotFoundError(f"No se encontró: {ruta_epub}")

        self._ruta_epub = ruta_epub
        self._libro     = epub.read_epub(ruta_epub)

        # Índice rápido href → item para la extracción
        self._items_por_href = {}
        for item in self._libro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            fn = item.file_name
            self._items_por_href[fn]                      = item
            self._items_por_href[fn.lower()]              = item
            self._items_por_href[os.path.basename(fn)]   = item
            self._items_por_href[os.path.basename(fn).lower()] = item

        # Construir split_lines y devolver la lista pública
        self._split_lines = self._construir_split_lines()

        return [
            {
                "titulo":    sl["titulo"],
                "display":   sl["display"],
                "nivel":     sl["nivel"],
                "es_padre":  sl["es_padre"],
                "pos_inicio": 0,     # campo legacy, no usado en v2
            }
            for sl in self._split_lines
        ]

    # ── Construcción de puntos de corte ───────────────────────────────────────

    def _construir_split_lines(self) -> list:
        """
        Genera la lista plana de puntos de corte combinando spine + anclas del TOC.
        Inspirado en get_split_lines() de EpubSplit.
        """
        toc_map = self._construir_toc_map()   # href_normalizado → [(titulo, anchor, nivel, es_padre)]

        split_lines = []

        for item_id in self._libro.spine:
            item = self._libro.get_item_with_id(item_id[0])
            if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            fn = self._normalizar_href(item.file_name)

            if fn in toc_map:
                for (titulo, anchor, nivel, es_padre) in toc_map[fn]:
                    indent = "    " * nivel
                    split_lines.append({
                        "href":     fn,
                        "anchor":   anchor,
                        "titulo":   titulo,
                        "display":  f"{indent}{titulo}",
                        "nivel":    nivel,
                        "es_padre": es_padre,
                    })
            else:
                # Archivo en spine pero no referenciado en el TOC
                # Se incluye con el nombre del archivo como título (cubierta, copyright…)
                nombre = os.path.splitext(os.path.basename(fn))[0]
                split_lines.append({
                    "href":     fn,
                    "anchor":   None,
                    "titulo":   nombre,
                    "display":  nombre,
                    "nivel":    0,
                    "es_padre": False,
                })

        return split_lines

    def _construir_toc_map(self) -> dict:
        """
        Construye el mapa: href_normalizado → [(titulo, anchor, nivel, es_padre)]

        Los ítems sin ancla (nivel de archivo) van PRIMERO dentro de cada href,
        seguidos de los que tienen ancla (divisiones internas). Mismo criterio
        que get_toc_map() de EpubSplit.
        """
        toc_map: dict = {}

        def _recorrer(nodos, nivel: int):
            for nodo in nodos:
                titulo, href, hijos = "", "", []

                if isinstance(nodo, epub.Link):
                    titulo = nodo.title or ""
                    href   = nodo.href  or ""
                elif isinstance(nodo, (tuple, list)):
                    cab = nodo[0]
                    if isinstance(cab, (epub.Section, epub.Link)):
                        titulo = cab.title or ""
                        href   = cab.href  or ""
                    if len(nodo) > 1 and isinstance(nodo[1], list):
                        hijos = nodo[1]

                if not titulo:
                    continue

                if "#" in href:
                    filename, anchor = href.split("#", 1)
                else:
                    filename, anchor = href, None

                fn       = self._normalizar_href(filename)
                es_padre = bool(hijos)

                if fn not in toc_map:
                    toc_map[fn] = []

                # Sin ancla → posición inicial de la lista (coincide con inicio del archivo)
                if anchor is None:
                    idx = 0
                    while idx < len(toc_map[fn]) and toc_map[fn][idx][1] is None:
                        idx += 1
                    toc_map[fn].insert(idx, (titulo, anchor, nivel, es_padre))
                else:
                    toc_map[fn].append((titulo, anchor, nivel, es_padre))

                if hijos:
                    _recorrer(hijos, nivel + 1)

        _recorrer(self._libro.toc, nivel=0)
        return toc_map

    def _normalizar_href(self, href: str) -> str:
        """
        Intenta encontrar en el manifiesto la clave exacta que corresponde a href.
        Tolera rutas con y sin prefijo de directorio.
        """
        if href in self._items_por_href:
            return self._items_por_href[href].file_name
        bn = os.path.basename(href)
        if bn in self._items_por_href:
            return self._items_por_href[bn].file_name
        return href

    # ── División ──────────────────────────────────────────────────────────────

    def dividir(
        self,
        indices_seleccionados: list,
        carpeta_salida: str,
        callback_progreso=None,
    ) -> int:
        """
        Genera un TXT por cada índice seleccionado.
        callback_progreso(actual, total, titulo) — llamado desde el mismo hilo.
        Devuelve el número de archivos TXT guardados.
        """
        os.makedirs(carpeta_salida, exist_ok=True)

        guardados = 0
        indices_sorted = sorted(indices_seleccionados)
        total          = len(indices_sorted)

        for num, idx in enumerate(indices_sorted, 1):
            sl      = self._split_lines[idx]
            next_sl = self._split_lines[idx + 1] if idx + 1 < len(self._split_lines) else None

            texto = self._extraer_texto(sl, next_sl)
            texto = limpiar_para_lectura(texto).strip()

            if callback_progreso:
                callback_progreso(num, total, sl["titulo"])

            if not texto:
                continue

            # El número del archivo coincide con la posición del capítulo en la
            # lista completa (idx+1), no con su orden entre los seleccionados.
            # Así "03_Capitulo.txt" corresponde exactamente al ítem "03" de la lista.
            titulo_limpio  = _nombre_seguro(sl["titulo"])
            nombre_archivo = f"{idx + 1:02d}_{titulo_limpio}.txt"
            ruta           = os.path.join(carpeta_salida, nombre_archivo)

            with open(ruta, "w", encoding="utf-8") as f:
                sep = "=" * min(len(sl["titulo"]), 60)
                f.write(f"{sl['titulo']}\n{sep}\n\n{texto}\n")

            guardados += 1

        return guardados

    def _extraer_texto(self, sl: dict, next_sl: dict | None) -> str:
        """
        Extrae el texto del capítulo definido por sl, usando next_sl como límite.

        Casos:
          · sl.anchor = None, next_sl distinto archivo → archivo completo
          · sl.anchor = None, next_sl mismo archivo + anchor → cortar al inicio de next_sl
          · sl.anchor ≠ None → contenido desde ese anchor
          · next_sl mismo archivo + anchor ≠ None → cortar allí
        """
        item = self._items_por_href.get(sl["href"])
        if item is None:
            return ""

        html_data = item.get_content().decode("utf-8", errors="replace")

        # Recortar el inicio al anchor del split line actual
        if sl["anchor"]:
            html_data = _split_html(html_data, sl["anchor"], before=False)

        # Recortar el fin si el siguiente capítulo está en el mismo archivo
        if (next_sl is not None
                and next_sl["href"] == sl["href"]
                and next_sl["anchor"] is not None):
            html_data = _split_html(html_data, next_sl["anchor"], before=True)

        return _html_a_texto(html_data)

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def carpeta_salida_para(ruta_epub: str) -> str:
        """
        Devuelve la ruta de la subcarpeta /originales/ donde se guardan los TXT.

        Estructura:
          Grabaciones_Epub-TTS/<NombreLibro>/originales/

        Donde <NombreLibro> es el nombre del archivo EPUB sin extensión.
        Ej: /libros/Mi Novela.epub  →  Grabaciones_Epub-TTS/Mi Novela/originales/
        """
        nombre_base = os.path.splitext(os.path.basename(ruta_epub))[0]
        return os.path.join(CARPETA_RAIZ, nombre_base, "originales")
# ANCLAJE_FIN: TROCEADOR_EPUB
