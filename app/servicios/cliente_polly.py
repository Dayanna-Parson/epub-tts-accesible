import os
import json
import io
import time
import sounddevice as sd
import soundfile as sf
from app.config_rutas import ruta_config

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


class ClientePolly:
    def __init__(self):
        # Parámetros de reproducción (0-100)
        self._velocidad = 50   # 50 = velocidad normal
        self._volumen = 100    # 100 = volumen máximo
        self._parado = False   # Flag para distinguir stop intencional de error de red

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

    def hablar(self, texto, datos_voz):
        try:
            import boto3
        except ImportError:
            raise Exception("boto3 no está instalado. Ejecuta: pip install boto3")

        self._parado = False

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

        # Mapear velocidad 0-100 a porcentaje de tasa SSML:
        #   v=0  → -80%  (muy lento)
        #   v=50 → +0%   (normal)
        #   v=100 → +80% (rápido)
        pct_rate = int((self._velocidad - 50) * 1.6)
        pct_rate = max(-80, min(80, pct_rate))
        tasa = f"+{pct_rate}%" if pct_rate >= 0 else f"{pct_rate}%"

        # Encapsular texto con prosody SSML para aplicar velocidad
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

        # Intentar síntesis con 1 reintento automático ante fallo de conexión
        respuesta = None
        for intento in range(2):
            try:
                # Intentar con motor "neural" (mayor calidad)
                try:
                    respuesta = cliente.synthesize_speech(
                        Engine="neural",
                        Text=ssml,
                        TextType="ssml",
                        OutputFormat="ogg_vorbis",
                        VoiceId=voice_id,
                    )
                except Exception:
                    respuesta = cliente.synthesize_speech(
                        Engine="standard",
                        Text=ssml,
                        TextType="ssml",
                        OutputFormat="ogg_vorbis",
                        VoiceId=voice_id,
                    )
                break  # Éxito: salir del bucle de reintentos
            except Exception as e:
                error_str = str(e).lower()
                # Solo reintentar si es un error de conexión y no fue una detención intencional
                es_error_red = any(k in error_str for k in ("connect", "network", "timeout", "connection"))
                if intento == 0 and es_error_red and not self._parado:
                    print(f"[Polly] Error de conexión, reintentando en 1s… ({e})")
                    time.sleep(1)
                    continue
                raise  # Segundo intento o error no recuperable

        if respuesta is None:
            raise Exception("No se obtuvo respuesta de Amazon Polly")

        audio_bytes = respuesta["AudioStream"].read()
        data, fs = sf.read(io.BytesIO(audio_bytes))

        # Aplicar volumen multiplicando la señal (100 = sin cambio)
        if self._volumen != 100:
            data = data * (self._volumen / 100.0)

        if not self._parado:
            sd.play(data, fs)
            sd.wait()

    def detener(self):
        self._parado = True
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
