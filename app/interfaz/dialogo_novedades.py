# ANCLAJE_INICIO: DIALOGO_NOVEDADES
"""
dialogo_novedades.py
─────────────────────
Ventana accesible que muestra el contenido remoto de novedades.txt
cuando se detecta una versión nueva disponible, y permite instalar
la actualización automáticamente sin abrir el navegador.

Características de accesibilidad:
  - Título de ventana descriptivo con el número de versión nueva.
  - El foco cae en el área de texto al abrirse → NVDA lo lee de inmediato.
  - Escape cierra el diálogo (EVT_CHAR_HOOK a nivel de Frame).
  - Área de texto en modo solo lectura con scroll accesible (flechas, RePág/AvPág).
  - SetHelpText en el TextCtrl explica los controles disponibles.
  - RESIZE_BORDER: el usuario puede ampliar la ventana si necesita más espacio.
  - La etiqueta de progreso informa a los lectores de pantalla del estado.
"""

import subprocess
import sys
import wx

from app.motor.comprobador_actualizaciones import ComprobadorActualizaciones


# ═════════════════════════════════════════════════════════════════════════════
class DialogoNovedades(wx.Dialog):
    """
    Diálogo modal que muestra las novedades de la nueva versión y ofrece
    instalación automática.

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
            size=(640, 500),
        )
        self._version_remota = version_remota
        self._construir(version_remota, texto_novedades)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _construir(self, version_remota: str, texto: str):
        self._panel = wx.Panel(self)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Encabezado
        lbl = wx.StaticText(
            self._panel,
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
            self._panel,
            value=contenido,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_AUTO_URL,
        )
        self.txt_novedades.SetHelpText(
            "Novedades de la nueva versión. Solo lectura. "
            "Usa las flechas, RePág y AvPág para desplazarte. "
            "Pulsa Escape o el botón Cerrar para salir."
        )
        sz.Add(self.txt_novedades, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # Separador
        sz.Add(
            wx.StaticLine(self._panel),
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            10,
        )

        # Etiqueta de progreso (inicialmente vacía)
        self.lbl_progreso = wx.StaticText(self._panel, label="")
        self.lbl_progreso.SetName("Estado de la actualización")
        self.lbl_progreso.SetHelpText(
            "Muestra el estado de la descarga e instalación de la actualización."
        )
        sz.Add(
            self.lbl_progreso,
            0,
            wx.ALIGN_CENTER | wx.TOP | wx.LEFT | wx.RIGHT,
            6,
        )

        # Botón actualizar automáticamente
        self.btn_actualizar = wx.Button(
            self._panel,
            label="Actualizar automáticamente",
        )
        self.btn_actualizar.SetName("Actualizar automáticamente")
        self.btn_actualizar.SetHelpText(
            "Descarga e instala la nueva versión directamente desde GitHub. "
            "Tus configuraciones y grabaciones no se borrarán. "
            "La aplicación se reiniciará al terminar."
        )
        self.btn_actualizar.Bind(wx.EVT_BUTTON, self._al_actualizar)
        sz.Add(self.btn_actualizar, 0, wx.ALIGN_CENTER | wx.TOP, 8)

        # Botón reiniciar (oculto hasta que la descarga termine con éxito)
        self.btn_reiniciar = wx.Button(
            self._panel,
            label="Reiniciar ahora para aplicar la actualización",
        )
        self.btn_reiniciar.SetName("Reiniciar ahora")
        self.btn_reiniciar.SetHelpText(
            "Cierra la aplicación y la vuelve a abrir con la nueva versión."
        )
        self.btn_reiniciar.Bind(wx.EVT_BUTTON, self._al_reiniciar)
        self.btn_reiniciar.Hide()
        sz.Add(self.btn_reiniciar, 0, wx.ALIGN_CENTER | wx.TOP, 6)

        btn_cerrar = wx.Button(self._panel, wx.ID_OK, label="Cerrar (Escape)")
        btn_cerrar.SetDefault()
        btn_cerrar.SetHelpText(
            "Cierra este diálogo. También puedes pulsar la tecla Escape."
        )
        sz.Add(btn_cerrar, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self._panel.SetSizer(sz)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        # El foco cae en el texto al abrirse para que NVDA comience a leer
        wx.CallAfter(self.txt_novedades.SetFocus)

    # ── Teclado ───────────────────────────────────────────────────────────────

    def _al_tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        evento.Skip()

    # ── Actualización automática ──────────────────────────────────────────────

    def _al_actualizar(self, evento):
        """Lanza la descarga en un hilo daemon y deshabilita el botón."""
        self.btn_actualizar.Disable()
        self.btn_actualizar.SetLabel("Actualizando…")
        self._set_progreso("Iniciando descarga…", 0)

        comp = ComprobadorActualizaciones()
        comp.descargar_en_hilo(
            callback_resultado=lambda r: wx.CallAfter(self._al_fin_descarga, r),
            callback_progreso=lambda msg, pct: wx.CallAfter(
                self._set_progreso, msg, pct
            ),
        )

    def _set_progreso(self, mensaje: str, porcentaje: int):
        """Actualiza la etiqueta de progreso (siempre desde el hilo UI)."""
        if porcentaje > 0:
            texto = f"{mensaje} ({porcentaje} %)"
        else:
            texto = mensaje
        self.lbl_progreso.SetLabel(texto)
        self._panel.Layout()
        self.Layout()

    def _al_fin_descarga(self, resultado: dict):
        """Callback invocado en el hilo UI tras terminar la descarga."""
        if resultado["ok"]:
            self._set_progreso("¡Actualización instalada correctamente!", 100)
            self.btn_reiniciar.Show()
            self._panel.Layout()
            self.Layout()
            wx.CallAfter(self.btn_reiniciar.SetFocus)
        else:
            error = resultado.get("error") or "Error desconocido."
            self._set_progreso(f"Error: {error}", 0)
            self.btn_actualizar.SetLabel("Reintentar actualización")
            self.btn_actualizar.Enable()

    def _al_reiniciar(self, evento):
        """Lanza una nueva instancia de la app y cierra la actual."""
        try:
            if getattr(sys, "frozen", False):
                # Ejecutable compilado con PyInstaller
                subprocess.Popen([sys.executable] + sys.argv[1:])
            else:
                # Modo desarrollo con Python
                subprocess.Popen([sys.executable] + sys.argv)
        except Exception:
            pass
        self.EndModal(wx.ID_OK)
        wx.CallAfter(wx.GetApp().ExitMainLoop)
# ANCLAJE_FIN: DIALOGO_NOVEDADES
