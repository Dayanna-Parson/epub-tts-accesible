# ANCLAJE_INICIO: DIALOGO_EDITAR_PROMPT
"""
dialogo_editar_prompt.py
─────────────────────────
Diálogo accesible para crear, editar y borrar las plantillas de prompt de
sistema del Asistente de Biblioteca. Se abre desde el botón "Editar
prompts..." de dialogo_asistente_biblioteca.py.
"""
import logging

import wx

from app.motor import anunciador_lector as voz
from app.motor import gestor_prompts_asistente as prompts
from app.motor.reproductor_sonidos import reproducir, SUCCESS, ERROR

logger = logging.getLogger(__name__)

_NUEVA = "(Nueva plantilla...)"


class DialogoEditarPrompt(wx.Dialog):
    def __init__(self, padre, nombre_seleccionado=None):
        super().__init__(
            padre, title="Editar prompts del Asistente de Biblioteca",
            size=(520, 480), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.cambios_realizados = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Plantilla:"), 0, wx.LEFT | wx.TOP, 8)
        self.combo_plantillas = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_plantillas.Bind(wx.EVT_COMBOBOX, self.al_seleccionar_plantilla)
        sizer.Add(self.combo_plantillas, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Nombre:"), 0, wx.LEFT, 8)
        self.txt_nombre = wx.TextCtrl(self)
        sizer.Add(self.txt_nombre, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Texto del prompt:"), 0, wx.LEFT, 8)
        self.txt_prompt = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.txt_prompt.SetName("Texto del prompt")
        sizer.Add(self.txt_prompt, 1, wx.EXPAND | wx.ALL, 8)

        sizer_botones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_guardar = wx.Button(self, label="Guardar plantilla")
        self.btn_guardar.Bind(wx.EVT_BUTTON, self.al_guardar)
        self.btn_borrar = wx.Button(self, label="Borrar plantilla")
        self.btn_borrar.Bind(wx.EVT_BUTTON, self.al_borrar)
        self.btn_cerrar = wx.Button(self, label="Cerrar")
        self.btn_cerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        for boton in (self.btn_guardar, self.btn_borrar, self.btn_cerrar):
            sizer_botones.Add(boton, 0, wx.RIGHT, 5)
        sizer.Add(sizer_botones, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

        self._recargar_combo(seleccionar=nombre_seleccionado)
        # Foco de partida determinista: sea cual sea el efecto colateral de
        # rellenar los campos al recargar el combo, el diálogo siempre debe
        # empezar con el foco en la propia lista de plantillas.
        self.combo_plantillas.SetFocus()

    def _recargar_combo(self, seleccionar=None):
        self._plantillas = prompts.listar_prompts()
        nombres = [p["nombre"] for p in self._plantillas] + [_NUEVA]
        self.combo_plantillas.Set(nombres)
        objetivo = seleccionar if seleccionar in nombres else nombres[0]
        self.combo_plantillas.SetStringSelection(objetivo)
        self.al_seleccionar_plantilla(None)

    def al_seleccionar_plantilla(self, evento):
        # No mueve el foco en ningún caso: navegar con flechas por un
        # combo de solo selección dispara este mismo evento en cada
        # cambio, así que robar el foco aquí (incluso solo al llegar a
        # "Nueva plantilla...") obligaba a salir con Escape para seguir
        # recorriendo la lista. El usuario decide con Tab cuándo pasar a
        # rellenar el nombre.
        seleccion = self.combo_plantillas.GetStringSelection()
        if seleccion == _NUEVA:
            self.txt_nombre.Clear()
            self.txt_prompt.Clear()
            return
        plantilla = next((p for p in self._plantillas if p["nombre"] == seleccion), None)
        if plantilla:
            self.txt_nombre.SetValue(plantilla["nombre"])
            self.txt_prompt.SetValue(plantilla["texto"])

    def al_guardar(self, evento):
        nombre = self.txt_nombre.GetValue().strip()
        texto = self.txt_prompt.GetValue().strip()
        if not nombre or not texto:
            reproducir(ERROR)
            wx.MessageBox("El nombre y el texto del prompt no pueden estar vacíos.", "Error")
            return
        prompts.guardar_prompt(nombre, texto)
        self.cambios_realizados = True
        reproducir(SUCCESS)
        voz.hablar(f"Plantilla «{nombre}» guardada.")
        self._recargar_combo(seleccionar=nombre)

    def al_borrar(self, evento):
        nombre = self.txt_nombre.GetValue().strip()
        if not nombre:
            return
        if wx.MessageBox(
            f"¿Borrar la plantilla «{nombre}»?", "Borrar plantilla",
            wx.YES_NO | wx.ICON_WARNING,
        ) != wx.YES:
            return
        if prompts.borrar_prompt(nombre):
            self.cambios_realizados = True
            reproducir(SUCCESS)
            voz.hablar(f"Plantilla «{nombre}» borrada.")
            self._recargar_combo()
        else:
            reproducir(ERROR)
            wx.MessageBox("No se puede borrar: tiene que quedar al menos una plantilla.", "Error")

    def _al_tecla_global(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        evento.Skip()
# ANCLAJE_FIN: DIALOGO_EDITAR_PROMPT
