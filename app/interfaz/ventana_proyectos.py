# ANCLAJE_INICIO: DEPENDENCIAS_VENTANA_PROYECTOS
import wx
import os
import json
import logging
import queue
import threading
import wx.lib.mixins.listctrl as listmix

from app.motor.gestor_proyectos import GestorProyectos, TIPOS_PROYECTO
from app.motor.reproductor_sonidos import (
    reproducir, LIST_NAV, MOVE_UP, MOVE_DOWN, OPEN_FOLDER, CLEAR, CLICK, ERROR, SUCCESS,
)

logger = logging.getLogger(__name__)
# ANCLAJE_FIN: DEPENDENCIAS_VENTANA_PROYECTOS


# ANCLAJE_INICIO: LISTA_CATEGORIAS
class ListaCategorias(wx.ListCtrl, listmix.CheckListCtrlMixin, listmix.ListCtrlAutoWidthMixin):
    """
    ListCtrl con casillas de verificación para seleccionar múltiples categorías.
    NVDA anuncia el estado (marcado/desmarcado) al navegar con las flechas.
    """
    def __init__(self, parent):
        wx.ListCtrl.__init__(
            self, parent,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        listmix.CheckListCtrlMixin.__init__(self)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        # Imprescindible para que las casillas sean visibles
        self.EnableCheckBoxes(True)
        self.InsertColumn(0, "Categoría", width=wx.LIST_AUTOSIZE_USEHEADER)
        for cat in TIPOS_PROYECTO:
            self.InsertItem(self.GetItemCount(), cat)
        self.Bind(wx.EVT_LIST_KEY_DOWN, self._al_tecla)

    def _al_tecla(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_UP, wx.WXK_DOWN):
            reproducir(LIST_NAV)
        elif key == wx.WXK_SPACE:
            idx = self.GetFirstSelected()
            if idx != -1:
                self.ToggleItem(idx)
        event.Skip()
# ANCLAJE_FIN: LISTA_CATEGORIAS


# ANCLAJE_INICIO: VENTANA_PROYECTOS
class VentanaProyectos(wx.Frame):
    """
    Ventana independiente (no modal) para gestionar la jerarquía de proyectos.
    Se abre con Ctrl+Shift+P desde el menú principal.

    Novedades v2 (Fase 3, Prompt 7):
      - Escape cierra la ventana y devuelve el foco exactamente al control previo.
      - Si se abre con un TXT cargado en Grabación, el árbol navega al nodo
        de ese archivo automáticamente (o informa si no está asociado).
      - Alt+Arriba / Alt+Abajo reordena nodos hermanos dentro de un padre.
        NVDA anuncia "Movido arriba" / "Movido abajo" vía pyttsx3 + título.
      - Menú contextual (tecla Aplicaciones / Shift+F10 / clic derecho):
          · Asociar TXT actual de Grabación
          · Nuevo subproyecto
          · Renombrar (F2)
          · Cambiar tipo
          · Eliminar
      - Botón «Cerrar» (antes «Cerrar esta ventana»).
      - Barra de estado integrada para retroalimentación sin diálogos modales.
      - Volcado de voces desde mapeo_etiquetas.json además de proyectos.json.
    """

    def __init__(self, parent, ruta_txt_activo=None, foco_previo=None, gestor_proyectos=None):
        super().__init__(
            parent,
            title="Gestión de Proyectos — Epub TTS",
            size=(900, 600),
        )
        self._frame_principal = parent
        # Compartir la instancia del gestor con PestanaGrabacion para evitar
        # que dos instancias independientes se sobreescriban mutuamente al guardar.
        self._gestor = gestor_proyectos if gestor_proyectos is not None else GestorProyectos()
        self._mapa_nodos = {}           # {TreeItemId → proyecto_id (str uuid)}
        self._ruta_txt_activo = ruta_txt_activo
        self._foco_previo = foco_previo
        self._proyecto_en_portapapeles: str | None = None  # id del proyecto cortado con Ctrl+X

        # Cola TTS: una sola instancia de pyttsx3 reutilizable para no bloquear el hilo principal.
        self._cola_tts: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker_tts, daemon=True).start()

        self._construir_interfaz()
        self._cargar_arbol()
        self._configurar_aceleradores()

        if ruta_txt_activo:
            wx.CallAfter(self._navegar_a_archivo, ruta_txt_activo)

        self.Bind(wx.EVT_CLOSE,     self._al_cerrar)
        self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla_global)

    # ================================================================== #
    # Construcción de la interfaz
    # ================================================================== #

    def _construir_interfaz(self):
        panel_raiz = wx.Panel(self)
        self._panel_raiz = panel_raiz
        sizer_raiz = wx.BoxSizer(wx.VERTICAL)

        # ── Área principal: árbol + detalle ──────────────────────────────
        sizer_principal = wx.BoxSizer(wx.HORIZONTAL)

        # ── Panel izquierdo: árbol de proyectos ──────────────────────────
        sz_arbol = wx.BoxSizer(wx.VERTICAL)
        lbl_arbol = wx.StaticText(panel_raiz, label="Proyectos:")
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
            "Lista de proyectos en árbol. Flechas para navegar; cada elemento muestra "
            "el nombre, el estado y el nivel. Tab: ir al panel de detalle. "
            "F2: renombrar. Supr: eliminar. "
            "Ctrl+Arriba / Ctrl+Abajo: reordenar dentro del mismo nivel. "
            "Ctrl+X: cortar para mover. Ctrl+V: pegar como subproyecto del seleccionado "
            "o como raíz si no hay nada seleccionado. Escape cancela el corte. "
            "Ctrl+Intro: abrir la carpeta en el Explorador. "
            "Menú o Shift+F10: más opciones."
        )
        sz_arbol.Add(lbl_arbol,  0, wx.BOTTOM, 4)
        sz_arbol.Add(self.arbol, 1, wx.EXPAND)

        # ── Panel derecho: detalle del nodo ──────────────────────────────
        sz_detalle = wx.BoxSizer(wx.VERTICAL)

        lbl_nombre = wx.StaticText(panel_raiz, label="Nombre del proyecto:")
        self.txt_nombre = wx.TextCtrl(panel_raiz, style=wx.TE_PROCESS_ENTER)
        self.txt_nombre.SetHelpText(
            "Nombre del proyecto seleccionado. Escribe el nuevo nombre y pulsa Intro para guardar."
        )

        lbl_tipo = wx.StaticText(
            panel_raiz,
            label="Categorías del proyecto:",
        )
        self.lista_cats = ListaCategorias(panel_raiz)
        self.lista_cats.SetMinSize((-1, 170))
        self.lista_cats.SetHelpText(
            "Categorías del proyecto. Flechas para navegar, Espacio para marcar o desmarcar. "
            "Puedes seleccionar varias a la vez."
        )

        lbl_archivos = wx.StaticText(panel_raiz, label="Archivos TXT asociados:")
        self.lista_archivos = wx.ListCtrl(
            panel_raiz,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.lista_archivos.InsertColumn(0, "Nombre del archivo", width=160)
        self.lista_archivos.InsertColumn(1, "Ruta completa",      width=280)
        self.lista_archivos.SetHelpText(
            "Archivos de texto vinculados a este proyecto. "
            "Flechas para navegar. Usa el botón Quitar TXT para desvincular el seleccionado."
        )

        sz_btn_archivos = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_añadir_txt = wx.Button(panel_raiz, label="Añadir TXT…")
        self.btn_añadir_txt.SetHelpText(
            "Abre un explorador de archivos para seleccionar un archivo de texto y vincularlo al proyecto."
        )
        self.btn_quitar_txt = wx.Button(panel_raiz, label="Quitar TXT")
        self.btn_quitar_txt.SetHelpText(
            "Desvincula el archivo de texto seleccionado de este proyecto. "
            "El archivo en disco no se borra."
        )
        sz_btn_archivos.Add(self.btn_añadir_txt, 0, wx.RIGHT, 8)
        sz_btn_archivos.Add(self.btn_quitar_txt, 0)

        lbl_voces = wx.StaticText(panel_raiz, label="Voces asignadas:")
        self.lista_voces = wx.ListCtrl(
            panel_raiz,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        self.lista_voces.InsertColumn(0, "Etiqueta",     width=120)
        self.lista_voces.InsertColumn(1, "Voz asignada", width=200)
        self.lista_voces.SetHelpText(
            "Voces asignadas a las etiquetas del proyecto. "
            "Si no hay voces propias, se muestran las heredadas del proyecto padre."
        )

        sz_detalle.Add(lbl_nombre,          0, wx.BOTTOM, 2)
        sz_detalle.Add(self.txt_nombre,     0, wx.EXPAND | wx.BOTTOM, 8)
        sz_detalle.Add(lbl_tipo,            0, wx.BOTTOM, 2)
        sz_detalle.Add(self.lista_cats,     0, wx.EXPAND | wx.BOTTOM, 8)
        sz_detalle.Add(lbl_archivos,        0, wx.BOTTOM, 2)
        sz_detalle.Add(self.lista_archivos, 1, wx.EXPAND | wx.BOTTOM, 4)
        sz_detalle.Add(sz_btn_archivos,     0, wx.BOTTOM, 8)
        sz_detalle.Add(lbl_voces,           0, wx.BOTTOM, 2)
        sz_detalle.Add(self.lista_voces,    1, wx.EXPAND)

        sizer_principal.Add(sz_arbol,   2, wx.EXPAND | wx.ALL, 8)
        sizer_principal.Add(sz_detalle, 3, wx.EXPAND | wx.TOP | wx.RIGHT | wx.BOTTOM, 8)

        # ── Barra inferior ────────────────────────────────────────────────
        # Nota: "Nuevo proyecto raíz" y "Nuevo hijo" se eliminaron de esta barra;
        # están accesibles vía menú contextual (Tecla Menú / Shift+F10 / clic derecho).
        sz_barra = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_eliminar = wx.Button(panel_raiz, label="Eliminar proyecto")
        self.btn_eliminar.SetHelpText(
            "Elimina el proyecto seleccionado y todos sus subproyectos. "
            "Se pedirá confirmación antes de proceder. "
            "También puedes pulsar Supr desde el árbol."
        )
        self.btn_cerrar = wx.Button(panel_raiz, label="Cerrar")
        self.btn_cerrar.SetHelpText(
            "Cierra el gestor y devuelve el foco a la ventana principal. "
            "También puedes pulsar Escape."
        )

        # Etiqueta de estado — retroalimentación sin diálogos modales
        self.lbl_estado = wx.StaticText(panel_raiz, label="")
        self.lbl_estado.SetHelpText(
            "Resultado de la última acción realizada."
        )

        sz_barra.Add(self.btn_eliminar,    0, wx.RIGHT, 8)
        sz_barra.Add((0, 0),               1)   # separador flexible
        sz_barra.Add(self.lbl_estado,   0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        sz_barra.Add(self.btn_cerrar,    0)

        sizer_raiz.Add(sizer_principal, 1, wx.EXPAND)
        sizer_raiz.Add(wx.StaticLine(panel_raiz), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer_raiz.Add(sz_barra, 0, wx.EXPAND | wx.ALL, 8)

        panel_raiz.SetSizer(sizer_raiz)

        # ── Eventos ───────────────────────────────────────────────────────
        self.arbol.Bind(wx.EVT_TREE_SEL_CHANGED,     self._al_seleccionar_nodo)
        self.arbol.Bind(wx.EVT_TREE_KEY_DOWN,         self._al_tecla_arbol)
        self.arbol.Bind(wx.EVT_TREE_END_LABEL_EDIT,  self._al_fin_edicion_nodo)
        self.arbol.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self._al_clic_derecho_arbol)
        self.arbol.Bind(wx.EVT_KEY_DOWN,              self._al_tecla_arbol_raw)

        self.txt_nombre.Bind(wx.EVT_TEXT_ENTER, self._al_guardar_nombre)
        self.lista_cats.Bind(wx.EVT_LIST_ITEM_CHECKED,   self._al_marcar_categoria)
        self.lista_cats.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._al_desmarcar_categoria)

        self.btn_añadir_txt.Bind(wx.EVT_BUTTON, self._al_añadir_txt)
        self.btn_quitar_txt.Bind(wx.EVT_BUTTON, self._al_quitar_txt)

        self.lista_archivos.Bind(wx.EVT_LIST_KEY_DOWN, self._al_tecla_lista_detalle)
        self.lista_voces.Bind(wx.EVT_LIST_KEY_DOWN, self._al_tecla_lista_detalle)

        self.btn_eliminar.Bind(    wx.EVT_BUTTON, self._al_eliminar)
        self.btn_cerrar.Bind(      wx.EVT_BUTTON, lambda e: self.Close())

    # ================================================================== #
    # Aceleradores de ventana (Ctrl+Arriba/Abajo/Intro)
    # ================================================================== #

    def _configurar_aceleradores(self):
        """
        Registra Ctrl+Arriba, Ctrl+Abajo y Ctrl+Intro como aceleradores
        a nivel de ventana (SetAcceleratorTable sobre el Frame).

        Usar AcceleratorTable —en lugar de EVT_KEY_DOWN— fuerza a Windows a
        entregar el evento a la app ANTES de que NVDA u otros interceptores
        del sistema lo procesen, resolviendo el problema de atajos silenciosos.

        Los mismos IDs (self._id_mover_*) se reutilizan en el menú contextual,
        de modo que menú y atajo comparten un único handler cada uno.
        """
        self._id_mover_arriba  = wx.NewIdRef()
        self._id_mover_abajo   = wx.NewIdRef()
        self._id_abrir_carpeta = wx.NewIdRef()
        self._id_cortar        = wx.NewIdRef()
        self._id_pegar         = wx.NewIdRef()

        self.Bind(wx.EVT_MENU, lambda e: self._mover_nodo(-1),           id=self._id_mover_arriba)
        self.Bind(wx.EVT_MENU, lambda e: self._mover_nodo(+1),           id=self._id_mover_abajo)
        self.Bind(wx.EVT_MENU, lambda e: self._abrir_carpeta_proyecto(),  id=self._id_abrir_carpeta)
        self.Bind(wx.EVT_MENU, lambda e: self._al_cortar_proyecto(),      id=self._id_cortar)
        self.Bind(wx.EVT_MENU, lambda e: self._al_pegar_proyecto(),       id=self._id_pegar)

        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, wx.WXK_UP,           self._id_mover_arriba),
            (wx.ACCEL_CTRL, wx.WXK_DOWN,         self._id_mover_abajo),
            (wx.ACCEL_CTRL, wx.WXK_RETURN,       self._id_abrir_carpeta),
            (wx.ACCEL_CTRL, wx.WXK_NUMPAD_ENTER, self._id_abrir_carpeta),
            (wx.ACCEL_CTRL, ord('X'),             self._id_cortar),
            (wx.ACCEL_CTRL, ord('V'),             self._id_pegar),
        ]))

    # ================================================================== #
    # Carga y reconstrucción del árbol
    # ================================================================== #

    def _cargar_arbol(self, seleccionar_id=None):
        """Reconstruye el árbol completo. Si seleccionar_id, selecciona ese nodo."""
        self.arbol.DeleteAllItems()
        self._mapa_nodos.clear()

        raiz_oculta = self.arbol.AddRoot("Proyectos")
        for proyecto in self._gestor.listar_proyectos_raiz():
            self._añadir_nodo_recursivo(raiz_oculta, proyecto)
        self.arbol.ExpandAll()

        if seleccionar_id:
            for nodo, pid in self._mapa_nodos.items():
                if pid == seleccionar_id:
                    self.arbol.SelectItem(nodo)
                    self.arbol.EnsureVisible(nodo)
                    break
        else:
            self._limpiar_detalle()

    def _añadir_nodo_recursivo(self, nodo_padre_wx, proyecto: dict, nivel: int = 1):
        etiqueta = self._etiqueta_nodo(proyecto, nivel)
        nodo = self.arbol.AppendItem(nodo_padre_wx, etiqueta)
        self._mapa_nodos[nodo] = proyecto["id"]
        for hijo in self._gestor.listar_hijos(proyecto["id"]):
            self._añadir_nodo_recursivo(nodo, hijo, nivel + 1)

    def _proyecto_seleccionado(self) -> dict | None:
        try:
            nodo = self.arbol.GetSelection()
        except RuntimeError:
            return None
        if not nodo or not nodo.IsOk():
            return None
        proyecto_id = self._mapa_nodos.get(nodo)
        if not proyecto_id:
            return None
        return self._gestor.obtener_proyecto(proyecto_id)

    # ================================================================== #
    # Navegar al nodo de un TXT activo (feature o)
    # ================================================================== #

    def _navegar_a_archivo(self, ruta: str):
        """
        Busca el proyecto al que pertenece ruta y selecciona su nodo en el árbol.
        Si no está asociado, muestra un mensaje en la barra de estado.
        """
        if not ruta:
            return
        self._gestor.recargar()
        proyecto = self._gestor.proyecto_de_archivo(ruta)
        if proyecto is None:
            nombre_archivo = os.path.basename(ruta)
            self._anunciar_estado(
                f"«{nombre_archivo}» no está asociado a ningún proyecto. "
                "Abre el menú contextual para asociarlo."
            )
            return
        for nodo, pid in self._mapa_nodos.items():
            if pid == proyecto["id"]:
                self.arbol.SelectItem(nodo)
                self.arbol.EnsureVisible(nodo)
                self._anunciar_estado(
                    f"Archivo asociado al proyecto: {proyecto['nombre']}"
                )
                return

    # ================================================================== #
    # Detalle del nodo seleccionado
    # ================================================================== #

    def _al_seleccionar_nodo(self, evento):
        """
        Actualiza el panel de detalle al cambiar la selección en el árbol.
        El foco NO se mueve automáticamente al panel de detalle —
        el usuario navega con flechas en el árbol y pulsa Tab cuando quiere editar.
        Esto evita el salto errático de foco que confunde a NVDA.
        """
        # Guardia ampliada: cualquier acceso al árbol o a los widgets del detalle
        # puede lanzar RuntimeError si el objeto C++ ya fue destruido (p. ej. al cerrar).
        try:
            if self.arbol.IsBeingDeleted():
                evento.Skip()
                return
            proyecto = self._proyecto_seleccionado()
            if proyecto is None:
                self._limpiar_detalle()
                evento.Skip()
                return
            self.txt_nombre.ChangeValue(proyecto.get("nombre", ""))
            tipos_activos = proyecto.get("tipo", [])
            if isinstance(tipos_activos, str):
                tipos_activos = [tipos_activos]
            for i in range(self.lista_cats.GetItemCount()):
                self.lista_cats.CheckItem(i, self.lista_cats.GetItemText(i) in tipos_activos)
            self._actualizar_lista_archivos(proyecto)
            self._actualizar_lista_voces(proyecto["id"])
        except RuntimeError:
            pass
        # NO SetFocus aquí: el foco se queda en el árbol para que NVDA lea el nodo
        evento.Skip()

    def _limpiar_detalle(self):
        self.txt_nombre.ChangeValue("")
        for i in range(self.lista_cats.GetItemCount()):
            self.lista_cats.CheckItem(i, False)
        self.lista_archivos.DeleteAllItems()
        self.lista_voces.DeleteAllItems()

    def _actualizar_lista_archivos(self, proyecto: dict):
        self.lista_archivos.DeleteAllItems()
        for ruta in proyecto.get("archivos", []):
            nombre = os.path.basename(ruta)
            idx = self.lista_archivos.InsertItem(self.lista_archivos.GetItemCount(), nombre)
            self.lista_archivos.SetItem(idx, 1, ruta)

    def _actualizar_lista_voces(self, proyecto_id: str):
        """
        Rellena la lista de voces combinando:
          1. Voces heredadas de proyectos.json (GestorProyectos).
          2. Voces de mapeo_etiquetas.json para los TXT asociados (feature g).
        Las voces del proyecto tienen prioridad; las del mapeo local completan los huecos.
        """
        self.lista_voces.DeleteAllItems()
        voces = self._gestor.obtener_voces_heredadas(proyecto_id)

        # Complementar con mapeo_etiquetas.json (feature g)
        proyecto = self._gestor.obtener_proyecto(proyecto_id)
        if proyecto:
            try:
                from app.config_rutas import ruta_config
                ruta_mapeo = ruta_config("mapeo_etiquetas.json")
                if os.path.exists(ruta_mapeo):
                    with open(ruta_mapeo, "r", encoding="utf-8") as f:
                        contenido = f.read().strip()
                    if contenido:
                        mapeo = json.loads(contenido)
                        for ruta_txt in proyecto.get("archivos", []):
                            titulo = os.path.splitext(os.path.basename(ruta_txt))[0]
                            for etiqueta, datos_voz in mapeo.get(titulo, {}).items():
                                if etiqueta not in voces:
                                    voces[etiqueta] = datos_voz
            except Exception:
                pass

        for etiqueta, datos_voz in voces.items():
            nombre_voz = (
                datos_voz.get("nombre", "—") if isinstance(datos_voz, dict)
                else str(datos_voz)
            )
            idx = self.lista_voces.InsertItem(self.lista_voces.GetItemCount(), f"@{etiqueta}")
            self.lista_voces.SetItem(idx, 1, nombre_voz)

    # ================================================================== #
    # Teclas globales de la ventana (Escape cierra)
    # ================================================================== #

    def _al_tecla_global(self, evento):
        keycode = evento.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            if self._proyecto_en_portapapeles:
                proyecto = self._gestor.obtener_proyecto(self._proyecto_en_portapapeles)
                self._proyecto_en_portapapeles = None
                reproducir(CLICK)
                nombre = proyecto["nombre"] if proyecto else "proyecto"
                self._anunciar_estado(f"Corte cancelado. «{nombre}» permanece en su sitio.")
                return
            self.Close()
            return
        # Tecla Menú / Shift+F10: menú contextual del árbol
        if keycode == getattr(wx, "WXK_WINDOWS_MENU", 348):
            self._mostrar_menu_contextual()
            return
        if keycode == wx.WXK_F10 and evento.ShiftDown():
            self._mostrar_menu_contextual()
            return
        evento.Skip()

    def _al_tecla_lista_detalle(self, evento):
        """Sonido de navegación en lista_archivos y lista_voces."""
        if evento.GetKeyCode() in (wx.WXK_UP, wx.WXK_DOWN):
            reproducir(LIST_NAV)
        evento.Skip()

    # ================================================================== #
    # Teclas en el árbol: F2, Supr (via EVT_TREE_KEY_DOWN)
    # ================================================================== #

    def _al_tecla_arbol(self, evento):
        """Gestiona F2 (renombrar) y Supr (eliminar) — EVT_TREE_KEY_DOWN."""
        keycode = evento.GetKeyCode()
        # PRIMERO: feedback de navegación antes de procesar cualquier lógica
        if keycode in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            reproducir(LIST_NAV)
        if keycode == wx.WXK_F2:
            nodo = self.arbol.GetSelection()
            if nodo and nodo.IsOk():
                self.arbol.EditLabel(nodo)
        elif keycode == wx.WXK_DELETE:
            self._al_eliminar(None)
        else:
            evento.Skip()

    def _al_tecla_arbol_raw(self, evento):
        """
        EVT_KEY_DOWN directo sobre el TreeCtrl.
        Ctrl+Arriba / Ctrl+Abajo : reordenar nodo entre hermanos.
        Ctrl+Intro               : abrir carpeta del proyecto en el Explorador.
        Tecla Menú / Shift+F10   : menú contextual.
        """
        keycode = evento.GetKeyCode()
        ctrl    = evento.ControlDown()
        shift   = evento.ShiftDown()

        if ctrl and keycode == wx.WXK_UP:
            self._mover_nodo(-1)
            return
        elif ctrl and keycode == wx.WXK_DOWN:
            self._mover_nodo(+1)
            return
        elif ctrl and keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._abrir_carpeta_proyecto()
            return
        elif keycode == getattr(wx, "WXK_WINDOWS_MENU", 348):
            self._mostrar_menu_contextual()
            return
        elif keycode == wx.WXK_F10 and shift:
            self._mostrar_menu_contextual()
            return

        evento.Skip()

    # ================================================================== #
    # Edición inline de nodos (F2 + fin de edición)
    # ================================================================== #

    def _al_fin_edicion_nodo(self, evento):
        if evento.IsEditCancelled():
            evento.Skip()
            return
        nuevo_nombre = evento.GetLabel().strip()
        if not nuevo_nombre:
            evento.Veto()
            reproducir(ERROR)
            wx.MessageBox(
                "El nombre no puede estar vacío.",
                "Nombre no válido", wx.OK | wx.ICON_WARNING
            )
            return
        nodo = evento.GetItem()
        proyecto_id = self._mapa_nodos.get(nodo)
        if proyecto_id:
            proyecto = self._gestor.obtener_proyecto(proyecto_id)
            if proyecto:
                self._gestor.renombrar_proyecto(proyecto_id, nuevo_nombre)
                proyecto["nombre"] = nuevo_nombre
                nivel = self._nivel_nodo(nodo)
                wx.CallAfter(self.arbol.SetItemText, nodo, self._etiqueta_nodo(proyecto, nivel))
                wx.CallAfter(self.txt_nombre.ChangeValue, nuevo_nombre)
                reproducir(SUCCESS)
        evento.Skip()

    # ================================================================== #
    # Menú contextual (clic derecho o tecla Menú / Shift+F10)
    # ================================================================== #

    def _al_clic_derecho_arbol(self, evento):
        nodo = evento.GetItem()
        if nodo and nodo.IsOk():
            self.arbol.SelectItem(nodo)
        self._mostrar_menu_contextual()

    def _mostrar_menu_contextual(self):
        proyecto = self._proyecto_seleccionado()

        # TXT activo en la pestaña Grabación (para "Asociar TXT actual")
        ruta_txt = None
        try:
            ruta_txt = self._frame_principal.pestana_grabacion.ruta_txt_actual
        except Exception:
            pass

        menu = wx.Menu()

        # Nuevo proyecto (siempre disponible)
        item_nuevo_raiz = menu.Append(wx.ID_ANY, "Nuevo proyecto")
        self.Bind(wx.EVT_MENU, self._al_nuevo_raiz, item_nuevo_raiz)

        # Nuevo subproyecto dentro del seleccionado (requiere selección)
        item_nuevo_hijo = menu.Append(wx.ID_ANY, "Nuevo subproyecto dentro del seleccionado")
        item_nuevo_hijo.Enable(bool(proyecto))
        self.Bind(wx.EVT_MENU, self._al_nuevo_hijo, item_nuevo_hijo)

        menu.AppendSeparator()

        item_asociar = menu.Append(wx.ID_ANY, "Asociar TXT actual de Grabación")
        item_asociar.Enable(bool(proyecto and ruta_txt))
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._asociar_txt_actual(proyecto, ruta_txt),
            item_asociar,
        )

        menu.AppendSeparator()

        # Cortar / Pegar para mover en la jerarquía
        etiq_pegar = (
            "Pegar como subproyecto (Ctrl+V)"
            if proyecto else
            "Pegar como raíz (Ctrl+V)"
        )
        item_cortar = menu.Append(self._id_cortar, "Cortar (Ctrl+X)")
        item_cortar.Enable(bool(proyecto))
        item_pegar = menu.Append(self._id_pegar, etiq_pegar)
        item_pegar.Enable(bool(self._proyecto_en_portapapeles))

        menu.AppendSeparator()

        # Reordenar — solo disponible para proyectos con padre (no raíz)
        puede_mover = bool(proyecto and proyecto.get("padre"))
        item_mover_arriba = menu.Append(self._id_mover_arriba, "Mover arriba (Ctrl+Arriba)")
        item_mover_arriba.Enable(puede_mover)
        item_mover_abajo = menu.Append(self._id_mover_abajo, "Mover abajo (Ctrl+Abajo)")
        item_mover_abajo.Enable(puede_mover)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar (F2)")
        item_renombrar.Enable(bool(proyecto))
        self.Bind(
            wx.EVT_MENU,
            lambda e: self.arbol.EditLabel(self.arbol.GetSelection()),
            item_renombrar,
        )

        menu.AppendSeparator()

        item_eliminar = menu.Append(wx.ID_ANY, "Eliminar…\tSupr")
        item_eliminar.Enable(bool(proyecto))
        self.Bind(wx.EVT_MENU, self._al_eliminar, item_eliminar)

        # Submenú Restaurar eliminado
        papelera = self._gestor.listar_papelera()
        sub_restaurar = wx.Menu()
        if papelera:
            for entrada in papelera:
                raiz = entrada["proyectos"].get(entrada["raiz_id"], {})
                nombre_pap = raiz.get("nombre", entrada["raiz_id"])
                ts = entrada.get("timestamp", "")[:10]   # solo la fecha
                etiq = f"{nombre_pap}  [{ts}]"
                item_rest = sub_restaurar.Append(wx.ID_ANY, etiq)
                raiz_id_cap = entrada["raiz_id"]
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, rid=raiz_id_cap: self._al_restaurar(rid),
                    item_rest,
                )
            sub_restaurar.AppendSeparator()
            item_vaciar = sub_restaurar.Append(wx.ID_ANY, "Vaciar papelera…")
            self.Bind(wx.EVT_MENU, self._al_vaciar_papelera, item_vaciar)
        else:
            item_vacio = sub_restaurar.Append(wx.ID_ANY, "No hay proyectos eliminados recientemente")
            item_vacio.Enable(False)

        menu.AppendSubMenu(sub_restaurar, "Restaurar proyectos eliminados recientemente…")

        self.arbol.PopupMenu(menu)
        menu.Destroy()

    def _asociar_txt_actual(self, proyecto: dict, ruta_txt: str):
        """Asocia el TXT activo de Grabación al proyecto seleccionado."""
        if not proyecto or not ruta_txt:
            return
        self._gestor.asociar_archivo(proyecto["id"], ruta_txt)
        proyecto_actualizado = self._gestor.obtener_proyecto(proyecto["id"])
        if proyecto_actualizado:
            self._actualizar_lista_archivos(proyecto_actualizado)
        nombre_archivo = os.path.basename(ruta_txt)
        self._anunciar_estado(f"«{nombre_archivo}» asociado a «{proyecto['nombre']}».")
        # Actualizar proyecto_actual en PestanaGrabacion
        try:
            self._frame_principal.pestana_grabacion.proyecto_actual = (
                self._gestor.obtener_proyecto(proyecto["id"])
            )
        except Exception:
            pass

    # ================================================================== #
    # Cortar / Pegar para mover proyectos en la jerarquía (Ctrl+X / Ctrl+V)
    # ================================================================== #

    def _al_cortar_proyecto(self):
        """Ctrl+X: marca el proyecto seleccionado como «en portapapeles» para moverlo."""
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        self._proyecto_en_portapapeles = proyecto["id"]
        reproducir(CLEAR)
        nombre = proyecto["nombre"]
        self._anunciar_estado(
            f"«{nombre}» cortado. Navega al destino y pulsa Ctrl+V para pegar, "
            "o Escape para cancelar."
        )
        self._hablar(f"{nombre} cortado")

    def _al_pegar_proyecto(self):
        """
        Ctrl+V: pega el proyecto cortado como subproyecto del seleccionado,
        o como proyecto raíz si no hay ninguno seleccionado.
        """
        if not self._proyecto_en_portapapeles:
            self._anunciar_estado("No hay ningún proyecto cortado. Selecciona uno y pulsa Ctrl+X.")
            return

        proyecto_cortado = self._gestor.obtener_proyecto(self._proyecto_en_portapapeles)
        if not proyecto_cortado:
            self._proyecto_en_portapapeles = None
            return

        destino = self._proyecto_seleccionado()
        destino_id = destino["id"] if destino else None
        nombre = proyecto_cortado["nombre"]

        ok = self._gestor.reparentar_proyecto(self._proyecto_en_portapapeles, destino_id)
        if ok:
            id_movido = self._proyecto_en_portapapeles
            self._proyecto_en_portapapeles = None
            reproducir(SUCCESS)
            self._cargar_arbol(seleccionar_id=id_movido)
            wx.CallAfter(self.arbol.SetFocus)
            if destino_id:
                nombre_destino = destino["nombre"]
                self._anunciar_estado(f"«{nombre}» pegado como subproyecto de «{nombre_destino}».")
                self._hablar(f"{nombre} movido a {nombre_destino}")
            else:
                self._anunciar_estado(f"«{nombre}» movido a raíz.")
                self._hablar(f"{nombre} movido a raíz")
        else:
            reproducir(ERROR)
            if destino_id == self._proyecto_en_portapapeles:
                self._anunciar_estado("No puedes pegar un proyecto dentro de sí mismo.")
            else:
                self._anunciar_estado("No se puede pegar aquí: causaría un ciclo en la jerarquía.")

    # ================================================================== #
    # Reordenar nodos: Alt+Arriba / Alt+Abajo (feature h)
    # ================================================================== #

    def _mover_nodo(self, delta: int):
        """
        Mueve el nodo seleccionado una posición arriba (delta=-1) o abajo (delta=+1).
        Anuncia resultado, devuelve el foco al árbol y selecciona el nodo movido.
        """
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        movido = self._gestor.mover_proyecto(proyecto["id"], delta)
        if movido:
            reproducir(MOVE_UP if delta < 0 else MOVE_DOWN)
            id_movido = proyecto["id"]
            self._cargar_arbol(seleccionar_id=id_movido)
            # Devolver foco al árbol después de reconstruirlo
            wx.CallAfter(self.arbol.SetFocus)
            direccion = "arriba" if delta < 0 else "abajo"
            nombre = proyecto["nombre"]
            self._anunciar_estado(f"Movido {direccion}: {nombre}")
            self._hablar(f"{nombre} movido {direccion}")
        else:
            self._anunciar_estado(
                "No se puede mover: está en el límite o es un proyecto raíz."
            )
            self._hablar("No se puede mover")

    # ================================================================== #
    # Guardar nombre y tipo desde el panel de detalle
    # ================================================================== #

    def _al_guardar_nombre(self, evento):
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        nuevo_nombre = self.txt_nombre.GetValue().strip()
        if not nuevo_nombre:
            reproducir(ERROR)
            wx.MessageBox(
                "El nombre no puede estar vacío.",
                "Nombre no válido", wx.OK | wx.ICON_WARNING
            )
            return
        self._gestor.renombrar_proyecto(proyecto["id"], nuevo_nombre)
        nodo = self.arbol.GetSelection()
        proyecto["nombre"] = nuevo_nombre
        self.arbol.SetItemText(nodo, self._etiqueta_nodo(proyecto, self._nivel_nodo(nodo)))
        reproducir(SUCCESS)
        self._anunciar_estado(f"Nombre guardado: {nuevo_nombre}")

    def _al_marcar_categoria(self, evento):
        """Actualiza las categorías del proyecto al marcar una casilla."""
        proyecto = self._proyecto_seleccionado()
        if proyecto:
            self._guardar_categorias_actuales(proyecto)

    def _al_desmarcar_categoria(self, evento):
        """Actualiza las categorías del proyecto al desmarcar una casilla."""
        proyecto = self._proyecto_seleccionado()
        if proyecto:
            self._guardar_categorias_actuales(proyecto)

    def _guardar_categorias_actuales(self, proyecto: dict):
        """Lee el estado de todas las casillas y persiste la lista de categorías."""
        categorias = [
            self.lista_cats.GetItemText(i)
            for i in range(self.lista_cats.GetItemCount())
            if self.lista_cats.IsItemChecked(i)
        ]
        self._gestor.cambiar_tipo(proyecto["id"], categorias)
        proyecto["tipo"] = categorias
        nodo = self.arbol.GetSelection()
        if nodo and nodo.IsOk():
            self.arbol.SetItemText(nodo, self._etiqueta_nodo(proyecto, self._nivel_nodo(nodo)))

    # ================================================================== #
    # Gestión de archivos TXT asociados
    # ================================================================== #

    def _al_añadir_txt(self, evento):
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            reproducir(ERROR)
            wx.MessageBox(
                "Selecciona primero un proyecto.",
                "Sin selección", wx.OK | wx.ICON_WARNING
            )
            return
        reproducir(OPEN_FOLDER)
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
        proyecto_actualizado = self._gestor.obtener_proyecto(proyecto["id"])
        if proyecto_actualizado:
            self._actualizar_lista_archivos(proyecto_actualizado)

    def _al_quitar_txt(self, evento):
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            return
        idx = self.lista_archivos.GetFirstSelected()
        if idx == -1:
            reproducir(ERROR)
            wx.MessageBox(
                "Selecciona primero un archivo en la lista para quitarlo.",
                "Sin selección", wx.OK | wx.ICON_WARNING
            )
            return
        ruta = self.lista_archivos.GetItem(idx, 1).GetText()
        self._gestor.desasociar_archivo(ruta)
        reproducir(CLEAR)
        proyecto_actualizado = self._gestor.obtener_proyecto(proyecto["id"])
        if proyecto_actualizado:
            self._actualizar_lista_archivos(proyecto_actualizado)

    # ================================================================== #
    # Crear proyectos nuevos
    # ================================================================== #

    def _pedir_nombre_y_tipo(self, titulo_dialogo: str) -> tuple[str, str] | None:
        dlg = wx.Dialog(self, title=titulo_dialogo)
        panel = wx.Panel(dlg)
        sz = wx.BoxSizer(wx.VERTICAL)

        lbl_n = wx.StaticText(panel, label="Nombre del proyecto:")
        txt_n = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        txt_n.SetHelpText("Escribe el nombre del nuevo proyecto. Campo obligatorio.")
        lbl_t = wx.StaticText(
            panel,
            label="Categorías (puedes elegir varias):",
        )
        lista_t = ListaCategorias(panel)
        lista_t.SetMinSize((-1, 180))
        lista_t.SetHelpText(
            "Categorías del proyecto. Usa las flechas para moverte y Espacio para marcar "
            "o desmarcar. Puedes asignar varias categorías al mismo tiempo."
        )
        btn_ok     = wx.Button(panel, wx.ID_OK,     label="Crear proyecto")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, label="Cancelar")
        sz_btn = wx.BoxSizer(wx.HORIZONTAL)
        sz_btn.Add(btn_ok, 0, wx.RIGHT, 8)
        sz_btn.Add(btn_cancel, 0)

        sz.Add(lbl_n,   0, wx.ALL, 6)
        sz.Add(txt_n,   0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sz.Add(lbl_t,   0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sz.Add(lista_t, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sz.Add(sz_btn,  0, wx.ALIGN_RIGHT | wx.ALL, 6)
        panel.SetSizer(sz)

        dlg_sz = wx.BoxSizer(wx.VERTICAL)
        dlg_sz.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sz)
        dlg.Fit()
        wx.CallAfter(txt_n.SetFocus)
        reproducir(CLICK)

        resultado = dlg.ShowModal()
        nombre = txt_n.GetValue().strip()
        tipos  = [
            lista_t.GetItemText(i)
            for i in range(lista_t.GetItemCount())
            if lista_t.IsItemChecked(i)
        ]
        dlg.Destroy()

        if resultado != wx.ID_OK or not nombre:
            return None
        return nombre, tipos

    def _al_nuevo_raiz(self, evento):
        resultado = self._pedir_nombre_y_tipo("Nuevo proyecto raíz")
        if resultado is None:
            return
        nombre, tipo = resultado
        nuevo_id = self._gestor.crear_proyecto(nombre, tipo, padre_id=None)
        reproducir(SUCCESS)
        self._cargar_arbol(seleccionar_id=nuevo_id)
        self._anunciar_estado(f"Proyecto «{nombre}» creado.")

    def _al_nuevo_hijo(self, evento):
        proyecto_padre = self._proyecto_seleccionado()
        if proyecto_padre is None:
            reproducir(ERROR)
            wx.MessageBox(
                "Selecciona primero el proyecto padre en la lista.",
                "Sin selección", wx.OK | wx.ICON_WARNING
            )
            return
        resultado = self._pedir_nombre_y_tipo(
            f"Nuevo subproyecto de «{proyecto_padre['nombre']}»"
        )
        if resultado is None:
            return
        nombre, tipo = resultado
        nuevo_id = self._gestor.crear_proyecto(nombre, tipo, padre_id=proyecto_padre["id"])
        reproducir(SUCCESS)
        self._cargar_arbol(seleccionar_id=nuevo_id)
        self._anunciar_estado(f"Subproyecto «{nombre}» creado dentro de «{proyecto_padre['nombre']}».")

    # ================================================================== #
    # Restaurar proyectos eliminados (papelera)
    # ================================================================== #

    def _al_restaurar(self, raiz_id: str):
        """Restaura un proyecto desde la papelera al árbol."""
        ok = self._gestor.restaurar_proyecto(raiz_id)
        if ok:
            reproducir(SUCCESS)
            self._cargar_arbol(seleccionar_id=raiz_id)
            self._anunciar_estado("Proyecto restaurado correctamente.")
        else:
            reproducir(ERROR)
            wx.MessageBox(
                "No se encontró el proyecto en la papelera.",
                "Error al restaurar", wx.OK | wx.ICON_WARNING
            )

    def _al_vaciar_papelera(self, evento):
        """Elimina definitivamente todos los proyectos en la papelera."""
        papelera = self._gestor.listar_papelera()
        n = len(papelera)
        if n == 0:
            return
        reproducir(CLICK)
        dlg = wx.MessageDialog(
            self,
            f"¿Eliminar definitivamente {n} proyecto(s) de la papelera?\n\n"
            "Esta acción no se puede deshacer.",
            "Vaciar papelera",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        resp = dlg.ShowModal()
        dlg.Destroy()
        if resp == wx.ID_YES:
            self._gestor.vaciar_papelera()
            reproducir(CLEAR)
            self._anunciar_estado("Papelera vaciada.")

    # ================================================================== #
    # Eliminar proyecto
    # ================================================================== #

    def _al_eliminar(self, evento):
        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            reproducir(ERROR)
            wx.MessageBox(
                "Selecciona un proyecto en la lista para eliminarlo.",
                "Sin selección", wx.OK | wx.ICON_WARNING
            )
            return
        tiene_hijos = bool(self._gestor.listar_hijos(proyecto["id"]))
        mensaje = (
            f"¿Eliminar «{proyecto['nombre']}» y todos sus subproyectos?\n\n"
            "Puedes recuperarlos después desde el menú contextual."
            if tiene_hijos else
            f"¿Eliminar el proyecto «{proyecto['nombre']}»?\n\n"
            "Puedes recuperarlo después desde el menú contextual."
        )
        reproducir(CLICK)
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
            reproducir(CLEAR)
        except Exception as e:
            reproducir(ERROR)
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

    def _nivel_nodo(self, nodo) -> int:
        """Devuelve la profundidad del nodo (1 = raíz visible)."""
        nivel = 1
        actual = nodo
        raiz = self.arbol.GetRootItem()
        while True:
            padre = self.arbol.GetItemParent(actual)
            if not padre or not padre.IsOk() or padre == raiz:
                break
            nivel += 1
            actual = padre
        return nivel

    def _estado_proyecto(self, proyecto: dict) -> str:
        """
        Devuelve 'Grabado' si existe al menos un archivo .mp3/.wav generado
        para este proyecto; 'Pendiente' si no.
        Comprueba:
          1. Carpeta Grabaciones_Epub-TTS/<nombre_proyecto>/grabaciones/ (salida de grabador_audio).
          2. Archivos .mp3/.wav hermanos de cualquier TXT asociado.
        """
        import re
        from app.config_rutas import RAIZ

        def _limpiar(nombre):
            return re.sub(r'[<>:"/\\|?*\n\r]', '_', nombre).strip() or "_"

        nombre = proyecto.get("nombre", "")
        carpeta_audio = os.path.join(RAIZ, "Grabaciones_Epub-TTS", _limpiar(nombre), "grabaciones")
        if os.path.isdir(carpeta_audio):
            for _, _, archivos in os.walk(carpeta_audio):
                if any(f.endswith(('.mp3', '.wav')) for f in archivos):
                    return "Grabado"

        for ruta_txt in proyecto.get("archivos", []):
            base = os.path.splitext(ruta_txt)[0]
            if os.path.exists(base + ".mp3") or os.path.exists(base + ".wav"):
                return "Grabado"

        return "Pendiente"

    def _etiqueta_nodo(self, proyecto: dict, nivel: int) -> str:
        """Devuelve el texto del nodo tal como NVDA lo leerá al navegar."""
        estado = self._estado_proyecto(proyecto)
        tipos = proyecto.get("tipo", [])
        if isinstance(tipos, str):
            tipos = [tipos]
        tipo_str = ", ".join(tipos) if tipos else "Sin categoría"
        etiqueta = f"{proyecto['nombre']} [{tipo_str}] — {estado} — Nivel {nivel}"
        padre_id = proyecto.get("padre")
        if padre_id:
            padre = self._gestor.obtener_proyecto(padre_id)
            if padre:
                etiqueta += f" — Subproyecto de: {padre['nombre']}"
        return etiqueta

    def _abrir_carpeta_proyecto(self):
        """Ctrl+Intro: abre en el Explorador la carpeta de audio o TXT del proyecto."""
        import re
        from app.config_rutas import RAIZ

        proyecto = self._proyecto_seleccionado()
        if proyecto is None:
            self._anunciar_estado("Selecciona primero un proyecto.")
            return
        reproducir(OPEN_FOLDER)

        def _limpiar(nombre):
            return re.sub(r'[<>:"/\\|?*\n\r]', '_', nombre).strip() or "_"

        nombre = proyecto.get("nombre", "")
        # Intenta abrir /grabaciones/ si existe; si no, la raíz del proyecto
        carpeta_libro = os.path.join(RAIZ, "Grabaciones_Epub-TTS", _limpiar(nombre))
        carpeta_audio = os.path.join(carpeta_libro, "grabaciones")
        if os.path.isdir(carpeta_audio):
            carpeta = carpeta_audio
        elif os.path.isdir(carpeta_libro):
            carpeta = carpeta_libro
        elif proyecto.get("archivos"):
            carpeta = os.path.dirname(proyecto["archivos"][0])
        else:
            self._anunciar_estado("No hay carpeta asociada a este proyecto.")
            return

        try:
            if os.name == "nt":
                os.startfile(carpeta)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", carpeta])
            self._anunciar_estado(f"Abriendo carpeta: {nombre}")
        except Exception as e:
            self._anunciar_estado(f"No se pudo abrir la carpeta: {e}")

    def actualizar_nombre_proyecto(self, proyecto_id: str, nuevo_nombre: str):
        """
        Actualiza en tiempo real el nodo del árbol cuando el nombre del proyecto
        cambia desde PestanaGrabacion (campo Título al perder el foco).
        Llama a GestorProyectos.renombrar_proyecto antes de invocar este método.
        """
        for nodo, pid in self._mapa_nodos.items():
            if pid == proyecto_id:
                proyecto = self._gestor.obtener_proyecto(proyecto_id)
                if proyecto:
                    nivel = self._nivel_nodo(nodo)
                    self.arbol.SetItemText(nodo, self._etiqueta_nodo(proyecto, nivel))
                break

    def _anunciar_estado(self, mensaje: str):
        """Actualiza la barra de estado y el título de la ventana temporalmente."""
        self.lbl_estado.SetLabel(mensaje)
        self.SetTitle(f"Gestión de Proyectos — {mensaje}")
        wx.CallLater(4000, self._restaurar_titulo)

    def _restaurar_titulo(self):
        if self:
            self.SetTitle("Gestión de Proyectos — Epub TTS")

    def _worker_tts(self):
        """
        Hilo persistente con una sola instancia de pyttsx3.
        Consume mensajes de _cola_tts; None como señal de parada.
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
        except Exception:
            return
        while True:
            texto = self._cola_tts.get()
            if texto is None:
                break
            try:
                engine.say(texto)
                engine.runAndWait()
            except Exception:
                pass

    def _hablar(self, texto: str):
        """
        Encola un texto para verbalizarlo con pyttsx3.
        Descarta mensajes pendientes para que NVDA oiga siempre el más reciente.
        """
        # Vaciar backlog (p.ej. al mover nodos rápidamente)
        while not self._cola_tts.empty():
            try:
                self._cola_tts.get_nowait()
            except queue.Empty:
                break
        self._cola_tts.put(texto)

    def _al_cerrar(self, evento):
        """Al cerrar, devuelve el foco exactamente al control que lo tenía antes."""
        # Desconectar el evento del árbol ANTES de destruir la ventana.
        # EVT_TREE_SEL_CHANGED puede dispararse durante la destrucción (deselección
        # automática de nodos) y acceder a objetos C++ ya liberados.
        # Detener el hilo TTS limpiamente
        self._cola_tts.put(None)

        try:
            self.arbol.Unbind(wx.EVT_TREE_SEL_CHANGED)
        except Exception:
            pass

        if self._foco_previo:
            try:
                if self._foco_previo.IsShown():
                    wx.CallAfter(self._foco_previo.SetFocus)
                    evento.Skip()
                    return
            except Exception:
                pass
        if self._frame_principal and self._frame_principal.IsShown():
            wx.CallAfter(self._frame_principal.SetFocus)
        evento.Skip()
# ANCLAJE_FIN: VENTANA_PROYECTOS
