"""
Gestor de perfiles de usuario.

Un perfil guarda la combinación de voz favorita (por proveedor y la voz
activa concreta), velocidad, volumen y las preferencias de pausa/tiempos
que hoy vivían sueltas en ajustes.json. Sirve para que distintas personas
que comparten el mismo equipo, o una misma persona que alterna entre tipos
de lectura (novela, técnico, idioma extranjero), no tengan que reconfigurar
la app cada vez.

No guarda claves API ni límites de cuota: eso es global de la aplicación,
no de la persona ni del tipo de lectura.

Persistencia en configuraciones/perfiles.json, con escritura atómica
(archivo temporal + os.replace) para no dejar el archivo a medias si la
app se cierra en mitad de un guardado.
"""
import json
import logging
import os

from app.config_rutas import ruta_config, CONFIG_DIR

logger = logging.getLogger(__name__)

_RUTA_PERFILES = ruta_config("perfiles.json")

# ANCLAJE_INICIO: ESTRUCTURA_PERFIL_DEFECTO
# Plantilla de un perfil recién creado. voces_favoritas es un diccionario
# proveedor_id -> id_voz; voz_activa es la última voz seleccionada en
# Lectura en el momento de guardar el perfil (proveedor_id + id_voz).
_PERFIL_VACIO = {
    "voz_activa": {"proveedor_id": "", "id_voz": ""},
    "voces_favoritas": {},
    "velocidad": 50,
    "volumen": 100,
    "segundos_salto": 10,
    "pausa_entre_fragmentos_ms": 0,
}
# ANCLAJE_FIN: ESTRUCTURA_PERFIL_DEFECTO


def _estructura_vacia():
    return {"perfiles": {}, "perfil_activo": None}


# ANCLAJE_INICIO: CARGA_Y_GUARDADO_PERFILES
def cargar_perfiles() -> dict:
    """
    Devuelve la estructura completa {"perfiles": {...}, "perfil_activo": ...}.
    Si el archivo no existe o está corrupto, devuelve la estructura vacía
    por defecto sin lanzar excepción — fallo seguro para primer arranque.
    """
    if not os.path.exists(_RUTA_PERFILES):
        return _estructura_vacia()
    try:
        with open(_RUTA_PERFILES, "r", encoding="utf-8") as f:
            contenido = f.read().strip()
        if not contenido:
            return _estructura_vacia()
        datos = json.loads(contenido)
        datos.setdefault("perfiles", {})
        datos.setdefault("perfil_activo", None)
        return datos
    except Exception:
        logger.exception("Error al leer perfiles.json")
        return _estructura_vacia()


