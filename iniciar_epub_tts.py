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
# Todos los registros van a app/registros/app.log (max 2 MB × 3 copias = 6 MB total).
# Solo se escriben WARNING / ERROR / CRITICAL → el archivo tarda mucho en llenarse.
# Error_log.txt y error_tiflo.log ya no se usan.
_DIR_REGISTROS = os.path.join(_RAIZ, "app", "registros")
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
_handler_consola.setLevel(logging.INFO)      # consola: INFO y superiores (útil en desarrollo)
_handler_consola.setFormatter(
    logging.Formatter("%(levelname)-8s  %(name)s  %(message)s")
)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_handler_archivo, _handler_consola],
)

# comtypes genera líneas INFO muy ruidosas sobre su caché interna — silenciar en archivo
logging.getLogger("comtypes").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)
logger.info("Epub-TTS arrancando. Errores → %s", _RUTA_LOG)

# ── Migración de archivos de configuración ────────────────────────────────────
try:
    sys.path.insert(0, _RAIZ)
    from app.config_rutas import migrar_archivos_config
    migrar_archivos_config()
except Exception as _e:
    logging.getLogger(__name__).warning("Migración de configuración fallida: %s", _e)

# ── Hooks de pánico ──────────────────────────────────────────────────────────
# Capturan cualquier excepción no controlada (hilo principal y threads de fondo)
# y escriben el traceback completo en app/registros/app.log.

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
            logger.info("Iniciando ventana principal")
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
        logger.info("Epub-TTS cerrado")   # solo consola, no llega al archivo
