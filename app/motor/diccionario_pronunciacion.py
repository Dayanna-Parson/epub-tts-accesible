# ANCLAJE_INICIO: DICCIONARIO_PRONUNCIACION
import json
import logging
import os
import re

from app.config_rutas import ruta_config

logger = logging.getLogger(__name__)

_RUTA = ruta_config("pronunciacion.json")


class DiccionarioPronunciacion:
    """
    Gestiona un diccionario local de sustituciones de pronunciación.

    Formato de pronunciacion.json:
        {
          "NVDA":    "en-ví-di-ei",
          "Tolkien": "Tól-kien",
          "EPUB":    "í-pub"
        }

    Las sustituciones se aplican como coincidencias de palabra completa
    para evitar reemplazos parciales dentro de términos más largos.
    La carga es diferida y se cachea en memoria; llamar a recargar()
    para que los cambios del usuario surtan efecto sin reiniciar.
    """

    def __init__(self):
        self._tabla: dict = self._cargar()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _cargar(self) -> dict:
        try:
            if os.path.exists(_RUTA):
                with open(_RUTA, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            logger.exception("[Pronunciacion] Error al leer pronunciacion.json")
        return {}

    def recargar(self):
        """Invalida la caché y lee el JSON desde disco."""
        self._tabla = self._cargar()

    def guardar(self, tabla: dict):
        """Persiste la tabla en disco de forma atómica."""
        try:
            os.makedirs(os.path.dirname(_RUTA), exist_ok=True)
            ruta_tmp = _RUTA + ".tmp"
            with open(ruta_tmp, "w", encoding="utf-8") as f:
                json.dump(tabla, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(ruta_tmp, _RUTA)
            self._tabla = dict(tabla)
        except Exception:
            logger.exception("[Pronunciacion] Error al guardar pronunciacion.json")

    # ── Aplicación de sustituciones ───────────────────────────────────────────

    def aplicar(self, texto: str) -> str:
        """
        Sustituye en 'texto' cada clave del diccionario por su pronunciación.
        Se buscan coincidencias de palabra completa para evitar reemplazos
        parciales (ej: "EPUB" no debe reemplazarse dentro de "EPUBook").
        """
        if not texto or not self._tabla:
            return texto
        for original, sustitucion in self._tabla.items():
            if not original:
                continue
            patron = r"(?<!\w)" + re.escape(original) + r"(?!\w)"
            texto = re.sub(patron, sustitucion, texto)
        return texto

    # ── CRUD de entradas ──────────────────────────────────────────────────────

    def obtener_tabla(self) -> dict:
        return dict(self._tabla)

    def anadir_entrada(self, original: str, pronunciacion: str):
        self._tabla[original] = pronunciacion
        self.guardar(self._tabla)

    def eliminar_entrada(self, original: str):
        if original in self._tabla:
            del self._tabla[original]
            self.guardar(self._tabla)
# ANCLAJE_FIN: DICCIONARIO_PRONUNCIACION
