import os
import sys
import json

# ── Detección de entorno PyInstaller ─────────────────────────────────────────
# La app se empaqueta con --onedir. En ese modo:
#   sys.frozen = True
#   sys._MEIPASS = subcarpeta _internal/ (archivos Python del bundle)
#   sys.executable = ruta al propio .exe
#
# recursos/, bin/, configuraciones/ y ayuda.html viven JUNTO AL .exe,
# no dentro de _internal/. Por eso RAIZ_RECURSOS usa el directorio del exe.
#
# RAIZ_RECURSOS → donde están sonidos, iconos y otros archivos externos.
#   · Frozen: directorio del .exe  (recursos copiados por construir_app.py)
#   · Normal: raíz del proyecto (donde está app/)
#
# RAIZ → directorio donde guardar configuraciones del usuario.
#   · Frozen: carpeta del .exe  (persistente entre ejecuciones)
#   · Normal: raíz del proyecto
if getattr(sys, "frozen", False):
    RAIZ_RECURSOS = os.path.dirname(sys.executable)
    RAIZ = os.path.dirname(sys.executable)
else:
    RAIZ_RECURSOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RAIZ = RAIZ_RECURSOS

CONFIG_DIR = os.path.join(RAIZ, "configuraciones")

# Valores por defecto neutros para claves_api.json (sin secretos reales)
# ANCLAJE_INICIO: CLAVES_DEFAULT_GEMINI
_CLAVES_DEFAULT = {
    "azure":       {"key": "", "region": ""},
    "polly":       {"access_key": "", "secret_key": "", "region": ""},
    "elevenlabs":  {"api_key": ""},
    "deepgram":    {"api_key": ""},
    "gemini":      {"api_key": "", "modelo": "auto"},
}
# ANCLAJE_FIN: CLAVES_DEFAULT_GEMINI


def ruta_config(nombre_archivo):
    """
    Devuelve la ruta absoluta a un archivo dentro de la carpeta configuraciones.
    Garantiza que la ruta es correcta independientemente del directorio de trabajo
    desde el que se lanza la aplicación.
    """
    return os.path.join(CONFIG_DIR, nombre_archivo)


def cargar_claves() -> dict:
    """
    Lee configuraciones/claves_api.json y devuelve el dict con las claves.
    Si el archivo no existe o está vacío, devuelve la estructura vacía por defecto.
    Nunca lanza excepción — fallo seguro para primer arranque o repo recién clonado.
    """
    ruta = ruta_config("claves_api.json")
    try:
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read().strip()
            if contenido:
                return json.loads(contenido)
    except Exception:
        pass
    return {k: dict(v) for k, v in _CLAVES_DEFAULT.items()}


def guardar_claves(claves: dict) -> None:
    """
    Escribe el dict de claves en configuraciones/claves_api.json.
    Crea la carpeta si no existe.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    ruta = ruta_config("claves_api.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(claves, f, ensure_ascii=False, indent=2)


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

    # ── Migrar claves API de ajustes.json → claves_api.json ──────────────────
    # Si ajustes.json contenía azure/polly/elevenlabs y claves_api.json aún no
    # existe, moverlas allí para separar secretos del resto de ajustes.
    ruta_claves = ruta_config("claves_api.json")
    if not os.path.exists(ruta_claves):
        claves = {k: dict(v) for k, v in _CLAVES_DEFAULT.items()}
        if os.path.exists(ruta_ajustes):
            try:
                with open(ruta_ajustes, encoding="utf-8") as f:
                    datos_aj = json.load(f)
                for proveedor in ("azure", "polly", "elevenlabs"):
                    if proveedor in datos_aj:
                        claves[proveedor] = datos_aj.pop(proveedor)
                # Guardar ajustes.json sin las claves (si hubo cambio)
                with open(ruta_ajustes, "w", encoding="utf-8") as f:
                    json.dump(datos_aj, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        # Crear claves_api.json (vacío estructurado o con las claves migradas)
        try:
            guardar_claves(claves)
        except Exception:
            pass
