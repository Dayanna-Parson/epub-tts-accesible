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
  · Los anuncios (contexto inicial, "Mensaje enviado.", "Pensando...",
    respuestas, errores, acciones sobre el historial) se hablan con
    app.motor.anunciador_lector (accessible_output3): habla directo al
    lector de pantalla activo sin mover el foco ni simular controles
    ocultos. Se descartó el patrón _anunciador (toque de foco a un
    TextCtrl oculto) para este diálogo porque NVDA anunciaba el rol del
    control en cada mensaje ("edición, solo lectura...") y se sentía como
    si saltara una ventana flotante en mitad de la conversación — ver
    historial de commits si se quiere retomar esa alternativa.
  · Las llamadas a Gemini se hacen siempre en hilo secundario; la
    respuesta se entrega vía wx.CallAfter. El foco nunca se mueve del
    campo de entrada mientras llega la respuesta.
"""

import logging
import os
import threading

import wx

from app.motor import anunciador_lector as voz
from app.motor import gestor_chat_biblioteca as chat
from app.motor import gestor_prompts_asistente as prompts
from app.motor.limpiador_markdown_chat import limpiar_markdown
from app.motor.reproductor_sonidos import (
    reproducir, iniciar_bucle, detener_bucle, SUCCESS, ERROR, CLEAR, THINKING,
)
from app.servicios.cliente_gemini import enviar_mensaje
from app.interfaz.ui_recursos import aplicar_icono_boton
from app.motor.gestor_idioma import traducir as _, idioma_activo

logger = logging.getLogger(__name__)

# Nombre del idioma en el propio idioma, para pedirle a Gemini que responda
# en el idioma activo de la interfaz sin depender de texto ya traducido.
_NOMBRE_IDIOMA_PARA_PROMPT = {
    "es": "español",
    "en": "English",
}


def _instruccion_idioma() -> str:
    nombre = _NOMBRE_IDIOMA_PARA_PROMPT.get(idioma_activo(), "español")
    return f"Responde siempre en {nombre}, sin importar en qué idioma esté escrito el mensaje del usuario."


# ANCLAJE_INICIO: DIALOGO_ASISTENTE_BIBLIOTECA_INIT
class DialogoAsistenteBiblioteca(wx.Dialog):
    def __init__(self, padre, contexto_libro=None):
        """
        contexto_libro: None para modo general, o un dict con
        {"id_libro", "titulo", "autor", "categoria", "estado"}.
        """
        titulo = _("Asistente de Biblioteca")
        if contexto_libro:
            titulo += f" — {contexto_libro['titulo']}"
        super().__init__(
            padre, title=titulo, size=(560, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.contexto_libro = contexto_libro
        self.id_libro = contexto_libro["id_libro"] if contexto_libro else None
        self._respuesta_pendiente = False
        self._ultimo_mensaje_usuario = ""
        self._ultimo_mensaje_asistente = ""

        sizer = wx.BoxSizer(wx.VERTICAL)

        # ANCLAJE_INICIO: ASISTENTE_SELECTOR_PROMPT
        # Solo el combo de selección rápida: crear, editar y borrar plantillas
        # se gestiona ahora desde Ajustes → Asistente de Biblioteca, para no
        # duplicar esa gestión completa aquí en el chat.
        sizer_prompt = wx.BoxSizer(wx.HORIZONTAL)
        sizer_prompt.Add(
            wx.StaticText(self, label=_("Estilo del asistente:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.combo_prompt = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_prompt.SetHelpText(
            _("Plantilla de instrucciones que sigue el asistente en esta conversación. "
              "Para crear, editar o borrar plantillas, ve a Ajustes → Asistente de Biblioteca.")
        )
        self.combo_prompt.Bind(wx.EVT_COMBOBOX, self.al_cambiar_prompt)
        sizer_prompt.Add(self.combo_prompt, 1, wx.RIGHT, 5)
        sizer.Add(sizer_prompt, 0, wx.EXPAND | wx.ALL, 8)
        # ANCLAJE_FIN: ASISTENTE_SELECTOR_PROMPT

        # Etiqueta visible + asociada por orden de tabulación: es lo que
        # realmente usa NVDA como nombre accesible del campo en esta app
        # (SetName() por sí solo no lo garantiza, se comprobó con el
        # historial y el campo de mensaje quedando sin nombre).
        sizer.Add(wx.StaticText(self, label=_("Historial de conversación:")), 0, wx.LEFT | wx.TOP, 8)
        self.historial_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.historial_ctrl.SetName(_("Historial de conversación"))
        self.historial_ctrl.SetHelpText(
            _("Historial de la conversación con el Asistente de Biblioteca. "
              "Solo lectura; usa Ctrl+Fin para ir al último mensaje. "
              "Puedes seleccionar cualquier texto y copiarlo con Ctrl+C.")
        )
        sizer.Add(self.historial_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.lbl_estado = wx.StaticText(self, label="")
        sizer.Add(self.lbl_estado, 0, wx.LEFT | wx.RIGHT, 8)

        sizer_entrada = wx.BoxSizer(wx.HORIZONTAL)
        sizer_entrada.Add(wx.StaticText(self, label=_("Mensaje:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.txt_entrada = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_entrada.SetName(_("Mensaje"))
        self.txt_entrada.SetHelpText(
            _("Escribe tu pregunta para el Asistente de Biblioteca y pulsa Intro para enviarla.")
        )
        self.txt_entrada.Bind(wx.EVT_TEXT_ENTER, self.al_enviar)
        sizer_entrada.Add(self.txt_entrada, 1, wx.EXPAND | wx.RIGHT, 5)
        self.btn_enviar = wx.Button(self, label=_("Enviar"))
        self.btn_enviar.Bind(wx.EVT_BUTTON, self.al_enviar)
        aplicar_icono_boton(self.btn_enviar, "avanzar", _("Enviar"))
        sizer_entrada.Add(self.btn_enviar, 0)
        sizer.Add(sizer_entrada, 0, wx.EXPAND | wx.ALL, 8)

        # ANCLAJE_INICIO: ASISTENTE_BOTONES_ACCION
        sizer_acciones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_copiar_mensaje = wx.Button(self, label=_("Copiar mi último mensaje"))
        self.btn_copiar_mensaje.SetHelpText(_("Copia al portapapeles el último mensaje que escribiste."))
        self.btn_copiar_mensaje.Bind(wx.EVT_BUTTON, self.al_copiar_mi_mensaje)
        aplicar_icono_boton(self.btn_copiar_mensaje, "copiar", _("Copiar mi último mensaje"))
        self.btn_copiar_respuesta = wx.Button(self, label=_("Copiar última respuesta"))
        self.btn_copiar_respuesta.SetHelpText(_("Copia al portapapeles la última respuesta del asistente."))
        self.btn_copiar_respuesta.Bind(wx.EVT_BUTTON, self.al_copiar_ultima_respuesta)
        aplicar_icono_boton(self.btn_copiar_respuesta, "copiar", _("Copiar última respuesta"))
        self.btn_guardar = wx.Button(self, label=_("Guardar conversación..."))
        self.btn_guardar.SetHelpText(_("Guarda toda la conversación en un archivo de texto."))
        self.btn_guardar.Bind(wx.EVT_BUTTON, self.al_guardar_conversacion)
        aplicar_icono_boton(self.btn_guardar, "guardar", _("Guardar conversación"))
        self.btn_borrar = wx.Button(self, label=_("Borrar historial"))
        self.btn_borrar.SetHelpText(_("Borra el historial de esta conversación, sin posibilidad de deshacer."))
        self.btn_borrar.Bind(wx.EVT_BUTTON, self.al_borrar_historial)
        aplicar_icono_boton(self.btn_borrar, "eliminar", _("Borrar historial"))
        self.btn_cerrar = wx.Button(self, label=_("Cerrar"))
        self.btn_cerrar.SetHelpText(_("Cierra el Asistente de Biblioteca. Equivale a pulsar Escape."))
        self.btn_cerrar.Bind(wx.EVT_BUTTON, self._al_cerrar)
        aplicar_icono_boton(self.btn_cerrar, "cerrar", _("Cerrar"))
        for boton in (
            self.btn_copiar_mensaje, self.btn_copiar_respuesta,
            self.btn_guardar, self.btn_borrar, self.btn_cerrar,
        ):
            sizer_acciones.Add(boton, 0, wx.RIGHT, 5)
        sizer.Add(sizer_acciones, 0, wx.ALL, 8)
        # ANCLAJE_FIN: ASISTENTE_BOTONES_ACCION

        self.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

        self._recargar_combo_prompt()
        self._cargar_historial_previo()
        self.txt_entrada.SetFocus()
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
        # Sin confirmación hablada aquí: EVT_COMBOBOX se dispara en cada
        # elemento que se cruza al navegar con flechas, y NVDA ya anuncia
        # de forma nativa el nombre de la plantilla seleccionada en el
        # combo — añadir voz.hablar() aquí duplicaba esa lectura (se oía
        # "Estilo del asistente: X." seguido de "X" en cada flecha).
        # al_enviar() relee obtener_prompt_activo() justo antes de llamar
        # a Gemini, así que lo que se fija aquí es lo que se usará.
        nombre = self.combo_prompt.GetStringSelection()
        prompts.fijar_prompt_activo(nombre)

    # ── Carga de historial (hilo principal, archivo pequeño) ────────────────

    def _cargar_historial_previo(self):
        for turno in chat.cargar_historial(self.id_libro):
            self._agregar_a_historial_visual(turno["rol"], turno["texto"])

    def _agregar_a_historial_visual(self, rol, texto):
        etiqueta = _("Tú") if rol == "usuario" else _("Asistente")
        self.historial_ctrl.AppendText(f"{etiqueta}: {texto}\n\n")
        if rol == "usuario":
            self._ultimo_mensaje_usuario = texto
        else:
            self._ultimo_mensaje_asistente = texto

    def _anunciar_contexto_inicial(self):
        if self.contexto_libro:
            texto = _("Hablando sobre: {titulo}.").format(titulo=self.contexto_libro["titulo"])
        else:
            texto = _("Asistente de Biblioteca en modo general. Sin libro seleccionado.")
        voz.hablar(texto)
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
        self.lbl_estado.SetLabel(_("Pensando..."))
        voz.hablar(_("Mensaje enviado. Pensando..."))
        iniciar_bucle(THINKING)

        historial_previo = chat.cargar_historial(self.id_libro)[:-1]
        instruccion_sistema = prompts.obtener_prompt_activo()["texto"] + "\n\n" + _instruccion_idioma()

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
        detener_bucle()
        self._respuesta_pendiente = False
        self.btn_enviar.Enable()
        self.lbl_estado.SetLabel("")
        chat.agregar_turno(self.id_libro, "asistente", respuesta)
        self._agregar_a_historial_visual("asistente", respuesta)
        reproducir(SUCCESS)
        voz.hablar(_("Asistente: {respuesta}").format(respuesta=respuesta))

    def _al_fallar_respuesta(self, mensaje_error):
        detener_bucle()
        self._respuesta_pendiente = False
        self.btn_enviar.Enable()
        self.lbl_estado.SetLabel("")
        reproducir(ERROR)
        voz.hablar(_("Error al consultar al asistente: {error}").format(error=mensaje_error))
# ANCLAJE_FIN: ASISTENTE_ENVIO_HILO_SECUNDARIO

    # ANCLAJE_INICIO: ASISTENTE_ACCIONES_HISTORIAL
    def _copiar_al_portapapeles(self, texto, etiqueta):
        if not texto:
            reproducir(ERROR)
            voz.hablar(_("Todavía no hay {etiqueta} que copiar.").format(etiqueta=etiqueta))
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(texto))
            wx.TheClipboard.Close()
            reproducir(SUCCESS)
            voz.hablar(_("{etiqueta} copiado al portapapeles.").format(etiqueta=etiqueta.capitalize()))
        else:
            reproducir(ERROR)
            voz.hablar(_("No se pudo abrir el portapapeles."))

    def al_copiar_mi_mensaje(self, evento):
        self._copiar_al_portapapeles(self._ultimo_mensaje_usuario, _("tu último mensaje"))

    def al_copiar_ultima_respuesta(self, evento):
        self._copiar_al_portapapeles(self._ultimo_mensaje_asistente, _("la última respuesta"))

    def al_guardar_conversacion(self, evento):
        contenido = self.historial_ctrl.GetValue()
        if not contenido.strip():
            reproducir(ERROR)
            voz.hablar(_("No hay ninguna conversación que guardar todavía."))
            return
        nombre_sugerido = _("Conversación Asistente de Biblioteca.txt")
        if self.contexto_libro:
            nombre_sugerido = _("Conversación sobre {titulo}.txt").format(titulo=self.contexto_libro["titulo"])
        with wx.FileDialog(
            self, _("Guardar conversación como"),
            defaultDir=chat.ruta_carpeta(),
            defaultFile=nombre_sugerido,
            wildcard=_("Archivos de texto (*.txt)|*.txt"),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            ruta = dlg.GetPath()
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(contenido)
            reproducir(SUCCESS)
            voz.hablar(_("Conversación guardada en {nombre}.").format(nombre=os.path.basename(ruta)))
        except Exception:
            logger.exception("Error al guardar la conversación del Asistente de Biblioteca")
            reproducir(ERROR)
            voz.hablar(_("No se pudo guardar la conversación."))

    def al_borrar_historial(self, evento):
        if self.historial_ctrl.IsEmpty():
            return
        confirmado = wx.MessageBox(
            _("¿Borrar todo el historial de esta conversación? No se puede deshacer."),
            _("Borrar historial"), wx.YES_NO | wx.ICON_WARNING,
        ) == wx.YES
        if not confirmado:
            return
        chat.borrar_historial(self.id_libro)
        self.historial_ctrl.Clear()
        self._ultimo_mensaje_usuario = ""
        self._ultimo_mensaje_asistente = ""
        reproducir(CLEAR)
        voz.hablar(_("Historial borrado."))
    # ANCLAJE_FIN: ASISTENTE_ACCIONES_HISTORIAL

    def _al_cerrar(self, evento):
        # Si el diálogo se cierra con una respuesta todavía pendiente, el
        # bucle de thinking.wav debe detenerse aquí — la respuesta que
        # llegue después vía wx.CallAfter ya no tiene diálogo al que
        # actualizar, así que _al_recibir_respuesta/_al_fallar_respuesta
        # nunca se ejecutarían para pararlo.
        detener_bucle()
        self.EndModal(wx.ID_CLOSE)

    def _al_tecla_global(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self._al_cerrar(evento)
            return
        evento.Skip()
