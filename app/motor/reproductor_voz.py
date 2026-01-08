import os
import json
import threading
import time
import wx
from app.servicios.cliente_sapi5 import ClienteSapi5
from app.servicios.cliente_azure import ClienteAzure
from app.servicios.cliente_eleven import ClienteEleven
# from app.servicios.cliente_polly import ClientePolly 

class ReproductorVoz:
    def __init__(self):
        self.config = self._cargar_config()
        
        # Motores
        self.cliente_local = ClienteSapi5()
        self.cliente_azure = ClienteAzure()
        self.cliente_eleven = ClienteEleven()
        # self.cliente_polly = ClientePolly() # Descomenta si usas Polly
        
        self.motor_activo = self.cliente_local
        self.tipo_motor_actual = "local"
        self.voz_actual = None
        self.estado = "detenido"
        self._hilo_reproduccion = None

    def _cargar_config(self):
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
            # self.motor_activo = self.cliente_polly
            # self.tipo_motor_actual = "polly"
            pass
        else:
            # --- FIX PARA SAPI5 (VOCES LOCALES) ---
            self.motor_activo = self.cliente_local
            self.tipo_motor_actual = "local"
            
            # Importante: Decirle a SAPI que cambie la voz AHORA
            nombre_voz = datos_voz.get("nombre", "")
            if hasattr(self.cliente_local, "cambiar_voz_por_nombre"):
                self.cliente_local.cambiar_voz_por_nombre(nombre_voz)
    def cargar_texto(self, texto):
        """
        Punto de entrada principal. Decide si usar hilo o no.
        """
        if not texto: return
        
        # 1. Asegurar parada limpia
        self.detener()
        time.sleep(0.05) # Pequeña pausa para liberar buffers de audio
        
        self.estado = "reproduciendo"
        
        # 2. Lógica HÍBRIDA
        if self.tipo_motor_actual == "local":
            # SAPI5: Ejecutar en hilo principal (es lo más seguro para COM)
            # SAPI ya gestiona su propia asincronía internamente.
            try:
                self.cliente_local.hablar(texto)
            except Exception as e:
                print(f"Error local: {e}")
                self.estado = "detenido"
        else:
            # NUBE: OBLIGATORIO usar hilo para no congelar la UI
            self._hilo_reproduccion = threading.Thread(
                target=self._procesar_hilo_nube, 
                args=(texto,), 
                daemon=True
            )
            self._hilo_reproduccion.start()

    def _procesar_hilo_nube(self, texto):
        """Este código se ejecuta en segundo plano."""
        try:
            if self.voz_actual:
                # Aquí es donde ocurre la magia (y la espera de internet)
                self.motor_activo.hablar(texto, self.voz_actual)
        except Exception as e:
            error_msg = str(e)
            print(f"Fallo en nube ({self.tipo_motor_actual}): {error_msg}")
            
            # Usamos wx.CallAfter para mostrar el error en la ventana principal de forma segura
            wx.CallAfter(self._mostrar_error_y_usar_paracaidas, error_msg, texto)
        
        self.estado = "detenido"

    def _mostrar_error_y_usar_paracaidas(self, error_msg, texto):
        """Muestra error visual y activa SAPI5 como respaldo."""
        wx.MessageBox(f"Error conexión {self.tipo_motor_actual}:\n{error_msg}\n\nUsando voz local.", "Aviso de Red")
        try:
            self.cliente_local.hablar(texto)
        except: pass

    def detener(self):
        """Detiene cualquier audio sonando."""
        # Intentamos detener todo para evitar superposiciones
        try: self.cliente_local.detener()
        except: pass
        try: self.cliente_azure.detener()
        except: pass
        try: self.cliente_eleven.detener()
        except: pass
        self.estado = "detenido"

    def pausar(self): 
        if self.tipo_motor_actual == "local":
            self.cliente_local.pausar()
        else:
            self.detener() # En streaming no se pausa, se para.
        self.estado = "pausado"

    def reanudar(self):
        if self.tipo_motor_actual == "local":
            self.cliente_local.reanudar()
            self.estado = "reproduciendo"
        # Nube requiere volver a enviar texto desde la posición (gestionado en pestana_lectura)

    def obtener_estado(self): return self.estado
    def fijar_velocidad(self, v): 
        if hasattr(self.motor_activo, 'fijar_velocidad'): self.motor_activo.fijar_velocidad(v)
    def fijar_volumen(self, v):
        if hasattr(self.motor_activo, 'fijar_volumen'): self.motor_activo.fijar_volumen(v)