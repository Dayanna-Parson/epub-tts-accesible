# ANCLAJE_INICIO: AUXILIAR_ACTUALIZADOR
"""
auxiliar_actualizador.py
─────────────────────────
Ejecutable auxiliar de instalación de actualizaciones (Fase C, v3.0).
Sustituye al enfoque de generar un .bat al vuelo (bloque
ACTUALIZADOR_SCRIPT_CLON en pestana_ajustes.py): al ser un ejecutable
compilado y fijo, no dispara los falsos positivos de antivirus que sí
provoca un script generado dinámicamente, y su lógica de rollback no
depende de que el propio script sobreviva al proceso que lo lanzó.

Compilar con PyInstaller (misma arquitectura que la app, no necesita ser
de 32 bits como auxiliar_sapi32.py):
    python -m PyInstaller --noconsole --onefile --name actualizador auxiliar_actualizador.py
Copiar el exe resultante a /bin/ del portable.

Uso:
    actualizador.exe --origen <carpeta con la versión nueva ya verificada>
                      --destino <raíz de la instalación actual>
                      [--pid <PID del proceso de la app que lo lanzó>]

La app llama a este ejecutable ya con --origen apuntando a la carpeta
descomprimida y verificada por GestorDescargaActualizacion
(temp/actualizacion/<repo>-main), y se cierra inmediatamente después de
lanzarlo, para liberar los archivos que van a sobrescribirse.

Pasos:
    1. Si se recibió --pid, espera a que ese proceso termine (hasta 30s)
       antes de tocar ningún archivo, para no chocar con archivos todavía
       abiertos por la app que se está cerrando.
    2. Por cada entrada de nivel superior en --origen (excepto las carpetas
       de datos de usuario, ver _PRESERVAR): si ya existe una entrada con
       ese nombre en --destino, se mueve a temp/backup_previo/ antes de
       mover la versión nueva a su lugar. Nunca se copia y se borra; se
       mueve, así que revertir es siempre una operación de mover de vuelta.
    3. Si cualquier paso falla, se revierte automáticamente lo ya movido
       (se restaura el respaldo, se retira lo nuevo a medio poner) antes de
       relanzar la app y notificar el fallo — la instalación nunca queda a
       medias.
    4. Si todo tiene éxito, se limpia temp/actualizacion/ y
       temp/backup_previo/, y se relanza la app.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

# Carpetas de datos de usuario que nunca se tocan durante la actualización.
# Mismo criterio que _PRESERVAR en comprobador_actualizaciones.py.
_PRESERVAR = {"configuraciones", "Grabaciones_Epub-TTS", "bin", "temp"}

_ESPERA_MAX_CIERRE_APP = 30   # segundos máximos esperando a que cierre la app
_REINTENTOS_MOVER = 5
_ESPERA_ENTRE_REINTENTOS = 1  # segundos


def _log(mensaje: str):
    """Escribe una línea de estado a stdout. La app no lee esta salida —
    es solo para diagnóstico manual si el usuario lo redirige a un archivo."""
    print(f"[actualizador] {mensaje}", flush=True)


def _proceso_sigue_vivo(pid: int) -> bool:
    """Comprueba si un PID sigue en ejecución, usando tasklist (sin dependencias)."""
    try:
        salida = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in salida.stdout
    except Exception:
        # Si tasklist no está disponible (entorno no-Windows de pruebas),
        # se asume que ya terminó para no bloquear el flujo indefinidamente.
        return False


def _esperar_cierre_app(pid: int):
    if not pid:
        return
    _log(f"Esperando a que el proceso {pid} de la app termine...")
    inicio = time.time()
    while _proceso_sigue_vivo(pid) and (time.time() - inicio) < _ESPERA_MAX_CIERRE_APP:
        time.sleep(0.5)


def _mover_con_reintentos(origen: str, destino: str):
    """
    shutil.move con reintentos: un antivirus o el propio SO puede retener
    un archivo un instante tras cerrarse el proceso que lo tenía abierto.
    """
    ultimo_error = None
    for intento in range(_REINTENTOS_MOVER):
        try:
            shutil.move(origen, destino)
            return
        except Exception as exc:
            ultimo_error = exc
            time.sleep(_ESPERA_ENTRE_REINTENTOS)
    raise ultimo_error


def _restaurar_entrada(nombre: str, destino: str, carpeta_backup: str):
    """
    Revierte una única entrada: retira la versión nueva ya puesta en
    destino/nombre (si llegó a ponerse) y restaura el respaldo (si existía).
    """
    ruta_destino = os.path.join(destino, nombre)
    ruta_backup = os.path.join(carpeta_backup, nombre)

    if os.path.exists(ruta_destino):
        try:
            if os.path.isdir(ruta_destino):
                shutil.rmtree(ruta_destino, ignore_errors=True)
            else:
                os.remove(ruta_destino)
        except Exception as exc:
            _log(f"Aviso: no se pudo retirar la versión nueva de «{nombre}»: {exc}")

    if os.path.exists(ruta_backup):
        try:
            _mover_con_reintentos(ruta_backup, ruta_destino)
        except Exception as exc:
            _log(f"Aviso: no se pudo restaurar el respaldo de «{nombre}»: {exc}")


def _instalar(origen: str, destino: str) -> dict:
    """
    Instala la versión nueva de origen sobre destino, con rollback
    automático si cualquier paso falla.
    Devuelve {"ok": bool, "error": str|None}.
    """
    carpeta_backup = os.path.join(destino, "temp", "backup_previo")
    if os.path.exists(carpeta_backup):
        shutil.rmtree(carpeta_backup, ignore_errors=True)
    os.makedirs(carpeta_backup, exist_ok=True)

    entradas = [e for e in os.listdir(origen) if e not in _PRESERVAR]

    completadas = []
    nombre_actual = None
    try:
        for nombre in entradas:
            nombre_actual = nombre
            ruta_origen = os.path.join(origen, nombre)
            ruta_destino = os.path.join(destino, nombre)
            ruta_backup = os.path.join(carpeta_backup, nombre)

            _log(f"Instalando «{nombre}»...")
            if os.path.exists(ruta_destino):
                _mover_con_reintentos(ruta_destino, ruta_backup)
            _mover_con_reintentos(ruta_origen, ruta_destino)
            completadas.append(nombre)

        _log("Instalación completada. Limpiando archivos temporales...")
        shutil.rmtree(carpeta_backup, ignore_errors=True)
        # origen es .../temp/actualizacion/<repo>-main: se limpia la carpeta
        # padre completa (temp/actualizacion/) para no dejar restos.
        shutil.rmtree(os.path.dirname(origen), ignore_errors=True)
        return {"ok": True, "error": None}

    except Exception as exc:
        _log(f"ERROR durante la instalación: {exc}. Revirtiendo cambios...")
        pendientes_de_revertir = list(completadas)
        if nombre_actual not in completadas:
            pendientes_de_revertir.append(nombre_actual)
        for nombre in reversed(pendientes_de_revertir):
            _restaurar_entrada(nombre, destino, carpeta_backup)
        shutil.rmtree(carpeta_backup, ignore_errors=True)
        return {"ok": False, "error": str(exc)}


def _relanzar_app(destino: str):
    """
    Relanza la app principal tras la instalación (correcta o revertida),
    mediante INICIAR_APP.bat, que ya existe en la raíz del portable.
    """
    lanzador = os.path.join(destino, "INICIAR_APP.bat")
    if not os.path.isfile(lanzador):
        _log(f"Aviso: no se encontró {lanzador}, no se pudo relanzar la app.")
        return
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", lanzador],
            cwd=destino,
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception as exc:
        _log(f"Aviso: no se pudo relanzar la app automáticamente: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Instalador auxiliar de actualizaciones.")
    parser.add_argument("--origen", required=True)
    parser.add_argument("--destino", required=True)
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()

    _esperar_cierre_app(args.pid)

    resultado = _instalar(args.origen, args.destino)

    if resultado["ok"]:
        _log("Actualización instalada con éxito.")
    else:
        _log(f"La actualización falló y se revirtió: {resultado['error']}")

    _relanzar_app(args.destino)
    sys.exit(0 if resultado["ok"] else 1)


if __name__ == "__main__":
    main()
# ANCLAJE_FIN: AUXILIAR_ACTUALIZADOR
