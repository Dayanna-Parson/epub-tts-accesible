"""
Compila los archivos .po de locale/*/LC_MESSAGES/*.po a su .mo binario
correspondiente, sin depender de gettext ni msgfmt instalados en el
sistema. Reimplementa el formato .mo (mismo algoritmo que la herramienta
msgfmt.py de CPython) usando únicamente la librería estándar de Python.

Uso:
    python herramientas/compilar_i18n.py

Recompila todos los .po encontrados bajo locale/. Pensado para que
cualquier colaborador pueda probar una traducción en local sin instalar
gettext para Windows.
"""
import array
import glob
import logging
import os
import struct
import sys

logger = logging.getLogger(__name__)

RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA_LOCALE = os.path.join(RAIZ_PROYECTO, "locale")


def _parsear_po(ruta_po: str) -> dict:
    """
    Parser mínimo de archivos .po: extrae los pares msgid/msgstr como un
    diccionario {msgid: msgstr}. Soporta cadenas multilínea y comentarios,
    que es lo único que producen Poedit y la edición manual descritas en
    docs/TRADUCCION.md.
    """
    mensajes = {}
    msgid_actual = []
    msgstr_actual = []
    en_msgid = False
    en_msgstr = False

    def _volcar():
        msgid_texto = "".join(msgid_actual)
        msgstr_texto = "".join(msgstr_actual)
        if msgid_texto or msgstr_texto:
            mensajes[msgid_texto] = msgstr_texto

    with open(ruta_po, encoding="utf-8") as archivo:
        for linea in archivo:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            if linea.startswith("msgid "):
                _volcar()
                msgid_actual = [_extraer_cadena(linea[len("msgid "):])]
                msgstr_actual = []
                en_msgid, en_msgstr = True, False
            elif linea.startswith("msgstr "):
                msgstr_actual = [_extraer_cadena(linea[len("msgstr "):])]
                en_msgid, en_msgstr = False, True
            elif linea.startswith('"'):
                fragmento = _extraer_cadena(linea)
                if en_msgstr:
                    msgstr_actual.append(fragmento)
                elif en_msgid:
                    msgid_actual.append(fragmento)
        _volcar()

    # La entrada de cabecera (msgid vacío) no se traduce como texto de
    # interfaz, pero sí debe ir en el .mo: gettext la usa para metadatos.
    return mensajes


def _extraer_cadena(fragmento: str) -> str:
    fragmento = fragmento.strip()
    if fragmento.startswith('"') and fragmento.endswith('"'):
        fragmento = fragmento[1:-1]
    return (
        fragmento.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


def _generar_mo(mensajes: dict) -> bytes:
    """
    Serializa el diccionario de mensajes al formato binario .mo, siguiendo
    el mismo layout que produce msgfmt.py de la librería de herramientas
    de CPython (cabecera + tablas de índices + bloque de cadenas).
    """
    # Las entradas sin traducir (msgstr vacío) se excluyen del .mo para que
    # gettext caiga de vuelta al propio msgid, en vez de devolver una
    # cadena vacía — así el .po en español puede dejarse sin msgstr y el
    # texto en español original (el msgid) sigue mostrándose tal cual.
    # La entrada de cabecera (msgid "") se conserva siempre.
    claves = sorted(
        clave for clave, valor in mensajes.items() if clave == "" or valor
    )
    offsets = []
    ids = b""
    strs = b""
    for clave in claves:
        valor = mensajes[clave]
        offsets.append((len(ids), len(clave.encode("utf-8")),
                        len(strs), len(valor.encode("utf-8"))))
        ids += clave.encode("utf-8") + b"\0"
        strs += valor.encode("utf-8") + b"\0"

    cabecera_len = 7 * 4
    tam_tabla_originales = len(claves) * 8
    tam_tabla_traducidas = len(claves) * 8

    inicio_ids = cabecera_len + tam_tabla_originales + tam_tabla_traducidas
    inicio_strs = inicio_ids + len(ids)

    tabla_originales = array.array("i")
    tabla_traducidas = array.array("i")
    for desplazamiento_id, longitud_id, desplazamiento_str, longitud_str in offsets:
        tabla_originales.append(longitud_id)
        tabla_originales.append(inicio_ids + desplazamiento_id)
        tabla_traducidas.append(longitud_str)
        tabla_traducidas.append(inicio_strs + desplazamiento_str)

    salida = struct.pack(
        "Iiiiiii",
        0x950412DE,          # número mágico
        0,                   # versión
        len(claves),         # número de cadenas
        cabecera_len,        # desplazamiento tabla de originales
        cabecera_len + tam_tabla_originales,  # desplazamiento tabla de traducidas
        0, 0,                # tamaño y desplazamiento de tabla hash (sin usar)
    )
    salida += tabla_originales.tobytes()
    salida += tabla_traducidas.tobytes()
    salida += ids
    salida += strs
    return salida


def compilar_archivo(ruta_po: str) -> str:
    mensajes = _parsear_po(ruta_po)
    contenido_mo = _generar_mo(mensajes)
    ruta_mo = os.path.splitext(ruta_po)[0] + ".mo"
    with open(ruta_mo, "wb") as archivo:
        archivo.write(contenido_mo)
    return ruta_mo


def compilar_todos() -> list:
    rutas_po = sorted(glob.glob(os.path.join(CARPETA_LOCALE, "*", "LC_MESSAGES", "*.po")))
    rutas_mo = []
    for ruta_po in rutas_po:
        ruta_mo = compilar_archivo(ruta_po)
        rutas_mo.append(ruta_mo)
        print(f"Compilado: {os.path.relpath(ruta_po, RAIZ_PROYECTO)} -> {os.path.relpath(ruta_mo, RAIZ_PROYECTO)}")
    return rutas_mo


if __name__ == "__main__":
    if not os.path.isdir(CARPETA_LOCALE):
        print(f"No existe la carpeta locale/ en {RAIZ_PROYECTO}")
        sys.exit(1)
    rutas = compilar_todos()
    if not rutas:
        print("No se encontró ningún archivo .po bajo locale/.")
    else:
        print(f"\n{len(rutas)} archivo(s) .mo generado(s) correctamente.")
