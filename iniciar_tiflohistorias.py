import logging
import sys
import os
import wx

# Asegurar que la carpeta de registros existe
os.makedirs('registros', exist_ok=True)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('registros', 'app.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configurar rutas para encontrar el paquete 'app'
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# IMPORTACIÓN ACTUALIZADA
try:
    from app.interfaz.ventana_principal import VentanaPrincipal
except ImportError as e:
    logger.critical(f"Error al importar la interfaz: {e}")
    sys.exit(1)

class TifloApp(wx.App):
    """Aplicación principal de TifloHistorias."""
    
    def OnInit(self):
        """Inicializa la aplicación."""
        try:
            logger.info("Iniciando TifloHistorias")
            # CORRECCIÓN: Usamos 'titulo' en lugar de 'title'
            self.frame = VentanaPrincipal(None, titulo="Tiflo Historias")
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