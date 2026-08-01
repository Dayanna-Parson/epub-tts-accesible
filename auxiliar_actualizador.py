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
                      [--lanzador <ruta al ejecutable o script a relanzar>]
                      [--python <intérprete a usar si --lanzador es un .py>]

La app llama a este ejecutable ya con --origen apuntando a la carpeta
descomprimida y verificada por GestorDescargaActualizacion
(temp/actualizacion/<repo>-main), y se cierra inmediatamente después de
lanzarlo, para liberar los archivos que van a sobrescribirse.

--lanzador lo decide la propia app en el momento de invocar a este
auxiliar, según su propio modo de ejecución (congelada con PyInstaller o
en modo desarrollo con el intérprete de Python) — este script nunca
asume un .bat de lanzamiento fijo. Si no se recibe --lanzador, se intenta
detectar automáticamente a partir de --destino (ver _detectar_lanzador).

Pasos:
    1. Si se recibió --pid, espera de forma nativa (sin parsear texto de
       comandos externos) a que ese proceso termine, con un tiempo límite,
       antes de tocar ningún archivo.
    2. Por cada entrada de nivel superior en --origen (excepto las carpetas
       de datos de usuario, ver _PRESERVAR): si ya existe una entrada con
       ese nombre en --destino, se copia (nunca se mueve) a
       temp/backup_previo/ y se verifica que la copia esté íntegra antes de
       tocar nada en destino. Solo entonces se reemplaza la entrada de
       destino por la versión nueva.
    3. Si cualquier paso falla, se revierte automáticamente lo ya
       reemplazado a partir de las copias de respaldo ya verificadas, antes
       de relanzar la app y notificar el fallo — la instalación nunca queda
       a medias.
    4. Si todo tiene éxito, se limpia temp/actualizacion/ y
       temp/backup_previo/, y se relanza la app.
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import time

# Carpetas de datos de usuario que nunca se tocan durante la actualización.
# Mismo criterio que _PRESERVAR en comprobador_actualizaciones.py.
_PRESERVAR = {"configuraciones", "Grabaciones_Epub-TTS", "bin", "temp"}

_ESPERA_MAX_CIERRE_APP = 30.0   # segundos máximos esperando a que cierre la app
_REINTENTOS_OPERACION = 5
_ESPERA_ENTRE_REINTENTOS = 1    # segundos

_NOMBRE_EXE_PRINCIPAL = "epubtts.exe"     # build congelada con PyInstaller
_NOMBRE_SCRIPT_PRINCIPAL = "iniciar_epub_tts.py"  # modo desarrollo


def _log(mensaje: str):
    """Escribe una línea de estado a stdout. La app no lee esta salida —
    es solo para diagnóstico manual si el usuario lo redirige a un archivo."""
    print(f"[actualizador] {mensaje}", flush=True)


# ── Espera de cierre del proceso padre ───────────────────────────────────────

def _esperar_cierre_app(pid: int, timeout_seg: float = _ESPERA_MAX_CIERRE_APP):
    """
    Espera de forma nativa (WinAPI vía ctypes, sin parsear salida de
    comandos externos como tasklist) a que el proceso `pid` termine, con
    un tiempo límite. Si `pid` es 0 o no se puede abrir el proceso (ya
    terminó, o el auxiliar corre en un sistema no soportado), no bloquea.
    """
    if not pid:
        return

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
    except (AttributeError, OSError):
        # No es Windows (p. ej. entorno de pruebas): no hay WinAPI
        # disponible para esperar de forma nativa. No se bloquea el flujo.
        _log("Aviso: espera nativa de PID no disponible en este sistema; se omite.")
        return

    _SYNCHRONIZE = 0x00100000
    _WAIT_TIMEOUT = 0x00000102

    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        # El proceso ya no existe (o no se pudo abrir): se asume terminado.
        return

    try:
        _log(f"Esperando a que el proceso {pid} de la app termine (hasta {timeout_seg:.0f}s)...")
        resultado = kernel32.WaitForSingleObject(handle, int(timeout_seg * 1000))
        if resultado == _WAIT_TIMEOUT:
            _log(f"Aviso: el proceso {pid} no terminó dentro del tiempo límite; se continúa igualmente.")
    finally:
        kernel32.CloseHandle(handle)


