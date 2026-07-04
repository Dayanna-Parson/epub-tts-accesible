"""
escaner_biblioteca.py
----------------------
Escaneo en segundo plano de carpetas para importar libros a la Biblioteca.

Responsabilidades:
  - Recorrer una carpeta (y subcarpetas) buscando EPUB y PDF sin bloquear
    el hilo principal.
  - Extraer metadatos ligeros (título, autor) en paralelo con un pool de
    hilos, sin tocar la base de datos desde los workers.
  - Detectar discrepancias entre el nombre de archivo y el título de los
    metadatos internos (titulo_revisado).
  - Detectar carpetas con varios libros como candidatas a etiqueta de
    saga/colección, sin aplicarlo nunca de forma automática.
  - Insertar los resultados en biblioteca.db por lotes.

Nota de arquitectura:
  Este módulo es puro motor (sin wx). Recibe callbacks opcionales para
  reportar progreso; la interfaz que lo invoque debe envolver esos
  callbacks con wx.CallAfter, ya que se ejecutan desde un hilo secundario.
"""

import logging
import os
import re
import threading
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional
from xml.etree import ElementTree

import fitz

from app.motor.gestor_biblioteca import GestorBiblioteca
from app.motor.procesador_etiquetas import limpiar_nombre_archivo

logger = logging.getLogger(__name__)

EXTENSIONES_VALIDAS = {".epub", ".pdf"}
TAMANO_LOTE = 50
MAX_WORKERS = 8
MIN_LIBROS_PARA_SUGERIR_CARPETA = 2


