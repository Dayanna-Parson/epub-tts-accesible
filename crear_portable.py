# ANCLAJE_INICIO: SCRIPT_CONSTRUCCION_PORTABLE
"""
crear_portable.py
─────────────────
Empaqueta Epub TTS Accesible en un archivo ZIP portable listo para
distribuir a usuarios finales invidentes.

Pasos que ejecuta:
  1. Limpia el directorio de salida anterior (/dist/epubtts/).
  2. Compila los catálogos de idioma (locale/*.po → *.mo).
  3. Ejecuta PyInstaller con --noconsole para generar epubtts.exe.
  4. Compila auxiliar_actualizador.py a bin/actualizador.exe (misma
     arquitectura que la app, por eso se automatiza aquí — a diferencia de
     auxiliar_sapi32.exe, que necesita un intérprete de 32 bits aparte y
     sigue siendo un paso manual, ver bin/INSTRUCCIONES.txt).
  5. Copia bin/, recursos/, locale/, ayuda.html, novedades.txt, LEEME.txt y
     LICENSE al portable, todo directo en la raíz junto a epubtts.exe — sin
     una subcarpeta documentos/ de por medio.
  6. Crea configuraciones/ vacía (ajustes.json de fábrica, carpetas de
     backups separadas y carpeta de plantillas del Asistente de Biblioteca)
     y registros/ vacía, para que un fallo en el portable escriba ahí
     mismo, igual que en el entorno de desarrollo.
  7. Comprime todo en dist/epub-tts-accesible-vX.Y.Z.zip.

Uso:
    python crear_portable.py

Requisitos previos:
    pip install pyinstaller
    FFmpeg portátil en bin/ffmpeg.exe
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile

# ── Raíz del proyecto ─────────────────────────────────────────────────────────
RAIZ = os.path.dirname(os.path.abspath(__file__))

# ── Versión ───────────────────────────────────────────────────────────────────
def _leer_version() -> str:
    ruta = os.path.join(RAIZ, "recursos", "version.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f).get("version", "0.0.0")
    except Exception:
        return "0.0.0"

VERSION = _leer_version()

# ── Rutas de trabajo ──────────────────────────────────────────────────────────
DIR_DIST_RAW  = os.path.join(RAIZ, "dist", "epubtts")   # PyInstaller vuelca aquí
DIR_PORTABLE  = os.path.join(RAIZ, "dist", "epub-tts-accesible")
ZIP_SALIDA    = os.path.join(RAIZ, "dist", f"epub-tts-accesible-v{VERSION}.zip")

# Archivos y carpetas del proyecto que NO van al portable
_EXCLUIR_RAIZ = {
    ".git", ".gitignore", ".gitattributes",
    "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".pytest_cache",
    "tests", "test",
    "*.md", "*.log", "*.spec",
    "construir_app.py",
}

# Ajustes de fábrica vacíos que se incluyen en configuraciones/
_AJUSTES_FABRICA = {
    "ajustes.json": {
        "velocidad_lectura": 50,
        "volumen_lectura": 100,
        "segundos_salto": 10,
        "pausa_entre_fragmentos_ms": 0,
        # Desmarcada por defecto: la comprobación/instalación automática al
        # arrancar debe ser una decisión explícita de quien instala, no un
        # comportamiento de fábrica que se cuela mientras se está probando
        # una versión concreta a propósito.
        "actualizar_automaticamente": False,
        "escala_velocidad": "porcentaje",
        "idioma_libro_codigo": "es-ES",
        "sonidos_habilitados": True,
    },
}


# ═════════════════════════════════════════════════════════════════════════════
def _ocultar_archivo(ruta: str):
    """Marca un archivo como oculto en Windows (atributo FILE_ATTRIBUTE_HIDDEN)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(ruta, 0x02)
    except Exception:
        pass  # En sistemas no-Windows se ignora silenciosamente


