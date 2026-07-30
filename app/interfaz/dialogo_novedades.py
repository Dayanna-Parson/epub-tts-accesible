# ANCLAJE_INICIO: DIALOGO_NOVEDADES
"""
dialogo_novedades.py
─────────────────────
Ventana accesible que muestra el contenido remoto de novedades.txt
cuando se detecta una versión nueva disponible, y pregunta si el
usuario quiere instalar la actualización (Script Clon).

También se reutiliza en modo_bienvenida=True para el diálogo posterior
al reinicio, ya con la actualización instalada: mismo diseño, pero sin
la pregunta de instalar (un único botón «Aceptar») ni las cadenas de
texto orientadas a "vas a actualizar" en vez de "ya se ha actualizado".

Características de accesibilidad:
  - Título descriptivo con el número de versión nueva.
  - El foco cae en el área de texto al abrirse → NVDA lo lee de inmediato.
  - Escape y el botón No → no actualizar (ID_CANCEL).
  - Botón Sí → procede con la actualización (ID_OK).
  - X de la ventana equivale a No (EVT_CLOSE → ID_CANCEL).
  - Área de texto solo lectura con scroll accesible (flechas, RePág/AvPág).
  - RESIZE_BORDER para ampliar la ventana si hace falta.
"""

import wx

from app.interfaz.ui_recursos import aplicar_icono_boton
from app.motor.gestor_idioma import traducir as _


# ═════════════════════════════════════════════════════════════════════════════
class DialogoNovedades(wx.Dialog):
    """
    Diálogo modal que muestra las novedades de la nueva versión y pregunta
    si el usuario desea actualizar (Script Clon).

    Devuelve wx.ID_OK si el usuario acepta actualizar (o al pulsar Aceptar
    en modo_bienvenida), wx.ID_CANCEL si rechaza o cierra la ventana.

    Parámetros
    ----------
    parent          : wx.Window | None
    version_remota  : str   ej. "2.0.0" (o la versión ya instalada, en modo_bienvenida)
    texto_novedades : str   contenido de novedades.txt (remoto, o local en modo_bienvenida)
    modo_bienvenida : bool  True → diálogo posterior a una actualización ya
                            instalada: un único botón «Aceptar», sin preguntar
                            si se quiere instalar.
    """

    def __init__(self, parent, version_remota: str, texto_novedades: str,
                 modo_bienvenida: bool = False):
        titulo = (
            _("Novedades de la versión {version}").format(version=version_remota)
            if modo_bienvenida else
            _("Nueva versión disponible: {version}").format(version=version_remota)
        )
        super().__init__(
            parent,
            title=titulo,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
            size=(640, 500),
        )
        self._modo_bienvenida = modo_bienvenida
        self._construir(version_remota, texto_novedades)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla)
        self.Bind(wx.EVT_CLOSE, self._al_cerrar_ventana)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir(self, version_remota: str, texto: str):
        self._panel = wx.Panel(self)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Encabezado
        if self._modo_bienvenida:
            texto_encabezado = _(
                "Se ha actualizado a la versión {version}. Esto es lo que ha cambiado:"
            ).format(version=version_remota)
            texto_ayuda_encabezado = _(
                "La actualización ya está instalada. Este es un resumen de las novedades."
            )
        else:
            texto_encabezado = _(
                "Hay una nueva versión disponible: {version}\n"
                "¿Deseas instalarla ahora?"
            ).format(version=version_remota)
            texto_ayuda_encabezado = _(
                "Se ha detectado una versión más reciente en el repositorio de GitHub. "
                "Pulsa Sí para actualizar o No para cerrar sin actualizar."
            )
        lbl = wx.StaticText(self._panel, label=texto_encabezado)
        lbl.SetHelpText(texto_ayuda_encabezado)
        sz.Add(lbl, 0, wx.ALL, 12)

        # Área de texto con el contenido de novedades.txt
        contenido = texto.strip() if texto.strip() else _(
            "No se pudo cargar el texto de novedades desde el repositorio.\n"
            "Visita GitHub para ver los cambios de esta versión."
        )
        self.txt_novedades = wx.TextCtrl(
            self._panel,
            value=contenido,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_AUTO_URL,
        )
        self.txt_novedades.SetHelpText(
            _("Novedades de la versión. Solo lectura. "
              "Usa las flechas, RePág y AvPág para desplazarte.")
        )
        sz.Add(self.txt_novedades, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        sz.Add(wx.StaticLine(self._panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Fila de botones: Sí/No al ofrecer instalar, o un único Aceptar
        # cuando la actualización ya está instalada (modo_bienvenida).
        fila = wx.BoxSizer(wx.HORIZONTAL)

        if self._modo_bienvenida:
            btn_aceptar = wx.Button(self._panel, wx.ID_OK, label=_("&Aceptar"))
            btn_aceptar.SetHelpText(_("Cierra este resumen de novedades."))
            btn_aceptar.SetDefault()
            btn_aceptar.Bind(wx.EVT_BUTTON, self._al_aceptar)
            fila.Add(btn_aceptar, 0)
        else:
            btn_si = wx.Button(self._panel, wx.ID_OK, label=_("&Sí, actualizar ahora"))
            btn_si.SetHelpText(
                _("Descarga e instala la nueva versión. "
                  "Tus configuraciones y grabaciones no se borrarán. "
                  "La aplicación se cerrará y se volverá a abrir automáticamente.")
            )
            btn_si.Bind(wx.EVT_BUTTON, self._al_aceptar)

            btn_no = wx.Button(self._panel, wx.ID_CANCEL, label=_("&No, cerrar"))
            btn_no.SetHelpText(
                _("Cierra este diálogo sin actualizar. "
                  "Podrás actualizar más tarde desde Ajustes.")
            )
            aplicar_icono_boton(btn_no, "cerrar", _("No, cerrar"))
            btn_no.SetDefault()
            btn_no.Bind(wx.EVT_BUTTON, self._al_rechazar)

            fila.Add(btn_si, 0, wx.RIGHT, 12)
            fila.Add(btn_no, 0)
        sz.Add(fila, 0, wx.ALIGN_CENTER | wx.ALL, 12)

        self._panel.SetSizer(sz)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        # El foco cae en el texto al abrirse para que NVDA comience a leer
        wx.CallAfter(self.txt_novedades.SetFocus)

    # ── Teclado y cierre ──────────────────────────────────────────────────────

    def _al_tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        evento.Skip()

    def _al_cerrar_ventana(self, evento):
        """X de la ventana equivale a No."""
        self.EndModal(wx.ID_CANCEL)

    def _al_aceptar(self, evento):
        self.EndModal(wx.ID_OK)

    def _al_rechazar(self, evento):
        self.EndModal(wx.ID_CANCEL)
# ANCLAJE_FIN: DIALOGO_NOVEDADES
