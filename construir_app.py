# ANCLAJE_INICIO: SCRIPT_CONSTRUCCION_PORTABLE
"""
construir_app.py
────────────────
Empaqueta Epub TTS Accesible en un archivo ZIP portable listo para
distribuir a usuarios finales invidentes.

Pasos que ejecuta:
  1. Limpia el directorio de salida anterior (/dist/epubtts/).
  2. Ejecuta PyInstaller con --noconsole para generar epubtts.exe.
  3. Copia bin/, recursos/ y documentos/ al portable.
  4. Crea configuraciones/ vacía (con solo ajustes.json de fábrica).
  5. Copia INICIAR_APP.bat y novedades.txt a la raíz del portable.
  6. Comprime todo en dist/epub-tts-accesible-vX.Y.Z.zip.

Uso:
    python construir_app.py

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
def limpiar_destino():
    print("[1/6] Limpiando directorios de salida anteriores...")
    for ruta in (DIR_DIST_RAW, DIR_PORTABLE):
        if os.path.exists(ruta):
            shutil.rmtree(ruta)
            print(f"      Eliminado: {ruta}")
    if os.path.exists(ZIP_SALIDA):
        os.remove(ZIP_SALIDA)
        print(f"      Eliminado: {ZIP_SALIDA}")
    os.makedirs(os.path.join(RAIZ, "dist"), exist_ok=True)


def ejecutar_pyinstaller():
    print("[2/6] Ejecutando PyInstaller...")
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


def copiar_recursos():
    print("[3/6] Copiando recursos al portable...")
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

    # INICIAR_APP.bat en la raíz
    bat_origen = os.path.join(RAIZ, "INICIAR_APP.bat")
    if os.path.isfile(bat_origen):
        shutil.copy2(bat_origen, os.path.join(DIR_PORTABLE, "INICIAR_APP.bat"))
        print("      Copiado: INICIAR_APP.bat")


def crear_configuraciones_fabrica():
    print("[4/6] Creando configuraciones/ de fábrica...")
    dir_conf = os.path.join(DIR_PORTABLE, "configuraciones")
    os.makedirs(dir_conf, exist_ok=True)

    for nombre, contenido in _AJUSTES_FABRICA.items():
        ruta = os.path.join(dir_conf, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(contenido, f, ensure_ascii=False, indent=2)
        print(f"      Creado: configuraciones/{nombre}")

    # Carpeta de grabaciones vacía para que el portable la tenga desde el inicio
    os.makedirs(os.path.join(DIR_PORTABLE, "Grabaciones_Epub-TTS"), exist_ok=True)


def comprimir_portable():
    print(f"[5/6] Comprimiendo en {os.path.basename(ZIP_SALIDA)}...")
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
    print("[6/6] Eliminando archivos temporales de compilación...")
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
    copiar_recursos()
    crear_configuraciones_fabrica()
    comprimir_portable()
    limpiar_temporal()
    print(f"\n✓ Portable listo: dist/epub-tts-accesible-v{VERSION}.zip\n")
# ANCLAJE_FIN: SCRIPT_CONSTRUCCION_PORTABLE
