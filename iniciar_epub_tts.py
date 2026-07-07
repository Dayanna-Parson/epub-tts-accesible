import logging
import logging.handlers
import sys
import os
import traceback
import threading
import wx

# ── Directorio raíz del proyecto ─────────────────────────────────────────────
_RAIZ = os.path.dirname(os.path.abspath(__file__))

# ── Sistema de logs centralizado ─────────────────────────────────────────────
# Los registros van a <raiz>/registros/app.log (max 2 MB × 3 copias = 6 MB).
# En el portable, <raiz> es la carpeta junto al .exe → fácil de encontrar.
# En desarrollo, es la raíz del proyecto.
# Solo se escriben WARNING / ERROR / CRITICAL → el archivo tarda mucho en llenarse.
if getattr(sys, "frozen", False):
    _BASE_REGISTROS = os.path.dirname(sys.executable)
else:
    _BASE_REGISTROS = _RAIZ
_DIR_REGISTROS = os.path.join(_BASE_REGISTROS, "registros")
os.makedirs(_DIR_REGISTROS, exist_ok=True)
_RUTA_LOG = os.path.join(_DIR_REGISTROS, "app.log")

_handler_archivo = logging.handlers.RotatingFileHandler(
    _RUTA_LOG,
    maxBytes=2 * 1024 * 1024,  # 2 MB por archivo
    backupCount=3,              # app.log + app.log.1 + app.log.2 + app.log.3
    encoding="utf-8",
)
_handler_archivo.setLevel(logging.WARNING)   # archivo: solo WARNING / ERROR / CRITICAL
_handler_archivo.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
)

_handler_consola = logging.StreamHandler()
_handler_consola.setLevel(logging.WARNING)   # consola: solo WARNING / ERROR / CRITICAL
_handler_consola.setFormatter(
    logging.Formatter("%(levelname)-8s  %(name)s  %(message)s")
)


class _HandlerErrorIndividual(logging.Handler):
    """
    Además del log combinado, cada ERROR/CRITICAL se escribe también en
    su propio archivo dentro de registros/errores/, nombrado con la
    fecha y hora — para poder abrir directamente el último fallo sin
    tener que buscarlo dentro de un log largo con avisos de todo tipo
    mezclados. Se conservan como máximo los últimos 20; los más
    antiguos se borran solos.
    """

    _MAXIMO_ARCHIVOS = 20

    def __init__(self, carpeta):
        super().__init__(level=logging.ERROR)
        self._carpeta = carpeta
        os.makedirs(self._carpeta, exist_ok=True)
        self.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
        )

    def emit(self, record):
        try:
            import datetime
            marca = datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d_%H-%M-%S")
            nombre = f"{marca}_{record.levelname.lower()}.log"
            ruta = os.path.join(self._carpeta, nombre)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(self.format(record))
            self._purgar_antiguos()
        except Exception:
            pass

    def _purgar_antiguos(self):
        archivos = sorted(
            (os.path.join(self._carpeta, n) for n in os.listdir(self._carpeta)),
            key=os.path.getmtime,
        )
        for ruta_vieja in archivos[:-self._MAXIMO_ARCHIVOS]:
            try:
                os.remove(ruta_vieja)
            except OSError:
                pass


_handler_error_individual = _HandlerErrorIndividual(
    os.path.join(_DIR_REGISTROS, "errores")
)

logging.basicConfig(
    level=logging.WARNING,
    handlers=[_handler_archivo, _handler_consola, _handler_error_individual],
)

# comtypes genera líneas INFO muy ruidosas sobre su caché interna — silenciar en archivo
logging.getLogger("comtypes").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# ── Migración de archivos de configuración ────────────────────────────────────
try:
    sys.path.insert(0, _RAIZ)
    from app.config_rutas import migrar_archivos_config, RAIZ as _RAIZ_APP, CONFIG_DIR as _CONFIG_DIR
    migrar_archivos_config()
except Exception as _e:
    logging.getLogger(__name__).warning("Migración de configuración fallida: %s", _e)
    _RAIZ_APP = _RAIZ
    _CONFIG_DIR = os.path.join(_RAIZ, "configuraciones")

# ── Carpetas persistentes necesarias desde la primera ejecución ───────────────
# Se crean aquí por si el ZIP se extrajo sin preservar carpetas vacías.
for _carpeta_arranque in [
    os.path.join(_RAIZ_APP, "Grabaciones_Epub-TTS"),
    os.path.join(_CONFIG_DIR, "proyectos_backup"),
]:
    try:
        os.makedirs(_carpeta_arranque, exist_ok=True)
    except Exception as _e:
        logging.getLogger(__name__).warning("No se pudo crear carpeta de arranque %s: %s", _carpeta_arranque, _e)

