import json
import os
import requests
import warnings

# Suprimimos advertencias técnicas de conexión segura
warnings.filterwarnings("ignore")

class GestorVoces:
    """
    Clase encargada de conectar con las APIs (Azure, Polly, ElevenLabs) vía HTTP (REST),
    descargar la lista de voces disponibles y guardarlas en un archivo local
    para que la interfaz pueda mostrarlas sin conectarse a internet cada vez.
    """
    def __init__(self):
        # Rutas de archivos
        self.ruta_config = os.path.join("configuraciones", "config_general.json")
        self.ruta_cache_voces = os.path.join("configuraciones", "voces_disponibles.json")
        
        # Estructura base para guardar las voces
        self.voces_cache = {
            "azure": [],
            "polly": [],
            "elevenlabs": []
        }

    def cargar_configuracion(self):
        """Lee las claves API del archivo de configuración."""
        if os.path.exists(self.ruta_config):
            try:
                with open(self.ruta_config, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def actualizar_voces_desde_internet(self):
        """
        Método maestro que llama a todas las APIs y actualiza el archivo local.
        Retorna un resumen de lo que ha pasado (ej: "Azure: 50 voces, Eleven: Error").
        """
        config = self.cargar_configuracion()
        resumen = []

        # 1. ACTUALIZAR AZURE (Vía REST API)
        datos_azure = config.get("azure", {})
        key_az = datos_azure.get("key", "")
        region_az = datos_azure.get("region", "")
        
        if key_az and region_az:
            try:
                voces = self._descargar_azure(key_az, region_az)
                self.voces_cache["azure"] = voces
                resumen.append(f"Azure: {len(voces)} voces encontradas.")
            except Exception as e:
                resumen.append(f"Azure Error: {str(e)}")
        else:
            resumen.append("Azure: Faltan datos (Key/Región).")

        # 2. ACTUALIZAR ELEVENLABS (Vía REST API)
        datos_eleven = config.get("elevenlabs", {})
        key_el = datos_eleven.get("api_key", "")
        
        if key_el:
            try:
                voces = self._descargar_elevenlabs(key_el)
                self.voces_cache["elevenlabs"] = voces
                resumen.append(f"ElevenLabs: {len(voces)} voces encontradas.")
            except Exception as e:
                resumen.append(f"ElevenLabs Error: {str(e)}")
        else:
            resumen.append("ElevenLabs: Falta API Key.")

        # 3. ACTUALIZAR POLLY (Requiere librería extra boto3, lo dejamos pendiente)
        resumen.append("Polly: (Pendiente de configuración)")

        # GUARDAR EN DISCO
        self._guardar_cache()
        return "\n".join(resumen)

    def _descargar_azure(self, key, region):
        """
        Conecta con la API REST de Azure y baja el JSON de voces.
        Documentación oficial: https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech
        """
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        headers = {
            "Ocp-Apim-Subscription-Key": key
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            lista_cruda = response.json()
            voces_procesadas = []
            
            for v in lista_cruda:
                # Extraemos solo lo útil para nuestra app
                voz = {
                    "nombre": v.get("LocalName", v.get("ShortName")), # Ej: Conchita
                    "id": v.get("ShortName"),       # Ej: es-ES-ConchitaNeural
                    "idioma": v.get("Locale"),      # Ej: es-ES
                    "genero": v.get("Gender"),      # Ej: Female
                    "proveedor": "Azure"
                }
                voces_procesadas.append(voz)
            
            return voces_procesadas
        elif response.status_code == 401:
            raise Exception("Clave de Azure incorrecta o caducada.")
        elif response.status_code == 404:
            raise Exception("Región de Azure incorrecta.")
        else:
            raise Exception(f"Error de conexión: {response.status_code}")

    def _descargar_elevenlabs(self, api_key):
        """Conecta con la API de ElevenLabs."""
        url = "https://api.elevenlabs.io/v1/voices"
        headers = {
            "xi-api-key": api_key
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            datos = response.json()
            lista_cruda = datos.get("voices", [])
            voces_procesadas = []
            
            for v in lista_cruda:
                voz = {
                    "nombre": v.get("name"),
                    "id": v.get("voice_id"),
                    "idioma": "Multilingüe (v2)", # Eleven suele ser multi
                    "proveedor": "ElevenLabs",
                    "etiquetas": v.get("labels", {}) 
                }
                voces_procesadas.append(voz)
            
            return voces_procesadas
        elif response.status_code == 401:
            raise Exception("API Key de ElevenLabs incorrecta.")
        else:
            raise Exception(f"Error ElevenLabs: {response.status_code}")

    def _guardar_cache(self):
        """Guarda el diccionario completo en voces_disponibles.json"""
        try:
            os.makedirs(os.path.dirname(self.ruta_cache_voces), exist_ok=True)
            with open(self.ruta_cache_voces, 'w', encoding='utf-8') as f:
                json.dump(self.voces_cache, f, indent=4)
        except Exception as e:
            print(f"Error guardando caché de voces: {e}")

    def obtener_todas_las_voces(self):
        """Devuelve el diccionario de voces guardado. Si no existe, devuelve vacío."""
        if os.path.exists(self.ruta_cache_voces):
            try:
                with open(self.ruta_cache_voces, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return self.voces_cache
        return self.voces_cache