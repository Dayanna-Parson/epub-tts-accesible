# ANCLAJE_INICIO: AUXILIAR_SAPI32
"""
auxiliar_sapi32.py
──────────────────
Proceso auxiliar de 32 bits para voces SAPI5 de 32 bits (p. ej. Eloquence de CodeFactory).
Se comunica con la aplicación principal de 64 bits mediante líneas JSON por stdin/stdout.

Compilar con Python 32 bits + PyInstaller:
    python -m PyInstaller --noconsole --onefile --name auxiliar_sapi32 auxiliar_sapi32.py
Copiar el exe resultante a /bin/ del portable.

Protocolo de comandos (stdin, una línea JSON por comando):
    {"cmd": "listar_voces"}
    {"cmd": "cambiar_voz", "nombre": "Eloquence"}
    {"cmd": "hablar",      "texto": "...", "pos_offset": 0}
    {"cmd": "detener"}
    {"cmd": "pausar"}
    {"cmd": "reanudar"}
    {"cmd": "fijar_velocidad", "valor": 50}
    {"cmd": "fijar_volumen",   "valor": 100}
    {"cmd": "salir"}

Protocolo de eventos (stdout, una línea JSON por evento):
    {"evento": "listo"}
    {"evento": "voces",        "lista": [...]}
    {"evento": "voz_cambiada", "exito": true}
    {"evento": "progreso",     "pos": 123}
    {"evento": "completado"}
    {"evento": "error",        "msg": "..."}
"""

import json
import sys
import threading

# Constantes SAPI5
_SPF_ASYNC            = 1
_SPF_PURGEBEFORESPEAK = 2
_SPF_IS_NOT_XML       = 8

_lock_stdout = threading.Lock()


