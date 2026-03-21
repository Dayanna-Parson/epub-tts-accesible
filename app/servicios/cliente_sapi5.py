import logging
import threading
import wx
import comtypes.client

logger = logging.getLogger(__name__)

# Constantes SAPI
SPF_ASYNC = 1            # No congela la app
SPF_PURGEBEFORESPEAK = 2 # Stop inmediato
SPF_IS_NOT_XML = 8       # Tratar texto como plano (evita errores con símbolos < >)

class ClienteSapi5:
    def __init__(self):
        self.motor = None
        self.conectado = False
        # Control de hilo de lectura párrafo a párrafo
        self._detener_flag = False
        self._generacion_sapi = 0
        self._inicializar_motor()

    def _inicializar_motor(self):
        try:
            self.motor = comtypes.client.CreateObject("SAPI.SpVoice")
            self.motor.Rate = 0
            self.motor.Volume = 100
            self.conectado = True
        except Exception as e:
            logger.warning("[SAPI5] No se pudo inicializar el motor: %s", e)
            self.conectado = False

    def obtener_voces(self):
        """
        Enumera todas las voces SAPI5 del sistema, incluyendo las voces OneCore
        (Windows 10/11) que no aparecen con GetVoices() estándar.
        """
        lista = []
        ids_vistos = set()

        def _leer_categoria(categoria_id):
            """Devuelve una lista de voces de una categoría de token SAPI5."""
            resultado = []
            try:
                sp_cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
                sp_cat.SetId(categoria_id, False)
                tokens = sp_cat.EnumTokens()
                for i in range(tokens.Count):
                    try:
                        item = tokens.Item(i)
                        vid = item.Id
                        if vid in ids_vistos:
                            continue
                        desc = item.GetDescription()
                        ids_vistos.add(vid)
                        resultado.append({
                            "id": vid,
                            "nombre": desc,
                            "proveedor_id": "local",
                        })
                    except Exception as e:
                        logger.debug("[SAPI5] Error leyendo token de voz: %s", e)
            except Exception as e:
                logger.debug("[SAPI5] Categoría '%s' no disponible: %s", categoria_id, e)
            return resultado

        if not self.conectado:
            logger.warning("[SAPI5] Motor no inicializado; no se pueden listar voces.")
            return lista

        # 1. Voces SAPI5 clásicas (HKLM\...\Speech\Voices)
        try:
            voces = self.motor.GetVoices()
            for i in range(voces.Count):
                try:
                    item = voces.Item(i)
                    vid  = item.Id
                    desc = item.GetDescription()
                    ids_vistos.add(vid)
                    lista.append({
                        "id": vid,
                        "nombre": desc,
                        "proveedor_id": "local",
                    })
                except Exception as e:
                    logger.debug("[SAPI5] Error leyendo voz estándar: %s", e)
        except Exception as e:
            logger.warning("[SAPI5] GetVoices() falló: %s", e)

        # 2. Voces OneCore — Windows 10/11 (suelen ser voces de alta calidad)
        lista += _leer_categoria(
            r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"
        )

        # 3. Voces modernas por usuario — Windows 11
        lista += _leer_categoria(
            r"HKEY_CURRENT_USER\SOFTWARE\Microsoft\Speech_ModernVoices"
        )

        logger.debug("[SAPI5] Total voces encontradas: %d", len(lista))
        return lista

    def hablar(self, texto):
        """Habla el texto completo de una vez (sin sincronización de cursor)."""
        if self.conectado:
            self._detener_flag = False
            try:
                self.motor.Volume = 100
                self.motor.Speak(texto, SPF_ASYNC | SPF_IS_NOT_XML)
            except Exception as e:
                logger.warning("[SAPI5] Error al hablar: %s", e)
                self._inicializar_motor()

    def hablar_con_callback(self, texto, pos_offset, callback_progreso, callback_completado):
        """
        Habla el texto párrafo a párrafo (igual que Bookworm).
        - callback_progreso(pos): llamado en el hilo principal al iniciar cada párrafo.
          Recibe la posición del párrafo en el texto global → mueve el cursor exacto.
        - callback_completado(): llamado en el hilo principal cuando termina todo.

        Pausa/reanudación funciona vía motor.Pause() / motor.Resume() sin
        interrumpir el hilo. Stop limpio mediante _detener_flag + purge de SAPI.
        """
        if not self.conectado:
            return
        # Incrementar generación invalida el hilo anterior (si lo hubiera)
        self._detener_flag = False
        self._generacion_sapi += 1
        gen = self._generacion_sapi
        threading.Thread(
            target=self._hilo_parrafos,
            args=(texto, pos_offset, callback_progreso, callback_completado, gen),
            daemon=True,
        ).start()

    def _hilo_parrafos(self, texto, pos_offset, callback_progreso, callback_completado, gen):
        """
        Hilo de fondo: habla cada párrafo sincrónicamente y dispara callbacks.
        WaitUntilDone(100) permite verificar _detener_flag cada 100 ms sin
        consumir CPU, y se comporta bien durante una pausa (motor.Pause() pausa
        el audio pero WaitUntilDone sigue esperando hasta motor.Resume()).
        """
        pos = pos_offset
        for linea in texto.split('\n'):
            # Comprobar cancelación antes de cada párrafo
            if self._detener_flag or self._generacion_sapi != gen:
                return
            if linea.strip():
                # Notificar posición al hilo principal (mueve cursor al párrafo)
                wx.CallAfter(callback_progreso, pos)
                try:
                    self.motor.Volume = 100
                    self.motor.Speak(linea, SPF_ASYNC | SPF_IS_NOT_XML)
                    # Esperar fin de párrafo en intervalos de 100 ms
                    while not self._detener_flag and self._generacion_sapi == gen:
                        if self.motor.WaitUntilDone(100):
                            break  # párrafo completado
                except Exception as e:
                    logger.warning("[SAPI5] Error en párrafo: %s", e)
                    if not self.conectado:
                        return
            pos += len(linea) + 1  # +1 por el \n eliminado al hacer split

        if not self._detener_flag and self._generacion_sapi == gen:
            wx.CallAfter(callback_completado)

    def detener(self):
        if self.conectado:
            # Señalizar al hilo de párrafos que debe detenerse
            self._detener_flag = True
            try:
                self.motor.Speak("", SPF_ASYNC | SPF_PURGEBEFORESPEAK)
            except: pass

    def pausar(self):
        if self.conectado:
            try: self.motor.Pause()
            except: pass

    def reanudar(self):
        if self.conectado:
            try: self.motor.Resume()
            except: pass

    def fijar_velocidad(self, v):
        if self.conectado:
            try:
                tasa = int((v / 5) - 10)
                self.motor.Rate = max(-10, min(10, tasa))
            except: pass

    def fijar_volumen(self, v):
        if self.conectado:
            try: self.motor.Volume = int(v)
            except: pass

    def cambiar_voz_por_nombre(self, nombre_objetivo):
        """
        Busca y activa una voz SAPI5 por nombre, incluyendo voces OneCore y modernas
        (Windows 10/11) que no aparecen en la categoría estándar.
        """
        if not self.motor:
            return
        logger.debug("[SAPI5] Buscando voz: %s", nombre_objetivo)

        _CATEGORIAS = [
            None,  # GetVoices() estándar
            r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
            r"HKEY_CURRENT_USER\SOFTWARE\Microsoft\Speech_ModernVoices",
        ]

        nombre_lower = nombre_objetivo.lower()

        for cat_id in _CATEGORIAS:
            try:
                if cat_id is None:
                    tokens = self.motor.GetVoices()
                else:
                    sp_cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
                    sp_cat.SetId(cat_id, False)
                    tokens = sp_cat.EnumTokens()

                for i in range(tokens.Count):
                    try:
                        tok  = tokens.Item(i)
                        desc = tok.GetDescription()
                        if nombre_lower in desc.lower():
                            self.motor.Voice = tok
                            logger.debug("[SAPI5] Voz cambiada a: %s", desc)
                            return
                    except Exception as e:
                        logger.debug("[SAPI5] Error leyendo token: %s", e)
            except Exception as e:
                logger.debug("[SAPI5] Categoría '%s' no disponible: %s", cat_id, e)

        logger.warning("[SAPI5] No se encontró voz con nombre: %s", nombre_objetivo)
