# ANCLAJE_INICIO: GESTOR_BACKUPS
"""
gestor_backups.py
───────────────────
Copias de seguridad automáticas de proyectos.json y biblioteca.db.

Cada tipo vive en su propia subcarpeta —configuraciones/backups_proyectos/
y configuraciones/backups_biblioteca/— para no mezclar archivos de origen
distinto en un mismo listado. Antes ambas compartían
configuraciones/proyectos_backup/; _migrar_carpeta_antigua_si_hace_falta()
reparte una sola vez los .zip que hubiera ahí por su prefijo de nombre.

Cada copia solo se crea si el archivo de origen cambió de verdad desde la
última copia (se compara su fecha de modificación con la del backup más
reciente): así abrir o cerrar la app sin tocar nada no genera un .zip vacío
de trabajo. Se mantiene un historial rotativo de las últimas _MAX_BACKUPS
copias de cada tipo; las más antiguas se borran automáticamente.
"""
import datetime
import logging
import os
import zipfile

from app.config_rutas import ruta_config

logger = logging.getLogger(__name__)

_DIR_BACKUPS_PROYECTOS = ruta_config("backups_proyectos")
_DIR_BACKUPS_BIBLIOTECA = ruta_config("backups_biblioteca")
_DIR_BACKUPS_ANTIGUA = ruta_config("proyectos_backup")
_MAX_BACKUPS = 5


def _migrar_carpeta_antigua_si_hace_falta():
    """
    Reparte los .zip de la carpeta antigua (mezclados) a las dos carpetas
    nuevas, por prefijo de nombre. Se ejecuta una sola vez: en cuanto la
    carpeta antigua queda vacía o no existe, no vuelve a mirar.
    """
    if not os.path.isdir(_DIR_BACKUPS_ANTIGUA):
        return
    try:
        for nombre in os.listdir(_DIR_BACKUPS_ANTIGUA):
            if not nombre.endswith(".zip"):
                continue
            if nombre.startswith("proyectos_"):
                destino_dir = _DIR_BACKUPS_PROYECTOS
            elif nombre.startswith("biblioteca_"):
                destino_dir = _DIR_BACKUPS_BIBLIOTECA
            else:
                continue
            os.makedirs(destino_dir, exist_ok=True)
            origen = os.path.join(_DIR_BACKUPS_ANTIGUA, nombre)
            os.replace(origen, os.path.join(destino_dir, nombre))
        if not os.listdir(_DIR_BACKUPS_ANTIGUA):
            os.rmdir(_DIR_BACKUPS_ANTIGUA)
    except Exception:
        logger.exception("[Backups] Error al migrar proyectos_backup/ a las carpetas separadas")


def _hay_cambios_desde_ultimo_backup(ruta_origen: str, carpeta_backups: str, prefijo: str) -> bool:
    """
    True si ruta_origen se modificó después de haberse creado el backup más
    reciente de ese prefijo (o si todavía no existe ningún backup).
    """
    if not os.path.isdir(carpeta_backups):
        return True
    backups = sorted(
        f for f in os.listdir(carpeta_backups)
        if f.startswith(prefijo) and f.endswith(".zip")
    )
    if not backups:
        return True
    ruta_ultimo = os.path.join(carpeta_backups, backups[-1])
    return os.path.getmtime(ruta_origen) > os.path.getmtime(ruta_ultimo)


def _crear_backup(ruta_origen: str, carpeta_backups: str, prefijo: str, arcname: str):
    os.makedirs(carpeta_backups, exist_ok=True)
    marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_zip = f"{prefijo}{marca}.zip"
    ruta_zip = os.path.join(carpeta_backups, nombre_zip)
    ruta_tmp = ruta_zip + ".tmp"

    with zipfile.ZipFile(ruta_tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ruta_origen, arcname=arcname)

    os.replace(ruta_tmp, ruta_zip)
    _rotar_backups_antiguos(carpeta_backups, prefijo)
    return nombre_zip


def _rotar_backups_antiguos(carpeta_backups: str, prefijo: str):
    """Elimina los backups de ese prefijo que superen el límite de _MAX_BACKUPS."""
    try:
        archivos = sorted(
            f for f in os.listdir(carpeta_backups)
            if f.startswith(prefijo) and f.endswith(".zip")
        )
        while len(archivos) > _MAX_BACKUPS:
            os.remove(os.path.join(carpeta_backups, archivos.pop(0)))
    except Exception:
        logger.exception("[Backups] Error al rotar backups antiguos de %s", prefijo)


def crear_backup_proyectos():
    """
    Crea backups_proyectos/proyectos_YYYYMMDD_HHMMSS.zip con el contenido
    actual de proyectos.json, solo si cambió desde la última copia.
    """
    _migrar_carpeta_antigua_si_hace_falta()
    ruta_proyectos = ruta_config("proyectos.json")
    if not os.path.exists(ruta_proyectos):
        return
    if not _hay_cambios_desde_ultimo_backup(ruta_proyectos, _DIR_BACKUPS_PROYECTOS, "proyectos_"):
        return
    try:
        nombre_zip = _crear_backup(ruta_proyectos, _DIR_BACKUPS_PROYECTOS, "proyectos_", "proyectos.json")
        logger.info("[Backups] Copia de proyectos creada: %s", nombre_zip)
    except Exception:
        logger.exception("[Backups] Error al crear copia de seguridad de proyectos.json")


def listar_backups() -> list:
    """
    Devuelve los nombres de los archivos de backup de proyectos, ordenados
    del más reciente al más antiguo.
    """
    _migrar_carpeta_antigua_si_hace_falta()
    try:
        if not os.path.exists(_DIR_BACKUPS_PROYECTOS):
            return []
        return sorted(
            (f for f in os.listdir(_DIR_BACKUPS_PROYECTOS)
             if f.startswith("proyectos_") and f.endswith(".zip")),
            reverse=True,
        )
    except Exception:
        return []


def crear_backup_biblioteca():
    """
    Copia de seguridad de biblioteca.db, con el mismo historial rotativo
    (últimas _MAX_BACKUPS) que proyectos.json — pero solo si biblioteca.db
    cambió de verdad desde la última copia (importar/editar/borrar libros,
    categorías o etiquetas), no en cada arranque de la pestaña Biblioteca.
    """
    _migrar_carpeta_antigua_si_hace_falta()
    ruta_db = ruta_config("biblioteca.db")
    if not os.path.exists(ruta_db):
        return
    if not _hay_cambios_desde_ultimo_backup(ruta_db, _DIR_BACKUPS_BIBLIOTECA, "biblioteca_"):
        return
    try:
        nombre_zip = _crear_backup(ruta_db, _DIR_BACKUPS_BIBLIOTECA, "biblioteca_", "biblioteca.db")
        logger.info("[Backups] Copia de biblioteca.db creada: %s", nombre_zip)
    except Exception:
        logger.exception("[Backups] Error al crear copia de seguridad de biblioteca.db")
# ANCLAJE_FIN: GESTOR_BACKUPS