# ANCLAJE_INICIO: BORRADO_CON_REINTENTOS
def _quitar_solo_lectura_y_reintentar(func, ruta_item, exc_info):
    """
    Callback de shutil.rmtree(onexc=...). La causa más frecuente de
    PermissionError (WinError 5) al borrar un árbol en Windows no es un
    proceso con el archivo abierto, sino que el archivo o carpeta quedó
    marcado como "solo lectura" (habitual tras clonar o copiar un repo en
    Windows) — rmtree no puede borrar eso sin quitarle antes el atributo.
    Se quita con os.chmod() y se reintenta la operación exacta que falló
    (os.remove/os.rmdir, recibida en func).
    """
    try:
        os.chmod(ruta_item, stat.S_IWRITE)
        func(ruta_item)
    except Exception:
        pass  # Si tampoco así se puede, se deja que el reintento exterior lo capture


def _borrar_arbol_con_reintentos(ruta: str, intentos: int = 8, espera_seg: float = 2.0):
    """
    Reintenta shutil.rmtree() varias veces, quitando el atributo de solo
    lectura en cada intento (ver _quitar_solo_lectura_y_reintentar). Si tras
    todos los intentos sigue sin poder borrarse, algo tiene un archivo
    concreto realmente abierto (el epubtts.exe de una construcción anterior,
    el Explorador generando miniaturas, o un antivirus escaneando) — se lista
    qué archivos quedan dentro para poder identificar cuál es.
    """
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            shutil.rmtree(ruta, onexc=_quitar_solo_lectura_y_reintentar)
            return
        except PermissionError as e:
            ultimo_error = e
            if intento < intentos:
                print(f"      Acceso denegado al borrar {ruta} (intento {intento}/{intentos}), reintentando...")
                time.sleep(espera_seg)
    restantes = [
        os.path.join(carpeta, archivo)
        for carpeta, _dirs, archivos in os.walk(ruta)
        for archivo in archivos
    ][:20]
    detalle = "\n".join(f"  - {r}" for r in restantes) if restantes else "  (la carpeta ya no tiene archivos, pero Windows sigue sin dejar borrarla)"
    raise PermissionError(
        f"No se pudo borrar '{ruta}' tras {intentos} intentos, ni siquiera quitando el atributo de solo lectura.\n"
        f"Archivos que siguen dentro:\n{detalle}\n"
        "Causas probables: el epubtts.exe de una construcción anterior sigue en marcha (revisa el "
        "Administrador de tareas), el Explorador tiene esa carpeta abierta, o un antivirus la está "
        "escaneando. Prueba a borrar esa carpeta a mano desde el Explorador; si Windows tampoco te "
        "deja, reinicia el equipo y vuelve a intentarlo."
    ) from ultimo_error
# ANCLAJE_FIN: BORRADO_CON_REINTENTOS


def limpiar_destino():
    print("[1/8] Limpiando directorios de salida anteriores...")
    for ruta in (DIR_DIST_RAW, DIR_PORTABLE):
        if os.path.exists(ruta):
            _borrar_arbol_con_reintentos(ruta)
            print(f"      Eliminado: {ruta}")
    if os.path.exists(ZIP_SALIDA):
        os.remove(ZIP_SALIDA)
        print(f"      Eliminado: {ZIP_SALIDA}")
    os.makedirs(os.path.join(RAIZ, "dist"), exist_ok=True)


# ANCLAJE_INICIO: COMPILACION_CATALOGOS_IDIOMA
def compilar_catalogos_idioma():
    """
    Recompila locale/*/LC_MESSAGES/*.mo a partir de los .po fuente antes de
    empaquetar, para que el portable siempre lleve las traducciones al día
    aunque alguien haya olvidado ejecutar compilar_i18n.py a mano.
    """
    print("[2/8] Compilando catálogos de idioma (locale/*.po → *.mo)...")
    script = os.path.join(RAIZ, "compilar_i18n.py")
    if not os.path.isfile(script):
        print("      AVISO: compilar_i18n.py no encontrado; se omite.")
        return
    resultado = subprocess.run([sys.executable, script], cwd=RAIZ)
    if resultado.returncode != 0:
        print("ERROR: fallo al compilar los catálogos de idioma. Abortando.")
        sys.exit(1)
# ANCLAJE_FIN: COMPILACION_CATALOGOS_IDIOMA


