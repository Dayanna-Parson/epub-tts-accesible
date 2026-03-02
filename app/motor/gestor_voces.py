import json
import os
import requests
import warnings

from app.config_rutas import ruta_config

# Suprimimos advertencias técnicas de conexión segura
warnings.filterwarnings("ignore")


class GestorVoces:
    """
    Clase encargada de conectar con las APIs (Azure, Polly, ElevenLabs) vía HTTP/SDK,
    descargar la lista de voces disponibles y guardarlas en un archivo local
    para que la interfaz pueda mostrarlas sin conectarse a internet cada vez.
    """
    def __init__(self):
        # Rutas absolutas — evita fallos cuando el CWD no es la raíz del proyecto
        self.ruta_config = ruta_config("config_general.json")
        self.ruta_cache_voces = ruta_config("voces_disponibles.json")

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
            except Exception as e:
                print(f"[GestorVoces] Error leyendo config: {e}")
                return {}
        return {}

    def actualizar_voces_desde_internet(self):
        """
        Método maestro que llama a todas las APIs y actualiza el archivo local.
        Retorna un resumen de lo que ha pasado (ej: "Azure: 50 voces, Polly: 30 voces").
        """
        config = self.cargar_configuracion()
        resumen = []

        # 1. ACTUALIZAR AZURE (Vía REST API)
        datos_azure = config.get("azure", {})
        key_az = datos_azure.get("key", "").strip()
        region_az = datos_azure.get("region", "").strip()

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
        key_el = datos_eleven.get("api_key", "").strip()

        if key_el:
            try:
                voces = self._descargar_elevenlabs(key_el)
                self.voces_cache["elevenlabs"] = voces
                resumen.append(f"ElevenLabs: {len(voces)} voces encontradas.")
            except Exception as e:
                resumen.append(f"ElevenLabs Error: {str(e)}")
        else:
            resumen.append("ElevenLabs: Falta API Key.")

        # 3. ACTUALIZAR AMAZON POLLY (Vía SDK boto3)
        datos_polly = config.get("polly", {})
        access_key_po = datos_polly.get("access_key", "").strip()
        secret_key_po = datos_polly.get("secret_key", "").strip()
        region_po = datos_polly.get("region", "us-east-1").strip() or "us-east-1"

        if access_key_po and secret_key_po:
            try:
                voces = self._descargar_polly(access_key_po, secret_key_po, region_po)
                self.voces_cache["polly"] = voces
                resumen.append(f"Amazon Polly: {len(voces)} voces encontradas.")
            except ImportError:
                resumen.append("Amazon Polly Error: boto3 no está instalado (pip install boto3).")
            except Exception as e:
                resumen.append(f"Amazon Polly Error: {str(e)}")
        else:
            resumen.append("Amazon Polly: Faltan credenciales (Access Key / Secret Key).")

        # GUARDAR EN DISCO
        self._guardar_cache()
        return "\n".join(resumen)

    def _descargar_azure(self, key, region):
        """
        Conecta con la API REST de Azure y baja el JSON de voces.
        """
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        headers = {"Ocp-Apim-Subscription-Key": key}

        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            lista_cruda = response.json()
            voces_procesadas = []
            for v in lista_cruda:
                voz = {
                    "nombre": v.get("LocalName", v.get("ShortName")),
                    "id": v.get("ShortName"),
                    "idioma": v.get("Locale"),
                    "genero": v.get("Gender"),
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
        """Conecta con la API de ElevenLabs y descarga la lista de voces."""
        url = "https://api.elevenlabs.io/v1/voices"
        headers = {"xi-api-key": api_key}

        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            datos = response.json()
            lista_cruda = datos.get("voices", [])
            voces_procesadas = []
            for v in lista_cruda:
                voz = {
                    "nombre": v.get("name"),
                    "id": v.get("voice_id"),
                    "idioma": "Multilingüe (v2)",
                    "proveedor": "ElevenLabs",
                    "etiquetas": v.get("labels", {})
                }
                voces_procesadas.append(voz)
            return voces_procesadas
        elif response.status_code == 401:
            raise Exception("API Key de ElevenLabs incorrecta.")
        else:
            raise Exception(f"Error ElevenLabs: {response.status_code}")

    def _descargar_polly(self, access_key, secret_key, region):
        """
        Conecta con Amazon Polly mediante boto3 y descarga la lista completa de voces.
        Gestiona la paginación automáticamente para obtener todas las voces disponibles.
        Requiere: pip install boto3
        """
        import boto3  # Importación diferida: solo falla si el usuario no tiene boto3

        cliente = boto3.client(
            "polly",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        voces_procesadas = []
        siguiente_token = None

        # describe_voices() está paginada: hay que iterar hasta agotar NextToken
        while True:
            kwargs = {}
            if siguiente_token:
                kwargs["NextToken"] = siguiente_token
            respuesta = cliente.describe_voices(**kwargs)

            for v in respuesta.get("Voices", []):
                motores = v.get("SupportedEngines", [])
                genero_raw = v.get("Gender", "")
                # Mapear género al formato esperado por el filtro de la interfaz
                genero = "Female" if genero_raw == "Female" else "Male"
                voz = {
                    "nombre": v.get("Name"),
                    "id": v.get("Id"),
                    "idioma": v.get("LanguageCode"),
                    "genero": genero,
                    "proveedor": "Amazon Polly",
                    "motores": motores,
                    # Nueva = cualquier motor de mayor calidad que standard
                    "es_nueva": any(m in motores for m in ("generative", "long-form", "neural")),
                }
                voces_procesadas.append(voz)

            siguiente_token = respuesta.get("NextToken")
            if not siguiente_token:
                break

        return voces_procesadas

    def _guardar_cache(self):
        """Guarda el diccionario completo de voces en voces_disponibles.json"""
        try:
            os.makedirs(os.path.dirname(self.ruta_cache_voces), exist_ok=True)
            with open(self.ruta_cache_voces, 'w', encoding='utf-8') as f:
                json.dump(self.voces_cache, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[GestorVoces] Error guardando caché de voces: {e}")

    def obtener_todas_las_voces(self):
        """Devuelve el diccionario de voces guardado. Si no existe, devuelve vacío."""
        if os.path.exists(self.ruta_cache_voces):
            try:
                with open(self.ruta_cache_voces, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return self.voces_cache
        return self.voces_cache
