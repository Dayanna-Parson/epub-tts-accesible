import os
import json
import requests
import sounddevice as sd
import soundfile as sf
import io
from app.config_rutas import ruta_config

_MAX_CACHE = 5


class ClienteEleven:
    def __init__(self):
        self.config = {}
        self._velocidad = 50
        self._volumen = 100
        self._sesion = requests.Session()
        self._parado = False
        self._audio_preparado = None
        self._texto_preparado = None
        self._cache_frags = {}
        self._cache_lru = []

    def _cargar_config(self):
        try:
            ruta = ruta_config("ajustes.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Error] No se pudo leer ajustes.json en ClienteEleven: {e}")
        return {}

    def obtener_voces(self):
        return []

    def _guardar_en_cache(self, texto, data, fs):
        if texto not in self._cache_frags:
            if len(self._cache_lru) >= _MAX_CACHE:
                clave_antigua = self._cache_lru.pop(0)
                self._cache_frags.pop(clave_antigua, None)
            self._cache_lru.append(texto)
        self._cache_frags[texto] = (data, fs)

    def _llamar_api(self, texto, datos_voz):
        """Llama a la API de ElevenLabs y devuelve (data, fs_efectiva)."""
        self.config = self._cargar_config()
        el_conf = self.config.get("elevenlabs", {})
        key = el_conf.get("api_key")

        if isinstance(datos_voz, dict):
            voice_id = datos_voz.get("id")
        else:
            voice_id = datos_voz

        if not key:
            raise Exception("Falta API Key ElevenLabs")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": key, "Content-Type": "application/json"}
        payload = {"text": texto, "model_id": "eleven_multilingual_v2"}

        response = self._sesion.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            raise Exception(f"Error ElevenLabs: {response.status_code}")

        data, fs = sf.read(io.BytesIO(response.content))

        if self._volumen != 100:
            data = data * (self._volumen / 100.0)

        factor_velocidad = 0.5 + (self._velocidad / 100.0)
        fs_efectiva = int(fs * factor_velocidad)

        return data, fs_efectiva

    def hablar(self, texto, datos_voz):
        """Sintetiza y reproduce el texto. Prioridad: caché → buffer proactivo → API."""
        self._parado = False

        if texto in self._cache_frags:
            data, fs_efectiva = self._cache_frags[texto]
        elif self._audio_preparado is not None and self._texto_preparado == texto:
            data, fs_efectiva = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            self._guardar_en_cache(texto, data, fs_efectiva)
        else:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(texto, data, fs_efectiva)

        if not self._parado:
            sd.play(data, fs_efectiva)
            sd.wait()

    def preparar(self, texto, datos_voz):
        """Pre-descarga el audio en segundo plano. Reutiliza caché si ya existe."""
        if texto in self._cache_frags:
            if not self._parado:
                self._audio_preparado = self._cache_frags[texto]
                self._texto_preparado = texto
            return
        try:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            if not self._parado:
                self._guardar_en_cache(texto, data, fs_efectiva)
                self._audio_preparado = (data, fs_efectiva)
                self._texto_preparado = texto
        except Exception:
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        self._parado = True
        self._audio_preparado = None
        self._texto_preparado = None
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

    def fijar_velocidad(self, v):
        nuevo = max(0, min(100, int(v)))
        if nuevo != self._velocidad:
            self._cache_frags.clear()
            self._cache_lru.clear()
        self._velocidad = nuevo

    def fijar_volumen(self, v):
        nuevo = max(0, min(100, int(v)))
        if nuevo != self._volumen:
            self._cache_frags.clear()
            self._cache_lru.clear()
        self._volumen = nuevo
