import requests
import sounddevice as sd
import soundfile as sf
import io
import time
from app.config_rutas import cargar_claves

_MAX_CACHE = 5  # Máximo de fragmentos de audio en caché por cliente


class ClienteAzure:
    def __init__(self):
        self.config = {}
        self._velocidad = 50
        self._volumen = 100
        self._sesion = requests.Session()
        self._parado = False
        # Buffer proactivo para el siguiente fragmento
        self._audio_preparado = None
        self._texto_preparado = None
        # Caché de fragmentos ya descargados (permite reutilizar audio al saltar atrás)
        self._cache_frags = {}   # texto → (data, fs)
        self._cache_lru = []     # lista de claves en orden de inserción

    def _cargar_config(self):
        return cargar_claves()

    def obtener_voces(self):
        return []

    def _guardar_en_cache(self, texto, data, fs):
        """Guarda audio en caché con límite de _MAX_CACHE entradas (LRU simple)."""
        if texto not in self._cache_frags:
            if len(self._cache_lru) >= _MAX_CACHE:
                clave_antigua = self._cache_lru.pop(0)
                self._cache_frags.pop(clave_antigua, None)
            self._cache_lru.append(texto)
        self._cache_frags[texto] = (data, fs)

    def _limpiar_texto_xml(self, texto):
        import xml.sax.saxutils
        return xml.sax.saxutils.escape(texto)

    def _velocidad_a_tasa(self):
        pct = int((self._velocidad - 50) * 1.6)
        pct = max(-80, min(80, pct))
        return f"+{pct}%" if pct >= 0 else f"{pct}%"

    def _volumen_a_nivel(self):
        v = self._volumen
        if v == 0:   return "silent"
        elif v < 20: return "x-soft"
        elif v < 40: return "soft"
        elif v < 70: return "medium"
        elif v < 90: return "loud"
        else:        return "x-loud"

    def _llamar_api(self, texto, datos_voz):
        """
        Realiza la llamada HTTP a la API de Azure TTS y devuelve (data, fs).
        Implementa 1 reintento automático ante errores de conexión transitoria.
        """
        self.config = self._cargar_config()
        az_conf = self.config.get("azure", {})
        key = az_conf.get("key")
        region = az_conf.get("region")
        # idioma_libro_codigo está en ajustes.json, no en claves_api.json
        try:
            import os, json
            from app.config_rutas import ruta_config as _ruta_config
            _ruta_aj = _ruta_config("ajustes.json")
            if os.path.exists(_ruta_aj):
                with open(_ruta_aj, "r", encoding="utf-8") as _f:
                    idioma_destino = json.load(_f).get("idioma_libro_codigo", "es-ES")
            else:
                idioma_destino = "es-ES"
        except Exception:
            idioma_destino = "es-ES"

        if not key or not region:
            raise Exception("Faltan claves de Azure")

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

        texto_limpio = self._limpiar_texto_xml(texto)
        tasa = self._velocidad_a_tasa()
        nivel_vol = self._volumen_a_nivel()

        ssml = f"""
        <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{idioma_destino}'>
            <voice name='{id_voz}'>
                <lang xml:lang='{idioma_destino}'>
                    <prosody rate='{tasa}' volume='{nivel_vol}'>
                        {texto_limpio}
                    </prosody>
                </lang>
            </voice>
        </speak>
        """

        response = None
        for intento in range(2):
            try:
                response = self._sesion.post(
                    url, headers=headers,
                    data=ssml.encode('utf-8'),
                    timeout=30
                )
                break
            except requests.exceptions.Timeout:
                raise Exception("Azure tardó demasiado (Timeout > 30s).")
            except requests.exceptions.ConnectionError as e:
                if intento == 0 and not self._parado:
                    time.sleep(1)
                    self._sesion = requests.Session()
                    continue
                raise

        if response is None or response.status_code != 200:
            codigo = response.status_code if response else "sin respuesta"
            raise Exception(f"Error Azure: {codigo}")

        data, fs = sf.read(io.BytesIO(response.content))
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
        """
        Pre-descarga el audio en segundo plano. Si ya está en caché, lo reutiliza.
        Llamado desde ReproductorVoz.precargar_fragmento() en un hilo aparte.
        """
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
        """
        Detiene el audio y cancela peticiones HTTP activas.
        El caché de fragmentos NO se borra para que el salto-atrás pueda reutilizarlo.
        """
        self._parado = True
        self._audio_preparado = None
        self._texto_preparado = None
        try:
            self._sesion.close()
            self._sesion = requests.Session()
        except Exception:
            pass
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
