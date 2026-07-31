# ANCLAJE_INICIO: DIALOGO_TROCEADOR
"""
dialogo_troceador.py
─────────────────────
Diálogo accesible para dividir un EPUB en archivos TXT, uno por capítulo.

Se abre desde el botón "Dividir EPUB…" de PestanaGrabacion.

Flujo:
  1. Examinar → FileDialog → carga capítulos en CheckListCtrl (hilo de fondo).
  2. El usuario marca / desmarca secciones con Espacio.
     Por defecto solo las hojas del índice (sin subniveles) vienen marcadas.
  3. "Dividir seleccionados" → genera un TXT por capítulo marcado (hilo de fondo).
  4. Resultado: diálogo "Se han generado N archivos. ¿Abrir carpeta de destino?".
  5. "Limpiar lista" → resetea el diálogo para procesar otro EPUB sin cerrarlo.

Accesibilidad:
  · La lista de capítulos usa CheckListCtrlMixin → NVDA anuncia marcado/desmarcado.
  · Escape cierra el diálogo (EVT_CHAR_HOOK).
  · El botón "Dividir" se deshabilita durante el proceso y luego vuelve.
  · El label de progreso actualiza el título de la ventana para NVDA.
  · Todos los botones usan aplicar_icono_boton() → AccessibleName siempre presente.
"""

import logging
import os
import threading

import wx
import wx.lib.mixins.listctrl as listmix

from app.motor.troceador_epub import TroceadorEpub
from app.motor.reproductor_sonidos import reproducir, ERROR, OPEN_FOLDER, LIST_NAV, SUCCESS, PROGRESS, CLEAR
from app.interfaz.ui_recursos import aplicar_icono_boton
from app.motor.anunciador_voz import AnunciadorVoz
from app.motor.gestor_idioma import traducir as _

logger = logging.getLogger(__name__)


# ── Lista de capítulos con casillas ──────────────────────────────────────────