def ejecutar_pyinstaller():
    print("[3/8] Ejecutando PyInstaller...")
    punto_entrada = os.path.join(RAIZ, "iniciar_epub_tts.py")
    icono         = os.path.join(RAIZ, "recursos", "iconos", "epubtts.ico")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--noconsole",
        "--onedir",
        "--name=epubtts",
        f"--distpath={os.path.join(RAIZ, 'dist')}",
        f"--workpath={os.path.join(RAIZ, 'build')}",
        f"--specpath={os.path.join(RAIZ, 'build')}",
        # accessible_output3.outputs.auto.Auto() detecta el lector de pantalla
        # disponible con importes/DLLs que el análisis estático de PyInstaller
        # no siempre traza (a diferencia de pyttsx3 o sounddevice, no hay un
        # hook dedicado para accessible_output3 en _pyinstaller_hooks_contrib).
        # Sin esto, el portable puede quedarse mudo con voz.hablar() aunque
        # NVDA esté corriendo: la llamada no lanza ninguna excepción, pero
        # Auto() nunca llega a encontrar ningún backend funcional.
        "--collect-all=accessible_output3",
    ]
    if os.path.isfile(icono):
        args.append(f"--icon={icono}")
    args.append(punto_entrada)

    resultado = subprocess.run(args, cwd=RAIZ)
    if resultado.returncode != 0:
        print("ERROR: PyInstaller terminó con errores. Abortando.")
        sys.exit(1)


# ANCLAJE_INICIO: COMPILACION_ACTUALIZADOR_AUXILIAR
def compilar_actualizador():
    """
    Compila auxiliar_actualizador.py a bin/actualizador.exe con PyInstaller,
    con el mismo intérprete (misma arquitectura) que compila la app
    principal. A diferencia de auxiliar_sapi32.exe —que necesita Python de
    32 bits y por eso sigue siendo un paso manual documentado en
    bin/INSTRUCCIONES.txt—, actualizador.exe no tiene ese requisito, así
    que se automatiza aquí para que cada portable lo lleve siempre
    actualizado sin depender de un paso manual adicional.
    """
    print("[4/8] Compilando actualizador.exe (auxiliar de actualizaciones)...")
    origen_script = os.path.join(RAIZ, "auxiliar_actualizador.py")
    if not os.path.isfile(origen_script):
        print("      AVISO: auxiliar_actualizador.py no encontrado; se omite bin/actualizador.exe.")
        return

    dir_build_aux = os.path.join(RAIZ, "build", "actualizador")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--noconsole",
        "--onefile",
        "--name=actualizador",
        f"--distpath={os.path.join(RAIZ, 'bin')}",
        f"--workpath={dir_build_aux}",
        f"--specpath={dir_build_aux}",
        origen_script,
    ]
    resultado = subprocess.run(args, cwd=RAIZ)
    if resultado.returncode != 0:
        print("ERROR: PyInstaller terminó con errores al compilar actualizador.exe. Abortando.")
        sys.exit(1)
    print("      Generado: bin/actualizador.exe")
# ANCLAJE_FIN: COMPILACION_ACTUALIZADOR_AUXILIAR


