import logging
import sys
import os
import traceback
import threading
import wx
from datetime import datetime

# Directorio raíz del proyecto (donde está este archivo)
_RAIZ = os.path.dirname(os.path.abspath(__file__))

# Asegurar que la carpeta de registros existe
os.makedirs(os.path.join(_RAIZ, 'registros'), exist_ok=True)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(_RAIZ, 'registros', 'app.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- MIGRACIÓN DE ARCHIVOS DE CONFIGURACIÓN ---
# Se ejecuta antes de importar nada de la app para garantizar que los nombres
# de archivo nuevos (ajustes.json, historial_epub.json, etc.) ya existen.
try:
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from app.config_rutas import migrar_archivos_config
    migrar_archivos_config()
except Exception:
    pass

# --- ARCHIVO DE PÁNICO ---
# Captura cualquier excepción no controlada que cierre la app y la escribe en
# error_log.txt en la raíz del proyecto, para diagnóstico sin necesidad de consola.
_RUTA_PANIC_LOG = os.path.join(_RAIZ, 'error_log.txt')


def _manejador_excepcion_global(tipo, valor, traza):
    """Hook de pánico: registra el crash en error_log.txt y en el logger estándar."""
    mensaje = "".join(traceback.format_exception(tipo, valor, traza))
    logger.critical(f"CRASH NO CONTROLADO:\n{mensaje}")
    try:
        with open(_RUTA_PANIC_LOG, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n{datetime.now().isoformat()}\n{mensaje}\n")
    except Exception:
        pass
    sys.__excepthook__(tipo, valor, traza)


sys.excepthook = _manejador_excepcion_global


def _manejador_excepcion_hilo(args):
    """
    Captura excepciones no manejadas en hilos de segundo plano (daemon threads).
    Sin este hook, un crash en un hilo muere silenciosamente sin dejar rastro.
    Relevante para errores de importación (boto3) o fallos de red en síntesis.
    """
    if args.exc_type is SystemExit:
        return
    mensaje = "".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_traceback
    ))
    nombre_hilo = getattr(args.thread, 'name', 'desconocido')
    logger.error(f"EXCEPCIÓN EN HILO '{nombre_hilo}':\n{mensaje}")
    try:
        with open(_RUTA_PANIC_LOG, 'a', encoding='utf-8') as f:
            f.write(
                f"\n{'='*60}\n"
                f"HILO: {nombre_hilo}\n"
                f"{datetime.now().isoformat()}\n"
                f"{mensaje}\n"
            )
    except Exception:
        pass


threading.excepthook = _manejador_excepcion_hilo

# Configurar rutas para encontrar el paquete 'app'
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# IMPORTACIÓN ACTUALIZADA
try:
    from app.interfaz.ventana_principal import VentanaPrincipal
except ImportError as e:
    logger.critical(f"Error al importar la interfaz: {e}")
    sys.exit(1)

class TifloApp(wx.App):
    """Aplicación principal de Epub TTS."""

    def OnInit(self):
        """Inicializa la aplicación."""
        try:
            logger.info("Iniciando Epub TTS")
            # CORRECCIÓN: Usamos 'titulo' en lugar de 'title'
            self.frame = VentanaPrincipal(None, titulo="Epub TTS")
            self.frame.Show()
            return True
        except Exception as e:
            logger.exception("Error fatal en OnInit")
            wx.MessageBox(f"Error al iniciar la aplicación: {e}", "Error Fatal", wx.OK | wx.ICON_ERROR)
            return False

    def OnExceptionInMainLoop(self):
        """Maneja excepciones en el bucle principal."""
        logger.exception("Excepción no manejada en el bucle principal")
        return True

if __name__ == '__main__':
    try:
        app = TifloApp(False)
        app.MainLoop()
    except Exception as e:
        logger.exception("Error fatal al ejecutar la aplicación")
        sys.exit(1)
    finally:
        logger.info("Aplicación cerrada")