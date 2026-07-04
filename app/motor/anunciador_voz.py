"""
anunciador_voz.py
-------------------
Verbalización de estado con voz del sistema (pyttsx3), independiente de
NVDA y del foco de la interfaz.

El patrón `_anunciador` (TextCtrl oculto + robo de foco) es la forma
correcta de verbalizar UNA cosa puntual para NVDA, pero no es fiable
para secuencias de anuncios rápidos o encadenados con otros cambios de
foco (por ejemplo, progreso de un escaneo, o un anuncio seguido de un
cambio de pestaña): las llamadas se pisan entre sí y NVDA puede no
llegar a anunciar nada. Para esos casos, este módulo ofrece una cola de
voz con una única instancia de pyttsx3 reutilizable en un hilo de
fondo, ya usado con éxito en la ventana de gestión de Proyectos.
"""

import logging
import queue
import threading

logger = logging.getLogger(__name__)


class AnunciadorVoz:
    """
    Cola de verbalización con pyttsx3. Cada mensaje nuevo descarta los
    pendientes que no se hayan hablado todavía, para que la voz siempre
    diga lo más reciente en vez de acumular un backlog.
    """

    def __init__(self):
        self._cola: queue.Queue = queue.Queue()
        self._hilo = threading.Thread(target=self._worker, daemon=True)
        self._hilo.start()

    def _worker(self):
        try:
            import pyttsx3
            motor = pyttsx3.init()
        except Exception:
            logger.warning("[AnunciadorVoz] No se pudo inicializar pyttsx3", exc_info=True)
            return
        while True:
            texto = self._cola.get()
            if texto is None:
                break
            try:
                motor.say(texto)
                motor.runAndWait()
            except Exception:
                logger.debug("[AnunciadorVoz] Fallo al verbalizar", exc_info=True)

    def hablar(self, texto: str):
        while not self._cola.empty():
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break
        self._cola.put(texto)

    def detener(self):
        self._cola.put(None)
