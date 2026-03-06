# ANCLAJE_INICIO: DEPENDENCIAS_VENTANA_PROYECTOS
import wx
import logging

from app.motor.gestor_config import GestorProyectos, TIPOS_PROYECTO

logger = logging.getLogger(__name__)
# ANCLAJE_FIN: DEPENDENCIAS_VENTANA_PROYECTOS


# ANCLAJE_INICIO: VENTANA_PROYECTOS
class VentanaProyectos(wx.Frame):
    """
    Ventana independiente (no modal) para gestionar la jerarquía de proyectos.
    Se abre con Ctrl+P desde el menú principal.

    Layout:
      - Panel izquierdo: TreeCtrl con la jerarquía de proyectos.
      - Panel derecho: formulario de detalle del nodo seleccionado.
      - Barra inferior: botones de acción sobre proyectos.

    Accesibilidad NVDA:
      - SetHelpText() descriptivo en todos los controles.
      - Al seleccionar un nodo en el árbol el foco pasa al campo Nombre.
      - Confirmación antes de eliminar.
      - Al cerrar, el foco vuelve al Frame principal.
    """

    def __init__(self, parent):
        super().__init__(
            parent,
            title="Gestión de Proyectos — TifloHistorias",
            size=(900, 600),
        )
        self._frame_principal = parent
        self._gestor = GestorProyectos()
        # Mapa de TreeItemId → id de proyecto (str uuid)
        self._mapa_nodos = {}

        self._construir_interfaz()
        self._cargar_arbol()

        self.Bind(wx.EVT_CLOSE, self._al_cerrar)

    # ================================================================== #
    # Construcción de la interfaz
    # ================================================================== #

    def _construir_interfaz(self):
        panel_raiz = wx.Panel(self)
        sizer_raiz = wx.BoxSizer(wx.VERTICAL)

        # ── Área principal: árbol + detalle ──────────────────────────────
        sizer_principal = wx.BoxSizer(wx.HORIZONTAL)

        # ── Panel izquierdo: árbol de proyectos ──────────────────────────
        sz_arbol = wx.BoxSizer(wx.VERTICAL)
        lbl_arbol = wx.StaticText(panel_raiz, label="Jerarquía de proyectos:")
        self.arbol = wx.TreeCtrl(
            panel_raiz,
            style=(
                wx.TR_HAS_BUTTONS
                | wx.TR_LINES_AT_ROOT
                | wx.TR_SINGLE
                | wx.TR_HIDE_ROOT
                | wx.TR_EDIT_LABELS
            ),
        )
        self.arbol.SetHelpText(
            "Árbol de proyectos. Usa las flechas para navegar entre nodos. "
            "F2 renombra el nodo seleccionado. Supr elimina el nodo seleccionado. "
            "Enter o Espacio despliega o contrae un nodo con hijos."
        )
        sz_arbol.Add(lbl_arbol,   0, wx.BOTTOM, 4)
        sz_arbol.Add(self.arbol,  1, wx.EXPAND)

        # ── Panel derecho: detalle del nodo ──────────────────────────────
        sz_detalle = wx.BoxSizer(wx.VERTICAL)

        # Nombre
        lbl_nombre = wx.StaticText(panel_raiz, label="Nombre del proyecto (Intro para guardar):")
        self.txt_nombre = wx.TextCtrl(panel_raiz)
        self.txt_nombre.SetHelpText(
            "Nombre del proyecto seleccionado. Edítalo y pulsa Intro para guardar el cambio."
        )

        # Tipo
        lbl_tipo = wx.StaticText(panel_raiz, label="Tipo de proyecto:")
        self.combo_tipo = wx.Choice(panel_raiz, choices=TIPOS_PROYECTO)
        self.combo_tipo.SetHelpText(
            "Tipo de proyecto: saga, libro, capitulo, autoconclusivo, podcast, episodio, "
            "video_youtube, guion, dialogo u otro. Cambia el tipo del proyecto seleccionado."
        )

        # Archivos TXT asociados
        lbl_archivos = wx.StaticText(panel_raiz, label="Archivos TXT asociados a este proyecto:")
        self.lista_archivos = wx.ListCtrl(
            panel_raiz,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.lista_archivos.InsertColumn(0, "Nombre del archivo", width=160)
        self.lista_archivos.InsertColumn(1, "Ruta completa",      width=280)
        self.lista_archivos.SetHelpText(
            "Lista de archivos TXT asociados a este proyecto. "
            "Usa las flechas para navegar por la lista. "
            "Selecciona un archivo y usa el botón Quitar para desasociarlo."
        )

        sz_btn_archivos = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_añadir_txt = wx.Button(panel_raiz, label="&Añadir TXT al proyecto…")
        self.btn_añadir_txt.SetHelpText(
            "Abre un diálogo para seleccionar un archivo TXT y asociarlo a este proyecto."
        )
        self.btn_quitar_txt = wx.Button(panel_raiz, label="&Quitar TXT seleccionado")
        self.btn_quitar_txt.SetHelpText(
            "Desasocia el archivo TXT seleccionado de este proyecto. "
            "El archivo en disco no se elimina."
        )
        sz_btn_archivos.Add(self.btn_añadir_txt, 0, wx.RIGHT, 8)
        sz_btn_archivos.Add(self.btn_quitar_txt, 0)

        # Voces del proyecto (heredadas)
        lbl_voces = wx.StaticText(panel_raiz, label="Voces del proyecto (heredadas del padre si no hay propias):")
        self.lista_voces = wx.ListCtrl(
            panel_raiz,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.lista_voces.InsertColumn(0, "Etiqueta", width=120)
        self.lista_voces.InsertColumn(1, "Voz asignada", width=200)
        self.lista_voces.SetHelpText(
            "Voces asignadas a las etiquetas de este proyecto, incluyendo las heredadas "
            "del proyecto padre. Las voces del nivel más específico tienen prioridad."
        )

        # Ensamblar panel derecho
        sz_detalle.Add(lbl_nombre,          0, wx.BOTTOM, 2)
        sz_detalle.Add(self.txt_nombre,     0, wx.EXPAND | wx.BOTTOM, 8)
        sz_detalle.Add(lbl_tipo,            0, wx.BOTTOM, 2)
        sz_detalle.Add(self.combo_tipo,     0, wx.EXPAND | wx.BOTTOM, 8)
        sz_detalle.Add(lbl_archivos,        0, wx.BOTTOM, 2)
        sz_detalle.Add(self.lista_archivos, 1, wx.EXPAND | wx.BOTTOM, 4)
        sz_detalle.Add(sz_btn_archivos,     0, wx.BOTTOM, 8)
        sz_detalle.Add(lbl_voces,           0, wx.BOTTOM, 2)
        sz_detalle.Add(self.lista_voces,    1, wx.EXPAND)

        sizer_principal.Add(sz_arbol,   2, wx.EXPAND | wx.ALL, 8)
        sizer_principal.Add(sz_detalle, 3, wx.EXPAND | wx.TOP | wx.RIGHT | wx.BOTTOM, 8)

        # ── Barra inferior de botones de acción ──────────────────────────
        sz_barra = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_nuevo_raiz = wx.Button(panel_raiz, label="&Nuevo proyecto raíz")
        self.btn_nuevo_raiz.SetHelpText(
            "Crea un nuevo proyecto de nivel raíz sin padre. "
            "Se te pedirá nombre y tipo."
        )
        self.btn_nuevo_hijo = wx.Button(panel_raiz, label="Nuevo &hijo del seleccionado")
        self.btn_nuevo_hijo.SetHelpText(
            "Crea un proyecto hijo dentro del proyecto actualmente seleccionado en el árbol. "
            "Se te pedirá nombre y tipo."
        )
        self.btn_eliminar = wx.Button(panel_raiz, label="&Eliminar proyecto seleccionado")
        self.btn_eliminar.SetHelpText(
            "Elimina el proyecto seleccionado. Si tiene hijos, se eliminarán también. "
            "Se pedirá confirmación antes de proceder."
        )
        self.btn_cerrar = wx.Button(panel_raiz, label="&Cerrar esta ventana")
        self.btn_cerrar.SetHelpText(
            "Cierra la ventana de gestión de proyectos y devuelve el foco a la ventana principal."
        )

        sz_barra.Add(self.btn_nuevo_raiz, 0, wx.RIGHT, 8)
        sz_barra.Add(self.btn_nuevo_hijo, 0, wx.RIGHT, 8)
        sz_barra.Add(self.btn_eliminar,   0, wx.RIGHT, 8)
        sz_barra.Add((0, 0),             1)  # separador flexible
        sz_barra.Add(self.btn_cerrar,     0)

        sizer_raiz.Add(sizer_principal, 1, wx.EXPAND)
        sizer_raiz.Add(wx.StaticLine(panel_raiz), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer_raiz.Add(sz_barra, 0, wx.EXPAND | wx.ALL, 8)

        panel_raiz.SetSizer(sizer_raiz)

        # ── Eventos ───────────────────────────────────────────────────────
        self.arbol.Bind(wx.EVT_TREE_SEL_CHANGED,    self._al_seleccionar_nodo)
        self.arbol.Bind(wx.EVT_TREE_KEY_DOWN,        self._al_tecla_arbol)
        self.arbol.Bind(wx.EVT_TREE_END_LABEL_EDIT,  self._al_fin_edicion_nodo)

        self.txt_nombre.Bind(wx.EVT_TEXT_ENTER, self._al_guardar_nombre)
        self.combo_tipo.Bind(wx.EVT_CHOICE,     self._al_cambiar_tipo)

        self.btn_añadir_txt.Bind(wx.EVT_BUTTON, self._al_añadir_txt)
        self.btn_quitar_txt.Bind(wx.EVT_BUTTON, self._al_quitar_txt)

        self.btn_nuevo_raiz.Bind(wx.EVT_BUTTON, self._al_nuevo_raiz)
        self.btn_nuevo_hijo.Bind(wx.EVT_BUTTON, self._al_nuevo_hijo)
        self.btn_eliminar.Bind(wx.EVT_BUTTON,   self._al_eliminar)
        self.btn_cerrar.Bind(wx.EVT_BUTTON,     lambda e: self.Close())

        # Forzar Intro en txt_nombre (EVT_TEXT_ENTER requiere style=wx.TE_PROCESS_ENTER)
        self.txt_nombre.SetWindowStyleFlag(
            self.txt_nombre.GetWindowStyleFlag() | wx.TE_PROCESS_ENTER
        )

    # ================================================================== #
    # Carga y reconstrucción del árbol
    # ================================================================== #

    def _cargar_arbol(self):
        """Reconstruye el árbol completo desde el gestor de proyectos."""
        self.arbol.DeleteAllItems()
        self._mapa_nodos.clear()

        # Nodo raíz oculto requerido por wx.TR_HIDE_ROOT
        raiz_oculta = self.arbol.AddRoot("Proyectos")

        proyectos_raiz = self._gestor.listar_proyectos_raiz()
        for proyecto in proyectos_raiz:
            self._añadir_nodo_recursivo(raiz_oculta, proyecto)

        self.arbol.ExpandAll()
        self._limpiar_detalle()

    def _añadir_nodo_recursivo(self, nodo_padre_wx, proyecto: dict):
        """Añade un nodo al árbol y recursivamente todos sus hijos."""
        etiqueta = f"{proyecto['nombre']} [{proyecto['tipo']}]"
        nodo = self.arbol.AppendItem(nodo_padre_wx, etiqueta)
        self._mapa_nodos[nodo] = proyecto["id"]

        for hijo in self._gestor.listar_hijos(proyecto["id"]):
            self._añadir_nodo_recursivo(nodo, hijo)

    def _proyecto_seleccionado(self) -> dict | None:
        """Devuelve el dict del proyecto del nodo actualmente seleccionado, o None."""
        nodo = self.arbol.GetSelection()
        if not nodo or not nodo.IsOk():
            return None
        proyecto_id = self._mapa_nodos.get(nodo)
        if not proyecto_id:
            return None
        return self._gestor.obtener_proyecto(proyecto_id)

    # ================================================================== #
    # Detalle del nodo seleccionado
    # ================================================================== #

    def _al_seleccionar_nodo(self, evento):
        """Al seleccionar un nodo, rellena el panel de detalle y mueve el foco al nombre."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            self._limpiar_detalle()
            evento.Skip()
            return

        # Rellenar nombre
        self.txt_nombre.ChangeValue(proyecto.get("nombre", ""))

        # Seleccionar tipo en el combo
        tipo = proyecto.get("tipo", "otro")
        idx_tipo = TIPOS_PROYECTO.index(tipo) if tipo in TIPOS_PROYECTO else -1
        if idx_tipo >= 0:
            self.combo_tipo.SetSelection(idx_tipo)

        # Rellenar lista de archivos
        self._actualizar_lista_archivos(proyecto)

        # Rellenar lista de voces heredadas
        self._actualizar_lista_voces(proyecto["id"])

        # Mover el foco al campo nombre (wx.CallAfter para que NVDA lo anuncie)
        wx.CallAfter(self.txt_nombre.SetFocus)
        evento.Skip()

    def _limpiar_detalle(self):
        """Vacía el panel de detalle cuando no hay nodo seleccionado."""
        self.txt_nombre.ChangeValue("")
        self.combo_tipo.SetSelection(wx.NOT_FOUND)
        self.lista_archivos.DeleteAllItems()
        self.lista_voces.DeleteAllItems()

    def _actualizar_lista_archivos(self, proyecto: dict):
        """Rellena la lista de archivos TXT asociados al proyecto."""
        self.lista_archivos.DeleteAllItems()
        for ruta in proyecto.get("archivos", []):
            import os
            nombre = os.path.basename(ruta)
            idx = self.lista_archivos.InsertItem(self.lista_archivos.GetItemCount(), nombre)
            self.lista_archivos.SetItem(idx, 1, ruta)

    def _actualizar_lista_voces(self, proyecto_id: str):
        """Rellena la lista de voces heredadas del proyecto."""
        self.lista_voces.DeleteAllItems()
        voces = self._gestor.obtener_voces_heredadas(proyecto_id)
        for etiqueta, datos_voz in voces.items():
            nombre_voz = datos_voz.get("nombre", "—") if isinstance(datos_voz, dict) else str(datos_voz)
            idx = self.lista_voces.InsertItem(self.lista_voces.GetItemCount(), f"@{etiqueta}")
            self.lista_voces.SetItem(idx, 1, nombre_voz)

    # ================================================================== #
    # Guardar cambios de nombre y tipo
    # ================================================================== #

    def _al_guardar_nombre(self, evento):
        """Guarda el nombre editado en el campo Nombre (al pulsar Intro)."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        nuevo_nombre = self.txt_nombre.GetValue().strip()
        if not nuevo_nombre:
            wx.MessageBox(
                "El nombre del proyecto no puede estar vacío.",
                "Nombre inválido", wx.OK | wx.ICON_WARNING
            )
            return
        self._gestor.renombrar_proyecto(proyecto["id"], nuevo_nombre)
        # Actualizar etiqueta del nodo en el árbol
        nodo = self.arbol.GetSelection()
        tipo = proyecto.get("tipo", "otro")
        self.arbol.SetItemText(nodo, f"{nuevo_nombre} [{tipo}]")
        self.lbl_estado_rapido(f"Nombre guardado: {nuevo_nombre}")

    def _al_cambiar_tipo(self, evento):
        """Cambia el tipo del proyecto al seleccionar en el combo."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        idx = self.combo_tipo.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        nuevo_tipo = TIPOS_PROYECTO[idx]
        self._gestor.cambiar_tipo(proyecto["id"], nuevo_tipo)
        # Actualizar etiqueta del nodo en el árbol
        nodo = self.arbol.GetSelection()
        nombre = proyecto.get("nombre", "")
        self.arbol.SetItemText(nodo, f"{nombre} [{nuevo_tipo}]")

    # ================================================================== #
    # Teclas rápidas en el árbol: F2 = renombrar, Supr = eliminar
    # ================================================================== #

    def _al_tecla_arbol(self, evento):
        """Gestiona F2 (renombrar) y Supr (eliminar) en el árbol."""
        keycode = evento.GetKeyCode()
        if keycode == wx.WXK_F2:
            nodo = self.arbol.GetSelection()
            if nodo and nodo.IsOk():
                self.arbol.EditLabel(nodo)
        elif keycode == wx.WXK_DELETE:
            self._al_eliminar(None)
        else:
            evento.Skip()

    def _al_fin_edicion_nodo(self, evento):
        """Guarda el nuevo nombre tras la edición inline en el árbol (F2)."""
        if evento.IsEditCancelled():
            evento.Skip()
            return
        nuevo_nombre = evento.GetLabel().strip()
        if not nuevo_nombre:
            evento.Veto()
            wx.MessageBox(
                "El nombre del proyecto no puede estar vacío.",
                "Nombre inválido", wx.OK | wx.ICON_WARNING
            )
            return
        nodo = evento.GetItem()
        proyecto_id = self._mapa_nodos.get(nodo)
        if proyecto_id:
            proyecto = self._gestor.obtener_proyecto(proyecto_id)
            if proyecto:
                self._gestor.renombrar_proyecto(proyecto_id, nuevo_nombre)
                tipo = proyecto.get("tipo", "otro")
                # Actualizar etiqueta con el nuevo nombre y el tipo
                wx.CallAfter(
                    self.arbol.SetItemText, nodo, f"{nuevo_nombre} [{tipo}]"
                )
                # Refrescar campo de nombre en el detalle
                wx.CallAfter(self.txt_nombre.ChangeValue, nuevo_nombre)
        evento.Skip()

    # ================================================================== #
    # Gestión de archivos TXT
    # ================================================================== #

    def _al_añadir_txt(self, evento):
        """Abre un FileDialog para asociar un TXT al proyecto seleccionado."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            wx.MessageBox(
                "Selecciona primero un proyecto en el árbol.",
                "Sin proyecto seleccionado", wx.OK | wx.ICON_WARNING
            )
            return
        with wx.FileDialog(
            self,
            "Seleccionar archivo TXT para asociar al proyecto",
            wildcard="Archivos de texto (*.txt)|*.txt|Todos (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            ruta = dlg.GetPath()

        self._gestor.asociar_archivo(proyecto["id"], ruta)
        # Recargar el proyecto desde el gestor (datos actualizados)
        proyecto_actualizado = self._gestor.obtener_proyecto(proyecto["id"])
        if proyecto_actualizado:
            self._actualizar_lista_archivos(proyecto_actualizado)

    def _al_quitar_txt(self, evento):
        """Desasocia el TXT seleccionado en la lista del proyecto actual."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        idx = self.lista_archivos.GetFirstSelected()
        if idx == -1:
            wx.MessageBox(
                "Selecciona primero un archivo en la lista para quitarlo.",
                "Sin selección", wx.OK | wx.ICON_WARNING
            )
            return
        ruta = self.lista_archivos.GetItem(idx, 1).GetText()
        self._gestor.desasociar_archivo(ruta)
        proyecto_actualizado = self._gestor.obtener_proyecto(proyecto["id"])
        if proyecto_actualizado:
            self._actualizar_lista_archivos(proyecto_actualizado)

    # ================================================================== #
    # Crear proyectos nuevos
    # ================================================================== #

    def _pedir_nombre_y_tipo(self, titulo_dialogo: str) -> tuple[str, str] | None:
        """
        Muestra un diálogo para introducir nombre y tipo de proyecto.
        Devuelve (nombre, tipo) o None si el usuario cancela.
        """
        dlg = wx.Dialog(self, title=titulo_dialogo)
        panel = wx.Panel(dlg)
        sz = wx.BoxSizer(wx.VERTICAL)

        lbl_n = wx.StaticText(panel, label="Nombre del proyecto (obligatorio):")
        txt_n = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        txt_n.SetHelpText("Escribe el nombre del nuevo proyecto.")

        lbl_t = wx.StaticText(panel, label="Tipo de proyecto:")
        combo_t = wx.Choice(panel, choices=TIPOS_PROYECTO)
        combo_t.SetSelection(0)
        combo_t.SetHelpText(
            "Elige el tipo: saga, libro, capitulo, autoconclusivo, podcast, "
            "episodio, video_youtube, guion, dialogo u otro."
        )

        btn_ok     = wx.Button(panel, wx.ID_OK,     label="Crear proyecto")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, label="Cancelar")
        sz_botones = wx.BoxSizer(wx.HORIZONTAL)
        sz_botones.Add(btn_ok,     0, wx.RIGHT, 8)
        sz_botones.Add(btn_cancel, 0)

        sz.Add(lbl_n,      0, wx.ALL, 6)
        sz.Add(txt_n,      0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sz.Add(lbl_t,      0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sz.Add(combo_t,    0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sz.Add(sz_botones, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        panel.SetSizer(sz)

        dlg_sz = wx.BoxSizer(wx.VERTICAL)
        dlg_sz.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sz)
        dlg.Fit()

        wx.CallAfter(txt_n.SetFocus)

        resultado = dlg.ShowModal()
        nombre = txt_n.GetValue().strip()
        tipo_idx = combo_t.GetSelection()
        tipo = TIPOS_PROYECTO[tipo_idx] if tipo_idx >= 0 else "otro"
        dlg.Destroy()

        if resultado != wx.ID_OK or not nombre:
            return None
        return nombre, tipo

    def _al_nuevo_raiz(self, evento):
        """Crea un nuevo proyecto de nivel raíz."""
        resultado = self._pedir_nombre_y_tipo("Nuevo proyecto raíz")
        if resultado is None:
            return
        nombre, tipo = resultado
        self._gestor.crear_proyecto(nombre, tipo, padre_id=None)
        self._cargar_arbol()

    def _al_nuevo_hijo(self, evento):
        """Crea un proyecto hijo del nodo actualmente seleccionado."""
        proyecto_padre = self._proyecto_seleccionado()
        if proyecto_padre is None:
            wx.MessageBox(
                "Selecciona primero el proyecto padre en el árbol.",
                "Sin proyecto seleccionado", wx.OK | wx.ICON_WARNING
            )
            return
        resultado = self._pedir_nombre_y_tipo(
            f"Nuevo hijo de «{proyecto_padre['nombre']}»"
        )
        if resultado is None:
            return
        nombre, tipo = resultado
        self._gestor.crear_proyecto(nombre, tipo, padre_id=proyecto_padre["id"])
        self._cargar_arbol()

    # ================================================================== #
    # Eliminar proyecto
    # ================================================================== #

    def _al_eliminar(self, evento):
        """Elimina el proyecto seleccionado tras confirmación del usuario."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            wx.MessageBox(
                "Selecciona primero un proyecto en el árbol para eliminarlo.",
                "Sin proyecto seleccionado", wx.OK | wx.ICON_WARNING
            )
            return

        tiene_hijos = bool(self._gestor.listar_hijos(proyecto["id"]))
        if tiene_hijos:
            mensaje = (
                f"¿Eliminar «{proyecto['nombre']}» y TODOS sus proyectos hijos?\n\n"
                "Esta acción no se puede deshacer."
            )
        else:
            mensaje = (
                f"¿Eliminar el proyecto «{proyecto['nombre']}»?\n\n"
                "Esta acción no se puede deshacer."
            )

        dlg = wx.MessageDialog(
            self, mensaje, "Confirmar eliminación",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        )
        respuesta = dlg.ShowModal()
        dlg.Destroy()

        if respuesta != wx.ID_YES:
            return

        try:
            self._gestor.eliminar_proyecto(proyecto["id"], recursivo=True)
        except Exception as e:
            wx.MessageBox(
                f"No se pudo eliminar el proyecto:\n{e}",
                "Error al eliminar", wx.OK | wx.ICON_ERROR
            )
            return

        self._cargar_arbol()
        self._limpiar_detalle()

    # ================================================================== #
    # Auxiliares
    # ================================================================== #

    def lbl_estado_rapido(self, mensaje: str):
        """Muestra un mensaje breve en el título de la ventana (retroalimentación rápida)."""
        self.SetTitle(f"Gestión de Proyectos — {mensaje}")
        wx.CallLater(3000, lambda: self.SetTitle(
            "Gestión de Proyectos — TifloHistorias"
        ) if self else None)

    def _al_cerrar(self, evento):
        """Al cerrar, devuelve el foco a la ventana principal."""
        if self._frame_principal and self._frame_principal.IsShown():
            wx.CallAfter(self._frame_principal.SetFocus)
        evento.Skip()
# ANCLAJE_FIN: VENTANA_PROYECTOS