# ── Copia de respaldo segura ──────────────────────────────────────────────────

def _con_reintentos(funcion, *args):
    """
    Ejecuta `funcion(*args)` con reintentos: un antivirus o un lector de
    pantalla que esté inspeccionando el sistema de archivos puede retener
    un archivo un instante y provocar un "Acceso denegado" transitorio.
    """
    ultimo_error = None
    for _ in range(_REINTENTOS_OPERACION):
        try:
            return funcion(*args)
        except Exception as exc:
            ultimo_error = exc
            _log(f"Aviso: fallo transitorio en {funcion.__name__} ({args}): {exc}. Reintentando...")
            time.sleep(_ESPERA_ENTRE_REINTENTOS)
    raise ultimo_error


def _copiar_entrada(origen: str, destino: str):
    """Copia un archivo o carpeta completa (nunca mueve el original)."""
    if os.path.isdir(origen):
        shutil.copytree(origen, destino)
    else:
        shutil.copy2(origen, destino)


def _verificar_copia_integra(original: str, copia: str) -> bool:
    """
    Comprueba que `copia` reproduce fielmente `original`: mismo árbol de
    archivos y sin diferencias de contenido detectadas por filecmp.
    """
    if not os.path.exists(copia):
        return False
    if os.path.isdir(original):
        comparacion = filecmp.dircmp(original, copia)
        if comparacion.left_only or comparacion.right_only or comparacion.diff_files:
            return False
        # Revisar también las subcarpetas comunes de forma recursiva.
        pendientes = [comparacion]
        while pendientes:
            actual = pendientes.pop()
            if actual.left_only or actual.right_only or actual.diff_files:
                return False
            pendientes.extend(actual.subdirs.values())
        return True
    else:
        return (
            os.path.isfile(copia)
            and os.path.getsize(original) == os.path.getsize(copia)
        )


def _eliminar_entrada(ruta: str):
    """Elimina un archivo o carpeta completa."""
    if os.path.isdir(ruta):
        shutil.rmtree(ruta)
    else:
        os.remove(ruta)


def _restaurar_entrada(nombre: str, destino: str, carpeta_backup: str):
    """
    Revierte una única entrada: retira la versión nueva ya puesta en
    destino/nombre (si llegó a ponerse) y restaura el respaldo verificado
    (si existe), copiándolo de vuelta.
    """
    ruta_destino = os.path.join(destino, nombre)
    ruta_backup = os.path.join(carpeta_backup, nombre)

    if os.path.exists(ruta_destino):
        try:
            _con_reintentos(_eliminar_entrada, ruta_destino)
        except Exception as exc:
            _log(f"Aviso: no se pudo retirar la versión nueva de «{nombre}»: {exc}")

    if os.path.exists(ruta_backup):
        try:
            _con_reintentos(_copiar_entrada, ruta_backup, ruta_destino)
        except Exception as exc:
            _log(f"Aviso: no se pudo restaurar el respaldo de «{nombre}»: {exc}")


