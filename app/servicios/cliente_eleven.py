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

    def hablar(self, texto, datos_voz):
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

        # La petición se realiza a través de la sesión gestionada.
        # Si detener() cierra la sesión, requests lanzará ConnectionError
        # que el reproductor captura y descarta según el contador de generación.
        response = self._sesion.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            data, fs = sf.read(io.BytesIO(response.content))

            # Aplicar volumen multiplicando la señal (100 = sin cambio)
            if self._volumen != 100:
                data = data * (self._volumen / 100.0)

            # Ajustar velocidad cambiando la tasa de muestreo efectiva.
            # factor=1.0 en v=50 (normal); factor=0.5 en v=0 (lento); factor=1.5 en v=100 (rápido).
            # Nota: altera ligeramente el tono al cambiar la velocidad.
            factor_velocidad = 0.5 + (self._velocidad / 100.0)
            fs_efectiva = int(fs * factor_velocidad)

            sd.play(data, fs_efectiva)
            sd.wait()
        else:
            raise Exception(f"Error ElevenLabs: {response.status_code}")

    def detener(self):
        """
        Detiene el audio y cancela cualquier petición HTTP activa cerrando la sesión.
        Una sesión nueva queda lista para la siguiente petición.
        """
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
