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
  descargar_actualizacion() está preparada para el día en que el sistema de
  distribución esté definido; por ahora devuelve un aviso informativo.
"""

import json
import os
import threading
import urllib.request

from app.config_rutas import RAIZ

# ── Rutas y URLs ──────────────────────────────────────────────────────────────

_RUTA_VERSION_LOCAL = os.path.join(RAIZ, "version.json")

_URL_BASE = (
    "https://raw.githubusercontent.com"
    "/Dayanna-Parson/epub-tts-accesible/main"
)
_URL_VERSION   = f"{_URL_BASE}/version.json"
_URL_NOVEDADES = f"{_URL_BASE}/novedades.txt"

_TIMEOUT = 10   # segundos de espera por petición HTTP


# ═════════════════════════════════════════════════════════════════════════════
class ComprobadorActualizaciones:
    """
    Motor de comprobación de actualizaciones. Sin dependencias wx.

    Uso típico desde la UI (hilo principal):
        comp = ComprobadorActualizaciones()
        comp.comprobar_en_hilo(
            lambda r: wx.CallAfter(mi_handler, r)
        )

    El dict de resultado tiene la forma:
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

    def descargar_actualizacion(self, url_descarga: str, ruta_destino: str) -> dict:
        """
        [PREPARADA — pendiente de implementar]
        Descargará el instalador/zip de la nueva versión a ruta_destino.
        Se activará cuando el sistema de distribución esté definido.

        Devuelve {"ok": bool, "error": str|None}.
        """
        # TODO: implementar cuando la URL de distribución esté disponible.
        return {
            "ok": False,
            "error": (
                "La descarga automática no está disponible aún en esta versión. "
                "Visita el repositorio de GitHub para descargar la actualización."
            ),
        }

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