def _enviar(datos):
    """Envía un diccionario como línea JSON a stdout de forma thread-safe."""
    try:
        with _lock_stdout:
            sys.stdout.write(json.dumps(datos, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    except Exception:
        pass


def _seleccionar_voz(motor_obj, nombre_buscado, comtypes_client):
    """
    Busca `nombre_buscado` entre las voces disponibles y la activa sobre
    `motor_obj`. Función compartida por el comando "cambiar_voz" (hilo
    principal) y por cada hilo de habla, que necesita repetir la misma
    selección sobre su propia instancia local del motor (ver _hilo_parrafos).
    Devuelve True si encontró y activó la voz.
    """
    nombre_buscado = (nombre_buscado or "").lower()
    if not nombre_buscado:
        return False
    try:
        sp_cat = comtypes_client.CreateObject("SAPI.SpObjectTokenCategory")
        sp_cat.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices", False)
        tokens = sp_cat.EnumTokens()
        for i in range(tokens.Count):
            try:
                tok = tokens.Item(i)
                if nombre_buscado in tok.GetDescription().lower():
                    motor_obj.Voice = tok
                    return True
            except Exception:
                pass
    except Exception:
        pass
    try:
        tokens = motor_obj.GetVoices()
        for i in range(tokens.Count):
            try:
                tok = tokens.Item(i)
                if nombre_buscado in tok.GetDescription().lower():
                    motor_obj.Voice = tok
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _leer_categorias_sapi(motor, comtypes_client):
    """Enumera voces de las tres categorías SAPI conocidas. Devuelve lista de dicts."""
    lista = []
    ids_vistos = set()

    def _procesar_tokens(tokens):
        for i in range(tokens.Count):
            try:
                tok = tokens.Item(i)
                vid = tok.Id
                if vid in ids_vistos:
                    continue
                ids_vistos.add(vid)
                lista.append({
                    "id":          vid,
                    "nombre":      tok.GetDescription(),
                    "proveedor_id": "local_32",
                })
            except Exception:
                pass

    try:
        _procesar_tokens(motor.GetVoices())
    except Exception:
        pass

    for cat_id in (
        r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
        r"HKEY_CURRENT_USER\SOFTWARE\Microsoft\Speech_ModernVoices",
    ):
        try:
            sp_cat = comtypes_client.CreateObject("SAPI.SpObjectTokenCategory")
            sp_cat.SetId(cat_id, False)
            _procesar_tokens(sp_cat.EnumTokens())
        except Exception:
            pass

    return lista


def _hilo_parrafos(texto, pos_offset, gen, estado):
    """
    Hilo de fondo: habla párrafo a párrafo y emite eventos de progreso.

    No recibe el `motor` de main() como parámetro. Un objeto COM (SAPI.SpVoice)
    creado en un hilo queda ligado al apartamento COM de ESE hilo — SAPI es un
    objeto de apartamento simple (STA), así que un puntero creado en el hilo
    principal no se puede usar de forma fiable desde otro hilo aunque ese
    segundo hilo llame a CoInitialize(): compartir el puntero directamente
    salta el marshaling entre apartamentos y explota con
    "No se ha llamado a CoInitialize." (CO_E_NOTINITIALIZED), de forma
    intermitente según el orden de llamadas. La solución robusta es que cada
    hilo tenga su PROPIO objeto COM, creado y usado enteramente dentro de sí
    mismo — nunca compartir un puntero COM entre hilos. Este hilo crea su
    propia instancia de SAPI.SpVoice y repite aquí la voz/velocidad/volumen
    ya aplicados en el hilo principal (guardados en `estado`), en vez de
    reutilizar el `motor` de main().
    """
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    try:
        try:
            motor_local = comtypes.client.CreateObject("SAPI.SpVoice")
            motor_local.Rate = estado.get("rate", 0)
            motor_local.Volume = estado.get("volume", 100)
            if estado.get("voz_nombre"):
                _seleccionar_voz(motor_local, estado["voz_nombre"], comtypes.client)
        except Exception as e:
            _enviar({"evento": "error", "msg": f"No se pudo crear el motor de habla: {e}"})
            return

        pos = pos_offset
        for linea in texto.split("\n"):
            if estado["detener"] or estado["generacion"] != gen:
                return
            if linea.strip():
                _enviar({"evento": "progreso", "pos": pos})
                try:
                    motor_local.Speak(linea, _SPF_ASYNC | _SPF_IS_NOT_XML)
                    while not estado["detener"] and estado["generacion"] == gen:
                        if motor_local.WaitUntilDone(100):
                            break
                except Exception as e:
                    _enviar({"evento": "error", "msg": str(e)})
            pos += len(linea) + 1  # +1 por el \n que split elimina

        if not estado["detener"] and estado["generacion"] == gen:
            _enviar({"evento": "completado"})
    finally:
        comtypes.CoUninitialize()


def main():
    try:
        import comtypes.client
        motor = comtypes.client.CreateObject("SAPI.SpVoice")
        motor.Rate   = 0
        motor.Volume = 100
    except Exception as e:
        _enviar({"evento": "error", "msg": f"No se pudo inicializar SAPI5: {e}"})
        sys.exit(1)

    _enviar({"evento": "listo"})

    # Estado compartido entre el hilo principal y el de habla — solo datos
    # planos (nunca punteros COM, ver _hilo_parrafos), así que compartirlo
    # entre hilos es seguro.
    estado = {"detener": False, "generacion": 0, "rate": 0, "volume": 100, "voz_nombre": None}

    for linea_cruda in sys.stdin:
        linea_cruda = linea_cruda.strip()
        if not linea_cruda:
            continue

        try:
            cmd = json.loads(linea_cruda)
        except Exception:
            continue

        accion = cmd.get("cmd", "")

        if accion == "salir":
            break

        elif accion == "listar_voces":
            _enviar({"evento": "voces", "lista": _leer_categorias_sapi(motor, comtypes.client)})

        elif accion == "cambiar_voz":
            nombre_buscado = cmd.get("nombre", "")
            encontrada = _seleccionar_voz(motor, nombre_buscado, comtypes.client)
            # Se recuerda el nombre para que cada hilo de habla nuevo pueda
            # reaplicarlo sobre su propia instancia local del motor.
            estado["voz_nombre"] = nombre_buscado if encontrada else estado["voz_nombre"]
            _enviar({"evento": "voz_cambiada", "exito": encontrada})

        elif accion == "hablar":
            estado["detener"] = False
            estado["generacion"] += 1
            gen = estado["generacion"]
            threading.Thread(
                target=_hilo_parrafos,
                args=(cmd.get("texto", ""), cmd.get("pos_offset", 0), gen, estado),
                daemon=True,
            ).start()

        elif accion == "detener":
            estado["generacion"] += 1
            estado["detener"] = True
            try:
                motor.Speak("", _SPF_ASYNC | _SPF_PURGEBEFORESPEAK)
            except Exception:
                pass

        elif accion == "pausar":
            try:
                motor.Pause()
            except Exception:
                pass

        elif accion == "reanudar":
            estado["detener"] = False
            try:
                motor.Resume()
            except Exception:
                pass

        elif accion == "fijar_velocidad":
            v = cmd.get("valor", 50)
            try:
                tasa = max(-10, min(10, int((v / 5) - 10)))
                motor.Rate = tasa
                estado["rate"] = tasa
            except Exception:
                pass

        elif accion == "fijar_volumen":
            try:
                vol = int(cmd.get("valor", 100))
                motor.Volume = vol
                estado["volume"] = vol
            except Exception:
                pass


if __name__ == "__main__":
    main()
# ANCLAJE_FIN: AUXILIAR_SAPI32