def _instalar(origen: str, destino: str) -> dict:
    """
    Instala la versión nueva de origen sobre destino, respaldando por
    copia (nunca por movimiento) cada entrada existente y verificando su
    integridad antes de reemplazarla. Si cualquier paso falla, revierte
    automáticamente lo ya reemplazado a partir de los respaldos.
    Devuelve {"ok": bool, "error": str|None}.
    """
    carpeta_backup = os.path.join(destino, "temp", "backup_previo")
    if os.path.exists(carpeta_backup):
        shutil.rmtree(carpeta_backup, ignore_errors=True)
    os.makedirs(carpeta_backup, exist_ok=True)

    entradas = [e for e in os.listdir(origen) if e not in _PRESERVAR]

    completadas = []
    nombre_actual = None
    # Entrada cuya verificación de respaldo falló *antes* de tocar el
    # destino: su original sigue intacto, así que no debe entrar en la
    # lista de reversión (revertirla borraría el original bueno para
    # sustituirlo por el propio respaldo que se acaba de determinar que
    # no es íntegro, dejando la instalación peor que al empezar).
    nombre_no_tocado = None
    try:
        for nombre in entradas:
            nombre_actual = nombre
            ruta_origen = os.path.join(origen, nombre)
            ruta_destino = os.path.join(destino, nombre)
            ruta_backup = os.path.join(carpeta_backup, nombre)

            if os.path.exists(ruta_destino):
                _log(f"Respaldando «{nombre}»...")
                _con_reintentos(_copiar_entrada, ruta_destino, ruta_backup)
                if not _verificar_copia_integra(ruta_destino, ruta_backup):
                    nombre_no_tocado = nombre
                    raise RuntimeError(
                        f"El respaldo de «{nombre}» no se pudo verificar íntegro; "
                        "se aborta antes de tocar el destino."
                    )

            _log(f"Instalando «{nombre}»...")
            if os.path.exists(ruta_destino):
                _con_reintentos(_eliminar_entrada, ruta_destino)
            _con_reintentos(_copiar_entrada, ruta_origen, ruta_destino)
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
        if (
            nombre_actual is not None
            and nombre_actual not in completadas
            and nombre_actual != nombre_no_tocado
        ):
            pendientes_de_revertir.append(nombre_actual)
        for nombre in reversed(pendientes_de_revertir):
            _restaurar_entrada(nombre, destino, carpeta_backup)
        shutil.rmtree(carpeta_backup, ignore_errors=True)
        return {"ok": False, "error": str(exc)}


# ── Relanzamiento de la app ───────────────────────────────────────────────────

def _detectar_lanzador(destino: str):
    """
    Autodetecta qué relanzar cuando la app no pasó --lanzador explícito:
    el ejecutable principal congelado si existe, o el script de entrada
    en modo desarrollo. Devuelve (comando: list[str]) o None si no se
    encontró ninguno de los dos.
    """
    ruta_exe = os.path.join(destino, _NOMBRE_EXE_PRINCIPAL)
    if os.path.isfile(ruta_exe):
        return [ruta_exe]

    ruta_script = os.path.join(destino, _NOMBRE_SCRIPT_PRINCIPAL)
    if os.path.isfile(ruta_script):
        return [sys.executable or "python", ruta_script]

    return None


def _construir_comando_lanzador(destino: str, lanzador: str, interprete: str):
    """
    Construye el comando a ejecutar para relanzar la app:
      - Si se pasó --lanzador explícito: se usa tal cual, o con el
        intérprete indicado en --python si es un script .py.
      - Si no, se autodetecta a partir de --destino.
    """
    if lanzador:
        if lanzador.lower().endswith(".py"):
            return [interprete or sys.executable or "python", lanzador]
        return [lanzador]

    return _detectar_lanzador(destino)


def _relanzar_app(destino: str, lanzador: str, interprete: str):
    """
    Relanza la app principal tras la instalación (correcta o revertida),
    ejecutando directamente el comando resuelto por
    _construir_comando_lanzador — nunca a través de un .bat intermedio.
    """
    comando = _construir_comando_lanzador(destino, lanzador, interprete)
    if not comando:
        _log(
            "Aviso: no se encontró ningún ejecutable o script principal para "
            "relanzar la app (ni --lanzador ni autodetección en destino)."
        )
        return
    try:
        subprocess.Popen(
            comando,
            cwd=destino,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except Exception as exc:
        _log(f"Aviso: no se pudo relanzar la app automáticamente ({comando}): {exc}")


def main():
    parser = argparse.ArgumentParser(description="Instalador auxiliar de actualizaciones.")
    parser.add_argument("--origen", required=True)
    parser.add_argument("--destino", required=True)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--lanzador", default="")
    parser.add_argument("--python", default="")
    args = parser.parse_args()

    _esperar_cierre_app(args.pid)

    resultado = _instalar(args.origen, args.destino)

    if resultado["ok"]:
        _log("Actualización instalada con éxito.")
    else:
        _log(f"La actualización falló y se revirtió: {resultado['error']}")

    _relanzar_app(args.destino, args.lanzador, args.python)
    sys.exit(0 if resultado["ok"] else 1)


if __name__ == "__main__":
    main()
# ANCLAJE_FIN: AUXILIAR_ACTUALIZADOR
