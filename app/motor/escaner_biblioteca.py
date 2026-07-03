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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from ebooklib import epub
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


def _extraer_metadatos_epub(ruta_archivo: str) -> dict:
    libro = epub.read_epub(ruta_archivo, options={"ignore_ncx": True})

    titulos = libro.get_metadata("DC", "title")
    titulo = titulos[0][0].strip() if titulos else ""

    autores_meta = libro.get_metadata("DC", "creator")
    autores = [a[0].strip() for a in autores_meta if a[0].strip()]

    return {"titulo": titulo, "autores": autores}


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
        coincide = _normalizar_para_comparar(titulo_metadatos) == _normalizar_para_comparar(
            titulo_archivo
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
        al_progresar: Optional[Callable[[int], None]] = None,
        al_detectar_carpetas: Optional[Callable[[dict], None]] = None,
        al_terminar: Optional[Callable[[int], None]] = None,
        al_fallar: Optional[Callable[[Exception], None]] = None,
    ):
        self.gestor = gestor
        self.al_progresar = al_progresar
        self.al_detectar_carpetas = al_detectar_carpetas
        self.al_terminar = al_terminar
        self.al_fallar = al_fallar
        self._hilo: Optional[threading.Thread] = None
        self._cancelado = threading.Event()

    def iniciar(self, carpeta_raiz: str):
        self._cancelado.clear()
        self._hilo = threading.Thread(
            target=self._ejecutar,
            args=(carpeta_raiz,),
            name="escaner_biblioteca",
            daemon=True,
        )
        self._hilo.start()

    def cancelar(self):
        self._cancelado.set()

    # ── Trabajo en segundo plano ─────────────────────────────────────────────

    def _ejecutar(self, carpeta_raiz: str):
        try:
            rutas_candidatas = self._listar_rutas_candidatas(carpeta_raiz)
            rutas_indexadas = self.gestor.obtener_rutas_indexadas()
            rutas_nuevas = [r for r in rutas_candidatas if r not in rutas_indexadas]

            total_insertados = 0
            lote_actual = []
            libros_por_carpeta: dict[str, list[str]] = {}

            with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="escaner_lib") as executor:
                futuros = {executor.submit(_procesar_archivo, ruta): ruta for ruta in rutas_nuevas}

                for futuro in as_completed(futuros):
                    if self._cancelado.is_set():
                        raise EscaneoCancelado()

                    resultado = futuro.result()
                    if resultado is None:
                        continue

                    lote_actual.append(resultado)
                    carpeta = os.path.dirname(resultado["ruta_archivo"])
                    libros_por_carpeta.setdefault(carpeta, []).append(resultado["titulo"])

                    if len(lote_actual) >= TAMANO_LOTE:
                        total_insertados += self.gestor.insertar_libros_lote(lote_actual)
                        lote_actual = []
                        if self.al_progresar:
                            self.al_progresar(total_insertados)

            if lote_actual:
                total_insertados += self.gestor.insertar_libros_lote(lote_actual)

            if self.al_progresar:
                self.al_progresar(total_insertados)

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
):
    """
    Aplica la etiqueta de agrupamiento a todos los libros ya indexados que
    procedan de `carpeta`. Debe llamarse solo tras la confirmación
    explícita del usuario en el diálogo de bautizo (sección 2.3.1 del
    documento de planificación) — nunca de forma automática.
    """
    nombre_etiqueta = limpiar_nombre_archivo(nombre_etiqueta.strip()) or nombre_etiqueta.strip()
    libros_de_la_carpeta = [
        libro for libro in gestor.buscar_libros() if os.path.dirname(libro["ruta_archivo"]) == carpeta
    ]
    for libro in libros_de_la_carpeta:
        gestor.asignar_etiqueta(libro["id"], nombre_etiqueta)
