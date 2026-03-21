"""
Gestor de atajos de teclado.

Usa dos archivos JSON separados (patrón VS Code):
  - teclas_predeterminadas.json  → Defaults de fábrica. NUNCA se modifica.
  - teclas_usuario.json          → Solo almacena los overrides del usuario.

Al cargar se fusionan ambos: el usuario puede sobrescribir cualquier default,
y restaurar todo borrando/vaciando teclas_usuario.json (restablecer_todos).
"""
import json
import os
from app.config_rutas import ruta_config

_RUTA_DEFAULTS = ruta_config("teclas_predeterminadas.json")
_RUTA_USUARIO = ruta_config("teclas_usuario.json")

# Atajos de fábrica embebidos en el código.
# Se escriben a teclas_predeterminadas.json si el archivo no existe o está vacío,
# garantizando que PanelAtajos siempre tenga la tabla poblada.
_DEFAULTS_EMBEBIDOS = {
    "reproducir_pausar": {
        "descripcion": "Reproducir / Pausar",
        "modificador": "Ctrl",
        "tecla": "P",
    },
    "detener": {
        "descripcion": "Detener lectura",
        "modificador": "Ctrl",
        "tecla": "D",
    },
    "buscar": {
        "descripcion": "Buscar en el texto",
        "modificador": "Ctrl",
        "tecla": "F",
    },
    "marcadores": {
        "descripcion": "Gestor de marcadores",
        "modificador": "Ctrl",
        "tecla": "M",
    },
    "ir_porcentaje": {
        "descripcion": "Ir a porcentaje del libro",
        "modificador": "Ctrl",
        "tecla": "G",
    },
}


def _asegurar_defaults():
    """Escribe _DEFAULTS_EMBEBIDOS en disco si el archivo no existe o está vacío."""
    if os.path.exists(_RUTA_DEFAULTS):
        try:
            with open(_RUTA_DEFAULTS, 'r', encoding='utf-8') as f:
                contenido = f.read().strip()
            if contenido and json.loads(contenido):
                return
        except Exception:
            pass
    os.makedirs(os.path.dirname(_RUTA_DEFAULTS), exist_ok=True)
    with open(_RUTA_DEFAULTS, 'w', encoding='utf-8') as f:
        json.dump(_DEFAULTS_EMBEBIDOS, f, ensure_ascii=False, indent=4)


def cargar_atajos():
    """
    Devuelve el diccionario fusionado: defaults + overrides del usuario.
    Cada entrada tiene: descripcion, modificador, tecla.
    """
    _asegurar_defaults()
    try:
        with open(_RUTA_DEFAULTS, 'r', encoding='utf-8') as f:
            defaults = json.load(f)
    except Exception:
        defaults = dict(_DEFAULTS_EMBEBIDOS)

    usuario = {}
    if os.path.exists(_RUTA_USUARIO):
        try:
            with open(_RUTA_USUARIO, 'r', encoding='utf-8') as f:
                usuario = json.load(f)
        except Exception:
            usuario = {}

    resultado = {}
    for clave, entrada_def in defaults.items():
        entrada = dict(entrada_def)
        if clave in usuario:
            override = usuario[clave]
            entrada["modificador"] = override.get("modificador", entrada["modificador"])
            entrada["tecla"] = override.get("tecla", entrada["tecla"])
        resultado[clave] = entrada
    return resultado


def cargar_defaults():
    """Devuelve solo los atajos predeterminados de fábrica."""
    _asegurar_defaults()
    try:
        with open(_RUTA_DEFAULTS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULTS_EMBEBIDOS)


def guardar_atajo_usuario(clave, modificador, tecla):
    """Guarda o actualiza un override de usuario en teclas_usuario.json."""
    usuario = {}
    if os.path.exists(_RUTA_USUARIO):
        try:
            with open(_RUTA_USUARIO, 'r', encoding='utf-8') as f:
                usuario = json.load(f)
        except Exception:
            usuario = {}

    usuario[clave] = {"modificador": modificador, "tecla": tecla}
    os.makedirs(os.path.dirname(_RUTA_USUARIO), exist_ok=True)
    with open(_RUTA_USUARIO, 'w', encoding='utf-8') as f:
        json.dump(usuario, f, indent=4, ensure_ascii=False)


def eliminar_atajo_usuario(clave):
    """Elimina el override de usuario para un atajo, restaurando el default."""
    if not os.path.exists(_RUTA_USUARIO):
        return
    try:
        with open(_RUTA_USUARIO, 'r', encoding='utf-8') as f:
            usuario = json.load(f)
        if clave in usuario:
            del usuario[clave]
            with open(_RUTA_USUARIO, 'w', encoding='utf-8') as f:
                json.dump(usuario, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def restablecer_todos():
    """Borra teclas_usuario.json, restaurando todos los atajos a sus defaults."""
    if os.path.exists(_RUTA_USUARIO):
        os.remove(_RUTA_USUARIO)


def texto_atajo(entrada):
    """Convierte {'modificador': 'Ctrl', 'tecla': 'P'} → 'Ctrl+P'."""
    mod = entrada.get("modificador", "").strip()
    tecla = entrada.get("tecla", "").strip()
    if mod and tecla:
        return f"{mod}+{tecla}"
    return tecla or mod or "(sin asignar)"
