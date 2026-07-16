# ANCLAJE_INICIO: DEPENDENCIAS_PRINCIPALES
import wx
import os
import json
import logging

logger = logging.getLogger(__name__)
from app.interfaz.pestana_biblioteca import PestanaBiblioteca
from app.interfaz.pestana_lectura import PestanaLectura
from app.interfaz.pestana_ajustes import PestanaAjustes
from app.interfaz.pestana_grabacion import PestanaGrabacion
from app.interfaz.pestana_creador_audiolibros import PestanaCreadorAudiolibros
from app.interfaz.ventana_proyectos import VentanaProyectos
from app.config_rutas import ruta_config
from app.motor.reproductor_sonidos import reproducir, APP_READY, CLICK, SUCCESS, ERROR
# ANCLAJE_FIN: DEPENDENCIAS_PRINCIPALES

# URL del repositorio (actualizar si cambia la ubicación del proyecto)
_URL_GITHUB = "https://github.com/Dayanna-Parson/epub-tts-accesible"

# ── Índices de pestaña del notebook ───────────────────────────────────────────
# Centralizados aquí para no repetir números mágicos por todo el archivo.
IDX_BIBLIOTECA = 0
IDX_LECTURA    = 1
IDX_CREADOR    = 2
IDX_GRABACION  = 3
IDX_AJUSTES    = 4
NUM_PESTANAS   = 5

# ── Helpers para traducir atajos de gestor_atajos al formato de wx ───────────
def _mod_a_flag(mod_str):
    """Convierte 'Ctrl', 'Alt', 'Ctrl+Shift'… al flag wx.ACCEL_* correspondiente."""
    _MAP = {
        "": wx.ACCEL_NORMAL,
        "Ctrl": wx.ACCEL_CTRL,
        "Alt": wx.ACCEL_ALT,
        "Shift": wx.ACCEL_SHIFT,
        "Ctrl+Alt": wx.ACCEL_CTRL | wx.ACCEL_ALT,
        "Ctrl+Shift": wx.ACCEL_CTRL | wx.ACCEL_SHIFT,
        "Alt+Shift": wx.ACCEL_ALT | wx.ACCEL_SHIFT,
        "Ctrl+Alt+Shift": wx.ACCEL_CTRL | wx.ACCEL_ALT | wx.ACCEL_SHIFT,
    }
    return _MAP.get(mod_str)


def _nombre_a_keycode(nombre):
    """Convierte 'A', 'Espacio', 'F5'… al código de tecla wx correspondiente."""
    _MAP = {
        "Espacio": wx.WXK_SPACE, "Intro": wx.WXK_RETURN,
        "F1": wx.WXK_F1,  "F2": wx.WXK_F2,  "F3": wx.WXK_F3,
        "F4": wx.WXK_F4,  "F5": wx.WXK_F5,  "F6": wx.WXK_F6,
        "F7": wx.WXK_F7,  "F8": wx.WXK_F8,  "F9": wx.WXK_F9,
        "F10": wx.WXK_F10, "F11": wx.WXK_F11, "F12": wx.WXK_F12,
        "Arriba": wx.WXK_UP, "Abajo": wx.WXK_DOWN,
        "Izquierda": wx.WXK_LEFT, "Derecha": wx.WXK_RIGHT,
        "Inicio": wx.WXK_HOME, "Fin": wx.WXK_END,
        "RePág": wx.WXK_PAGEUP, "AvPág": wx.WXK_PAGEDOWN,
        "Tab": wx.WXK_TAB, "Retroceso": wx.WXK_BACK,
        "Supr": wx.WXK_DELETE, "Insert": wx.WXK_INSERT,
    }
    if nombre in _MAP:
        return _MAP[nombre]
    if len(nombre) == 1:
        return ord(nombre.upper())
    return -1
# ─────────────────────────────────────────────────────────────────────────────

