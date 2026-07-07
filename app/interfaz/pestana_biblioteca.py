# ANCLAJE_INICIO: DEPENDENCIAS_BIBLIOTECA
import wx
import os
import re
import json
import logging
import threading

from app.config_rutas import ruta_config, CONFIG_DIR
from app.motor.gestor_biblioteca import GestorBiblioteca
from app.motor.escaner_biblioteca import EscanerBiblioteca, confirmar_agrupamiento_por_carpeta
from app.motor.renombrador_biblioteca import (
    renombrar_libro_segun_metadatos,
    renombrar_pendientes_por_lote,
)
from app.motor.anunciador_voz import AnunciadorVoz
from app.motor.reproductor_sonidos import (
    reproducir, SUCCESS, ERROR, LIST_NAV, MOVE_UP, MOVE_DOWN, CLEAR,
)
# ANCLAJE_FIN: DEPENDENCIAS_BIBLIOTECA

logger = logging.getLogger(__name__)


def _clave_orden_natural(titulo: str):
    """
    Clave de orden "natural": compara los números como números, no como
    texto, para que "2" vaya antes que "10" (alfabéticamente "10" iría
    antes que "2"). Sin esto, libros con el número al principio del
    título (herencia frecuente del nombre de archivo original) aparecen
    en un orden que parece aleatorio en vez de secuencial.
    """
    partes = re.split(r'(\d+)', titulo.lower())
    return [int(parte) if parte.isdigit() else parte for parte in partes]


# ANCLAJE_INICIO: DIALOGO_NUEVA_CATEGORIA
class DialogoNuevaCategoria(wx.Dialog):
    """
    Diálogo único para crear una categoría, tanto raíz como subcategoría.
    Si hay una categoría seleccionada en el árbol al abrirlo, ofrece una
    casilla para crearla como subcategoría de esa — evita tener que
    elegir entre un botón (solo raíz) y un elemento de menú (solo sub)
    que hacían fácil confundir cuál usar.
    """

    def __init__(self, padre, nombre_categoria_padre):
        super().__init__(padre, title="Nueva categoría")
        self.crear_como_subcategoria = False
        self.nombre = ""

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Nombre de la nueva categoría:"), 0, wx.ALL, 5)
        self.txt_nombre = wx.TextCtrl(self)
        sizer.Add(self.txt_nombre, 0, wx.EXPAND | wx.ALL, 5)

        self.chk_subcategoria = wx.CheckBox(
            self, label=(
                f"Crear como subcategoría de «{nombre_categoria_padre}»"
                if nombre_categoria_padre else
                "Crear como subcategoría (selecciona antes una categoría en el árbol)"
            )
        )
        self.chk_subcategoria.SetValue(bool(nombre_categoria_padre))
        self.chk_subcategoria.Enable(bool(nombre_categoria_padre))
        sizer.Add(self.chk_subcategoria, 0, wx.ALL, 5)

        botones = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(botones, 0, wx.ALIGN_CENTER | wx.ALL, 8)

        self.SetSizer(sizer)
        self.Fit()
        self.Bind(wx.EVT_BUTTON, self.al_aceptar, id=wx.ID_OK)
        self.txt_nombre.SetFocus()

    def al_aceptar(self, evento):
        self.nombre = self.txt_nombre.GetValue().strip()
        if not self.nombre:
            wx.MessageBox("Escribe un nombre para la categoría.", "Nombre vacío", wx.OK | wx.ICON_WARNING)
            return
        self.crear_como_subcategoria = self.chk_subcategoria.GetValue()
        evento.Skip()
# ANCLAJE_FIN: DIALOGO_NUEVA_CATEGORIA


