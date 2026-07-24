# ANCLAJE_INICIO: SCRIPT_CONSTRUCCION_PORTABLE
"""
crear_portable.py
─────────────────
Empaqueta Epub TTS Accesible en un archivo ZIP portable listo para
distribuir a usuarios finales invidentes.

Pasos que ejecuta:
  1. Limpia el directorio de salida anterior (/dist/epubtts/).
  2. Ejecuta PyInstaller con --noconsole para generar epubtts.exe.
  3. Compila auxiliar_actualizador.py a bin/actualizador.exe (misma
     arquitectura que la app, por eso se automatiza aquí — a diferencia de
     auxiliar_sapi32.exe, que necesita un intérprete de 32 bits aparte y
     sigue siendo un paso manual, ver bin/INSTRUCCIONES.txt).
  4. Copia bin/, recursos/ y documentos/ al portable.
  5. Crea configuraciones/ vacía (con solo ajustes.json de fábrica).
  6. Copia INICIAR_APP.bat y novedades.txt a la raíz del portable.
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
import subprocess
import sys
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
        "actualizar_automaticamente": True,
        "escala_velocidad": "porcentaje",
        "idioma_libro_codigo": "es-ES",
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


def limpiar_destino():
    print("[1/7] Limpiando directorios de salida anteriores...")
    for ruta in (DIR_DIST_RAW, DIR_PORTABLE):
        if os.path.exists(ruta):
            shutil.rmtree(ruta)
            print(f"      Eliminado: {ruta}")
    if os.path.exists(ZIP_SALIDA):
        os.remove(ZIP_SALIDA)
        print(f"      Eliminado: {ZIP_SALIDA}")
    os.makedirs(os.path.join(RAIZ, "dist"), exist_ok=True)


def ejecutar_pyinstaller():
    print("[2/7] Ejecutando PyInstaller...")
    punto_entrada = os.path.join(RAIZ, "iniciar_epub_tts.py")
    icono         = os.path.join(RAIZ, "recursos", "iconos", "epubtts.ico")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--noconsole",
        "--onedir",
        f"--name=epubtts",
        f"--distpath={os.path.join(RAIZ, 'dist')}",
        f"--workpath={os.path.join(RAIZ, 'build')}",
        f"--specpath={os.path.join(RAIZ, 'build')}",
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
    print("[3/7] Compilando actualizador.exe (auxiliar de actualizaciones)...")
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
    print("[4/7] Copiando recursos al portable...")
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
    for carpeta in ("bin", "recursos"):
        origen = os.path.join(RAIZ, carpeta)
        destino = os.path.join(DIR_PORTABLE, carpeta)
        if os.path.isdir(origen):
            shutil.copytree(origen, destino)
            print(f"      Copiado: {carpeta}/")
        else:
            print(f"      AVISO: carpeta '{carpeta}/' no encontrada, omitida.")

    # Carpeta documentos: solo ayuda y novedades
    dir_docs_orig  = os.path.join(RAIZ, "documentos")
    dir_docs_dest  = os.path.join(DIR_PORTABLE, "documentos")
    os.makedirs(dir_docs_dest, exist_ok=True)
    _archivos_docs = ("Manual de usuario.pdf", "novedades.txt", "Léeme.txt")
    for nombre in _archivos_docs:
        origen = os.path.join(RAIZ, nombre) if not os.path.isdir(dir_docs_orig) \
                 else os.path.join(dir_docs_orig, nombre)
        if not os.path.isfile(origen):
            origen = os.path.join(RAIZ, nombre)
        if os.path.isfile(origen):
            shutil.copy2(origen, os.path.join(dir_docs_dest, nombre))
            print(f"      Copiado: documentos/{nombre}")

    # ayuda.html en la raíz del portable (F1 la busca junto al ejecutable)
    ayuda_origen = os.path.join(RAIZ, "ayuda.html")
    if os.path.isfile(ayuda_origen):
        shutil.copy2(ayuda_origen, os.path.join(DIR_PORTABLE, "ayuda.html"))
        print("      Copiado: ayuda.html")
    else:
        print("      AVISO: ayuda.html no encontrado en la raíz del proyecto, omitido.")


def crear_configuraciones_fabrica():
    print("[5/7] Creando configuraciones/ de fábrica...")
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

    os.makedirs(os.path.join(dir_conf, "proyectos_backup"), exist_ok=True)
    _gitkeep_bak = os.path.join(dir_conf, "proyectos_backup", ".gitkeep")
    open(_gitkeep_bak, "w").close()
    _ocultar_archivo(_gitkeep_bak)
    print("      Creado: configuraciones/proyectos_backup/ (carpeta de respaldos)")

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


def comprimir_portable():
    print(f"[6/7] Comprimiendo en {os.path.basename(ZIP_SALIDA)}...")
    raiz_zip = f"epub-tts-accesible-v{VERSION}"
    with zipfile.ZipFile(ZIP_SALIDA, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for carpeta_actual, _, archivos in os.walk(DIR_PORTABLE):
            for archivo in archivos:
                ruta_abs = os.path.join(carpeta_actual, archivo)
                ruta_rel = os.path.relpath(ruta_abs, DIR_PORTABLE)
                zf.write(ruta_abs, os.path.join(raiz_zip, ruta_rel))
    tam = os.path.getsize(ZIP_SALIDA) / (1024 * 1024)
    print(f"      ZIP creado: {tam:.1f} MB")


def limpiar_temporal():
    print("[7/7] Eliminando archivos temporales de compilación...")
    dir_build = os.path.join(RAIZ, "build")
    if os.path.isdir(dir_build):
        shutil.rmtree(dir_build, ignore_errors=True)
    if os.path.isdir(DIR_PORTABLE):
        shutil.rmtree(DIR_PORTABLE, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n=== Construcción del portable Epub TTS Accesible v{VERSION} ===\n")
    limpiar_destino()
    ejecutar_pyinstaller()
    compilar_actualizador()
    copiar_recursos()
    crear_configuraciones_fabrica()
    comprimir_portable()
    limpiar_temporal()
    print(f"\n✓ Portable listo: dist/epub-tts-accesible-v{VERSION}.zip\n")
# ANCLAJE_FIN: SCRIPT_CONSTRUCCION_PORTABLE
