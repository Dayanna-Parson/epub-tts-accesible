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
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

_CODIGO_HABLAR_SUBPROCESO = (
    "import pyttsx3, sys\n"
    "motor = pyttsx3.init()\n"
    "motor.say(sys.argv[1])\n"
    "motor.runAndWait()\n"
)


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
        while True:
            texto = self._cola.get()
            if texto is None:
                break
            try:
                self._hablar_en_subproceso(texto)
            except Exception:
                # A WARNING, no a DEBUG: el archivo de log solo registra desde
                # WARNING hacia arriba (ver iniciar_epub_tts.py), así que un
                # fallo aquí a nivel DEBUG queda completamente invisible —
                # exactamente el silencio sin rastro que se venía reportando.
                logger.warning("[AnunciadorVoz] Fallo al verbalizar", exc_info=True)

    @staticmethod
    def _hablar_en_subproceso(texto: str):
        """
        pyttsx3 con el driver SAPI5 tiene un problema conocido: incluso
        creando una instancia de motor nueva por cada anuncio dentro del
        mismo proceso, deja de sonar a partir de la segunda o tercera
        llamada, sin lanzar ninguna excepción — el estado COM/de audio de
        SAPI5 queda inconsistente y solo un proceso nuevo lo resetea del
        todo. Es el mismo motivo por el que SAPI de 32 bits ya se puentea
        a un proceso aparte en cliente_sapi32_bridge.py. Lanzar un
        proceso de Python nuevo por cada anuncio es más lento, pero es la
        forma fiable de que suene siempre y no solo las primeras veces.
        """
        logger.debug("[AnunciadorVoz] Verbalizando: %s", texto)
        subprocess.run(
            [sys.executable, "-c", _CODIGO_HABLAR_SUBPROCESO, texto],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
            check=False,
        )

    def hablar(self, texto: str):
        while not self._cola.empty():
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break
        self._cola.put(texto)

    def detener(self):
        self._cola.put(None)
