# ANCLAJE_INICIO: COMPROBADOR_ACTUALIZACIONES
"""
comprobador_actualizaciones.py
───────────────────────────────
Compara la versión local (version.json en la raíz del proyecto) con la versión
publicada en GitHub y, si hay novedad, descarga el texto de novedades.txt.

Diseño:
  - Sin dependencias wx (motor puro, testeable de forma independiente).
  - Toda la red se hace mediante urllib.request (stdlib, sin pip extras).
  - comprobar_en_hilo(callback) lanza el trabajo en un hilo daemon para que
    la UI no se bloquee mientras se realiza la consulta.

URLs remotas (raw.githubusercontent.com):
  version.json  → compara versiones semánticas X.Y.Z
  novedades.txt → texto libre que se muestra en el diálogo de novedades

Función de descarga:
  descargar_actualizacion() descarga el ZIP de la rama main desde GitHub,
  lo extrae en un directorio temporal y copia los archivos al directorio de
  instalación, preservando configuraciones/, Grabaciones_Epub-TTS/ y bin/.
"""

import io
import json
import logging
import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile

from app.config_rutas import RAIZ, RAIZ_RECURSOS

logger = logging.getLogger(__name__)

# ── Rutas y URLs ──────────────────────────────────────────────────────────────

_RUTA_VERSION_LOCAL = os.path.join(RAIZ_RECURSOS, "recursos", "version.json")

_URL_BASE = (
    "https://raw.githubusercontent.com"
    "/Dayanna-Parson/epub-tts-accesible/main"
)
_URL_VERSION   = f"{_URL_BASE}/recursos/version.json"
_URL_NOVEDADES = f"{_URL_BASE}/novedades.txt"
_URL_ZIP = (
    "https://github.com/Dayanna-Parson/epub-tts-accesible"
    "/archive/refs/heads/main.zip"
)

_TIMEOUT = 10   # segundos de espera por petición HTTP

# Carpetas de usuario que no se sobreescriben durante la actualización
_PRESERVAR = {"configuraciones", "Grabaciones_Epub-TTS", "bin"}