def _guardar(datos: dict):
    """Escritura atómica: primero a un archivo temporal, luego renombrado."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    ruta_tmp = _RUTA_PERFILES + ".tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta_tmp, _RUTA_PERFILES)
# ANCLAJE_FIN: CARGA_Y_GUARDADO_PERFILES


# ANCLAJE_INICIO: CRUD_PERFILES
def nombres_perfiles() -> list:
    """Lista de nombres de perfiles existentes, en el orden en que se crearon."""
    return list(cargar_perfiles()["perfiles"].keys())


def existe_perfil(nombre: str) -> bool:
    return nombre in cargar_perfiles()["perfiles"]


def crear_perfil(nombre: str, datos_perfil: dict = None) -> bool:
    """
    Crea un perfil nuevo con el nombre indicado. Si datos_perfil es None,
    se crea con la plantilla vacía. Devuelve False si el nombre está
    vacío o ya existe (no sobrescribe perfiles existentes).
    """
    nombre = nombre.strip()
    if not nombre:
        return False
    datos = cargar_perfiles()
    if nombre in datos["perfiles"]:
        return False
    datos["perfiles"][nombre] = dict(datos_perfil) if datos_perfil else dict(_PERFIL_VACIO)
    if datos["perfil_activo"] is None:
        datos["perfil_activo"] = nombre
    try:
        _guardar(datos)
        return True
    except Exception:
        logger.exception("Error al crear el perfil '%s'", nombre)
        return False


def renombrar_perfil(nombre_actual: str, nombre_nuevo: str) -> bool:
    """
    Renombra un perfil existente. Devuelve False si el perfil de origen no
    existe, el nombre nuevo está vacío o ya está en uso por otro perfil.
    """
    nombre_nuevo = nombre_nuevo.strip()
    if not nombre_nuevo:
        return False
    datos = cargar_perfiles()
    if nombre_actual not in datos["perfiles"] or nombre_nuevo in datos["perfiles"]:
        return False
    datos["perfiles"][nombre_nuevo] = datos["perfiles"].pop(nombre_actual)
    if datos["perfil_activo"] == nombre_actual:
        datos["perfil_activo"] = nombre_nuevo
    try:
        _guardar(datos)
        return True
    except Exception:
        logger.exception("Error al renombrar el perfil '%s' a '%s'", nombre_actual, nombre_nuevo)
        return False


def eliminar_perfil(nombre: str) -> bool:
    """
    Elimina el perfil indicado. Si era el perfil activo, el activo pasa a
    ser otro perfil restante (el primero de la lista) o None si no queda
    ninguno. Devuelve False si el perfil no existe.
    """
    datos = cargar_perfiles()
    if nombre not in datos["perfiles"]:
        return False
    del datos["perfiles"][nombre]
    if datos["perfil_activo"] == nombre:
        restantes = list(datos["perfiles"].keys())
        datos["perfil_activo"] = restantes[0] if restantes else None
    try:
        _guardar(datos)
        return True
    except Exception:
        logger.exception("Error al eliminar el perfil '%s'", nombre)
        return False
# ANCLAJE_FIN: CRUD_PERFILES


# ANCLAJE_INICIO: ESTADO_Y_ALTERNANCIA_PERFILES
def obtener_perfil_activo():
    """Devuelve (nombre, datos_del_perfil) del perfil activo, o (None, None) si no hay ninguno."""
    datos = cargar_perfiles()
    nombre = datos["perfil_activo"]
    if nombre is None or nombre not in datos["perfiles"]:
        return None, None
    return nombre, datos["perfiles"][nombre]


def fijar_perfil_activo(nombre: str) -> bool:
    """Marca el perfil indicado como activo. Devuelve False si no existe."""
    datos = cargar_perfiles()
    if nombre not in datos["perfiles"]:
        return False
    datos["perfil_activo"] = nombre
    try:
        _guardar(datos)
        return True
    except Exception:
        logger.exception("Error al fijar el perfil activo '%s'", nombre)
        return False


def siguiente_perfil() -> str:
    """
    Calcula el nombre del perfil siguiente al activo, en orden circular,
    para el atajo de alternancia rápida (Ctrl+Shift+P). Devuelve cadena
    vacía si no hay ningún perfil creado.
    """
    datos = cargar_perfiles()
    nombres = list(datos["perfiles"].keys())
    if not nombres:
        return ""
    if len(nombres) == 1 or datos["perfil_activo"] not in nombres:
        return nombres[0]
    indice_actual = nombres.index(datos["perfil_activo"])
    return nombres[(indice_actual + 1) % len(nombres)]


def guardar_estado_en_perfil(nombre: str, voz_activa: dict, voces_favoritas: dict,
                              velocidad: int, volumen: int, segundos_salto: int,
                              pausa_entre_fragmentos_ms: int) -> bool:
    """
    Sobrescribe el contenido de un perfil existente con el estado actual de
    la interfaz (voz, velocidad, volumen y preferencias de pausa/tiempos).
    Devuelve False si el perfil no existe.
    """
    datos = cargar_perfiles()
    if nombre not in datos["perfiles"]:
        return False
    datos["perfiles"][nombre] = {
        "voz_activa": dict(voz_activa),
        "voces_favoritas": dict(voces_favoritas),
        "velocidad": velocidad,
        "volumen": volumen,
        "segundos_salto": segundos_salto,
        "pausa_entre_fragmentos_ms": pausa_entre_fragmentos_ms,
    }
    try:
        _guardar(datos)
        return True
    except Exception:
        logger.exception("Error al guardar el estado actual en el perfil '%s'", nombre)
        return False
# ANCLAJE_FIN: ESTADO_Y_ALTERNANCIA_PERFILES
