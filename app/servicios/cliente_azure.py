import os
import json
import requests
import sounddevice as sd
import soundfile as sf
import io
import time
from app.config_rutas import ruta_config


class ClienteAzure:
    def __init__(self):
        self.config = {}
        # Parámetros de reproducción (0-100)
        self._velocidad = 50   # 50 = velocidad normal
        self._volumen = 100    # 100 = volumen máximo
        # Una sesión reutilizable mejora el rendimiento (keep-alive HTTP) y permite
        # cancelar peticiones en curso llamando a self._sesion.close().
        self._sesion = requests.Session()
        # Flag para distinguir una detención intencional de un error de red
        self._parado = False
        # Buffer de precarga: almacena audio ya descargado para el siguiente fragmento
        self._audio_preparado = None   # (data, fs) o None
        self._texto_preparado = None   # texto al que pertenece _audio_preparado

    def _cargar_config(self):
        try:
            ruta = ruta_config("config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Error] No se pudo leer config_general.json en ClienteAzure: {e}")
        return {}

    def obtener_voces(self):
        return []

    def _limpiar_texto_xml(self, texto):
        """Elimina caracteres especiales que rompen el SSML de Azure."""
        t = texto.replace("&", "y")
        t = t.replace("<", "")
        t = t.replace(">", "")
        t = t.replace('"', "")
        t = t.replace("'", "")
        return t

    def _velocidad_a_tasa(self):
        """
        Convierte el valor de velocidad (0-100) a porcentaje de tasa SSML para Azure.
          v=0  → -80%  (muy lento)
          v=50 → +0%   (normal)
          v=100 → +80% (rápido)
        """
        pct = int((self._velocidad - 50) * 1.6)
        pct = max(-80, min(80, pct))
        if pct >= 0:
            return f"+{pct}%"
        return f"{pct}%"

    def _volumen_a_nivel(self):
        """Convierte el valor de volumen (0-100) a nivel de volumen SSML para Azure."""
        v = self._volumen
        if v == 0:
            return "silent"
        elif v < 20:
            return "x-soft"
        elif v < 40:
            return "soft"
        elif v < 70:
            return "medium"
        elif v < 90:
            return "loud"
        else:
            return "x-loud"

    def _llamar_api(self, texto, datos_voz):
        """
        Realiza la llamada HTTP a la API de Azure TTS y devuelve (data, fs).
        Implementa 1 reintento automático ante errores de conexión transitoria.
        No reproduce el audio — solo lo descarga y decodifica.
        """
        self.config = self._cargar_config()
        az_conf = self.config.get("azure", {})
        key = az_conf.get("key")
        region = az_conf.get("region")
        idioma_destino = self.config.get("idioma_libro_codigo", "es-ES")

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
                    print(f"[Azure] Error de conexión, reintentando en 1s… ({e})")
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
        """Sintetiza y reproduce el texto. Usa audio pre-descargado si está disponible."""
        self._parado = False
        inicio = time.time()
        print(f"--> [Azure] Iniciando petición...")

        # Usar audio pre-descargado si fue preparado para exactamente este texto
        if self._audio_preparado is not None and self._texto_preparado == texto:
            data, fs = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            print(f"--> [Azure] Usando audio pre-descargado (sin latencia de API).")
        else:
            data, fs = self._llamar_api(texto, datos_voz)
            tiempo_total = time.time() - inicio
            print(f"--> [Azure] Respuesta recibida en {tiempo_total:.2f} segundos.")

        if not self._parado:
            sd.play(data, fs)
            sd.wait()

    def preparar(self, texto, datos_voz):
        """
        Pre-descarga el audio del texto en segundo plano y lo cachea.
        Si hablar() se llama después con el mismo texto, usa el caché y no hay latencia.
        Llamado desde ReproductorVoz.precargar_fragmento() en un hilo aparte.
        """
        try:
            data, fs = self._llamar_api(texto, datos_voz)
            if not self._parado:
                self._audio_preparado = (data, fs)
                self._texto_preparado = texto
                print(f"[Azure] Precarga completada ({len(texto)} chars).")
        except Exception as e:
            print(f"[Azure] Error en precarga: {e}")
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        """
        Detiene la reproducción de audio y cancela cualquier petición HTTP activa.
        Cerrar la sesión interrumpe la conexión TCP, lo que hace que la llamada
        bloqueante a self._sesion.post() en el hilo de síntesis lance una excepción
        y se detenga sin necesidad de esperar la respuesta completa de la API.
        """
        self._parado = True
        # Invalidar buffer de precarga al detener
        self._audio_preparado = None
        self._texto_preparado = None
        try:
            self._sesion.close()
            # Crear una sesión nueva para peticiones futuras
            self._sesion = requests.Session()
        except Exception as e:
            print(f"[Aviso] Error al cerrar sesión Azure: {e}")
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
