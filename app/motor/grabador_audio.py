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

  Todos los archivos de salida se re-codifican a MP3 320 kbps
  normalizados a 44100 Hz mono.

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
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config_rutas import ruta_config, RAIZ as _RAIZ
from app.motor.procesador_etiquetas import limpiar_nombre_archivo
from app.motor.control_cuota import ControlCuota

logger = logging.getLogger(__name__)


class _ExportacionAbortada(Exception):
    """Señal interna: el usuario pidió abortar mientras se generaba un trozo."""
    pass


# Trozos/capítulos generados en paralelo por exportación. Un valor moderado
# aprovecha la espera de red de las APIs de nube sin disparar límites de
# tasa de los proveedores ni saturar la CPU con voces locales.
_MAX_WORKERS_EXPORTACION = 4

# ── ffmpeg portable (bin/ffmpeg.exe junto a la raíz del proyecto) ─────────────
# Si existe bin/ffmpeg.exe, se configura pydub para usarlo automáticamente.
# El usuario solo necesita copiar ffmpeg.exe en esa carpeta; no hace falta
# instalarlo ni añadirlo al PATH del sistema.
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

# ── Suprimir ventanas de consola en Windows (ffmpeg/ffprobe) ──────────────────
# Sin este parche, pydub crea un subproceso visible por cada llamada a ffmpeg;
# lectores de pantalla como NVDA anuncian cada ventana que aparece/desaparece.
try:
    import sys as _sys
    if _sys.platform == 'win32':
        import subprocess as _subprocess
        _si = _subprocess.STARTUPINFO()
        _si.dwFlags |= _subprocess.STARTF_USESHOWWINDOW
        _si.wShowWindow = 0                        # SW_HIDE
        _orig_Popen = _subprocess.Popen
        class _SilentPopen(_orig_Popen):
            def __init__(self, *args, **kwargs):
                if 'startupinfo' not in kwargs:
                    kwargs['startupinfo'] = _si
                _orig_Popen.__init__(self, *args, **kwargs)
        _subprocess.Popen = _SilentPopen
    del _sys
