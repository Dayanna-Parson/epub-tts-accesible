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

import os
import threading

import wx
import wx.lib.mixins.listctrl as listmix

from app.motor.troceador_epub import TroceadorEpub
from app.motor.reproductor_sonidos import reproducir, ERROR, OPEN_FOLDER, LIST_NAV, SUCCESS, PROCESO
from app.interfaz.ui_recursos import aplicar_icono_boton


# ── Lista de capítulos con casillas ──────────────────────────────────────────

class ListaCapitulos(wx.ListCtrl, listmix.CheckListCtrlMixin, listmix.ListCtrlAutoWidthMixin):
    """
    ListCtrl accesible con casillas. Una sola columna: "01 Nombre del capítulo".
    NVDA anuncia directamente el número y el título sin separadores artificiales.
    """
    def __init__(self, parent):
        wx.ListCtrl.__init__(
            self, parent,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_NO_HEADER,
        )
        listmix.CheckListCtrlMixin.__init__(self)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.EnableCheckBoxes(True)
        self.InsertColumn(0, "Capítulo", width=500)
        self.SetHelpText(
            "Lista de capítulos del EPUB. Flechas Arriba y Abajo para navegar. "
            "Espacio para marcar o desmarcar el capítulo enfocado. "
            "Los capítulos marcados se exportarán como archivos TXT individuales. "
            "El número de cada capítulo coincide con el número del archivo TXT generado."
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
            title="Dividir EPUB en capítulos TXT",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(700, 600),
        )
        self._troceador      = TroceadorEpub()
        self._carpeta_salida = ""
        self._construir()
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

    # ── Construcción de la interfaz ───────────────────────────────────────────

    def _construir(self):
        panel = wx.Panel(self)
        sz    = wx.BoxSizer(wx.VERTICAL)

        # ── Selector de archivo ───────────────────────────────────────────────
        sb_arch = wx.StaticBox(panel, label="Archivo EPUB de origen")
        sz_arch = wx.StaticBoxSizer(sb_arch, wx.HORIZONTAL)

        self.txt_ruta = wx.TextCtrl(panel, style=wx.TE_READONLY)
        self.txt_ruta.SetHelpText(
            "Ruta del archivo EPUB seleccionado. Solo lectura. "
            "Usa el botón 'Examinar EPUB' para seleccionar un archivo."
        )
        self.btn_examinar = wx.Button(panel, label="&Examinar EPUB…")
        self.btn_examinar.SetHelpText(
            "Abre un diálogo para seleccionar el archivo EPUB que deseas dividir en capítulos."
        )
        aplicar_icono_boton(self.btn_examinar, "examinar", "Examinar EPUB")

        sz_arch.Add(self.txt_ruta,     1, wx.EXPAND | wx.ALL, 4)
        sz_arch.Add(self.btn_examinar, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        sz.Add(sz_arch, 0, wx.EXPAND | wx.ALL, 8)

        # ── Lista de capítulos ────────────────────────────────────────────────
        sb_caps = wx.StaticBox(
            panel,
            label="Capítulos detectados (Espacio para marcar o desmarcar)",
        )
        sz_caps = wx.StaticBoxSizer(sb_caps, wx.VERTICAL)

        self.lista_caps = ListaCapitulos(panel)
        sz_caps.Add(self.lista_caps, 1, wx.EXPAND | wx.ALL, 4)

        # Botones de selección masiva + limpiar lista
        sz_sel = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_sel_todo   = wx.Button(panel, label="Seleccionar &todo")
        self.btn_desel_todo = wx.Button(panel, label="&Deseleccionar todo")
        self.btn_limpiar    = wx.Button(panel, label="&Limpiar lista")
        self.btn_sel_todo.SetHelpText("Marca todos los capítulos de la lista.")
        self.btn_desel_todo.SetHelpText("Desmarca todos los capítulos de la lista.")
        self.btn_limpiar.SetHelpText(
            "Resetea el diálogo: borra la lista y la ruta del EPUB para "
            "poder cargar otro archivo sin cerrar la ventana."
        )
        aplicar_icono_boton(self.btn_sel_todo,   "seleccionar",   "Seleccionar todo")
        aplicar_icono_boton(self.btn_desel_todo, "deseleccionar", "Deseleccionar todo")
        aplicar_icono_boton(self.btn_limpiar,    "limpiar",       "Limpiar lista")
        sz_sel.Add(self.btn_sel_todo,   0, wx.RIGHT, 8)
        sz_sel.Add(self.btn_desel_todo, 0, wx.RIGHT, 8)
        sz_sel.Add(self.btn_limpiar,    0)
        sz_caps.Add(sz_sel, 0, wx.ALL, 4)

        sz.Add(sz_caps, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Barra de acción ───────────────────────────────────────────────────
        sz_accion = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_dividir = wx.Button(panel, label="&Dividir seleccionados")
        self.btn_dividir.SetHelpText(
            "Genera un archivo TXT por cada capítulo marcado. "
            "Los archivos se guardan en Grabaciones_Epub-TTS/<Nombre del libro>/capitulos/."
        )
        self.btn_dividir.Disable()
        aplicar_icono_boton(self.btn_dividir, "trocear", "Dividir seleccionados")

        self.lbl_progreso = wx.StaticText(panel, label="")
        self.lbl_progreso.SetHelpText(
            "Progreso de la división y resultado final. "
            "NVDA lo leerá al enfocar esta etiqueta."
        )

        self.btn_abrir_carpeta = wx.Button(panel, label="Abrir carpeta &capitulos")
        self.btn_abrir_carpeta.SetHelpText(
            "Abre en el Explorador la carpeta /capitulos/ donde se generaron los TXT."
        )
        self.btn_abrir_carpeta.Hide()
        aplicar_icono_boton(self.btn_abrir_carpeta, "carpeta", "Abrir carpeta capitulos")

        sz_accion.Add(self.btn_dividir,      0, wx.RIGHT, 8)
        sz_accion.Add(self.lbl_progreso,     1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sz_accion.Add(self.btn_abrir_carpeta, 0)
        sz.Add(sz_accion, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Botón cerrar ──────────────────────────────────────────────────────
        sz.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        btn_cerrar = wx.Button(panel, wx.ID_CLOSE, label="&Cerrar (Escape)")
        btn_cerrar.SetHelpText("Cierra este diálogo. También puedes pulsar Escape.")
        aplicar_icono_boton(btn_cerrar, "cerrar", "Cerrar diálogo")
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
            "Seleccionar archivo EPUB",
            wildcard="Archivos EPUB (*.epub)|*.epub|Todos (*.*)|*.*",
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
        self._set_progreso("Cargando índice del EPUB…")
        self.Layout()

        def _tarea():
            try:
                caps = self._troceador.cargar(ruta)
                wx.CallAfter(self._al_epub_cargado, caps, None)
            except Exception as exc:
                wx.CallAfter(self._al_epub_cargado, [], str(exc))

        threading.Thread(target=_tarea, daemon=True).start()

    def _al_epub_cargado(self, caps: list, error: str):
        if error:
            self._set_progreso(f"Error al cargar: {error}")
            wx.MessageBox(
                f"No se pudo leer el EPUB:\n{error}",
                "Error al abrir EPUB", wx.OK | wx.ICON_ERROR,
            )
            reproducir(ERROR)
            return

        self.lista_caps.DeleteAllItems()
        for i, cap in enumerate(caps):
            # Una sola columna: "01 Nombre del capítulo"
            # El número coincide con el nombre del fichero TXT generado (idx+1)
            etiqueta = f"{i + 1:02d}  {cap['display']}"
            self.lista_caps.InsertItem(i, etiqueta)
            # Hojas (sin subniveles) → marcadas por defecto
            # Padres (secciones contenedoras) → desmarcados por defecto
            self.lista_caps.CheckItem(i, not cap["es_padre"])

        n = len(caps)
        self._set_progreso(
            f"{n} sección(es) en el índice. Marca las que quieres exportar."
        )
        self.btn_dividir.Enable(n > 0)
        wx.CallAfter(self.lista_caps.SetFocus)

    # ── Selección masiva y limpieza ───────────────────────────────────────────

    def _seleccionar_todo(self, marcar: bool):
        for i in range(self.lista_caps.GetItemCount()):
            self.lista_caps.CheckItem(i, marcar)

    def _al_limpiar(self, evento=None):
        """Resetea el diálogo para cargar otro EPUB."""
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
                "Marca al menos un capítulo antes de iniciar la división.",
                "Nada seleccionado", wx.OK | wx.ICON_INFORMATION,
            )
            return

        carpeta = TroceadorEpub.carpeta_salida_para(self.txt_ruta.GetValue())
        self._carpeta_salida = carpeta

        self.btn_dividir.Disable()
        self.btn_examinar.Disable()
        self.btn_abrir_carpeta.Hide()
        self._set_progreso("Dividiendo…")
        self.Layout()

        reproducir(PROCESO)

        def _progreso(actual, total, titulo):
            wx.CallAfter(
                self._set_progreso,
                f"Procesando {actual}/{total}: {titulo}",
            )

        def _tarea():
            try:
                n = self._troceador.dividir(indices, carpeta, _progreso)
                wx.CallAfter(self._al_division_completada, n, carpeta, None)
            except Exception as exc:
                wx.CallAfter(self._al_division_completada, 0, carpeta, str(exc))

        threading.Thread(target=_tarea, daemon=True).start()

    def _al_division_completada(self, n_archivos: int, carpeta: str, error: str):
        self.btn_dividir.Enable()
        self.btn_examinar.Enable()

        if error:
            self._set_progreso(f"Error durante la división: {error}")
            wx.MessageBox(
                f"Se produjo un error durante la división:\n{error}",
                "Error al dividir", wx.OK | wx.ICON_ERROR,
            )
            reproducir(ERROR)
            return

        self._set_progreso(f"División completada: {n_archivos} archivo(s) TXT generado(s).")
        self.btn_abrir_carpeta.Show()
        self.Layout()
        reproducir(SUCCESS)

        # Diálogo Sí/No para abrir la carpeta /capitulos/
        respuesta = wx.MessageBox(
            f"Se han generado {n_archivos} archivo(s).\n¿Abrir carpeta de destino?",
            "División completada",
            wx.YES_NO | wx.ICON_INFORMATION,
        )
        if respuesta == wx.YES:
            self._abrir_carpeta_capitulos()

    def _set_progreso(self, texto: str):
        """Actualiza label de progreso Y título de la ventana (retroalimentación NVDA)."""
        self.lbl_progreso.SetLabel(texto)
        sufijo = f" — {texto}" if texto else ""
        self.SetTitle(f"Dividir EPUB{sufijo}")

    # ── Abrir carpeta de destino ──────────────────────────────────────────────

    def _abrir_carpeta_capitulos(self):
        if not self._carpeta_salida or not os.path.isdir(self._carpeta_salida):
            wx.MessageBox(
                "La carpeta de destino no existe todavía o no se ha generado correctamente.",
                "Carpeta no encontrada", wx.OK | wx.ICON_WARNING,
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
                f"No se pudo abrir la carpeta:\n{exc}",
                "Error al abrir carpeta", wx.OK | wx.ICON_ERROR,
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
