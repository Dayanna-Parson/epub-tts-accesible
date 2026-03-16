import os
import sys
import json

# ── Brújula de rutas ──────────────────────────────────────────────────────────
#
# La app puede ejecutarse de tres formas:
#
#   1. Script Python normal  (python iniciar_epub_tts.py)
#      __file__ es conocido → RUTA_BASE = carpeta que contiene app/
#
#   2. Ejecutable PyInstaller --onedir  (EpubTTS.exe en su carpeta)
#      sys.frozen = True
#      sys.executable  = C:\...\EpubTTS\EpubTTS.exe
#      sys._MEIPASS    = C:\...\EpubTTS\_internal\   ← aquí van sonidos/iconos
#      RUTA_BASE       = C:\...\EpubTTS\             ← aquí van configs/grabaciones
#
#   3. Ejecutable PyInstaller --onefile  (archivo único, desaconsejado)
#      sys.frozen = True
#      sys.executable  = C:\...\EpubTTS.exe
#      sys._MEIPASS    = C:\Temp\_MEIxxxxx\          ← carpeta temporal efímera
#      RUTA_BASE       = C:\...\                     ← carpeta del .exe
#
# RUTA_BASE    → raíz permanente del usuario (configs, grabaciones, bin).
#                Nunca es una carpeta temporal.
# RUTA_RECURSOS → donde están los archivos del bundle (sonidos, iconos, version.json).
#                Frozen: sys._MEIPASS  |  Normal: igual que RUTA_BASE

if getattr(sys, "frozen", False):
    # --onedir: EpubTTS.exe está en la raíz de instalación; _internal/ contiene
    # los recursos empaquetados (iconos, sonidos). Los datos del usuario nunca
    # van dentro de _internal/ para que el directorio sea completamente portable.
    RUTA_BASE     = os.path.dirname(sys.executable)   # .../EpubTTS/
    RUTA_RECURSOS = sys._MEIPASS                       # .../EpubTTS/_internal/
else:
    RUTA_BASE     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RUTA_RECURSOS = RUTA_BASE

# ── Carpetas principales ──────────────────────────────────────────────────────
# Datos de usuario: cuelgan de RUTA_BASE (al lado del .exe, nunca en _internal)
CARPETA_CONFIG      = os.path.join(RUTA_BASE,     "configuraciones")
CARPETA_PROYECTOS   = os.path.join(RUTA_BASE,     "proyectos")
CARPETA_GRABACIONES = os.path.join(RUTA_BASE,     "Grabaciones_Epub-TTS")
CARPETA_CACHE       = os.path.join(RUTA_BASE,     "cache")
CARPETA_BIN         = os.path.join(RUTA_BASE,     "bin")

# Recursos del bundle: cuelgan de RUTA_RECURSOS (_internal/ en modo frozen)
CARPETA_SONIDOS     = os.path.join(RUTA_RECURSOS, "recursos", "sonidos")
CARPETA_ICONOS      = os.path.join(RUTA_RECURSOS, "recursos", "iconos")

# ── Autocreación de carpetas de usuario ───────────────────────────────────────
# Se ejecuta una sola vez al importar el módulo. Garantiza que las carpetas
# existan en la raíz del ejecutable incluso en la primera ejecución.
for _carpeta in (CARPETA_CONFIG, CARPETA_PROYECTOS, CARPETA_GRABACIONES, CARPETA_CACHE):
    os.makedirs(_carpeta, exist_ok=True)

# ── Aliases de compatibilidad ─────────────────────────────────────────────────
# Los módulos existentes importan RAIZ, RAIZ_RECURSOS y CONFIG_DIR directamente.
RAIZ          = RUTA_BASE
RAIZ_RECURSOS = RUTA_RECURSOS
CONFIG_DIR    = CARPETA_CONFIG

# ── Valores por defecto para claves_api.json (sin secretos reales) ────────────
_CLAVES_DEFAULT = {
    "azure":       {"key": "", "region": ""},
    "polly":       {"access_key": "", "secret_key": "", "region": ""},
    "elevenlabs":  {"api_key": ""},
}


# ── Helpers de rutas ──────────────────────────────────────────────────────────

def ruta_config(nombre_archivo: str) -> str:
    """Ruta absoluta a un archivo dentro de configuraciones/."""
    return os.path.join(CARPETA_CONFIG, nombre_archivo)


# ── Claves API ────────────────────────────────────────────────────────────────

def cargar_claves() -> dict:
    """
    Lee configuraciones/claves_api.json.
    Devuelve estructura vacía si el archivo no existe o está corrupto.
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
    """Escribe claves en configuraciones/claves_api.json. Crea la carpeta si falta."""
    os.makedirs(CARPETA_CONFIG, exist_ok=True)
    with open(ruta_config("claves_api.json"), "w", encoding="utf-8") as f:
        json.dump(claves, f, ensure_ascii=False, indent=2)


# ── Migración de archivos heredados ──────────────────────────────────────────

def migrar_archivos_config():
    """
    Renombra archivos de configuración viejos al nuevo esquema de nombres.
    Se llama una sola vez al arranque; es seguro llamarla siempre.

    Mapa de migración:
      config_general.json   → ajustes.json
      libros_recientes.json → historial_epub.json
      datos_lectura.json    → estado_lectura.json
      ajustes_globales.json (vacío) → se elimina

    Además extrae txt_recientes de ajustes.json a historial_grabacion.json
    si todavía estuviera mezclado allí, y migra claves API al archivo separado.
    """
    os.makedirs(CARPETA_CONFIG, exist_ok=True)

    _renombrar = [
        ("config_general.json",   "ajustes.json"),
        ("libros_recientes.json", "historial_epub.json"),
        ("datos_lectura.json",    "estado_lectura.json"),
    ]
    for viejo, nuevo in _renombrar:
        ruta_vieja = ruta_config(viejo)
        ruta_nueva = ruta_config(nuevo)
        if os.path.exists(ruta_vieja) and not os.path.exists(ruta_nueva):
            try:
                os.rename(ruta_vieja, ruta_nueva)
            except Exception:
                pass

    # Eliminar ajustes_globales.json si está vacío
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
    ruta_ajustes   = ruta_config("ajustes.json")
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

    # Migrar claves API de ajustes.json → claves_api.json
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
                with open(ruta_ajustes, "w", encoding="utf-8") as f:
                    json.dump(datos_aj, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        try:
            guardar_claves(claves)
        except Exception:
            pass
