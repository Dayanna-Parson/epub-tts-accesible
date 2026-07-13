import logging

import wx

from app.interfaz.pestana_ajustes import PanelAzure, PanelDeepgram, PanelPolly, PanelElevenLabs

logger = logging.getLogger(__name__)


# ANCLAJE_INICIO: DIALOGO_ELEGIR_VOZ
class DialogoElegirVoz(wx.Dialog):
    """
    Selección explícita de proveedor y voz para el Creador de Audiolibros,
    sin depender de la voz favorita automática ni de que se agote la cuota.
    Se abre desde el botón «Elegir voz...» de la pestaña.

    Reutiliza PanelProveedorIA (vía sus subclases de pestana_ajustes.py) para
    el catálogo de voces/favoritas/preescucha, igual que
    DialogoProveedorAlternativo, sin duplicar esa lógica.

    Resultado expuesto tras ShowModal():
        self.accion            "elegida" / "local" / None (cancelado)
        self.proveedor_elegido clave del proveedor si accion == "elegida"
        self.voz_elegida       dict de la voz seleccionada en el catálogo embebido
    """

    _NOMBRES_PROVEEDOR = {
        "azure":      "Azure Neural",
        "polly":      "Amazon Polly",
        "elevenlabs": "ElevenLabs",
        "deepgram":   "Deepgram Aura-2",
    }

    _PANELES_PROVEEDOR = {
        "azure":      PanelAzure,
        "polly":      PanelPolly,
        "elevenlabs": PanelElevenLabs,
        "deepgram":   PanelDeepgram,
    }

    def __init__(self, padre):
        super().__init__(
            padre, title="Elegir voz para la exportación",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.accion = None
        self.proveedor_elegido = None
        self.voz_elegida = None

        self._control_previo = wx.Window.FindFocus()
        self._panel_voces = None

        self._construir_ui()

        self.Fit()
        self.SetMinSize((520, 460))
        self.CenterOnParent()
        self._actualizar_panel_voces()

    def _construir_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl_combo = wx.StaticText(self, label="Proveedor:")
        sizer.Add(lbl_combo, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.combo_proveedores = wx.Choice(self, choices=list(self._NOMBRES_PROVEEDOR.values()))
        self.combo_proveedores.SetHelpText(
            "Proveedor de voz para la exportación. Al cambiarlo se actualiza "
            "el catálogo de voces de abajo."
        )
        self.combo_proveedores.SetSelection(0)
        self.combo_proveedores.Bind(wx.EVT_CHOICE, self._al_cambiar_proveedor)
        sizer.Add(self.combo_proveedores, 0, wx.EXPAND | wx.ALL, 10)

        self.panel_contenedor = wx.Panel(self)
        self.sizer_contenedor = wx.BoxSizer(wx.VERTICAL)
        self.panel_contenedor.SetSizer(self.sizer_contenedor)
        sizer.Add(self.panel_contenedor, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        sz_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_usar = wx.Button(self, label="Usar esta voz")
        self.btn_usar.SetHelpText("Usa la voz seleccionada en el catálogo de arriba para la exportación.")
        self.btn_usar.Bind(wx.EVT_BUTTON, self._al_usar_voz)
        sz_botones.Add(self.btn_usar, 0, wx.RIGHT, 8)

        self.btn_local = wx.Button(self, label="Usar voz local")
        self.btn_local.SetHelpText("Usa la voz local (SAPI5), sin coste ni límite de cuota.")
        self.btn_local.Bind(wx.EVT_BUTTON, self._al_usar_local)
        sz_botones.Add(self.btn_local, 0, wx.RIGHT, 8)

        self.btn_cancelar = wx.Button(self, wx.ID_CANCEL, "Cancelar")
        sz_botones.Add(self.btn_cancelar, 0)

        sizer.Add(sz_botones, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, lambda e: self._cerrar(wx.ID_CANCEL))

    def _al_cambiar_proveedor(self, evento):
        self._actualizar_panel_voces()

    def _actualizar_panel_voces(self):
        idx = self.combo_proveedores.GetSelection()
        claves = list(self._NOMBRES_PROVEEDOR.keys())
        if idx == wx.NOT_FOUND or idx >= len(claves):
            return
        clave = claves[idx]

        if self._panel_voces:
            self.sizer_contenedor.Detach(self._panel_voces)
            self._panel_voces.Destroy()
            self._panel_voces = None

        clase_panel = self._PANELES_PROVEEDOR[clave]
        self._panel_voces = clase_panel(self.panel_contenedor, {})
        self.sizer_contenedor.Add(self._panel_voces, 1, wx.EXPAND)
        self.panel_contenedor.Layout()
        self.GetSizer().Layout()
        self.Fit()

    def _al_usar_voz(self, evento):
        idx = self.combo_proveedores.GetSelection()
        claves = list(self._NOMBRES_PROVEEDOR.keys())
        if idx == wx.NOT_FOUND or idx >= len(claves) or not self._panel_voces:
            wx.MessageBox("Selecciona un proveedor.", "Info")
            return

        idx_voz = self._panel_voces.lista_voces.GetFirstSelected()
        if idx_voz == -1:
            wx.MessageBox("Selecciona una voz del catálogo antes de continuar.", "Info")
            return

        voz = self._panel_voces.mapa_indices.get(idx_voz)
        if not voz:
            wx.MessageBox("Selecciona una voz del catálogo antes de continuar.", "Info")
            return

        self.accion = "elegida"
        self.proveedor_elegido = claves[idx]
        self.voz_elegida = voz
        self._cerrar(wx.ID_OK)

    def _al_usar_local(self, evento):
        self.accion = "local"
        self._cerrar(wx.ID_OK)

    def _cerrar(self, resultado):
        control_previo = self._control_previo
        self.EndModal(resultado)
        if control_previo:
            wx.CallAfter(lambda: control_previo.SetFocus() if control_previo else None)
# ANCLAJE_FIN: DIALOGO_ELEGIR_VOZ
