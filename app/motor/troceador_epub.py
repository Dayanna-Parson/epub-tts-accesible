# ANCLAJE_INICIO: TROCEADOR_EPUB
"""
troceador_epub.py
──────────────────
Divide un archivo EPUB en múltiples archivos TXT, uno por cada sección
del índice de contenidos (TOC).

Soporta los dos tipos de TOC más comunes:
  · Jerárquico  (niveles): Parte I → Capítulo 1, Capítulo 2 …
                            Parte II → Capítulo 3, Capítulo 4 …
  · Plano (único nivel):   Dedicatoria / Prólogo / Capítulo 1 / Epílogo …

La detección del tipo es automática: si la raíz tiene hijos se trata como
jerárquico; si todos los nodos son hojas se trata como plano.

Nomenclatura de los archivos de salida:
  01_Prologo.txt
  02_Capitulo_1_El_inicio.txt
  ...

La carpeta de salida se llama exactamente igual que el archivo EPUB
(sin la extensión), en el mismo directorio.

Reutiliza ebooklib + BeautifulSoup ya instalados por gestor_epub.py.
"""

import os
import re
import warnings

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from app.motor.limpiador_lectura import limpiar_para_lectura

warnings.filterwarnings("ignore", category=UserWarning, module="bs4")


# ── Auxiliar ──────────────────────────────────────────────────────────────────

def _nombre_seguro(titulo: str) -> str:
    """Elimina caracteres ilegales en nombres de archivo y acorta a 80 chars."""
    limpio = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", titulo).strip()
    return (limpio or "capitulo")[:80]


# ═════════════════════════════════════════════════════════════════════════════
class TroceadorEpub:
    """
    Motor de troceado de EPUB. Sin dependencias wx.

    Flujo de uso:
        t = TroceadorEpub()
        caps = t.cargar("/ruta/libro.epub")
        # caps → list[dict]:
        #   titulo    str   nombre del capítulo
        #   display   str   texto en la lista (con indentación de nivel)
        #   nivel     int   0 = raíz, 1 = hijo …
        #   es_padre  bool  True si tiene subnodos (sección contenedora)
        #   pos_inicio int  offset en el texto completo
        n = t.trocear([0, 1, 3], "/ruta/libro/", callback_progreso=fn)
    """

    def __init__(self):
        self._ruta_epub:    str  = ""
        self._texto:        str  = ""   # texto completo del libro
        self._posiciones:   dict = {}   # filename → offset en _texto
        self._capitulos:    list = []   # list[dict] devuelto por cargar()

    # ── Carga ─────────────────────────────────────────────────────────────────

    def cargar(self, ruta_epub: str) -> list:
        """
        Lee el EPUB y devuelve la lista de capítulos/secciones del TOC.
        Lanza FileNotFoundError o Exception si el archivo no es válido.
        """
        if not os.path.exists(ruta_epub):
            raise FileNotFoundError(f"No se encontró: {ruta_epub}")

        self._ruta_epub  = ruta_epub
        self._texto      = ""
        self._posiciones = {}
        self._capitulos  = []

        libro = epub.read_epub(ruta_epub)

        # 1. Construir texto completo y mapa filename → offset
        for item_id in libro.spine:
            item = libro.get_item_with_id(item_id[0])
            if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            offset = len(self._texto)
            fn     = item.file_name

            # Registrar bajo nombre completo y basename para tolerar variaciones
            self._posiciones[fn]               = offset
            self._posiciones[fn.lower()]       = offset
            bn = os.path.basename(fn)
            self._posiciones[bn]               = offset
            self._posiciones[bn.lower()]       = offset

            sopa = BeautifulSoup(item.get_content(), "html.parser")
            for tag in sopa(["script", "style", "head", "title", "meta"]):
                tag.extract()
            lineas = [l.strip() for l in sopa.get_text(separator="\n").splitlines() if l.strip()]
            self._texto += "\n\n".join(lineas) + "\n\n"

        # 2. Construir lista de capítulos desde el TOC
        self._recorrer_toc(libro.toc, nivel=0)

        # 3. Resolver posición de inicio para cada entrada
        for cap in self._capitulos:
            cap["pos_inicio"] = self._offset_de(cap["_archivo"])

        return self._capitulos

    def _recorrer_toc(self, nodos, nivel: int):
        """Recorre el árbol del TOC de forma recursiva (jerárquico y plano)."""
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

            archivo  = href.split("#")[0]
            es_padre = bool(hijos)
            indent   = "    " * nivel

            self._capitulos.append({
                "titulo":    titulo,
                "display":   f"{indent}{titulo}",
                "nivel":     nivel,
                "es_padre":  es_padre,
                "_archivo":  archivo,
                "pos_inicio": 0,       # se rellena después
            })

            if hijos:
                self._recorrer_toc(hijos, nivel + 1)

    def _offset_de(self, archivo: str) -> int:
        """Devuelve el offset en _texto para un href de TOC."""
        if not archivo:
            return 0
        bn = os.path.basename(archivo)
        return (
            self._posiciones.get(archivo)
            or self._posiciones.get(archivo.lower())
            or self._posiciones.get(bn)
            or self._posiciones.get(bn.lower())
            or 0
        )

    # ── Troceado ──────────────────────────────────────────────────────────────

    def trocear(
        self,
        indices_seleccionados: list,
        carpeta_salida: str,
        callback_progreso=None,
    ) -> int:
        """
        Genera un TXT por cada índice seleccionado.

        callback_progreso(actual, total, titulo) — opcional, llamado desde el
        mismo hilo (si se invoca desde un hilo de fondo, usar wx.CallAfter
        en el callback si toca la UI).

        Devuelve el número de archivos TXT guardados.
        """
        os.makedirs(carpeta_salida, exist_ok=True)

        # Límites para calcular el fin de cada capítulo:
        # posiciones únicas + centinela al final del texto
        limites = sorted(set(c["pos_inicio"] for c in self._capitulos))
        limites.append(len(self._texto))

        guardados = 0
        total     = len(indices_seleccionados)

        for num, idx in enumerate(sorted(indices_seleccionados), 1):
            cap     = self._capitulos[idx]
            pos_ini = cap["pos_inicio"]

            # Siguiente límite estrictamente mayor que pos_ini
            pos_fin = len(self._texto)
            for lim in limites:
                if lim > pos_ini:
                    pos_fin = lim
                    break

            fragmento = self._texto[pos_ini:pos_fin]
            texto     = limpiar_para_lectura(fragmento).strip()

            if callback_progreso:
                callback_progreso(num, total, cap["titulo"])

            if not texto:
                continue

            titulo_limpio = _nombre_seguro(cap["titulo"])
            nombre_archivo = f"{num:02d}_{titulo_limpio}.txt"
            ruta = os.path.join(carpeta_salida, nombre_archivo)

            with open(ruta, "w", encoding="utf-8") as f:
                sep = "=" * min(len(cap["titulo"]), 60)
                f.write(f"{cap['titulo']}\n{sep}\n\n{texto}\n")

            guardados += 1

        return guardados

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def carpeta_salida_para(ruta_epub: str) -> str:
        """
        Devuelve la ruta de la carpeta de salida:
          mismo directorio que el EPUB, con el nombre del archivo sin extensión.
        Ej: /libros/Mi Novela.epub → /libros/Mi Novela/
        """
        dir_epub    = os.path.dirname(os.path.abspath(ruta_epub))
        nombre_base = os.path.splitext(os.path.basename(ruta_epub))[0]
        return os.path.join(dir_epub, nombre_base)
# ANCLAJE_FIN: TROCEADOR_EPUB