def copiar_recursos():
    print("[5/8] Copiando recursos al portable...")
    os.makedirs(DIR_PORTABLE, exist_ok=True)

    # Mover el directorio generado por PyInstaller a DIR_PORTABLE
    if os.path.isdir(DIR_DIST_RAW):
        for entrada in os.listdir(DIR_DIST_RAW):
            shutil.move(
                os.path.join(DIR_DIST_RAW, entrada),
                os.path.join(DIR_PORTABLE, entrada),
            )
        shutil.rmtree(DIR_DIST_RAW, ignore_errors=True)

    # Carpetas de recursos
    for carpeta in ("bin", "recursos", "locale"):
        origen = os.path.join(RAIZ, carpeta)
        destino = os.path.join(DIR_PORTABLE, carpeta)
        if os.path.isdir(origen):
            shutil.copytree(origen, destino)
            print(f"      Copiado: {carpeta}/")
        else:
            print(f"      AVISO: carpeta '{carpeta}/' no encontrada, omitida.")

    # bin/ffmpeg.exe y bin/auxiliar_sapi32.exe no van al repositorio (ver
    # bin/INSTRUCCIONES.txt) y hay que colocarlos a mano antes de empaquetar.
    # Sin ellos el portable arranca igual, pero se queda cojo en Windows
    # real: sin ffmpeg no hay MP3 320 kbps con Polly/SAPI5, y sin el puente
    # de 32 bits las voces Eloquence/RealSpeak no aparecen en la lista. Se
    # avisa aquí, en vez de descubrirlo ya distribuido a un usuario final.
    for nombre_exe in ("ffmpeg.exe", "auxiliar_sapi32.exe"):
        if not os.path.isfile(os.path.join(DIR_PORTABLE, "bin", nombre_exe)):
            print(f"      AVISO: bin/{nombre_exe} no está presente — "
                  f"revisa bin/INSTRUCCIONES.txt antes de distribuir este portable.")

    # ayuda.html, novedades.txt, LEEME.txt y LICENSE van directos a la raíz
    # del portable, junto a epubtts.exe (F1 busca ayuda.html ahí mismo) — sin
    # carpeta documentos/ de por medio, que solo llegó a contener un archivo.
    # LEEME.txt es el primer contacto de quien acaba de descomprimir el ZIP,
    # antes incluso de abrir la app; LICENSE va con el ejecutable distribuido
    # porque los términos de uso deben viajar con el propio programa, no solo
    # estar en el repositorio de origen.
    for nombre in ("ayuda.html", "novedades.txt", "LEEME.txt", "LICENSE"):
        origen = os.path.join(RAIZ, nombre)
        if os.path.isfile(origen):
            shutil.copy2(origen, os.path.join(DIR_PORTABLE, nombre))
            print(f"      Copiado: {nombre}")
        else:
            print(f"      AVISO: {nombre} no encontrado en la raíz del proyecto, omitido.")


