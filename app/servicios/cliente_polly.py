import os
import json
import io
import time
import sounddevice as sd
import soundfile as sf
from app.config_rutas import ruta_config

# ── Comprobación inmediata de boto3 ──────────────────────────────────────────
# Se comprueba al importar el módulo para que el fallo sea visible desde
# el arranque, en consola Y en el log, no solo cuando el usuario habla.
try:
    import boto3 as _boto3_check
    _BOTO3_DISPONIBLE = True
except ImportError:
    _BOTO3_DISPONIBLE = False
    _MSG_BOTO3 = (
        "boto3 NO está instalado. Amazon Polly no funcionará.\n"
        "Solución: pip install boto3"
    )
    print("=" * 60)
    print(f"[ADVERTENCIA] {_MSG_BOTO3}")
    print("=" * 60)
    # Escribir al log del sistema si ya está configurado (se configura en iniciar_tiflohistorias.py)
    try:
        import logging as _logging
        _logging.getLogger(__name__).warning(_MSG_BOTO3)
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────────────────────

# Mapeo de nombres de región descriptivos a códigos AWS estándar.
_REGIONES_AWS = {
    "us east (north virginia)": "us-east-1",
    "us east (ohio)": "us-east-2",
    "us west (n. california)": "us-west-1",
    "us west (oregon)": "us-west-2",
    "eu (ireland)": "eu-west-1",
    "eu (london)": "eu-west-2",
    "eu (paris)": "eu-west-3",
    "eu (frankfurt)": "eu-central-1",
    "eu (stockholm)": "eu-north-1",
    "ap (tokyo)": "ap-northeast-1",
    "ap (seoul)": "ap-northeast-2",
    "ap (singapore)": "ap-southeast-1",
    "ap (sydney)": "ap-southeast-2",
    "ap (mumbai)": "ap-south-1",
    "ca (central)": "ca-central-1",
    "sa (são paulo)": "sa-east-1",
}

# Códigos AWS reconocidos directamente (se aceptan tal cual en el config)
_CODIGOS_AWS_VALIDOS = {
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-north-1",
    "ap-northeast-1", "ap-northeast-2", "ap-southeast-1", "ap-southeast-2", "ap-south-1",
    "ca-central-1", "sa-east-1",
}


def _normalizar_region(valor):
    """
    Convierte un nombre descriptivo o un código directo al código AWS estándar.
    Si el valor no se reconoce en ninguna forma, devuelve 'us-east-1' como defecto seguro.
    """
    if not valor:
        return "us-east-1"
    limpio = valor.strip()
    normalizado = limpio.lower()
    # 1. Intentar reconocer por nombre descriptivo ("US East (North Virginia)")
    if normalizado in _REGIONES_AWS:
        return _REGIONES_AWS[normalizado]
    # 2. Aceptar código directo reconocido ("us-east-1", "eu-central-1", …)
    if normalizado in _CODIGOS_AWS_VALIDOS:
        return normalizado
    # 3. Valor no reconocido → región por defecto estricta
    return "us-east-1"


_MAX_CACHE = 5  # Máximo de fragmentos en caché por cliente


class ClientePolly:
    def __init__(self):
        self._velocidad = 50
        self._volumen = 100
        self._parado = False
        self._audio_preparado = None
        self._texto_preparado = None
        # Caché de fragmentos ya descargados (reutiliza audio al saltar atrás)
        self._cache_frags = {}
        self._cache_lru = []

    def _cargar_config(self):
        try:
            ruta = ruta_config("config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Error] No se pudo leer config_general.json en ClientePolly: {e}")
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

    def _elegir_motor(self, datos_voz):
        """
        Elige el motor óptimo para la voz según los motores que soporta.
        Prioridad: generative > long-form > neural > standard.
        Si no hay información de motores, intenta neural como mínimo seguro.
        """
        motores = datos_voz.get("motores", []) if isinstance(datos_voz, dict) else []
        for motor in ("generative", "long-form", "neural", "standard"):
            if motor in motores:
                return motor
        return "neural"

    def _llamar_api(self, texto, datos_voz):
        """
        Llama a la API de Amazon Polly y devuelve (data, fs).
        Implementa 1 reintento automático ante errores de conexión transitoria.
        No reproduce el audio — solo lo descarga y decodifica.
        """
        if not _BOTO3_DISPONIBLE:
            raise Exception(
                "boto3 no está instalado. Amazon Polly no puede funcionar.\n"
                "Solución: pip install boto3"
            )
        import boto3

        config = self._cargar_config()
        po_conf = config.get("polly", {})
        access_key = po_conf.get("access_key", "").strip()
        secret_key = po_conf.get("secret_key", "").strip()
        region_raw = po_conf.get("region", "").strip()
        region = _normalizar_region(region_raw)

        if not access_key or not secret_key:
            raise Exception("Faltan credenciales de Amazon Polly (Access Key ID / Secret Access Key)")

        if isinstance(datos_voz, dict):
            voice_id = datos_voz.get("id", "Lucia")
        else:
            voice_id = str(datos_voz)

        motor = self._elegir_motor(datos_voz)

        pct_rate = int((self._velocidad - 50) * 1.6)
        pct_rate = max(-80, min(80, pct_rate))
        tasa = f"+{pct_rate}%" if pct_rate >= 0 else f"{pct_rate}%"

        ssml = (
            "<speak>"
            f"<prosody rate='{tasa}'>"
            f"{texto}"
            "</prosody>"
            "</speak>"
        )

        cliente = boto3.client(
            "polly",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        respuesta = None
        for intento in range(2):
            try:
                respuesta = cliente.synthesize_speech(
                    Engine=motor,
                    Text=ssml,
                    TextType="ssml",
                    OutputFormat="ogg_vorbis",
                    SampleRate="24000",
                    VoiceId=voice_id,
                )
                print("[Polly] Conexión establecida.")
                break
            except Exception as e:
                error_str = str(e).lower()
                es_error_red = any(k in error_str for k in ("connect", "network", "timeout", "connection"))
                if intento == 0 and es_error_red and not self._parado:
                    time.sleep(1)
                    continue
                raise

        if respuesta is None:
            raise Exception("No se obtuvo respuesta de Amazon Polly")

        audio_bytes = respuesta["AudioStream"].read()
        data, fs = sf.read(io.BytesIO(audio_bytes))

        if self._volumen != 100:
            data = data * (self._volumen / 100.0)

        return data, fs

    def hablar(self, texto, datos_voz):
        """Sintetiza y reproduce el texto. Prioridad: caché → buffer proactivo → API."""
        self._parado = False

        if texto in self._cache_frags:
            data, fs = self._cache_frags[texto]
        elif self._audio_preparado is not None and self._texto_preparado == texto:
            data, fs = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            self._guardar_en_cache(texto, data, fs)
        else:
            data, fs = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(texto, data, fs)

        if not self._parado:
            sd.play(data, fs)
            sd.wait()

    def preparar(self, texto, datos_voz):
        """Pre-descarga el audio en segundo plano. Reutiliza caché si ya existe."""
        if texto in self._cache_frags:
            if not self._parado:
                self._audio_preparado = self._cache_frags[texto]
                self._texto_preparado = texto
            return
        try:
            data, fs = self._llamar_api(texto, datos_voz)
            if not self._parado:
                self._guardar_en_cache(texto, data, fs)
                self._audio_preparado = (data, fs)
                self._texto_preparado = texto
        except Exception:
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        self._parado = True
        # El caché de fragmentos NO se borra: el salto-atrás puede reutilizarlo
        self._audio_preparado = None
        self._texto_preparado = None
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