except Exception:
    pass

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
        # Cliente boto3 de Polly reutilizado entre trozos de la misma
        # exportación — crear boto3.client() por trozo repetía la carga de
        # los modelos de servicio en cada llamada.
        self._cliente_polly_boto3 = None
        self._cliente_polly_credenciales = None
        self._ultima_carpeta = None
        self._velocidad = 50
        self._volumen = 100

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
        velocidad: int = 50,
        volumen: int = 100,
    ) -> tuple:
        """
        Graba todos los fragmentos y los guarda como archivos de audio.

        Returns:
            (archivos_generados, errores, carpeta_destino)
        """
        self._abortar = False
        self._velocidad = max(0, min(100, int(velocidad)))
        self._volumen = max(0, min(100, int(volumen)))
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

            nombre_limpio = limpiar_nombre_archivo(etiqueta).capitalize()
            nombre_arch = f"{i + 1}. {nombre_limpio}.mp3"
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

    def _grabar_fragmento(self, texto: str, datos_voz, ruta_salida: str, callback_progreso_trozo=None):
        """
        Punto de entrada por fragmento.
        Si el texto supera el límite del proveedor, lo divide en trozos,
        genera cada trozo en un archivo temporal y los concatena.

        callback_progreso_trozo(trozo_actual, total_trozos): opcional, llamado
        tras generar cada trozo cuando el texto se dividió en varios — permite
        que el llamador anime una barra de progreso durante fragmentos largos
        (p. ej. el libro completo en el Creador de Audiolibros) en vez de
        quedarse sin ninguna señal hasta que termina todo.

        Comprueba self._abortar antes de generar cada trozo y lanza
        _ExportacionAbortada si el usuario pidió detener la exportación —
        antes este bucle no se podía interrumpir hasta terminar el fragmento
        completo, dejando "Cancelando..." congelado en la interfaz.
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
                    f"en {len(trozos)} trozos para {proveedor}, generados en paralelo "
                    f"(hasta {min(_MAX_WORKERS_EXPORTACION, len(trozos))} a la vez)."
                )
                self._generar_trozos_en_paralelo(
                    trozos, datos_voz, ruta_salida, proveedor, callback_progreso_trozo
                )
                return

        if self._abortar:
            raise _ExportacionAbortada()
        self._llamar_motor(texto, datos_voz, ruta_salida, proveedor)

    def _generar_trozos_en_paralelo(
        self, trozos: list, datos_voz, ruta_salida: str, proveedor: str,
        callback_progreso_trozo=None,
    ):
        """
        Genera los trozos de un fragmento largo en paralelo con un
        ThreadPoolExecutor, en vez de uno detrás de otro — aprovecha la
        espera de red de las APIs de nube (o el reparto entre instancias de
        motor local independientes para SAPI5) para acortar el tiempo total
        de exportación.

        La numeración de los archivos temporales es atómica por índice de
        trozo (archivos_tmp[j], no por orden de llegada), así que el orden
        de finalización de los hilos es irrelevante: _concatenar_audios()
        siempre recibe la lista en el orden real del texto, sin importar
        qué hilo terminó primero. El progreso reportado sí es por orden de
        finalización (cuántos van completados, no cuál en concreto), que es
        lo único que le interesa a la barra de progreso.

        Si algún trozo falla (incluido el aborto del usuario), se cancelan
        los trozos pendientes que aún no habían empezado y se relanza el
        error una vez terminan los que ya estaban en marcha — sin dejar
        hilos sueltos ni archivos temporales huérfanos.
        """
        total = len(trozos)
        archivos_tmp = [None] * total
        lock = threading.Lock()
        contador = {"completados": 0}
        excepcion_pendiente = None

        def _generar(indice, trozo):
            if self._abortar:
                raise _ExportacionAbortada()
            fd, ruta_tmp = tempfile.mkstemp(suffix='.mp3', prefix=f'tfh_trozo{indice:03d}_')
            os.close(fd)
            self._llamar_motor(trozo, datos_voz, ruta_tmp, proveedor)
            return ruta_tmp

        max_workers = min(_MAX_WORKERS_EXPORTACION, total)
        try:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="grabador_trozo") as executor:
                futuros = {executor.submit(_generar, j, trozo): j for j, trozo in enumerate(trozos)}
                for futuro in as_completed(futuros):
                    indice = futuros[futuro]
                    try:
                        archivos_tmp[indice] = futuro.result()
                    except Exception as e:
                        if excepcion_pendiente is None:
                            excepcion_pendiente = e
                            for f in futuros:
                                f.cancel()
                        continue
                    if excepcion_pendiente is None:
                        with lock:
                            contador["completados"] += 1
                            n = contador["completados"]
                        if callback_progreso_trozo:
                            callback_progreso_trozo(n, total)

            if excepcion_pendiente is not None:
                raise excepcion_pendiente

            self._concatenar_audios(archivos_tmp, ruta_salida, proveedor=proveedor)
        finally:
            for tmp in archivos_tmp:
                if tmp:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except Exception:
                        pass

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
            audio = audio.set_frame_rate(44100).set_channels(1)
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

    # Umbral (dBFS) y margen (ms) de recorte de silencio por proveedor.
    # El motor "standard" de Polly (Conchita, Enrique, Miguel, Penélope...)
    # termina las palabras con una caída de volumen más suave que las voces
    # neuronales; con el umbral por defecto (-40 dBFS) el detector confundía
    # esa caída con silencio real y se comía la última sílaba en cada
    # costura de trozo. Umbral más estricto (más negativo) y margen mayor
    # para no recortar sonido real.
    _RECORTE_SILENCIO_POR_PROVEEDOR = {
        "polly": {"umbral_db": -50, "margen_ms": 120},
    }
    _RECORTE_SILENCIO_DEFECTO = {"umbral_db": -40, "margen_ms": 60}

    def _recortar_silencio_extremos(self, segmento, proveedor=None):
        """
        Recorta el silencio de sobra al principio y al final de un trozo de
        audio, dejando un margen natural configurado por proveedor.

        Cuando un texto largo se divide en varios trozos por el límite de
        caracteres del proveedor (_grabar_fragmento), cada trozo se sintetiza
        como un audio independiente. Varios proveedores añaden su propio
        silencio de entrada/salida a cada síntesis; al concatenar varios
        trozos ese silencio se suma en cada punto de unión, y como el corte
        cae por número de caracteres (no por frase), el resultado son
        pausas que no se corresponden con la puntuación real del texto.
        Recortar el silencio de cada trozo antes de unirlos evita que se
        acumule en cada costura.
        """
        ajuste = self._RECORTE_SILENCIO_POR_PROVEEDOR.get(
            (proveedor or "").lower(), self._RECORTE_SILENCIO_DEFECTO
        )
        umbral_db = ajuste["umbral_db"]
        margen_ms = ajuste["margen_ms"]
        try:
            from pydub import silence as pydub_silence
            inicio = pydub_silence.detect_leading_silence(segmento, silence_threshold=umbral_db)
            fin = pydub_silence.detect_leading_silence(segmento.reverse(), silence_threshold=umbral_db)
            inicio = max(0, inicio - margen_ms)
            fin = max(0, fin - margen_ms)
            if len(segmento) - fin > inicio:
                return segmento[inicio: len(segmento) - fin]
        except Exception:
            logger.debug("[GrabadorAudio] No se pudo recortar silencio de un trozo; se usa sin recortar.")
        return segmento

    def _concatenar_audios(self, archivos: list, ruta_salida: str, proveedor=None):
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

            segmentos = []
            for arch in archivos_validos:
                try:
                    seg = AudioSegment.from_file(arch, format='mp3')
                    segmentos.append(self._recortar_silencio_extremos(seg, proveedor=proveedor))
                except Exception as e:
                    logger.debug(
                        f"[GrabadorAudio] pydub no leyó {os.path.basename(arch)}: {e}"
                    )

            if segmentos:
                # Usar el primer segmento real como base evita que AudioSegment.empty()
                # (44100 Hz / 2 ch por defecto) contamine los metadatos del resultado.
                combined = segmentos[0]
                for seg in segmentos[1:]:
                    combined += seg
                combined = combined.set_frame_rate(44100).set_channels(1)
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
    # Helpers SSML: velocidad y volumen para Azure y Polly
    # ------------------------------------------------------------------ #

    def _velocidad_a_tasa_ssml(self, v: int) -> str:
        pct = int((v - 50) * 1.6)
        pct = max(-80, min(80, pct))
        return f"+{pct}%" if pct >= 0 else f"{pct}%"

    def _volumen_a_nivel_ssml(self, v: int) -> str:
        if v == 0:    return "silent"
        elif v < 20:  return "x-soft"
        elif v < 40:  return "soft"
        elif v < 70:  return "medium"
        elif v < 90:  return "loud"
        else:         return "x-loud"

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
        tasa      = self._velocidad_a_tasa_ssml(self._velocidad)
        nivel_vol = self._volumen_a_nivel_ssml(self._volumen)

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
            f"<lang xml:lang='{idioma}'>"
            f"<prosody rate='{tasa}' volume='{nivel_vol}'>"
            f"{texto_limpio}"
            f"</prosody>"
            f"</lang>"
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
            # Aplicar velocidad/volumen con pydub y normalizar a 44100 Hz mono
            try:
                import math
                from pydub import AudioSegment
                audio = AudioSegment.from_file(ruta_tmp, format='mp3')
                if self._velocidad != 50:
                    fs_efectiva = max(1, int(audio.frame_rate * (0.5 + self._velocidad / 100)))
                    audio = audio._spawn(audio.raw_data, overrides={"frame_rate": fs_efectiva})
                if self._volumen == 0:
                    audio = audio.apply_gain(-120)
                elif self._volumen != 100:
                    audio = audio.apply_gain(20 * math.log10(self._volumen / 100))
                audio = audio.set_frame_rate(44100).set_channels(1)
                audio.export(ruta_salida, format='mp3', bitrate='320k')
            except Exception:
                self._recodificar_mp3_320k(ruta_tmp, ruta_salida)
        finally:
            if os.path.exists(ruta_tmp):
                os.remove(ruta_tmp)

        logger.info(f"[ElevenLabs] {os.path.basename(ruta_salida)} (44.1kHz→44.1kHz 320k)")

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

        credenciales_actuales = (access_key, secret_key, region)
        if self._cliente_polly_boto3 is None or self._cliente_polly_credenciales != credenciales_actuales:
            self._cliente_polly_boto3 = boto3.client(
                'polly',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            self._cliente_polly_credenciales = credenciales_actuales
        cliente = self._cliente_polly_boto3

        texto_limpio = self._limpiar_xml(texto)
        tasa      = self._velocidad_a_tasa_ssml(self._velocidad)
        nivel_vol = self._volumen_a_nivel_ssml(self._volumen)
        # El motor "standard" de Polly tiene un problema conocido (reportado
        # en la comunidad de AWS): a veces recorta la última sílaba de la
        # última palabra del texto enviado, sin relación con cómo se
        # concatenan los trozos después — es el propio audio devuelto por
        # Polly el que ya viene corto. Confirmado también en lectura en vivo
        # (cliente_polly.py, sin trozeado ni concatenación de por medio), lo
        # que descarta que sea un problema de _recortar_silencio_extremos.
        #
        # El <break> SSML (aunque esté fuera de <prosody>, como se dejó en el
        # primer intento) deja de ser suficiente a velocidades altas: el
        # servidor de Polly parece truncar el búfer de renderizado antes de
        # que la pausa termine, sin importar cuánto dure. El remedio que sí
        # funciona de forma consistente es textual, no de temporización:
        # puntos suspensivos reales al final del texto obligan al motor
        # fonético a seguir articulando la última palabra real antes de
        # llegar a esos puntos. Se mantiene además el <break> fuera de
        # <prosody> como margen extra a velocidades altas, ya que no
        # perjudica. El silencio de sobra (puntos + break) se recorta
        # después en _recortar_silencio_extremos sin arriesgar la palabra
        # real, que ya quedó completa antes de la pausa.
        cola_ssml = ""
        sufijo_standard = ""
        if motor == 'standard':
            sufijo_standard = " ..."
            pct_velocidad = max(0, min(80, int((self._velocidad - 50) * 1.6)))
            break_ms = min(1000, 400 + int(pct_velocidad * 7.5))
            cola_ssml = f"<break time='{break_ms}ms'/>"
        ssml_text = (
            f"<speak><prosody rate='{tasa}' volume='{nivel_vol}'>"
            f"{texto_limpio}{sufijo_standard}"
            f"</prosody>{cola_ssml}</speak>"
        )

        # OGG Vorbis / 24000 Hz → sin «efecto teléfono»
        respuesta = cliente.synthesize_speech(
            Engine=motor,
            Text=ssml_text,
            TextType='ssml',
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
            sapi.Rate   = int((self._velocidad / 5) - 10)   # −10..+10
            sapi.Volume = self._volumen                      # 0..100
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
            audio = audio.set_frame_rate(44100).set_channels(1)
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
    # ANCLAJE_INICIO: EXPORTACION_AUDIOLIBROS_CREADOR
    #
    # Exportación silenciosa para el Creador de Audiolibros: volcado directo
    # a disco, sin pasar por la cola interactiva de reproductor_voz.py (esa
    # cola está pensada para lectura por altavoces con pausas/rebobinado, no
    # para exportación masiva a máxima velocidad).
    #
    # Consulta de cuota exclusivamente silenciosa: solo se usan
    # ControlCuota().tiene_cuota() y ControlCuota().registrar_gasto().
    # Prohibido aquí verificar_y_registrar() (levanta wx.MessageBox).
    #
    # Esta capa no toca biblioteca.db ni exportaciones_pendientes: se
    # limita a calcular, generar y devolver el estado de detención. La
    # persistencia en SQLite la resuelve la capa superior (pestaña /
    # gestor que llame a estos métodos).
    # ------------------------------------------------------------------ #

    def calcular_presupuesto(self, texto: str, proveedor: str) -> dict:
        """
        Cuenta caracteres y consulta la cuota de forma silenciosa, sin generar
        audio ni registrar gasto. La capa superior usa esto para mostrar el
        diálogo único de presupuesto (sección 3.2 de la planificación).
        """
        caracteres = len(texto)
        cabe_en_cuota = ControlCuota().tiene_cuota(texto, proveedor)
        return {"caracteres": caracteres, "cabe_en_cuota": cabe_en_cuota}

    def obtener_carpeta_audiolibro(self, titulo_libro: str, nombre_saga: str = None) -> str:
        """
        Carpeta exclusiva del Creador de Audiolibros, separada de la de
        Grabación de Fragmentos: Grabaciones_Epub-TTS/Audiolibros/<Título>/.

        Si `nombre_saga` viene informado (etiqueta de Biblioteca del libro),
        se intercala una subcarpeta con ese nombre para agrupar los libros
        de una misma saga automáticamente:
        Grabaciones_Epub-TTS/Audiolibros/<Saga>/<Título>/.
        """
        titulo_limpio = limpiar_nombre_archivo(titulo_libro)
        partes = [CARPETA_RAIZ_GRABACIONES, "Audiolibros"]
        if nombre_saga:
            partes.append(limpiar_nombre_archivo(nombre_saga))
        partes.append(titulo_limpio)
        carpeta = os.path.join(*partes)
        os.makedirs(carpeta, exist_ok=True)
        return carpeta

    def _buscar_punto_corte_por_cuota(self, texto: str, proveedor: str, control: ControlCuota) -> int:
        """
        Bisección silenciosa: encuentra el mayor N tal que el prefijo
        texto[:N] todavía cabe en la cuota disponible, usando exclusivamente
        control.tiene_cuota(). No genera audio ni registra gasto.
        """
        if control.tiene_cuota(texto, proveedor):
            return len(texto)

        bajo, alto = 0, len(texto)
        while bajo < alto:
            medio = (bajo + alto + 1) // 2
            if control.tiene_cuota(texto[:medio], proveedor):
                bajo = medio
            else:
                alto = medio - 1
        return bajo

    def _ajustar_punto_corte(self, texto: str, punto_bruto: int, fronteras_capitulo: list) -> int:
        """
        Ajusta el corte bruto (calculado solo por presupuesto de caracteres)
        hacia atrás hasta un punto seguro:
          1. La frontera de capítulo real más cercana que no supere el presupuesto.
          2. Si no hay ninguna (el presupuesto no alcanza ni el primer capítulo
             completo), el punto de frase más próximo.
          3. Como último respaldo, el espacio más cercano — nunca a mitad de palabra.

        fronteras_capitulo: lista de índices de carácter (dentro de `texto`)
        donde empieza cada capítulo, calculada por la capa superior a partir
        de troceador_epub.py. Este método no conoce la estructura del EPUB,
        solo trabaja con los índices que recibe.
        """
        if punto_bruto <= 0:
            return 0
        if punto_bruto >= len(texto):
            return len(texto)

        candidatas = [f for f in (fronteras_capitulo or []) if 0 < f <= punto_bruto]
        if candidatas:
            return max(candidatas)

        fragmento = texto[:punto_bruto]
        coincidencias = list(re.finditer(r'[.!?…]["\'”’)\]]?\s+', fragmento))
        if coincidencias:
            return coincidencias[-1].end()

        espacio = fragmento.rfind(' ')
        return espacio + 1 if espacio > 0 else punto_bruto

    def exportar_audiolibro_completo(
        self,
        texto: str,
        fronteras_capitulo: list,
        datos_voz: dict,
        titulo_libro: str,
        numero_parte: int = 1,
        velocidad: int = 50,
        volumen: int = 100,
        nombre_saga: str = None,
    ) -> dict:
        """
        Modo "libro completo": genera un único MP3. Si la cuota no alcanza
        para todo el texto, corta en la frontera de capítulo o frase más
        cercana (sin romper palabras) y guarda lo generado como parte
        pendiente.

        Returns:
            dict con el estado de la exportación:
              completo (bool), punto_corte (int|None), archivos_generados,
              errores, carpeta_destino, numero_parte.
        """
        self._abortar = False
        self._velocidad = max(0, min(100, int(velocidad)))
        self._volumen = max(0, min(100, int(volumen)))
        self._cargar_config()

        proveedor = (
            datos_voz.get('proveedor_id', 'local') if isinstance(datos_voz, dict) else 'local'
        )
        control = ControlCuota()

        punto_bruto = self._buscar_punto_corte_por_cuota(texto, proveedor, control)
        completo = punto_bruto >= len(texto)
        punto_corte = None if completo else self._ajustar_punto_corte(texto, punto_bruto, fronteras_capitulo)
        texto_a_generar = texto if completo else texto[:punto_corte]

        carpeta_destino = self.obtener_carpeta_audiolibro(titulo_libro, nombre_saga=nombre_saga)

        if not texto_a_generar.strip():
            return {
                "completo": False,
                "punto_corte": 0,
                "archivos_generados": [],
                "errores": ["Sin cuota disponible para generar ni el primer fragmento."],
                "carpeta_destino": carpeta_destino,
                "numero_parte": numero_parte,
            }

        titulo_limpio = limpiar_nombre_archivo(titulo_libro)
        if completo and numero_parte <= 1:
            nombre_archivo = f"{titulo_limpio}.mp3"
        elif completo:
            # Parte 2 o posterior que sí llega a terminar el texto que le
            # tocaba: se mantiene la etiqueta de parte para no generar un
            # archivo "{titulo}.mp3" a secas que dé a entender que es el
            # libro entero cuando en realidad es solo la continuación.
            nombre_archivo = f"{titulo_limpio} (parte {numero_parte}).mp3"
        else:
            nombre_archivo = f"{titulo_limpio} (parte {numero_parte} - pendiente).mp3"
        ruta_salida = os.path.join(carpeta_destino, nombre_archivo)

        nombre_voz = datos_voz.get('nombre', 'sin nombre') if isinstance(datos_voz, dict) else 'sin voz'
        if self.callback_progreso:
            self.callback_progreso(0, 1, titulo_libro, nombre_voz)

        def _al_progreso_trozo(actual_trozo, total_trozos):
            if self.callback_progreso:
                self.callback_progreso(actual_trozo, total_trozos, titulo_libro, nombre_voz)

        errores = []
        archivos_generados = []
        abortada = False
        if not self._abortar:
            for intento in range(3):
                try:
                    self._grabar_fragmento(
                        texto_a_generar, datos_voz, ruta_salida,
                        callback_progreso_trozo=_al_progreso_trozo,
                    )
                    archivos_generados.append(ruta_salida)
                    control.registrar_gasto(texto_a_generar, proveedor)
                    break
                except _ExportacionAbortada:
                    logger.info("[GrabadorAudio] Exportación de libro completo abortada por el usuario.")
                    abortada = True
                    break
                except Exception as e:
                    logger.warning(
                        f"[GrabadorAudio] Intento {intento + 1}/3 fallido al exportar "
                        f"'{titulo_libro}': {e}"
                    )
                    if intento == 2:
                        errores.append(f"{titulo_libro}: {e}")

        if self.callback_progreso and archivos_generados:
            self.callback_progreso(1, 1, titulo_libro, nombre_voz)

        return {
            "completo": completo and bool(archivos_generados),
            "punto_corte": punto_corte if archivos_generados else 0,
            "archivos_generados": archivos_generados,
            "errores": errores,
            "carpeta_destino": carpeta_destino,
            "numero_parte": numero_parte,
        }

    def exportar_audiolibro_por_capitulos(
        self,
        capitulos: list,
        datos_voz: dict,
        titulo_libro: str,
        velocidad: int = 50,
        volumen: int = 100,
        nombre_saga: str = None,
    ) -> dict:
        """
        Modo "por capítulos": un MP3 por capítulo, nombrado "1. Capítulo uno.mp3".

        La decisión de qué capítulos caben en la cuota disponible sigue
        siendo estrictamente secuencial y en orden (fase 1, abajo): en
        cuanto uno no cabe, ese capítulo y todos los siguientes quedan
        "pendiente_sin_cuota" — nunca se salta uno para grabar uno
        posterior más corto, para no dejar huecos sueltos en el audiolibro.
        Esa comprobación es aritmética pura (ControlCuota.tiene_cuota no
        hace ninguna llamada de red), así que recorrerla entera es
        prácticamente instantánea incluso con cientos de capítulos.

        La generación real del audio (fase 2, la lenta) sí se hace en
        paralelo con un ThreadPoolExecutor: cada capítulo incluido escribe
        directamente a su propio archivo numerado ("1. Título.mp3", "2. ...")
        — el nombre depende del índice fijo del capítulo, nunca del orden en
        que terminan los hilos, así que no hace falta ningún paso de
        reordenación posterior.

        capitulos: lista de tuplas (titulo_capitulo, texto_capitulo).

        Returns:
            dict con capitulos (lista de estado por capítulo), archivos_generados,
            errores, carpeta_destino.
        """
        self._abortar = False
        self._velocidad = max(0, min(100, int(velocidad)))
        self._volumen = max(0, min(100, int(volumen)))
        self._cargar_config()

        proveedor = (
            datos_voz.get('proveedor_id', 'local') if isinstance(datos_voz, dict) else 'local'
        )
        nombre_voz = datos_voz.get('nombre', 'sin nombre') if isinstance(datos_voz, dict) else 'sin voz'
        control = ControlCuota()

        carpeta_destino = self.obtener_carpeta_audiolibro(titulo_libro, nombre_saga=nombre_saga)
        total = len(capitulos)

        # ── Fase 1: qué capítulos caben en la cuota, en orden ────────────
        incluidos = []   # lista de (indice, titulo, texto)
        estado_capitulos = [None] * total
        for i, (titulo_capitulo, texto_capitulo) in enumerate(capitulos):
            if self._abortar or not control.tiene_cuota(texto_capitulo, proveedor):
                estado_capitulos[i] = {
                    "indice": i, "titulo": titulo_capitulo,
                    "estado": "pendiente_sin_cuota", "ruta": None,
                }
                # A partir de aquí todo el resto queda pendiente también,
                # se agoten o no realmente su cuota individual — es la misma
                # regla de "sin huecos" que antes, solo que ahora se marca
                # de una vez en vez de comprobar cada uno.
                for j in range(i + 1, total):
                    estado_capitulos[j] = {
                        "indice": j, "titulo": capitulos[j][0],
                        "estado": "pendiente_sin_cuota", "ruta": None,
                    }
                break
            incluidos.append((i, titulo_capitulo, texto_capitulo))
        else:
            pass

        if self._abortar:
            logger.info("[GrabadorAudio] Exportación por capítulos abortada antes de generar audio.")

        # ── Fase 2: generación en paralelo de los capítulos incluidos ────
        archivos_generados = [None] * total
        errores = []
        lock = threading.Lock()

        def _generar_capitulo(indice, titulo_capitulo, texto_capitulo):
            if self._abortar:
                return indice, titulo_capitulo, None, "Exportación abortada por el usuario."
            nombre_limpio = limpiar_nombre_archivo(titulo_capitulo)
            nombre_arch = f"{indice + 1}. {nombre_limpio}.mp3"
            ruta_arch = os.path.join(carpeta_destino, nombre_arch)

            ultimo_error = None
            for intento in range(3):
                if self._abortar:
                    return indice, titulo_capitulo, None, "Exportación abortada por el usuario."
                try:
                    self._grabar_fragmento(texto_capitulo, datos_voz, ruta_arch)
                    with lock:
                        control.registrar_gasto(texto_capitulo, proveedor)
                    return indice, titulo_capitulo, ruta_arch, None
                except Exception as e:
                    ultimo_error = e
                    logger.warning(
                        f"[GrabadorAudio] Intento {intento + 1}/3 fallido "
                        f"(capítulo {indice + 1}, '{titulo_capitulo}'): {e}"
                    )
            return indice, titulo_capitulo, None, str(ultimo_error)

        if incluidos:
            max_workers = min(_MAX_WORKERS_EXPORTACION, len(incluidos))
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="grabador_capitulo") as executor:
                futuros = [
                    executor.submit(_generar_capitulo, i, titulo, texto)
                    for i, titulo, texto in incluidos
                ]
                completados = 0
                for futuro in as_completed(futuros):
                    indice, titulo_capitulo, ruta_arch, error = futuro.result()
                    if ruta_arch:
                        estado_capitulos[indice] = {
                            "indice": indice, "titulo": titulo_capitulo,
                            "estado": "completado", "ruta": ruta_arch,
                        }
                        archivos_generados[indice] = ruta_arch
                    else:
                        estado_capitulos[indice] = {
                            "indice": indice, "titulo": titulo_capitulo,
                            "estado": "pendiente_sin_cuota", "ruta": None,
                        }
                        if error and "abortada" not in error:
                            errores.append(f"Capítulo {indice + 1} ('{titulo_capitulo}'): {error}")

                    completados += 1
                    if self.callback_progreso:
                        # "completados" (cuántos van, no cuál en concreto) es
                        # lo único que tiene sentido reportar cuando varios
                        # capítulos terminan en paralelo y no en orden.
                        self.callback_progreso(completados, len(incluidos), titulo_capitulo, nombre_voz)

        archivos_generados = [a for a in archivos_generados if a]

        return {
            "capitulos": estado_capitulos,
            "archivos_generados": archivos_generados,
            "errores": errores,
            "carpeta_destino": carpeta_destino,
        }
    # ANCLAJE_FIN: EXPORTACION_AUDIOLIBROS_CREADOR

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
