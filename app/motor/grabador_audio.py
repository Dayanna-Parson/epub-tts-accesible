"""
grabador_audio.py
-----------------
Motor de grabación silenciosa multivoz.

Genera archivos MP3 a partir de fragmentos de texto etiquetados,
sin reproducción por altavoces (volcado a archivo).

Proveedores soportados:
  - Azure Cognitive Services TTS  → MP3 directo desde la API
  - ElevenLabs TTS                → MP3 directo desde la API
  - Windows SAPI5 (local)         → WAV via SpFileStream + conversión a MP3

Reintentos: 3 intentos por fragmento antes de registrar el error en el log.
"""

import os
import json
import logging
import tempfile
import requests

from app.motor.procesador_etiquetas import limpiar_nombre_archivo

logger = logging.getLogger(__name__)

CARPETA_RAIZ_GRABACIONES = "Grabaciones_TifloHistorias"


class GrabadorAudio:
    """
    Gestiona la generación silenciosa de archivos de audio multivoz.

    Parámetros:
        callback_progreso: callable(actual, total, etiqueta, nombre_voz)
                           Llamado desde el hilo de grabación; usar wx.CallAfter
                           para actualizar la UI de forma segura.
    """

    def __init__(self, callback_progreso=None):
        self.callback_progreso = callback_progreso
        self._abortar = False
        self.config = {}
        self._ultima_carpeta = None

    # ------------------------------------------------------------------ #
    # Configuración
    # ------------------------------------------------------------------ #

    def _cargar_config(self):
        try:
            ruta = os.path.join("configuraciones", "config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
        except Exception as e:
            logger.warning(f"[GrabadorAudio] No se pudo cargar config: {e}")
            self.config = {}

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def abortar(self):
        """Señala al motor para que detenga el proceso en curso."""
        self._abortar = True

    def obtener_ultima_carpeta(self) -> str:
        """Devuelve la carpeta donde se guardó la última grabación."""
        return self._ultima_carpeta

    def obtener_carpeta_libro(self, titulo_libro: str) -> str:
        """Crea y devuelve la carpeta madre para el libro indicado."""
        titulo_limpio = limpiar_nombre_archivo(titulo_libro)
        carpeta = os.path.join(CARPETA_RAIZ_GRABACIONES, titulo_limpio)
        os.makedirs(carpeta, exist_ok=True)
        return carpeta

    def grabar_fragmentos(
        self,
        fragmentos: list,
        asignaciones_voz: dict,
        titulo_libro: str,
        nombre_capitulo: str,
        modo_dividido: bool,
    ) -> tuple:
        """
        Graba todos los fragmentos y los guarda como archivos de audio.

        Args:
            fragmentos:      [(etiqueta, texto), ...]
            asignaciones_voz: {etiqueta: datos_voz}
            titulo_libro:    Nombre del libro (carpeta madre)
            nombre_capitulo: Nombre del capítulo (subcarpeta)
            modo_dividido:   True → un archivo por fragmento numerado
                             False → un único archivo MP3 concatenado

        Returns:
            (archivos_generados, errores, carpeta_destino)
        """
        self._abortar = False
        self._cargar_config()

        carpeta_libro = self.obtener_carpeta_libro(titulo_libro)
        nombre_cap_limpio = limpiar_nombre_archivo(nombre_capitulo)

        if modo_dividido:
            subcarpeta = os.path.join(carpeta_libro, f"Fragmentos_{nombre_cap_limpio}")
        else:
            subcarpeta = os.path.join(carpeta_libro, f"Audio_Completo_{nombre_cap_limpio}")

        os.makedirs(subcarpeta, exist_ok=True)
        self._ultima_carpeta = subcarpeta

        archivos_generados = []
        errores = []
        total = len(fragmentos)

        if modo_dividido:
            archivos_generados, errores = self._grabar_modo_dividido(
                fragmentos, asignaciones_voz, subcarpeta, total
            )
        else:
            archivos_generados, errores = self._grabar_modo_unico(
                fragmentos, asignaciones_voz, subcarpeta, nombre_cap_limpio, total
            )

        return archivos_generados, errores, subcarpeta

    # ------------------------------------------------------------------ #
    # Modos de grabación
    # ------------------------------------------------------------------ #

    def _grabar_modo_dividido(self, fragmentos, asignaciones_voz, subcarpeta, total):
        archivos_generados = []
        errores = []

        for i, (etiqueta, texto) in enumerate(fragmentos):
            if self._abortar:
                logger.info("[GrabadorAudio] Proceso abortado por el usuario.")
                break

            datos_voz = asignaciones_voz.get(etiqueta)
            nombre_voz = datos_voz.get('nombre', 'sin nombre') if datos_voz else 'sin voz asignada'

            if self.callback_progreso:
                self.callback_progreso(i + 1, total, etiqueta, nombre_voz)

            nombre_arch = f"{i + 1:03d}_{limpiar_nombre_archivo(etiqueta)}.mp3"
            ruta_arch = os.path.join(subcarpeta, nombre_arch)

            exito = False
            for intento in range(3):
                try:
                    self._grabar_fragmento(texto, datos_voz, ruta_arch)
                    exito = True
                    archivos_generados.append(ruta_arch)
                    break
                except Exception as e:
                    logger.warning(
                        f"[GrabadorAudio] Intento {intento + 1}/3 fallido "
                        f"(fragmento {i + 1}, @{etiqueta}): {e}"
                    )
                    if intento == 2:
                        errores.append(f"Fragmento {i + 1} (@{etiqueta}): {e}")

        return archivos_generados, errores

    def _grabar_modo_unico(
        self, fragmentos, asignaciones_voz, subcarpeta, nombre_cap_limpio, total
    ):
        archivos_generados = []
        errores = []
        archivos_temp = []

        try:
            for i, (etiqueta, texto) in enumerate(fragmentos):
                if self._abortar:
                    logger.info("[GrabadorAudio] Proceso abortado por el usuario.")
                    break

                datos_voz = asignaciones_voz.get(etiqueta)
                nombre_voz = datos_voz.get('nombre', 'sin nombre') if datos_voz else 'sin voz asignada'

                if self.callback_progreso:
                    self.callback_progreso(i + 1, total, etiqueta, nombre_voz)

                fd, ruta_temp = tempfile.mkstemp(
                    suffix='.mp3', prefix=f'tfh_{i:03d}_'
                )
                os.close(fd)
                archivos_temp.append(ruta_temp)

                for intento in range(3):
                    try:
                        self._grabar_fragmento(texto, datos_voz, ruta_temp)
                        break
                    except Exception as e:
                        logger.warning(
                            f"[GrabadorAudio] Intento {intento + 1}/3 fallido "
                            f"(fragmento {i + 1}, @{etiqueta}): {e}"
                        )
                        if intento == 2:
                            errores.append(f"Fragmento {i + 1} (@{etiqueta}): {e}")

            if not self._abortar and archivos_temp:
                ruta_final = os.path.join(subcarpeta, f"{nombre_cap_limpio}.mp3")
                self._concatenar_audios(archivos_temp, ruta_final)
                archivos_generados.append(ruta_final)

        finally:
            for t in archivos_temp:
                try:
                    if os.path.exists(t):
                        os.remove(t)
                except Exception:
                    pass

        return archivos_generados, errores

    # ------------------------------------------------------------------ #
    # Concatenación
    # ------------------------------------------------------------------ #

    def _concatenar_audios(self, archivos: list, ruta_salida: str):
        """Une varios archivos de audio en uno solo usando pydub."""
        try:
            from pydub import AudioSegment

            combined = AudioSegment.empty()
            for arch in archivos:
                if os.path.exists(arch) and os.path.getsize(arch) > 0:
                    try:
                        combined += AudioSegment.from_file(arch)
                    except Exception as e:
                        logger.warning(f"[GrabadorAudio] No se pudo añadir {arch}: {e}")

            combined.export(ruta_salida, format='mp3')
            logger.info(f"[GrabadorAudio] Archivo único generado: {ruta_salida}")

        except ImportError:
            # pydub no disponible: concatenar bytes crudos como fallback
            logger.warning("[GrabadorAudio] pydub no disponible. Concatenando bytes crudos.")
            with open(ruta_salida, 'wb') as f_out:
                for arch in archivos:
                    if os.path.exists(arch) and os.path.getsize(arch) > 0:
                        with open(arch, 'rb') as f_in:
                            f_out.write(f_in.read())

    # ------------------------------------------------------------------ #
    # Despacho por proveedor
    # ------------------------------------------------------------------ #

    def _grabar_fragmento(self, texto: str, datos_voz, ruta_salida: str):
        """Selecciona el motor adecuado y genera el audio silenciosamente."""
        if not datos_voz:
            raise Exception("Sin voz asignada para esta etiqueta.")

        proveedor = (
            datos_voz.get('proveedor_id', 'local').lower()
            if isinstance(datos_voz, dict)
            else 'local'
        )

        if 'azure' in proveedor:
            self._grabar_azure(texto, datos_voz, ruta_salida)
        elif 'eleven' in proveedor:
            self._grabar_elevenlabs(texto, datos_voz, ruta_salida)
        elif 'polly' in proveedor:
            self._grabar_polly(texto, datos_voz, ruta_salida)
        else:
            self._grabar_sapi5(texto, datos_voz, ruta_salida)

    # ------------------------------------------------------------------ #
    # Motor: Azure
    # ------------------------------------------------------------------ #

    def _limpiar_xml(self, texto: str) -> str:
        """Elimina caracteres que rompen SSML/XML."""
        t = texto.replace("&", "y")
        t = t.replace("<", "").replace(">", "")
        t = t.replace('"', "").replace("'", "")
        return t

    def _grabar_azure(self, texto: str, datos_voz, ruta_salida: str):
        """Solicita audio MP3 a Azure y lo guarda directamente a disco."""
        az_conf = self.config.get('azure', {})
        key = az_conf.get('key')
        region = az_conf.get('region')
        idioma = self.config.get('idioma_libro_codigo', 'es-ES')

        if not key or not region:
            raise Exception("Credenciales de Azure no configuradas (clave o región vacías).")

        id_voz = datos_voz.get('id') if isinstance(datos_voz, dict) else str(datos_voz)
        texto_limpio = self._limpiar_xml(texto)

        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            # MP3 directo: evita conversión posterior
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        }
        ssml = (
            f"<speak version='1.0' "
            f"xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xml:lang='{idioma}'>"
            f"<voice name='{id_voz}'>"
            f"<lang xml:lang='{idioma}'>{texto_limpio}</lang>"
            f"</voice></speak>"
        )

        response = requests.post(
            url, headers=headers, data=ssml.encode('utf-8'), timeout=60
        )

        if response.status_code == 200:
            with open(ruta_salida, 'wb') as f:
                f.write(response.content)
            logger.info(f"[Azure] Fragmento guardado: {os.path.basename(ruta_salida)}")
        else:
            raise Exception(
                f"Azure {response.status_code}: {response.text[:300]}"
            )

    # ------------------------------------------------------------------ #
    # Motor: ElevenLabs
    # ------------------------------------------------------------------ #

    def _grabar_elevenlabs(self, texto: str, datos_voz, ruta_salida: str):
        """Solicita audio MP3 a ElevenLabs y lo guarda directamente a disco."""
        el_conf = self.config.get('elevenlabs', {})
        key = el_conf.get('api_key')

        if not key:
            raise Exception("API Key de ElevenLabs no configurada.")

        voice_id = datos_voz.get('id') if isinstance(datos_voz, dict) else str(datos_voz)
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": key, "Content-Type": "application/json"}
        payload = {"text": texto, "model_id": "eleven_multilingual_v2"}

        response = requests.post(url, json=payload, headers=headers, timeout=60)

        if response.status_code == 200:
            with open(ruta_salida, 'wb') as f:
                f.write(response.content)
            logger.info(f"[ElevenLabs] Fragmento guardado: {os.path.basename(ruta_salida)}")
        else:
            raise Exception(
                f"ElevenLabs {response.status_code}: {response.text[:300]}"
            )

    # ------------------------------------------------------------------ #
    # Motor: Amazon Polly (stub)
    # ------------------------------------------------------------------ #

    def _grabar_polly(self, texto: str, datos_voz, ruta_salida: str):
        raise NotImplementedError(
            "Amazon Polly aún no está implementado. "
            "Configura Azure o ElevenLabs como alternativa."
        )

    # ------------------------------------------------------------------ #
    # Motor: SAPI5 local (Windows)
    # ------------------------------------------------------------------ #

    def _grabar_sapi5(self, texto: str, datos_voz, ruta_salida: str):
        """
        Genera audio con SAPI5 redirigiendo la salida a un SpFileStream (WAV),
        luego convierte a MP3 con pydub. Si pydub/ffmpeg no está disponible,
        guarda el archivo con extensión .mp3 pero contenido WAV como fallback.
        """
        try:
            import comtypes.client
        except ImportError:
            raise Exception(
                "comtypes no disponible. SAPI5 requiere Windows con comtypes instalado."
            )

        sapi = comtypes.client.CreateObject("SAPI.SpVoice")

        # Seleccionar la voz correcta
        nombre_voz = (
            datos_voz.get('nombre', '')
            if isinstance(datos_voz, dict)
            else str(datos_voz)
        )
        if nombre_voz:
            try:
                voces = sapi.GetVoices()
                for i in range(voces.Count):
                    v = voces.Item(i)
                    if nombre_voz.lower() in v.GetDescription().lower():
                        sapi.Voice = v
                        break
            except Exception as e:
                logger.warning(f"[SAPI5] No se pudo seleccionar voz '{nombre_voz}': {e}")

        # Ruta WAV temporal
        base = ruta_salida.rsplit('.', 1)[0]
        ruta_wav = base + '_tmp.wav'

        try:
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            SSFMCreateForWrite = 3
            stream.Open(ruta_wav, SSFMCreateForWrite)

            # Redirigir salida de audio al archivo
            sapi.AudioOutputStream = stream
            SPF_SYNC = 0  # Síncrono: espera hasta que termine antes de cerrar el stream
            sapi.Speak(texto, SPF_SYNC)
            stream.Close()
        except Exception as e:
            raise Exception(f"Error SAPI5 al escribir audio: {e}")

        # Convertir WAV → MP3
        if not os.path.exists(ruta_wav) or os.path.getsize(ruta_wav) == 0:
            raise Exception("SAPI5 no generó datos de audio.")

        convertido = False
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_wav(ruta_wav)
            audio.export(ruta_salida, format='mp3')
            convertido = True
            logger.info(f"[SAPI5] Fragmento guardado como MP3: {os.path.basename(ruta_salida)}")
        except Exception as e:
            logger.warning(f"[SAPI5] Conversión WAV→MP3 no disponible (ffmpeg?): {e}")

        if convertido:
            os.remove(ruta_wav)
        else:
            # Fallback: renombrar WAV a .mp3 (contenido PCM, válido en la mayoría de reproductores)
            os.rename(ruta_wav, ruta_salida)
            logger.info(f"[SAPI5] Fragmento guardado como WAV(.mp3): {os.path.basename(ruta_salida)}")

    # ------------------------------------------------------------------ #
    # Previsualización de voz (con altavoces)
    # ------------------------------------------------------------------ #

    def probar_voz(self, datos_voz: dict):
        """
        Reproduce una muestra de la voz indicada por los altavoces.
        Pensado para previsualización antes de iniciar la grabación.
        """
        texto_prueba = "Hola. Esta es una prueba de voz para TifloHistorias."
        proveedor = (
            datos_voz.get('proveedor_id', 'local').lower()
            if isinstance(datos_voz, dict)
            else 'local'
        )

        try:
            if 'azure' in proveedor:
                from app.servicios.cliente_azure import ClienteAzure
                ClienteAzure().hablar(texto_prueba, datos_voz)

            elif 'eleven' in proveedor:
                from app.servicios.cliente_eleven import ClienteEleven
                ClienteEleven().hablar(texto_prueba, datos_voz)

            else:
                from app.servicios.cliente_sapi5 import ClienteSapi5
                cliente = ClienteSapi5()
                if isinstance(datos_voz, dict):
                    nombre = datos_voz.get('nombre', '')
                    if nombre:
                        cliente.cambiar_voz_por_nombre(nombre)
                cliente.hablar(texto_prueba)

        except Exception as e:
            raise Exception(f"Error al probar voz: {e}")
