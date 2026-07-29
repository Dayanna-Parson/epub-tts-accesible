# ANCLAJE_INICIO: DIALOGO_VOCES_NUEVAS
"""
dialogo_voces_nuevas.py
────────────────────────
Diálogo accesible que informa al usuario cuando se detectan voces nuevas.

Características de accesibilidad:
  - NVDA lo anuncia automáticamente al aparecer (ShowModal en hilo principal).
  - El foco cae en el botón "Entendido" al abrirse (btn_ok.SetFocus vía CallAfter).
  - Cada línea de proveedor tiene SetHelpText para contexto extra con Tab+F1.
  - Título de ventana descriptivo ("Voces nuevas disponibles").
  - STAY_ON_TOP garantiza que el diálogo quede encima de la ventana principal.

Solo se muestra cuando hay novedades reales; nunca aparece en una sesión donde
no se detectaron cambios.
"""

import wx

from app.motor.gestor_idioma import traducir as _

_NOMBRES_PROVEEDOR = {
    "azure":      "Microsoft Azure",
    "polly":      "Amazon Polly",
    "elevenlabs": "ElevenLabs",
    "deepgram":   "Deepgram Aura-2",
}


# ═════════════════════════════════════════════════════════════════════════════
class DialogoVocesNuevas(wx.Dialog):
    """
    Diálogo modal que lista los proveedores con voces nuevas y cuántas hay.

    Parámetros
    ----------
    parent : wx.Window | None
    nuevas : dict   {proveedor_id: [nombre_voz, ...]}
    """

    def __init__(self, parent, nuevas: dict):
        super().__init__(
            parent,
            title=_("Voces nuevas disponibles"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )
        self._construir(nuevas)
        self.Fit()
        self.CentreOnScreen()

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir(self, nuevas: dict):
        panel = wx.Panel(self)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Encabezado
        intro = wx.StaticText(
            panel,
            label=_("Se han detectado voces nuevas en los siguientes proveedores:"),
        )
        intro.SetHelpText(
            _("La aplicación encontró voces que no estaban en la lista local. "
              "Ve a la pestaña Ajustes para explorarlas y escucharlas.")
        )
        sz.Add(intro, 0, wx.ALL, 12)

        # Una línea por proveedor con novedades
        for proveedor, nombres in nuevas.items():
            nombre_prov = _NOMBRES_PROVEEDOR.get(proveedor, proveedor.title())
            n = len(nombres)
            etiq = (
                _("  • {proveedor}: 1 voz nueva").format(proveedor=nombre_prov)
                if n == 1
                else _("  • {proveedor}: {n} voces nuevas").format(proveedor=nombre_prov, n=n)
            )
            lbl = wx.StaticText(panel, label=etiq)
            lbl.SetHelpText(
                _("El proveedor {proveedor} tiene {n} {palabra} que no estaban registradas localmente.").format(
                    proveedor=nombre_prov, n=n, palabra=(_("voz") if n == 1 else _("voces"))
                )
            )
            sz.Add(lbl, 0, wx.LEFT | wx.BOTTOM, 8)

        # Nota de acción
        nota = wx.StaticText(
            panel,
            label=_("Abre la pestaña Ajustes → sección Voces para explorarlas."),
        )
        sz.Add(nota, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Separador y botón
        sz.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.btn_ok = wx.Button(panel, wx.ID_OK, label=_("Entendido"))
        self.btn_ok.SetDefault()
        self.btn_ok.SetHelpText(
            _("Cierra este aviso. Puedes explorar las novedades en la pestaña Ajustes.")
        )
        sz.Add(self.btn_ok, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sz)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        # El foco cae en el botón al abrirse → NVDA lo lee de inmediato
        wx.CallAfter(self.btn_ok.SetFocus)
# ANCLAJE_FIN: DIALOGO_VOCES_NUEVAS
