"""
dialogo_asistente_biblioteca.py
────────────────────────────────
Diálogo de chat con el Asistente de Biblioteca (Gemini).

Se abre con Ctrl+Shift+B desde cualquier pestaña de la aplicación (atajo
global, ver ATAJO_ASISTENTE_BIBLIOTECA en gestor_atajos.py y
al_abrir_asistente_biblioteca_global en ventana_principal.py), y también
desde el menú contextual de cada pestaña. Con un libro seleccionado en la
lista de Biblioteca, precarga su contexto (título, autor,
categoría/etiquetas, estado de lectura); sin selección, se abre en modo
general.

Accesibilidad (Sección 6 de planificacion_v3.md):
  · El historial previo se lee del JSON en el hilo principal antes de
    mostrar el diálogo (archivo pequeño, sin diferir a hilo secundario).
  · El contexto se anuncia con el patrón _anunciador, entregando el foco
    al campo de entrada al terminar — el usuario debe poder escribir de
    inmediato.
  · Las llamadas a Gemini se hacen siempre en hilo secundario, con
    indicador "Pensando..." anunciado una vez al enviar, y la respuesta
    entregada vía wx.CallAfter.
  · Los mensajes nuevos (propios o del asistente) se anuncian con un
    toque de foco brevísimo al control oculto (necesario para que NVDA
    detecte el cambio) que vuelve enseguida al campo de entrada — el
    texto ya escrito en el campo no se pierde, porque SetFocus() no
    modifica el contenido del control.
"""

import logging
import os
import threading

import wx

