# ANCLAJE_INICIO: VERIFICADOR_VOCES_NUEVAS
"""
verificador_voces_nuevas.py
───────────────────────────
Detecta automáticamente voces nuevas comparando el estado local
(voces_disponibles.json) con la respuesta fresca de cada API.

Flujo:
  1. Lee los IDs de voces_disponibles.json  →  snapshot "conocidas".
  2. Llama a GestorVoces.actualizar_voces_desde_internet() (reutiliza clientes existentes).
  3. Compara IDs descargados vs snapshot: las que faltan en el snapshot son "nuevas".
  4. Invoca callback({"nuevas": {proveedor: [nombres]}, "error": str|None}).
  5. Actualiza voces_conocidas.json con los IDs actuales.

Cooldown: una sola comprobación cada 24 horas (evita llamadas innecesarias a las APIs).
El timestamp se persiste en configuraciones/voces_ultima_comprobacion.json.

Primera ejecución (sin historial previo): guarda el snapshot sin notificar.
"""

import datetime
import json
import os
import threading

from app.config_rutas import ruta_config
from app.motor.cliente_nube_voces import GestorVoces

_RUTA_TIMESTAMP  = ruta_config("voces_ultima_comprobacion.json")
_COOLDOWN_HORAS  = 24


# ═════════════════════════════════════════════════════════════════════════════
class VerificadorVocesNuevas:
    """
    Motor de detección de voces nuevas. Sin dependencias wx.

    Uso típico desde el hilo principal de la UI:
        v = VerificadorVocesNuevas()
        if v.puede_verificar():
            v.verificar_en_hilo(mi_callback)

    El callback recibe un dict y es invocado desde el hilo de fondo.
    Si el callback modifica la UI, debe usar wx.CallAfter internamente.
    """

    # ── Cooldown ──────────────────────────────────────────────────────────────

    def puede_verificar(self) -> bool:
        """
        Devuelve True si han pasado más de _COOLDOWN_HORAS desde la última
        comprobación, o si nunca se ha comprobado.
        Operación rápida (solo lectura de un JSON pequeño).
        """
        try:
            if os.path.exists(_RUTA_TIMESTAMP):
                with open(_RUTA_TIMESTAMP, "r", encoding="utf-8") as f:
                    datos = json.loads(f.read())
                ultima = datetime.datetime.fromisoformat(datos.get("ultima", ""))
                delta = datetime.datetime.now() - ultima
                return delta.total_seconds() > _COOLDOWN_HORAS * 3600
        except Exception:
            pass
        return True

    # ── Ejecución asíncrona ───────────────────────────────────────────────────

    def verificar_en_hilo(self, callback_resultado):
        """
        Lanza la verificación en un hilo daemon (no bloquea la UI).

        callback_resultado(dict) se llama desde ese hilo de fondo cuando
        termina. El dict tiene la forma:
          {
            "nuevas": {
              "azure":      ["Nombre voz 1", ...],
              "polly":      [...],
              "elevenlabs": [...],
            },
            "error": str | None   # mensaje de error si algo falló
          }
        """
        t = threading.Thread(
            target=self._ejecutar,
            args=(callback_resultado,),
            daemon=True,
        )
        t.start()

    # ── Lógica interna ────────────────────────────────────────────────────────

    def _ejecutar(self, callback):
        try:
            # 1. Snapshot local ANTES de descargar
            ids_conocidos = self._leer_ids_locales()

            # 2. Descargar voces frescas (reutiliza GestorVoces y sus clientes)
            gestor = GestorVoces()
            gestor.actualizar_voces_desde_internet()

            # 3. Guardar timestamp de esta comprobación
            self._guardar_timestamp()

            voces_actuales = gestor.obtener_todas_las_voces()

            # 4. Primera vez (sin snapshot): guardar baseline y no notificar
            if not ids_conocidos:
                self._guardar_conocidas(voces_actuales)
                callback({"nuevas": {}, "error": None})
                return

            # 5. Detectar novedades
            nuevas = self._detectar_nuevas(voces_actuales, ids_conocidos)

            # 6. Actualizar voces_conocidas.json con el estado actual
            self._guardar_conocidas(voces_actuales)

            callback({"nuevas": nuevas, "error": None})

        except Exception as exc:
            callback({"nuevas": {}, "error": str(exc)})

    def _leer_ids_locales(self) -> set:
        """
        Lee los IDs de voces_disponibles.json (estado previo a la descarga).
        Devuelve un set vacío si el archivo no existe o hay error.
        """
        try:
            ruta = ruta_config("voces_disponibles.json")
            if os.path.exists(ruta):
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.loads(f.read())
                return {
                    v.get("id", "")
                    for lista in datos.values()
                    for v in lista
                    if v.get("id")
                }
        except Exception:
            pass
        return set()

    def _detectar_nuevas(self, voces_dict: dict, ids_conocidos: set) -> dict:
        """
        Compara voces_dict (descargadas) con ids_conocidos (snapshot previo).
        Devuelve {proveedor: [nombre_voz, ...]} solo para proveedores con novedades.
        """
        nuevas = {}
        for proveedor, lista in voces_dict.items():
            voces_nuevas = [
                voz.get("nombre", voz.get("id", "—"))
                for voz in lista
                if voz.get("id") and voz["id"] not in ids_conocidos
            ]
            if voces_nuevas:
                nuevas[proveedor] = voces_nuevas
        return nuevas

    def _guardar_timestamp(self):
        try:
            os.makedirs(os.path.dirname(_RUTA_TIMESTAMP), exist_ok=True)
            with open(_RUTA_TIMESTAMP, "w", encoding="utf-8") as f:
                json.dump(
                    {"ultima": datetime.datetime.now().isoformat()},
                    f,
                    ensure_ascii=False,
                )
        except Exception:
            pass

    def _guardar_conocidas(self, voces_dict: dict):
        """
        Persiste los IDs actuales en voces_conocidas.json.
        Este archivo también lo usa PanelVoces para marcar 'es_nueva'.
        """
        try:
            ruta = ruta_config("voces_conocidas.json")
            ids = [
                v.get("id", "")
                for lista in voces_dict.values()
                for v in lista
                if v.get("id")
            ]
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(ids, f, ensure_ascii=False)
        except Exception:
            pass
# ANCLAJE_FIN: VERIFICADOR_VOCES_NUEVAS