# ANCLAJE_INICIO: DEFINICION_VENTANA
class VentanaPrincipal(wx.Frame):
    """Ventana raíz de la aplicación que contiene las pestañas y el menú principal."""
    
    # ANCLAJE_INICIO: CONSTRUCCION_INTERFAZ_PRINCIPAL
    def __init__(self, padre, titulo="Epub TTS"):
        super().__init__(padre, title=titulo, size=(1000, 700))
        self.Maximize(True)

        # Icono de ventana con el sistema de arte estándar de wx
        try:
            bmp = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_FRAME_ICON, (32, 32))
            if bmp.IsOk():
                self.SetIcon(wx.Icon(bmp))
        except Exception:
            pass

        # 1. Configurar Panel de Pestañas (Notebook)
        self.notebook = wx.Notebook(self)

        # Pestaña 1: Biblioteca
        self.pestana_biblioteca = PestanaBiblioteca(self.notebook)
        self.notebook.AddPage(self.pestana_biblioteca, "Biblioteca")

        # Pestaña 2: Lectura
        self.pestana_lectura = PestanaLectura(self.notebook)
        self.notebook.AddPage(self.pestana_lectura, "Modo Lectura")

        # Pestaña 3: Creador de Audiolibros
        self.pestana_creador = PestanaCreadorAudiolibros(self.notebook)
        self.notebook.AddPage(self.pestana_creador, "Creador de Audiolibros")

        # Pestaña 4: Grabación multivoz
        self.pestana_grabacion = PestanaGrabacion(self.notebook)
        self.notebook.AddPage(self.pestana_grabacion, "Creación de fragmentos")

        # Pestaña 5: Ajustes
        self.pestana_ajustes = PestanaAjustes(self.notebook)
        self.notebook.AddPage(self.pestana_ajustes, "Ajustes")

        # 2. La barra de menú clásica se ha eliminado.
        # Toda la funcionalidad está en los menús contextuales de cada pestaña
        # (Tecla Menú / Shift+F10) y en los atajos de teclado del AcceleratorTable.

        # Eventos
        self.Bind(wx.EVT_CLOSE, self.al_cerrar)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.al_cambiar_pestana)

        # Bucle de tabulación accesible a nivel de ventana.
        # Vinculado aquí (Frame) en lugar de en cada Panel para no interferir
        # con los eventos internos de los controles hijo (ej: EVT_TREE_ITEM_ACTIVATED).
        self.Bind(wx.EVT_CHAR_HOOK, self.al_navegacion_tab_global)

        # Referencia a la ventana de proyectos (prevención de doble instancia)
        self._ventana_proyectos = None

        # Historial de recientes — ruta absoluta para evitar fallos de permisos según CWD
        self.archivos_recientes = []
        self.ruta_recientes = ruta_config("historial_epub.json")
        self.cargar_historial_recientes()

        # TXT recientes — archivo independiente historial_grabacion.json
        self.txt_recientes = []
        self._ruta_historial_grabacion = ruta_config("historial_grabacion.json")

        # Aplicar AcceleratorTable al Frame para que los atajos funcionen
        # incluso cuando el foco está dentro del RichTextCtrl de lectura
        self._ids_atajos_global = {}
        self._configurar_aceleradores_globales()

        # Restaurar sesión anterior antes de mostrar la ventana
        self._ruta_config_general = ruta_config("ajustes.json")
        self._restaurar_sesion()

        self.Show()

        # Verificación automática de voces nuevas (una vez al día, hilo de fondo)
        wx.CallAfter(self._iniciar_verificacion_voces)

        # Comprobación automática de actualizaciones al arranque (5 s de margen
        # para que NVDA lea la ventana antes de que aparezca el diálogo).
        wx.CallLater(5000, self._comprobar_actualizaciones_arranque)

        # Sonido "aplicación lista" — 200 ms de margen para que NVDA
        # empiece a leer la ventana antes de sonar (sin ser tardío).
        wx.CallLater(200, reproducir, APP_READY)
    # ANCLAJE_FIN: CONSTRUCCION_INTERFAZ_PRINCIPAL

    # ANCLAJE_INICIO: CONFIGURACION_MENUS
    # (La barra de menú clásica fue eliminada en Prompt 8.
    #  Toda la funcionalidad está en los menús contextuales por pestaña
    #  — método _mostrar_menu_contextual() — y en el AcceleratorTable.)
    # ANCLAJE_FIN: CONFIGURACION_MENUS

    # ANCLAJE_INICIO: EVENTOS_GLOBALES
    def al_navegacion_tab_global(self, evento):
        """
        Gestiona:
          - Tab cíclico accesible (bucle dentro de cada pestaña).
          - Tecla Menú / Shift+F10: abre el menú contextual de la pestaña activa.

        Vinculado al Frame en lugar de a cada Panel individual para evitar
        interferencias con eventos internos de controles hijo como el TreeCtrl.
        """
        keycode = evento.GetKeyCode()

        # Tecla Menú (Applications key) → menú contextual de la pestaña activa
        if keycode == getattr(wx, "WXK_WINDOWS_MENU", 348):
            self._mostrar_menu_contextual_seguro()
            return
        # Shift+F10 → ídem (alternativa universal para teclados sin tecla Menú)
        if keycode == wx.WXK_F10 and evento.ShiftDown():
            self._mostrar_menu_contextual_seguro()
            return

        # Ctrl+1 a Ctrl+5 → cambiar de pestaña directamente
        # Solo cuando el foco está dentro de la ventana principal (no en diálogos externos)
        if evento.ControlDown() and not evento.ShiftDown() and keycode in (
            ord('1'), ord('2'), ord('3'), ord('4'), ord('5')
        ):
            idx = keycode - ord('1')   # 0 a 4
            self.notebook.SetSelection(idx)
            # Sin esto, el foco de teclado se quedaba en el control que ya
            # tuviera antes (a veces de una pestaña que acaba de ocultarse),
            # así que el lector de pantalla anunciaba un control desconectado
            # en vez de la pestaña nueva — mismo tratamiento que ya recibe
            # Ctrl+Tab más abajo.
            wx.CallAfter(self.notebook.SetFocus)
            return

        # Ctrl+Tab / Ctrl+Shift+Tab → cambiar de pestaña sin importar dónde
        # esté el foco dentro de la ventana principal (nunca afecta a
        # diálogos ni ventanas secundarias, que gestionan su propio Tab).
        if keycode == wx.WXK_TAB and evento.ControlDown():
            self.notebook.AdvanceSelection(not evento.ShiftDown())
            wx.CallAfter(self.notebook.SetFocus)
            return

        if keycode != wx.WXK_TAB:
            evento.Skip()
            return

        # Todo el bloque de Tab cíclico queda blindado: un fallo al resolver
        # primer_control/ultimo_control de una pestaña (por ejemplo, un
        # atributo que aún no existe tras un cambio a medio terminar) no debe
        # dejar el teclado sin Tab en el resto de la aplicación — se registra
        # y se cede el evento al comportamiento por defecto de wx en vez de
        # propagar la excepción hacia EVT_CHAR_HOOK.
        try:
            foco = self.FindFocus()
            if foco is None:
                evento.Skip()
                return

            shift = evento.ShiftDown()
            indice = self.notebook.GetSelection()

            if indice == IDX_BIBLIOTECA:
                primer = self.pestana_biblioteca.primer_control
                ultimo = self.pestana_biblioteca.ultimo_control
            elif indice == IDX_LECTURA:
                primer = self.pestana_lectura.primer_control
                ultimo = self.pestana_lectura.ultimo_control
            elif indice == IDX_CREADOR:
                primer = self.pestana_creador.primer_control
                ultimo = self.pestana_creador.ultimo_control
            elif indice == IDX_GRABACION:
                primer = self.pestana_grabacion.primer_control
                ultimo = self.pestana_grabacion.ultimo_control
            elif indice == IDX_AJUSTES:
                primer = self.pestana_ajustes.arbol_cat
                ultimo = self.pestana_ajustes.obtener_ultimo_control()
            else:
                evento.Skip()
                return
        except Exception:
            logger.exception("[VentanaPrincipal] Fallo al resolver el Tab cíclico de la pestaña activa")
            evento.Skip()
            return

        if not shift and foco == ultimo:
            # Tab en el último control: salir del panel hacia el Notebook
            wx.CallAfter(self.notebook.SetFocus)
            return
        elif shift and foco == primer:
            # Shift+Tab en el primer control: bucle circular → saltar al último control.
            # wx.CallAfter garantiza que NVDA anuncia el nuevo foco correctamente
            # al diferirlo hasta después de que el evento de teclado sea procesado.
            wx.CallAfter(ultimo.SetFocus)
            return

        evento.Skip()

    def al_cambiar_pestana(self, evento):
        reproducir(CLICK)   # PRIMERO — feedback antes de cualquier procesado visual
        indice = evento.GetSelection()
        if indice == IDX_LECTURA:
            # Refrescar AcceleratorTable en caso de que el usuario haya cambiado atajos
            self._configurar_aceleradores_globales()
        self._guardar_sesion()
        evento.Skip()

    def al_abrir_gestor_proyectos(self, evento):
        """
        Abre la ventana de gestión de proyectos.
        Evita doble instancia. Captura el foco previo para devolverlo al cerrar (feature b).
        Si hay un TXT cargado en Grabación, navega al nodo del archivo (feature o).
        """
        reproducir(CLICK)
        foco_previo = wx.Window.FindFocus()
        ruta_txt = self.pestana_grabacion.ruta_txt_actual
        if self._ventana_proyectos and not self._ventana_proyectos.IsBeingDeleted():
            try:
                self._ventana_proyectos.Raise()
                if ruta_txt:
                    self._ventana_proyectos._navegar_a_archivo(ruta_txt)
                return
            except Exception:
                pass
        self._ventana_proyectos = VentanaProyectos(
            parent=self,
            ruta_txt_activo=ruta_txt,
            foco_previo=foco_previo,
            gestor_proyectos=self.pestana_grabacion.gestor_proyectos,
        )
        self._ventana_proyectos.Show()

    def al_abrir_txt_grabacion(self, evento):
        """Activa la pestaña Grabación y llama al método Examinar del panel."""
        self.notebook.SetSelection(IDX_GRABACION)
        ruta_previa = self.pestana_grabacion.ruta_txt_actual
        self.pestana_grabacion.al_examinar(None)
        ruta_nueva = self.pestana_grabacion.ruta_txt_actual
        if ruta_nueva and ruta_nueva != ruta_previa:
            self.agregar_txt_a_recientes(ruta_nueva)

    def al_abrir_archivo(self, evento):
        self.notebook.SetSelection(IDX_LECTURA)
        self.pestana_lectura.al_cargar_libro(None)

    def al_abrir_marcadores(self, evento):
        if self.notebook.GetSelection() == IDX_LECTURA:
            self.pestana_lectura.iniciar_marcadores()

    def al_buscar(self, evento):
        if self.notebook.GetSelection() == IDX_LECTURA:
            self.pestana_lectura.iniciar_busqueda()

    def al_ir_a_porcentaje(self, evento):
        if self.notebook.GetSelection() == IDX_LECTURA:
            self.pestana_lectura.iniciar_ir_a_pagina()

    def al_salir(self, evento):
        self.Close()

    def al_cerrar(self, evento):
        try:
            if hasattr(self.pestana_lectura, 'reproductor'):
                self.pestana_lectura.al_detener(None)
        except Exception:
            logger.warning("Error al detener la reproducción durante el cierre", exc_info=True)

        # Desconectar EVT_TREE_SEL_CHANGED antes de destruir: puede
        # dispararse durante el cierre y acceder a objetos C++ ya liberados
        # (mismo problema ya resuelto para el árbol de ventana_proyectos.py).
        try:
            self.pestana_biblioteca.arbol_categorias.Unbind(wx.EVT_TREE_SEL_CHANGED)
        except Exception:
            pass

        self._guardar_sesion()
        self.Destroy()
    # ANCLAJE_FIN: EVENTOS_GLOBALES

    # ANCLAJE_INICIO: MEMORIA_SESION
    def _cargar_config_general(self) -> dict:
        """Lee ajustes.json sin borrar claves existentes."""
        try:
            if os.path.exists(self._ruta_config_general):
                with open(self._ruta_config_general, "r", encoding="utf-8") as f:
                    contenido = f.read().strip()
                if contenido:
                    return json.loads(contenido)
        except Exception:
            pass
        return {}

    def _guardar_sesion(self):
        """Persiste el estado de sesión en ajustes.json."""
        try:
            config = self._cargar_config_general()
            config["ultima_pestana"]       = self.notebook.GetSelection()
            config["ultimo_txt_grabacion"] = (
                self.pestana_grabacion.ruta_txt_actual or ""
            )
            config["dividir_por_etiqueta"] = (
                self.pestana_grabacion.chk_dividir.IsChecked()
            )
            os.makedirs(os.path.dirname(self._ruta_config_general), exist_ok=True)
            with open(self._ruta_config_general, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass  # No es crítico si falla el guardado de sesión

    def _restaurar_sesion(self):
        """Restaura el estado de sesión desde ajustes.json."""
        config = self._cargar_config_general()

        # La pestaña activa ya no se restaura desde la sesión anterior: el
        # arranque siempre aterriza en Biblioteca (IDX_BIBLIOTECA), para que
        # NVDA llegue directo a los libros en vez de a la última pestaña
        # usada (a veces Ajustes), sea cual sea. self.notebook ya empieza en
        # la página 0 por orden de construcción, así que no hace falta
        # ningún SetSelection() explícito aquí.

        # Restaurar estado del checkbox "Dividir por etiquetas"
        dividir = config.get("dividir_por_etiqueta", True)
        self.pestana_grabacion.chk_dividir.SetValue(bool(dividir))
        # Sincronizar el label del checkbox con su estado restaurado
        self.pestana_grabacion.al_cambiar_division(None)

        # Restaurar último TXT de grabación si existe en disco
        ultimo_txt = config.get("ultimo_txt_grabacion", "")
        if ultimo_txt and os.path.exists(ultimo_txt):
            self.pestana_grabacion.cargar_txt_desde_ruta(ultimo_txt)

        # Cargar lista de TXT recientes desde historial_grabacion.json
        self.txt_recientes = []
        try:
            if os.path.exists(self._ruta_historial_grabacion):
                with open(self._ruta_historial_grabacion, encoding="utf-8") as f:
                    self.txt_recientes = [r for r in json.load(f) if os.path.exists(r)]
        except Exception:
            pass
        self.actualizar_menu_txt_recientes()
    # ANCLAJE_FIN: MEMORIA_SESION

    # ANCLAJE_INICIO: TXT_RECIENTES
    def agregar_txt_a_recientes(self, ruta: str):
        """Añade un TXT a la lista de recientes de grabación y actualiza el submenú."""
        if ruta in self.txt_recientes:
            self.txt_recientes.remove(ruta)
        self.txt_recientes.insert(0, ruta)
        self.txt_recientes = self.txt_recientes[:10]
        self._guardar_txt_recientes()
        self.actualizar_menu_txt_recientes()

    def _guardar_txt_recientes(self):
        try:
            os.makedirs(os.path.dirname(self._ruta_historial_grabacion), exist_ok=True)
            with open(self._ruta_historial_grabacion, "w", encoding="utf-8") as f:
                json.dump(self.txt_recientes, f, ensure_ascii=False)
        except Exception:
            pass

    def actualizar_menu_txt_recientes(self):
        """No-op: los TXT recientes se construyen dinámicamente en _menu_contextual_grabacion."""
        pass

    def _abrir_txt_reciente(self, ruta: str):
        if os.path.exists(ruta):
            self.notebook.SetSelection(IDX_GRABACION)
            self.pestana_grabacion.cargar_txt_desde_ruta(ruta)
            self.agregar_txt_a_recientes(ruta)
        else:
            wx.MessageBox("El archivo ya no existe en disco.", "Archivo no encontrado")
            if ruta in self.txt_recientes:
                self.txt_recientes.remove(ruta)
                self._guardar_txt_recientes()
                self.actualizar_menu_txt_recientes()

    def _al_borrar_txt_recientes(self, evento):
        if wx.MessageBox(
            "¿Borrar el historial de TXT recientes?",
            "Confirmar", wx.YES_NO | wx.ICON_QUESTION
        ) == wx.YES:
            self.txt_recientes = []
            self._guardar_txt_recientes()
            self.actualizar_menu_txt_recientes()
    # ANCLAJE_FIN: TXT_RECIENTES

    # ANCLAJE_INICIO: HISTORIAL_RECIENTES
    def cargar_historial_recientes(self):
        self.archivos_recientes = []
        try:
            if os.path.exists(self.ruta_recientes):
                with open(self.ruta_recientes, "r", encoding="utf-8") as archivo:
                    self.archivos_recientes = json.load(archivo)
        except Exception as e:
            print(f"[Aviso] No se pudo leer el historial de recientes: {e}")
            self.archivos_recientes = []
        self.actualizar_menu_recientes()

    def agregar_a_recientes(self, ruta):
        if ruta in self.archivos_recientes:
            self.archivos_recientes.remove(ruta)
        self.archivos_recientes.insert(0, ruta)
        self.archivos_recientes = self.archivos_recientes[:10]
        
        self._guardar_recientes()
        self.actualizar_menu_recientes()

    def al_borrar_recientes(self, evento):
        if wx.MessageBox("¿Seguro que quieres borrar el historial de libros recientes?", "Confirmar", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.archivos_recientes = []
            self._guardar_recientes()
            self.actualizar_menu_recientes()

    def _guardar_recientes(self):
        try:
            os.makedirs(os.path.dirname(self.ruta_recientes), exist_ok=True)
            with open(self.ruta_recientes, "w", encoding="utf-8") as archivo:
                json.dump(self.archivos_recientes, archivo)
        except Exception as e:
            print(f"Error guardando recientes: {e}")

    def actualizar_menu_recientes(self):
        """No-op: los libros recientes se construyen dinámicamente en _menu_contextual_lectura."""
        pass

    def abrir_libro_reciente(self, ruta):
        if os.path.exists(ruta):
            self.notebook.SetSelection(IDX_LECTURA)
            self.pestana_lectura.cargar_epub_desde_ruta(ruta)
        else:
            wx.MessageBox("El archivo ya no existe", "Error")
            if ruta in self.archivos_recientes:
                self.archivos_recientes.remove(ruta)
                self._guardar_recientes()
                self.actualizar_menu_recientes()
    # ANCLAJE_FIN: HISTORIAL_RECIENTES

    # ANCLAJE_INICIO: MENUS_CONTEXTUALES
    def _mostrar_menu_contextual_seguro(self):
        """
        Envoltorio defensivo alrededor de _mostrar_menu_contextual(): un
        error al construir un menú contextual (por ejemplo, un atributo de
        wx mal usado en algún ítem) no debe propagarse hasta
        al_navegacion_tab_global(), vinculado a EVT_CHAR_HOOK del Frame —
        un fallo sin capturar ahí deja sin Tab/Shift+F10/tecla Menú al resto
        de la aplicación, no solo a la pestaña donde ocurrió.
        """
        try:
            self._mostrar_menu_contextual()
        except Exception:
            logger.exception("[VentanaPrincipal] Error al mostrar el menú contextual")
            reproducir(ERROR)

    def _mostrar_menu_contextual(self):
        """Muestra el menú contextual correspondiente a la pestaña activa."""
        indice = self.notebook.GetSelection()
        if indice == IDX_BIBLIOTECA:
            self._menu_contextual_biblioteca()
        elif indice == IDX_LECTURA:
            self._menu_contextual_lectura()
        elif indice == IDX_CREADOR:
            self._menu_contextual_creador()
        elif indice == IDX_GRABACION:
            self._menu_contextual_grabacion()
        else:
            self._menu_contextual_ajustes()

    def _menu_contextual_biblioteca(self):
        """
        Menú contextual de la pestaña Biblioteca: delega en el método
        propio del control que tenga el foco en ese momento (árbol de
        categorías, listado de etiquetas o listado de libros), en vez de
        reconstruir aquí una copia paralela del menú del libro.

        Antes este método duplicaba a mano el menú de al_menu_contextual()
        (pestana_biblioteca.py) y SIEMPRE lo mostraba sin importar qué
        control tuviera el foco realmente — por eso el árbol y el listado
        de etiquetas nunca mostraban su propio menú (Nueva categoría,
        Renombrar, Nueva etiqueta...) y siempre aparecían "Importar
        carpeta"/Ayuda/Salir pegados a cualquier menú, y por qué las
        opciones de pendiente/leyendo ahora/leído (añadidas solo en la
        copia real) nunca llegaban a verse aquí.
        """
        pb = self.pestana_biblioteca
        foco = wx.Window.FindFocus()

        if foco is pb.arbol_categorias:
            pb.al_menu_contextual_arbol(None)
            return
        if foco is pb.lista_etiquetas:
            pb.al_menu_contextual_etiquetas(None)
            return
        if foco is pb.lista_libros:
            pb.al_menu_contextual(None)
            return

        # Ningún control específico de la lista/árbol tiene el foco (por
        # ejemplo, el botón "Importar carpeta..."): menú mínimo genérico.
        menu = wx.Menu()
        item_importar = menu.Append(wx.ID_ANY, "Importar carpeta...\tCtrl+O")
        self.Bind(wx.EVT_MENU, pb.al_importar_carpeta, item_importar)
        menu.AppendSeparator()
        self._submenu_ayuda(menu)
        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, "Salir")
        self.Bind(wx.EVT_MENU, self.al_salir, item_salir)
        self.PopupMenu(menu)
        menu.Destroy()

    def _menu_contextual_creador(self):
        """
        Menú contextual de Creador de Audiolibros. Sin selector de archivos
        propio (flujo de entrada único: solo libros enviados desde
        Biblioteca), así que por ahora se limita a Ayuda y Salir. Las
        acciones propias de exportación se añadirán aquí cuando se conecte
        el cableado real de la pestaña.
        """
        menu = wx.Menu()
        self._submenu_ayuda(menu)
        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, "Salir")
        self.Bind(wx.EVT_MENU, self.al_salir, item_salir)
        self.pestana_creador.PopupMenu(menu)
        menu.Destroy()

    def _menu_contextual_ajustes(self):
        """Menú contextual de la pestaña Ajustes: solo Ayuda y Salir."""
        menu = wx.Menu()
        self._submenu_ayuda(menu)
        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, "Salir")
        self.Bind(wx.EVT_MENU, self.al_salir, item_salir)
        self.pestana_ajustes.PopupMenu(menu)
        menu.Destroy()

    def _submenu_ayuda(self, menu):
        """Añade el submenú Ayuda al menú contextual recibido (compartido por todas las pestañas)."""
        sub = wx.Menu()

        item_ayuda = sub.Append(wx.ID_ANY, "Abrir ayuda (F1)")
        self.Bind(wx.EVT_MENU, self._al_abrir_ayuda_global, item_ayuda)

        item_atajos = sub.Append(wx.ID_ANY, "Ver atajos de teclado")
        self.Bind(wx.EVT_MENU, self.al_ver_atajos, item_atajos)

        sub.AppendSeparator()

        item_acerca = sub.Append(wx.ID_ANY, "Acerca de")
        self.Bind(wx.EVT_MENU, self.al_abrir_acerca_de, item_acerca)

        sub.AppendSeparator()

        item_github = sub.Append(wx.ID_ANY, "Abrir repositorio en GitHub")
        self.Bind(wx.EVT_MENU, self.al_abrir_github, item_github)

        item_releases = sub.Append(wx.ID_ANY, "Ver todas las versiones en Releases")
        self.Bind(wx.EVT_MENU, self.al_abrir_releases, item_releases)

        sub.AppendSeparator()

        item_tiflohistorias = sub.Append(wx.ID_ANY, "Escuchar audiolibros en Tiflohistorias")
        self.Bind(wx.EVT_MENU, self.al_abrir_tiflohistorias, item_tiflohistorias)

        item_tiflotutos = sub.Append(wx.ID_ANY, "Visitar tiflotutos.com")
        self.Bind(wx.EVT_MENU, self.al_visitar_tiflotutos, item_tiflotutos)

        sub.AppendSeparator()

        item_log = sub.Append(wx.ID_ANY, "Abrir carpeta de registros")
        self.Bind(wx.EVT_MENU, self.al_abrir_registros, item_log)

        item_copiar_log = sub.Append(wx.ID_ANY, "Copiar registros al portapapeles")
        self.Bind(wx.EVT_MENU, self.al_copiar_registros, item_copiar_log)

        item_copiar_ultimo_error = sub.Append(wx.ID_ANY, "Copiar el último error al portapapeles")
        self.Bind(wx.EVT_MENU, self.al_copiar_ultimo_error, item_copiar_ultimo_error)

        menu.AppendSubMenu(sub, "Ayuda")

    def _menu_contextual_lectura(self):
        """Menú contextual de la pestaña Lectura: abrir, recientes, navegación."""
        menu = wx.Menu()

        # Abrir libro
        item_abrir = menu.Append(wx.ID_ANY, "Abrir libro EPUB")
        self.Bind(wx.EVT_MENU, self.al_abrir_archivo, item_abrir)

        # Submenú libros recientes
        sub_rec = wx.Menu()
        if self.archivos_recientes:
            for i, ruta in enumerate(self.archivos_recientes):
                nombre = os.path.basename(ruta)
                id_item = wx.NewIdRef()
                sub_rec.Append(id_item, f"{i+1}. {nombre}")
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, p=ruta: self.abrir_libro_reciente(p),
                    id=id_item,
                )
            sub_rec.AppendSeparator()
            id_borrar = wx.NewIdRef()
            sub_rec.Append(id_borrar, "Borrar historial")
            self.Bind(wx.EVT_MENU, self.al_borrar_recientes, id=id_borrar)
        else:
            sub_rec.Append(wx.ID_ANY, "(Vacío)").Enable(False)
        menu.AppendSubMenu(sub_rec, "Libros Recientes")

        menu.AppendSeparator()

        # Navegación por el texto
        item_b = menu.Append(wx.ID_ANY, "Buscar en el texto\tCtrl+F")
        self.Bind(wx.EVT_MENU, self.al_buscar, item_b)
        item_g = menu.Append(wx.ID_ANY, "Ir a página / porcentaje...\tCtrl+G")
        self.Bind(wx.EVT_MENU, self.al_ir_a_porcentaje, item_g)
        item_m = menu.Append(wx.ID_ANY, "Gestor de Marcadores\tCtrl+M")
        self.Bind(wx.EVT_MENU, self.al_abrir_marcadores, item_m)

        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, "Salir")
        self.Bind(wx.EVT_MENU, self.al_salir, item_salir)

        self.pestana_lectura.PopupMenu(menu)
        menu.Destroy()

    def _menu_contextual_grabacion(self):
        """Menú contextual de la pestaña Grabación: TXT recientes y proyectos."""
        menu = wx.Menu()

        # Submenú TXT recientes
        sub_txt = wx.Menu()
        if self.txt_recientes:
            gestor = self.pestana_grabacion.gestor_proyectos
            gestor.recargar()
            for i, ruta in enumerate(self.txt_recientes):
                nombre = os.path.basename(ruta)
                proyecto = gestor.proyecto_de_archivo(ruta)
                etiqueta = (
                    f"{i+1}. {nombre}  ({proyecto['nombre']})"
                    if proyecto else
                    f"{i+1}. {nombre}"
                )
                id_item = wx.NewIdRef()
                sub_txt.Append(id_item, etiqueta)
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, p=ruta: self._abrir_txt_reciente(p),
                    id=id_item,
                )
            sub_txt.AppendSeparator()
            id_borrar = wx.NewIdRef()
            sub_txt.Append(id_borrar, "Borrar historial de TXT")
            self.Bind(wx.EVT_MENU, self._al_borrar_txt_recientes, id=id_borrar)
        else:
            sub_txt.Append(wx.ID_ANY, "(Vacío)").Enable(False)
        menu.AppendSubMenu(sub_txt, "TXT Recientes para grabar")

        menu.AppendSeparator()

        item_proy = menu.Append(wx.ID_ANY, "Abrir Gestor de Proyectos")
        self.Bind(wx.EVT_MENU, self.al_abrir_gestor_proyectos, item_proy)

        menu.AppendSeparator()
        item_salir = menu.Append(wx.ID_EXIT, "Salir")
        self.Bind(wx.EVT_MENU, self.al_salir, item_salir)

        self.pestana_grabacion.PopupMenu(menu)
        menu.Destroy()
    # ANCLAJE_FIN: MENUS_CONTEXTUALES

    # ANCLAJE_INICIO: ACELERADORES_GLOBALES
    def _configurar_aceleradores_globales(self):
        """
        Aplica los atajos de teclado al Frame principal.
        Al estar en el Frame (no en el Panel), tienen prioridad sobre cualquier
        control hijo — incluyendo el RichTextCtrl que consumía las pulsaciones.
        Se llama al arranque y al volver a la pestaña Lectura para recoger cambios.
        """
        from app.motor.gestor_atajos import cargar_atajos
        atajos = cargar_atajos()
        entradas = []
        self._atajos_sin_modificador = set()  # Claves de tecla simple sin modificador

        for clave, entrada in atajos.items():
            mod_str = entrada.get("modificador", "")
            tecla_str = entrada.get("tecla", "")
            flag = _mod_a_flag(mod_str)
            keycode = _nombre_a_keycode(tecla_str)
            if flag is None or keycode < 0:
                continue
            # Reutilizar IDs para evitar acumulación (Bind sobreescribe el anterior)
            if clave not in self._ids_atajos_global:
                self._ids_atajos_global[clave] = wx.NewIdRef()
            id_atajo = self._ids_atajos_global[clave]
            entradas.append((flag, keycode, id_atajo))
            if flag == wx.ACCEL_NORMAL:
                # Tecla sin modificador (ej. Espacio): hay que ceder a botones con foco
                self._atajos_sin_modificador.add(clave)
            self.Bind(wx.EVT_MENU,
                      lambda e, c=clave: self._ejecutar_atajo_global(c),
                      id=id_atajo)

        # Atajos fijos adicionales (Ctrl+T, Ctrl+Shift+P, Ctrl+O, F1)
        _FIJOS_EXTRA = [
            ("ctrl_t",  wx.ACCEL_CTRL,              ord('T'), self.al_abrir_txt_grabacion),
            ("ctrl_sp", wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('P'), self.al_abrir_gestor_proyectos),
            ("ctrl_o",  wx.ACCEL_CTRL,              ord('O'), self._al_ctrl_o_contextual),
            ("f1",      wx.ACCEL_NORMAL,            wx.WXK_F1, self._al_abrir_ayuda_global),
        ]
        for clave, flag, keycode, handler in _FIJOS_EXTRA:
            if clave not in self._ids_atajos_global:
                self._ids_atajos_global[clave] = wx.NewIdRef()
            id_atajo = self._ids_atajos_global[clave]
            entradas.append((flag, keycode, id_atajo))
            self.Bind(wx.EVT_MENU, handler, id=id_atajo)

        if entradas:
            self.SetAcceleratorTable(wx.AcceleratorTable(entradas))

    def _ejecutar_atajo_global(self, clave):
        """Despacha el atajo de teclado al método correspondiente de PestanaLectura.

        Si el atajo es de tecla simple sin modificador (ej. Espacio) y el foco está
        en un botón, el espacio activa el botón en lugar de disparar nuestra acción.
        Atajos contextuales de Lectura (buscar, marcadores, ir_porcentaje) solo
        ejecutan cuando la pestaña Lectura está activa.
        """
        ctrl_foco = self.FindFocus()
        if (clave in getattr(self, '_atajos_sin_modificador', set())
                and ctrl_foco and isinstance(ctrl_foco, wx.Button)):
            ctrl_foco.GetEventHandler().ProcessEvent(
                wx.CommandEvent(wx.EVT_BUTTON.typeId, ctrl_foco.GetId())
            )
            return

        en_lectura = self.notebook.GetSelection() == IDX_LECTURA
        _ATAJOS_SOLO_LECTURA = {"buscar", "marcadores", "ir_porcentaje"}

        _ACCIONES = {
            "reproducir_pausar": lambda: self.pestana_lectura.al_alternar_reproduccion(None),
            "detener":           lambda: self.pestana_lectura.al_detener(None),
            "marcadores":        lambda: self.pestana_lectura.al_abrir_marcadores(None),
            "buscar":            lambda: self.pestana_lectura.iniciar_busqueda(),
            "ir_porcentaje":     lambda: self.pestana_lectura.iniciar_ir_a_pagina(),
        }
        if clave in _ACCIONES:
            if clave in _ATAJOS_SOLO_LECTURA and not en_lectura:
                return
            try:
                _ACCIONES[clave]()
            except Exception:
                pass
    # ANCLAJE_FIN: ACELERADORES_GLOBALES

    # ANCLAJE_INICIO: AYUDA
    def _al_ctrl_o_contextual(self, evento=None):
        """Ctrl+O: apertura contextual según la pestaña activa —
        importar carpeta en Biblioteca, libro en Lectura, TXT en Grabación.
        En Creador de Audiolibros no abre nada propio: solo anuncia que hay
        que enviar el libro desde Biblioteca (flujo de entrada único)."""
        indice = self.notebook.GetSelection()
        if indice == IDX_BIBLIOTECA:
            self.pestana_biblioteca.al_importar_carpeta(None)
        elif indice == IDX_LECTURA:
            self.pestana_lectura.al_cargar_libro(None)
        elif indice == IDX_CREADOR:
            self.pestana_creador.al_ctrl_o(None)
        elif indice == IDX_GRABACION:
            self.pestana_grabacion.al_examinar(None)

    def _al_abrir_ayuda_global(self, evento=None):
        """F1: abre ayuda.html con el visor predeterminado del sistema."""
        import subprocess
        from app.config_rutas import RAIZ
        ruta_ayuda = os.path.join(RAIZ, "ayuda.html")
        if not os.path.exists(ruta_ayuda):
            wx.MessageBox(
                f"No se encontró el archivo de ayuda en:\n{ruta_ayuda}",
                "Ayuda no encontrada", wx.OK | wx.ICON_INFORMATION,
            )
            return
        try:
            os.startfile(ruta_ayuda)
        except Exception:
            try:
                subprocess.Popen(["xdg-open", ruta_ayuda])
            except Exception as e:
                wx.MessageBox(str(e), "Error al abrir ayuda")

    def al_ver_atajos(self, evento):
        """Muestra un diálogo con todos los atajos actuales (defaults + personalizados)."""
        from app.motor.gestor_atajos import cargar_atajos, texto_atajo
        atajos = cargar_atajos()
        lineas = []
        for clave, entrada in atajos.items():
            desc = entrada.get("descripcion", clave)
            tecla = texto_atajo(entrada)
            lineas.append(f"• {desc}:  {tecla}")
        wx.MessageBox(
            "\n".join(lineas),
            "Atajos de teclado actuales",
            wx.OK | wx.ICON_INFORMATION
        )

    def al_abrir_readme(self, evento):
        """Abre el README del proyecto con el visor de texto predeterminado del sistema."""
        import subprocess
        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for nombre in ("README.md", "README.txt", "README"):
            ruta = os.path.join(raiz, nombre)
            if os.path.exists(ruta):
                try:
                    os.startfile(ruta)
                except Exception:
                    try:
                        subprocess.Popen(["xdg-open", ruta])
                    except Exception:
                        wx.MessageBox(f"README encontrado en:\n{ruta}", "README")
                return
        wx.MessageBox("No se encontró un archivo README en el directorio del proyecto.", "Info")

    def al_abrir_github(self, evento):
        """Abre el repositorio del proyecto en el navegador predeterminado."""
        import webbrowser
        webbrowser.open(_URL_GITHUB)

    def al_abrir_acerca_de(self, evento):
        """Muestra el diálogo Acerca de con información y créditos de la aplicación."""
        import webbrowser
        texto = (
            "Epub TTS Accesible\n"
            "Versión: Fase 3 (2026)\n\n"
            "Aplicación de texto a voz accesible para libros EPUB y archivos TXT.\n"
            "Diseñada para usuarios de lectores de pantalla como NVDA.\n\n"
            "Créditos\n"
            "Desarrollo: Dayanna Parson\n"
            "Asistencia IA: Claude (Anthropic)\n\n"
            "Proveedores de voz:\n"
            "  Microsoft Azure Text to Speech\n"
            "  Amazon Polly (AWS)\n"
            "  ElevenLabs\n"
            "  Microsoft SAPI5 (voces del sistema, sin coste)\n\n"
            "Repositorio: github.com/Dayanna-Parson/epub-tts-accesible"
        )
        wx.MessageBox(texto, "Acerca de Epub TTS Accesible", wx.OK | wx.ICON_INFORMATION)

    def al_abrir_releases(self, evento):
        """Abre la sección de Releases en GitHub."""
        import webbrowser
        webbrowser.open(f"{_URL_GITHUB}/releases")

    def al_abrir_tiflohistorias(self, evento):
        """Abre Tiflohistorias en el navegador predeterminado."""
        import webbrowser
        webbrowser.open("https://tiflotutos.com/tiflohistorias")

    def al_visitar_tiflotutos(self, evento):
        """Abre tiflotutos.com en el navegador predeterminado."""
        import webbrowser
        webbrowser.open("https://tiflotutos.com")

    def al_abrir_registros(self, evento=None):
        """Abre la carpeta de registros con el explorador de archivos."""
        import subprocess
        from app.config_rutas import RAIZ
        # OJO: era "app/registros" (carpeta huérfana, distinta de donde
        # iniciar_epub_tts.py escribe de verdad) — ver _RUTA_LOG ahí.
        carpeta = os.path.join(RAIZ, "registros")
        os.makedirs(carpeta, exist_ok=True)
        try:
            os.startfile(carpeta)
        except Exception:
            try:
                subprocess.Popen(["xdg-open", carpeta])
            except Exception as e:
                wx.MessageBox(str(e), "Error al abrir carpeta de registros")

    def al_copiar_registros(self, evento=None):
        """
        Copia el contenido de registros/app.log al portapapeles, para no
        depender de que el usuario encuentre y adjunte el archivo a mano
        (ruta fácil de confundir, y programas de sincronización en la nube
        pueden interferir con verlo actualizado desde el explorador).
        """
        from app.config_rutas import RAIZ
        ruta_log = os.path.join(RAIZ, "registros", "app.log")
        try:
            with open(ruta_log, "r", encoding="utf-8") as f:
                contenido = f.read()
        except Exception as e:
            wx.MessageBox(f"No se pudo leer el registro:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(contenido))
            wx.TheClipboard.Close()
            reproducir(SUCCESS)
            wx.MessageBox(
                "Registros copiados al portapapeles. Ya puedes pegarlos donde quieras.",
                "Registros copiados", wx.OK | wx.ICON_INFORMATION,
            )
        else:
            wx.MessageBox("No se pudo abrir el portapapeles.", "Error", wx.OK | wx.ICON_ERROR)

    def al_copiar_ultimo_error(self, evento=None):
        """
        Copia al portapapeles solo el archivo del error más reciente, de
        registros/errores/ — cada ERROR/CRITICAL se guarda ahí en su
        propio archivo (ver _HandlerErrorIndividual en iniciar_epub_tts.py),
        para no tener que buscarlo dentro del log combinado.
        """
        from app.config_rutas import RAIZ
        carpeta = os.path.join(RAIZ, "registros", "errores")
        try:
            archivos = [os.path.join(carpeta, n) for n in os.listdir(carpeta)]
        except Exception as e:
            wx.MessageBox(f"No se pudo leer la carpeta de errores:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        if not archivos:
            wx.MessageBox("No hay ningún error registrado todavía.", "Sin errores", wx.OK | wx.ICON_INFORMATION)
            return
        ultimo = max(archivos, key=os.path.getmtime)
        try:
            with open(ultimo, "r", encoding="utf-8") as f:
                contenido = f.read()
        except Exception as e:
            wx.MessageBox(f"No se pudo leer el error:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(contenido))
            wx.TheClipboard.Close()
            reproducir(SUCCESS)
            wx.MessageBox(
                f"Último error ({os.path.basename(ultimo)}) copiado al portapapeles.",
                "Error copiado", wx.OK | wx.ICON_INFORMATION,
            )
        else:
            wx.MessageBox("No se pudo abrir el portapapeles.", "Error", wx.OK | wx.ICON_ERROR)
    # ANCLAJE_FIN: AYUDA

    # ANCLAJE_INICIO: VERIFICACION_VOCES_NUEVAS
    # ANCLAJE_INICIO: COMPROBACION_ACTUALIZACIONES_ARRANQUE
    def _comprobar_actualizaciones_arranque(self):
        """
        Comprueba actualizaciones al arrancar si el usuario tiene activada
        la opción 'actualizar_automaticamente' en ajustes.json.
        Solo lanza la comprobación; el diálogo aparece en el hilo principal
        a través de wx.CallAfter en el callback.
        """
        import json
        from app.config_rutas import ruta_config
        try:
            with open(ruta_config("ajustes.json"), encoding="utf-8") as f:
                conf = json.load(f)
            if not conf.get("actualizar_automaticamente", True):
                return
        except Exception:
            pass
        try:
            from app.motor.comprobador_actualizaciones import ComprobadorActualizaciones
            comp = ComprobadorActualizaciones()
            comp.comprobar_en_hilo(
                lambda r: wx.CallAfter(self._al_resultado_actualizacion_arranque, r)
            )
        except Exception as e:
            logger.warning("Comprobación de actualizaciones al arranque fallida: %s", e)

    def _al_resultado_actualizacion_arranque(self, resultado: dict):
        if resultado.get("error") or not resultado.get("hay_nueva"):
            return
        from app.interfaz.dialogo_novedades import DialogoNovedades
        from app.motor.reproductor_sonidos import reproducir, SUCCESS
        reproducir(SUCCESS)
        v_remota = resultado.get("version_remota", "")
        dlg = DialogoNovedades(self, v_remota, resultado.get("novedades", ""))
        respuesta = dlg.ShowModal()
        dlg.Destroy()
        if respuesta == wx.ID_OK:
            self.pestana_ajustes._hilo_descargar_e_instalar_desde_arranque(v_remota)
    # ANCLAJE_FIN: COMPROBACION_ACTUALIZACIONES_ARRANQUE

    def _iniciar_verificacion_voces(self):
        """
        Comprueba si hay voces nuevas en las APIs (Azure, Polly, ElevenLabs).
        Solo se ejecuta si han pasado más de 24 horas desde la última comprobación.
        Corre en hilo de fondo para no bloquear la UI al arrancar.
        """
        from app.motor.verificador_voces_nuevas import VerificadorVocesNuevas
        verificador = VerificadorVocesNuevas()
        if not verificador.puede_verificar():
            return
        verificador.verificar_en_hilo(self._al_resultado_voces)

    def _al_resultado_voces(self, resultado: dict):
        """
        Recibe el dict del hilo de fondo.
        Usa wx.CallAfter para agendar cualquier acción de UI en el hilo principal.
        """
        nuevas = resultado.get("nuevas", {})
        if nuevas:
            wx.CallAfter(self._mostrar_dialogo_voces_nuevas, nuevas)

    def _mostrar_dialogo_voces_nuevas(self, nuevas: dict):
        """Muestra el diálogo de novedades (siempre en hilo principal)."""
        from app.interfaz.dialogo_voces_nuevas import DialogoVocesNuevas
        reproducir(SUCCESS)
        dlg = DialogoVocesNuevas(self, nuevas)
        dlg.ShowModal()
        dlg.Destroy()
    # ANCLAJE_FIN: VERIFICACION_VOCES_NUEVAS
# ANCLAJE_FIN: DEFINICION_VENTANA