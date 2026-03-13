import logging
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
        lista = []
        if self.conectado:
            try:
                voces = self.motor.GetVoices()
                for i in range(voces.Count):
                    item = voces.Item(i)
                    desc = item.GetDescription()
                    lista.append({
                        "id": item.Id,
                        "nombre": desc,
                        "proveedor_id": "local", 
                        "objeto_real": item
                    })
            except: pass
        return lista

    def hablar(self, texto):
        if self.conectado:
            try:
                # SOLUCIÓN DEL SILENCIO:
                # 1. Aseguramos volumen al 100 por si acaso
                self.motor.Volume = 100
                
                # 2. NO paramos aquí. Ya lo hizo el reproductor antes.
                # 3. Usamos SPF_IS_NOT_XML para que si el libro tiene símbolos < o >
                #    SAPI no se crea que son comandos y falle.
                self.motor.Speak(texto, SPF_ASYNC | SPF_IS_NOT_XML)
            except Exception as e:
                logger.warning("[SAPI5] Error al hablar: %s", e)
                self._inicializar_motor()

    def detener(self):
        if self.conectado:
            try:
                # Aquí sí paramos y purgamos la cola
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
        """Busca y activa una voz local de forma inteligente."""
        if not self.motor: return
        logger.debug("[SAPI5] Buscando voz: %s", nombre_objetivo)
        try:
            voces = self.motor.GetVoices()
            for i in range(voces.Count):
                voz = voces.Item(i)
                desc = voz.GetDescription()
                if nombre_objetivo.lower() in desc.lower():
                    self.motor.Voice = voz
                    logger.debug("[SAPI5] Voz cambiada a: %s", desc)
                    return
            logger.debug("[SAPI5] No se encontró voz: %s", nombre_objetivo)
        except Exception as e:
            logger.warning("[SAPI5] Error al cambiar voz: %s", e)