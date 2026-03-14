"""
grabador_audio.py
-----------------
Motor de grabación silenciosa multivoz.

Genera archivos MP3 a partir de fragmentos de texto etiquetados,
sin reproducción por altavoces (volcado directo a archivo).

Calidad de audio:
  - Azure:       audio-48khz-192kbitrate-mono-mp3  (48 kHz nativo) → MP3 320k
  - ElevenLabs:  mp3_44100_192                     (44.1 kHz nativo, 192 kbps) → MP3 320k
  - Polly:       OGG Vorbis / 24000 Hz → MP3 320k  (evita el «efecto teléfono»)
  - SAPI5 local: WAV 22 kHz → MP3 320 kbps vía pydub

  Todos los archivos de salida se re-codifican a MP3 320 kbps respetando
  la frecuencia de muestreo nativa del proveedor (sin re-muestreos).

Chunking inteligente para textos largos:
  Cuando un fragmento supera el límite del proveedor, se divide
  en trozos por párrafo/oración, se genera cada trozo por separado
  y se concatenan silenciosamente en el archivo final.
"""

import os
import re
import json
import logging
import tempfile
import requests

from app.config_rutas import ruta_config
from app.motor.procesador_etiquetas import limpiar_nombre_archivo

logger = logging.getLogger(__name__)

# ── ffmpeg portable (bin/ffmpeg.exe junto a la raíz del proyecto) ─────────────
# Si existe bin/ffmpeg.exe, se configura pydub para usarlo automáticamente.
# El usuario solo necesita copiar ffmpeg.exe en esa carpeta; no hace falta
# instalarlo ni añadirlo al PATH del sistema.
_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FFMPEG_LOCAL  = os.path.join(_RAIZ, 'bin', 'ffmpeg.exe')
_FFPROBE_LOCAL = os.path.join(_RAIZ, 'bin', 'ffprobe.exe')

try:
    from pydub import AudioSegment as _AS
    if os.path.isfile(_FFMPEG_LOCAL):
        _AS.converter = _FFMPEG_LOCAL
        if os.path.isfile(_FFPROBE_LOCAL):
            _AS.ffprobe = _FFPROBE_LOCAL
        logger.info(f"[GrabadorAudio] ffmpeg local detectado: {_FFMPEG_LOCAL}")
    del _AS
except ImportError:
    pass  # pydub no instalado — los métodos individuales manejan el fallback

# Ruta absoluta → funciona independientemente del directorio de trabajo actual
CARPETA_RAIZ_GRABACIONES = os.path.join(_RAIZ, "Grabaciones_Epub-TTS")

# ── Máximo de caracteres por petición a cada proveedor ────────────────────────
_MAX_CHARS = {
    'azure':  4500,   # Azure acepta hasta ~5000 en SSML; usamos margen
    'eleven': 2400,   # ElevenLabs ~2500 por request en plan gratuito
    'polly':  2800,   # Polly: 3000 chars para text, 6000 para SSML
    'local':  50000,  # SAPI5 no tiene límite práctico
}

# ── Formatos de salida de alta calidad ───────────────────────────────────────
_AZURE_OUTPUT_FORMAT  = "audio-48khz-192kbitrate-mono-mp3"
_ELEVEN_OUTPUT_FORMAT = "mp3_44100_192"


