# ANCLAJE_INICIO: DEPENDENCIAS_BIBLIOTECA
import wx
import os
import re
import json
import logging
import threading

from app.config_rutas import ruta_config, CONFIG_DIR
from app.motor.gestor_biblioteca import GestorBiblioteca
from app.motor.escaner_biblioteca import EscanerBiblioteca, confirmar_agrupamiento_por_carpeta, _procesar_archivo
from app.motor.renombrador_biblioteca import (
    renombrar_libro_segun_metadatos,
    renombrar_pendientes_por_lote,
    relocalizar_libro,
    reconciliar_carpeta_movida,
)
from app.interfaz.dialogos import DialogoArchivoNoEncontrado, DialogoAgruparCarpetas
from app.motor import anunciador_lector as voz
from app.motor.anunciador_voz import AnunciadorVoz
from app.motor.reproductor_sonidos import (
    reproducir, SUCCESS, ERROR, LIST_NAV, MOVE_UP, MOVE_DOWN, CLEAR,
)
from app.interfaz.ui_recursos import aplicar_icono_boton
from app.motor.gestor_idioma import traducir as _
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
        super().__init__(padre, title=_("Nueva categoría"))
        self.crear_como_subcategoria = False
        self.nombre = ""

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=_("Nombre de la nueva categoría:")), 0, wx.ALL, 5)
        self.txt_nombre = wx.TextCtrl(self)
        sizer.Add(self.txt_nombre, 0, wx.EXPAND | wx.ALL, 5)

        self.chk_subcategoria = wx.CheckBox(
            self, label=(
                _("Crear como subcategoría de «{nombre}»").format(nombre=nombre_categoria_padre)
                if nombre_categoria_padre else
                _("Crear como subcategoría (selecciona antes una categoría en el árbol)")
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
            wx.MessageBox(_("Escribe un nombre para la categoría."), _("Nombre vacío"), wx.OK | wx.ICON_WARNING)
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
        self._ids_audiolibro_pendiente = set()
        self._id_categoria_activa = None
        self._id_etiqueta_activa = None
        self._categoria_en_portapapeles = None

        self._configurar_interfaz()
        self._configurar_atajos()

        self._voz = AnunciadorVoz()
        self.Bind(wx.EVT_WINDOW_DESTROY, lambda e: (self._voz.detener(), e.Skip()))

        self._progreso_actual = (0, 0)
        # "escaneo" o "agrupando": mismo temporizador y misma barra para las
        # dos operaciones de fondo largas de esta pestaña, solo cambia el
        # texto anunciado por voz cada 2.5s (al_temporizador_progreso).
        self._modo_progreso = "escaneo"
        self._timer_progreso = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.al_temporizador_progreso, self._timer_progreso)

        # Copia de seguridad de biblioteca.db una vez por sesión, en un
        # hilo de fondo (comprimir cientos/miles de libros puede tardar
        # y no debe congelar el arranque de la pestaña).
        threading.Thread(
            target=self._crear_backup_biblioteca_en_hilo, daemon=True
        ).start()

        wx.CallAfter(self._cargar_arbol_categorias)
        wx.CallAfter(self._cargar_lista_etiquetas)
        wx.CallAfter(self._cargar_libros)

    @staticmethod
    def _crear_backup_biblioteca_en_hilo():
        try:
            from app.motor.gestor_backups import crear_backup_biblioteca
            crear_backup_biblioteca()
        except Exception:
            logger.exception("[PestanaBiblioteca] Fallo al crear backup de biblioteca.db")

    # ── Construcción de la interfaz ─────────────────────────────────────────

    def _configurar_interfaz(self):
        sizer_general = wx.BoxSizer(wx.VERTICAL)

        # ── Barra de herramientas fija de importación (siempre visible) ──
        # Antes vivía al final de la columna derecha, dentro de un sizer que
        # podía quedar recortado fuera del área visible según el tamaño de
        # la ventana (la lista de libros, con proporción 1, se quedaba con
        # todo el espacio disponible y empujaba estos botones fuera). Al ir
        # en su propia fila fija en la parte superior de toda la pestaña,
        # con proporción 0, nunca se oculta ni se recorta.
        sizer_importar = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_importar = wx.Button(self, label=_("Importar carpeta... (Ctrl+O)"))
        self.btn_importar.Bind(wx.EVT_BUTTON, self.al_importar_carpeta)
        aplicar_icono_boton(self.btn_importar, "examinar", _("Importar carpeta"))
        sizer_importar.Add(self.btn_importar, 0, wx.ALL, 5)
        self.btn_importar_archivo = wx.Button(self, label=_("Importar libro..."))
        self.btn_importar_archivo.SetHelpText(
            _("Añade un único archivo EPUB o PDF a la Biblioteca, sin escanear "
              "toda una carpeta.")
        )
        self.btn_importar_archivo.Bind(wx.EVT_BUTTON, self.al_importar_archivo)
        aplicar_icono_boton(self.btn_importar_archivo, "examinar", _("Importar libro"))
        sizer_importar.Add(self.btn_importar_archivo, 0, wx.ALL, 5)
        self.barra_progreso = wx.Gauge(self, range=100)
        self.barra_progreso.Hide()
        sizer_importar.Add(self.barra_progreso, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_general.Add(sizer_importar, 0, wx.EXPAND)

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
            _("Árbol de géneros y subgéneros. Flechas para navegar; seleccionar "
              "un nodo filtra la lista de libros por esa categoría (incluye "
              "subgéneros). F2 renombra, Supr elimina, Ctrl+X/Ctrl+V mueve un "
              "género bajo otro, Ctrl+Arriba/Ctrl+Abajo lo reordena entre sus "
              "hermanos, Menú o Shift+F10 para más opciones.")
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
            panel_generos, label=_("Nueva categoría... (F2 renombra, Supr elimina)")
        )
        self.btn_nueva_categoria.Bind(wx.EVT_BUTTON, self.al_nueva_categoria)
        sizer_generos.Add(self.btn_nueva_categoria, 0, wx.EXPAND | wx.ALL, 5)
        panel_generos.SetSizer(sizer_generos)
        self.subnotebook_izquierdo.AddPage(panel_generos, _("Géneros"))

        panel_sagas = wx.Panel(self.subnotebook_izquierdo)
        sizer_sagas = wx.BoxSizer(wx.VERTICAL)
        self.lista_etiquetas = wx.ListBox(panel_sagas)
        self.lista_etiquetas.SetHelpText(
            _("Lista plana de etiquetas (sagas y colecciones personalizadas). "
              "Seleccionar una filtra la lista de libros por esa etiqueta. "
              "F2 renombra, Supr elimina.")
        )
        self.lista_etiquetas.SetMinSize((220, 160))
        self.lista_etiquetas.Bind(wx.EVT_LISTBOX, self.al_seleccionar_etiqueta)
        self.lista_etiquetas.Bind(wx.EVT_KEY_DOWN, self.al_tecla_lista_etiquetas)
        self.lista_etiquetas.Bind(wx.EVT_CONTEXT_MENU, self.al_menu_contextual_etiquetas)
        sizer_sagas.Add(self.lista_etiquetas, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_nueva_etiqueta = wx.Button(
            panel_sagas, label=_("Nueva etiqueta... (F2 renombra, Supr elimina)")
        )
        self.btn_nueva_etiqueta.Bind(wx.EVT_BUTTON, self.al_nueva_etiqueta)
        sizer_sagas.Add(self.btn_nueva_etiqueta, 0, wx.EXPAND | wx.ALL, 5)
        panel_sagas.SetSizer(sizer_sagas)
        self.subnotebook_izquierdo.AddPage(panel_sagas, _("Sagas y colecciones"))

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
            wx.StaticText(self, label=_("Buscar por título o autor (Ctrl+F):")),
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
            wx.StaticText(self, label=_("Estado:")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5
        )
        # Los valores de _ESTADOS_FILTRO se comparan tal cual contra el
        # texto elegido en _cargar_libros(), así que se guardan en español
        # (clave interna) y se muestran traducidos en el propio wx.Choice.
        self._ESTADOS_FILTRO = ["Todos", "Pendientes de leer", "Leyendo ahora", "Leídos", "Audiolibros a medias"]
        self.combo_estado = wx.Choice(self, choices=[_(estado) for estado in self._ESTADOS_FILTRO])
        self.combo_estado.SetSelection(0)
        self.combo_estado.Bind(wx.EVT_CHOICE, self.al_cambiar_filtro)
        sizer_filtro_estado.Add(self.combo_estado, 0, wx.ALL, 5)

        self.chk_favoritos = wx.CheckBox(self, label=_("Solo favoritos"))
        self.chk_favoritos.Bind(wx.EVT_CHECKBOX, self.al_cambiar_filtro)
        sizer_filtro_estado.Add(self.chk_favoritos, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        sizer_derecho.Add(sizer_filtro_estado, 0)

        # Lista principal de libros
        self.lista_libros = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self.lista_libros.InsertColumn(0, _("Título"), width=320)
        self.lista_libros.InsertColumn(1, _("Autor"), width=200)
        self.lista_libros.InsertColumn(2, _("Formato"), width=80)
        self.lista_libros.InsertColumn(3, _("Estado"), width=160)
        self.lista_libros.Bind(wx.EVT_CONTEXT_MENU, self.al_menu_contextual)
        self.lista_libros.Bind(wx.EVT_KEY_DOWN, self.al_tecla_lista)
        sizer_derecho.Add(self.lista_libros, 1, wx.EXPAND | wx.ALL, 5)

        self.lbl_estado = wx.StaticText(self, label="")
        sizer_derecho.Add(self.lbl_estado, 0, wx.ALL, 5)

        sizer_principal.Add(sizer_derecho, 3, wx.EXPAND)

        sizer_general.Add(sizer_principal, 1, wx.EXPAND)
        self.SetSizer(sizer_general)

        # Orden de tabulación explícito, de principio a fin: subpestañas de
        # géneros/sagas → filtros (buscar, estado, favoritos) → lista de
        # libros → botones de importación al final (acción puntual, no lo
        # que más se usa). Antes solo se reposicionaban la lista y los
        # botones de importar, así que los filtros —creados antes que la
        # lista, pero nunca movidos— quedaban descolgados al final del
        # todo, después de los botones de importar, en vez de justo
        # delante de la lista donde tiene sentido encontrarlos.
        self.txt_filtro.MoveAfterInTabOrder(self.subnotebook_izquierdo)
        self.combo_estado.MoveAfterInTabOrder(self.txt_filtro)
        self.chk_favoritos.MoveAfterInTabOrder(self.combo_estado)
        self.lista_libros.MoveAfterInTabOrder(self.chk_favoritos)
        self.btn_importar.MoveAfterInTabOrder(self.lista_libros)
        self.btn_importar_archivo.MoveAfterInTabOrder(self.btn_importar)

    def _configurar_atajos(self):
        # Ctrl+O (apertura universal, contextual por pestaña) y Ctrl+I
        # (anunciar/info, también contextual) se gestionan a nivel de
        # VentanaPrincipal y llaman a al_importar_carpeta()/al_anunciar_info_libro()
        # desde allí — no se duplican aquí para no pisar el atajo global.
        # Ctrl+I sí estuvo duplicado aquí y en pestana_lectura.py a la vez:
        # cada pestaña con su propia AcceleratorTable para la misma tecla,
        # sin ninguna autoridad central. En el build congelado (PyInstaller)
        # eso hacía que Ctrl+I activara el manejador de Biblioteca aunque el
        # foco estuviera claramente en Lectura — se centralizó para quitar
        # la ambigüedad de raíz. Ctrl+Shift+B (Asistente de Biblioteca)
        # también se gestiona a nivel de VentanaPrincipal (AcceleratorTable
        # del Frame, con prioridad sobre los de cualquier panel hijo) para
        # que funcione desde cualquier pestaña, no solo con el foco dentro
        # de Biblioteca.
        id_buscar = wx.NewIdRef()
        id_favorito = wx.NewIdRef()

        self.Bind(wx.EVT_MENU, lambda e: self.txt_filtro.SetFocus(), id=id_buscar)
        self.Bind(wx.EVT_MENU, self.al_alternar_favorito, id=id_favorito)

        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('F'), id_buscar),
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
        return self.btn_importar_archivo

    # ── Anuncios de accesibilidad — accessible_output3, sin mover el foco ────

    def _anunciar(self, texto):
        voz.hablar(texto)

    # ── Árbol de categorías (jerárquico) ─────────────────────────────────────
    #
    # Cada nodo guarda una tupla (tipo, id) en SetItemData:
    #   ("todas", None)      → sin filtro de categoría
    #   ("categoria", id)    → género/subgénero

    def _cargar_arbol_categorias(self, id_categoria_seleccionar=None):
        self.arbol_categorias.Freeze()
        self.arbol_categorias.DeleteAllItems()
        raiz = self.arbol_categorias.AddRoot(_("Categorías"))

        nodo_todas = self.arbol_categorias.AppendItem(raiz, _("(Todas las categorías)"))
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
            etiqueta = _("{nombre} ({total} libro(s))").format(nombre=categoria["nombre"], total=total)
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
            logger.debug("Árbol de categorías ya destruido al obtener la categoría seleccionada", exc_info=True)
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
            # EVT_TREE_KEY_DOWN entrega un wx.TreeEvent, no un wx.KeyEvent
            # — ControlDown() vive en el KeyEvent real, que hay que sacar
            # aparte con GetKeyEvent().
            ctrl = evento.GetKeyEvent().ControlDown()
            if ctrl and codigo == wx.WXK_UP:
                self._mover_categoria_seleccionada(-1)
            elif ctrl and codigo == wx.WXK_DOWN:
                self._mover_categoria_seleccionada(1)
            elif codigo == wx.WXK_F2:
                if self._categoria_seleccionada_id() is not None:
                    self.arbol_categorias.EditLabel(self.arbol_categorias.GetSelection())
            elif codigo == wx.WXK_DELETE:
                self.al_eliminar_categoria(evento)
            else:
                evento.Skip()
        except RuntimeError:
            logger.debug("Árbol de categorías ya destruido al procesar tecla", exc_info=True)
            pass

    def _mover_categoria_seleccionada(self, direccion):
        # Mismo patrón que _mover_nodo() en ventana_proyectos.py: sonido
        # direccional (no un SUCCESS genérico) y anuncio con el nombre de
        # lo movido, no solo "movido" a secas.
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            self._anunciar(_("Selecciona primero un género o subgénero para moverlo."))
            return
        nombre = self.gestor.obtener_ruta_categoria(id_categoria)[-1]
        if self.gestor.mover_categoria(id_categoria, direccion):
            reproducir(MOVE_UP if direccion < 0 else MOVE_DOWN)
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_categoria)
            texto_direccion = _("arriba") if direccion < 0 else _("abajo")
            mensaje = _("{nombre} movido {direccion}.").format(nombre=nombre, direccion=texto_direccion)
            self._anunciar(mensaje)
            voz.hablar(mensaje)
        else:
            self._anunciar(_("Ya está en ese extremo, no se puede mover más."))

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
            voz.hablar(_("Categoría renombrada a {nombre}.").format(nombre=nuevo_nombre))
            self._cargar_libros()
        else:
            evento.Veto()
            reproducir(ERROR)
            wx.MessageBox(
                _("Ya existe una categoría con ese nombre en el mismo nivel."),
                _("No se pudo renombrar"), wx.OK | wx.ICON_WARNING,
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
                voz.hablar(
                    _("Subcategoría {nombre} creada dentro de {padre}.").format(
                        nombre=dlg.nombre, padre=nombre_padre
                    )
                )
            else:
                voz.hablar(_("Categoría {nombre} creada.").format(nombre=dlg.nombre))
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_nueva)
        dlg.Destroy()

    def al_eliminar_categoria(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            return
        nombre = self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
        if wx.MessageBox(
            _("¿Eliminar la categoría «{nombre}» y sus subcategorías?\n\n"
              "Los libros no se eliminan, solo dejan de pertenecer a esta categoría.").format(nombre=nombre),
            _("Eliminar categoría"), wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.eliminar_categoria(id_categoria)
        self._id_categoria_activa = None
        reproducir(SUCCESS)
        voz.hablar(_("Categoría {nombre} eliminada.").format(nombre=nombre))
        self._cargar_arbol_categorias()
        self._cargar_libros()

    def al_cortar_categoria(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            return
        self._categoria_en_portapapeles = id_categoria
        reproducir(CLEAR)
        nombre = self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
        voz.hablar(
            _("{nombre} cortada. Selecciona el destino y pulsa Control V, o Escape para cancelar.").format(
                nombre=nombre
            )
        )

    def al_pegar_categoria(self, evento):
        if self._categoria_en_portapapeles is None:
            voz.hablar(_("No hay ninguna categoría cortada."))
            return
        destino = self._categoria_seleccionada_id()
        if self.gestor.reparentar_categoria(self._categoria_en_portapapeles, destino):
            reproducir(SUCCESS)
            id_movida = self._categoria_en_portapapeles
            self._categoria_en_portapapeles = None
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_movida)
            voz.hablar(_("Categoría movida."))
        else:
            reproducir(ERROR)
            voz.hablar(_("No se puede mover ahí: crearía un ciclo o el destino es la misma categoría."))

    def al_menu_contextual_arbol(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        menu = wx.Menu()

        item_nueva = menu.Append(wx.ID_ANY, _("Nueva categoría o subcategoría..."))
        self.Bind(wx.EVT_MENU, self.al_nueva_categoria, item_nueva)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, _("Renombrar\tF2"))
        item_renombrar.Enable(id_categoria is not None)
        self.Bind(
            wx.EVT_MENU,
            lambda e: self.arbol_categorias.EditLabel(self.arbol_categorias.GetSelection()),
            item_renombrar,
        )

        item_mover_arriba = menu.Append(wx.ID_ANY, _("Mover arriba (Ctrl+Arriba)"))
        item_mover_arriba.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, lambda e: self._mover_categoria_seleccionada(-1), item_mover_arriba)

        item_mover_abajo = menu.Append(wx.ID_ANY, _("Mover abajo (Ctrl+Abajo)"))
        item_mover_abajo.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, lambda e: self._mover_categoria_seleccionada(1), item_mover_abajo)

        item_cortar = menu.Append(wx.ID_ANY, _("Cortar (Ctrl+X)"))
        item_cortar.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, self.al_cortar_categoria, item_cortar)

        item_pegar = menu.Append(wx.ID_ANY, _("Pegar aquí (Ctrl+V)"))
        item_pegar.Enable(self._categoria_en_portapapeles is not None)
        self.Bind(wx.EVT_MENU, self.al_pegar_categoria, item_pegar)

        menu.AppendSeparator()

        item_eliminar = menu.Append(wx.ID_ANY, _("Eliminar...\tSupr"))
        item_eliminar.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, self.al_eliminar_categoria, item_eliminar)

        self._anadir_ayuda_y_salir(menu)
        self.arbol_categorias.PopupMenu(menu)
        menu.Destroy()

    # ── Lista de etiquetas (plana) ────────────────────────────────────────────

    def _cargar_lista_etiquetas(self, id_etiqueta_seleccionar=None):
        self.lista_etiquetas.Freeze()
        self.lista_etiquetas.Clear()
        self._etiquetas_indice = [{"id": None, "nombre": _("(Todas las etiquetas)")}]
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
            voz.hablar(_("Selecciona primero una etiqueta para renombrarla."))
            return
        dlg = wx.TextEntryDialog(
            self, _("Nuevo nombre de la etiqueta:"), _("Renombrar etiqueta"), value=etiqueta["nombre"]
        )
        if dlg.ShowModal() == wx.ID_OK:
            nuevo_nombre = dlg.GetValue().strip()
            if nuevo_nombre and self.gestor.renombrar_etiqueta(etiqueta["id"], nuevo_nombre):
                reproducir(SUCCESS)
                voz.hablar(_("Etiqueta renombrada a {nombre}.").format(nombre=nuevo_nombre))
                self._cargar_lista_etiquetas(id_etiqueta_seleccionar=etiqueta["id"])
                self._cargar_libros()
            elif nuevo_nombre:
                reproducir(ERROR)
                wx.MessageBox(
                    _("Ya existe una etiqueta con ese nombre."), _("No se pudo renombrar"),
                    wx.OK | wx.ICON_WARNING,
                )
        dlg.Destroy()

    def al_eliminar_etiqueta_seleccionada(self):
        etiqueta = self._etiqueta_seleccionada()
        if etiqueta is None:
            return
        if wx.MessageBox(
            _("¿Eliminar la etiqueta «{nombre}»?\n\n"
              "Los libros no se eliminan, solo dejan de tener esta etiqueta.").format(nombre=etiqueta["nombre"]),
            _("Eliminar etiqueta"), wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.eliminar_etiqueta(etiqueta["id"])
        reproducir(SUCCESS)
        voz.hablar(_("Etiqueta {nombre} eliminada.").format(nombre=etiqueta["nombre"]))
        self._cargar_lista_etiquetas()
        self._cargar_libros()

    def al_nueva_etiqueta(self, evento):
        dlg = wx.TextEntryDialog(self, _("Nombre de la nueva etiqueta:"), _("Nueva etiqueta"))
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                id_nueva = self.gestor.crear_etiqueta(nombre)
                reproducir(SUCCESS)
                voz.hablar(_("Etiqueta {nombre} creada.").format(nombre=nombre))
                self._cargar_lista_etiquetas(id_etiqueta_seleccionar=id_nueva)
        dlg.Destroy()

    def al_menu_contextual_etiquetas(self, evento):
        etiqueta = self._etiqueta_seleccionada()
        menu = wx.Menu()

        item_nueva = menu.Append(wx.ID_ANY, _("Nueva etiqueta..."))
        self.Bind(wx.EVT_MENU, self.al_nueva_etiqueta, item_nueva)

        if etiqueta is not None:
            libros_de_la_etiqueta = self.gestor.buscar_libros(id_etiqueta=etiqueta["id"])
            etiqueta_menu = _("Asignar categoría a los {n} libro(s) de esta etiqueta").format(
                n=len(libros_de_la_etiqueta)
            )
            estado_menu = _("Marcar los {n} libro(s) de esta etiqueta como").format(
                n=len(libros_de_la_etiqueta)
            )
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

        item_renombrar = menu.Append(wx.ID_ANY, _("Renombrar\tF2"))
        item_renombrar.Enable(etiqueta is not None)
        self.Bind(wx.EVT_MENU, lambda e: self.al_renombrar_etiqueta_seleccionada(), item_renombrar)

        item_eliminar = menu.Append(wx.ID_ANY, _("Eliminar...\tSupr"))
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
            solo_pendientes=(estado == "Pendientes de leer"),
            solo_leyendo=(estado == "Leyendo ahora"),
            solo_leidos=(estado == "Leídos"),
        )
        self._ids_audiolibro_pendiente = self.gestor.obtener_ids_libros_con_exportacion_pendiente()
        if estado == "Audiolibros a medias":
            libros = [l for l in libros if l["id"] in self._ids_audiolibro_pendiente]
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
            estado_txt = self._describir_estado(
                libro, libro["id"] in self._ids_audiolibro_pendiente
            )

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

        self.lbl_estado.SetLabel(_("{n} libro(s) en la biblioteca.").format(n=len(libros)))

    @staticmethod
    def _describir_estado(libro, tiene_audiolibro_pendiente=False) -> str:
        partes = []
        if libro["favorito"]:
            partes.append(_("Favorito"))
        if libro["leyendo_ahora"]:
            partes.append(_("Leyendo"))
        elif libro["en_pendientes"]:
            partes.append(_("Pendiente de leer"))
        elif libro["leido"]:
            partes.append(_("Leído"))
        if not libro["titulo_revisado"]:
            partes.append(_("Título sin revisar"))
        if tiene_audiolibro_pendiente:
            partes.append(_("Audiolibro a medias"))
        return ", ".join(partes) if partes else _("Sin marcar")

    def al_cambiar_filtro(self, evento):
        self._cargar_libros()
        evento.Skip()

    def _libro_seleccionado(self):
        indice = self.lista_libros.GetFirstSelected()
        if indice == -1:
            # Tras recargar la lista (Freeze/DeleteAllItems/Thaw en
            # _cargar_libros), puede quedar un ítem con el foco de
            # teclado pero sin marca de selección — GetFirstSelected()
            # no lo ve, GetFocusedItem() sí. Sin este respaldo, abrir el
            # Asistente de Biblioteca con un libro visiblemente
            # enfocado podía acabar en modo general por error.
            indice = self.lista_libros.GetFocusedItem()
        if indice == -1 or indice >= len(self._libros_actuales):
            return None
        return self._libros_actuales[indice]

    # ── Importación de carpetas ──────────────────────────────────────────────

    def al_importar_carpeta(self, evento):
        with wx.DirDialog(
            self, _("Seleccionar carpeta con libros para importar"),
            defaultPath=self._cargar_ultima_carpeta_importada(),
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            carpeta = dlg.GetPath()
        self._guardar_ultima_carpeta_importada(carpeta)

        usar_subcarpetas = wx.MessageBox(
            _("¿Las subcarpetas de esta carpeta representan géneros y subgéneros?\n\n"
              "Ejemplo: «Fantasía/Fantasía épica/tu_libro.epub» crearía la categoría "
              "«Fantasía» con la subcategoría «Fantasía épica».\n\n"
              "Podrás renombrar o mover las categorías después. Si tus subcarpetas "
              "no son géneros (por ejemplo, son autores o sagas), elige No."),
            _("¿Crear categorías desde las subcarpetas?"), wx.YES_NO | wx.ICON_QUESTION,
        ) == wx.YES

        voz.hablar(_("Escaneando carpeta, por favor espera..."))
        self._modo_progreso = "escaneo"
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

    def al_importar_archivo(self, evento=None):
        """
        Añade un único archivo EPUB o PDF a la Biblioteca, sin pasar por el
        escáner de carpetas (pensado para 500 libros a la vez, no para uno
        suelto). Reutiliza _procesar_archivo() y insertar_libros_lote(), la
        misma lógica de extracción de metadatos e inserción que usa
        EscanerBiblioteca, para no duplicarla.
        """
        with wx.FileDialog(
            self, _("Seleccionar libro a importar"),
            wildcard=_(
                "Libros compatibles (*.epub;*.pdf)|*.epub;*.pdf|"
                "Archivos EPUB (*.epub)|*.epub|Archivos PDF (*.pdf)|*.pdf"
            ),
            style=wx.FD_OPEN,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            ruta = dlg.GetPath()

        if ruta in self.gestor.obtener_rutas_indexadas():
            reproducir(ERROR)
            self._anunciar(_("Ese libro ya está en la Biblioteca."))
            return

        resultado = _procesar_archivo(ruta)
        if resultado is None:
            reproducir(ERROR)
            wx.MessageBox(
                _("No se pudieron leer los metadatos de ese archivo."),
                _("Error al importar"), wx.OK | wx.ICON_ERROR,
            )
            return

        self.gestor.insertar_libros_lote([resultado])
        reproducir(SUCCESS)
        self._anunciar(_("Libro añadido a la Biblioteca: {titulo}.").format(titulo=resultado["titulo"]))
        self._cargar_libros()

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
        self.lbl_estado.SetLabel(
            _("Escaneando... {procesados} de {total} libro(s) procesados.").format(
                procesados=procesados, total=total
            )
        )

    def al_temporizador_progreso(self, evento):
        procesados, total = self._progreso_actual
        if total <= 0:
            return
        if self._modo_progreso == "agrupando":
            self._voz.hablar(
                _("Aplicando etiquetas... {procesados} de {total} carpetas.").format(
                    procesados=procesados, total=total
                )
            )
        else:
            self._voz.hablar(
                _("Procesando... {procesados} de {total} libros.").format(
                    procesados=procesados, total=total
                )
            )

    def _al_detectar_carpetas_agrupables(self, carpetas_candidatas: dict):
        evaluadas = self._cargar_carpetas_evaluadas()
        candidatas_nuevas = {
            carpeta: titulos
            for carpeta, titulos in carpetas_candidatas.items()
            if os.path.normpath(carpeta) not in evaluadas
        }
        if not candidatas_nuevas:
            return

        nombres_sugeridos = {
            carpeta: os.path.basename(os.path.normpath(carpeta))
            for carpeta in candidatas_nuevas
        }
        dlg = DialogoAgruparCarpetas(self, candidatas_nuevas, nombres_sugeridos)
        resultado_modal = dlg.ShowModal()
        if resultado_modal != wx.ID_OK:
            # Diálogo cancelado por completo: no se registra ninguna
            # carpeta como evaluada, se volverá a preguntar la próxima vez.
            self._ultima_etiqueta_creada = None
            dlg.Destroy()
            return

        # Las carpetas mostradas (marcadas o no) quedan registradas como
        # evaluadas: no se vuelve a preguntar por ellas en futuros
        # escaneos, se hayan agrupado o no (sección 2.3.1).
        self._marcar_carpetas_evaluadas(dlg.carpetas_mostradas)
        carpetas_a_agrupar = dlg.resultado
        dlg.Destroy()

        if not carpetas_a_agrupar:
            self._ultima_etiqueta_creada = None
            return

        # Entre que se confirma y se termina de etiquetar puede pasar un
        # rato perceptible con muchas carpetas — sin este aviso, NVDA se
        # queda en silencio y parece que la app se ha colgado. El
        # etiquetado en sí se hace en un hilo de fondo (ver
        # _agrupar_carpetas_en_hilo) para no bloquear la interfaz. Igual
        # que en el escaneo, la barra y el aviso periódico por temporizador
        # cubren el hueco mientras dura (antes solo había este aviso inicial
        # y el de "Etiquetas aplicadas" al final, sin nada en medio).
        voz.hablar(_("Aplicando etiquetas, por favor espera..."))
        self._modo_progreso = "agrupando"
        self._progreso_actual = (0, len(carpetas_a_agrupar))
        self.barra_progreso.SetRange(len(carpetas_a_agrupar))
        self.barra_progreso.SetValue(0)
        self.barra_progreso.Show()
        self.Layout()
        self._timer_progreso.Start(2500)
        self._ultima_etiqueta_creada = next(iter(carpetas_a_agrupar.values()), None)
        threading.Thread(
            target=self._agrupar_carpetas_en_hilo,
            args=(
                {carpeta: candidatas_nuevas[carpeta] for carpeta in carpetas_a_agrupar},
                carpetas_a_agrupar,
            ),
            name="agrupar_por_carpeta",
            daemon=True,
        ).start()

    def _agrupar_carpetas_en_hilo(self, carpetas_candidatas: dict, nombres_sugeridos: dict):
        """
        Etiqueta cada carpeta candidata en un hilo de fondo. Un fallo en
        una carpeta concreta (registrado por confirmar_agrupamiento_por_
        carpeta) nunca detiene el resto; y si el hilo entero revienta por
        algo inesperado, el except de aquí garantiza que igualmente se
        llegue al callback de finalización en vez de dejar a NVDA
        colgado en silencio para siempre.
        """
        total = len(carpetas_candidatas)
        procesadas = 0
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
                finally:
                    procesadas += 1
                    wx.CallAfter(self._al_progresar_agrupamiento, procesadas, total)
        except Exception:
            logger.exception("[PestanaBiblioteca] Fallo inesperado al agrupar por carpeta")
        finally:
            wx.CallAfter(self._al_terminar_agrupamiento, total_fallos)

    def _al_progresar_agrupamiento(self, procesadas, total):
        # Mismo criterio que _al_progresar_escaneo: solo actualiza el
        # estado visual aquí, el aviso de voz va aparte por temporizador.
        self._progreso_actual = (procesadas, total)
        if total > 0:
            self.barra_progreso.SetRange(total)
            self.barra_progreso.SetValue(min(procesadas, total))
        self.lbl_estado.SetLabel(
            _("Aplicando etiquetas... {procesadas} de {total} carpeta(s).").format(
                procesadas=procesadas, total=total
            )
        )

    def _al_terminar_agrupamiento(self, total_fallos: int):
        self._timer_progreso.Stop()
        self.barra_progreso.Hide()
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
            voz.hablar(
                _("Etiquetas aplicadas, pero {n} libro(s) no se pudieron etiquetar.").format(
                    n=total_fallos
                )
            )
        else:
            reproducir(SUCCESS)
            voz.hablar(_("Etiquetas aplicadas."))

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
            mensaje = _("Se han añadido {n} libro(s) a la biblioteca.").format(n=total_insertados)
        else:
            mensaje = _("No se encontraron libros nuevos en esa carpeta.")
        voz.hablar(mensaje)
        wx.MessageBox(mensaje, _("Escaneo completado"), wx.OK | wx.ICON_INFORMATION)

    def _al_fallar_escaneo(self, error):
        self._timer_progreso.Stop()
        reproducir(ERROR)
        self.barra_progreso.Hide()
        self.Layout()
        wx.MessageBox(
            _("No se pudo completar el escaneo:\n{error}").format(error=error),
            _("Error"), wx.OK | wx.ICON_ERROR,
        )

    # ── Acciones sobre el libro seleccionado ─────────────────────────────────

    def al_anunciar_info_libro(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            self._anunciar(_("No hay ningún libro seleccionado."))
            return
        autores = self.gestor.obtener_autores_de_libro(libro["id"])
        nombres_autores = ", ".join(a["nombre"] for a in autores) or _("autor desconocido")
        pendiente = bool(self.gestor.obtener_exportaciones_pendientes(libro["id"]))
        estado = self._describir_estado(libro, pendiente)
        self._anunciar(
            "{titulo}, {autores}, {formato}, {estado}.".format(
                titulo=libro["titulo"], autores=nombres_autores,
                formato=libro["formato"].upper(), estado=estado,
            )
        )

    # ANCLAJE_INICIO: ABRIR_ASISTENTE_BIBLIOTECA
    def al_abrir_asistente_biblioteca(self, evento):
        from app.interfaz.dialogo_asistente_biblioteca import DialogoAsistenteBiblioteca

        libro = self._libro_seleccionado()
        contexto_libro = None
        if libro is not None:
            autores = self.gestor.obtener_autores_de_libro(libro["id"])
            nombres_autores = ", ".join(a["nombre"] for a in autores) or None
            categorias = self.gestor.obtener_categorias_de_libro(libro["id"])
            etiquetas = self.gestor.obtener_etiquetas_de_libro(libro["id"])
            nombres_categoria = ", ".join(
                c["nombre"] for c in list(categorias) + list(etiquetas)
            ) or None
            pendiente = bool(self.gestor.obtener_exportaciones_pendientes(libro["id"]))
            contexto_libro = {
                "id_libro": libro["id"],
                "tipo": "libro",
                "titulo": libro["titulo"],
                "autor": nombres_autores,
                "categoria": nombres_categoria,
                "estado": self._describir_estado(libro, pendiente),
            }
        elif self._id_etiqueta_activa is not None:
            # Sin libro concreto seleccionado pero con una saga activa en
            # el panel izquierdo (lista_etiquetas): se manda esa saga como
            # contexto en vez de caer directo a modo general.
            contexto_libro = self._contexto_saga(self._id_etiqueta_activa)
        elif self._id_categoria_activa is not None:
            contexto_libro = self._contexto_categoria(self._id_categoria_activa)
        else:
            # Modo totalmente general: sin libro, saga ni categoría
            # concretos, se manda un resumen agregado de toda la
            # Biblioteca (géneros y autores más frecuentes, sagas,
            # conteos de favoritos/leídos/pendientes) para que el
            # asistente conozca los gustos del usuario incluso sin
            # selección. Se calcula al vuelo desde biblioteca.db en cada
            # apertura, así que altas y bajas de libros ya se reflejan
            # solas, sin nada que mantener sincronizado aparte.
            contexto_libro = self._contexto_resumen_biblioteca()

        dlg = DialogoAsistenteBiblioteca(self, contexto_libro)
        dlg.ShowModal()
        dlg.Destroy()

    def _resumen_titulos(self, libros, limite=15):
        titulos = [l["titulo"] for l in libros]
        resumen = _("{n} libro(s): ").format(n=len(titulos)) + ", ".join(titulos[:limite])
        if len(titulos) > limite:
            resumen += ", ..."
        return resumen

    def _contexto_saga(self, id_etiqueta):
        nombre = next(
            (e["nombre"] for e in self._etiquetas_indice if e["id"] == id_etiqueta), None
        )
        if nombre is None:
            return None
        libros = self.gestor.buscar_libros(id_etiqueta=id_etiqueta)
        return {
            "id_libro": f"etiqueta:{id_etiqueta}",
            "tipo": "saga",
            "titulo": _("Saga: {nombre}").format(nombre=nombre),
            "autor": None,
            "categoria": None,
            "estado": self._resumen_titulos(libros),
        }

    def _contexto_categoria(self, id_categoria):
        try:
            nodo = self.arbol_categorias.GetSelection()
            nombre = self.arbol_categorias.GetItemText(nodo).rsplit(" (", 1)[0]
        except RuntimeError:
            logger.debug("Árbol de categorías ya destruido al obtener contexto para el Asistente", exc_info=True)
            return None
        libros = self.gestor.buscar_libros(id_categoria=id_categoria)
        return {
            "id_libro": f"categoria:{id_categoria}",
            "tipo": "categoria",
            "titulo": _("Género: {nombre}").format(nombre=nombre),
            "autor": None,
            "categoria": None,
            "estado": self._resumen_titulos(libros),
        }

    def _contexto_resumen_biblioteca(self):
        resumen = self.gestor.resumen_para_asistente()
        if resumen["total"] == 0:
            return None
        partes = [
            _(
                "{total} libro(s) en total "
                "({favoritos} favorito(s), {leidos} leído(s), "
                "{pendientes} pendiente(s), {leyendo} en curso)."
            ).format(
                total=resumen["total"], favoritos=resumen["favoritos"],
                leidos=resumen["leidos"], pendientes=resumen["pendientes"],
                leyendo=resumen["leyendo"],
            )
        ]
        if resumen["generos_frecuentes"]:
            nombres = ", ".join(f"{g['nombre']} ({g['total']})" for g in resumen["generos_frecuentes"])
            partes.append(_("Géneros más frecuentes: {nombres}.").format(nombres=nombres))
        if resumen["autores_frecuentes"]:
            nombres = ", ".join(f"{a['nombre']} ({a['total']})" for a in resumen["autores_frecuentes"])
            partes.append(_("Autores más frecuentes: {nombres}.").format(nombres=nombres))
        if resumen["sagas"]:
            nombres = ", ".join(f"{s['nombre']} ({s['total']})" for s in resumen["sagas"])
            partes.append(_("Sagas en la Biblioteca: {nombres}.").format(nombres=nombres))
        return {
            "id_libro": None,
            "tipo": "resumen",
            "titulo": _("tu Biblioteca"),
            "autor": None,
            "categoria": None,
            "estado": " ".join(partes),
            "catalogo": self._catalogo_completo_texto(),
        }

    def _catalogo_completo_texto(self):
        """
        Listado título/autor/saga de toda la Biblioteca, en texto plano
        separado por punto y coma — para que el Asistente sepa con certeza
        qué libros y sagas tienes, en vez de solo los más frecuentes del
        resumen agregado de arriba (por eso a veces decía que no tenías una
        saga que sí tenías: solo veía las más repetidas, no todas).
        """
        catalogo = self.gestor.catalogo_para_asistente()
        lineas = []
        for libro in catalogo["libros"]:
            partes_libro = [libro["titulo"]]
            if libro.get("autores"):
                partes_libro.append(libro["autores"])
            if libro.get("sagas"):
                partes_libro.append(_("Saga: {nombre}").format(nombre=libro["sagas"]))
            lineas.append(" — ".join(partes_libro))
        texto = "; ".join(lineas)
        if catalogo["total"] > len(catalogo["libros"]):
            texto += _("; ... y {n} libro(s) más.").format(
                n=catalogo["total"] - len(catalogo["libros"])
            )
        return texto
    # ANCLAJE_FIN: ABRIR_ASISTENTE_BIBLIOTECA

    def al_alternar_favorito(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        nuevo_valor = not bool(libro["favorito"])
        self.gestor.establecer_bandera(libro["id"], "favorito", nuevo_valor)
        self._anunciar(_("Marcado como favorito.") if nuevo_valor else _("Quitado de favoritos."))
        self._cargar_libros()

    def _alternar_estado_libro(self, campo, nombre_al_marcar, nombre_al_quitar):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        nuevo_valor = not bool(libro[campo])
        self.gestor.establecer_bandera(libro["id"], campo, nuevo_valor)
        mensaje = (
            _("Marcado como {nombre}.").format(nombre=nombre_al_marcar) if nuevo_valor
            else _("Quitado de {nombre}.").format(nombre=nombre_al_quitar)
        )
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
            ("en_pendientes", _("Pendiente de leer"), _("pendientes de leer")),
            ("leyendo_ahora", _("Leyendo ahora"), _("leyendo ahora")),
            ("leido", _("Leído"), _("leídos")),
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
        self._anunciar(_("{n} libro(s) marcados como {estado}.").format(n=len(libros), estado=nombre_plural))
        self._cargar_libros()

    def al_abrir_libro_seleccionado(self, evento=None):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        if not os.path.exists(libro["ruta_archivo"]):
            self._al_archivo_no_encontrado(libro)
            return
        voz.hablar(_("Abriendo libro, por favor espera..."))
        self._anunciar(_("Abriendo libro, por favor espera..."))

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

    def al_enviar_a_creador_audiolibros(self):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        if not os.path.exists(libro["ruta_archivo"]):
            self._al_archivo_no_encontrado(libro)
            return

        autores = self.gestor.obtener_autores_de_libro(libro["id"])
        nombres_autores = ", ".join(a["nombre"] for a in autores)

        datos_libro = {
            "id": libro["id"],
            "titulo": libro["titulo"],
            "autor": nombres_autores,
            "formato": libro["formato"],
            "ruta_archivo": libro["ruta_archivo"],
        }

        ventana_principal = self.padre_notebook.GetParent()
        try:
            from app.interfaz.ventana_principal import IDX_CREADOR
            self.padre_notebook.SetSelection(IDX_CREADOR)
            ventana_principal.pestana_creador.cargar_libro(datos_libro)
        except Exception:
            logger.exception(
                "[PestanaBiblioteca] No se pudo enviar el libro al Creador de Audiolibros"
            )
            reproducir(ERROR)

    def _al_abrir_reglas_pronunciacion(self, libro):
        ventana_principal = self.padre_notebook.GetParent()
        try:
            from app.interfaz.ventana_principal import IDX_AJUSTES
            self.padre_notebook.SetSelection(IDX_AJUSTES)
            ventana_principal.pestana_ajustes.abrir_diccionario_para_libro(libro["id"])
        except Exception:
            logger.exception("[PestanaBiblioteca] No se pudo abrir el diccionario para el libro")
            reproducir(ERROR)

    def _al_archivo_no_encontrado(self, libro):
        """
        Diálogo de re-enrutado (sección 2.4 de la planificación v3.0):
        localizar el archivo manualmente, reconciliar en bloque una
        carpeta movida, o eliminar el libro de la biblioteca.
        """
        extension = os.path.splitext(libro["ruta_archivo"])[1] or f".{libro['formato']}"
        dlg = DialogoArchivoNoEncontrado(self, libro["titulo"], extension)
        if dlg.ShowModal() != wx.ID_OK or dlg.accion is None:
            dlg.Destroy()
            return

        if dlg.accion == "localizar":
            if relocalizar_libro(self.gestor, libro["id"], dlg.ruta_localizada):
                reproducir(SUCCESS)
                self._anunciar(_("Archivo localizado. Abriendo el libro."))
                self._cargar_libros()
                libro_actualizado = self.gestor.obtener_libro(libro["id"])
                dlg.Destroy()
                if libro_actualizado is not None:
                    self.al_abrir_libro_seleccionado()
                return
            reproducir(ERROR)
            self._anunciar(_("No se pudo localizar el archivo indicado."))

        elif dlg.accion == "reescanear":
            reconciliados = reconciliar_carpeta_movida(self.gestor, dlg.carpeta_reescaneo)
            reproducir(SUCCESS if reconciliados else ERROR)
            self._anunciar(
                _("{n} libro(s) reconciliados con la nueva carpeta.").format(n=reconciliados)
                if reconciliados else
                _("No se encontró ningún libro de la biblioteca en esa carpeta.")
            )
            self._cargar_libros()

        elif dlg.accion == "eliminar":
            self.gestor.quitar_libro(libro["id"])
            reproducir(SUCCESS)
            self._anunciar(_("Libro quitado de la biblioteca."))
            self._cargar_libros()

        dlg.Destroy()

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
            _("¿Quitar «{titulo}» de la biblioteca?\n\n"
              "El archivo no se borrará del disco, solo su registro aquí.").format(titulo=libro["titulo"]),
            _("Quitar de la biblioteca"), wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.quitar_libro(libro["id"])
        self._anunciar(_("Libro quitado de la biblioteca."))
        self._cargar_libros()

    def al_renombrar_segun_metadatos(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        dlg = wx.TextEntryDialog(
            self,
            _("Nombre de archivo propuesto (editable):"),
            _("Renombrar archivo (F2)"),
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
            self._anunciar(_("Archivo renombrado correctamente."))
        else:
            reproducir(ERROR)
            wx.MessageBox(
                _("No se pudo renombrar el archivo:\n{motivo}").format(motivo=resultado.motivo_fallo),
                _("Error al renombrar"), wx.OK | wx.ICON_ERROR,
            )
        self._cargar_libros()

    def al_renombrar_todos_pendientes(self, evento):
        pendientes = self.gestor.obtener_pendientes_de_revision()
        if not pendientes:
            self._anunciar(_("No hay libros pendientes de revisión."))
            return

        cambios = [{"id_libro": p["id"], "titulo_nuevo": p["titulo"]} for p in pendientes]
        exitosos, fallidos = renombrar_pendientes_por_lote(self.gestor, cambios)

        mensaje = _("{exitosos} de {total} archivos renombrados correctamente.").format(
            exitosos=len(exitosos), total=len(cambios)
        )
        if fallidos:
            detalle = "\n".join(f"· {f.titulo_anterior}: {f.motivo_fallo}" for f in fallidos)
            mensaje += _("\n\nNo se pudieron renombrar:\n{detalle}").format(detalle=detalle)
        wx.MessageBox(mensaje, _("Renombrado por lotes"), wx.OK | wx.ICON_INFORMATION)
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
        item_nueva = menu.Append(wx.ID_ANY, _("Crear categoría nueva y asignar..."))
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
            item_aqui = submenu.Append(wx.ID_ANY, _("Asignar a «{nombre}»").format(nombre=categoria["nombre"]))
            self.Bind(
                wx.EVT_MENU,
                lambda e, id_cat=categoria["id"]: self.al_asignar_categoria_existente(
                    libros, id_cat
                ),
                item_aqui,
            )
            submenu.AppendSeparator()
            item_nueva_sub = submenu.Append(wx.ID_ANY, _("Crear subcategoría nueva y asignar..."))
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
        item_nueva = menu.Append(wx.ID_ANY, _("Crear etiqueta nueva y asignar..."))
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
        voz.hablar(_("Añadido a etiqueta {nombre}.").format(nombre=nombre))
        self._cargar_lista_etiquetas(id_etiqueta_seleccionar=self._id_etiqueta_activa)
        self._cargar_libros()

    def al_crear_etiqueta_y_asignar(self, libro):
        dlg = wx.TextEntryDialog(self, _("Nombre de la nueva etiqueta:"), _("Crear etiqueta y asignar"))
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                self.gestor.asignar_etiqueta(libro["id"], nombre)
                reproducir(SUCCESS)
                voz.hablar(_("Etiqueta {nombre} creada y libro añadido.").format(nombre=nombre))
                self._cargar_lista_etiquetas(id_etiqueta_seleccionar=self._id_etiqueta_activa)
                self._cargar_libros()
        dlg.Destroy()

    def al_quitar_de_etiqueta_actual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None or self._id_etiqueta_activa is None:
            return
        self.gestor.quitar_etiqueta_de_libro(libro["id"], self._id_etiqueta_activa)
        reproducir(SUCCESS)
        voz.hablar(_("Libro quitado de esta etiqueta."))
        self._cargar_libros()

    def al_asignar_categoria_existente(self, libros, id_categoria):
        ruta = self.gestor.obtener_ruta_categoria(id_categoria)
        for libro in libros:
            self.gestor.asignar_categoria_por_ruta(libro["id"], ruta)
        reproducir(SUCCESS)
        if len(libros) == 1:
            voz.hablar(_("Añadido a categoría {ruta}.").format(ruta=" > ".join(ruta)))
        else:
            voz.hablar(
                _("{n} libros añadidos a categoría {ruta}.").format(n=len(libros), ruta=" > ".join(ruta))
            )
        self._cargar_arbol_categorias(id_categoria_seleccionar=self._id_categoria_activa)
        self._cargar_libros()

    def al_crear_categoria_y_asignar(self, libros, id_padre):
        dlg = wx.TextEntryDialog(
            self,
            _("Nombre de la nueva categoría:"),
            _("Crear categoría y asignar"),
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
                    voz.hablar(_("Categoría {nombre} creada y libro añadido.").format(nombre=nombre))
                else:
                    voz.hablar(
                        _("Categoría {nombre} creada y {n} libros añadidos.").format(
                            nombre=nombre, n=len(libros)
                        )
                    )
                self._cargar_arbol_categorias(id_categoria_seleccionar=self._id_categoria_activa)
                self._cargar_libros()
        dlg.Destroy()

    def al_quitar_de_categoria_actual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None or self._id_categoria_activa is None:
            return
        self.gestor.quitar_categoria_de_libro(libro["id"], self._id_categoria_activa)
        reproducir(SUCCESS)
        self._anunciar(_("Libro quitado de esta categoría."))
        self._cargar_libros()

    # ── Menú contextual ──────────────────────────────────────────────────────

    def al_menu_contextual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return

        menu = wx.Menu()

        item_abrir = menu.Append(wx.ID_ANY, _("Abrir en Lectura\tIntro"))
        self.Bind(wx.EVT_MENU, lambda e: self.al_abrir_libro_seleccionado(), item_abrir)

        item_creador = menu.Append(wx.ID_ANY, _("Enviar a Creador de Audiolibros"))
        item_creador.SetHelp(
            _("Cambia a la pestaña Creador de Audiolibros con este libro ya cargado.")
        )
        self.Bind(wx.EVT_MENU, lambda e: self.al_enviar_a_creador_audiolibros(), item_creador)

        menu.AppendSeparator()

        item_favorito = menu.Append(
            wx.ID_ANY, _("Quitar de favoritos") if libro["favorito"] else _("Marcar como favorito")
        )
        self.Bind(wx.EVT_MENU, self.al_alternar_favorito, item_favorito)

        item_pendiente = menu.Append(
            wx.ID_ANY,
            _("Quitar de pendientes de leer") if libro["en_pendientes"]
            else _("Marcar como pendiente de leer"),
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._alternar_estado_libro(
                "en_pendientes", _("pendiente de leer"), _("pendientes de leer")
            ),
            item_pendiente,
        )

        item_leyendo = menu.Append(
            wx.ID_ANY,
            _("Quitar de leyendo ahora") if libro["leyendo_ahora"] else _("Marcar como leyendo ahora"),
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._alternar_estado_libro(
                "leyendo_ahora", _("leyendo ahora"), _("leyendo ahora")
            ),
            item_leyendo,
        )

        item_leido = menu.Append(
            wx.ID_ANY, _("Quitar de leídos") if libro["leido"] else _("Marcar como leído")
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._alternar_estado_libro("leido", _("leído"), _("leídos")),
            item_leido,
        )

        menu.AppendSubMenu(self.construir_menu_asignar_categoria(libro), _("Añadir a categoría"))

        item_quitar_cat = menu.Append(wx.ID_ANY, _("Quitar de esta categoría"))
        item_quitar_cat.Enable(self._id_categoria_activa is not None)
        self.Bind(wx.EVT_MENU, self.al_quitar_de_categoria_actual, item_quitar_cat)

        menu.AppendSubMenu(self.construir_menu_asignar_etiqueta(libro), _("Añadir a etiqueta"))

        item_quitar_etq = menu.Append(wx.ID_ANY, _("Quitar de esta etiqueta"))
        item_quitar_etq.Enable(self._id_etiqueta_activa is not None)
        self.Bind(wx.EVT_MENU, self.al_quitar_de_etiqueta_actual, item_quitar_etq)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, _("Renombrar archivo...\tF2"))
        self.Bind(wx.EVT_MENU, self.al_renombrar_segun_metadatos, item_renombrar)

        item_renombrar_pendientes = menu.Append(
            wx.ID_ANY, _("Renombrar todos los pendientes de revisión...")
        )
        item_renombrar_pendientes.SetHelp(
            _("Renombra en bloque, según sus metadatos, todos los libros de la "
              "biblioteca cuyo nombre de archivo no coincide con el título real.")
        )
        self.Bind(wx.EVT_MENU, self.al_renombrar_todos_pendientes, item_renombrar_pendientes)

        item_reglas_pronunciacion = menu.Append(
            wx.ID_ANY, _("Reglas de pronunciación de este libro...")
        )
        item_reglas_pronunciacion.SetHelp(
            _("Abre Ajustes en el diccionario de pronunciación, ya en alcance "
              "'Este libro' y con este libro seleccionado.")
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._al_abrir_reglas_pronunciacion(libro),
            item_reglas_pronunciacion,
        )

        item_quitar = menu.Append(wx.ID_ANY, _("Quitar de la biblioteca"))
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
        ventana_principal._agregar_item_asistente_biblioteca(menu)
        ventana_principal._submenu_ayuda(menu)
        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, _("Salir"))
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

    # ANCLAJE_INICIO: CARPETAS_AGRUPACION_EVALUADAS
    _RUTA_CARPETAS_EVALUADAS = staticmethod(lambda: ruta_config("carpetas_agrupacion_evaluadas.json"))

    def _cargar_carpetas_evaluadas(self) -> set:
        """
        Carpetas que ya se ofrecieron para agrupar por saga (aceptadas o
        descartadas explícitamente), para no volver a preguntar por ellas
        en escaneos posteriores (sección 2.3.1 de la planificación v3.0).
        """
        try:
            ruta = self._RUTA_CARPETAS_EVALUADAS()
            if os.path.exists(ruta):
                with open(ruta, "r", encoding="utf-8") as f:
                    return set(json.load(f))
        except Exception:
            logger.exception("[PestanaBiblioteca] No se pudo leer carpetas_agrupacion_evaluadas.json")
        return set()

    def _marcar_carpetas_evaluadas(self, carpetas):
        try:
            ruta = self._RUTA_CARPETAS_EVALUADAS()
            evaluadas = self._cargar_carpetas_evaluadas()
            evaluadas.update(os.path.normpath(carpeta) for carpeta in carpetas)
            os.makedirs(CONFIG_DIR, exist_ok=True)
            ruta_temporal = ruta + ".tmp"
            with open(ruta_temporal, "w", encoding="utf-8") as f:
                json.dump(sorted(evaluadas), f, ensure_ascii=False, indent=4)
            os.replace(ruta_temporal, ruta)
        except Exception:
            logger.exception("[PestanaBiblioteca] No se pudo guardar carpetas_agrupacion_evaluadas.json")
    # ANCLAJE_FIN: CARPETAS_AGRUPACION_EVALUADAS
# ANCLAJE_FIN: DEFINICION_PESTANA_BIBLIOTECA
