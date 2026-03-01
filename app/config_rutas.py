import os

# Directorio raíz del proyecto: un nivel por encima del paquete app/
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(RAIZ, "configuraciones")


def ruta_config(nombre_archivo):
    """
    Devuelve la ruta absoluta a un archivo dentro de la carpeta configuraciones.
    Garantiza que la ruta es correcta independientemente del directorio de trabajo
    desde el que se lanza la aplicación.
    """
    return os.path.join(CONFIG_DIR, nombre_archivo)
