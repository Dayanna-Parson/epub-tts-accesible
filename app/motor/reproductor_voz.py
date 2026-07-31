# ANCLAJE_INICIO: IMPORTACIONES
import os
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)
import wx
from app.servicios.cliente_sapi5 import ClienteSapi5
from app.servicios.cliente_sapi32_bridge import ClienteSapi32Bridge
from app.servicios.cliente_azure import ClienteAzure
from app.servicios.cliente_eleven import ClienteEleven
from app.servicios.cliente_polly import ClientePolly
from app.servicios.cliente_deepgram import ClienteDeepgram
from app.motor.control_cuota import ControlCuota
from app.motor.reproductor_sonidos import reproducir, ERROR as SND_ERROR
from app.config_rutas import ruta_config
from app.motor.gestor_idioma import traducir as _
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
        self.cliente_local    = ClienteSapi5()
        self.cliente_local_32 = ClienteSapi32Bridge()
        self.cliente_azure   = ClienteAzure()
        self.cliente_eleven  = ClienteEleven()
        self.cliente_polly   = ClientePolly()
        self.cliente_deepgram = ClienteDeepgram()
        
        # Estado inicial del sistema
        self.motor_activo = self.cliente_local
        self.tipo_motor_actual = "local"
        self.voz_actual = None
        # Última velocidad/volumen elegidos desde la interfaz. Cada cliente
        # (ClienteAzure, ClientePolly...) guarda su propio _velocidad/_volumen
        # interno con su propio valor por defecto (50/100): al cambiar de
        # motor_activo en fijar_voz(), ese cliente recién activado nunca había
        # recibido el valor que el usuario ya tenía puesto en el deslizador,
        # así que la lectura sonaba siempre "como al 50%" tras seleccionar o
        # cambiar de voz. Se guardan aquí para poder reaplicarlos.
        self._velocidad_actual = 50
        self._volumen_actual = 100
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
        # Proveedores que ya mostraron el aviso de error de red/API esta
        # sesión — evita una ventana modal por cada fragmento fallido (con
        # una API caída a mitad de lectura, eso podía disparar un aviso tras
        # otro y dar la sensación de que la app se había colgado). Se limpia
        # al cambiar de voz manualmente, igual que las suspensiones de cuota.
        self._proveedores_con_aviso_red = set()

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
        self._proveedores_con_aviso_red.clear()
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
        elif "deepgram" in proveedor:
            self.motor_activo = self.cliente_deepgram
            self.tipo_motor_actual = "deepgram"
        else:

            # ANCLAJE_INICIO: CONFIGURACION_VOZ_ACTIVA
            nombre_voz = datos_voz.get("nombre", "")
            if "local_32" in proveedor:
                # Voz SAPI5 de 32 bits (p. ej. Eloquence de CodeFactory):
                # usar el proceso auxiliar de 32 bits si está disponible.
                if self.cliente_local_32.conectado:
                    self.motor_activo = self.cliente_local_32
                    self.tipo_motor_actual = "local_32"
                    self.cliente_local_32.cambiar_voz_por_nombre(nombre_voz)
                else:
                    logger.warning(
                        "[ReproductorVoz] Voz 32 bits solicitada pero auxiliar_sapi32.exe "
                        "no está disponible. Cae a SAPI5 de 64 bits."
                    )
                    self.motor_activo = self.cliente_local
                    self.tipo_motor_actual = "local"
                    self.cliente_local.cambiar_voz_por_nombre(nombre_voz)
            else:
                self.motor_activo = self.cliente_local
                self.tipo_motor_actual = "local"
                if hasattr(self.cliente_local, "cambiar_voz_por_nombre"):
                    self.cliente_local.cambiar_voz_por_nombre(nombre_voz)
            # ANCLAJE_FIN: CONFIGURACION_VOZ_ACTIVA

        self._reaplicar_velocidad_volumen()

    def _reaplicar_velocidad_volumen(self):
        """
        Reaplica al motor_activo actual la velocidad/volumen que el usuario
        ya tenía puestos en los deslizadores. Cada cliente (ClienteAzure,
        ClientePolly...) guarda su propio estado interno con su propio valor
        por defecto (50/100): sin esto, la lectura sonaba siempre "a mitad"
        nada más cambiar de voz o de proveedor (manualmente o por cuota
        agotada), sin importar dónde estuviera el deslizador. Se llama desde
        cada punto de este archivo que reasigna self.motor_activo.
        """
        logger.debug(
            "[ReproductorVoz] _reaplicar_velocidad_volumen: motor=%s (%s) velocidad=%s volumen=%s",
            self.tipo_motor_actual, type(self.motor_activo).__name__,
            self._velocidad_actual, self._volumen_actual,
        )
        if hasattr(self.motor_activo, 'fijar_velocidad'):
            self.motor_activo.fijar_velocidad(self._velocidad_actual)
        if hasattr(self.motor_activo, 'fijar_volumen'):
            self.motor_activo.fijar_volumen(self._volumen_actual)

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
            ("azure",    self.cliente_azure),
            ("polly",    self.cliente_polly),
            ("deepgram", self.cliente_deepgram),
            ("eleven",   self.cliente_eleven),
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
                    self._reaplicar_velocidad_volumen()
                return tipo

        # Ningún proveedor tiene cuota: caer a voz local
        def _aviso_cuota_total():
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("Se ha alcanzado el límite de cuota de todos los proveedores de IA.\n\n"
                  "Se usará la voz local para continuar sin generar costes adicionales."),
                _("Límite de cuota alcanzado")
            )
        wx.CallAfter(_aviso_cuota_total)
        self.motor_activo = self.cliente_local
        self.tipo_motor_actual = "local"
        self._reaplicar_velocidad_volumen()
        return "local"

    def cargar_texto(self, texto, callback_completado=None,
                     pos_offset=0, callback_progreso=None, modo_cola=False):
        """
        Inicia la lectura del texto.
        Aplica el método adecuado según si se usa una voz local o una voz neuronal.
        Incrementa el contador de generación para invalidar cualquier hilo anterior.

        Para voces neuronales, verifica la cuota antes de iniciar y salta al siguiente
        proveedor disponible si el actual ha agotado su límite mensual.

        callback_completado : función sin argumentos llamada en el hilo principal cuando
            termina el fragmento. Usada por PestanaLectura para encadenar la cola de audio.
        pos_offset          : posición global del inicio del texto en el TextCtrl.
            Solo se usa con voces SAPI5 para la sincronización de cursor.
        callback_progreso   : función(pos) llamada al iniciar cada párrafo en SAPI5.
            Permite mover el cursor exactamente al párrafo que se está leyendo.
        modo_cola           : True cuando el fragmento llega desde la cola de lectura
            continua. El audio anterior ya terminó de sonar (sd.wait() completó antes
            del callback), por lo que no hay nada que detener ni sesiones que cerrar.
            Saltar detener() y el sleep elimina la pausa entre fragmentos y preserva
            la sesión HTTP activa, permitiendo que el audio predesargado se use.
        """
        if not texto: return

        if not modo_cola:
            # Detener cualquier lectura en curso antes de iniciar una nueva
            self.detener()
            time.sleep(0.05)

        # Nueva síntesis: restablecer el flag de detención intencional
        self._detenido_intencionalmente = False

        # Para voces neuronales, verificar cuota y seleccionar motor disponible
        if self.tipo_motor_actual not in ("local", "local_32"):
            self._elegir_motor_con_cuota(texto)

        # Incrementar generación: los hilos de síntesis anteriores quedan invalidados
        self._generacion += 1
        generacion_actual = self._generacion

        # Registrar el callback para este fragmento
        self._callback_completado = callback_completado

        self.estado = "reproduciendo"

        if self.tipo_motor_actual in ("local", "local_32"):
            motor_local = self.motor_activo
            try:
                usa_callback = (callback_progreso or callback_completado) and hasattr(motor_local, "hablar_con_callback")
                if usa_callback:
                    motor_local.hablar_con_callback(
                        texto,
                        pos_offset,
                        callback_progreso or (lambda pos: None),
                        callback_completado or (lambda: None),
                    )
                else:
                    motor_local.hablar(texto)
            except Exception as e:
                logger.warning("[ReproductorVoz] Error en voz local: %s", e)
                self.estado = "detenido"
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
                        except Exception:
                            logger.exception("[ReproductorVoz] Error usando voz local tras cuota agotada de '%s'", proveedor)
                else:
                    # Error de red/API real (voz inexistente, timeout, región
                    # sin esa voz nueva...): aviso accesible una sola vez por
                    # proveedor y sesión — repetirlo en cada fragmento fallido
                    # (p. ej. toda una lectura con la API caída) se sentía
                    # como que la app se quedaba colgada esperando que se
                    # cerraran ventanas modales una tras otra.
                    proveedor = self.tipo_motor_actual
                    primera_vez = proveedor not in self._proveedores_con_aviso_red
                    self._proveedores_con_aviso_red.add(proveedor)
                    if primera_vez:
                        wx.CallAfter(self._activar_voz_local_automatica, error_msg, texto)
                    elif not self._detenido_intencionalmente:
                        try: self.cliente_local.hablar(texto)
                        except Exception:
                            logger.exception("[ReproductorVoz] Error usando voz local tras fallo de red de '%s'", proveedor)

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
        reproducir(SND_ERROR)
        wx.MessageBox(
            _("El proveedor {proveedor} ha alcanzado el límite de su plan/cuota.\n\n"
              "• Este proveedor queda desactivado automáticamente para esta sesión.\n"
              "• La lectura continuará con tu voz local sin interrupciones.\n"
              "• Para reactivarlo, cambia de voz manualmente en el selector.").format(
                proveedor=proveedor.upper()
            ),
            _("Cuota agotada — aviso único"),
            wx.OK | wx.ICON_INFORMATION
        )
    # ANCLAJE_FIN: GESTION_ERRORES_CUOTA

    # ANCLAJE_INICIO: ACTIVACION_VOZ_LOCAL_AUTOMATICA
    def _activar_voz_local_automatica(self, error_msg, texto):
        """
        Activa automáticamente una voz local si el servicio de la voz neuronal falla o pierde conexión.
        """
        reproducir(SND_ERROR)
        wx.MessageBox(
            _("No se ha podido conectar con el servicio de voz con IA ({proveedor}).\n\n"
              "Detalle: {detalle}\n\n"
              "Para que la lectura no se detenga, continuaremos usando tu voz local.").format(
                proveedor=self.tipo_motor_actual.upper(), detalle=error_msg
            ),
            _("Aviso sobre la voz de lectura")
        )
        try:
            self.cliente_local.hablar(texto)
        except Exception:
            logger.exception("[ReproductorVoz] Error activando la voz local automática tras fallo de '%s'", self.tipo_motor_actual)
    # ANCLAJE_FIN: ACTIVACION_VOZ_LOCAL_AUTOMATICA

    # ANCLAJE_INICIO: PRECARGA_SIGUIENTE_FRAGMENTO
    def precargar_fragmento(self, texto, datos_voz):
        """
        Inicia en segundo plano la descarga del audio para el siguiente fragmento.
        Cuando hablar() se llame después con el mismo texto, encontrará el audio
        ya listo y lo reproducirá sin la latencia de la API (típicamente 1-2s).
        Solo aplica a voces neuronales; SAPI5 no necesita precarga.
        La precarga captura la generación actual y la verifica antes de almacenar
        el resultado: si el usuario pausó/detuvo mientras se descargaba, el audio
        se descarta en lugar de reproducirse de forma residual.
        """
        if self.tipo_motor_actual == "local":
            return
        if not hasattr(self.motor_activo, 'preparar'):
            return

        motor = self.motor_activo
        generacion_precarga = self._generacion  # capturar generación al lanzar

        def _preparar():
            try:
                motor.preparar(texto, datos_voz)
                # Si la generación cambió durante la descarga (pausa/detención),
                # invalidar la caché para que no se sirva el audio viejo.
                if self._generacion != generacion_precarga:
                    if hasattr(motor, 'invalidar_cache'):
                        try:
                            motor.invalidar_cache(texto)
                        except Exception:
                            logger.debug("[ReproductorVoz] No se pudo invalidar la caché de precarga; sin impacto, hay fallback a síntesis directa.")
            except Exception as e:
                logger.warning("[ReproductorVoz] Error en precarga: %s", e)

        threading.Thread(target=_preparar, daemon=True).start()
    # ANCLAJE_FIN: PRECARGA_SIGUIENTE_FRAGMENTO

    # ANCLAJE_INICIO: COMANDOS_REPRODUCTOR
    def detener(self):
        """Finaliza cualquier proceso de audio activo en todos los motores."""
        # Incrementar generación PRIMERO: invalida al instante cualquier hilo
        # de síntesis o precarga en vuelo. Si el hilo llega a la comprobación
        # _generacion == generacion tras el cierre HTTP, encontrará valores
        # distintos y descartará el audio sin reproducirlo ni encadenar la cola.
        self._generacion += 1
        self._detenido_intencionalmente = True
        self._callback_completado = None
        try: self.cliente_local.detener()
        except Exception: logger.debug("[ReproductorVoz] No se pudo detener el motor local (probablemente no estaba activo).")
        try: self.cliente_azure.detener()
        except Exception: logger.debug("[ReproductorVoz] No se pudo detener el motor de Azure (probablemente no estaba activo).")
        try: self.cliente_eleven.detener()
        except Exception: logger.debug("[ReproductorVoz] No se pudo detener el motor de ElevenLabs (probablemente no estaba activo).")
        try: self.cliente_polly.detener()
        except Exception: logger.debug("[ReproductorVoz] No se pudo detener el motor de Amazon Polly (probablemente no estaba activo).")
        try: self.cliente_deepgram.detener()
        except Exception: logger.debug("[ReproductorVoz] No se pudo detener el motor de Deepgram (probablemente no estaba activo).")
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
        self._velocidad_actual = v
        logger.debug("[ReproductorVoz] fijar_velocidad(%s) -> motor_activo=%s (%s)",
                        v, self.tipo_motor_actual, type(self.motor_activo).__name__)
        if hasattr(self.motor_activo, 'fijar_velocidad'): self.motor_activo.fijar_velocidad(v)
    def fijar_volumen(self, v):
        self._volumen_actual = v
        if hasattr(self.motor_activo, 'fijar_volumen'): self.motor_activo.fijar_volumen(v)