def _normalizar_para_comparar(texto: str) -> str:
    """
    Normaliza un título para comparar archivo vs. metadatos, ignorando
    tildes, mayúsculas y separadores — una diferencia solo de acentuación
    no debe marcar el libro como pendiente de revisión.
    """
    texto = texto.lower()
    texto = re.sub(r"[_\-\.]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    texto_sin_tildes = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto_sin_tildes if not unicodedata.combining(c))


def _titulo_desde_nombre_archivo(ruta_archivo: str) -> str:
    nombre = os.path.splitext(os.path.basename(ruta_archivo))[0]
    nombre = re.sub(r"[_\-]+", " ", nombre)
    return re.sub(r"\s+", " ", nombre).strip()


def _nombre_local(etiqueta: str) -> str:
    """'{http://purl.org/dc/elements/1.1/}title' → 'title'."""
    return etiqueta.rsplit("}", 1)[-1].lower()


def _textos_por_nombre_local(raiz: ElementTree.Element, nombre: str) -> list[str]:
    return [
        elemento.text.strip()
        for elemento in raiz.iter()
        if _nombre_local(elemento.tag) == nombre and elemento.text and elemento.text.strip()
    ]


def _extraer_metadatos_epub(ruta_archivo: str) -> dict:
    """
    Lee solo container.xml y el .opf del EPUB para extraer título y
    autores, sin cargar el resto del manifiesto. Este enfoque es
    deliberadamente más ligero que un lector de EPUB completo: algunos
    archivos reales traen referencias rotas a imágenes u otros recursos
    en el manifiesto (portadas movidas, exportaciones defectuosas de
    otras herramientas) que harían fallar una carga completa del libro
    sin que eso afecte en nada a la lectura de sus metadatos.
    """
    with zipfile.ZipFile(ruta_archivo) as zf:
        contenedor = ElementTree.fromstring(zf.read("META-INF/container.xml"))
        rootfile = contenedor.find(".//{*}rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise ValueError("container.xml sin rootfile válido")
        ruta_opf = rootfile.get("full-path")

        opf = ElementTree.fromstring(zf.read(ruta_opf))

    titulos = _textos_por_nombre_local(opf, "title")
    autores = _textos_por_nombre_local(opf, "creator")

    return {"titulo": titulos[0] if titulos else "", "autores": autores}


def _extraer_metadatos_pdf(ruta_archivo: str) -> dict:
    documento = fitz.open(ruta_archivo)
    try:
        titulo = (documento.metadata.get("title") or "").strip()
        autor = (documento.metadata.get("author") or "").strip()
    finally:
        documento.close()

    autores = [autor] if autor else []
    return {"titulo": titulo, "autores": autores}


def _procesar_archivo(ruta_archivo: str) -> Optional[dict]:
    """
    Extrae metadatos ligeros de un archivo. Se ejecuta dentro del pool de
    hilos y no toca la base de datos. Devuelve None si el archivo no se
    puede procesar (se registra el motivo y se salta, sin detener el
    resto del escaneo).
    """
    extension = os.path.splitext(ruta_archivo)[1].lower()
    formato = "epub" if extension == ".epub" else "pdf"

    try:
        if formato == "epub":
            metadatos = _extraer_metadatos_epub(ruta_archivo)
        else:
            metadatos = _extraer_metadatos_pdf(ruta_archivo)
    except Exception:
        logger.exception("[EscanerBiblioteca] No se pudo leer metadatos de: %s", ruta_archivo)
        return None

    titulo_metadatos = metadatos["titulo"]
    titulo_archivo = _titulo_desde_nombre_archivo(ruta_archivo)

    if titulo_metadatos:
        norm_metadatos = _normalizar_para_comparar(titulo_metadatos)
        norm_archivo = _normalizar_para_comparar(titulo_archivo)
        # Contención, no solo igualdad exacta: es habitual que el título de
        # los metadatos incluya información de saga entre paréntesis que el
        # nombre de archivo no tiene (o al revés), sin que eso sea una
        # discrepancia real que merezca marcarse para revisión manual.
        coincide = (
            norm_metadatos == norm_archivo
            or norm_archivo in norm_metadatos
            or norm_metadatos in norm_archivo
        )
        titulo_final = titulo_metadatos
        titulo_revisado = coincide
    else:
        titulo_final = titulo_archivo
        titulo_revisado = True

    return {
        "ruta_archivo": ruta_archivo,
        "titulo": titulo_final or "Sin título",
        "formato": formato,
        "autores": metadatos["autores"],
        "titulo_revisado": titulo_revisado,
    }


class EscaneoCancelado(Exception):
    pass


class EscanerBiblioteca:
    """
    Coordina el escaneo de una carpeta en un hilo de fondo.

    Uso típico desde la interfaz:
        escaner = EscanerBiblioteca(
            gestor,
            al_progresar=lambda n: wx.CallAfter(self._actualizar_contador, n),
            al_detectar_carpetas=lambda carpetas: wx.CallAfter(self._preguntar_agrupar, carpetas),
            al_terminar=lambda total: wx.CallAfter(self._anunciar_fin, total),
        )
        escaner.iniciar("/ruta/a/mis/libros")
    """

    def __init__(
        self,
        gestor: GestorBiblioteca,
        al_progresar: Optional[Callable[[int, int], None]] = None,
        al_detectar_carpetas: Optional[Callable[[dict], None]] = None,
        al_terminar: Optional[Callable[[int], None]] = None,
        al_fallar: Optional[Callable[[Exception], None]] = None,
    ):
        """
        al_progresar recibe (procesados, total) — no solo el número de
        insertados — para poder anunciar y mostrar progreso real incluso
        en importaciones pequeñas (menos de un lote de TAMANO_LOTE).
        """
        self.gestor = gestor
        self.al_progresar = al_progresar
        self.al_detectar_carpetas = al_detectar_carpetas
        self.al_terminar = al_terminar
        self.al_fallar = al_fallar
        self._hilo: Optional[threading.Thread] = None
        self._cancelado = threading.Event()

    def iniciar(self, carpeta_raiz: str, usar_subcarpetas_como_categorias: bool = False):
        """
        Si usar_subcarpetas_como_categorias es True, la ruta de carpetas
        entre carpeta_raiz y cada libro se usa como su género/subgénero
        (ej. carpeta_raiz/Fantasía/Fantasía épica/libro.epub → categoría
        "Fantasía > Fantasía épica"). Es opcional porque no todo el mundo
        organiza su colección por género en el disco — quien no lo haga
        no debe ver categorías inventadas a partir de nombres de carpeta
        que en realidad son otra cosa (autor, formato, origen...).
        """
        self._cancelado.clear()
        self._hilo = threading.Thread(
            target=self._ejecutar,
            args=(carpeta_raiz, usar_subcarpetas_como_categorias),
            name="escaner_biblioteca",
            daemon=True,
        )
        self._hilo.start()

    def cancelar(self):
        self._cancelado.set()

    # ── Trabajo en segundo plano ─────────────────────────────────────────────

    def _ejecutar(self, carpeta_raiz: str, usar_subcarpetas_como_categorias: bool = False):
        try:
            rutas_candidatas = self._listar_rutas_candidatas(carpeta_raiz)
            rutas_indexadas = self.gestor.obtener_rutas_indexadas()
            rutas_nuevas = [r for r in rutas_candidatas if r not in rutas_indexadas]
            total_a_procesar = len(rutas_nuevas)

            total_insertados = 0
            procesados = 0
            lote_actual = []
            libros_por_carpeta: dict[str, list[str]] = {}

            with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="escaner_lib") as executor:
                futuros = {executor.submit(_procesar_archivo, ruta): ruta for ruta in rutas_nuevas}

                for futuro in as_completed(futuros):
                    if self._cancelado.is_set():
                        raise EscaneoCancelado()

                    resultado = futuro.result()
                    procesados += 1
                    if resultado is None:
                        if self.al_progresar:
                            self.al_progresar(procesados, total_a_procesar)
                        continue

                    if usar_subcarpetas_como_categorias:
                        resultado["categorias"] = [
                            self._ruta_categoria_desde_carpeta(carpeta_raiz, resultado["ruta_archivo"])
                        ]

                    lote_actual.append(resultado)
                    carpeta = os.path.dirname(resultado["ruta_archivo"])
                    libros_por_carpeta.setdefault(carpeta, []).append(resultado["titulo"])

                    if len(lote_actual) >= TAMANO_LOTE:
                        total_insertados += self.gestor.insertar_libros_lote(lote_actual)
                        lote_actual = []

                    if self.al_progresar:
                        self.al_progresar(procesados, total_a_procesar)

            if lote_actual:
                total_insertados += self.gestor.insertar_libros_lote(lote_actual)

            if self.al_progresar:
                self.al_progresar(total_a_procesar, total_a_procesar)

            carpetas_candidatas = {
                carpeta: titulos
                for carpeta, titulos in libros_por_carpeta.items()
                if len(titulos) >= MIN_LIBROS_PARA_SUGERIR_CARPETA
            }
            if carpetas_candidatas and self.al_detectar_carpetas:
                self.al_detectar_carpetas(carpetas_candidatas)

            if self.al_terminar:
                self.al_terminar(total_insertados)

        except EscaneoCancelado:
            logger.info("[EscanerBiblioteca] Escaneo cancelado por el usuario.")
        except Exception as error:
            logger.exception("[EscanerBiblioteca] Fallo durante el escaneo de: %s", carpeta_raiz)
            if self.al_fallar:
                self.al_fallar(error)

    @staticmethod
    def _ruta_categoria_desde_carpeta(carpeta_raiz: str, ruta_archivo: str) -> list[str]:
        carpeta_libro = os.path.dirname(ruta_archivo)
        relativa = os.path.relpath(carpeta_libro, carpeta_raiz)
        if relativa in ("", "."):
            return []
        return [parte for parte in relativa.split(os.sep) if parte not in ("", ".")]

    @staticmethod
    def _listar_rutas_candidatas(carpeta_raiz: str) -> list[str]:
        rutas = []
        for raiz, _subcarpetas, archivos in os.walk(carpeta_raiz):
            for nombre_archivo in archivos:
                extension = os.path.splitext(nombre_archivo)[1].lower()
                if extension in EXTENSIONES_VALIDAS:
                    rutas.append(os.path.join(raiz, nombre_archivo))
        return rutas


def confirmar_agrupamiento_por_carpeta(
    gestor: GestorBiblioteca, carpeta: str, nombre_etiqueta: str
) -> tuple[int, int]:
    """
    Aplica la etiqueta de agrupamiento a todos los libros ya indexados que
    procedan de `carpeta`. Debe llamarse solo tras la confirmación
    explícita del usuario en el diálogo de bautizo (sección 2.3.1 del
    documento de planificación) — nunca de forma automática.

    El orden dentro de la etiqueta sigue el orden alfabético del nombre
    de archivo dentro de la carpeta (no el título), porque es habitual
    numerar los libros de una saga en el nombre del archivo ("01.",
    "02."...) incluso cuando el título real de los metadatos no lo
    indica. Ese orden es el que luego respeta buscar_libros() al listar
    la saga, en vez del alfabético por título.

    Usa gestor.obtener_libros_de_carpeta() (consulta indexada por
    carpeta) en vez de gestor.buscar_libros() sin filtro — con muchas
    carpetas candidatas (una biblioteca grande puede detectar cientos de
    sagas de golpe), repetir un SELECT de toda la biblioteca por cada
    carpeta es demasiado lento.

    Un fallo al asignar la etiqueta a un libro concreto no aborta el
    resto de la carpeta — se registra y se continúa, mismo principio ya
    usado en renombrar_pendientes_por_lote (renombrador_biblioteca.py).
    Devuelve (exitosos, fallidos).
    """
    nombre_etiqueta = limpiar_nombre_archivo(nombre_etiqueta.strip()) or nombre_etiqueta.strip()
    libros_de_la_carpeta = sorted(
        gestor.obtener_libros_de_carpeta(carpeta),
        key=lambda libro: os.path.basename(libro["ruta_archivo"]).lower(),
    )
    exitosos = 0
    fallidos = 0
    for orden, libro in enumerate(libros_de_la_carpeta):
        try:
            gestor.asignar_etiqueta(libro["id"], nombre_etiqueta, orden=orden)
            exitosos += 1
        except Exception:
            fallidos += 1
            logger.exception(
                "[EscanerBiblioteca] No se pudo etiquetar el libro %s con «%s»",
                libro["id"], nombre_etiqueta,
            )
    return exitosos, fallidos