# ═════════════════════════════════════════════════════════════════════════════
class ComprobadorActualizaciones:
    """
    Motor de comprobación y descarga de actualizaciones. Sin dependencias wx.

    Uso típico desde la UI (hilo principal):
        comp = ComprobadorActualizaciones()
        comp.comprobar_en_hilo(
            lambda r: wx.CallAfter(mi_handler, r)
        )

    El dict de resultado de comprobar tiene la forma:
        {
          "hay_nueva":       bool,
          "version_local":   str,   # ej. "1.0.0"
          "version_remota":  str,   # ej. "1.1.0"  (o "—" si hay error)
          "novedades":       str,   # contenido de novedades.txt (si hay nueva)
          "error":           str | None,
        }
    """

    # ── API pública ───────────────────────────────────────────────────────────

    def comprobar_en_hilo(self, callback_resultado):
        """
        Lanza la comprobación completa en un hilo daemon.
        callback_resultado(dict) se invoca desde ese hilo de fondo.
        Si el callback toca la UI, usa wx.CallAfter internamente.
        """
        t = threading.Thread(
            target=self._ejecutar,
            args=(callback_resultado,),
            daemon=True,
        )
        t.start()

    def leer_version_local(self) -> str:
        """Lee la versión del version.json local. Devuelve '0.0.0' si falla."""
        try:
            with open(_RUTA_VERSION_LOCAL, "r", encoding="utf-8") as f:
                datos = json.load(f)
            return datos.get("version", "0.0.0")
        except Exception:
            logger.exception("No se pudo leer la versión local desde %s", _RUTA_VERSION_LOCAL)
            return "0.0.0"

    def obtener_version_remota(self) -> dict:
        """
        Descarga version.json desde GitHub.
        Devuelve {"version": str, "error": str|None}.
        """
        try:
            with urllib.request.urlopen(_URL_VERSION, timeout=_TIMEOUT) as resp:
                datos = json.loads(resp.read().decode("utf-8"))
            return {"version": datos.get("version", "0.0.0"), "error": None}
        except Exception as exc:
            return {"version": "0.0.0", "error": str(exc)}

    def obtener_novedades(self) -> dict:
        """
        Descarga novedades.txt desde GitHub.
        Devuelve {"texto": str, "error": str|None}.
        """
        try:
            with urllib.request.urlopen(_URL_NOVEDADES, timeout=_TIMEOUT) as resp:
                texto = resp.read().decode("utf-8")
            return {"texto": texto, "error": None}
        except Exception as exc:
            return {"texto": "", "error": str(exc)}

    def hay_actualizacion(self, version_local: str, version_remota: str) -> bool:
        """
        Compara dos versiones semánticas X.Y.Z.
        Devuelve True si la remota es estrictamente mayor que la local.
        """
        try:
            local   = tuple(int(x) for x in version_local.split("."))
            remota  = tuple(int(x) for x in version_remota.split("."))
            return remota > local
        except Exception:
            return False

    def descargar_actualizacion(self, callback_progreso=None) -> dict:
        """
        Descarga la versión más reciente desde GitHub y la instala sobre la
        instalación actual, preservando los datos de usuario.

        Las carpetas 'configuraciones/', 'Grabaciones_Epub-TTS/' y 'bin/' no
        se tocan; el resto de archivos se sobreescriben con la versión nueva.

        callback_progreso(mensaje: str, porcentaje: int) — opcional, se invoca
        durante el proceso para informar del avance. Si actualiza la UI, debe
        hacerse mediante wx.CallAfter desde el hilo llamante.

        Devuelve {"ok": bool, "error": str|None}.
        """
        def progreso(msg, pct):
            if callback_progreso:
                callback_progreso(msg, pct)

        try:
            progreso("Conectando con GitHub…", 2)

            req = urllib.request.Request(
                _URL_ZIP,
                headers={"User-Agent": "epub-tts-accesible/updater"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                longitud = int(resp.headers.get("Content-Length") or 0)
                datos = io.BytesIO()
                descargado = 0
                bloque = 65536
                while True:
                    chunk = resp.read(bloque)
                    if not chunk:
                        break
                    datos.write(chunk)
                    descargado += len(chunk)
                    if longitud:
                        pct = int(5 + 45 * descargado / longitud)
                        progreso(
                            f"Descargando… {descargado // 1024} KB"
                            f" de {longitud // 1024} KB",
                            pct,
                        )
                    else:
                        progreso(f"Descargando… {descargado // 1024} KB", 25)

            progreso("Descomprimiendo…", 52)

            dir_tmp = tempfile.mkdtemp(prefix="epub_tts_upd_")
            try:
                datos.seek(0)
                with zipfile.ZipFile(datos) as zf:
                    zf.extractall(dir_tmp)

                # La carpeta raíz del ZIP (ej. "epub-tts-accesible-main")
                entradas = [
                    e for e in os.listdir(dir_tmp)
                    if os.path.isdir(os.path.join(dir_tmp, e))
                ]
                if len(entradas) != 1:
                    return {"ok": False, "error": "Estructura del ZIP inesperada."}

                raiz_zip = os.path.join(dir_tmp, entradas[0])

                # Contar archivos totales para el progreso
                total = sum(len(archs) for _, _, archs in os.walk(raiz_zip))
                copiados = 0

                progreso("Instalando archivos…", 55)

                for carpeta, subcarpetas, archivos in os.walk(raiz_zip):
                    rel = os.path.relpath(carpeta, raiz_zip)

                    # En el nivel raíz del ZIP excluir carpetas de usuario
                    if rel == ".":
                        subcarpetas[:] = [
                            d for d in subcarpetas if d not in _PRESERVAR
                        ]
                        destino = RAIZ
                    else:
                        destino = os.path.join(RAIZ, rel)

                    os.makedirs(destino, exist_ok=True)

                    for archivo in archivos:
                        shutil.copy2(
                            os.path.join(carpeta, archivo),
                            os.path.join(destino, archivo),
                        )
                        copiados += 1
                        if total:
                            pct = int(55 + 40 * copiados / total)
                            progreso(
                                f"Instalando archivos… {copiados}/{total}",
                                pct,
                            )

                progreso("¡Actualización completada!", 100)
                return {"ok": True, "error": None}

            finally:
                shutil.rmtree(dir_tmp, ignore_errors=True)

        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def descargar_en_hilo(self, callback_resultado, callback_progreso=None):
        """
        Lanza descargar_actualizacion() en un hilo daemon.
        callback_resultado(dict) se invoca al terminar.
        callback_progreso(msg, pct) se invoca durante la descarga.
        Si los callbacks tocan la UI, deben envolverse con wx.CallAfter.
        """
        t = threading.Thread(
            target=lambda: callback_resultado(
                self.descargar_actualizacion(callback_progreso)
            ),
            daemon=True,
        )
        t.start()

    # ── Lógica interna ────────────────────────────────────────────────────────

    def _ejecutar(self, callback):
        v_local = self.leer_version_local()

        res_remota = self.obtener_version_remota()
        if res_remota["error"]:
            callback({
                "hay_nueva":      False,
                "version_local":  v_local,
                "version_remota": "—",
                "novedades":      "",
                "error":          res_remota["error"],
            })
            return

        v_remota  = res_remota["version"]
        hay_nueva = self.hay_actualizacion(v_local, v_remota)

        novedades = ""
        if hay_nueva:
            res_nov   = self.obtener_novedades()
            novedades = res_nov["texto"]

        callback({
            "hay_nueva":      hay_nueva,
            "version_local":  v_local,
            "version_remota": v_remota,
            "novedades":      novedades,
            "error":          None,
        })
# ANCLAJE_FIN: COMPROBADOR_ACTUALIZACIONES
