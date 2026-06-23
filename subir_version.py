# ANCLAJE_INICIO: SCRIPT_SUBIR_VERSION
"""
subir_version.py
────────────────
Asistente de publicación de versiones para Epub TTS Accesible.

Uso:
    python subir_version.py          → muestra la versión actual
    python subir_version.py patch    → 1.2.0 → 1.2.1
    python subir_version.py minor    → 1.2.0 → 1.3.0
    python subir_version.py major    → 1.2.0 → 2.0.0
    python subir_version.py 2.0.0    → fuerza una versión concreta

Lo que hace:
  1. Lee la versión actual de recursos/version.json.
  2. Calcula la nueva versión según el argumento.
  3. Escribe recursos/version.json con la nueva versión y la fecha de hoy.
  4. Actualiza también novedades.txt con una cabecera de versión si no existe.
  5. Hace git add + git commit con el mensaje estándar.
  6. Informa de los pasos siguientes (push a main).

Nunca hace git push solo — siempre lo deja en manos de la desarrolladora.
"""

import datetime
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
RUTA_VERSION   = os.path.join(RAIZ, "recursos", "version.json")
RUTA_NOVEDADES = os.path.join(RAIZ, "novedades.txt")


def leer_version() -> tuple[int, int, int]:
    try:
        with open(RUTA_VERSION, encoding="utf-8") as f:
            v = json.load(f).get("version", "0.0.0")
        partes = [int(x) for x in v.split(".")]
        if len(partes) == 3:
            return tuple(partes)
    except Exception:
        pass
    return (0, 0, 0)


def escribir_version(mayor: int, menor: int, parche: int):
    hoy = datetime.date.today().isoformat()
    datos = {"version": f"{mayor}.{menor}.{parche}", "fecha": hoy}
    ruta_tmp = RUTA_VERSION + ".tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta_tmp, RUTA_VERSION)


def asegurar_cabecera_novedades(version_str: str):
    """
    Añade una cabecera de versión al principio de novedades.txt si aún no existe.
    No sobreescribe el contenido existente.
    """
    hoy = datetime.date.today().strftime("%d/%m/%Y")
    cabecera = f"=== v{version_str} ({hoy}) ===\n\n"
    contenido = ""
    if os.path.isfile(RUTA_NOVEDADES):
        with open(RUTA_NOVEDADES, encoding="utf-8") as f:
            contenido = f.read()
    if f"=== v{version_str}" not in contenido:
        nuevo = cabecera + contenido
        ruta_tmp = RUTA_NOVEDADES + ".tmp"
        with open(ruta_tmp, "w", encoding="utf-8") as f:
            f.write(nuevo)
        os.replace(ruta_tmp, RUTA_NOVEDADES)
        print(f"  → Cabecera v{version_str} añadida a novedades.txt")
    else:
        print(f"  → novedades.txt ya tiene la cabecera v{version_str}")


def git_commit(version_str: str):
    archivos = [RUTA_VERSION, RUTA_NOVEDADES]
    archivos_existentes = [a for a in archivos if os.path.isfile(a)]
    subprocess.run(["git", "add"] + archivos_existentes, cwd=RAIZ, check=True)
    mensaje = f"Versión {version_str}: actualiza version.json y novedades.txt"
    subprocess.run(["git", "commit", "-m", mensaje], cwd=RAIZ, check=True)


def main():
    actual = leer_version()
    version_actual_str = ".".join(str(x) for x in actual)

    if len(sys.argv) < 2:
        print(f"Versión actual: {version_actual_str}")
        print("\nUso: python subir_version.py [patch|minor|major|X.Y.Z]")
        return

    arg = sys.argv[1].lower()
    mayor, menor, parche = actual

    if arg == "patch":
        parche += 1
    elif arg == "minor":
        menor += 1
        parche = 0
    elif arg == "major":
        mayor += 1
        menor = 0
        parche = 0
    elif arg.count(".") == 2:
        try:
            mayor, menor, parche = (int(x) for x in arg.split("."))
        except ValueError:
            print(f"ERROR: '{arg}' no es una versión semántica válida (X.Y.Z).")
            sys.exit(1)
    else:
        print(f"ERROR: argumento no reconocido: '{arg}'")
        print("Uso: python subir_version.py [patch|minor|major|X.Y.Z]")
        sys.exit(1)

    nueva_str = f"{mayor}.{menor}.{parche}"

    print(f"\n  {version_actual_str}  →  {nueva_str}\n")

    escribir_version(mayor, menor, parche)
    print(f"  → recursos/version.json actualizado a {nueva_str}")

    asegurar_cabecera_novedades(nueva_str)

    try:
        git_commit(nueva_str)
        print(f"  → Commit creado: 'Versión {nueva_str}: actualiza version.json y novedades.txt'")
    except subprocess.CalledProcessError as exc:
        print(f"  AVISO: no se pudo hacer el commit automático ({exc})")
        print("  Haz el commit manualmente antes de hacer push.")

    print(f"""
┌─────────────────────────────────────────────────────┐
  Versión {nueva_str} preparada.

  Pasos siguientes:
    1. Edita novedades.txt con los cambios de esta versión.
    2. git push origin main
    3. Crea el release en GitHub y sube el ZIP del portable.
└─────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    main()
# ANCLAJE_FIN: SCRIPT_SUBIR_VERSION
