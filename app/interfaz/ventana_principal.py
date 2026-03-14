# ANCLAJE_INICIO: DEPENDENCIAS_PRINCIPALES
import wx
import os
import json
import logging

logger = logging.getLogger(__name__)
from app.interfaz.pestana_lectura import PestanaLectura
from app.interfaz.pestana_ajustes import PestanaAjustes
from app.interfaz.pestana_grabacion import PestanaGrabacion
from app.interfaz.ventana_proyectos import VentanaProyectos
from app.config_rutas import ruta_config
from app.motor.reproductor_sonidos import reproducir, APP_READY, CLICK, OPEN_FOLDER
# ANCLAJE_FIN: DEPENDENCIAS_PRINCIPALES

# URL del repositorio (actualizar si cambia la ubicación del proyecto)
_URL_GITHUB = "https://github.com/Dayanna-Parson/epub-tts-accesible"

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

        # Pestaña 1: Lectura
        self.pestana_lectura = PestanaLectura(self.notebook)
        self.notebook.AddPage(self.pestana_lectura, "Modo Lectura")

        # Pestaña 2: Grabación multivoz
        self.pestana_grabacion = PestanaGrabacion(self.notebook)
        self.notebook.AddPage(self.pestana_grabacion, "Modo Grabación")
        
        # Pestaña 3: Ajustes
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
            self._mostrar_menu_contextual()
            return
        # Shift+F10 → ídem (alternativa universal para teclados sin tecla Menú)
        if keycode == wx.WXK_F10 and evento.ShiftDown():
            self._mostrar_menu_contextual()
            return

        # Ctrl+1 / Ctrl+2 / Ctrl+3 → cambiar de pestaña directamente
        # Solo cuando el foco está dentro de la ventana principal (no en diálogos externos)
        if evento.ControlDown() and keycode in (ord('1'), ord('2'), ord('3')):
            idx = keycode - ord('1')   # 0, 1 ó 2
            self.notebook.SetSelection(idx)
            return

        if keycode != wx.WXK_TAB:
            evento.Skip()
            return

        foco = self.FindFocus()
        if foco is None:
            evento.Skip()
            return

        shift = evento.ShiftDown()
        indice = self.notebook.GetSelection()

        if indice == 0:
            primer = self.pestana_lectura.primer_control
            ultimo = self.pestana_lectura.ultimo_control
        elif indice == 1:
            primer = self.pestana_grabacion.primer_control
            ultimo = self.pestana_grabacion.ultimo_control
        elif indice == 2:
            primer = self.pestana_ajustes.primer_control
            ultimo = self.pestana_ajustes.obtener_ultimo_control()
        else:
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
        if indice == 0:
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
        reproducir(OPEN_FOLDER)
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
        self.notebook.SetSelection(1)
        ruta_previa = self.pestana_grabacion.ruta_txt_actual
        self.pestana_grabacion.al_examinar(None)
        ruta_nueva = self.pestana_grabacion.ruta_txt_actual
        if ruta_nueva and ruta_nueva != ruta_previa:
            self.agregar_txt_a_recientes(ruta_nueva)

    def al_abrir_archivo(self, evento):
        self.notebook.SetSelection(0)
        self.pestana_lectura.al_cargar_libro(None)

    def al_abrir_marcadores(self, evento):
        if self.notebook.GetSelection() == 0:
            self.pestana_lectura.iniciar_marcadores()

    def al_buscar(self, evento):
        if self.notebook.GetSelection() == 0:
            self.pestana_lectura.iniciar_busqueda()

    def al_ir_a_porcentaje(self, evento): 
        if self.notebook.GetSelection() == 0:
            self.pestana_lectura.iniciar_ir_a_porcentaje()

    def al_salir(self, evento):
        self.Close()

    def al_cerrar(self, evento):
        try:
            if hasattr(self.pestana_lectura, 'reproductor'):
                self.pestana_lectura.al_detener(None)
        except Exception:
            logger.warning("Error al detener la reproducción durante el cierre", exc_info=True)
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

        # Restaurar pestaña activa
        ultima_pestana = config.get("ultima_pestana", 0)
        if isinstance(ultima_pestana, int) and 0 <= ultima_pestana <= 2:
            self.notebook.SetSelection(ultima_pestana)

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
            self.notebook.SetSelection(1)
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
            self.notebook.SetSelection(0)
            self.pestana_lectura.cargar_epub_desde_ruta(ruta)
        else:
            wx.MessageBox("El archivo ya no existe", "Error")
            if ruta in self.archivos_recientes:
                self.archivos_recientes.remove(ruta)
                self._guardar_recientes()
                self.actualizar_menu_recientes()
    # ANCLAJE_FIN: HISTORIAL_RECIENTES

    # ANCLAJE_INICIO: MENUS_CONTEXTUALES
    def _mostrar_menu_contextual(self):
        """Muestra el menú contextual correspondiente a la pestaña activa."""
        indice = self.notebook.GetSelection()
        if indice == 0:
            self._menu_contextual_lectura()
        elif indice == 1:
            self._menu_contextual_grabacion()
        # Pestaña Ajustes (2): no tiene menú contextual propio

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
        item_b = menu.Append(wx.ID_ANY, "Buscar en el texto")
        self.Bind(wx.EVT_MENU, self.al_buscar, item_b)
        item_g = menu.Append(wx.ID_ANY, "Ir a porcentaje")
        self.Bind(wx.EVT_MENU, self.al_ir_a_porcentaje, item_g)
        item_m = menu.Append(wx.ID_ANY, "Gestor de Marcadores")
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

        # Atajos fijos adicionales (Ctrl+T y Ctrl+Shift+P, antes en el menú)
        _FIJOS_EXTRA = [
            ("ctrl_t",  wx.ACCEL_CTRL,              ord('T'), self.al_abrir_txt_grabacion),
            ("ctrl_sp", wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('P'), self.al_abrir_gestor_proyectos),
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
        """
        ctrl_foco = self.FindFocus()
        if (clave in getattr(self, '_atajos_sin_modificador', set())
                and ctrl_foco and isinstance(ctrl_foco, wx.Button)):
            ctrl_foco.GetEventHandler().ProcessEvent(
                wx.CommandEvent(wx.EVT_BUTTON.typeId, ctrl_foco.GetId())
            )
            return

        _ACCIONES = {
            "abrir_libro":       lambda: (self.notebook.SetSelection(0),
                                          self.pestana_lectura.al_cargar_libro(None)),
            "reproducir_pausar": lambda: self.pestana_lectura.al_alternar_reproduccion(None),
            "detener":           lambda: self.pestana_lectura.al_detener(None),
            "marcadores":        lambda: self.pestana_lectura.al_abrir_marcadores(None),
            "buscar":            lambda: self.pestana_lectura.iniciar_busqueda(),
            "ir_porcentaje":     lambda: self.pestana_lectura.iniciar_ir_a_porcentaje(),
        }
        if clave in _ACCIONES:
            try:
                _ACCIONES[clave]()
            except Exception:
                pass
    # ANCLAJE_FIN: ACELERADORES_GLOBALES

    # ANCLAJE_INICIO: AYUDA
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
    # ANCLAJE_FIN: AYUDA

    # ANCLAJE_INICIO: VERIFICACION_VOCES_NUEVAS
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
        dlg = DialogoVocesNuevas(self, nuevas)
        dlg.ShowModal()
        dlg.Destroy()
    # ANCLAJE_FIN: VERIFICACION_VOCES_NUEVAS
# ANCLAJE_FIN: DEFINICION_VENTANA