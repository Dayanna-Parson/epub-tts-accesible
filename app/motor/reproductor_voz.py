# ANCLAJE_INICIO: IMPORTACIONES
import os
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)
import wx
from app.servicios.cliente_sapi5 import ClienteSapi5
from app.servicios.cliente_azure import ClienteAzure
from app.servicios.cliente_eleven import ClienteEleven
from app.servicios.cliente_polly import ClientePolly
from app.motor.control_cuota import ControlCuota
from app.config_rutas import ruta_config
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
        # Contador de generación: cada nueva petición de síntesis incrementa este valor.
        # Los hilos anteriores lo comparan antes de reproducir y se descartan si ya no
        # coincide, evitando acumulación de hilos y colisión de audio.
        self._generacion = 0
        # Callback opcional que se ejecuta en el hilo principal cuando un fragmento
        # termina de reproducirse. Lo usa PestanaLectura para encadenar la cola de audio.
        self._callback_completado = None
        # Flag que indica que la detención fue intencional (pausa o stop del usuario).
        # Cuando True, el hilo de síntesis no mostrará el diálogo de error por ConnectionError
        # ni sobreescribirá el estado con 'detenido' al recibir la excepción de cancelación.
        self._detenido_intencionalmente = False
        # Control de cuota: evita gastos inesperados y permite saltar al siguiente proveedor
        self._control_cuota = ControlCuota()
        # Proveedores suspendidos esta sesión por error de cuota (402 / plan agotado).
        # Se limpian cuando el usuario cambia de voz manualmente.
        self._proveedores_suspendidos = set()

    def _cargar_config(self):
        """Carga la configuración de voces desde el archivo JSON global."""
        try:
            ruta = ruta_config("ajustes.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning("[ReproductorVoz] No se pudo leer ajustes.json: %s", e)
        return {}
    def fijar_voz(self, datos_voz):
        self.detener()
        # El usuario elige voz manualmente: resetear suspensiones de cuota
        self._proveedores_suspendidos.clear()
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
    def _elegir_motor_con_cuota(self, texto):
        """
        Verifica la cuota del proveedor de IA actualmente seleccionado.
        Si está agotada, intenta el siguiente proveedor disponible antes de
        recurrir a la voz local (SAPI5).

        Orden de prioridad: proveedor actual → otros proveedores de IA → local.
        Registra el gasto del proveedor elegido antes de retornar.
        Retorna el tipo de motor elegido ("azure", "polly", "eleven" o "local").
        """
        todos = [
            ("azure", self.cliente_azure),
            ("polly", self.cliente_polly),
            ("eleven", self.cliente_eleven),
        ]
        # El proveedor actual va primero
        prioridad = [(t, m) for t, m in todos if t == self.tipo_motor_actual] + \
                    [(t, m) for t, m in todos if t != self.tipo_motor_actual]

        for tipo, motor in prioridad:
            if tipo in self._proveedores_suspendidos:
                continue  # Proveedor desactivado esta sesión por cuota agotada
            if self._control_cuota.tiene_cuota(texto, tipo):
                self._control_cuota.registrar_gasto(texto, tipo)
                # Cambiar motor activo si difiere del actual
                if tipo != self.tipo_motor_actual:
                    logger.info("[ReproductorVoz] '%s' sin cuota → usando '%s'", self.tipo_motor_actual, tipo)
                    self.motor_activo = motor
                    self.tipo_motor_actual = tipo
                return tipo

        # Ningún proveedor tiene cuota: caer a voz local
        wx.MessageBox(
            "Se ha alcanzado el límite de cuota de todos los proveedores de IA.\n\n"
            "Se usará la voz local para continuar sin generar costes adicionales.",
            "Límite de cuota alcanzado"
        )
        self.motor_activo = self.cliente_local
        self.tipo_motor_actual = "local"
        return "local"

    def cargar_texto(self, texto, callback_completado=None):
        """
        Inicia la lectura del texto.
        Aplica el método adecuado según si se usa una voz local o una voz neuronal.
        Incrementa el contador de generación para invalidar cualquier hilo anterior
        que pudiera estar esperando respuesta de la API.

        Para voces neuronales, verifica la cuota antes de iniciar y salta al siguiente
        proveedor disponible si el actual ha agotado su límite mensual.

        callback_completado: función sin argumentos que se llamará en el hilo principal
        cuando termine de reproducirse el fragmento. Usado por PestanaLectura para
        encadenar la cola de audio de lectura continua.
        """
        if not texto: return

        # Detener cualquier lectura en curso antes de iniciar una nueva
        self.detener()
        time.sleep(0.05)

        # Nueva síntesis: restablecer el flag de detención intencional
        self._detenido_intencionalmente = False

        # Para voces neuronales, verificar cuota y seleccionar motor disponible
        if self.tipo_motor_actual != "local":
            self._elegir_motor_con_cuota(texto)

        # Incrementar generación: los hilos de síntesis anteriores quedan invalidados
        self._generacion += 1
        generacion_actual = self._generacion

        # Registrar el callback para este fragmento
        self._callback_completado = callback_completado

        self.estado = "reproduciendo"

        if self.tipo_motor_actual == "local":
            # Ejecución directa para voces locales SAPI5 (SPF_ASYNC, no bloquea)
            try:
                self.cliente_local.hablar(texto)
            except Exception as e:
                logger.warning("[ReproductorVoz] Error en voz local SAPI5: %s", e)
                self.estado = "detenido"
            # Las voces locales gestionan su propia cola internamente; no se usa callback
        else:
            # Voces neuronales: se ejecutan en segundo plano para no bloquear la interfaz
            self._hilo_reproduccion = threading.Thread(
                target=self._procesar_voz_neuronal,
                args=(texto, generacion_actual),
                daemon=True
            )
            self._hilo_reproduccion.start()
    # ANCLAJE_FIN: FLUJO_PRINCIPAL_SINTESIS

    # ANCLAJE_INICIO: PROCESAMIENTO_VOCES_NEURONALES
    def _procesar_voz_neuronal(self, texto, generacion):
        """
        Gestiona la reproducción de las voces neuronales sin interrumpir el uso del programa.
        Recibe la generación con la que fue creado el hilo. Si al recibir la respuesta
        de la API la generación ya no coincide con la actual, el audio se descarta
        sin reproducirlo para evitar colisiones entre peticiones rápidas.
        """
        try:
            if self.voz_actual:
                # Petición bloqueante a la API del proveedor
                self.motor_activo.hablar(texto, self.voz_actual)
        except Exception as e:
            error_msg = str(e)
            logger.warning("[ReproductorVoz] Error en voz neuronal (%s): %s", self.tipo_motor_actual, error_msg)

            if self._generacion == generacion and not self._detenido_intencionalmente:
                if self._es_error_cuota(error_msg):
                    proveedor = self.tipo_motor_actual
                    if proveedor not in self._proveedores_suspendidos:
                        # Primer aviso: mostrar diálogo y suspender proveedor
                        self._proveedores_suspendidos.add(proveedor)
                        wx.CallAfter(self._avisar_cuota_agotada, proveedor)
                    # Leer este fragmento con voz local para no perder la lectura
                    if not self._detenido_intencionalmente:
                        try: self.cliente_local.hablar(texto)
                        except Exception: pass
                else:
                    # Error de red/API real: activar voz local con mensaje de error
                    wx.CallAfter(self._activar_voz_local_automatica, error_msg, texto)

        # Solo actualizar el estado y encadenar el callback si:
        # 1. Esta generación sigue siendo la activa (no se inició otra síntesis)
        # 2. La detención NO fue intencional (si fue pausa/stop, el estado ya fue asignado)
        if self._generacion == generacion and not self._detenido_intencionalmente:
            self.estado = "detenido"
            if self._callback_completado:
                wx.CallAfter(self._callback_completado)
    # ANCLAJE_FIN: PROCESAMIENTO_VOCES_NEURONALES

    # ANCLAJE_INICIO: GESTION_ERRORES_CUOTA
    def _es_error_cuota(self, error_msg):
        """Detecta si el error corresponde a cuota agotada o plan de pago excedido."""
        msg = error_msg.lower()
        return any(k in msg for k in (
            "402", "quota", "payment required", "insufficient_credits",
            "characters_limit", "limit_reached", "plan limit",
            "monthly usage", "billing", "credit", "subscription"
        ))

    def _avisar_cuota_agotada(self, proveedor):
        """
        Aviso único por proveedor. Se llama desde el hilo principal via wx.CallAfter.
        Al ser único por proveedor por sesión, no se repite en cada fragmento.
        """
        wx.MessageBox(
            f"El proveedor {proveedor.upper()} ha alcanzado el límite de su plan/cuota.\n\n"
            "• Este proveedor queda desactivado automáticamente para esta sesión.\n"
            "• La lectura continuará con tu voz local sin interrupciones.\n"
            "• Para reactivarlo, cambia de voz manualmente en el selector.",
            "Cuota agotada — aviso único",
            wx.OK | wx.ICON_INFORMATION
        )
    # ANCLAJE_FIN: GESTION_ERRORES_CUOTA

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

    # ANCLAJE_INICIO: PRECARGA_SIGUIENTE_FRAGMENTO
    def precargar_fragmento(self, texto, datos_voz):
        """
        Inicia en segundo plano la descarga del audio para el siguiente fragmento.
        Cuando hablar() se llame después con el mismo texto, encontrará el audio
        ya listo y lo reproducirá sin la latencia de la API (típicamente 1-2s).
        Solo aplica a voces neuronales; SAPI5 no necesita precarga.
        """
        if self.tipo_motor_actual == "local":
            return
        if not hasattr(self.motor_activo, 'preparar'):
            return

        motor = self.motor_activo  # capturar referencia local para el hilo

        def _preparar():
            try:
                motor.preparar(texto, datos_voz)
            except Exception as e:
                logger.warning("[ReproductorVoz] Error en precarga: %s", e)

        threading.Thread(target=_preparar, daemon=True).start()
    # ANCLAJE_FIN: PRECARGA_SIGUIENTE_FRAGMENTO

    # ANCLAJE_INICIO: COMANDOS_REPRODUCTOR
    def detener(self):
        """Finaliza cualquier proceso de audio activo en todos los motores."""
        # Marcar como detención intencional ANTES de cerrar la sesión HTTP.
        # El hilo de síntesis leerá este flag cuando capture la ConnectionError
        # y no mostrará el diálogo de error ni sobreescribirá el estado.
        self._detenido_intencionalmente = True
        # Limpiar callback para que el hilo no encadene el siguiente fragmento
        self._callback_completado = None
        try: self.cliente_local.detener()
        except: pass
        try: self.cliente_azure.detener()
        except: pass
        try: self.cliente_eleven.detener()
        except: pass
        try: self.cliente_polly.detener()
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