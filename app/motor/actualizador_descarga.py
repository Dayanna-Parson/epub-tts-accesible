# ANCLAJE_INICIO: ACTUALIZADOR_DESCARGA
"""
actualizador_descarga.py
─────────────────────────
Fase C — Actualizador automático (v3.0).

Descarga el ZIP de la nueva versión desde GitHub a temp/actualizacion/ y
verifica que la estructura de archivos esperada esté completa, sin tocar
la instalación actual en ningún momento. Es el primer tramo del flujo de
actualización descrito en la Sección 4 de planificacion_v3.md; el
lanzamiento de actualizador.exe y el cierre de la app se añaden en un paso
posterior, una vez validado este tramo.

Si la verificación falla, temp/actualizacion/ se limpia por completo y no
se toca ningún archivo de la instalación — el aviso y el aborto seguro los
gestiona la interfaz a partir del resultado devuelto aquí.

Diseño (mismo patrón que comprobador_actualizaciones.py):
  - Sin dependencias wx (motor puro, testeable de forma independiente).
  - Toda la red se hace mediante urllib.request (stdlib, sin pip extras).
  - descargar_y_verificar_en_hilo(callback) lanza el trabajo en un hilo
    daemon para que la UI no se bloquee durante la descarga.
"""

import io
import logging
import os
import shutil
import threading
import urllib.request
import zipfile

from app.config_rutas import RAIZ

logger = logging.getLogger(__name__)

_URL_ZIP = (
    "https://github.com/Dayanna-Parson/epub-tts-accesible"
    "/archive/refs/heads/main.zip"
)

_TIMEOUT_DESCARGA = 120   # segundos de espera por la descarga del ZIP

_CARPETA_TEMP = os.path.join(RAIZ, "temp", "actualizacion")

# Rutas (relativas a la raíz del ZIP) que deben existir para considerar
# completa la nueva versión descargada. Si falta cualquiera, se aborta.
_ESTRUCTURA_ESPERADA = (
    "app",
    "iniciar_epub_tts.py",
    os.path.join("recursos", "version.json"),
)


class GestorDescargaActualizacion:
    """
    Descarga y verifica una nueva versión en temp/actualizacion/, sin
    tocar la instalación actual.

    Uso típico desde la UI (hilo principal):
        gestor = GestorDescargaActualizacion()
        gestor.descargar_y_verificar_en_hilo(
            callback_resultado=lambda r: wx.CallAfter(mi_handler, r),
            callback_progreso=lambda msg, pct: wx.CallAfter(mi_progreso, msg, pct),
        )

    El dict de resultado tiene la forma:
        {
          "ok":            bool,
          "ruta_extraida": str | None,  # carpeta raíz del ZIP ya descomprimido
          "error":         str | None,
        }
    """

    def descargar_y_verificar_en_hilo(self, callback_resultado, callback_progreso=None):
        """
        Lanza descargar_y_verificar() en un hilo daemon.
        callback_resultado(dict) se invoca al terminar.
        callback_progreso(msg, pct) se invoca durante el proceso.
        Si los callbacks tocan la UI, deben envolverse con wx.CallAfter.
        """
        t = threading.Thread(
            target=lambda: callback_resultado(
                self.descargar_y_verificar(callback_progreso)
            ),
            daemon=True,
        )
        t.start()

    def descargar_y_verificar(self, callback_progreso=None) -> dict:
        """
        Descarga el ZIP de la última versión a temp/actualizacion/, lo
        descomprime ahí mismo y verifica que la estructura esperada esté
        completa. No toca ningún archivo fuera de temp/actualizacion/.

        Devuelve {"ok": bool, "ruta_extraida": str|None, "error": str|None}.
        """
        def progreso(msg, pct):
            if callback_progreso:
                callback_progreso(msg, pct)

        try:
            # Empezar siempre desde una carpeta limpia: restos de un intento
            # anterior (fallido o interrumpido) no deben mezclarse con este.
            if os.path.exists(_CARPETA_TEMP):
                shutil.rmtree(_CARPETA_TEMP, ignore_errors=True)
            os.makedirs(_CARPETA_TEMP, exist_ok=True)

            progreso("Conectando con GitHub…", 2)

            req = urllib.request.Request(
                _URL_ZIP,
                headers={"User-Agent": "epub-tts-accesible/updater"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_DESCARGA) as resp:
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
                        pct = int(5 + 65 * descargado / longitud)
                        progreso(
                            f"Descargando… {descargado // 1024} KB"
                            f" de {longitud // 1024} KB",
                            pct,
                        )
                    else:
                        progreso(f"Descargando… {descargado // 1024} KB", 35)

            progreso("Descomprimiendo…", 72)

            datos.seek(0)
            with zipfile.ZipFile(datos) as zf:
                zf.extractall(_CARPETA_TEMP)

            # La carpeta raíz del ZIP (ej. "epub-tts-accesible-main")
            entradas = [
                e for e in os.listdir(_CARPETA_TEMP)
                if os.path.isdir(os.path.join(_CARPETA_TEMP, e))
            ]
            if len(entradas) != 1:
                shutil.rmtree(_CARPETA_TEMP, ignore_errors=True)
                return {
                    "ok": False,
                    "ruta_extraida": None,
                    "error": "Estructura del ZIP inesperada: no se encontró una única carpeta raíz.",
                }

            raiz_extraida = os.path.join(_CARPETA_TEMP, entradas[0])

            progreso("Verificando la nueva versión…", 90)

            faltante = self._verificar_estructura(raiz_extraida)
            if faltante:
                shutil.rmtree(_CARPETA_TEMP, ignore_errors=True)
                return {
                    "ok": False,
                    "ruta_extraida": None,
                    "error": f"La descarga está incompleta: falta «{faltante}».",
                }

            progreso("Verificación correcta.", 100)
            return {"ok": True, "ruta_extraida": raiz_extraida, "error": None}

        except Exception as exc:
            logger.exception("Error descargando o verificando la actualización")
            shutil.rmtree(_CARPETA_TEMP, ignore_errors=True)
            return {"ok": False, "ruta_extraida": None, "error": str(exc)}

    def _verificar_estructura(self, raiz_extraida: str):
        """
        Comprueba que todas las rutas de _ESTRUCTURA_ESPERADA existan dentro
        de raiz_extraida. Devuelve la primera ruta que falte, o None si la
        estructura está completa.
        """
        for relativa in _ESTRUCTURA_ESPERADA:
            if not os.path.exists(os.path.join(raiz_extraida, relativa)):
                return relativa
        return None

    def limpiar(self):
        """Elimina temp/actualizacion/ por completo, si existe."""
        shutil.rmtree(_CARPETA_TEMP, ignore_errors=True)
# ANCLAJE_FIN: ACTUALIZADOR_DESCARGA
