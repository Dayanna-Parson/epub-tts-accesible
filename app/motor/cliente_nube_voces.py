import json
import os
import requests
import warnings

from app.config_rutas import ruta_config, cargar_claves

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
        self.ruta_cache_voces = ruta_config("voces_disponibles.json")

        # Estructura base para guardar las voces
        self.voces_cache = {
            "azure": [],
            "polly": [],
            "elevenlabs": [],
            "deepgram": [],
        }

    def cargar_configuracion(self):
        """Lee las claves API desde configuraciones/claves_api.json."""
        return cargar_claves()

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

        # 4. ACTUALIZAR DEEPGRAM (Vía REST API)
        datos_dg = config.get("deepgram", {})
        key_dg = datos_dg.get("api_key", "").strip()

        if key_dg:
            try:
                voces = self._descargar_deepgram(key_dg)
                self.voces_cache["deepgram"] = voces
                resumen.append(f"Deepgram: {len(voces)} voces encontradas.")
            except Exception as e:
                resumen.append(f"Deepgram Error: {str(e)}")
        else:
            resumen.append("Deepgram: Falta API Key.")

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

        # Consulta explícita por motor para garantizar voces generative y long-form.
        # describe_voices() sin Engine devuelve todas las voces, pero en ciertas regiones
        # o versiones de la API las voces de estos motores solo aparecen al filtrar.
        voces_por_id = {v["id"]: v for v in voces_procesadas}
        for engine_extra in ("generative", "long-form"):
            try:
                resp_extra = cliente.describe_voices(Engine=engine_extra)
                for v in resp_extra.get("Voices", []):
                    id_voz = v.get("Id")
                    motores_extra = v.get("SupportedEngines", [engine_extra])
                    if id_voz not in voces_por_id:
                        genero_raw = v.get("Gender", "")
                        genero = "Female" if genero_raw == "Female" else "Male"
                        voz_nueva = {
                            "nombre": v.get("Name"),
                            "id": id_voz,
                            "idioma": v.get("LanguageCode"),
                            "genero": genero,
                            "proveedor": "Amazon Polly",
                            "motores": motores_extra,
                            "es_nueva": True,
                        }
                        voces_procesadas.append(voz_nueva)
                        voces_por_id[id_voz] = voz_nueva
                    else:
                        existente = voces_por_id[id_voz]
                        for m in motores_extra:
                            if m not in existente["motores"]:
                                existente["motores"].append(m)
                        existente["es_nueva"] = any(
                            m in existente["motores"]
                            for m in ("generative", "long-form", "neural")
                        )
            except Exception as e:
                print(f"[Polly] Motor '{engine_extra}' no disponible en esta región: {e}")

        return voces_procesadas

    # ANCLAJE_INICIO: VOCES_DEEPGRAM_HARDCODED
    _VOCES_DEEPGRAM_BASE = [
        {"nombre": "Asteria",   "id": "aura-2-asteria-en",   "idioma": "en-US", "genero": "Female"},
        {"nombre": "Luna",      "id": "aura-2-luna-en",      "idioma": "en-US", "genero": "Female"},
        {"nombre": "Stella",    "id": "aura-2-stella-en",    "idioma": "en-US", "genero": "Female"},
        {"nombre": "Athena",    "id": "aura-2-athena-en",    "idioma": "en-US", "genero": "Female"},
        {"nombre": "Hera",      "id": "aura-2-hera-en",      "idioma": "en-US", "genero": "Female"},
        {"nombre": "Helena",    "id": "aura-2-helena-en",    "idioma": "en-US", "genero": "Female"},
        {"nombre": "Thalia",    "id": "aura-2-thalia-en",    "idioma": "en-US", "genero": "Female"},
        {"nombre": "Andromeda", "id": "aura-2-andromeda-en", "idioma": "en-US", "genero": "Female"},
        {"nombre": "Orion",     "id": "aura-2-orion-en",     "idioma": "en-US", "genero": "Male"},
        {"nombre": "Arcas",     "id": "aura-2-arcas-en",     "idioma": "en-US", "genero": "Male"},
        {"nombre": "Perseus",   "id": "aura-2-perseus-en",   "idioma": "en-US", "genero": "Male"},
        {"nombre": "Angus",     "id": "aura-2-angus-en",     "idioma": "en-US", "genero": "Male"},
        {"nombre": "Orpheus",   "id": "aura-2-orpheus-en",   "idioma": "en-US", "genero": "Male"},
        {"nombre": "Helios",    "id": "aura-2-helios-en",    "idioma": "en-US", "genero": "Male"},
        {"nombre": "Zeus",      "id": "aura-2-zeus-en",      "idioma": "en-US", "genero": "Male"},
        {"nombre": "Celeste",   "id": "aura-2-celeste-es",   "idioma": "es-ES", "genero": "Female"},
        {"nombre": "Cora",      "id": "aura-2-cora-es",      "idioma": "es-ES", "genero": "Female"},
    ]
    # ANCLAJE_FIN: VOCES_DEEPGRAM_HARDCODED

    def _descargar_deepgram(self, api_key: str) -> list:
        """
        Obtiene la lista de modelos TTS de Deepgram consultando /v1/models.
        Si la petición falla o devuelve resultados vacíos, usa la lista base integrada.
        """
        idioma_map = {
            "en": "en-US", "es": "es-ES", "de": "de-DE",
            "fr": "fr-FR", "nl": "nl-NL", "it": "it-IT", "ja": "ja-JP",
        }

        def _parsear_modelos(modelos_tts):
            voces = []
            for m in modelos_tts:
                nombre_id = m.get("name", "")
                if not nombre_id:
                    continue
                partes = nombre_id.split("-")
                if len(partes) < 4:
                    continue
                lang_code  = partes[-1]
                nombre_voz = "-".join(partes[2:-1]).capitalize()
                meta       = m.get("metadata", {})
                genero_raw = meta.get("gender", "").lower()
                genero     = "Female" if genero_raw == "female" else "Male"
                voces.append({
                    "nombre":    nombre_voz,
                    "id":        nombre_id,
                    "idioma":    idioma_map.get(lang_code, lang_code),
                    "genero":    genero,
                    "proveedor": "Deepgram",
                })
            return voces

        try:
            url = "https://api.deepgram.com/v1/models"
            cabeceras = {"Authorization": f"Token {api_key}"}
            respuesta = requests.get(url, headers=cabeceras, timeout=15)

            if respuesta.status_code == 401:
                raise Exception("API Key de Deepgram incorrecta o sin permisos.")
            if respuesta.status_code == 200:
                datos = respuesta.json()
                # La API puede devolver {"tts": [...]} o {"models": [...]} según la versión
                modelos_tts = datos.get("tts") or datos.get("models") or []
                voces = _parsear_modelos(modelos_tts)
                if voces:
                    return voces
        except Exception as e:
            if "incorrecta" in str(e):
                raise
            # Cualquier otro error: caer a la lista base integrada

        # Fallback: lista base con voces Aura-2 confirmadas
        return [
            dict(v, proveedor="Deepgram")
            for v in self._VOCES_DEEPGRAM_BASE
        ]

    def actualizar_proveedor(self, proveedor: str) -> str:
        """
        Descarga y guarda las voces de un único proveedor sin tocar los demás.
        proveedor: "azure" | "polly" | "elevenlabs"
        """
        # Cargar la caché existente para no machacar los otros proveedores
        if os.path.exists(self.ruta_cache_voces):
            try:
                with open(self.ruta_cache_voces, 'r', encoding='utf-8') as f:
                    self.voces_cache = json.load(f)
            except Exception:
                pass

        config = self.cargar_configuracion()

        if proveedor == "azure":
            datos = config.get("azure", {})
            key = datos.get("key", "").strip()
            region = datos.get("region", "").strip()
            if not (key and region):
                return "Azure: Faltan datos (Key/Región)."
            try:
                voces = self._descargar_azure(key, region)
                self.voces_cache["azure"] = voces
                self._guardar_cache()
                return f"Azure: {len(voces)} voces descargadas."
            except Exception as e:
                return f"Azure Error: {e}"

        elif proveedor == "polly":
            datos = config.get("polly", {})
            access_key = datos.get("access_key", "").strip()
            secret_key = datos.get("secret_key", "").strip()
            region = datos.get("region", "us-east-1").strip() or "us-east-1"
            if not (access_key and secret_key):
                return "Amazon Polly: Faltan credenciales (Access Key / Secret Key)."
            try:
                voces = self._descargar_polly(access_key, secret_key, region)
                self.voces_cache["polly"] = voces
                self._guardar_cache()
                return f"Amazon Polly: {len(voces)} voces descargadas."
            except ImportError:
                return "Amazon Polly Error: boto3 no instalado (pip install boto3)."
            except Exception as e:
                return f"Amazon Polly Error: {e}"

        elif proveedor == "elevenlabs":
            datos = config.get("elevenlabs", {})
            key = datos.get("api_key", "").strip()
            if not key:
                return "ElevenLabs: Falta API Key."
            try:
                voces = self._descargar_elevenlabs(key)
                self.voces_cache["elevenlabs"] = voces
                self._guardar_cache()
                return f"ElevenLabs: {len(voces)} voces descargadas."
            except Exception as e:
                return f"ElevenLabs Error: {e}"

        elif proveedor == "deepgram":
            datos = config.get("deepgram", {})
            key = datos.get("api_key", "").strip()
            if not key:
                return "Deepgram: Falta API Key."
            try:
                voces = self._descargar_deepgram(key)
                self.voces_cache["deepgram"] = voces
                self._guardar_cache()
                return f"Deepgram: {len(voces)} voces descargadas."
            except Exception as e:
                return f"Deepgram Error: {e}"

        return f"Proveedor desconocido: {proveedor}"

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
