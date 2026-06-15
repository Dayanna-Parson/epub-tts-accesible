# ANCLAJE_INICIO: CLIENTE_DEEPGRAM
import io
import logging
import time

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from app.config_rutas import cargar_claves

logger = logging.getLogger(__name__)

_MAX_CACHE = 5
_URL_SPEAK  = "https://api.deepgram.com/v1/speak"
_URL_MODELS = "https://api.deepgram.com/v1/models"

# Modelo predeterminado cuando datos_voz no especifica ninguno
_MODELO_DEFAULT = "aura-2-thalia-en"


class ClienteDeepgram:
    """
    Cliente TTS para Deepgram Aura-2.

    Realiza peticiones REST directas sin SDK:
      POST https://api.deepgram.com/v1/speak
      Authorization: Token <api_key>
      Content-Type: application/json
      Body: {"text": "..."}
      Query: ?model=aura-2-thalia-en&encoding=mp3

    La respuesta es audio MP3 que se decodifica y reproduce con soundfile/sounddevice,
    siguiendo el mismo patrón que ClienteAzure y ClienteEleven.
    """

    def __init__(self):
        self._velocidad = 50
        self._volumen   = 100
        self._sesion    = requests.Session()
        self._parado    = False
        self._audio_preparado = None
        self._texto_preparado = None
        self._cache_frags: dict = {}
        self._cache_lru:   list = []

    def _cargar_config(self) -> dict:
        return cargar_claves()

    def obtener_voces(self) -> list:
        return []

    # ── Caché LRU ─────────────────────────────────────────────────────────────

    def _guardar_en_cache(self, texto: str, data, fs: int):
        if texto not in self._cache_frags:
            if len(self._cache_lru) >= _MAX_CACHE:
                clave_antigua = self._cache_lru.pop(0)
                self._cache_frags.pop(clave_antigua, None)
            self._cache_lru.append(texto)
        self._cache_frags[texto] = (data, fs)

    # ── División de texto largo ────────────────────────────────────────────────

    # ANCLAJE_INICIO: DIVISOR_TEXTO_DEEPGRAM
    _LIMITE_API = 1900  # margen de seguridad sobre el límite oficial de 2000 chars

    def _dividir_texto(self, texto: str) -> list:
        """
        Divide el texto en fragmentos que no superen _LIMITE_API caracteres.
        Respeta los finales de frase (punto, interrogación, exclamación, punto y coma)
        para que cada fragmento sea fonéticamente coherente.
        """
        if len(texto) <= self._LIMITE_API:
            return [texto]
        fragmentos = []
        while texto:
            if len(texto) <= self._LIMITE_API:
                fragmentos.append(texto.strip())
                break
            # Buscar el final de frase más tardío dentro del límite
            corte = -1
            for sep in ('. ', '! ', '? ', '; ', '\n'):
                pos = texto.rfind(sep, 0, self._LIMITE_API)
                if pos != -1:
                    candidato = pos + len(sep)
                    if candidato > corte:
                        corte = candidato
            if corte <= 0:
                corte = self._LIMITE_API  # sin separador: cortar en el límite
            fragmento = texto[:corte].strip()
            if fragmento:
                fragmentos.append(fragmento)
            texto = texto[corte:].strip()
        return fragmentos

    def _sintetizar_fragmentos(self, texto: str, datos_voz):
        """
        Llama a la API por cada fragmento del texto dividido y concatena
        los arrays de audio resultantes en un único bloque reproducible.
        Si se detecta una parada intencional entre fragmentos, devuelve None.
        """
        fragmentos = self._dividir_texto(texto)
        partes = []
        fs_comun = None
        for frag in fragmentos:
            if self._parado:
                return None, None
            data, fs = self._llamar_api(frag, datos_voz)
            if fs_comun is None:
                fs_comun = fs
            partes.append(data)
        if not partes:
            return None, None
        return np.concatenate(partes, axis=0), fs_comun
    # ANCLAJE_FIN: DIVISOR_TEXTO_DEEPGRAM

    # ── Llamada HTTP ──────────────────────────────────────────────────────────

    def _llamar_api(self, texto: str, datos_voz):
        """Envía texto a la API de Deepgram y devuelve (data_numpy, sample_rate)."""
        config  = self._cargar_config()
        api_key = config.get("deepgram", {}).get("api_key", "").strip()
        if not api_key:
            raise Exception("Falta API Key de Deepgram.")

        if isinstance(datos_voz, dict):
            modelo = datos_voz.get("id") or _MODELO_DEFAULT
        else:
            modelo = datos_voz or _MODELO_DEFAULT

        cabeceras = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        # encoding=mp3 es el predeterminado de Deepgram; lo indicamos explícitamente
        # para que la respuesta pueda ser leída por soundfile sin conversión adicional.
        params = {"model": modelo, "encoding": "mp3"}
        cuerpo = {"text": texto}

        respuesta = None
        for intento in range(2):
            try:
                respuesta = self._sesion.post(
                    _URL_SPEAK,
                    headers=cabeceras,
                    params=params,
                    json=cuerpo,
                    timeout=30,
                )
                break
            except requests.exceptions.Timeout:
                raise Exception("Deepgram tardó demasiado (Timeout > 30s).")
            except requests.exceptions.ConnectionError:
                if intento == 0 and not self._parado:
                    time.sleep(1)
                    self._sesion = requests.Session()
                    continue
                raise

        if respuesta is None or respuesta.status_code != 200:
            codigo = respuesta.status_code if respuesta else "sin respuesta"
            detalle = ""
            if respuesta is not None:
                try:
                    detalle = respuesta.json().get("err_msg", "")
                except Exception:
                    pass
            raise Exception(f"Error Deepgram: {codigo} {detalle}".strip())

        data, fs = sf.read(io.BytesIO(respuesta.content))
        return data, fs

    # ── Reproducción ──────────────────────────────────────────────────────────

    def hablar(self, texto: str, datos_voz):
        """
        Sintetiza y reproduce el texto. Prioridad: caché → buffer proactivo → API.
        Si el texto supera el límite de la API (2000 caracteres), se divide
        automáticamente en fragmentos, se sintetiza cada uno por separado y los
        arrays de audio se concatenan antes de reproducir.
        """
        self._parado = False

        if texto in self._cache_frags:
            data, fs = self._cache_frags[texto]
        elif self._audio_preparado is not None and self._texto_preparado == texto:
            data, fs = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            self._guardar_en_cache(texto, data, fs)
        elif len(texto) > self._LIMITE_API:
            data, fs = self._sintetizar_fragmentos(texto, datos_voz)
            if data is not None:
                self._guardar_en_cache(texto, data, fs)
        else:
            data, fs = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(texto, data, fs)

        if not self._parado and data is not None:
            sd.play(data, fs)
            sd.wait()

    def preparar(self, texto: str, datos_voz):
        """Pre-descarga el audio del siguiente fragmento en segundo plano."""
        if texto in self._cache_frags:
            self._audio_preparado = self._cache_frags[texto]
            self._texto_preparado = texto
            return
        try:
            data, fs = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(texto, data, fs)
            self._audio_preparado = (data, fs)
            self._texto_preparado = texto
        except Exception:
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        """Detiene el audio y cancela peticiones HTTP activas."""
        self._parado = True
        try:
            self._sesion.close()
            self._sesion = requests.Session()
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass

    def pausar(self):
        self.detener()

    def reanudar(self):
        pass

    def fijar_velocidad(self, v: int):
        nuevo = max(0, min(100, int(v)))
        if nuevo != self._velocidad:
            self._cache_frags.clear()
            self._cache_lru.clear()
        self._velocidad = nuevo

    def fijar_volumen(self, v: int):
        nuevo = max(0, min(100, int(v)))
        if nuevo != self._volumen:
            self._cache_frags.clear()
            self._cache_lru.clear()
        self._volumen = nuevo
# ANCLAJE_FIN: CLIENTE_DEEPGRAM
