"""
renombrador_biblioteca.py
---------------------------
Renombrado físico seguro y re-enrutado de libros de la Biblioteca.

Responsabilidades:
  - Renombrar el archivo físico de un libro en disco cuando su título
    no coincide con los metadatos internos (titulo_revisado = 0),
    garantizando que biblioteca.db nunca quede apuntando a una ruta
    que no existe.
  - Relocalizar manualmente un libro cuyo archivo ya no está en la ruta
    indexada (movido o borrado).
  - Reconciliar en bloque rutas de una carpeta completa que se movió,
    casando por nombre de archivo en vez de por ruta exacta.

Nota de arquitectura:
  Módulo puro motor (sin wx). Cada operación de escritura en disco se
  verifica antes de tocar la base de datos: si el renombrado físico
  falla, el registro correspondiente se deja exactamente como estaba.
"""

import logging
import os

from app.motor.gestor_biblioteca import GestorBiblioteca
from app.motor.procesador_etiquetas import limpiar_nombre_archivo

logger = logging.getLogger(__name__)


class ResultadoRenombrado:
    def __init__(self, id_libro: int, titulo_anterior: str):
        self.id_libro = id_libro
        self.titulo_anterior = titulo_anterior
        self.exito = False
        self.motivo_fallo = ""
        self.ruta_nueva = ""


def renombrar_libro_segun_metadatos(gestor: GestorBiblioteca, id_libro: int, titulo_nuevo: str) -> ResultadoRenombrado:
    """
    Renombra el archivo físico de un libro para que coincida con el
    título confirmado por el usuario (flujo de bautizo, sección 2.7).

    Solo actualiza biblioteca.db si el renombrado físico tiene éxito y
    se verifica que el archivo existe en la ruta nueva.
    """
    libro = gestor.obtener_libro(id_libro)
    resultado = ResultadoRenombrado(id_libro, libro["titulo"] if libro else "")

    if libro is None:
        resultado.motivo_fallo = "El libro ya no existe en la biblioteca."
        return resultado

    ruta_actual = libro["ruta_archivo"]
    carpeta = os.path.dirname(ruta_actual)
    extension = os.path.splitext(ruta_actual)[1]

    if not os.access(carpeta, os.W_OK):
        resultado.motivo_fallo = f"Sin permiso de escritura en la carpeta: {carpeta}"
        logger.warning("[RenombradorBiblioteca] %s", resultado.motivo_fallo)
        return resultado

    nombre_saneado = limpiar_nombre_archivo(titulo_nuevo) or "Sin_titulo"
    ruta_nueva = os.path.join(carpeta, nombre_saneado + extension)

    if os.path.abspath(ruta_nueva) == os.path.abspath(ruta_actual):
        gestor.confirmar_titulo_revisado(id_libro, ruta_actual, titulo_nuevo)
        resultado.exito = True
        resultado.ruta_nueva = ruta_actual
        return resultado

    if os.path.exists(ruta_nueva):
        resultado.motivo_fallo = f"Ya existe un archivo con ese nombre: {ruta_nueva}"
        return resultado

    try:
        os.rename(ruta_actual, ruta_nueva)
    except OSError as error:
        resultado.motivo_fallo = str(error)
        logger.exception(
            "[RenombradorBiblioteca] Fallo al renombrar %s -> %s", ruta_actual, ruta_nueva
        )
        return resultado

    if not os.path.exists(ruta_nueva):
        resultado.motivo_fallo = "El renombrado no se pudo verificar tras ejecutarse."
        logger.error("[RenombradorBiblioteca] %s (%s)", resultado.motivo_fallo, ruta_nueva)
        return resultado

    gestor.confirmar_titulo_revisado(id_libro, ruta_nueva, titulo_nuevo)
    resultado.exito = True
    resultado.ruta_nueva = ruta_nueva
    return resultado


def renombrar_pendientes_por_lote(
    gestor: GestorBiblioteca, cambios: list[dict]
) -> tuple[list[ResultadoRenombrado], list[ResultadoRenombrado]]:
    """
    Aplica renombrar_libro_segun_metadatos() a varios libros de forma
    independiente. Un fallo en un archivo nunca detiene el resto del
    lote ni afecta a los registros ya renombrados con éxito.

    `cambios`: lista de dicts con las claves id_libro y titulo_nuevo.

    Devuelve (exitosos, fallidos) como listas de ResultadoRenombrado.
    """
    exitosos, fallidos = [], []
    for cambio in cambios:
        resultado = renombrar_libro_segun_metadatos(
            gestor, cambio["id_libro"], cambio["titulo_nuevo"]
        )
        (exitosos if resultado.exito else fallidos).append(resultado)
    return exitosos, fallidos


def relocalizar_libro(gestor: GestorBiblioteca, id_libro: int, ruta_localizada: str) -> bool:
    """
    Actualiza la ruta de un libro cuyo archivo se movió o se localizó
    manualmente (sección 2.4). Verifica primero que la ruta indicada
    exista de verdad en disco.
    """
    if not os.path.isfile(ruta_localizada):
        logger.warning(
            "[RenombradorBiblioteca] Ruta localizada no existe: %s", ruta_localizada
        )
        return False
    gestor.actualizar_ruta_archivo(id_libro, ruta_localizada)
    return True


def reconciliar_carpeta_movida(gestor: GestorBiblioteca, carpeta_nueva: str) -> int:
    """
    Reconcilia en bloque los libros de la biblioteca cuya ruta original
    ya no existe, casando por nombre de archivo dentro de la carpeta
    nueva indicada por el usuario (sección 2.4, re-enrutado por lotes).

    Devuelve el número de libros reconciliados.
    """
    archivos_disponibles = {}
    for raiz, _subcarpetas, archivos in os.walk(carpeta_nueva):
        for nombre_archivo in archivos:
            archivos_disponibles[nombre_archivo] = os.path.join(raiz, nombre_archivo)

    reconciliados = 0
    for libro in gestor.buscar_libros():
        if os.path.isfile(libro["ruta_archivo"]):
            continue
        nombre_archivo = os.path.basename(libro["ruta_archivo"])
        ruta_candidata = archivos_disponibles.get(nombre_archivo)
        if ruta_candidata:
            gestor.actualizar_ruta_archivo(libro["id"], ruta_candidata)
            reconciliados += 1

    return reconciliados
