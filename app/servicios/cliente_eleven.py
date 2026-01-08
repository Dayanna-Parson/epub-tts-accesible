import os
import json
import requests
import sounddevice as sd
import soundfile as sf
import io

class ClienteEleven:
    def __init__(self):
        self.config = {}

    def _cargar_config(self):
        try:
            ruta = os.path.join("configuraciones", "config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except: pass
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

        if not key: raise Exception("Falta API Key ElevenLabs")
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": key, "Content-Type": "application/json"}
        data = {"text": texto, "model_id": "eleven_multilingual_v2"}
        
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            data, fs = sf.read(io.BytesIO(response.content))
            sd.play(data, fs)
            sd.wait()
        else:
            raise Exception(f"Error Eleven: {response.status_code}")

    def detener(self):
        try: sd.stop()
        except: pass
        
    def pausar(self): self.detener()
    def reanudar(self): pass
    def fijar_velocidad(self, v): pass
    def fijar_volumen(self, v): pass