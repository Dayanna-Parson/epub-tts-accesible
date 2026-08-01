import logging
import time
import requests
import sounddevice as sd
import soundfile as sf
import io
from app.config_rutas import cargar_claves

logger = logging.getLogger(__name__)

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
        return cargar_claves()

    def obtener_voces(self):
        return []

    def _clave_cache(self, texto, datos_voz):
        """
        Clave de caché con la voz incluida: el mismo texto con dos voces
        distintas (etiquetas {{@voz}}, o cambio de voz en Lectura y
        retroceso) no debe devolver el audio cacheado de la voz anterior.
        """
        if isinstance(datos_voz, dict):
            voice_id = datos_voz.get("id")
        else:
            voice_id = datos_voz
        return (voice_id, texto)

    def _guardar_en_cache(self, clave, data, fs):
        if clave not in self._cache_frags:
            if len(self._cache_lru) >= _MAX_CACHE:
                clave_antigua = self._cache_lru.pop(0)
                self._cache_frags.pop(clave_antigua, None)
            self._cache_lru.append(clave)
        self._cache_frags[clave] = (data, fs)

    # ── División de texto largo ────────────────────────────────────────────────

    # ANCLAJE_INICIO: DIVISOR_TEXTO_ELEVEN
    _LIMITE_API = 5000  # valor conservador, seguro para todos los planes de ElevenLabs

    def _dividir_texto(self, texto):
        """
        Divide el texto en fragmentos que no superen _LIMITE_API caracteres.
        Respeta los finales de frase para mantener la cohesión fonética.
        """
        if len(texto) <= self._LIMITE_API:
            return [texto]
        fragmentos = []
        while texto:
            if len(texto) <= self._LIMITE_API:
                fragmentos.append(texto.strip())
                break
            corte = -1
            for sep in ('. ', '! ', '? ', '; ', '\n'):
                pos = texto.rfind(sep, 0, self._LIMITE_API)
                if pos != -1:
                    candidato = pos + len(sep)
                    if candidato > corte:
                        corte = candidato
            if corte <= 0:
                corte = self._LIMITE_API
            fragmento = texto[:corte].strip()
            if fragmento:
                fragmentos.append(fragmento)
            texto = texto[corte:].strip()
        return fragmentos
    # ANCLAJE_FIN: DIVISOR_TEXTO_ELEVEN

    def _llamar_api(self, texto, datos_voz):
        """
        Punto de entrada para toda síntesis HTTP de ElevenLabs. Divide el
        texto si supera el límite de la API, realiza las peticiones de
        forma secuencial y concatena el audio antes de devolverlo.
        """
        fragmentos = self._dividir_texto(texto)
        if len(fragmentos) == 1:
            return self._peticion_http(fragmentos[0], datos_voz)
        import numpy as np
        partes = []
        fs_comun = None
        for frag in fragmentos:
            if self._parado:
                raise Exception("Síntesis cancelada.")
            data, fs = self._peticion_http(frag, datos_voz)
            if fs_comun is None:
                fs_comun = fs
            partes.append(data)
        return np.concatenate(partes, axis=0), fs_comun

    def _peticion_http(self, texto, datos_voz):
        """Realiza una única petición POST a la API. El texto siempre es <= _LIMITE_API chars."""
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

        response = self._sesion.post(url, json=payload, headers=headers, timeout=30)

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
        clave = self._clave_cache(texto, datos_voz)

        if clave in self._cache_frags:
            data, fs_efectiva = self._cache_frags[clave]
        elif self._audio_preparado is not None and self._texto_preparado == clave:
            data, fs_efectiva = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            self._guardar_en_cache(clave, data, fs_efectiva)
        else:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(clave, data, fs_efectiva)

        if not self._parado:
            sd.play(data, fs_efectiva)
            sd.wait()
            # Margen de seguridad: sd.wait() puede volver antes de que el
            # hardware termine de vaciar físicamente su búfer, sobre todo a
            # velocidades altas — sin esto, el sd.play() del fragmento
            # siguiente puede cortar la última sílaba del anterior.
            if not self._parado:
                time.sleep(0.12)

    def preparar(self, texto, datos_voz):
        """Pre-descarga el audio en segundo plano. Reutiliza caché si ya existe.
        El resultado se guarda siempre: detener() no debe invalidarlo porque el
        audio descargado es para el SIGUIENTE fragmento, no para el actual."""
        clave = self._clave_cache(texto, datos_voz)
        if clave in self._cache_frags:
            self._audio_preparado = self._cache_frags[clave]
            self._texto_preparado = clave
            return
        try:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(clave, data, fs_efectiva)
            self._audio_preparado = (data, fs_efectiva)
            self._texto_preparado = clave
        except Exception:
            logger.exception("[ElevenLabs] Fallo al precargar audio en preparar()")
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        self._parado = True
        # Caché y buffer proactivo se conservan para el siguiente fragmento.
        try:
            self._sesion.close()
            self._sesion = requests.Session()
        except Exception:
            logger.exception("[ElevenLabs] Fallo al reiniciar la sesión HTTP en detener()")
        try:
            sd.stop()
        except Exception:
            logger.exception("[ElevenLabs] Fallo al detener la reproducción de audio en detener()")

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
