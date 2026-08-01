"""
Compila los archivos .po de locale/*/LC_MESSAGES/*.po a su .mo binario
correspondiente, sin depender de gettext ni msgfmt instalados en el
sistema. Reimplementa el formato .mo (mismo algoritmo que la herramienta
msgfmt.py de CPython) usando únicamente la librería estándar de Python.

Uso:
    python compilar_i18n.py

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

RAIZ_PROYECTO = os.path.dirname(os.path.abspath(__file__))
CARPETA_LOCALE = os.path.join(RAIZ_PROYECTO, "locale")


class ErrorSintaxisPo(Exception):
    """
    Error de sintaxis al parsear un .po, con la ruta y el número de línea
    exactos para que quien lo lea con lector de pantalla no tenga que
    recorrer el archivo entero buscando el problema.
    """

    def __init__(self, ruta_po: str, numero_linea: int, contenido_linea: str, motivo: str):
        self.ruta_po = ruta_po
        self.numero_linea = numero_linea
        self.contenido_linea = contenido_linea
        self.motivo = motivo
        super().__init__(
            f"{ruta_po}:{numero_linea}: {motivo}\n    Línea {numero_linea}: {contenido_linea}"
        )


def _tiene_cierre_valido(fragmento: str) -> bool:
    """
    Comprueba que una cadena entre comillas ("...") esté correctamente
    cerrada: debe empezar y terminar con una comilla doble, y la comilla
    final no puede estar escapada con una barra invertida.
    """
    if len(fragmento) < 2 or not fragmento.startswith('"') or not fragmento.endswith('"'):
        return False
    cuerpo = fragmento[1:-1]
    barras_finales = len(cuerpo) - len(cuerpo.rstrip("\\"))
    # Un número impar de barras invertidas justo antes del final significa
    # que la última comilla está escapada (\") y no cierra la cadena.
    return barras_finales % 2 == 0


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
    nonlocal_duplicados = []

    def _volcar():
        msgid_texto = "".join(msgid_actual)
        msgstr_texto = "".join(msgstr_actual)
        if msgid_texto or msgstr_texto:
            if msgid_texto in mensajes and mensajes[msgid_texto] != msgstr_texto:
                nonlocal_duplicados.append((msgid_texto, mensajes[msgid_texto], msgstr_texto))
            mensajes[msgid_texto] = msgstr_texto

    # "utf-8-sig" exige UTF-8 estricto igual que "utf-8" (lanza
    # UnicodeDecodeError ante bytes inválidos) pero además reconoce y
    # descarta el BOM que añaden por defecto el Bloc de notas de Windows y
    # algunos editores — con "utf-8" a secas ese BOM se cuela como parte
    # del primer msgid y rompe la comparación de cadenas silenciosamente.
    with open(ruta_po, encoding="utf-8-sig") as archivo:
        for numero_linea, linea_original in enumerate(archivo, start=1):
            linea = linea_original.strip()
            if not linea or linea.startswith("#"):
                continue
            if linea.startswith("msgid "):
                _volcar()
                resto = linea[len("msgid "):].strip()
                if not _tiene_cierre_valido(resto):
                    raise ErrorSintaxisPo(
                        ruta_po, numero_linea, linea_original.rstrip("\n"),
                        "cadena de msgid sin comillas de cierre",
                    )
                msgid_actual = [_extraer_cadena(resto)]
                msgstr_actual = []
                en_msgid, en_msgstr = True, False
            elif linea.startswith("msgstr "):
                resto = linea[len("msgstr "):].strip()
                if not _tiene_cierre_valido(resto):
                    raise ErrorSintaxisPo(
                        ruta_po, numero_linea, linea_original.rstrip("\n"),
                        "cadena de msgstr sin comillas de cierre",
                    )
                msgstr_actual = [_extraer_cadena(resto)]
                en_msgid, en_msgstr = False, True
            elif linea.startswith('"'):
                if not en_msgid and not en_msgstr:
                    raise ErrorSintaxisPo(
                        ruta_po, numero_linea, linea_original.rstrip("\n"),
                        "línea de continuación sin un msgid/msgstr previo",
                    )
                if not _tiene_cierre_valido(linea):
                    raise ErrorSintaxisPo(
                        ruta_po, numero_linea, linea_original.rstrip("\n"),
                        "cadena sin comillas de cierre",
                    )
                fragmento = _extraer_cadena(linea)
                if en_msgstr:
                    msgstr_actual.append(fragmento)
                else:
                    msgid_actual.append(fragmento)
            else:
                raise ErrorSintaxisPo(
                    ruta_po, numero_linea, linea_original.rstrip("\n"),
                    "línea no reconocida (se esperaba msgid, msgstr, continuación o comentario)",
                )
        _volcar()

    for msgid_texto, valor_descartado, valor_conservado in nonlocal_duplicados:
        print(
            f"AVISO: msgid duplicado en {ruta_po}: '{msgid_texto[:60]}...' "
            "— se conserva la última traducción encontrada "
            f"('{valor_descartado[:60]}' descartado, se conserva '{valor_conservado[:60]}')."
        )

    # La entrada de cabecera (msgid vacío) no se traduce como texto de
    # interfaz, pero sí debe ir en el .mo: gettext la usa para metadatos.
    return mensajes, len(nonlocal_duplicados)


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
    hubo_error = False
    for ruta_po in rutas_po:
        try:
            ruta_mo = compilar_archivo(ruta_po)
        except ErrorSintaxisPo as error:
            hubo_error = True
            print(f"ERROR de sintaxis: {error}")
            continue
        rutas_mo.append(ruta_mo)
        print(f"Compilado: {os.path.relpath(ruta_po, RAIZ_PROYECTO)} -> {os.path.relpath(ruta_mo, RAIZ_PROYECTO)}")
    if hubo_error:
        raise SystemExit(1)
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