from app.motor import gestor_chat_biblioteca as chat
from app.motor import gestor_prompts_asistente as prompts
from app.motor.limpiador_markdown_chat import limpiar_markdown
from app.motor.reproductor_sonidos import reproducir, SUCCESS, ERROR, CLEAR
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
            padre, title=titulo, size=(560, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.contexto_libro = contexto_libro
        self.id_libro = contexto_libro["id_libro"] if contexto_libro else None
        self._respuesta_pendiente = False
        self._temporizador_anuncio = None
        self._ultimo_mensaje_usuario = ""
        self._ultimo_mensaje_asistente = ""

        sizer = wx.BoxSizer(wx.VERTICAL)

        # ANCLAJE_INICIO: ASISTENTE_SELECTOR_PROMPT
        sizer_prompt = wx.BoxSizer(wx.HORIZONTAL)
        sizer_prompt.Add(wx.StaticText(self, label="Estilo del asistente:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.combo_prompt = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_prompt.SetHelpText(
            "Plantilla de instrucciones que sigue el asistente en esta conversación."
        )
        self.combo_prompt.Bind(wx.EVT_COMBOBOX, self.al_cambiar_prompt)
        sizer_prompt.Add(self.combo_prompt, 1, wx.RIGHT, 5)
        self.btn_editar_prompts = wx.Button(self, label="Editar prompts...")
        self.btn_editar_prompts.SetHelpText(
            "Crea, edita o borra las plantillas de prompt de sistema del asistente."
        )
        self.btn_editar_prompts.Bind(wx.EVT_BUTTON, self.al_editar_prompts)
        sizer_prompt.Add(self.btn_editar_prompts, 0)
        sizer.Add(sizer_prompt, 0, wx.EXPAND | wx.ALL, 8)
        # ANCLAJE_FIN: ASISTENTE_SELECTOR_PROMPT

        self.historial_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.historial_ctrl.SetName("Historial de mensajes")
        self.historial_ctrl.SetHelpText(
            "Historial de la conversación con el Asistente de Biblioteca. "
            "Solo lectura; usa Ctrl+Fin para ir al último mensaje. "
            "Puedes seleccionar cualquier texto y copiarlo con Ctrl+C."
        )
        sizer.Add(self.historial_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        self.lbl_estado = wx.StaticText(self, label="")
        sizer.Add(self.lbl_estado, 0, wx.LEFT | wx.RIGHT, 8)

        sizer_entrada = wx.BoxSizer(wx.HORIZONTAL)
        self.txt_entrada = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_entrada.SetName("Mensaje")
        self.txt_entrada.SetHelpText(
            "Escribe tu pregunta para el Asistente de Biblioteca y pulsa Intro para enviarla."
        )
        self.txt_entrada.Bind(wx.EVT_TEXT_ENTER, self.al_enviar)
        sizer_entrada.Add(self.txt_entrada, 1, wx.EXPAND | wx.RIGHT, 5)
        self.btn_enviar = wx.Button(self, label="Enviar")
        self.btn_enviar.Bind(wx.EVT_BUTTON, self.al_enviar)
        sizer_entrada.Add(self.btn_enviar, 0)
        sizer.Add(sizer_entrada, 0, wx.EXPAND | wx.ALL, 8)

        # ANCLAJE_INICIO: ASISTENTE_BOTONES_ACCION
        sizer_acciones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_copiar_mensaje = wx.Button(self, label="Copiar mi último mensaje")
        self.btn_copiar_mensaje.SetHelpText("Copia al portapapeles el último mensaje que escribiste.")
        self.btn_copiar_mensaje.Bind(wx.EVT_BUTTON, self.al_copiar_mi_mensaje)
        self.btn_copiar_respuesta = wx.Button(self, label="Copiar última respuesta")
        self.btn_copiar_respuesta.SetHelpText("Copia al portapapeles la última respuesta del asistente.")
        self.btn_copiar_respuesta.Bind(wx.EVT_BUTTON, self.al_copiar_ultima_respuesta)
        self.btn_guardar = wx.Button(self, label="Guardar conversación...")
        self.btn_guardar.SetHelpText("Guarda toda la conversación en un archivo de texto.")
        self.btn_guardar.Bind(wx.EVT_BUTTON, self.al_guardar_conversacion)
        self.btn_borrar = wx.Button(self, label="Borrar historial")
        self.btn_borrar.SetHelpText("Borra el historial de esta conversación, sin posibilidad de deshacer.")
        self.btn_borrar.Bind(wx.EVT_BUTTON, self.al_borrar_historial)
        self.btn_cerrar = wx.Button(self, label="Cerrar")
        self.btn_cerrar.SetHelpText("Cierra el Asistente de Biblioteca. Equivale a pulsar Escape.")
        self.btn_cerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        for boton in (
            self.btn_copiar_mensaje, self.btn_copiar_respuesta,
            self.btn_guardar, self.btn_borrar, self.btn_cerrar,
        ):
            sizer_acciones.Add(boton, 0, wx.RIGHT, 5)
        sizer.Add(sizer_acciones, 0, wx.ALL, 8)
        # ANCLAJE_FIN: ASISTENTE_BOTONES_ACCION

        self.SetSizer(sizer)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador),
        # con la variante de esta sección: siempre devuelve el foco al campo
        # de entrada (nunca al control que lo tuviera antes de abrir el
        # diálogo, ni se queda sin devolverlo tras un mensaje entrante).
        self._anunciador = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1)
        )
        self._anunciador.SetName("Anuncios del asistente")
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())

        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

        self._recargar_combo_prompt()
        self._cargar_historial_previo()
        wx.CallAfter(self._anunciar_contexto_inicial)

    # ── Plantillas de prompt de sistema ──────────────────────────────────────

    def _recargar_combo_prompt(self):
        nombres = [p["nombre"] for p in prompts.listar_prompts()]
        self.combo_prompt.Set(nombres)
        activo = prompts.obtener_prompt_activo()["nombre"]
        if activo in nombres:
            self.combo_prompt.SetStringSelection(activo)
        elif nombres:
            self.combo_prompt.SetSelection(0)

    def al_cambiar_prompt(self, evento):
        prompts.fijar_prompt_activo(self.combo_prompt.GetStringSelection())

    def al_editar_prompts(self, evento):
        from app.interfaz.dialogo_editar_prompt import DialogoEditarPrompt

        dlg = DialogoEditarPrompt(self, self.combo_prompt.GetStringSelection())
        dlg.ShowModal()
        cambios = dlg.cambios_realizados
        dlg.Destroy()
        if cambios:
            self._recargar_combo_prompt()
            self.txt_entrada.SetFocus()

    # ── Carga de historial (hilo principal, archivo pequeño) ────────────────

    def _cargar_historial_previo(self):
        for turno in chat.cargar_historial(self.id_libro):
            self._agregar_a_historial_visual(turno["rol"], turno["texto"])

    def _agregar_a_historial_visual(self, rol, texto):
        etiqueta = "Tú" if rol == "usuario" else "Asistente"
        self.historial_ctrl.AppendText(f"{etiqueta}: {texto}\n\n")
        if rol == "usuario":
            self._ultimo_mensaje_usuario = texto
        else:
            self._ultimo_mensaje_asistente = texto

    # ── Anuncios sin robar el campo de entrada de forma permanente ──────────

    def _anunciar(self, texto):
        # Patrón _anunciador establecido en el resto de la app: toque de
        # foco brevísimo al control oculto (necesario para que NVDA
        # detecte el cambio) y vuelta al campo de entrada — el texto ya
        # escrito no se pierde porque SetFocus() no lo toca. Se probó una
        # notificación UIA "en vivo" que anunciaba sin tocar el foco en
        # ningún momento, pero en pruebas reales con NVDA no llegaba a
        # leerse (quedó descartada; ver historial de commits si se quiere
        # retomar con más margen para depurarla en Windows real).
        if self._temporizador_anuncio is not None and self._temporizador_anuncio.IsRunning():
            self._temporizador_anuncio.Stop()

        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()

        def _restaurar_foco():
            if wx.Window.FindFocus() is self._anunciador:
                self.txt_entrada.SetFocus()

        self._temporizador_anuncio = wx.CallLater(350, _restaurar_foco)

    def _anunciar_contexto_inicial(self):
        if self.contexto_libro:
            texto = f"Hablando sobre: {self.contexto_libro['titulo']}."
        else:
            texto = "Asistente de Biblioteca en modo general. Sin libro seleccionado."
        self._anunciar(texto)
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
        self._anunciar("Pensando...")

        historial_previo = chat.cargar_historial(self.id_libro)[:-1]
        instruccion_sistema = prompts.obtener_prompt_activo()["texto"]

        threading.Thread(
            target=self._pedir_respuesta_en_hilo,
            args=(historial_previo, mensaje, instruccion_sistema),
            daemon=True,
        ).start()

    def _pedir_respuesta_en_hilo(self, historial_previo, mensaje, instruccion_sistema):
        try:
            respuesta = enviar_mensaje(
                historial_previo, mensaje, contexto_libro=self.contexto_libro,
                instruccion_sistema=instruccion_sistema,
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
        self._anunciar(f"Asistente: {respuesta}")

    def _al_fallar_respuesta(self, mensaje_error):
        self._respuesta_pendiente = False
        self.btn_enviar.Enable()
        self.lbl_estado.SetLabel("")
        reproducir(ERROR)
        self._anunciar(f"Error al consultar al asistente: {mensaje_error}")
# ANCLAJE_FIN: ASISTENTE_ENVIO_HILO_SECUNDARIO

    # ANCLAJE_INICIO: ASISTENTE_ACCIONES_HISTORIAL
    def _copiar_al_portapapeles(self, texto, etiqueta):
        if not texto:
            reproducir(ERROR)
            self._anunciar(f"Todavía no hay {etiqueta} que copiar.")
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(texto))
            wx.TheClipboard.Close()
            reproducir(SUCCESS)
            self._anunciar(f"{etiqueta.capitalize()} copiado al portapapeles.")
        else:
            reproducir(ERROR)
            self._anunciar("No se pudo abrir el portapapeles.")

    def al_copiar_mi_mensaje(self, evento):
        self._copiar_al_portapapeles(self._ultimo_mensaje_usuario, "tu último mensaje")

    def al_copiar_ultima_respuesta(self, evento):
        self._copiar_al_portapapeles(self._ultimo_mensaje_asistente, "la última respuesta")

    def al_guardar_conversacion(self, evento):
        contenido = self.historial_ctrl.GetValue()
        if not contenido.strip():
            reproducir(ERROR)
            self._anunciar("No hay ninguna conversación que guardar todavía.")
            return
        nombre_sugerido = "Conversación Asistente de Biblioteca.txt"
        if self.contexto_libro:
            nombre_sugerido = f"Conversación sobre {self.contexto_libro['titulo']}.txt"
        with wx.FileDialog(
            self, "Guardar conversación como",
            defaultFile=nombre_sugerido,
            wildcard="Archivos de texto (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            ruta = dlg.GetPath()
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(contenido)
            reproducir(SUCCESS)
            self._anunciar(f"Conversación guardada en {os.path.basename(ruta)}.")
        except Exception:
            logger.exception("Error al guardar la conversación del Asistente de Biblioteca")
            reproducir(ERROR)
            self._anunciar("No se pudo guardar la conversación.")

    def al_borrar_historial(self, evento):
        if self.historial_ctrl.IsEmpty():
            return
        confirmado = wx.MessageBox(
            "¿Borrar todo el historial de esta conversación? No se puede deshacer.",
            "Borrar historial", wx.YES_NO | wx.ICON_WARNING,
        ) == wx.YES
        if not confirmado:
            return
        chat.borrar_historial(self.id_libro)
        self.historial_ctrl.Clear()
        self._ultimo_mensaje_usuario = ""
        self._ultimo_mensaje_asistente = ""
        reproducir(CLEAR)
        self._anunciar("Historial borrado.")
    # ANCLAJE_FIN: ASISTENTE_ACCIONES_HISTORIAL

    def _al_tecla_global(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        evento.Skip()
