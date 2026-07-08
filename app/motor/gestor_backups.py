# ANCLAJE_INICIO: GESTOR_BACKUPS
import datetime
import logging
import os
import zipfile

from app.config_rutas import ruta_config

logger = logging.getLogger(__name__)

# Usa la misma carpeta que iniciar_epub_tts.py y crear_portable.py ya
# pre-crean dentro de configuraciones/ — antes se escribía en RAIZ/backups/,
# una carpeta distinta a la que el arranque preparaba (configuraciones/
# proyectos_backup/), que por eso quedaba siempre vacía.
_DIR_BACKUPS = ruta_config("proyectos_backup")
_MAX_BACKUPS = 5


def crear_backup_proyectos():
    """
    Crea un archivo .zip con el contenido actual de proyectos.json
    y lo guarda en /backups/proyectos_YYYYMMDD_HHMMSS.zip.

    Mantiene un historial rotativo de las últimas _MAX_BACKUPS copias:
    cuando se supera ese límite, los archivos más antiguos se eliminan.
    Si proyectos.json no existe, la función retorna sin hacer nada.
    """
    ruta_proyectos = ruta_config("proyectos.json")
    if not os.path.exists(ruta_proyectos):
        return

    try:
        os.makedirs(_DIR_BACKUPS, exist_ok=True)
        marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_zip = f"proyectos_{marca}.zip"
        ruta_zip = os.path.join(_DIR_BACKUPS, nombre_zip)
        ruta_tmp = ruta_zip + ".tmp"

        with zipfile.ZipFile(ruta_tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(ruta_proyectos, arcname="proyectos.json")

        os.replace(ruta_tmp, ruta_zip)
        _rotar_backups_antiguos()
        logger.info("[Backups] Copia creada: %s", nombre_zip)

    except Exception:
        logger.exception("[Backups] Error al crear copia de seguridad")


def _rotar_backups_antiguos():
    """Elimina los backups que superen el límite de _MAX_BACKUPS."""
    try:
        archivos = sorted(
            f for f in os.listdir(_DIR_BACKUPS)
            if f.startswith("proyectos_") and f.endswith(".zip")
        )
        while len(archivos) > _MAX_BACKUPS:
            os.remove(os.path.join(_DIR_BACKUPS, archivos.pop(0)))
    except Exception:
        logger.exception("[Backups] Error al rotar backups antiguos")


def listar_backups() -> list:
    """
    Devuelve los nombres de los archivos de backup ordenados
    del más reciente al más antiguo.
    """
    try:
        if not os.path.exists(_DIR_BACKUPS):
            return []
        return sorted(
            (f for f in os.listdir(_DIR_BACKUPS)
             if f.startswith("proyectos_") and f.endswith(".zip")),
            reverse=True,
        )
    except Exception:
        return []


def crear_backup_biblioteca():
    """
    Copia de seguridad de biblioteca.db, con el mismo historial rotativo
    (últimas _MAX_BACKUPS) que ya usan los proyectos. A diferencia de
    proyectos.json (que se respalda en cada guardar() por ser pequeño),
    esta se llama solo una vez por sesión, al arrancar la pestaña
    Biblioteca — con cientos o miles de libros, comprimir la base de
    datos entera en cada escritura individual (cada libro añadido, cada
    cambio de estado...) sería demasiado costoso.
    """
    ruta_db = ruta_config("biblioteca.db")
    if not os.path.exists(ruta_db):
        return

    try:
        os.makedirs(_DIR_BACKUPS, exist_ok=True)
        marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_zip = f"biblioteca_{marca}.zip"
        ruta_zip = os.path.join(_DIR_BACKUPS, nombre_zip)
        ruta_tmp = ruta_zip + ".tmp"

        with zipfile.ZipFile(ruta_tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(ruta_db, arcname="biblioteca.db")

        os.replace(ruta_tmp, ruta_zip)
        _rotar_backups_antiguos_biblioteca()
        logger.info("[Backups] Copia de biblioteca.db creada: %s", nombre_zip)

    except Exception:
        logger.exception("[Backups] Error al crear copia de seguridad de biblioteca.db")


def _rotar_backups_antiguos_biblioteca():
    try:
        archivos = sorted(
            f for f in os.listdir(_DIR_BACKUPS)
            if f.startswith("biblioteca_") and f.endswith(".zip")
        )
        while len(archivos) > _MAX_BACKUPS:
            os.remove(os.path.join(_DIR_BACKUPS, archivos.pop(0)))
    except Exception:
        logger.exception("[Backups] Error al rotar backups antiguos de biblioteca.db")
# ANCLAJE_FIN: GESTOR_BACKUPS
