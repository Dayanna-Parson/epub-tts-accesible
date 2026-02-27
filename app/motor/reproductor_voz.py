# ANCLAJE_INICIO: IMPORTACIONES
import os
import json
import threading
import time
import wx
from app.servicios.cliente_sapi5 import ClienteSapi5
from app.servicios.cliente_azure import ClienteAzure
from app.servicios.cliente_eleven import ClienteEleven
from app.servicios.cliente_polly import ClientePolly
# ANCLAJE_FIN: IMPORTACIONES

# ANCLAJE_INICIO: CLASE_REPRODUCTOR
class ReproductorVoz:
    """
    Clase principal para la gestión de la salida de audio.
    Controla la lógica de conmutación entre motores de síntesis de voz locales y en la nube.
    """
    def __init__(self):
        self.config = self._cargar_config()
        
        # Inicialización de motores de síntesis
        self.cliente_local = ClienteSapi5()
        self.cliente_azure = ClienteAzure()
        self.cliente_eleven = ClienteEleven()
        self.cliente_polly = ClientePolly()
        
        # Estado inicial del sistema        
        self.motor_activo = self.cliente_local
        self.tipo_motor_actual = "local"
        self.voz_actual = None
        self.estado = "detenido"
        self._hilo_reproduccion = None

    def _cargar_config(self):
        """Carga la configuración de voces desde el archivo JSON global."""
        try:
            ruta = os.path.join("configuraciones", "config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
        return {}
    def fijar_voz(self, datos_voz):
        self.detener() 
        self.voz_actual = datos_voz
        
        proveedor = datos_voz.get("proveedor_id", "local").lower()
        
        if "azure" in proveedor:
            self.motor_activo = self.cliente_azure
            self.tipo_motor_actual = "azure"
        elif "eleven" in proveedor:
            self.motor_activo = self.cliente_eleven
            self.tipo_motor_actual = "eleven"
        elif "polly" in proveedor:
            self.motor_activo = self.cliente_polly
            self.tipo_motor_actual = "polly"
            pass
        else:

            # ANCLAJE_INICIO: CONFIGURACION_VOZ_ACTIVA
            # --- FIX PARA SAPI5 (VOCES LOCALES) ---
            self.motor_activo = self.cliente_local
            self.tipo_motor_actual = "local"
            
            # Le decimos a SAPI que cambie la voz.
            nombre_voz = datos_voz.get("nombre", "")
            if hasattr(self.cliente_local, "cambiar_voz_por_nombre"):
                self.cliente_local.cambiar_voz_por_nombre(nombre_voz)
            # ANCLAJE_FIN: CONFIGURACION_VOZ_ACTIVA

# ANCLAJE_INICIO: FLUJO_PRINCIPAL_SINTESIS
    def cargar_texto(self, texto):
        """
        Inicia la lectura del texto.
        Aplica el método adecuado según si se usa una voz local o una voz neuronal.
        """
        if not texto: return
        
        # Detener cualquier lectura en curso antes de iniciar una nueva
        self.detener()
        time.sleep(0.05) 
        
        self.estado = "reproduciendo"
        
        if self.tipo_motor_actual == "local":
            # Ejecución directa para voces locales SAPI5
            try:
                self.cliente_local.hablar(texto)
            except Exception as e:
                print(f"Error en voz local: {e}")
                self.estado = "detenido"
        else:
            # Voces neuronales: Se ejecutan en segundo plano para no bloquear el lector de pantalla ni la interfaz
            self._hilo_reproduccion = threading.Thread(
                target=self._procesar_voz_neuronal, 
                args=(texto,), 
                daemon=True
            )
            self._hilo_reproduccion.start()
    # ANCLAJE_FIN: FLUJO_PRINCIPAL_SINTESIS

    # ANCLAJE_INICIO: PROCESAMIENTO_VOCES_NEURONALES
    def _procesar_voz_neuronal(self, texto):
        """
        Gestiona la reproducción de las voces neuronales sin interrumpir el uso del programa.
        """
        try:
            if self.voz_actual:
                # Envío del texto al proveedor y espera de la respuesta de audio
                self.motor_activo.hablar(texto, self.voz_actual)
        except Exception as e:
            error_msg = str(e)
            print(f"Error en el servicio de voz neuronal ({self.tipo_motor_actual}): {error_msg}")
            
            # Notificamos al usuario de forma segura
            wx.CallAfter(self._activar_voz_local_automatica, error_msg, texto)
        
        self.estado = "detenido"
    # ANCLAJE_FIN: PROCESAMIENTO_VOCES_NEURONALES

    # ANCLAJE_INICIO: ACTIVACION_VOZ_LOCAL_AUTOMATICA
    def _activar_voz_local_automatica(self, error_msg, texto):
        """
        Activa automáticamente una voz local si el servicio de la voz neuronal falla o pierde conexión.
        """
        wx.MessageBox(
            f"No se ha podido conectar con el servicio de voz con IA ({self.tipo_motor_actual.upper()}).\n\n"
            f"Detalle: {error_msg}\n\n"
            "Para que la lectura no se detenga, continuaremos usando tu voz local.", 
            "Aviso sobre la voz de lectura"
        )
        try:
            self.cliente_local.hablar(texto)
        except: pass
    # ANCLAJE_FIN: ACTIVACION_VOZ_LOCAL_AUTOMATICA

    # ANCLAJE_INICIO: COMANDOS_REPRODUCTOR
    def detener(self):
        """Finaliza cualquier proceso de audio activo en todos los motores."""
        try: self.cliente_local.detener()
        except: pass
        try: self.cliente_azure.detener()
        except: pass
        try: self.cliente_eleven.detener()
        except: pass
        self.estado = "detenido"

    def pausar(self): 
        """Interrumpe temporalmente la salida de audio."""
        if self.tipo_motor_actual == "local":
            self.cliente_local.pausar()
        else:
            self.detener() 
        self.estado = "pausado"

    def reanudar(self):
        """Recupera la reproducción desde el punto de interrupción."""
        if self.tipo_motor_actual == "local":
            self.cliente_local.reanudar()
            self.estado = "reproduciendo"
        # Las voces neuronales requieren reenviar el texto desde la posición actual
    # ANCLAJE_FIN: COMANDOS_REPRODUCTOR

    def obtener_estado(self): return self.estado
    def fijar_velocidad(self, v): 
        if hasattr(self.motor_activo, 'fijar_velocidad'): self.motor_activo.fijar_velocidad(v)
    def fijar_volumen(self, v):
        if hasattr(self.motor_activo, 'fijar_volumen'): self.motor_activo.fijar_volumen(v)