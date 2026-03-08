import os
import json

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


def migrar_archivos_config():
    """
    Renombra archivos de configuración viejos al nuevo esquema de nombres.
    Se llama una sola vez al arranque; es seguro llamarla siempre.

    Mapa de migración:
      config_general.json  → ajustes.json
      libros_recientes.json → historial_epub.json
      datos_lectura.json   → estado_lectura.json
      ajustes_globales.json (vacío) → se elimina

    Además extrae txt_recientes de ajustes.json a historial_grabacion.json
    si todavía estuviera mezclado allí.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)

    _renombrar = [
        ("config_general.json", "ajustes.json"),
        ("libros_recientes.json", "historial_epub.json"),
        ("datos_lectura.json", "estado_lectura.json"),
    ]
    for viejo, nuevo in _renombrar:
        ruta_vieja = ruta_config(viejo)
        ruta_nueva = ruta_config(nuevo)
        if os.path.exists(ruta_vieja) and not os.path.exists(ruta_nueva):
            try:
                os.rename(ruta_vieja, ruta_nueva)
            except Exception:
                pass

    # Eliminar ajustes_globales.json si está vacío o no existe
    ruta_global = ruta_config("ajustes_globales.json")
    if os.path.exists(ruta_global):
        try:
            if os.path.getsize(ruta_global) == 0:
                os.remove(ruta_global)
            else:
                with open(ruta_global, encoding="utf-8") as f:
                    contenido = f.read().strip()
                if not contenido or contenido in ("{}", "[]"):
                    os.remove(ruta_global)
        except Exception:
            pass

    # Extraer txt_recientes de ajustes.json → historial_grabacion.json
    ruta_ajustes = ruta_config("ajustes.json")
    ruta_hist_grab = ruta_config("historial_grabacion.json")
    if os.path.exists(ruta_ajustes) and not os.path.exists(ruta_hist_grab):
        try:
            with open(ruta_ajustes, encoding="utf-8") as f:
                datos = json.load(f)
            if "txt_recientes" in datos:
                with open(ruta_hist_grab, "w", encoding="utf-8") as f:
                    json.dump(datos.pop("txt_recientes"), f, ensure_ascii=False)
                with open(ruta_ajustes, "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
