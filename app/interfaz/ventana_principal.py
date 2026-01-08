import wx
import os
import json
from app.interfaz.pestana_lectura import PestanaLectura
from app.interfaz.pestana_ajustes import PestanaAjustes

class VentanaPrincipal(wx.Frame):
    def __init__(self, padre, titulo):
        super().__init__(padre, title=titulo, size=(1000, 700))
        self.Maximize(True)

        # 1. Configurar Panel de Pestañas (Notebook)
        self.notebook = wx.Notebook(self)

        # Pestaña 1: Lectura
        self.pestana_lectura = PestanaLectura(self.notebook)
        self.notebook.AddPage(self.pestana_lectura, "Modo Lectura")

        # Pestaña 2: Grabación (Aún vacía)
        self.pestana_grabacion = wx.Panel(self.notebook)
        self.notebook.AddPage(self.pestana_grabacion, "Modo Grabación")
        
        # Pestaña 3: Ajustes
        self.pestana_ajustes = PestanaAjustes(self.notebook)
        self.notebook.AddPage(self.pestana_ajustes, "Ajustes")

        # 2. Configurar Menú
        self._configurar_menu()

        # Eventos
        self.Bind(wx.EVT_CLOSE, self.al_cerrar)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.al_cambiar_pestana)

        # Historial de recientes
        self.archivos_recientes = []
        self.ruta_recientes = os.path.join("configuraciones", "libros_recientes.json")
        self.cargar_historial_recientes()
        
        self.Show()

    def _configurar_menu(self):
        self.barra_menu = wx.MenuBar()
        
        # MENÚ ARCHIVO
        self.menu_archivo = wx.Menu()
        self.item_abrir = self.menu_archivo.Append(wx.ID_OPEN, "&Abrir Libro...\tCtrl+O")
        
        # Submenú Recientes
        self.menu_recientes = wx.Menu()
        self.menu_recientes.Append(wx.ID_ANY, "(Vacío)").Enable(False)
        self.menu_archivo.AppendSubMenu(self.menu_recientes, "Libros &Recientes")
        
        self.menu_archivo.AppendSeparator()
        self.item_salir = self.menu_archivo.Append(wx.ID_EXIT, "&Salir\tAlt+F4")
        
        self.barra_menu.Append(self.menu_archivo, "&Archivo")
        
        # MENÚ IR A
        self.menu_ir = wx.Menu()
        self.item_buscar = self.menu_ir.Append(wx.ID_FIND, "&Buscar en texto...\tCtrl+B")
        self.item_porcentaje = self.menu_ir.Append(wx.ID_ANY, "Ir a &Porcentaje...\tCtrl+G")
        self.item_marcadores = self.menu_ir.Append(wx.ID_ANY, "Gestor de &Marcadores...\tCtrl+M")
        
        self.barra_menu.Append(self.menu_ir, "&Ir a...")

        # MENÚ AYUDA
        self.menu_ayuda = wx.Menu()
        self.item_atajos = self.menu_ayuda.Append(wx.ID_ANY, "&Atajos de teclado")
        self.barra_menu.Append(self.menu_ayuda, "A&yuda")
        
        self.SetMenuBar(self.barra_menu)

        # Vincular eventos
        self.Bind(wx.EVT_MENU, self.al_abrir_archivo, self.item_abrir)
        self.Bind(wx.EVT_MENU, self.al_salir, self.item_salir)
        self.Bind(wx.EVT_MENU, self.al_abrir_marcadores, self.item_marcadores)
        self.Bind(wx.EVT_MENU, self.al_buscar, self.item_buscar)
        self.Bind(wx.EVT_MENU, self.al_ir_a_porcentaje, self.item_porcentaje)

    def al_cambiar_pestana(self, evento):
        indice = evento.GetSelection()
        es_lectura = (indice == 0)
        self.barra_menu.EnableTop(1, es_lectura) 
        evento.Skip()

    def al_abrir_archivo(self, evento):
    # Forzar cambio a pestaña de lectura
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
                self.pestana_lectura.detener_reproduccion_segura()
        except: pass
        self.Destroy()

    # --- GESTIÓN DE RECIENTES ---
    def cargar_historial_recientes(self):
        self.archivos_recientes = []
        try:
            if os.path.exists(self.ruta_recientes):
                with open(self.ruta_recientes, "r", encoding="utf-8") as archivo:
                    self.archivos_recientes = json.load(archivo)
        except: pass
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
        for item in self.menu_recientes.GetMenuItems():
            self.menu_recientes.Delete(item)
            
        if not self.archivos_recientes:
            self.menu_recientes.Append(wx.ID_ANY, "(Vacío)").Enable(False)
        else:
            for i, ruta in enumerate(self.archivos_recientes):
                nombre_archivo = os.path.basename(ruta)
                id_item = wx.NewIdRef()
                self.menu_recientes.Append(id_item, f"{i+1}. {nombre_archivo}")
                self.Bind(wx.EVT_MENU, lambda evt, p=ruta: self.abrir_libro_reciente(p), id=id_item)
            
            self.menu_recientes.AppendSeparator()
            item_borrar = self.menu_recientes.Append(wx.ID_ANY, "Borrar historial")
            self.Bind(wx.EVT_MENU, self.al_borrar_recientes, item_borrar)

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