# ANCLAJE_INICIO: DEFINICION_PESTANA_BIBLIOTECA
class PestanaBiblioteca(wx.Panel):
    """
    Pestaña de la Biblioteca: importación, filtrado, árbol de categorías
    (géneros/subgéneros) y gestión de la colección de EPUB y PDF
    indexada en biblioteca.db.
    """

    def __init__(self, padre):
        super().__init__(padre)
        self.padre_notebook = padre

        self.gestor = GestorBiblioteca()
        self.escaner = None
        self._libros_actuales = []
        self._id_categoria_activa = None
        self._id_etiqueta_activa = None
        self._categoria_en_portapapeles = None

        self._configurar_interfaz()
        self._configurar_atajos()

        self._voz = AnunciadorVoz()
        self.Bind(wx.EVT_WINDOW_DESTROY, lambda e: (self._voz.detener(), e.Skip()))

        self._progreso_actual = (0, 0)
        self._timer_progreso = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.al_temporizador_progreso, self._timer_progreso)

        wx.CallAfter(self._cargar_arbol_categorias)
        wx.CallAfter(self._cargar_lista_etiquetas)
        wx.CallAfter(self._cargar_libros)

    # ── Construcción de la interfaz ─────────────────────────────────────────

    def _configurar_interfaz(self):
        sizer_principal = wx.BoxSizer(wx.HORIZONTAL)

        # ── Panel izquierdo: sub-pestañas Géneros / Sagas ────────────────
        # Categorías (árbol jerárquico) y etiquetas (lista plana) son
        # conceptos distintos y se guardan por separado, pero antes vivían
        # como dos controles apilados uno debajo del otro, lo que hacía
        # difícil ubicarlas mentalmente y obligaba a tabular de uno a otro.
        # Un sub-notebook las coloca en el mismo sitio de la pantalla,
        # alternando con Ctrl+RePág/Ctrl+AvPág (comportamiento nativo de
        # wx.Notebook), igual que ya alternas entre pestañas principales.
        self.subnotebook_izquierdo = wx.Notebook(self)

        panel_generos = wx.Panel(self.subnotebook_izquierdo)
        sizer_generos = wx.BoxSizer(wx.VERTICAL)
        self.arbol_categorias = wx.TreeCtrl(
            panel_generos,
            style=(
                wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE
                | wx.TR_HIDE_ROOT | wx.TR_EDIT_LABELS
            ),
        )
        self.arbol_categorias.SetHelpText(
            "Árbol de géneros y subgéneros. Flechas para navegar; seleccionar "
            "un nodo filtra la lista de libros por esa categoría (incluye "
            "subgéneros). F2 renombra, Supr elimina, Ctrl+X/Ctrl+V mueve un "
            "género bajo otro, Ctrl+Arriba/Ctrl+Abajo lo reordena entre sus "
            "hermanos, Menú o Shift+F10 para más opciones."
        )
        self.arbol_categorias.SetMinSize((220, 160))
        self.arbol_categorias.Bind(wx.EVT_TREE_SEL_CHANGED, self.al_seleccionar_categoria)
        self.arbol_categorias.Bind(wx.EVT_TREE_KEY_DOWN, self.al_tecla_arbol)
        self.arbol_categorias.Bind(wx.EVT_KEY_DOWN, self.al_tecla_arbol_raw)
        self.arbol_categorias.Bind(wx.EVT_TREE_END_LABEL_EDIT, self.al_fin_edicion_categoria)
        self.arbol_categorias.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self.al_clic_derecho_arbol)
        # EVT_TREE_ITEM_RIGHT_CLICK solo se dispara con clic de ratón — la
        # tecla Menú/Shift+F10 (como usa NVDA) genera EVT_CONTEXT_MENU, que
        # no estaba enlazado aquí. Por eso el árbol nunca mostraba su menú
        # propio por teclado, solo el genérico del sistema.
        self.arbol_categorias.Bind(wx.EVT_CONTEXT_MENU, self.al_menu_contextual_arbol)
        sizer_generos.Add(self.arbol_categorias, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_nueva_categoria = wx.Button(
            panel_generos, label="Nueva categoría... (F2 renombra, Supr elimina)"
        )
        self.btn_nueva_categoria.Bind(wx.EVT_BUTTON, self.al_nueva_categoria)
        sizer_generos.Add(self.btn_nueva_categoria, 0, wx.EXPAND | wx.ALL, 5)
        panel_generos.SetSizer(sizer_generos)
        self.subnotebook_izquierdo.AddPage(panel_generos, "Géneros")

        panel_sagas = wx.Panel(self.subnotebook_izquierdo)
        sizer_sagas = wx.BoxSizer(wx.VERTICAL)
        self.lista_etiquetas = wx.ListBox(panel_sagas)
        self.lista_etiquetas.SetHelpText(
            "Lista plana de etiquetas (sagas y colecciones personalizadas). "
            "Seleccionar una filtra la lista de libros por esa etiqueta. "
            "F2 renombra, Supr elimina."
        )
        self.lista_etiquetas.SetMinSize((220, 160))
        self.lista_etiquetas.Bind(wx.EVT_LISTBOX, self.al_seleccionar_etiqueta)
        self.lista_etiquetas.Bind(wx.EVT_KEY_DOWN, self.al_tecla_lista_etiquetas)
        self.lista_etiquetas.Bind(wx.EVT_CONTEXT_MENU, self.al_menu_contextual_etiquetas)
        sizer_sagas.Add(self.lista_etiquetas, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_nueva_etiqueta = wx.Button(
            panel_sagas, label="Nueva etiqueta... (F2 renombra, Supr elimina)"
        )
        self.btn_nueva_etiqueta.Bind(wx.EVT_BUTTON, self.al_nueva_etiqueta)
        sizer_sagas.Add(self.btn_nueva_etiqueta, 0, wx.EXPAND | wx.ALL, 5)
        panel_sagas.SetSizer(sizer_sagas)
        self.subnotebook_izquierdo.AddPage(panel_sagas, "Sagas y colecciones")

        self.subnotebook_izquierdo.Bind(
            wx.EVT_NOTEBOOK_PAGE_CHANGED, self.al_cambiar_subpestana_izquierda
        )
        # Ctrl+Av/RePág no cambia de subpestaña por sí solo: al estar el
        # subnotebook anidado dentro de una página del notebook principal,
        # ese notebook exterior intercepta la combinación antes de que
        # llegue aquí (por eso el notebook principal tampoco confía en el
        # manejo nativo y reimplementa su propio Ctrl+Tab a mano en
        # ventana_principal.py). Se captura aquí igual, a mano.
        self.subnotebook_izquierdo.Bind(wx.EVT_KEY_DOWN, self.al_tecla_subnotebook_izquierdo)

        sizer_principal.Add(self.subnotebook_izquierdo, 1, wx.EXPAND | wx.ALL, 5)

        # ── Panel derecho: filtros, lista (arriba) e importación (abajo) ──
        # Orden pensado para minimizar tabulaciones hasta lo que más se usa:
        # filtrar y leer la lista es la tarea constante; importar una
        # carpeta es una acción puntual, así que va al final.
        sizer_derecho = wx.BoxSizer(wx.VERTICAL)

        sizer_filtro = wx.BoxSizer(wx.HORIZONTAL)
        sizer_filtro.Add(
            wx.StaticText(self, label="Buscar por título o autor (Ctrl+F):"),
            0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5,
        )
        self.txt_filtro = wx.TextCtrl(self)
        self.txt_filtro.Bind(wx.EVT_TEXT, self.al_cambiar_filtro)
        sizer_filtro.Add(self.txt_filtro, 1, wx.ALL | wx.EXPAND, 5)
        sizer_derecho.Add(sizer_filtro, 0, wx.EXPAND)

        # en_pendientes/leyendo_ahora/leido son etapas mutuamente excluyentes
        # de un mismo libro, así que un combo de una sola selección evita
        # sugerir combinaciones que no tienen sentido. Favorito sí es
        # ortogonal al estado, por eso es una casilla aparte.
        sizer_filtro_estado = wx.BoxSizer(wx.HORIZONTAL)
        sizer_filtro_estado.Add(
            wx.StaticText(self, label="Estado:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5
        )
        self._ESTADOS_FILTRO = ["Todos", "Pendientes", "Leyendo ahora", "Leídos"]
        self.combo_estado = wx.Choice(self, choices=self._ESTADOS_FILTRO)
        self.combo_estado.SetSelection(0)
        self.combo_estado.Bind(wx.EVT_CHOICE, self.al_cambiar_filtro)
        sizer_filtro_estado.Add(self.combo_estado, 0, wx.ALL, 5)

        self.chk_favoritos = wx.CheckBox(self, label="Solo favoritos")
        self.chk_favoritos.Bind(wx.EVT_CHECKBOX, self.al_cambiar_filtro)
        sizer_filtro_estado.Add(self.chk_favoritos, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        sizer_derecho.Add(sizer_filtro_estado, 0)

        # Lista principal de libros
        self.lista_libros = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self.lista_libros.InsertColumn(0, "Título", width=320)
        self.lista_libros.InsertColumn(1, "Autor", width=200)
        self.lista_libros.InsertColumn(2, "Formato", width=80)
        self.lista_libros.InsertColumn(3, "Estado", width=160)
        self.lista_libros.Bind(wx.EVT_CONTEXT_MENU, self.al_menu_contextual)
        self.lista_libros.Bind(wx.EVT_KEY_DOWN, self.al_tecla_lista)
        sizer_derecho.Add(self.lista_libros, 1, wx.EXPAND | wx.ALL, 5)

        self.lbl_estado = wx.StaticText(self, label="")
        sizer_derecho.Add(self.lbl_estado, 0, wx.ALL, 5)

        # Botón de importación + barra de progreso (visual, oculta hasta escanear)
        sizer_importar = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_importar = wx.Button(self, label="Importar carpeta... (Ctrl+O)")
        self.btn_importar.Bind(wx.EVT_BUTTON, self.al_importar_carpeta)
        sizer_importar.Add(self.btn_importar, 0, wx.ALL, 5)
        self.barra_progreso = wx.Gauge(self, range=100)
        self.barra_progreso.Hide()
        sizer_importar.Add(self.barra_progreso, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_derecho.Add(sizer_importar, 0, wx.EXPAND)

        sizer_principal.Add(sizer_derecho, 3, wx.EXPAND)

        self.SetSizer(sizer_principal)

        # Tab desde el árbol/lista de etiquetas debe llegar directo a la
        # lista de libros — es lo que se usa constantemente — en vez de
        # pasar antes por los controles de filtro, que se usan mucho
        # menos y quedan más lejos en el orden natural de creación.
        self.lista_libros.MoveAfterInTabOrder(self.subnotebook_izquierdo)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador).
        self._anunciador = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1)
        )
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())
        self._temporizador_anuncio = None

    def _configurar_atajos(self):
        # Ctrl+O (apertura universal, contextual por pestaña) se gestiona a
        # nivel de VentanaPrincipal y llama a al_importar_carpeta() desde
        # allí — no se duplica aquí para no pisar el atajo global.
        id_buscar = wx.NewIdRef()
        id_info = wx.NewIdRef()
        id_favorito = wx.NewIdRef()

        self.Bind(wx.EVT_MENU, lambda e: self.txt_filtro.SetFocus(), id=id_buscar)
        self.Bind(wx.EVT_MENU, self.al_anunciar_info_libro, id=id_info)
        self.Bind(wx.EVT_MENU, self.al_alternar_favorito, id=id_favorito)

        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('F'), id_buscar),
            (wx.ACCEL_CTRL, ord('I'), id_info),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('F'), id_favorito),
        ]))

    def al_cambiar_subpestana_izquierda(self, evento):
        # Igual que el notebook principal (ver al_cambiar_pestana en
        # ventana_principal.py): cambiar de pestaña NO debe mover el foco
        # a ningún control de su contenido. El foco se queda en la propia
        # pestaña — así se puede seguir recorriendo con flechas o
        # Ctrl+Av/RePág sin que NVDA salte al árbol o a la lista en cada
        # cambio. Entrar al contenido sigue siendo un Tab explícito.
        evento.Skip()

    def al_tecla_subnotebook_izquierdo(self, evento):
        codigo = evento.GetKeyCode()
        if evento.ControlDown() and codigo in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            self.subnotebook_izquierdo.AdvanceSelection(codigo == wx.WXK_PAGEDOWN)
            return
        evento.Skip()

    # ── Propiedades para Tab cíclico (usadas por ventana_principal.py) ──────

    @property
    def primer_control(self):
        return self.arbol_categorias

    @property
    def ultimo_control(self):
        return self.btn_importar

    # ── Anuncios de accesibilidad ────────────────────────────────────────────

    def _anunciar(self, texto):
        control_previo = wx.Window.FindFocus()

        def _restaurar_foco():
            # Solo devuelve el foco si sigue en el anunciador oculto — si
            # el usuario ya navegó a otro control mientras tanto (por
            # ejemplo, pulsando otro atajo o moviéndose con flechas antes
            # de que pasaran los 300ms), forzar aquí el foco de vuelta a
            # control_previo se lo quitaría de las manos sin que lo pidiera,
            # obligando a insistir con flechas arriba/abajo para que el
            # foco "se quedara quieto" — exactamente el síntoma reportado.
            if wx.Window.FindFocus() is self._anunciador and control_previo:
                control_previo.SetFocus()

        # Si ya había un anuncio pendiente de restaurar el foco (por
        # ejemplo, dos atajos de estado pulsados en sucesión rápida), se
        # cancela — si no, el primero podía disparar su restauración
        # DESPUÉS de que el segundo ya hubiera puesto el nuevo texto,
        # cortando el anuncio del segundo mensaje a mitad de lectura.
        if self._temporizador_anuncio is not None and self._temporizador_anuncio.IsRunning():
            self._temporizador_anuncio.Stop()

        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()
        # 450ms en vez de 300: con el foco ya asentado de verdad (antes se
        # perdía y recuperaba con las peleas de foco), NVDA necesita algo
        # más de margen para terminar de leer mensajes de estado más
        # largos ("Quitado de leyendo ahora.") antes de que se le devuelva
        # el foco a la lista.
        self._temporizador_anuncio = wx.CallLater(450, _restaurar_foco)

    # ── Árbol de categorías (jerárquico) ─────────────────────────────────────
    #
    # Cada nodo guarda una tupla (tipo, id) en SetItemData:
    #   ("todas", None)      → sin filtro de categoría
    #   ("categoria", id)    → género/subgénero

    def _cargar_arbol_categorias(self, id_categoria_seleccionar=None):
        self.arbol_categorias.Freeze()
        self.arbol_categorias.DeleteAllItems()
        raiz = self.arbol_categorias.AddRoot("Categorías")

        nodo_todas = self.arbol_categorias.AppendItem(raiz, "(Todas las categorías)")
        self.arbol_categorias.SetItemData(nodo_todas, ("todas", None))

        nodo_a_seleccionar = [nodo_todas]
        conteos = self.gestor.contar_libros_por_categoria()
        self._construir_nodos_categoria(raiz, None, id_categoria_seleccionar, nodo_a_seleccionar, conteos)

        self.arbol_categorias.ExpandAll()
        self.arbol_categorias.Thaw()
        self.arbol_categorias.SelectItem(nodo_a_seleccionar[0])

    def _construir_nodos_categoria(
        self, nodo_padre, id_categoria_padre, id_buscado, resultado_ref, conteos
    ):
        for categoria in self.gestor.listar_categorias_hijas(id_categoria_padre):
            total = conteos.get(categoria["id"], 0)
            etiqueta = f"{categoria['nombre']} ({total} libro(s))"
            nodo = self.arbol_categorias.AppendItem(nodo_padre, etiqueta)
            self.arbol_categorias.SetItemData(nodo, ("categoria", categoria["id"]))
            if id_buscado is not None and categoria["id"] == id_buscado:
                resultado_ref[0] = nodo
            self._construir_nodos_categoria(nodo, categoria["id"], id_buscado, resultado_ref, conteos)

    def _dato_nodo_seleccionado(self):
        # EVT_TREE_SEL_CHANGED puede dispararse durante el cierre de la app,
        # después de que el árbol ya fue destruido (comportamiento conocido
        # de wxPython). Sin esta guarda, el evento residual lanza
        # RuntimeError en bucle y bloquea el cierre — mismo problema ya
        # resuelto en ventana_proyectos.py para su propio árbol.
        try:
            nodo = self.arbol_categorias.GetSelection()
        except RuntimeError:
            return ("todas", None)
        if not nodo.IsOk():
            return ("todas", None)
        return self.arbol_categorias.GetItemData(nodo)

    def _categoria_seleccionada_id(self):
        tipo, valor = self._dato_nodo_seleccionado()
        return valor if tipo == "categoria" else None

    def al_seleccionar_categoria(self, evento):
        if self.arbol_categorias is None:
            return
        self._id_categoria_activa = self._categoria_seleccionada_id()
        self._cargar_libros()
        evento.Skip()

    def al_clic_derecho_arbol(self, evento):
        nodo = evento.GetItem()
        if nodo and nodo.IsOk():
            self.arbol_categorias.SelectItem(nodo)
        self.al_menu_contextual_arbol(evento)

    def al_tecla_arbol(self, evento):
        try:
            codigo = evento.GetKeyCode()
            if codigo in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
                reproducir(LIST_NAV)
            if evento.ControlDown() and codigo == wx.WXK_UP:
                self._mover_categoria_seleccionada(-1)
            elif evento.ControlDown() and codigo == wx.WXK_DOWN:
                self._mover_categoria_seleccionada(1)
            elif codigo == wx.WXK_F2:
                if self._categoria_seleccionada_id() is not None:
                    self.arbol_categorias.EditLabel(self.arbol_categorias.GetSelection())
            elif codigo == wx.WXK_DELETE:
                self.al_eliminar_categoria(evento)
            else:
                evento.Skip()
        except RuntimeError:
            pass

    def _mover_categoria_seleccionada(self, direccion):
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            self._anunciar("Selecciona primero un género o subgénero para moverlo.")
            return
        if self.gestor.mover_categoria(id_categoria, direccion):
            reproducir(SUCCESS)
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_categoria)
        else:
            self._anunciar("Ya está en ese extremo, no se puede mover más.")

    def al_tecla_arbol_raw(self, evento):
        codigo = evento.GetKeyCode()
        ctrl = evento.ControlDown()
        if ctrl and codigo == ord('X'):
            self.al_cortar_categoria(evento)
            return
        if ctrl and codigo == ord('V'):
            self.al_pegar_categoria(evento)
            return
        if codigo == getattr(wx, "WXK_WINDOWS_MENU", 348):
            self.al_menu_contextual_arbol(evento)
            return
        if codigo == wx.WXK_F10 and evento.ShiftDown():
            self.al_menu_contextual_arbol(evento)
            return
        evento.Skip()

    def al_fin_edicion_categoria(self, evento):
        if evento.IsEditCancelled():
            evento.Skip()
            return
        nuevo_nombre = evento.GetLabel().strip()
        nodo = evento.GetItem()
        tipo, valor = self.arbol_categorias.GetItemData(nodo)
        if not nuevo_nombre or tipo != "categoria":
            evento.Veto()
            return

        if self.gestor.renombrar_categoria(valor, nuevo_nombre):
            reproducir(SUCCESS)
            self._voz.hablar(f"Categoría renombrada a {nuevo_nombre}.")
            self._cargar_libros()
        else:
            evento.Veto()
            reproducir(ERROR)
            wx.MessageBox(
                "Ya existe una categoría con ese nombre en el mismo nivel.",
                "No se pudo renombrar", wx.OK | wx.ICON_WARNING,
            )
        evento.Skip()

    def al_nueva_categoria(self, evento):
        id_padre_actual = self._categoria_seleccionada_id()
        nombre_padre = (
            self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
            if id_padre_actual is not None else None
        )
        dlg = DialogoNuevaCategoria(self, nombre_padre)
        if dlg.ShowModal() == wx.ID_OK:
            id_padre_final = id_padre_actual if dlg.crear_como_subcategoria else None
            id_nueva = self.gestor.crear_categoria(dlg.nombre, id_padre_final)
            reproducir(SUCCESS)
            if id_padre_final is not None:
                self._voz.hablar(f"Subcategoría {dlg.nombre} creada dentro de {nombre_padre}.")
            else:
                self._voz.hablar(f"Categoría {dlg.nombre} creada.")
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_nueva)
        dlg.Destroy()

    def al_eliminar_categoria(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            return
        nombre = self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
        if wx.MessageBox(
            f"¿Eliminar la categoría «{nombre}» y sus subcategorías?\n\n"
            "Los libros no se eliminan, solo dejan de pertenecer a esta categoría.",
            "Eliminar categoría", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.eliminar_categoria(id_categoria)
        self._id_categoria_activa = None
        reproducir(SUCCESS)
        self._voz.hablar(f"Categoría {nombre} eliminada.")
        self._cargar_arbol_categorias()
        self._cargar_libros()

    def al_cortar_categoria(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            return
        self._categoria_en_portapapeles = id_categoria
        reproducir(CLEAR)
        nombre = self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
        self._voz.hablar(
            f"{nombre} cortada. Selecciona el destino y pulsa Control V, o Escape para cancelar."
        )

    def al_pegar_categoria(self, evento):
        if self._categoria_en_portapapeles is None:
            self._voz.hablar("No hay ninguna categoría cortada.")
            return
        destino = self._categoria_seleccionada_id()
        if self.gestor.reparentar_categoria(self._categoria_en_portapapeles, destino):
            reproducir(SUCCESS)
            id_movida = self._categoria_en_portapapeles
            self._categoria_en_portapapeles = None
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_movida)
            self._voz.hablar("Categoría movida.")
        else:
            reproducir(ERROR)
            self._voz.hablar("No se puede mover ahí: crearía un ciclo o el destino es la misma categoría.")

    def al_menu_contextual_arbol(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        menu = wx.Menu()

        item_nueva = menu.Append(wx.ID_ANY, "Nueva categoría o subcategoría...")
        self.Bind(wx.EVT_MENU, self.al_nueva_categoria, item_nueva)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar\tF2")
        item_renombrar.Enable(id_categoria is not None)
        self.Bind(
            wx.EVT_MENU,
            lambda e: self.arbol_categorias.EditLabel(self.arbol_categorias.GetSelection()),
            item_renombrar,
        )

        item_mover_arriba = menu.Append(wx.ID_ANY, "Mover arriba (Ctrl+Arriba)")
        item_mover_arriba.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, lambda e: self._mover_categoria_seleccionada(-1), item_mover_arriba)

        item_mover_abajo = menu.Append(wx.ID_ANY, "Mover abajo (Ctrl+Abajo)")
        item_mover_abajo.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, lambda e: self._mover_categoria_seleccionada(1), item_mover_abajo)

        item_cortar = menu.Append(wx.ID_ANY, "Cortar (Ctrl+X)")
        item_cortar.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, self.al_cortar_categoria, item_cortar)

        item_pegar = menu.Append(wx.ID_ANY, "Pegar aquí (Ctrl+V)")
        item_pegar.Enable(self._categoria_en_portapapeles is not None)
        self.Bind(wx.EVT_MENU, self.al_pegar_categoria, item_pegar)

        menu.AppendSeparator()

        item_eliminar = menu.Append(wx.ID_ANY, "Eliminar...\tSupr")
        item_eliminar.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, self.al_eliminar_categoria, item_eliminar)

        self._anadir_ayuda_y_salir(menu)
        self.arbol_categorias.PopupMenu(menu)
        menu.Destroy()

    # ── Lista de etiquetas (plana) ────────────────────────────────────────────

    def _cargar_lista_etiquetas(self, id_etiqueta_seleccionar=None):
        self.lista_etiquetas.Freeze()
        self.lista_etiquetas.Clear()
        self._etiquetas_indice = [{"id": None, "nombre": "(Todas las etiquetas)"}]
        self._etiquetas_indice.extend(dict(e) for e in self.gestor.listar_etiquetas())
        for etiqueta in self._etiquetas_indice:
            self.lista_etiquetas.Append(etiqueta["nombre"])
        indice_seleccionar = 0
        if id_etiqueta_seleccionar is not None:
            for i, etiqueta in enumerate(self._etiquetas_indice):
                if etiqueta["id"] == id_etiqueta_seleccionar:
                    indice_seleccionar = i
                    break
        self.lista_etiquetas.Thaw()
        if self._etiquetas_indice:
            self.lista_etiquetas.SetSelection(indice_seleccionar)
            self._id_etiqueta_activa = self._etiquetas_indice[indice_seleccionar]["id"]

    def _etiqueta_seleccionada(self):
        indice = self.lista_etiquetas.GetSelection()
        if indice == wx.NOT_FOUND or indice >= len(getattr(self, "_etiquetas_indice", [])):
            return None
        etiqueta = self._etiquetas_indice[indice]
        return None if etiqueta["id"] is None else etiqueta

    def al_seleccionar_etiqueta(self, evento):
        etiqueta = self._etiqueta_seleccionada()
        self._id_etiqueta_activa = etiqueta["id"] if etiqueta else None
        self._cargar_libros()
        evento.Skip()

    def al_tecla_lista_etiquetas(self, evento):
        codigo = evento.GetKeyCode()
        if codigo in (wx.WXK_UP, wx.WXK_DOWN):
            reproducir(LIST_NAV)
        if codigo == wx.WXK_F2:
            self.al_renombrar_etiqueta_seleccionada()
            return
        if codigo == wx.WXK_DELETE:
            self.al_eliminar_etiqueta_seleccionada()
            return
        evento.Skip()

    def al_renombrar_etiqueta_seleccionada(self):
        etiqueta = self._etiqueta_seleccionada()
        if etiqueta is None:
            self._voz.hablar("Selecciona primero una etiqueta para renombrarla.")
            return
        dlg = wx.TextEntryDialog(
            self, "Nuevo nombre de la etiqueta:", "Renombrar etiqueta", value=etiqueta["nombre"]
        )
        if dlg.ShowModal() == wx.ID_OK:
            nuevo_nombre = dlg.GetValue().strip()
            if nuevo_nombre and self.gestor.renombrar_etiqueta(etiqueta["id"], nuevo_nombre):
                reproducir(SUCCESS)
                self._voz.hablar(f"Etiqueta renombrada a {nuevo_nombre}.")
                self._cargar_lista_etiquetas(id_etiqueta_seleccionar=etiqueta["id"])
                self._cargar_libros()
            elif nuevo_nombre:
                reproducir(ERROR)
                wx.MessageBox(
                    "Ya existe una etiqueta con ese nombre.", "No se pudo renombrar",
                    wx.OK | wx.ICON_WARNING,
                )
        dlg.Destroy()

    def al_eliminar_etiqueta_seleccionada(self):
        etiqueta = self._etiqueta_seleccionada()
        if etiqueta is None:
            return
        if wx.MessageBox(
            f"¿Eliminar la etiqueta «{etiqueta['nombre']}»?\n\n"
            "Los libros no se eliminan, solo dejan de tener esta etiqueta.",
            "Eliminar etiqueta", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.eliminar_etiqueta(etiqueta["id"])
        reproducir(SUCCESS)
        self._voz.hablar(f"Etiqueta {etiqueta['nombre']} eliminada.")
        self._cargar_lista_etiquetas()
        self._cargar_libros()

    def al_nueva_etiqueta(self, evento):
        dlg = wx.TextEntryDialog(self, "Nombre de la nueva etiqueta:", "Nueva etiqueta")
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                id_nueva = self.gestor.crear_etiqueta(nombre)
                reproducir(SUCCESS)
                self._voz.hablar(f"Etiqueta {nombre} creada.")
                self._cargar_lista_etiquetas(id_etiqueta_seleccionar=id_nueva)
        dlg.Destroy()

    def al_menu_contextual_etiquetas(self, evento):
        etiqueta = self._etiqueta_seleccionada()
        menu = wx.Menu()

        item_nueva = menu.Append(wx.ID_ANY, "Nueva etiqueta...")
        self.Bind(wx.EVT_MENU, self.al_nueva_etiqueta, item_nueva)

        if etiqueta is not None:
            libros_de_la_etiqueta = self.gestor.buscar_libros(id_etiqueta=etiqueta["id"])
            etiqueta_menu = f"Asignar categoría a los {len(libros_de_la_etiqueta)} libro(s) de esta etiqueta"
            estado_menu = f"Marcar los {len(libros_de_la_etiqueta)} libro(s) de esta etiqueta como"
            if libros_de_la_etiqueta:
                menu.AppendSubMenu(
                    self.construir_menu_asignar_categoria_masivo(libros_de_la_etiqueta), etiqueta_menu
                )
                menu.AppendSubMenu(
                    self._construir_menu_marcar_estado_masivo(libros_de_la_etiqueta), estado_menu
                )
            else:
                menu.Append(wx.ID_ANY, etiqueta_menu).Enable(False)
                menu.Append(wx.ID_ANY, estado_menu).Enable(False)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar\tF2")
        item_renombrar.Enable(etiqueta is not None)
        self.Bind(wx.EVT_MENU, lambda e: self.al_renombrar_etiqueta_seleccionada(), item_renombrar)

        item_eliminar = menu.Append(wx.ID_ANY, "Eliminar...\tSupr")
        item_eliminar.Enable(etiqueta is not None)
        self.Bind(wx.EVT_MENU, lambda e: self.al_eliminar_etiqueta_seleccionada(), item_eliminar)

        self._anadir_ayuda_y_salir(menu)
        self.lista_etiquetas.PopupMenu(menu)
        menu.Destroy()

    # ── Carga y filtrado de la lista ─────────────────────────────────────────

    def _cargar_libros(self):
        estado = self._ESTADOS_FILTRO[self.combo_estado.GetSelection()]
        libros = self.gestor.buscar_libros(
            texto=self.txt_filtro.GetValue().strip(),
            id_categoria=self._id_categoria_activa,
            id_etiqueta=self._id_etiqueta_activa,
            solo_favoritos=self.chk_favoritos.GetValue(),
            solo_pendientes=(estado == "Pendientes"),
            solo_leyendo=(estado == "Leyendo ahora"),
            solo_leidos=(estado == "Leídos"),
        )
        if self._id_etiqueta_activa is None and self._id_categoria_activa is None:
            # Sin etiqueta ni categoría activa, buscar_libros() ordena
            # alfabéticamente por título — pero muchos libros heredan un
            # número al principio del título original del archivo, y un
            # orden alfabético puro coloca "10" antes que "2". El orden
            # natural evita eso. Con etiqueta o categoría activa, se
            # respeta el orden de saga/género tal cual lo devuelve la
            # base de datos (el que se fue añadiendo).
            libros = sorted(libros, key=lambda l: _clave_orden_natural(l["titulo"]))
        self._libros_actuales = libros

        autores_por_libro = self.gestor.obtener_autores_por_libros([libro["id"] for libro in libros])

        self.lista_libros.Freeze()
        self.lista_libros.DeleteAllItems()
        for indice, libro in enumerate(libros):
            nombres_autores = ", ".join(autores_por_libro.get(libro["id"], [])) or "—"
            estado_txt = self._describir_estado(libro)

            self.lista_libros.InsertItem(indice, libro["titulo"])
            self.lista_libros.SetItem(indice, 1, nombres_autores)
            self.lista_libros.SetItem(indice, 2, libro["formato"].upper())
            self.lista_libros.SetItem(indice, 3, estado_txt)
        self.lista_libros.Thaw()
        # Refresh() explícito: en algunos entornos Windows, Thaw() tras un
        # DeleteAllItems()+recarga masiva dentro de un ciclo Freeze() no
        # repinta el control hasta un evento externo (redimensionar,
        # cambiar de ventana...), aunque los datos internos (GetItemCount)
        # ya sean correctos — se ha visto la lista "vacía" o mostrando solo
        # parte de los libros hasta reiniciar la app, sin ningún error.
        self.lista_libros.Refresh()

        self.lbl_estado.SetLabel(f"{len(libros)} libro(s) en la biblioteca.")

    @staticmethod
    def _describir_estado(libro) -> str:
        partes = []
        if libro["favorito"]:
            partes.append("Favorito")
        if libro["leyendo_ahora"]:
            partes.append("Leyendo")
        elif libro["en_pendientes"]:
            partes.append("Pendiente")
        elif libro["leido"]:
            partes.append("Leído")
        if not libro["titulo_revisado"]:
            partes.append("Título sin revisar")
        return ", ".join(partes) if partes else "Sin marcar"

    def al_cambiar_filtro(self, evento):
        self._cargar_libros()
        evento.Skip()

    def _libro_seleccionado(self):
        indice = self.lista_libros.GetFirstSelected()
        if indice == -1 or indice >= len(self._libros_actuales):
            return None
        return self._libros_actuales[indice]

    # ── Importación de carpetas ──────────────────────────────────────────────

    def al_importar_carpeta(self, evento):
        with wx.DirDialog(
            self, "Seleccionar carpeta con libros para importar",
            defaultPath=self._cargar_ultima_carpeta_importada(),
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            carpeta = dlg.GetPath()
        self._guardar_ultima_carpeta_importada(carpeta)

        usar_subcarpetas = wx.MessageBox(
            "¿Las subcarpetas de esta carpeta representan géneros y subgéneros?\n\n"
            "Ejemplo: «Fantasía/Fantasía épica/tu_libro.epub» crearía la categoría "
            "«Fantasía» con la subcategoría «Fantasía épica».\n\n"
            "Podrás renombrar o mover las categorías después. Si tus subcarpetas "
            "no son géneros (por ejemplo, son autores o sagas), elige No.",
            "¿Crear categorías desde las subcarpetas?", wx.YES_NO | wx.ICON_QUESTION,
        ) == wx.YES

        self._voz.hablar("Escaneando carpeta, por favor espera...")
        self.barra_progreso.SetValue(0)
        self.barra_progreso.Show()
        self.Layout()
        self._progreso_actual = (0, 0)
        self._timer_progreso.Start(2500)

        self.escaner = EscanerBiblioteca(
            self.gestor,
            al_progresar=lambda p, t: wx.CallAfter(self._al_progresar_escaneo, p, t),
            al_detectar_carpetas=lambda carpetas: wx.CallAfter(
                self._al_detectar_carpetas_agrupables, carpetas
            ),
            al_terminar=lambda total: wx.CallAfter(self._al_terminar_escaneo, total),
            al_fallar=lambda error: wx.CallAfter(self._al_fallar_escaneo, error),
        )
        self.escaner.iniciar(carpeta, usar_subcarpetas_como_categorias=usar_subcarpetas)

    def _al_progresar_escaneo(self, procesados, total):
        # Solo actualiza el estado visual (Gauge + etiqueta) aquí — esto se
        # llama muchas veces por segundo desde 8 hilos en paralelo. Llamar a
        # _anunciar() (que roba y devuelve el foco) en cada evento provoca
        # que las llamadas se pisen entre sí y NVDA acabe sin anunciar nada
        # con claridad. El anuncio de voz va aparte, por temporizador
        # (al_temporizador_progreso), con una cadencia fija y predecible.
        self._progreso_actual = (procesados, total)
        if total > 0:
            self.barra_progreso.SetRange(total)
            self.barra_progreso.SetValue(min(procesados, total))
        self.lbl_estado.SetLabel(f"Escaneando... {procesados} de {total} libro(s) procesados.")

    def al_temporizador_progreso(self, evento):
        procesados, total = self._progreso_actual
        if total > 0:
            self._voz.hablar(f"Procesando... {procesados} de {total} libros.")

    def _al_detectar_carpetas_agrupables(self, carpetas_candidatas: dict):
        nombres_sugeridos = {
            carpeta: os.path.basename(os.path.normpath(carpeta))
            for carpeta in carpetas_candidatas
        }
        mensaje = "Se detectaron carpetas con varios libros. ¿Agrupar cada una con una etiqueta?\n\n"
        mensaje += "\n".join(
            f"· {nombres_sugeridos[carpeta]} ({len(titulos)} libros)"
            for carpeta, titulos in carpetas_candidatas.items()
        )
        if wx.MessageBox(mensaje, "Agrupar por carpeta", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            # Entre que se confirma y se termina de etiquetar puede pasar un
            # rato perceptible con muchas carpetas — sin este aviso, NVDA se
            # queda en silencio y parece que la app se ha colgado. El
            # etiquetado en sí se hace en un hilo de fondo (ver
            # _agrupar_carpetas_en_hilo) para no bloquear la interfaz.
            self._voz.hablar("Aplicando etiquetas, por favor espera...")
            self._ultima_etiqueta_creada = next(iter(nombres_sugeridos.values()), None)
            threading.Thread(
                target=self._agrupar_carpetas_en_hilo,
                args=(dict(carpetas_candidatas), dict(nombres_sugeridos)),
                name="agrupar_por_carpeta",
                daemon=True,
            ).start()
        else:
            self._ultima_etiqueta_creada = None

    def _agrupar_carpetas_en_hilo(self, carpetas_candidatas: dict, nombres_sugeridos: dict):
        """
        Etiqueta cada carpeta candidata en un hilo de fondo. Un fallo en
        una carpeta concreta (registrado por confirmar_agrupamiento_por_
        carpeta) nunca detiene el resto; y si el hilo entero revienta por
        algo inesperado, el except de aquí garantiza que igualmente se
        llegue al callback de finalización en vez de dejar a NVDA
        colgado en silencio para siempre.
        """
        total_fallos = 0
        try:
            for carpeta in carpetas_candidatas:
                try:
                    _exitosos, fallidos = confirmar_agrupamiento_por_carpeta(
                        self.gestor, carpeta, nombres_sugeridos[carpeta]
                    )
                    total_fallos += fallidos
                except Exception:
                    total_fallos += len(carpetas_candidatas[carpeta])
                    logger.exception(
                        "[PestanaBiblioteca] Fallo agrupando la carpeta: %s", carpeta
                    )
        except Exception:
            logger.exception("[PestanaBiblioteca] Fallo inesperado al agrupar por carpeta")
        finally:
            wx.CallAfter(self._al_terminar_agrupamiento, total_fallos)

    def _al_terminar_agrupamiento(self, total_fallos: int):
        id_etiqueta_nueva = None
        nombre_etiqueta_nueva = getattr(self, "_ultima_etiqueta_creada", None)
        if nombre_etiqueta_nueva:
            id_etiqueta_nueva = next(
                (e["id"] for e in self.gestor.listar_etiquetas() if e["nombre"] == nombre_etiqueta_nueva),
                None,
            )
        self._ultima_etiqueta_creada = None

        self._cargar_arbol_categorias()
        self._cargar_lista_etiquetas(id_etiqueta_seleccionar=id_etiqueta_nueva)
        self._cargar_libros()
        self.lista_libros.SetFocus()

        if total_fallos:
            reproducir(ERROR)
            self._voz.hablar(
                f"Etiquetas aplicadas, pero {total_fallos} libro(s) no se pudieron etiquetar."
            )
        else:
            reproducir(SUCCESS)
            self._voz.hablar("Etiquetas aplicadas.")

    def _al_terminar_escaneo(self, total_insertados):
        self._timer_progreso.Stop()
        reproducir(SUCCESS)
        self.barra_progreso.Hide()
        self.Layout()

        # _ultima_etiqueta_creada no se toca aquí: EscanerBiblioteca llama a
        # al_detectar_carpetas (que la fija, si hay agrupamiento por
        # confirmar) y justo después a al_terminar, sin esperar a que el
        # hilo de etiquetado (lanzado de forma asíncrona) haya terminado.
        # Si este método la leyera y reseteara, se la "robaría" a
        # _al_terminar_agrupamiento antes de que la etiqueta nueva tuviera
        # libros asignados — mostrando la lista filtrada y vacía por una
        # etiqueta recién creada sin contenido todavía.
        # Igual que _cargar_arbol_categorias() de la línea de arriba, sin
        # argumento: vuelve a "(Todas las etiquetas)" en vez de conservar
        # la que estuviera activa. Si se preserva la etiqueta activa, tras
        # importar más libros la lista de la derecha se queda mostrando el
        # filtro estrecho de lo que fuera esa etiqueta (a veces vacía o
        # con muy pocos libros), dando la falsa impresión de que faltan
        # libros cuando en realidad solo faltaba ampliar el filtro.
        self._cargar_arbol_categorias()
        self._cargar_lista_etiquetas()
        self._cargar_libros()
        self.lista_libros.SetFocus()

        # Diálogo modal nativo en vez de solo el anunciador: siempre tiene
        # foco propio y se cierra con Enter/Escape/OK de forma garantizada,
        # sin depender de que el usuario navegue de vuelta a la lista.
        if total_insertados > 0:
            mensaje = f"Se han añadido {total_insertados} libro(s) a la biblioteca."
        else:
            mensaje = "No se encontraron libros nuevos en esa carpeta."
        self._voz.hablar(mensaje)
        wx.MessageBox(mensaje, "Escaneo completado", wx.OK | wx.ICON_INFORMATION)

    def _al_fallar_escaneo(self, error):
        self._timer_progreso.Stop()
        reproducir(ERROR)
        self.barra_progreso.Hide()
        self.Layout()
        wx.MessageBox(f"No se pudo completar el escaneo:\n{error}", "Error", wx.OK | wx.ICON_ERROR)

    # ── Acciones sobre el libro seleccionado ─────────────────────────────────

    def al_anunciar_info_libro(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            self._anunciar("No hay ningún libro seleccionado.")
            return
        autores = self.gestor.obtener_autores_de_libro(libro["id"])
        nombres_autores = ", ".join(a["nombre"] for a in autores) or "autor desconocido"
        estado = self._describir_estado(libro)
        self._anunciar(
            f"{libro['titulo']}, {nombres_autores}, {libro['formato'].upper()}, {estado}."
        )

    def al_alternar_favorito(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        nuevo_valor = not bool(libro["favorito"])
        self.gestor.establecer_bandera(libro["id"], "favorito", nuevo_valor)
        self._anunciar("Marcado como favorito." if nuevo_valor else "Quitado de favoritos.")
        self._cargar_libros()

    def _alternar_estado_libro(self, campo, nombre_al_marcar, nombre_al_quitar):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        nuevo_valor = not bool(libro[campo])
        self.gestor.establecer_bandera(libro["id"], campo, nuevo_valor)
        mensaje = f"Marcado como {nombre_al_marcar}." if nuevo_valor else f"Quitado de {nombre_al_quitar}."
        self._anunciar(mensaje)
        self._cargar_libros()

    def _construir_menu_marcar_estado_masivo(self, libros) -> wx.Menu:
        """
        Submenú para marcar de golpe el estado de lectura de todos los
        libros de una etiqueta — útil para quien lee varios libros de una
        saga a la vez (marcar toda la saga como "leyendo ahora") o para
        dar por terminada una saga completa de una sola vez.
        """
        menu = wx.Menu()
        opciones = [
            ("en_pendientes", "Pendiente", "pendientes"),
            ("leyendo_ahora", "Leyendo ahora", "leyendo ahora"),
            ("leido", "Leído", "leídos"),
        ]
        for campo, etiqueta_item, nombre_plural in opciones:
            item = menu.Append(wx.ID_ANY, etiqueta_item)
            self.Bind(
                wx.EVT_MENU,
                lambda e, c=campo, n=nombre_plural: self._marcar_estado_libros_masivo(libros, c, n),
                item,
            )
        return menu

    def _marcar_estado_libros_masivo(self, libros, campo, nombre_plural):
        for libro in libros:
            self.gestor.establecer_bandera(libro["id"], campo, True)
        reproducir(SUCCESS)
        self._anunciar(f"{len(libros)} libro(s) marcados como {nombre_plural}.")
        self._cargar_libros()

    def al_abrir_libro_seleccionado(self, evento=None):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        if not os.path.exists(libro["ruta_archivo"]):
            self._anunciar(
                "No se encontró el archivo en su ubicación. "
                "Usa Renombrar (F2) o localízalo manualmente."
            )
            return
        if libro["formato"] != "epub":
            wx.MessageBox(
                "La lectura de archivos PDF todavía no está conectada a la pestaña "
                "Lectura. Por ahora solo se pueden abrir libros EPUB desde aquí.",
                "Formato no disponible todavía", wx.OK | wx.ICON_INFORMATION,
            )
            return

        self._voz.hablar("Abriendo libro, por favor espera...")
        self._anunciar("Abriendo libro, por favor espera...")

        wx.CallLater(400, self._continuar_apertura_libro, libro)

    def _continuar_apertura_libro(self, libro):
        ventana_principal = self.padre_notebook.GetParent()
        try:
            from app.interfaz.ventana_principal import IDX_LECTURA
            self.padre_notebook.SetSelection(IDX_LECTURA)
            ventana_principal.pestana_lectura.cargar_epub_desde_ruta(libro["ruta_archivo"])
        except Exception:
            logger.exception("[PestanaBiblioteca] No se pudo abrir el libro en Lectura")
            reproducir(ERROR)
            return

        self.gestor.establecer_bandera(libro["id"], "leyendo_ahora", True)
        reproducir(SUCCESS)

    def al_tecla_lista(self, evento):
        codigo = evento.GetKeyCode()
        if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.al_abrir_libro_seleccionado()
            return
        if codigo == wx.WXK_DELETE:
            self._quitar_libro_seleccionado()
            return
        if codigo == wx.WXK_F5:
            self.al_importar_carpeta(evento)
            return
        if codigo == wx.WXK_F2:
            self.al_renombrar_segun_metadatos(evento)
            return
        evento.Skip()

    def _quitar_libro_seleccionado(self):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        if wx.MessageBox(
            f"¿Quitar «{libro['titulo']}» de la biblioteca?\n\n"
            "El archivo no se borrará del disco, solo su registro aquí.",
            "Quitar de la biblioteca", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.quitar_libro(libro["id"])
        self._anunciar("Libro quitado de la biblioteca.")
        self._cargar_libros()

    def al_renombrar_segun_metadatos(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        dlg = wx.TextEntryDialog(
            self,
            "Nombre de archivo propuesto (editable):",
            "Renombrar archivo (F2)",
            value=libro["titulo"],
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        titulo_confirmado = dlg.GetValue().strip()
        dlg.Destroy()
        if not titulo_confirmado:
            return

        resultado = renombrar_libro_segun_metadatos(self.gestor, libro["id"], titulo_confirmado)
        if resultado.exito:
            reproducir(SUCCESS)
            self._anunciar("Archivo renombrado correctamente.")
        else:
            reproducir(ERROR)
            wx.MessageBox(
                f"No se pudo renombrar el archivo:\n{resultado.motivo_fallo}",
                "Error al renombrar", wx.OK | wx.ICON_ERROR,
            )
        self._cargar_libros()

    def al_renombrar_todos_pendientes(self, evento):
        pendientes = self.gestor.obtener_pendientes_de_revision()
        if not pendientes:
            self._anunciar("No hay libros pendientes de revisión.")
            return

        cambios = [{"id_libro": p["id"], "titulo_nuevo": p["titulo"]} for p in pendientes]
        exitosos, fallidos = renombrar_pendientes_por_lote(self.gestor, cambios)

        mensaje = f"{len(exitosos)} de {len(cambios)} archivos renombrados correctamente."
        if fallidos:
            detalle = "\n".join(f"· {f.titulo_anterior}: {f.motivo_fallo}" for f in fallidos)
            mensaje += f"\n\nNo se pudieron renombrar:\n{detalle}"
        wx.MessageBox(mensaje, "Renombrado por lotes", wx.OK | wx.ICON_INFORMATION)
        self._cargar_libros()

    def construir_menu_asignar_categoria(self, libro) -> wx.Menu:
        """Submenú «Añadir a categoría» para un único libro (ver _construir_menu_categorias)."""
        return self._construir_menu_categorias([libro])

    def construir_menu_asignar_categoria_masivo(self, libros) -> wx.Menu:
        """
        Igual que construir_menu_asignar_categoria pero aplicado a varios
        libros a la vez — se usa desde la lista de etiquetas para asignar
        una categoría a todos los libros de una saga de una sola vez, sin
        tener que abrir el menú libro por libro.
        """
        return self._construir_menu_categorias(libros)

    def _construir_menu_categorias(self, libros) -> wx.Menu:
        """
        Submenú "Añadir a categoría": primer elemento para crear una
        categoría nueva y asignarla en el mismo paso, después el árbol
        de categorías existentes como submenús anidados — cada nivel
        tiene su propio elemento "Asignar aquí" antes de sus hijos, para
        poder elegir tanto un género como uno de sus subgéneros
        directamente, sin escribir ni buscar nada.

        `libros` es siempre una lista (uno o varios), para poder reutilizar
        el mismo menú tanto al asignar un libro suelto como al asignar
        todos los libros de una etiqueta de una vez.
        """
        menu = wx.Menu()
        item_nueva = menu.Append(wx.ID_ANY, "Crear categoría nueva y asignar...")
        self.Bind(
            wx.EVT_MENU, lambda e: self.al_crear_categoria_y_asignar(libros, None), item_nueva
        )

        raices = self.gestor.listar_categorias_hijas(None)
        if raices:
            menu.AppendSeparator()
            self._rellenar_submenu_categorias(menu, None, libros)
        return menu

    def _rellenar_submenu_categorias(self, menu_destino, id_categoria_padre, libros):
        # Toda categoría —tenga o no subcategorías todavía— recibe su propio
        # submenú con "Asignar aquí" y "Crear subcategoría nueva", y sus
        # subcategorías existentes aparecen directamente anidadas debajo,
        # sin necesidad de escribir ni buscar nada.
        for categoria in self.gestor.listar_categorias_hijas(id_categoria_padre):
            hijas = self.gestor.listar_categorias_hijas(categoria["id"])
            submenu = wx.Menu()
            item_aqui = submenu.Append(wx.ID_ANY, f"Asignar a «{categoria['nombre']}»")
            self.Bind(
                wx.EVT_MENU,
                lambda e, id_cat=categoria["id"]: self.al_asignar_categoria_existente(
                    libros, id_cat
                ),
                item_aqui,
            )
            submenu.AppendSeparator()
            item_nueva_sub = submenu.Append(wx.ID_ANY, "Crear subcategoría nueva y asignar...")
            self.Bind(
                wx.EVT_MENU,
                lambda e, id_padre=categoria["id"]: self.al_crear_categoria_y_asignar(
                    libros, id_padre
                ),
                item_nueva_sub,
            )
            if hijas:
                submenu.AppendSeparator()
                self._rellenar_submenu_categorias(submenu, categoria["id"], libros)
            menu_destino.AppendSubMenu(submenu, categoria["nombre"])

    def construir_menu_asignar_etiqueta(self, libro) -> wx.Menu:
        """Submenú «Añadir a etiqueta»: lista plana, sin jerarquía (a diferencia de categorías)."""
        menu = wx.Menu()
        item_nueva = menu.Append(wx.ID_ANY, "Crear etiqueta nueva y asignar...")
        self.Bind(
            wx.EVT_MENU, lambda e: self.al_crear_etiqueta_y_asignar(libro), item_nueva
        )

        etiquetas = self.gestor.listar_etiquetas()
        etiquetas_del_libro = {e["id"] for e in self.gestor.obtener_etiquetas_de_libro(libro["id"])}
        if etiquetas:
            menu.AppendSeparator()
            for etiqueta in etiquetas:
                if etiqueta["id"] in etiquetas_del_libro:
                    continue
                item = menu.Append(wx.ID_ANY, etiqueta["nombre"])
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, id_etq=etiqueta["id"]: self.al_asignar_etiqueta_existente(libro, id_etq),
                    item,
                )
        return menu

    def al_asignar_etiqueta_existente(self, libro, id_etiqueta):
        nombre = next(
            (e["nombre"] for e in self.gestor.listar_etiquetas() if e["id"] == id_etiqueta), ""
        )
        self.gestor.asignar_etiqueta(libro["id"], nombre)
        reproducir(SUCCESS)
        self._voz.hablar(f"Añadido a etiqueta {nombre}.")
        self._cargar_lista_etiquetas(id_etiqueta_seleccionar=self._id_etiqueta_activa)
        self._cargar_libros()

    def al_crear_etiqueta_y_asignar(self, libro):
        dlg = wx.TextEntryDialog(self, "Nombre de la nueva etiqueta:", "Crear etiqueta y asignar")
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                self.gestor.asignar_etiqueta(libro["id"], nombre)
                reproducir(SUCCESS)
                self._voz.hablar(f"Etiqueta {nombre} creada y libro añadido.")
                self._cargar_lista_etiquetas(id_etiqueta_seleccionar=self._id_etiqueta_activa)
                self._cargar_libros()
        dlg.Destroy()

    def al_quitar_de_etiqueta_actual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None or self._id_etiqueta_activa is None:
            return
        self.gestor.quitar_etiqueta_de_libro(libro["id"], self._id_etiqueta_activa)
        reproducir(SUCCESS)
        self._voz.hablar("Libro quitado de esta etiqueta.")
        self._cargar_libros()

    def al_asignar_categoria_existente(self, libros, id_categoria):
        ruta = self.gestor.obtener_ruta_categoria(id_categoria)
        for libro in libros:
            self.gestor.asignar_categoria_por_ruta(libro["id"], ruta)
        reproducir(SUCCESS)
        if len(libros) == 1:
            self._voz.hablar(f"Añadido a categoría {' > '.join(ruta)}.")
        else:
            self._voz.hablar(f"{len(libros)} libros añadidos a categoría {' > '.join(ruta)}.")
        self._cargar_arbol_categorias(id_categoria_seleccionar=self._id_categoria_activa)
        self._cargar_libros()

    def al_crear_categoria_y_asignar(self, libros, id_padre):
        dlg = wx.TextEntryDialog(
            self,
            "Nombre de la nueva categoría:",
            "Crear categoría y asignar",
        )
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                id_categoria = self.gestor.crear_categoria(nombre, id_padre)
                ruta = self.gestor.obtener_ruta_categoria(id_categoria)
                for libro in libros:
                    self.gestor.asignar_categoria_por_ruta(libro["id"], ruta)
                reproducir(SUCCESS)
                if len(libros) == 1:
                    self._voz.hablar(f"Categoría {nombre} creada y libro añadido.")
                else:
                    self._voz.hablar(f"Categoría {nombre} creada y {len(libros)} libros añadidos.")
                self._cargar_arbol_categorias(id_categoria_seleccionar=self._id_categoria_activa)
                self._cargar_libros()
        dlg.Destroy()

    def al_quitar_de_categoria_actual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None or self._id_categoria_activa is None:
            return
        self.gestor.quitar_categoria_de_libro(libro["id"], self._id_categoria_activa)
        reproducir(SUCCESS)
        self._anunciar("Libro quitado de esta categoría.")
        self._cargar_libros()

    # ── Menú contextual ──────────────────────────────────────────────────────

    def al_menu_contextual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return

        menu = wx.Menu()

        item_abrir = menu.Append(wx.ID_ANY, "Abrir en Lectura\tIntro")
        self.Bind(wx.EVT_MENU, lambda e: self.al_abrir_libro_seleccionado(), item_abrir)

        menu.AppendSeparator()

        item_favorito = menu.Append(
            wx.ID_ANY, "Quitar de favoritos" if libro["favorito"] else "Marcar como favorito"
        )
        self.Bind(wx.EVT_MENU, self.al_alternar_favorito, item_favorito)

        item_pendiente = menu.Append(
            wx.ID_ANY,
            "Quitar de pendientes" if libro["en_pendientes"] else "Marcar como pendiente",
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._alternar_estado_libro("en_pendientes", "pendiente", "pendientes"),
            item_pendiente,
        )

        item_leyendo = menu.Append(
            wx.ID_ANY,
            "Quitar de leyendo ahora" if libro["leyendo_ahora"] else "Marcar como leyendo ahora",
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._alternar_estado_libro(
                "leyendo_ahora", "leyendo ahora", "leyendo ahora"
            ),
            item_leyendo,
        )

        item_leido = menu.Append(
            wx.ID_ANY, "Quitar de leídos" if libro["leido"] else "Marcar como leído"
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._alternar_estado_libro("leido", "leído", "leídos"),
            item_leido,
        )

        menu.AppendSubMenu(self.construir_menu_asignar_categoria(libro), "Añadir a categoría")

        item_quitar_cat = menu.Append(wx.ID_ANY, "Quitar de esta categoría")
        item_quitar_cat.Enable(self._id_categoria_activa is not None)
        self.Bind(wx.EVT_MENU, self.al_quitar_de_categoria_actual, item_quitar_cat)

        menu.AppendSubMenu(self.construir_menu_asignar_etiqueta(libro), "Añadir a etiqueta")

        item_quitar_etq = menu.Append(wx.ID_ANY, "Quitar de esta etiqueta")
        item_quitar_etq.Enable(self._id_etiqueta_activa is not None)
        self.Bind(wx.EVT_MENU, self.al_quitar_de_etiqueta_actual, item_quitar_etq)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar archivo...\tF2")
        self.Bind(wx.EVT_MENU, self.al_renombrar_segun_metadatos, item_renombrar)

        item_quitar = menu.Append(wx.ID_ANY, "Quitar de la biblioteca")
        self.Bind(wx.EVT_MENU, lambda e: self._quitar_libro_seleccionado(), item_quitar)

        self._anadir_ayuda_y_salir(menu)
        self.PopupMenu(menu)
        menu.Destroy()

    def _anadir_ayuda_y_salir(self, menu):
        """
        Añade el separador + submenú Ayuda + Salir al final de un menú
        contextual propio de Biblioteca (árbol, etiquetas o libro),
        reutilizando el submenú compartido de VentanaPrincipal en vez de
        duplicarlo — mismo principio que llevó a corregir el dispatcher
        de _menu_contextual_biblioteca().
        """
        ventana_principal = self.padre_notebook.GetParent()
        menu.AppendSeparator()
        ventana_principal._submenu_ayuda(menu)
        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, "Salir")
        ventana_principal.Bind(wx.EVT_MENU, ventana_principal.al_salir, item_salir)

    def _cargar_ultima_carpeta_importada(self) -> str:
        try:
            ruta = ruta_config("ajustes.json")
            if os.path.exists(ruta):
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                carpeta = datos.get("ultima_carpeta_importada_biblioteca", "")
                if carpeta and os.path.isdir(carpeta):
                    return carpeta
        except Exception:
            logger.exception("[PestanaBiblioteca] No se pudo leer la última carpeta importada")
        return ""

    def _guardar_ultima_carpeta_importada(self, carpeta: str):
        try:
            ruta = ruta_config("ajustes.json")
            datos = {}
            if os.path.exists(ruta):
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            datos["ultima_carpeta_importada_biblioteca"] = carpeta
            os.makedirs(CONFIG_DIR, exist_ok=True)
            ruta_temporal = ruta + ".tmp"
            with open(ruta_temporal, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=4)
            os.replace(ruta_temporal, ruta)
        except Exception:
            logger.exception("[PestanaBiblioteca] No se pudo guardar la última carpeta importada")
# ANCLAJE_FIN: DEFINICION_PESTANA_BIBLIOTECA