class GrabadorAudio:
    """
    Gestiona la generación silenciosa de archivos de audio multivoz.

    callback_progreso: callable(actual, total, etiqueta, nombre_voz)
                       Siempre se llama desde el hilo de grabación;
                       usa wx.CallAfter para actualizar la UI.
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
            ruta = ruta_config("ajustes.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
        except Exception as e:
            logger.warning(f"[GrabadorAudio] No se pudo cargar config: {e}")
            self.config = {}
        # Las claves API se guardan en claves_api.json (separado de ajustes.json).
        # Las fusionamos aquí para que _grabar_azure/polly/elevenlabs las encuentren.
        try:
            from app.config_rutas import cargar_claves
            claves = cargar_claves()
            for proveedor in ('azure', 'polly', 'elevenlabs'):
                if proveedor in claves:
                    self.config[proveedor] = claves[proveedor]
        except Exception as e:
            logger.warning(f"[GrabadorAudio] No se pudieron cargar claves API: {e}")

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def abortar(self):
        self._abortar = True

    def obtener_ultima_carpeta(self) -> str:
        return self._ultima_carpeta

    def obtener_carpeta_libro(self, titulo_libro: str) -> str:
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

        Returns:
            (archivos_generados, errores, carpeta_destino)
        """
        self._abortar = False
        self._cargar_config()

        carpeta_libro   = self.obtener_carpeta_libro(titulo_libro)
        nombre_cap_limpio = limpiar_nombre_archivo(nombre_capitulo)

        # Los audios siempre van dentro de /grabaciones/ para coexistir con
        # /capitulos/ (los TXT del divisor de EPUB) sin mezclarse.
        base_grabaciones = os.path.join(carpeta_libro, "grabaciones")
        if modo_dividido:
            subcarpeta = os.path.join(base_grabaciones, f"Fragmentos_{nombre_cap_limpio}")
        else:
            subcarpeta = os.path.join(base_grabaciones, f"Audio_Completo_{nombre_cap_limpio}")

        os.makedirs(subcarpeta, exist_ok=True)
        self._ultima_carpeta = subcarpeta

        total = len(fragmentos)

        if modo_dividido:
            archivos, errores = self._grabar_modo_dividido(
                fragmentos, asignaciones_voz, subcarpeta, total
            )
        else:
            archivos, errores = self._grabar_modo_unico(
                fragmentos, asignaciones_voz, subcarpeta, nombre_cap_limpio, total
            )

        return archivos, errores, subcarpeta

    # ------------------------------------------------------------------ #
    # Modos de grabación
    # ------------------------------------------------------------------ #

    def _grabar_modo_dividido(self, fragmentos, asignaciones_voz, subcarpeta, total):
        archivos_generados, errores = [], []

        for i, (etiqueta, texto) in enumerate(fragmentos):
            if self._abortar:
                logger.info("[GrabadorAudio] Proceso abortado.")
                break

            datos_voz  = asignaciones_voz.get(etiqueta)
            nombre_voz = datos_voz.get('nombre', 'sin nombre') if datos_voz else 'sin voz'

            if self.callback_progreso:
                self.callback_progreso(i + 1, total, etiqueta, nombre_voz)

            nombre_arch = f"{i + 1:03d}_{limpiar_nombre_archivo(etiqueta)}.mp3"
            ruta_arch   = os.path.join(subcarpeta, nombre_arch)

            for intento in range(3):
                try:
                    self._grabar_fragmento(texto, datos_voz, ruta_arch)
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
        archivos_generados, errores = [], []
        archivos_temp = []

        try:
            for i, (etiqueta, texto) in enumerate(fragmentos):
                if self._abortar:
                    logger.info("[GrabadorAudio] Proceso abortado.")
                    break

                datos_voz  = asignaciones_voz.get(etiqueta)
                nombre_voz = datos_voz.get('nombre', 'sin nombre') if datos_voz else 'sin voz'

                if self.callback_progreso:
                    self.callback_progreso(i + 1, total, etiqueta, nombre_voz)

                fd, ruta_temp = tempfile.mkstemp(suffix='.mp3', prefix=f'tfh_{i:03d}_')
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
    # Chunking inteligente para textos largos
    # ------------------------------------------------------------------ #

    def _dividir_en_trozos(self, texto: str, max_chars: int) -> list:
        """
        Divide un texto largo en trozos respetando párrafos y frases.
        Nunca corta palabras a la mitad.
        """
        if len(texto) <= max_chars:
            return [texto]

        trozos   = []
        parrafos = [p.strip() for p in re.split(r'\n\s*\n', texto) if p.strip()]

        trozo_actual = ""
        for parrafo in parrafos:
            if len(trozo_actual) + len(parrafo) + 2 <= max_chars:
                trozo_actual += ("\n\n" if trozo_actual else "") + parrafo
            else:
                if trozo_actual:
                    trozos.append(trozo_actual)

                if len(parrafo) <= max_chars:
                    trozo_actual = parrafo
                else:
                    # Párrafo demasiado largo → dividir por frases
                    oraciones    = re.split(r'(?<=[.!?…])\s+', parrafo)
                    trozo_actual = ""
                    for oracion in oraciones:
                        if len(trozo_actual) + len(oracion) + 1 <= max_chars:
                            trozo_actual += (" " if trozo_actual else "") + oracion
                        else:
                            if trozo_actual:
                                trozos.append(trozo_actual)
                            # Si una sola oración supera el límite, partir por palabras
                            if len(oracion) > max_chars:
                                palabras   = oracion.split()
                                trozo_pal  = ""
                                for pal in palabras:
                                    if len(trozo_pal) + len(pal) + 1 <= max_chars:
                                        trozo_pal += (" " if trozo_pal else "") + pal
                                    else:
                                        if trozo_pal:
                                            trozos.append(trozo_pal)
                                        trozo_pal = pal
                                trozo_actual = trozo_pal
                            else:
                                trozo_actual = oracion

        if trozo_actual:
            trozos.append(trozo_actual)

        return trozos if trozos else [texto]

    # ------------------------------------------------------------------ #
    # Grabación de un fragmento (con chunking automático)
    # ------------------------------------------------------------------ #

    def _grabar_fragmento(self, texto: str, datos_voz, ruta_salida: str):
        """
        Punto de entrada por fragmento.
        Si el texto supera el límite del proveedor, lo divide en trozos,
        genera cada trozo en un archivo temporal y los concatena.
        """
        if not datos_voz:
            raise Exception("Sin voz asignada para esta etiqueta.")

        proveedor = (
            datos_voz.get('proveedor_id', 'local').lower()
            if isinstance(datos_voz, dict) else 'local'
        )
        max_chars = _MAX_CHARS.get(proveedor, 2500)

        if len(texto) > max_chars:
            trozos = self._dividir_en_trozos(texto, max_chars)
            if len(trozos) > 1:
                logger.info(
                    f"[GrabadorAudio] Texto largo ({len(texto)} chars) dividido "
                    f"en {len(trozos)} trozos para {proveedor}."
                )
                archivos_tmp = []
                try:
                    for j, trozo in enumerate(trozos):
                        fd, ruta_tmp = tempfile.mkstemp(
                            suffix='.mp3', prefix=f'tfh_trozo{j:03d}_'
                        )
                        os.close(fd)
                        archivos_tmp.append(ruta_tmp)
                        self._llamar_motor(trozo, datos_voz, ruta_tmp, proveedor)
                    self._concatenar_audios(archivos_tmp, ruta_salida)
                finally:
                    for tmp in archivos_tmp:
                        try:
                            if os.path.exists(tmp):
                                os.remove(tmp)
                        except Exception:
                            pass
                return

        self._llamar_motor(texto, datos_voz, ruta_salida, proveedor)

    def _llamar_motor(self, texto: str, datos_voz, ruta_salida: str, proveedor: str):
        """Despacha al motor correspondiente según el proveedor."""
        if 'azure' in proveedor:
            self._grabar_azure(texto, datos_voz, ruta_salida)
        elif 'eleven' in proveedor:
            self._grabar_elevenlabs(texto, datos_voz, ruta_salida)
        elif 'polly' in proveedor:
            self._grabar_polly(texto, datos_voz, ruta_salida)
        else:
            self._grabar_sapi5(texto, datos_voz, ruta_salida)

    # ------------------------------------------------------------------ #
    # Re-codificación a MP3 320 kbps (preserva frecuencia de origen)
    # ------------------------------------------------------------------ #

    def _recodificar_mp3_320k(self, ruta_origen: str, ruta_destino: str):
        """
        Convierte cualquier archivo de audio a MP3 320 kbps.
        pydub preserva la frecuencia de muestreo original sin re-muestrear.
        Si pydub no está disponible, copia el archivo tal cual (fallback).
        """
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(ruta_origen)
            audio.export(ruta_destino, format='mp3', bitrate='320k')
        except ImportError:
            import shutil
            shutil.copy2(ruta_origen, ruta_destino)
            logger.warning(
                "[GrabadorAudio] pydub no disponible; "
                "archivo guardado sin re-codificar a 320k."
            )
        except Exception as e:
            logger.warning(f"[GrabadorAudio] No se pudo re-codificar a 320k: {e}")
            if ruta_origen != ruta_destino:
                import shutil
                shutil.copy2(ruta_origen, ruta_destino)

    # ------------------------------------------------------------------ #
    # Concatenación sin re-muestreo
    # ------------------------------------------------------------------ #

    def _concatenar_audios(self, archivos: list, ruta_salida: str):
        """
        Une varios MP3 en uno solo.
        Intenta pydub+ffmpeg (320k, preserva sample rate).
        Si ffmpeg no está disponible, concatena bytes crudos como fallback.
        Los archivos MP3 son secuencias de frames: la concatenación directa
        de bytes produce un archivo válido y reproducible.
        """
        archivos_validos = [
            a for a in archivos
            if os.path.exists(a) and os.path.getsize(a) > 0
        ]
        if not archivos_validos:
            logger.warning("[GrabadorAudio] _concatenar_audios: ningún archivo válido.")
            return

        # ── Intentar pydub + ffmpeg ──────────────────────────────────────
        try:
            from pydub import AudioSegment

            combined = AudioSegment.empty()
            fallos   = 0
            for arch in archivos_validos:
                try:
                    combined += AudioSegment.from_file(arch, format='mp3')
                except Exception as e:
                    fallos += 1
                    logger.debug(
                        f"[GrabadorAudio] pydub no leyó {os.path.basename(arch)}: {e}"
                    )

            if fallos < len(archivos_validos):
                # Al menos un archivo se decodificó correctamente
                combined.export(ruta_salida, format='mp3', bitrate='320k')
                logger.info(
                    f"[GrabadorAudio] Concatenado 320k: {os.path.basename(ruta_salida)}"
                )
                return
            # Todos fallaron (ffmpeg ausente) → caer al fallback
            logger.info(
                "[GrabadorAudio] pydub/ffmpeg no disponible para MP3. "
                "Concatenando bytes crudos."
            )

        except ImportError:
            logger.info(
                "[GrabadorAudio] pydub no instalado. Concatenando bytes crudos."
            )
        except Exception as e:
            logger.warning(
                f"[GrabadorAudio] Error pydub al concatenar: {e}. "
                "Usando bytes crudos."
            )

        # ── Fallback: concatenación de bytes MP3 crudos ──────────────────
        # Los frames MP3 son auto-sincronizables; la concatenación directa
        # produce un archivo válido para todos los reproductores.
        with open(ruta_salida, 'wb') as f_out:
            for arch in archivos_validos:
                try:
                    with open(arch, 'rb') as f_in:
                        f_out.write(f_in.read())
                except Exception as e:
                    logger.warning(
                        f"[GrabadorAudio] No se pudo leer "
                        f"{os.path.basename(arch)}: {e}"
                    )
        logger.info(
            f"[GrabadorAudio] Concatenado (bytes crudos): "
            f"{os.path.basename(ruta_salida)}"
        )

    # ------------------------------------------------------------------ #
    # Motor: Azure
    # ------------------------------------------------------------------ #

    def _limpiar_xml(self, texto: str) -> str:
        """Escapa caracteres especiales XML para usarlos dentro de SSML."""
        import xml.sax.saxutils
        return xml.sax.saxutils.escape(texto)

    def _grabar_azure(self, texto: str, datos_voz, ruta_salida: str):
        """MP3 48 kHz / 192 kbps desde Azure, re-codificado a MP3 320 kbps."""
        az_conf = self.config.get('azure', {})
        key     = az_conf.get('key')
        region  = az_conf.get('region')
        idioma  = self.config.get('idioma_libro_codigo', 'es-ES')

        if not key or not region:
            raise Exception("Credenciales de Azure no configuradas.")

        id_voz = datos_voz.get('id') if isinstance(datos_voz, dict) else str(datos_voz)
        texto_limpio = self._limpiar_xml(texto)

        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": _AZURE_OUTPUT_FORMAT,
        }
        ssml = (
            f"<speak version='1.0' "
            f"xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xml:lang='{idioma}'>"
            f"<voice name='{id_voz}'>"
            f"<lang xml:lang='{idioma}'>{texto_limpio}</lang>"
            f"</voice></speak>"
        )

        response = requests.post(url, headers=headers, data=ssml.encode('utf-8'), timeout=60)
        if response.status_code != 200:
            raise Exception(f"Azure {response.status_code}: {response.text[:300]}")

        fd, ruta_tmp = tempfile.mkstemp(suffix='.mp3', prefix='tfh_az_')
        os.close(fd)
        try:
            with open(ruta_tmp, 'wb') as f:
                f.write(response.content)
            self._recodificar_mp3_320k(ruta_tmp, ruta_salida)
        finally:
            if os.path.exists(ruta_tmp):
                os.remove(ruta_tmp)

        logger.info(f"[Azure] {os.path.basename(ruta_salida)} (48kHz→320k)")

    # ------------------------------------------------------------------ #
    # Motor: ElevenLabs
    # ------------------------------------------------------------------ #

    def _grabar_elevenlabs(self, texto: str, datos_voz, ruta_salida: str):
        """MP3 44.1 kHz / 192 kbps desde ElevenLabs, re-codificado a MP3 320 kbps."""
        el_conf = self.config.get('elevenlabs', {})
        key = el_conf.get('api_key')
        if not key:
            raise Exception("API Key de ElevenLabs no configurada.")

        voice_id = datos_voz.get('id') if isinstance(datos_voz, dict) else str(datos_voz)
        url      = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers  = {"xi-api-key": key, "Content-Type": "application/json"}
        payload  = {
            "text": texto,
            "model_id": "eleven_multilingual_v2",
            "output_format": _ELEVEN_OUTPUT_FORMAT,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=60)
        if response.status_code != 200:
            raise Exception(f"ElevenLabs {response.status_code}: {response.text[:300]}")

        fd, ruta_tmp = tempfile.mkstemp(suffix='.mp3', prefix='tfh_el_')
        os.close(fd)
        try:
            with open(ruta_tmp, 'wb') as f:
                f.write(response.content)
            self._recodificar_mp3_320k(ruta_tmp, ruta_salida)
        finally:
            if os.path.exists(ruta_tmp):
                os.remove(ruta_tmp)

        logger.info(f"[ElevenLabs] {os.path.basename(ruta_salida)} (44.1kHz→320k)")

    # ------------------------------------------------------------------ #
    # Motor: Amazon Polly (MP3 nativo via boto3)
    # ------------------------------------------------------------------ #

    def _grabar_polly(self, texto: str, datos_voz, ruta_salida: str):
        """
        OGG Vorbis / 24000 Hz desde Polly → MP3 320 kbps.

        La API de Polly solo soporta 22050 Hz en formato MP3 (efecto teléfono).
        Usando OGG Vorbis se obtiene 24 kHz con todos los motores (standard,
        neural, long-form, generative), y pydub convierte a MP3 320 kbps
        preservando esa frecuencia de muestreo.
        """
        try:
            import boto3
        except ImportError:
            raise Exception("boto3 no está instalado. Ejecuta: pip install boto3")

        from app.servicios.cliente_polly import _normalizar_region

        po_conf    = self.config.get('polly', {})
        access_key = po_conf.get('access_key', '').strip()
        secret_key = po_conf.get('secret_key', '').strip()
        region_raw = po_conf.get('region', '').strip()

        if not access_key or not secret_key:
            raise Exception(
                "Credenciales de Amazon Polly no configuradas "
                "(Access Key / Secret Key vacíos)."
            )

        region   = _normalizar_region(region_raw)
        voice_id = datos_voz.get('id') if isinstance(datos_voz, dict) else str(datos_voz)

        # Seleccionar motor con mayor calidad disponible para esta voz
        motores = datos_voz.get('motores', []) if isinstance(datos_voz, dict) else []
        motor   = 'neural'  # mínimo seguro
        for m in ('generative', 'long-form', 'neural', 'standard'):
            if m in motores:
                motor = m
                break

        cliente = boto3.client(
            'polly',
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        # OGG Vorbis / 24000 Hz → sin «efecto teléfono»
        respuesta = cliente.synthesize_speech(
            Engine=motor,
            Text=texto,
            TextType='text',
            OutputFormat='ogg_vorbis',
            SampleRate='24000',
            VoiceId=voice_id,
        )

        fd, ruta_ogg = tempfile.mkstemp(suffix='.ogg', prefix='tfh_polly_')
        os.close(fd)
        try:
            with open(ruta_ogg, 'wb') as f:
                f.write(respuesta['AudioStream'].read())
            self._recodificar_mp3_320k(ruta_ogg, ruta_salida)
        finally:
            if os.path.exists(ruta_ogg):
                os.remove(ruta_ogg)

        logger.info(
            f"[Polly] {os.path.basename(ruta_salida)} "
            f"(motor={motor}, voice={voice_id}, 24kHz→320k)"
        )

    # ------------------------------------------------------------------ #
    # Motor: SAPI5 local (Windows) → WAV → MP3 320 kbps
    # ------------------------------------------------------------------ #

    def _grabar_sapi5(self, texto: str, datos_voz, ruta_salida: str):
        """
        Genera audio con SAPI5 redirigiendo la salida a SpFileStream (WAV nativo).
        Convierte a MP3 320 kbps con pydub preservando la frecuencia de muestreo.
        Fallback: renombra el WAV a .mp3 si pydub/ffmpeg no están disponibles.
        """
        try:
            import comtypes.client
        except ImportError:
            raise Exception("comtypes no disponible. SAPI5 requiere Windows.")

        sapi = comtypes.client.CreateObject("SAPI.SpVoice")

        nombre_voz = (
            datos_voz.get('nombre', '') if isinstance(datos_voz, dict) else str(datos_voz)
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
                logger.warning(f"[SAPI5] No se pudo seleccionar '{nombre_voz}': {e}")

        base    = ruta_salida.rsplit('.', 1)[0]
        ruta_wav = base + '_tmp.wav'

        try:
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            stream.Open(ruta_wav, 3)          # SSFMCreateForWrite = 3
            sapi.AudioOutputStream = stream
            sapi.Speak(texto, 0)              # SPF_SYNC = 0
            stream.Close()
        except Exception as e:
            raise Exception(f"Error SAPI5 al escribir audio: {e}")

        if not os.path.exists(ruta_wav) or os.path.getsize(ruta_wav) == 0:
            raise Exception("SAPI5 no generó datos de audio.")

        convertido = False
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_wav(ruta_wav)
            audio.export(ruta_salida, format='mp3', bitrate='320k')
            convertido = True
            logger.info(f"[SAPI5] MP3 320k: {os.path.basename(ruta_salida)}")
        except Exception as e:
            logger.warning(f"[SAPI5] Conversión WAV→MP3 no disponible: {e}")

        if convertido:
            os.remove(ruta_wav)
        else:
            os.rename(ruta_wav, ruta_salida)

    # ------------------------------------------------------------------ #
    # Previsualización de voz (con altavoces)
    # ------------------------------------------------------------------ #

    def probar_voz(self, datos_voz: dict):
        """Reproduce una muestra de la voz por los altavoces (previsualización)."""
        texto_prueba = "Hola. Esta es una prueba de voz para Epub-TTS."
        proveedor = (
            datos_voz.get('proveedor_id', 'local').lower()
            if isinstance(datos_voz, dict) else 'local'
        )

        try:
            if 'azure' in proveedor:
                from app.servicios.cliente_azure import ClienteAzure
                ClienteAzure().hablar(texto_prueba, datos_voz)

            elif 'eleven' in proveedor:
                from app.servicios.cliente_eleven import ClienteEleven
                ClienteEleven().hablar(texto_prueba, datos_voz)

            elif 'polly' in proveedor:
                from app.servicios.cliente_polly import ClientePolly
                ClientePolly().hablar(texto_prueba, datos_voz)

            else:
                from app.servicios.cliente_sapi5 import ClienteSapi5
                cliente = ClienteSapi5()
                if isinstance(datos_voz, dict):
                    nombre = datos_voz.get('nombre', '')
                    if nombre:
                        cliente.cambiar_voz_por_nombre(nombre)
                cliente.hablar(texto_prueba)

        except Exception as e:
            raise Exception(f"Error al probar voz ({proveedor}): {e}")
