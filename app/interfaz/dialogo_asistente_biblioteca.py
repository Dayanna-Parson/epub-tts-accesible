"""
dialogo_asistente_biblioteca.py
────────────────────────────────
Diálogo de chat con el Asistente de Biblioteca (Gemini).

Se abre con Ctrl+Shift+B desde la pestaña Biblioteca (ver
ATAJO_ASISTENTE_BIBLIOTECA en gestor_atajos.py). Con un libro seleccionado
en la lista, precarga su contexto (título, autor, categoría/etiquetas,
estado de lectura); sin selección, se abre en modo general.

Accesibilidad (Sección 6 de planificacion_v3.md):
  · El historial previo se lee del JSON en el hilo principal antes de
    mostrar el diálogo (archivo pequeño, sin diferir a hilo secundario).
  · El contexto se anuncia con el patrón _anunciador, pero entregando el
    foco directamente al campo de entrada en vez de devolverlo al control
    previo — el usuario debe poder escribir de inmediato.
  · Las llamadas a Gemini se hacen siempre en hilo secundario, con
    indicador "Pensando..." anunciado una vez al enviar, y la respuesta
    se entrega vía wx.CallAfter sin robarle el foco al campo de entrada.
"""

import logging

import wx

from app.motor import gestor_chat_biblioteca as chat
from app.motor.limpiador_markdown_chat import limpiar_markdown
from app.motor.reproductor_sonidos import reproducir, SUCCESS, ERROR
from app.servicios.cliente_gemini import enviar_mensaje

logger = logging.getLogger(__name__)


# ANCLAJE_INICIO: DIALOGO_ASISTENTE_BIBLIOTECA_INIT
class DialogoAsistenteBiblioteca(wx.Dialog):
    def __init__(self, padre, contexto_libro=None):
        """
        contexto_libro: None para modo general, o un dict con
        {"id_libro", "titulo", "autor", "categoria", "estado"}.
        """
        titulo = "Asistente de Biblioteca"
        if contexto_libro:
            titulo += f" — {contexto_libro['titulo']}"
        super().__init__(
            padre, title=titulo, size=(560, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.contexto_libro = contexto_libro
        self.id_libro = contexto_libro["id_libro"] if contexto_libro else None
        self._respuesta_pendiente = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.historial_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.historial_ctrl.SetHelpText(
            "Historial de la conversación con el Asistente de Biblioteca. "
            "Solo lectura; usa Ctrl+Fin para ir al último mensaje."
        )
        sizer.Add(self.historial_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        self.lbl_estado = wx.StaticText(self, label="")
        sizer.Add(self.lbl_estado, 0, wx.LEFT | wx.RIGHT, 8)

        sizer_entrada = wx.BoxSizer(wx.HORIZONTAL)
        self.txt_entrada = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_entrada.SetHelpText(
            "Escribe tu pregunta para el Asistente de Biblioteca y pulsa Intro para enviarla."
        )
        self.txt_entrada.Bind(wx.EVT_TEXT_ENTER, self.al_enviar)
        sizer_entrada.Add(self.txt_entrada, 1, wx.EXPAND | wx.RIGHT, 5)
        self.btn_enviar = wx.Button(self, label="Enviar")
        self.btn_enviar.Bind(wx.EVT_BUTTON, self.al_enviar)
        sizer_entrada.Add(self.btn_enviar, 0)
        sizer.Add(sizer_entrada, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador),
        # con la variante de esta sección: entrega el foco al campo de
        # entrada en vez de devolverlo al control previo.
        self._anunciador = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1)
        )
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())

        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

        self._cargar_historial_previo()
        wx.CallAfter(self._anunciar_contexto_inicial)

    # ── Carga de historial (hilo principal, archivo pequeño) ────────────────

    def _cargar_historial_previo(self):
        for turno in chat.cargar_historial(self.id_libro):
            self._agregar_a_historial_visual(turno["rol"], turno["texto"])

    def _agregar_a_historial_visual(self, rol, texto):
        etiqueta = "Tú" if rol == "usuario" else "Asistente"
        self.historial_ctrl.AppendText(f"{etiqueta}: {texto}\n\n")

    # ── Anuncio de contexto y foco directo al campo de entrada ──────────────

    def _anunciar_contexto_inicial(self):
        if self.contexto_libro:
            texto = f"Hablando sobre: {self.contexto_libro['titulo']}."
        else:
            texto = "Asistente de Biblioteca en modo general. Sin libro seleccionado."
        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()
        wx.CallLater(300, self.txt_entrada.SetFocus)
# ANCLAJE_FIN: DIALOGO_ASISTENTE_BIBLIOTECA_INIT


# ANCLAJE_INICIO: ASISTENTE_ENVIO_HILO_SECUNDARIO
    def al_enviar(self, evento):
        if self._respuesta_pendiente:
            return
        mensaje = self.txt_entrada.GetValue().strip()
        if not mensaje:
            return

        self.txt_entrada.Clear()
        self._agregar_a_historial_visual("usuario", mensaje)
        chat.agregar_turno(self.id_libro, "usuario", mensaje)

        self._respuesta_pendiente = True
        self.btn_enviar.Disable()
        self.lbl_estado.SetLabel("Pensando...")
        self._anunciador.SetValue("Pensando...")
        self._anunciador.SetFocus()
        wx.CallLater(300, self.txt_entrada.SetFocus)

        historial_previo = chat.cargar_historial(self.id_libro)[:-1]

        import threading
        threading.Thread(
            target=self._pedir_respuesta_en_hilo,
            args=(historial_previo, mensaje),
            daemon=True,
        ).start()

    def _pedir_respuesta_en_hilo(self, historial_previo, mensaje):
        try:
            respuesta = enviar_mensaje(
                historial_previo, mensaje, contexto_libro=self.contexto_libro,
            )
            respuesta = limpiar_markdown(respuesta)
            wx.CallAfter(self._al_recibir_respuesta, respuesta)
        except Exception as e:
            logger.exception("Error al consultar al Asistente de Biblioteca (Gemini)")
            wx.CallAfter(self._al_fallar_respuesta, str(e))

    def _al_recibir_respuesta(self, respuesta):
        self._respuesta_pendiente = False
        self.btn_enviar.Enable()
        self.lbl_estado.SetLabel("")
        chat.agregar_turno(self.id_libro, "asistente", respuesta)
        self._agregar_a_historial_visual("asistente", respuesta)
        reproducir(SUCCESS)
        # No se mueve el foco: el usuario puede seguir escribiendo mientras
        # llega la respuesta. NVDA anuncia el texto añadido al historial
        # sin robarle el punto de edición al campo de entrada.
        self._anunciador.SetValue(f"Asistente: {respuesta}")

    def _al_fallar_respuesta(self, mensaje_error):
        self._respuesta_pendiente = False
        self.btn_enviar.Enable()
        self.lbl_estado.SetLabel("")
        reproducir(ERROR)
        self._anunciador.SetValue(f"Error al consultar al asistente: {mensaje_error}")
# ANCLAJE_FIN: ASISTENTE_ENVIO_HILO_SECUNDARIO

    def _al_tecla_global(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        evento.Skip()
