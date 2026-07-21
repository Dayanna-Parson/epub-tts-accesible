# ANCLAJE_INICIO: CLIENTE_SAPI32_BRIDGE
"""
Puente hacia el proceso auxiliar de 32 bits (auxiliar_sapi32.exe).
Implementa la misma interfaz que ClienteSapi5 para ser intercambiable.

Requisito de distribución:
    /bin/auxiliar_sapi32.exe  — compilado con Python 32 bits + PyInstaller.
    Los usuarios finales no necesitan instalar nada.
"""
import json
import logging
import os
import subprocess
import threading

import wx

from app.config_rutas import RAIZ

logger = logging.getLogger(__name__)

_RUTA_AUXILIAR = os.path.join(RAIZ, "bin", "auxiliar_sapi32.exe")
_CREACION_SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW de la API Win32


class ClienteSapi32Bridge:
    """
    Lanza auxiliar_sapi32.exe como proceso hijo y se comunica con él mediante
    líneas JSON por stdin/stdout.  La interfaz pública es idéntica a ClienteSapi5.
    """

    def __init__(self):
        self.conectado = False
        self._proceso = None
        self._lock_envio = threading.Lock()
        self._callback_progreso   = None
        self._callback_completado = None
        # Eventos de sincronización para llamadas síncronas
        self._evt_voces       = threading.Event()
        self._voces_resultado = []
        self._evt_voz_cambiada = threading.Event()
        self._evt_exportado = threading.Event()
        self._exportado_resultado = {}
        self._inicializar()

    # ── Inicialización ────────────────────────────────────────────────────────

    def _inicializar(self):
        if not os.path.isfile(_RUTA_AUXILIAR):
            logger.warning(
                "[SAPI32] auxiliar_sapi32.exe no encontrado en %s", _RUTA_AUXILIAR
            )
            return
        try:
            self._proceso = subprocess.Popen(
                [_RUTA_AUXILIAR],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=_CREACION_SIN_VENTANA,
            )
            # Esperar el evento "listo" (lectura síncrona antes de arrancar el hilo)
            primer_evento = self._leer_linea_json_directo()
            if primer_evento and primer_evento.get("evento") == "listo":
                self.conectado = True
                threading.Thread(
                    target=self._hilo_eventos, daemon=True
                ).start()
                logger.debug("[SAPI32] Proceso auxiliar iniciado correctamente.")
            else:
                logger.warning(
                    "[SAPI32] El auxiliar no envió 'listo': %s", primer_evento
                )
                self._proceso.kill()
                self._proceso = None
        except Exception as e:
            logger.warning("[SAPI32] No se pudo iniciar el auxiliar: %s", e)

    # ── Comunicación interna ──────────────────────────────────────────────────

    def _leer_linea_json_directo(self):
        """Lee una línea JSON del proceso sin pasar por el hilo de eventos."""
        try:
            linea = self._proceso.stdout.readline()
            if linea:
                return json.loads(linea.decode("utf-8", errors="replace").strip())
        except Exception as e:
            logger.debug("[SAPI32] Error leyendo JSON inicial: %s", e)
        return None

    def _hilo_eventos(self):
        """Lee continuamente stdout del auxiliar y despacha callbacks."""
        while self._proceso and self._proceso.poll() is None:
            try:
                linea = self._proceso.stdout.readline()
                if not linea:
                    continue
                datos = json.loads(linea.decode("utf-8", errors="replace").strip())
            except Exception:
                continue

            evento = datos.get("evento")

            if evento == "progreso":
                cb = self._callback_progreso
                if cb:
                    wx.CallAfter(cb, datos.get("pos", 0))

            elif evento == "completado":
                cb = self._callback_completado
                if cb:
                    wx.CallAfter(cb)

            elif evento == "voces":
                self._voces_resultado = datos.get("lista", [])
                self._evt_voces.set()

            elif evento == "voz_cambiada":
                self._evt_voz_cambiada.set()

            elif evento == "exportado":
                self._exportado_resultado = datos
                self._evt_exportado.set()

            elif evento == "error":
                logger.warning("[SAPI32] Error del auxiliar: %s", datos.get("msg"))

        logger.debug("[SAPI32] Proceso auxiliar terminado.")
        self.conectado = False

    def _enviar(self, datos):
        """Envía un comando JSON al proceso auxiliar."""
        if not self._proceso or self._proceso.poll() is not None:
            return
        try:
            with self._lock_envio:
                linea = json.dumps(datos, ensure_ascii=False) + "\n"
                self._proceso.stdin.write(linea.encode("utf-8"))
                self._proceso.stdin.flush()
        except Exception as e:
            logger.warning("[SAPI32] Error enviando comando: %s", e)

    # ── Interfaz pública (igual que ClienteSapi5) ─────────────────────────────

    def obtener_voces(self):
        if not self.conectado:
            return []
        self._evt_voces.clear()
        self._enviar({"cmd": "listar_voces"})
        self._evt_voces.wait(timeout=10.0)
        return list(self._voces_resultado)

    def hablar(self, texto):
        if self.conectado:
            self._enviar({"cmd": "hablar", "texto": texto, "pos_offset": 0})

    def hablar_con_callback(self, texto, pos_offset, callback_progreso, callback_completado):
        if not self.conectado:
            return
        self._callback_progreso   = callback_progreso
        self._callback_completado = callback_completado
        self._enviar({"cmd": "hablar", "texto": texto, "pos_offset": pos_offset})

    def detener(self):
        if self.conectado:
            self._callback_progreso   = None
            self._callback_completado = None
            self._enviar({"cmd": "detener"})

    def pausar(self):
        if self.conectado:
            self._enviar({"cmd": "pausar"})

    def reanudar(self):
        if self.conectado:
            self._enviar({"cmd": "reanudar"})

    def fijar_velocidad(self, v):
        if self.conectado:
            self._enviar({"cmd": "fijar_velocidad", "valor": v})

    def fijar_volumen(self, v):
        if self.conectado:
            self._enviar({"cmd": "fijar_volumen", "valor": v})

    def exportar_archivo(self, texto, ruta_wav, voz_nombre="", rate=0, volume=100, timeout=None):
        """
        Sintetiza `texto` directamente a `ruta_wav` (WAV) de forma síncrona,
        para el Creador de Audiolibros. Devuelve (exito, mensaje_error).
        Nunca debe llamarse en paralelo sobre la misma instancia: el
        auxiliar procesa los comandos uno a uno por stdin.
        """
        if not self.conectado:
            return False, "El proceso auxiliar de 32 bits no está conectado."
        self._evt_exportado.clear()
        self._exportado_resultado = {}
        self._enviar({
            "cmd": "exportar_archivo",
            "texto": texto,
            "ruta_wav": ruta_wav,
            "voz_nombre": voz_nombre,
            "rate": rate,
            "volume": volume,
        })
        # Margen generoso: textos largos pueden tardar bastante en
        # sintetizarse por completo antes de que el auxiliar responda.
        espera = timeout if timeout is not None else max(30.0, len(texto) * 0.05)
        if not self._evt_exportado.wait(timeout=espera):
            return False, "El proceso auxiliar de 32 bits no respondió a tiempo."
        resultado = self._exportado_resultado
        return bool(resultado.get("exito")), resultado.get("msg", "")

    def cambiar_voz_por_nombre(self, nombre):
        if not self.conectado:
            return
        self._evt_voz_cambiada.clear()
        self._enviar({"cmd": "cambiar_voz", "nombre": nombre})
        self._evt_voz_cambiada.wait(timeout=5.0)

    def cerrar(self):
        if self._proceso:
            try:
                self._enviar({"cmd": "salir"})
                self._proceso.wait(timeout=3.0)
            except Exception:
                self._proceso.kill()
            self._proceso = None
        self.conectado = False

    def __del__(self):
        try:
            self.cerrar()
        except Exception:
            pass
# ANCLAJE_FIN: CLIENTE_SAPI32_BRIDGE
