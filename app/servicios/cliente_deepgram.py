import requests
import sounddevice as sd
import soundfile as sf
import io
import time
import numpy as np
from app.config_rutas import cargar_claves

_MAX_CACHE = 5
_LIMITE_CHARS = 1950  # La API permite 2000; usamos 1950 de margen

# Voces Deepgram Aura disponibles (lista estática)
_VOCES_DEEPGRAM = [
    {"nombre": "Asteria",  "id": "aura-asteria-en",  "idioma": "en-US", "genero": "Female", "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Luna",     "id": "aura-luna-en",     "idioma": "en-US", "genero": "Female", "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Stella",   "id": "aura-stella-en",   "idioma": "en-US", "genero": "Female", "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Athena",   "id": "aura-athena-en",   "idioma": "en-GB", "genero": "Female", "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Hera",     "id": "aura-hera-en",     "idioma": "en-US", "genero": "Female", "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Orion",    "id": "aura-orion-en",    "idioma": "en-US", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Arcas",    "id": "aura-arcas-en",    "idioma": "en-US", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Perseus",  "id": "aura-perseus-en",  "idioma": "en-US", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Angus",    "id": "aura-angus-en",    "idioma": "en-IE", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Orpheus",  "id": "aura-orpheus-en",  "idioma": "en-US", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Helios",   "id": "aura-helios-en",   "idioma": "en-GB", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
    {"nombre": "Zeus",     "id": "aura-zeus-en",     "idioma": "en-US", "genero": "Male",   "proveedor": "Deepgram", "proveedor_id": "deepgram"},
]


class ClienteDeepgram:
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
        return [dict(v) for v in _VOCES_DEEPGRAM]

    def _guardar_en_cache(self, texto, data, fs):
        """Guarda audio en caché con límite de _MAX_CACHE entradas (LRU simple)."""
        if texto not in self._cache_frags:
            if len(self._cache_lru) >= _MAX_CACHE:
                clave_antigua = self._cache_lru.pop(0)
                self._cache_frags.pop(clave_antigua, None)
            self._cache_lru.append(texto)
        self._cache_frags[texto] = (data, fs)

    def _trocear(self, texto):
        """
        Divide el texto en trozos de como máximo _LIMITE_CHARS caracteres,
        intentando cortar en límites de frase (.!?…), luego en espacios y,
        como último recurso, cortando directamente en _LIMITE_CHARS.
        Devuelve una lista de strings no vacíos.
        """
        trozos = []
        while len(texto) > _LIMITE_CHARS:
            candidato = texto[:_LIMITE_CHARS]
            # Buscar el último signo de puntuación de fin de oración
            pos_corte = -1
            for signo in ".!?…":
                p = candidato.rfind(signo)
                if p > pos_corte:
                    pos_corte = p

            if pos_corte > 0:
                # Cortar tras el signo de puntuación (incluirlo en el trozo)
                corte = pos_corte + 1
            else:
                # No hay puntuación: cortar en el último espacio
                corte = candidato.rfind(" ")
                if corte <= 0:
                    # Corte duro en el límite
                    corte = _LIMITE_CHARS

            trozo = texto[:corte].strip()
            if trozo:
                trozos.append(trozo)
            texto = texto[corte:].strip()

        if texto:
            trozos.append(texto)
        return trozos

    def _llamar_api_chunk(self, trozo, datos_voz):
        """
        Realiza una única llamada a la API de Deepgram para un trozo de texto.
        Implementa 1 reintento automático ante errores de conexión transitoria.
        Devuelve (data, fs) con el audio en crudo sin aplicar velocidad ni volumen.
        """
        self.config = self._cargar_config()
        dg_conf = self.config.get("deepgram", {})
        api_key = dg_conf.get("api_key", "").strip()

        if not api_key:
            raise Exception("Falta API Key de Deepgram")

        if isinstance(datos_voz, dict):
            model_id = datos_voz.get("id", "aura-asteria-en")
        else:
            model_id = datos_voz or "aura-asteria-en"

        url = f"https://api.deepgram.com/v1/speak?model={model_id}&encoding=linear16&sample_rate=22050"
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"text": trozo}

        response = None
        for intento in range(2):
            try:
                response = self._sesion.post(url, json=payload, headers=headers, timeout=30)
                break
            except requests.exceptions.Timeout:
                raise Exception("Deepgram tardó demasiado (Timeout > 30s).")
            except requests.exceptions.ConnectionError:
                if intento == 0 and not self._parado:
                    time.sleep(1)
                    self._sesion = requests.Session()
                    continue
                raise

        if response is None or response.status_code != 200:
            codigo = response.status_code if response is not None else "sin respuesta"
            detalle = response.text[:200] if response is not None else ""
            raise Exception(f"Error Deepgram: {codigo} {detalle}")

        data, fs = sf.read(io.BytesIO(response.content))
        return data, fs

    def _llamar_api(self, texto, datos_voz):
        """
        Trocea el texto si supera el límite de la API, llama a _llamar_api_chunk
        para cada trozo y concatena los arrays de audio resultantes con numpy.
        Aplica volumen y velocidad (truco de sample-rate) antes de retornar.
        Devuelve (data, fs_efectiva).
        """
        trozos = self._trocear(texto)
        if not trozos:
            raise Exception("Error Deepgram: texto vacío")

        fragmentos = []
        fs_final = 22050  # valor por defecto; se sobreescribe con el real
        for trozo in trozos:
            if self._parado:
                break
            data, fs = self._llamar_api_chunk(trozo, datos_voz)
            fs_final = fs
            fragmentos.append(data)

        if not fragmentos:
            raise Exception("Error Deepgram: sin datos de audio")

        if len(fragmentos) == 1:
            data_completa = fragmentos[0]
        else:
            data_completa = np.concatenate(fragmentos, axis=0)

        # Aplicar volumen
        if self._volumen != 100:
            data_completa = data_completa * (self._volumen / 100.0)

        # Aplicar velocidad mediante truco de frame-rate
        fs_efectiva = int(fs_final * (0.5 + self._velocidad / 100.0))

        return data_completa, fs_efectiva

    def hablar(self, texto, datos_voz):
        """Sintetiza y reproduce el texto. Prioridad: caché → buffer proactivo → API."""
        self._parado = False

        if texto in self._cache_frags:
            data, fs_efectiva = self._cache_frags[texto]
        elif self._audio_preparado is not None and self._texto_preparado == texto:
            data, fs_efectiva = self._audio_preparado
            self._audio_preparado = None
            self._texto_preparado = None
            self._guardar_en_cache(texto, data, fs_efectiva)
        else:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(texto, data, fs_efectiva)

        if not self._parado:
            sd.play(data, fs_efectiva)
            sd.wait()

    def preparar(self, texto, datos_voz):
        """
        Pre-descarga el audio en segundo plano. Si ya está en caché, lo reutiliza.
        El resultado se guarda siempre: detener() no debe invalidarlo porque el
        audio descargado es para el SIGUIENTE fragmento, no para el actual.
        """
        if texto in self._cache_frags:
            self._audio_preparado = self._cache_frags[texto]
            self._texto_preparado = texto
            return
        try:
            data, fs_efectiva = self._llamar_api(texto, datos_voz)
            self._guardar_en_cache(texto, data, fs_efectiva)
            self._audio_preparado = (data, fs_efectiva)
            self._texto_preparado = texto
        except Exception:
            self._audio_preparado = None
            self._texto_preparado = None

    def detener(self):
        """
        Detiene el audio y cancela peticiones HTTP activas.
        El caché y el buffer proactivo se conservan para el siguiente fragmento.
        """
        self._parado = True
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