class ListaCapitulos(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    """
    ListCtrl accesible con casillas. Una sola columna: "01 Nombre del capítulo".
    NVDA anuncia directamente el número y el título sin separadores artificiales.
    """
    def __init__(self, parent):
        wx.ListCtrl.__init__(
            self, parent,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_NO_HEADER,
        )
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.EnableCheckBoxes(True)
        self.InsertColumn(0, _("Capítulo"), width=500)
        self.SetHelpText(
            _("Lista de capítulos del EPUB. Flechas Arriba y Abajo para navegar. "
              "Espacio para marcar o desmarcar el capítulo enfocado. "
              "Los capítulos marcados se exportarán como archivos TXT individuales. "
              "El número de cada capítulo coincide con el número del archivo TXT generado.")
        )
        self.Bind(wx.EVT_LIST_KEY_DOWN, self._al_tecla)

    def _al_tecla(self, event):
        keycode = event.GetKeyCode()
        # Navegar con flechas → sonido de navegación (no al marcar/desmarcar)
        if keycode in (wx.WXK_UP, wx.WXK_DOWN):
            reproducir(LIST_NAV)
        elif keycode == wx.WXK_SPACE:
            idx = self.GetFirstSelected()
            if idx != -1:
                self.ToggleItem(idx)
        event.Skip()


# ── Diálogo principal ─────────────────────────────────────────────────────────

class DialogoTroceador(wx.Dialog):
    """
    Diálogo modal para dividir EPUBs en archivos TXT.
    Se construye completo; la lista de capítulos se rellena tras cargar el EPUB.
    """

    def __init__(self, parent):
        super().__init__(
            parent,
            title=_("Dividir EPUB en capítulos TXT"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(700, 600),
        )
        self._troceador      = TroceadorEpub()
        self._carpeta_salida = ""
        self._construir()
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

        # Antes la división de capítulos solo se veía en la barra y el
        # título de la ventana — nada que NVDA verbalizara sin más mientras
        # duraba. Misma cola de voz con descarte de mensajes intermedios ya
        # usada en el escaneo de Biblioteca y en la Fase C del actualizador.
        self._voz_progreso = AnunciadorVoz()
        self._progreso_actual = (0, 0)
        self._timer_progreso = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._al_temporizador_progreso, self._timer_progreso)
        self.Bind(wx.EVT_WINDOW_DESTROY, lambda e: (self._voz_progreso.detener(), e.Skip()))

    # ── Construcción de la interfaz ───────────────────────────────────────────

    def _construir(self):
        panel = wx.Panel(self)
        sz    = wx.BoxSizer(wx.VERTICAL)

        # ── Selector de archivo ───────────────────────────────────────────────
        sb_arch = wx.StaticBox(panel, label=_("Archivo EPUB de origen"))
        sz_arch = wx.StaticBoxSizer(sb_arch, wx.HORIZONTAL)

        self.txt_ruta = wx.TextCtrl(panel, style=wx.TE_READONLY)
        self.txt_ruta.SetHelpText(
            _("Ruta del archivo EPUB seleccionado. Solo lectura. "
              "Usa el botón 'Examinar EPUB' para seleccionar un archivo.")
        )
        self.btn_examinar = wx.Button(panel, label=_("Examinar EPUB…"))
        self.btn_examinar.SetHelpText(
            _("Abre un diálogo para seleccionar el archivo EPUB que deseas dividir en capítulos.")
        )
        aplicar_icono_boton(self.btn_examinar, "examinar", _("Examinar EPUB"))

        sz_arch.Add(self.txt_ruta,     1, wx.EXPAND | wx.ALL, 4)
        sz_arch.Add(self.btn_examinar, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        sz.Add(sz_arch, 0, wx.EXPAND | wx.ALL, 8)

        # ── Lista de capítulos ────────────────────────────────────────────────
        sb_caps = wx.StaticBox(
            panel,
            label=_("Capítulos detectados (Espacio para marcar o desmarcar)"),
        )
        sz_caps = wx.StaticBoxSizer(sb_caps, wx.VERTICAL)

        self.lista_caps = ListaCapitulos(panel)
        sz_caps.Add(self.lista_caps, 1, wx.EXPAND | wx.ALL, 4)

        # Botones de selección masiva + limpiar lista
        sz_sel = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_sel_todo   = wx.Button(panel, label=_("Seleccionar todo"))
        self.btn_desel_todo = wx.Button(panel, label=_("Deseleccionar todo"))
        self.btn_limpiar    = wx.Button(panel, label=_("Limpiar lista"))
        self.btn_sel_todo.SetHelpText(_("Marca todos los capítulos de la lista."))
        self.btn_desel_todo.SetHelpText(_("Desmarca todos los capítulos de la lista."))
        self.btn_limpiar.SetHelpText(
            _("Resetea el diálogo: borra la lista y la ruta del EPUB para "
              "poder cargar otro archivo sin cerrar la ventana.")
        )
        aplicar_icono_boton(self.btn_sel_todo,   "seleccionar",   _("Seleccionar todo"))
        aplicar_icono_boton(self.btn_desel_todo, "deseleccionar", _("Deseleccionar todo"))
        aplicar_icono_boton(self.btn_limpiar,    "limpiar",       _("Limpiar lista"))
        sz_sel.Add(self.btn_sel_todo,   0, wx.RIGHT, 8)
        sz_sel.Add(self.btn_desel_todo, 0, wx.RIGHT, 8)
        sz_sel.Add(self.btn_limpiar,    0)
        sz_caps.Add(sz_sel, 0, wx.ALL, 4)

        sz.Add(sz_caps, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Barra de acción ───────────────────────────────────────────────────
        sz_accion = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_dividir = wx.Button(panel, label=_("Dividir seleccionados"))
        self.btn_dividir.SetHelpText(
            _("Genera un archivo TXT por cada capítulo marcado. "
              "Los archivos se guardan en Grabaciones_Epub-TTS/<Nombre del libro>/capitulos/.")
        )
        self.btn_dividir.Disable()
        aplicar_icono_boton(self.btn_dividir, "trocear", _("Dividir seleccionados"))

        self.lbl_progreso = wx.StaticText(panel, label="")
        self.lbl_progreso.SetHelpText(
            _("Progreso de la división y resultado final. "
              "NVDA lo leerá al enfocar esta etiqueta.")
        )

        self.btn_abrir_carpeta = wx.Button(panel, label=_("Abrir carpeta capitulos"))
        self.btn_abrir_carpeta.SetHelpText(
            _("Abre en el Explorador la carpeta /capitulos/ donde se generaron los TXT.")
        )
        self.btn_abrir_carpeta.Hide()
        aplicar_icono_boton(self.btn_abrir_carpeta, "carpeta", _("Abrir carpeta capitulos"))

        self.barra_progreso = wx.Gauge(panel, range=100)
        self.barra_progreso.Hide()

        sz_accion.Add(self.btn_dividir,      0, wx.RIGHT, 8)
        sz_accion.Add(self.lbl_progreso,     1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sz_accion.Add(self.barra_progreso,   1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sz_accion.Add(self.btn_abrir_carpeta, 0)
        sz.Add(sz_accion, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Botón cerrar ──────────────────────────────────────────────────────
        sz.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        btn_cerrar = wx.Button(panel, wx.ID_CLOSE, label=_("Cerrar (Escape)"))
        btn_cerrar.SetHelpText(_("Cierra este diálogo. También puedes pulsar Escape."))
        aplicar_icono_boton(btn_cerrar, "cerrar", _("Cerrar diálogo"))
        sz.Add(btn_cerrar, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(sz)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        # ── Eventos ───────────────────────────────────────────────────────────
        self.btn_examinar.Bind(   wx.EVT_BUTTON, self._al_examinar)
        self.btn_sel_todo.Bind(   wx.EVT_BUTTON, lambda e: self._seleccionar_todo(True))
        self.btn_desel_todo.Bind( wx.EVT_BUTTON, lambda e: self._seleccionar_todo(False))
        self.btn_limpiar.Bind(    wx.EVT_BUTTON, self._al_limpiar)
        self.btn_dividir.Bind(    wx.EVT_BUTTON, self._al_dividir)
        self.btn_abrir_carpeta.Bind(wx.EVT_BUTTON, self._al_abrir_carpeta)
        btn_cerrar.Bind(          wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

    # ── Selección y carga de archivo EPUB ────────────────────────────────────

    def _al_examinar(self, evento=None):
        with wx.FileDialog(
            self,
            _("Seleccionar archivo EPUB"),
            wildcard=_("Archivos EPUB (*.epub)|*.epub|Todos (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            ruta = dlg.GetPath()

        self.txt_ruta.SetValue(ruta)
        self._cargar_epub(ruta)

    def _cargar_epub(self, ruta: str):
        """Lanza la carga del EPUB en hilo de fondo."""
        self.lista_caps.DeleteAllItems()
        self.btn_dividir.Disable()
        self.btn_abrir_carpeta.Hide()
        self._set_progreso(_("Cargando índice del EPUB…"))
        self.Layout()

        def _tarea():
            try:
                caps = self._troceador.cargar(ruta)
                wx.CallAfter(self._al_epub_cargado, caps, None)
            except Exception as exc:
                logger.exception("Error al cargar el índice del EPUB para trocear")
                wx.CallAfter(self._al_epub_cargado, [], str(exc))

        threading.Thread(target=_tarea, daemon=True).start()

    def _al_epub_cargado(self, caps: list, error: str):
        if error:
            self._set_progreso(_("Error al cargar: {error}").format(error=error))
            wx.MessageBox(
                _("No se pudo leer el EPUB:\n{error}").format(error=error),
                _("Error al abrir EPUB"), wx.OK | wx.ICON_ERROR,
            )
            reproducir(ERROR)
            return

        self.lista_caps.DeleteAllItems()
        self.lista_caps.Freeze()
        try:
            for i, cap in enumerate(caps):
                # Una sola columna: "01 Nombre del capítulo"
                # El número coincide con el nombre del fichero TXT generado (idx+1)
                etiqueta = f"{i + 1:02d}  {cap['display']}"
                self.lista_caps.InsertItem(i, etiqueta)
                # Hojas (sin subniveles) → marcadas por defecto
                # Padres (secciones contenedoras) → desmarcados por defecto
                self.lista_caps.CheckItem(i, not cap["es_padre"])
        finally:
            self.lista_caps.Thaw()

        n = len(caps)
        self._set_progreso(
            _("{n} sección(es) en el índice. Marca las que quieres exportar.").format(n=n)
        )
        self.btn_dividir.Enable(n > 0)
        wx.CallAfter(self.lista_caps.SetFocus)

    # ── Selección masiva y limpieza ───────────────────────────────────────────

    def _seleccionar_todo(self, marcar: bool):
        for i in range(self.lista_caps.GetItemCount()):
            self.lista_caps.CheckItem(i, marcar)

    def _al_limpiar(self, evento=None):
        """Resetea el diálogo para cargar otro EPUB."""
        reproducir(CLEAR)
        self.lista_caps.DeleteAllItems()
        self.txt_ruta.SetValue("")
        self.btn_dividir.Disable()
        self.btn_abrir_carpeta.Hide()
        self._carpeta_salida = ""
        self._set_progreso("")
        self.Layout()
        wx.CallAfter(self.btn_examinar.SetFocus)

    # ── Proceso de división ───────────────────────────────────────────────────

    def _al_dividir(self, evento=None):
        indices = [
            i for i in range(self.lista_caps.GetItemCount())
            if self.lista_caps.IsItemChecked(i)
        ]
        if not indices:
            wx.MessageBox(
                _("Marca al menos un capítulo antes de iniciar la división."),
                _("Nada seleccionado"), wx.OK | wx.ICON_INFORMATION,
            )
            return

        carpeta = TroceadorEpub.carpeta_salida_para(self.txt_ruta.GetValue())
        self._carpeta_salida = carpeta

        self.btn_dividir.Disable()
        self.btn_examinar.Disable()
        self.btn_abrir_carpeta.Hide()
        self._set_progreso(_("Dividiendo…"))
        self.barra_progreso.SetValue(0)
        self.barra_progreso.Show()
        self.Layout()
        self._timer_progreso.Start(2500)

        reproducir(PROGRESS)

        def _progreso(actual, total, titulo):
            wx.CallAfter(self._actualizar_barra, actual, total)
            wx.CallAfter(
                self._set_progreso,
                _("Procesando {actual}/{total}: {titulo}").format(actual=actual, total=total, titulo=titulo),
            )

        def _tarea():
            try:
                n = self._troceador.dividir(indices, carpeta, _progreso)
                wx.CallAfter(self._al_division_completada, n, carpeta, None)
            except Exception as exc:
                logger.exception("Error al dividir el EPUB en capítulos")
                wx.CallAfter(self._al_division_completada, 0, carpeta, str(exc))

        threading.Thread(target=_tarea, daemon=True).start()

    def _actualizar_barra(self, actual: int, total: int):
        self._progreso_actual = (actual, total)
        if total > 0:
            self.barra_progreso.SetRange(total)
            self.barra_progreso.SetValue(min(actual, total))

    def _al_temporizador_progreso(self, evento):
        actual, total = self._progreso_actual
        if total > 0:
            self._voz_progreso.hablar(
                _("Dividiendo... {actual} de {total} capítulos.").format(actual=actual, total=total)
            )

    def _al_division_completada(self, n_archivos: int, carpeta: str, error: str):
        self._timer_progreso.Stop()
        self.btn_dividir.Enable()
        self.btn_examinar.Enable()
        self.barra_progreso.Hide()
        self.Layout()

        if error:
            self._set_progreso(_("Error durante la división: {error}").format(error=error))
            wx.MessageBox(
                _("Se produjo un error durante la división:\n{error}").format(error=error),
                _("Error al dividir"), wx.OK | wx.ICON_ERROR,
            )
            reproducir(ERROR)
            return

        self._set_progreso(
            _("División completada: {n} archivo(s) TXT generado(s).").format(n=n_archivos)
        )
        self.btn_abrir_carpeta.Show()
        self.Layout()
        reproducir(SUCCESS)

        # Diálogo Sí/No para abrir la carpeta /capitulos/
        respuesta = wx.MessageBox(
            _("Se han generado {n} archivo(s).\n¿Abrir carpeta de destino?").format(n=n_archivos),
            _("División completada"),
            wx.YES_NO | wx.ICON_INFORMATION,
        )
        if respuesta == wx.YES:
            self._abrir_carpeta_capitulos()

    def _set_progreso(self, texto: str):
        """Actualiza label de progreso Y título de la ventana (retroalimentación NVDA)."""
        self.lbl_progreso.SetLabel(texto)
        sufijo = f" — {texto}" if texto else ""
        self.SetTitle(_("Dividir EPUB{sufijo}").format(sufijo=sufijo))

    # ── Abrir carpeta de destino ──────────────────────────────────────────────

    def _abrir_carpeta_capitulos(self):
        if not self._carpeta_salida or not os.path.isdir(self._carpeta_salida):
            wx.MessageBox(
                _("La carpeta de destino no existe todavía o no se ha generado correctamente."),
                _("Carpeta no encontrada"), wx.OK | wx.ICON_WARNING,
            )
            return
        reproducir(OPEN_FOLDER)
        try:
            if os.name == "nt":
                os.startfile(self._carpeta_salida)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", self._carpeta_salida])
        except Exception as exc:
            wx.MessageBox(
                _("No se pudo abrir la carpeta:\n{error}").format(error=exc),
                _("Error al abrir carpeta"), wx.OK | wx.ICON_ERROR,
            )

    def _al_abrir_carpeta(self, evento=None):
        self._abrir_carpeta_capitulos()

    # ── Teclado global ────────────────────────────────────────────────────────

    def _al_tecla_global(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        evento.Skip()
# ANCLAJE_FIN: DIALOGO_TROCEADOR
