# ANCLAJE_INICIO: DEPENDENCIAS_BIBLIOTECA
import wx
import os
import logging

from app.motor.gestor_biblioteca import GestorBiblioteca
from app.motor.escaner_biblioteca import EscanerBiblioteca, confirmar_agrupamiento_por_carpeta
from app.motor.renombrador_biblioteca import (
    renombrar_libro_segun_metadatos,
    renombrar_pendientes_por_lote,
)
from app.motor.reproductor_sonidos import (
    reproducir, SUCCESS, ERROR, LIST_NAV, MOVE_UP, MOVE_DOWN, CLEAR,
)
# ANCLAJE_FIN: DEPENDENCIAS_BIBLIOTECA

logger = logging.getLogger(__name__)


# ANCLAJE_INICIO: DEFINICION_PESTANA_BIBLIOTECA
class PestanaBiblioteca(wx.Panel):
    """
    Pestaña de la Biblioteca: importación, filtrado, árbol de categorías
    (géneros/subgéneros) y gestión de la colección de EPUB y PDF
    indexada en biblioteca.db.
    """

    _SENTINEL_TODAS = -1  # id_categoria virtual para "sin filtro de categoría"

    def __init__(self, padre):
        super().__init__(padre)
        self.padre_notebook = padre

        self.gestor = GestorBiblioteca()
        self.escaner = None
        self._libros_actuales = []
        self._id_categoria_activa = None
        self._categoria_en_portapapeles = None

        self._configurar_interfaz()
        self._configurar_atajos()

        self._progreso_actual = (0, 0)
        self._timer_progreso = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.al_temporizador_progreso, self._timer_progreso)

        wx.CallAfter(self._cargar_arbol_categorias)
        wx.CallAfter(self._cargar_libros)

    # ── Construcción de la interfaz ─────────────────────────────────────────

    def _configurar_interfaz(self):
        sizer_principal = wx.BoxSizer(wx.HORIZONTAL)

        # ── Panel izquierdo: árbol de categorías ─────────────────────────
        sizer_izquierdo = wx.BoxSizer(wx.VERTICAL)
        sizer_izquierdo.Add(
            wx.StaticText(self, label="Categorías (géneros):"), 0, wx.ALL, 5
        )
        self.arbol_categorias = wx.TreeCtrl(
            self,
            style=(
                wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE
                | wx.TR_HIDE_ROOT | wx.TR_EDIT_LABELS
            ),
        )
        self.arbol_categorias.SetHelpText(
            "Árbol de géneros y subgéneros. Flechas para navegar; seleccionar "
            "un nodo filtra la lista de libros por esa categoría (incluye "
            "subgéneros). F2 renombra, Supr elimina, Ctrl+X/Ctrl+V mueve un "
            "género bajo otro, Menú o Shift+F10 para más opciones."
        )
        self.arbol_categorias.SetMinSize((220, -1))
        self.arbol_categorias.Bind(wx.EVT_TREE_SEL_CHANGED, self.al_seleccionar_categoria)
        self.arbol_categorias.Bind(wx.EVT_TREE_KEY_DOWN, self.al_tecla_arbol)
        self.arbol_categorias.Bind(wx.EVT_KEY_DOWN, self.al_tecla_arbol_raw)
        self.arbol_categorias.Bind(wx.EVT_TREE_END_LABEL_EDIT, self.al_fin_edicion_categoria)
        self.arbol_categorias.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self.al_clic_derecho_arbol)
        sizer_izquierdo.Add(self.arbol_categorias, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_nueva_categoria = wx.Button(self, label="Nueva categoría...")
        self.btn_nueva_categoria.SetHelpText(
            "Crea una nueva categoría raíz. Para crear una subcategoría, "
            "selecciona primero la categoría padre en el árbol y usa el menú contextual."
        )
        self.btn_nueva_categoria.Bind(wx.EVT_BUTTON, self.al_nueva_categoria_raiz)
        sizer_izquierdo.Add(self.btn_nueva_categoria, 0, wx.EXPAND | wx.ALL, 5)

        sizer_principal.Add(sizer_izquierdo, 1, wx.EXPAND)

        # ── Panel derecho: filtros + lista ───────────────────────────────
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

        # Botón de importación + barra de progreso (visual, oculta hasta escanear)
        sizer_importar = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_importar = wx.Button(self, label="Importar carpeta... (Ctrl+O)")
        self.btn_importar.Bind(wx.EVT_BUTTON, self.al_importar_carpeta)
        sizer_importar.Add(self.btn_importar, 0, wx.ALL, 5)
        self.barra_progreso = wx.Gauge(self, range=100)
        self.barra_progreso.Hide()
        sizer_importar.Add(self.barra_progreso, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_derecho.Add(sizer_importar, 0, wx.EXPAND)

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

        sizer_principal.Add(sizer_derecho, 3, wx.EXPAND)

        self.SetSizer(sizer_principal)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador).
        self._anunciador = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1)
        )
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())

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

    # ── Propiedades para Tab cíclico (usadas por ventana_principal.py) ──────

    @property
    def primer_control(self):
        return self.arbol_categorias

    @property
    def ultimo_control(self):
        return self.lista_libros

    # ── Anuncios de accesibilidad ────────────────────────────────────────────

    def _anunciar(self, texto):
        control_previo = wx.Window.FindFocus()
        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()
        wx.CallLater(300, lambda: control_previo.SetFocus() if control_previo else None)

    # ── Árbol de categorías ──────────────────────────────────────────────────

    def _cargar_arbol_categorias(self, id_categoria_seleccionar=None):
        self.arbol_categorias.Freeze()
        self.arbol_categorias.DeleteAllItems()
        raiz = self.arbol_categorias.AddRoot("Categorías")

        nodo_todas = self.arbol_categorias.AppendItem(raiz, "(Todas las categorías)")
        self.arbol_categorias.SetItemData(nodo_todas, self._SENTINEL_TODAS)

        nodo_a_seleccionar = nodo_todas
        self._construir_nodos_categoria(raiz, None, id_categoria_seleccionar, [nodo_a_seleccionar])

        self.arbol_categorias.ExpandAll()
        self.arbol_categorias.Thaw()
        self.arbol_categorias.SelectItem(nodo_todas)

    def _construir_nodos_categoria(self, nodo_padre, id_categoria_padre, id_buscado, resultado_ref):
        for categoria in self.gestor.listar_categorias_hijas(id_categoria_padre):
            nodo = self.arbol_categorias.AppendItem(nodo_padre, categoria["nombre"])
            self.arbol_categorias.SetItemData(nodo, categoria["id"])
            if id_buscado is not None and categoria["id"] == id_buscado:
                resultado_ref[0] = nodo
            self._construir_nodos_categoria(nodo, categoria["id"], id_buscado, resultado_ref)
        if resultado_ref[0] is not None and self.arbol_categorias.GetItemData(resultado_ref[0]) == id_buscado:
            self.arbol_categorias.SelectItem(resultado_ref[0])

    def _categoria_seleccionada_id(self):
        # EVT_TREE_SEL_CHANGED puede dispararse durante el cierre de la app,
        # después de que el árbol ya fue destruido (comportamiento conocido
        # de wxPython). Sin esta guarda, el evento residual lanza
        # RuntimeError en bucle y bloquea el cierre — mismo problema ya
        # resuelto en ventana_proyectos.py para su propio árbol.
        try:
            nodo = self.arbol_categorias.GetSelection()
        except RuntimeError:
            return None
        if not nodo.IsOk():
            return None
        dato = self.arbol_categorias.GetItemData(nodo)
        return None if dato == self._SENTINEL_TODAS else dato

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
            if codigo == wx.WXK_F2:
                nodo = self.arbol_categorias.GetSelection()
                if nodo.IsOk() and self.arbol_categorias.GetItemData(nodo) != self._SENTINEL_TODAS:
                    self.arbol_categorias.EditLabel(nodo)
            elif codigo == wx.WXK_DELETE:
                self.al_eliminar_categoria(evento)
            else:
                evento.Skip()
        except RuntimeError:
            pass

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
        id_categoria = self.arbol_categorias.GetItemData(nodo)
        if not nuevo_nombre or id_categoria == self._SENTINEL_TODAS:
            evento.Veto()
            return
        if self.gestor.renombrar_categoria(id_categoria, nuevo_nombre):
            reproducir(SUCCESS)
            self._cargar_libros()
        else:
            evento.Veto()
            reproducir(ERROR)
            wx.MessageBox(
                "Ya existe una categoría con ese nombre en el mismo nivel.",
                "No se pudo renombrar", wx.OK | wx.ICON_WARNING,
            )
        evento.Skip()

    def al_nueva_categoria_raiz(self, evento):
        dlg = wx.TextEntryDialog(self, "Nombre del nuevo género:", "Nueva categoría")
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                self.gestor.crear_categoria(nombre, None)
                reproducir(SUCCESS)
                self._anunciar(f"Categoría «{nombre}» creada.")
                self._cargar_arbol_categorias()
        dlg.Destroy()

    def al_nueva_subcategoria(self, evento):
        id_padre = self._categoria_seleccionada_id()
        if id_padre is None:
            self._anunciar(
                "Selecciona primero una categoría en el árbol para añadirle una subcategoría."
            )
            return
        nombre_padre = self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
        dlg = wx.TextEntryDialog(
            self, f"Nombre del nuevo subgénero dentro de «{nombre_padre}»:", "Nueva subcategoría"
        )
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                self.gestor.crear_categoria(nombre, id_padre)
                reproducir(SUCCESS)
                self._anunciar(f"Subcategoría «{nombre}» creada dentro de «{nombre_padre}».")
                self._cargar_arbol_categorias(id_categoria_seleccionar=id_padre)
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
        reproducir(SUCCESS)
        self._id_categoria_activa = None
        self._cargar_arbol_categorias()
        self._cargar_libros()

    def al_cortar_categoria(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        if id_categoria is None:
            return
        self._categoria_en_portapapeles = id_categoria
        reproducir(CLEAR)
        nombre = self.arbol_categorias.GetItemText(self.arbol_categorias.GetSelection())
        self._anunciar(f"{nombre} cortada. Selecciona el destino y pulsa Ctrl+V, o Escape para cancelar.")

    def al_pegar_categoria(self, evento):
        if self._categoria_en_portapapeles is None:
            self._anunciar("No hay ninguna categoría cortada.")
            return
        destino = self._categoria_seleccionada_id()
        if self.gestor.reparentar_categoria(self._categoria_en_portapapeles, destino):
            reproducir(SUCCESS)
            id_movida = self._categoria_en_portapapeles
            self._categoria_en_portapapeles = None
            self._cargar_arbol_categorias(id_categoria_seleccionar=id_movida)
            self._anunciar("Categoría movida.")
        else:
            reproducir(ERROR)
            self._anunciar("No se puede mover ahí: crearía un ciclo o el destino es la misma categoría.")

    def al_menu_contextual_arbol(self, evento):
        id_categoria = self._categoria_seleccionada_id()
        menu = wx.Menu()

        item_nueva = menu.Append(wx.ID_ANY, "Nueva categoría raíz...")
        self.Bind(wx.EVT_MENU, self.al_nueva_categoria_raiz, item_nueva)

        item_sub = menu.Append(wx.ID_ANY, "Nueva subcategoría dentro de la seleccionada...")
        item_sub.Enable(id_categoria is not None)
        self.Bind(wx.EVT_MENU, self.al_nueva_subcategoria, item_sub)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar\tF2")
        item_renombrar.Enable(id_categoria is not None)
        self.Bind(
            wx.EVT_MENU,
            lambda e: self.arbol_categorias.EditLabel(self.arbol_categorias.GetSelection()),
            item_renombrar,
        )

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

        self.arbol_categorias.PopupMenu(menu)
        menu.Destroy()

    # ── Carga y filtrado de la lista ─────────────────────────────────────────

    def _cargar_libros(self):
        estado = self._ESTADOS_FILTRO[self.combo_estado.GetSelection()]
        libros = self.gestor.buscar_libros(
            texto=self.txt_filtro.GetValue().strip(),
            id_categoria=self._id_categoria_activa,
            solo_favoritos=self.chk_favoritos.GetValue(),
            solo_pendientes=(estado == "Pendientes"),
            solo_leyendo=(estado == "Leyendo ahora"),
            solo_leidos=(estado == "Leídos"),
        )
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
        with wx.DirDialog(self, "Seleccionar carpeta con libros para importar") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            carpeta = dlg.GetPath()

        usar_subcarpetas = wx.MessageBox(
            "¿Quieres usar la estructura de subcarpetas de esta carpeta como árbol "
            "de categorías (género/subgénero)?\n\n"
            "Por ejemplo, si tienes libros dentro de «Fantasía/Fantasía épica/», se "
            "crearán esas categorías automáticamente. Podrás renombrarlas o moverlas "
            "después. Si no organizas tus libros por género en carpetas, elige No.",
            "Categorías automáticas", wx.YES_NO | wx.ICON_QUESTION,
        ) == wx.YES

        self._anunciar("Escaneando carpeta, por favor espera...")
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
            self._anunciar(f"Procesando... {procesados} de {total} libros.")

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
            for carpeta in carpetas_candidatas:
                confirmar_agrupamiento_por_carpeta(self.gestor, carpeta, nombres_sugeridos[carpeta])

    def _al_terminar_escaneo(self, total_insertados):
        self._timer_progreso.Stop()
        reproducir(SUCCESS)
        self.barra_progreso.Hide()
        self.Layout()
        self._cargar_arbol_categorias()
        self._cargar_libros()
        self.lista_libros.SetFocus()

        # Diálogo modal nativo en vez de solo el anunciador: siempre tiene
        # foco propio y se cierra con Enter/Escape/OK de forma garantizada,
        # sin depender de que el usuario navegue de vuelta a la lista.
        if total_insertados > 0:
            wx.MessageBox(
                f"Se han añadido {total_insertados} libro(s) a la biblioteca.",
                "Escaneo completado", wx.OK | wx.ICON_INFORMATION,
            )
        else:
            wx.MessageBox(
                "No se encontraron libros nuevos en esa carpeta.",
                "Escaneo completado", wx.OK | wx.ICON_INFORMATION,
            )

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

        self._anunciar("Abriendo libro, por favor espera...")

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
        """
        Submenú "Añadir a categoría": primer elemento para crear una
        categoría nueva y asignarla en el mismo paso, después el árbol
        de categorías existentes como submenús anidados — cada nivel
        tiene su propio elemento "Asignar aquí" antes de sus hijos, para
        poder elegir tanto un género como uno de sus subgéneros.

        Para asignar varias categorías a la vez, se invoca este menú una
        vez por cada categoría a añadir (igual que marcar favorito), en
        vez de una selección múltiple con casillas dentro del propio
        menú — los menús no están pensados para selección múltiple y
        forzarla los haría más confusos de navegar con teclado.
        """
        menu = wx.Menu()
        item_nueva = menu.Append(wx.ID_ANY, "Crear categoría nueva y asignar...")
        self.Bind(
            wx.EVT_MENU, lambda e: self.al_crear_categoria_y_asignar(libro, None), item_nueva
        )

        raices = self.gestor.listar_categorias_hijas(None)
        if raices:
            menu.AppendSeparator()
            self._rellenar_submenu_categorias(menu, None, libro)
        return menu

    def _rellenar_submenu_categorias(self, menu_destino, id_categoria_padre, libro):
        for categoria in self.gestor.listar_categorias_hijas(id_categoria_padre):
            hijas = self.gestor.listar_categorias_hijas(categoria["id"])
            if hijas:
                submenu = wx.Menu()
                item_aqui = submenu.Append(wx.ID_ANY, f"Asignar a «{categoria['nombre']}»")
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, id_cat=categoria["id"]: self.al_asignar_categoria_existente(
                        libro, id_cat
                    ),
                    item_aqui,
                )
                submenu.AppendSeparator()
                item_nueva_sub = submenu.Append(wx.ID_ANY, "Crear subcategoría nueva y asignar...")
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, id_padre=categoria["id"]: self.al_crear_categoria_y_asignar(
                        libro, id_padre
                    ),
                    item_nueva_sub,
                )
                submenu.AppendSeparator()
                self._rellenar_submenu_categorias(submenu, categoria["id"], libro)
                menu_destino.AppendSubMenu(submenu, categoria["nombre"])
            else:
                item = menu_destino.Append(wx.ID_ANY, categoria["nombre"])
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, id_cat=categoria["id"]: self.al_asignar_categoria_existente(
                        libro, id_cat
                    ),
                    item,
                )

    def al_asignar_categoria_existente(self, libro, id_categoria):
        ruta = self.gestor.obtener_ruta_categoria(id_categoria)
        self.gestor.asignar_categoria_por_ruta(libro["id"], ruta)
        reproducir(SUCCESS)
        self._anunciar(f"Añadido a categoría {' > '.join(ruta)}.")
        self._cargar_arbol_categorias(id_categoria_seleccionar=self._id_categoria_activa)
        self._cargar_libros()

    def al_crear_categoria_y_asignar(self, libro, id_padre):
        dlg = wx.TextEntryDialog(
            self,
            "Nombre de la nueva categoría:",
            "Crear categoría y asignar",
        )
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                id_categoria = self.gestor.crear_categoria(nombre, id_padre)
                self.gestor.asignar_categoria_por_ruta(
                    libro["id"], self.gestor.obtener_ruta_categoria(id_categoria)
                )
                reproducir(SUCCESS)
                self._anunciar(f"Categoría «{nombre}» creada y libro añadido.")
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

        menu.AppendSubMenu(self.construir_menu_asignar_categoria(libro), "Añadir a categoría")

        item_quitar_cat = menu.Append(wx.ID_ANY, "Quitar de esta categoría")
        item_quitar_cat.Enable(self._id_categoria_activa is not None)
        self.Bind(wx.EVT_MENU, self.al_quitar_de_categoria_actual, item_quitar_cat)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar archivo...\tF2")
        self.Bind(wx.EVT_MENU, self.al_renombrar_segun_metadatos, item_renombrar)

        item_quitar = menu.Append(wx.ID_ANY, "Quitar de la biblioteca")
        self.Bind(wx.EVT_MENU, lambda e: self._quitar_libro_seleccionado(), item_quitar)

        self.PopupMenu(menu)
        menu.Destroy()
# ANCLAJE_FIN: DEFINICION_PESTANA_BIBLIOTECA
