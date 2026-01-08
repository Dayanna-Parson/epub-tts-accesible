import os
import json
import requests
import sounddevice as sd
import soundfile as sf
import io
import time # Para medir el tiempo

class ClienteAzure:
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

    def _limpiar_texto_xml(self, texto):
        """
        Elimina símbolos que rompen Azure.
        Si el libro tiene < o >, Azure se cree que son instrucciones y falla.
        """
        t = texto.replace("&", "y") # El & rompe XML
        t = t.replace("<", "")      # Eliminar etiquetas html sueltas
        t = t.replace(">", "")
        t = t.replace('"', "")      # Comillas dobles a veces lían
        t = t.replace("'", "")      # Comillas simples
        return t

    def hablar(self, texto, datos_voz):
        inicio = time.time()
        print(f"--> [Azure] Iniciando petición...")
        
        self.config = self._cargar_config()
        az_conf = self.config.get("azure", {})
        key = az_conf.get("key")
        region = az_conf.get("region")
        idioma_destino = self.config.get("idioma_libro_codigo", "es-ES")
        
        if not key or not region: raise Exception("Faltan claves de Azure")

        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"
        }
        
        if isinstance(datos_voz, dict):
            id_voz = datos_voz.get("id")
        else:
            id_voz = datos_voz

        # 1. LIMPIEZA
        texto_limpio = self._limpiar_texto_xml(texto)
        print(f"--> [Azure] Texto limpio ({len(texto_limpio)} caracteres). Enviando...")

        # 2. SSML
        ssml = f"""
        <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{idioma_destino}'>
            <voice name='{id_voz}'>
                <lang xml:lang='{idioma_destino}'>
                    {texto_limpio}
                </lang>
            </voice>
        </speak>
        """

        # 3. ENVÍO (Timeout subido a 30s)
        try:
            response = requests.post(url, headers=headers, data=ssml.encode('utf-8'), timeout=30)
        except requests.exceptions.Timeout:
            raise Exception("Azure tardó demasiado (Timeout > 30s).")

        tiempo_total = time.time() - inicio
        print(f"--> [Azure] Respuesta recibida en {tiempo_total:.2f} segundos.")
        
        if response.status_code == 200:
            data, fs = sf.read(io.BytesIO(response.content))
            sd.play(data, fs)
            sd.wait()
        else:
            raise Exception(f"Error Azure: {response.status_code} - {response.text}")
    def detener(self):
        try: sd.stop()
        except: pass