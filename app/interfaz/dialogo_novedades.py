# ANCLAJE_INICIO: DIALOGO_NOVEDADES
"""
dialogo_novedades.py
─────────────────────
Ventana accesible que muestra el contenido remoto de novedades.txt
cuando se detecta una versión nueva disponible.

Características de accesibilidad:
  - Título de ventana descriptivo con el número de versión nueva.
  - El foco cae en el área de texto al abrirse → NVDA lo lee de inmediato.
  - Escape cierra el diálogo (EVT_CHAR_HOOK a nivel de Frame).
  - Área de texto en modo solo lectura con scroll accesible (flechas, RePág/AvPág).
  - SetHelpText en el TextCtrl explica los controles disponibles.
  - RESIZE_BORDER: el usuario puede ampliar la ventana si necesita más espacio.
"""

import webbrowser
import wx

_URL_RELEASES = "https://github.com/Dayanna-Parson/epub-tts-accesible/releases"


# ═════════════════════════════════════════════════════════════════════════════
class DialogoNovedades(wx.Dialog):
    """
    Diálogo modal que muestra las novedades de la nueva versión.

    Parámetros
    ----------
    parent          : wx.Window | None
    version_remota  : str   ej. "1.1.0"
    texto_novedades : str   contenido descargado de novedades.txt
    """

    def __init__(self, parent, version_remota: str, texto_novedades: str):
        super().__init__(
            parent,
            title=f"Novedades — Versión {version_remota} disponible",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
            size=(640, 460),
        )
        self._construir(version_remota, texto_novedades)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir(self, version_remota: str, texto: str):
        panel = wx.Panel(self)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Encabezado
        lbl = wx.StaticText(
            panel,
            label=f"Hay una nueva versión disponible: {version_remota}",
        )
        lbl.SetHelpText(
            "Se ha detectado una versión más reciente en el repositorio de GitHub."
        )
        sz.Add(lbl, 0, wx.ALL, 12)

        # Área de texto con el contenido de novedades.txt
        contenido = texto.strip() if texto.strip() else (
            "No se pudo cargar el texto de novedades desde el repositorio.\n"
            "Visita GitHub para ver los cambios de esta versión."
        )
        self.txt_novedades = wx.TextCtrl(
            panel,
            value=contenido,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_AUTO_URL,
        )
        self.txt_novedades.SetHelpText(
            "Novedades de la nueva versión. Solo lectura. "
            "Usa las flechas, RePág y AvPág para desplazarte. "
            "Pulsa Escape o el botón Cerrar para salir."
        )
        sz.Add(self.txt_novedades, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # Separador y botón
        sz.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        btn_descargar = wx.Button(panel, label="Descargar nueva versión en GitHub Releases")
        btn_descargar.SetHelpText(
            "Abre la página de Releases del repositorio en GitHub, "
            "donde puedes descargar la nueva versión."
        )
        btn_descargar.Bind(
            wx.EVT_BUTTON,
            lambda e: webbrowser.open(_URL_RELEASES),
        )
        sz.Add(btn_descargar, 0, wx.ALIGN_CENTER | wx.TOP, 6)

        btn_cerrar = wx.Button(panel, wx.ID_OK, label="Cerrar (Escape)")
        btn_cerrar.SetDefault()
        btn_cerrar.SetHelpText(
            "Cierra este diálogo. También puedes pulsar la tecla Escape."
        )
        sz.Add(btn_cerrar, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sz)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        # El foco cae en el texto al abrirse para que NVDA comience a leer
        wx.CallAfter(self.txt_novedades.SetFocus)

    # ── Teclado ───────────────────────────────────────────────────────────────

    def _al_tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        evento.Skip()
# ANCLAJE_FIN: DIALOGO_NOVEDADES