def crear_configuraciones_fabrica():
    print("[6/8] Creando configuraciones/ de fábrica...")
    dir_conf = os.path.join(DIR_PORTABLE, "configuraciones")
    os.makedirs(dir_conf, exist_ok=True)

    for nombre, contenido in _AJUSTES_FABRICA.items():
        ruta = os.path.join(dir_conf, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(contenido, f, ensure_ascii=False, indent=2)
        print(f"      Creado: configuraciones/{nombre}")

    # proyectos.json vacío: estructura mínima para que el gestor arranque sin errores
    ruta_proy = os.path.join(dir_conf, "proyectos.json")
    datos_proy = {"proyectos": {}, "orden_raiz": []}
    with open(ruta_proy, "w", encoding="utf-8") as f:
        json.dump(datos_proy, f, ensure_ascii=False, indent=2)
    print("      Creado: configuraciones/proyectos.json (vacío)")

    # pronunciacion.json vacío
    ruta_pron = os.path.join(dir_conf, "pronunciacion.json")
    with open(ruta_pron, "w", encoding="utf-8") as f:
        json.dump([], f)
    print("      Creado: configuraciones/pronunciacion.json (vacío)")

    # Carpetas vacías necesarias desde la primera ejecución.
    # Se añade un marcador .gitkeep para que el ZIP las incluya al comprimir
    # (os.walk solo recoge archivos; carpetas sin contenido se perderían).
    os.makedirs(os.path.join(DIR_PORTABLE, "Grabaciones_Epub-TTS"), exist_ok=True)
    _gitkeep_grab = os.path.join(DIR_PORTABLE, "Grabaciones_Epub-TTS", ".gitkeep")
    open(_gitkeep_grab, "w").close()
    _ocultar_archivo(_gitkeep_grab)
    print("      Creado: Grabaciones_Epub-TTS/ (carpeta de salida de audio)")

    for _carpeta_bak in ("backups_proyectos", "backups_biblioteca"):
        _dir_bak = os.path.join(dir_conf, _carpeta_bak)
        os.makedirs(_dir_bak, exist_ok=True)
        _gitkeep_bak = os.path.join(_dir_bak, ".gitkeep")
        open(_gitkeep_bak, "w").close()
        _ocultar_archivo(_gitkeep_bak)
        print(f"      Creado: configuraciones/{_carpeta_bak}/ (carpeta de respaldos)")

    # asistente_biblioteca/: historial de chat y plantillas de prompt del
    # Asistente de Biblioteca, separados del resto de configuraciones/.
    # Las plantillas se guardan una por archivo .txt en plantillas/; la
    # plantilla "Por defecto" la crea la propia app en el primer arranque
    # (gestor_prompts_asistente.listar_prompts), no hace falta sembrarla aquí.
    dir_plantillas = os.path.join(dir_conf, "asistente_biblioteca", "plantillas")
    os.makedirs(dir_plantillas, exist_ok=True)
    _gitkeep_plantillas = os.path.join(dir_plantillas, ".gitkeep")
    open(_gitkeep_plantillas, "w").close()
    _ocultar_archivo(_gitkeep_plantillas)
    print("      Creado: configuraciones/asistente_biblioteca/plantillas/")

    # registros/: iniciar_epub_tts.py ya la crea sola en el primer arranque
    # (os.makedirs(..., exist_ok=True)), pero se siembra de fábrica en el
    # portable para que quede visible desde el primer momento junto al
    # .exe, igual que en el entorno de desarrollo — así un fallo temprano
    # (antes de que la app termine de arrancar) tiene dónde escribirse.
    dir_registros = os.path.join(DIR_PORTABLE, "registros")
    dir_registros_errores = os.path.join(dir_registros, "errores")
    os.makedirs(dir_registros_errores, exist_ok=True)
    _gitkeep_registros = os.path.join(dir_registros, ".gitkeep")
    open(_gitkeep_registros, "w").close()
    _ocultar_archivo(_gitkeep_registros)
    _gitkeep_registros_errores = os.path.join(dir_registros_errores, ".gitkeep")
    open(_gitkeep_registros_errores, "w").close()
    _ocultar_archivo(_gitkeep_registros_errores)
    print("      Creado: registros/ y registros/errores/ (logs de la app)")


def comprimir_portable():
    print(f"[7/8] Comprimiendo en {os.path.basename(ZIP_SALIDA)}...")
    raiz_zip = f"epub-tts-accesible-v{VERSION}"
    with zipfile.ZipFile(ZIP_SALIDA, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for carpeta_actual, _, archivos in os.walk(DIR_PORTABLE):
            for archivo in archivos:
                ruta_abs = os.path.join(carpeta_actual, archivo)
                ruta_rel = os.path.relpath(ruta_abs, DIR_PORTABLE)
                zf.write(ruta_abs, os.path.join(raiz_zip, ruta_rel))
    tam = os.path.getsize(ZIP_SALIDA) / (1024 * 1024)
    print(f"      ZIP creado: {tam:.1f} MB")


def verificar_contenido_zip():
    """
    Lista el contenido de primer nivel del ZIP ya generado, para comprobar
    a simple vista en la consola que el portable no lleva nada de más
    (código fuente, .git, documentación interna...) sin depender de abrir
    el Explorador de Windows y arriesgarse a confundir esta carpeta con
    otra copia del repo que hubiera al lado.
    """
    print("[Verificación] Contenido de primer nivel del ZIP:")
    prefijo = f"epub-tts-accesible-v{VERSION}/"
    nivel_superior = set()
    with zipfile.ZipFile(ZIP_SALIDA) as zf:
        total_entradas = len(zf.namelist())
        for nombre in zf.namelist():
            resto = nombre[len(prefijo):] if nombre.startswith(prefijo) else nombre
            primero = resto.split("/")[0]
            if primero:
                nivel_superior.add(primero)
    for entrada in sorted(nivel_superior):
        print(f"      - {entrada}")
    print(f"      ({total_entradas} archivos en total dentro del ZIP)")


def limpiar_temporal():
    print("[8/8] Eliminando archivos temporales de compilación...")
    dir_build = os.path.join(RAIZ, "build")
    if os.path.isdir(dir_build):
        shutil.rmtree(dir_build, ignore_errors=True)
    if os.path.isdir(DIR_PORTABLE):
        shutil.rmtree(DIR_PORTABLE, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n=== Construcción del portable Epub TTS Accesible v{VERSION} ===\n")
    limpiar_destino()
    compilar_catalogos_idioma()
    ejecutar_pyinstaller()
    compilar_actualizador()
    copiar_recursos()
    crear_configuraciones_fabrica()
    comprimir_portable()
    verificar_contenido_zip()
    limpiar_temporal()
    print(f"\n✓ Portable listo: dist/epub-tts-accesible-v{VERSION}.zip\n")
# ANCLAJE_FIN: SCRIPT_CONSTRUCCION_PORTABLE