# ANCLAJE_INICIO: LIMPIEZA_TEMPORALES_ARRANQUE
def _limpiar_temporales_huerfanos():
    """
    Elimina archivos temporales de audio huérfanos (prefijo tfh_) que hayan
    quedado en el directorio temp del sistema si la app se cerró de forma
    abrupta durante una grabación. Solo borra archivos con más de 7 días de
    antigüedad. No toca ningún archivo de configuración ni JSON.
    Límite adicional: si la carpeta supera 50 MB de archivos tfh_, elimina
    los más antiguos hasta bajar del umbral.
    """
    import glob
    import tempfile
    import time

    _PREFIJO       = "tfh_"
    _DIAS_MAX      = 7
    _LIMITE_BYTES  = 50 * 1024 * 1024  # 50 MB
    _EXTS          = {".mp3", ".wav"}

    dir_tmp = tempfile.gettempdir()
    ahora   = time.time()
    umbral  = ahora - _DIAS_MAX * 86400

    candidatos = []
    for ruta in glob.glob(os.path.join(dir_tmp, f"{_PREFIJO}*")):
        ext = os.path.splitext(ruta)[1].lower()
        if ext not in _EXTS:
            continue
        try:
            mtime = os.path.getmtime(ruta)
            size  = os.path.getsize(ruta)
            candidatos.append((mtime, size, ruta))
        except OSError:
            continue

    # Eliminar archivos mayores de 7 días
    for mtime, size, ruta in candidatos:
        if mtime < umbral:
            try:
                os.remove(ruta)
                logging.getLogger(__name__).debug(
                    "Temporal huérfano eliminado (>7 días): %s", ruta
                )
            except OSError:
                pass

    # Si la carpeta sigue superando el límite, eliminar los más antiguos
    candidatos = [(m, s, r) for m, s, r in candidatos if os.path.exists(r)]
    total = sum(s for _, s, _ in candidatos)
    if total > _LIMITE_BYTES:
        candidatos.sort()  # más antiguos primero
        for mtime, size, ruta in candidatos:
            if total <= _LIMITE_BYTES:
                break
            try:
                os.remove(ruta)
                total -= size
                logging.getLogger(__name__).debug(
                    "Temporal huérfano eliminado (límite 50 MB): %s", ruta
                )
            except OSError:
                pass

try:
    _limpiar_temporales_huerfanos()
except Exception as _e:
    logging.getLogger(__name__).warning("Limpieza de temporales fallida: %s", _e)
# ANCLAJE_FIN: LIMPIEZA_TEMPORALES_ARRANQUE

# ── Hooks de pánico ──────────────────────────────────────────────────────────
# Capturan cualquier excepción no controlada (hilo principal y threads de fondo)
# y escriben el traceback completo en registros/app.log (raíz del proyecto,
# no dentro de app/ — ver _RUTA_LOG más arriba).

def _manejador_excepcion_global(tipo, valor, traza):
    """Excepción no capturada en el hilo principal."""
    mensaje = "".join(traceback.format_exception(tipo, valor, traza))
    logger.critical("CRASH NO CONTROLADO:\n%s", mensaje)
    sys.__excepthook__(tipo, valor, traza)


def _manejador_excepcion_hilo(args):
    """Excepción no capturada en un hilo de fondo (threading.excepthook)."""
    if args.exc_type is SystemExit:
        return
    mensaje = "".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_traceback
    ))
    nombre_hilo = getattr(args.thread, "name", "desconocido")
    logger.error("EXCEPCIÓN EN HILO '%s':\n%s", nombre_hilo, mensaje)


sys.excepthook        = _manejador_excepcion_global
threading.excepthook  = _manejador_excepcion_hilo

# ── Importación de la ventana principal ───────────────────────────────────────
try:
    from app.interfaz.ventana_principal import VentanaPrincipal
except ImportError as e:
    logger.critical("Error al importar la interfaz: %s", e)
    sys.exit(1)


# ── Aplicación wx ─────────────────────────────────────────────────────────────

class EpubTTSApp(wx.App):
    """Aplicación principal de Epub-TTS."""

    def OnInit(self):
        try:
            self.frame = VentanaPrincipal(None, titulo="Epub-TTS")
            return True
        except Exception as e:
            logger.exception("Error fatal en OnInit")
            wx.MessageBox(
                f"Error al iniciar la aplicación:\n{e}",
                "Error Fatal", wx.OK | wx.ICON_ERROR,
            )
            return False

    def OnExceptionInMainLoop(self):
        logger.exception("Excepción en el bucle principal de wx")
        return True


if __name__ == "__main__":
    try:
        app = EpubTTSApp(False)
        app.MainLoop()
    except Exception:
        logger.exception("Error fatal al ejecutar la aplicación")
        sys.exit(1)
    finally:
        pass
