import os
import json
import requests
import sounddevice as sd
import soundfile as sf
import io
from app.config_rutas import ruta_config


class ClienteEleven:
    def __init__(self):
        self.config = {}
        # Parámetros de reproducción (0-100)
        self._velocidad = 50   # 50 = velocidad normal
        self._volumen = 100    # 100 = volumen máximo
        # Sesión reutilizable con soporte para cancelación inmediata.
        self._sesion = requests.Session()
        self._parado = False
        # Buffer de precarga
        self._audio_preparado = None   # (data, fs_efectiva) o None
        self._texto_preparado = None

    def _cargar_config(self):
        try:
            ruta = ruta_config("config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Error] No se pudo leer config_general.json en ClienteEleven: {e}")
        return {}

    def obtener_voces(self):
        return []

    def _llamar_api(self, texto, datos_voz):
        """
        Llama a la API de ElevenLabs y devuelve (data, fs_efectiva).
        No reproduce el audio — solo lo descarga y decodifica.
        """
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
        """Sintetiza y reproduce el texto. Usa audio pre-descargado si está disponible."""
        self._parado = False

        if self._audio_preparado is not None and self._texto_preparado == texto:
            data, fs_efectiva = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            print(f"[ElevenLabs] Usando audio pre-descargado (sin latencia de API).")
        else:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)

        if not self._parado:
            sd.play(data, fs_efectiva)
            sd.wait()

    def preparar(self, texto, datos_voz):
        """Pre-descarga el audio y lo cachea para reproducción sin latencia."""
        try:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            if not self._parado:
                self._audio_preparado = (data, fs_efectiva)
                self._texto_preparado = texto
                print(f"[ElevenLabs] Precarga completada ({len(texto)} chars).")
        except Exception as e:
            print(f"[ElevenLabs] Error en precarga: {e}")
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        """
        Detiene el audio y cancela cualquier petición HTTP activa cerrando la sesión.
        Una sesión nueva queda lista para la siguiente petición.
        """
        self._parado = True
        self._audio_preparado = None
        self._texto_preparado = None
        try:
            self._sesion.close()
            self._sesion = requests.Session()
        except Exception as e:
            print(f"[Aviso] Error al cerrar sesión ElevenLabs: {e}")
        try:
            sd.stop()
        except Exception:
            pass

    def pausar(self):
        self.detener()

    def reanudar(self):
        pass

    def fijar_velocidad(self, v):
        self._velocidad = max(0, min(100, int(v)))

    def fijar_volumen(self, v):
        self._volumen = max(0, min(100, int(v)))
