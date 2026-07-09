import wx
import os
import sys
from app.motor.reproductor_sonidos import reproducir, LIST_NAV, OPEN_FOLDER

class DialogoMarcadores(wx.Dialog):
    """
    Ventana emergente para gestionar los marcadores del libro.
    """
    def __init__(self, padre, marcadores, posicion_actual):
        super().__init__(padre, title="Gestor de Marcadores", style=wx.DEFAULT_DIALOG_STYLE)
        
        self.marcadores = marcadores
        self.posicion_actual = posicion_actual
        self.debe_navegar = False
        self.posicion_seleccionada = None
        
        self._configurar_interfaz()
        self.CenterOnParent()

    def _configurar_interfaz(self):
        sizer_principal = wx.BoxSizer(wx.VERTICAL)
        
        lbl_titulo = wx.StaticText(self, label="Mis marcadores:")
        sizer_principal.Add(lbl_titulo, 0, wx.ALL, 5)
        
        # Lista
        self.lista_marcadores = wx.ListBox(self, style=wx.LB_SINGLE)
        
        # El doble clic activa la navegación directamente
        self.lista_marcadores.Bind(wx.EVT_LISTBOX_DCLICK, self.al_activar_item)

        # EVT_KEY_DOWN sobre ListBox en diálogos modales puede ser interceptado
        # por el botón por defecto del diálogo antes de llegar al control.
        # EVT_CHAR_HOOK a nivel de diálogo garantiza la captura sin importar el foco.
        self.lista_marcadores.Bind(wx.EVT_KEY_DOWN, self.al_tecla_lista)
        self.Bind(wx.EVT_CHAR_HOOK, self.al_char_hook_dialogo)
        
        sizer_principal.Add(self.lista_marcadores, 1, wx.EXPAND | wx.ALL, 5)
        
        # Botonera
        sizer_botones = wx.BoxSizer(wx.HORIZONTAL)
        
        self.btn_anadir = wx.Button(self, label="Nuevo")
        self.btn_anadir.Bind(wx.EVT_BUTTON, self.al_anadir_marcador)

        self.btn_renombrar = wx.Button(self, label="Renombrar")
        self.btn_renombrar.Bind(wx.EVT_BUTTON, self.al_renombrar_marcador)

        self.btn_eliminar = wx.Button(self, label="Eliminar")
        self.btn_eliminar.Bind(wx.EVT_BUTTON, self.al_eliminar_marcador)

        self.btn_cerrar = wx.Button(self, wx.ID_CANCEL, "Cerrar")
        
        sizer_botones.Add(self.btn_anadir, 0, wx.ALL, 5)
        sizer_botones.Add(self.btn_renombrar, 0, wx.ALL, 5)
        sizer_botones.Add(self.btn_eliminar, 0, wx.ALL, 5)
        sizer_botones.Add(self.btn_cerrar, 0, wx.ALL, 5)
        
        sizer_principal.Add(sizer_botones, 0, wx.EXPAND | wx.ALL, 5)
        
        self.SetSizer(sizer_principal)
        self.SetSize((500, 400))
        

        # IMPORTANTE: Llenamos la lista AL FINAL, cuando los botones ya existen
        self.llenar_lista()

    def llenar_lista(self):
        seleccion_previa = self.lista_marcadores.GetSelection()
        self.lista_marcadores.Clear()
        
        if not self.marcadores:
            self.lista_marcadores.Append("(Sin marcadores)")
            self.lista_marcadores.Enable(False)
            # Ahora esto no fallará porque los botones ya existen
            self.btn_renombrar.Disable()
            self.btn_eliminar.Disable()
        else:
            self.lista_marcadores.Enable(True)
            self.btn_renombrar.Enable()
            self.btn_eliminar.Enable()
            for nombre in self.marcadores.keys():
                self.lista_marcadores.Append(nombre)
            
            if seleccion_previa != wx.NOT_FOUND and seleccion_previa < self.lista_marcadores.GetCount():
                self.lista_marcadores.SetSelection(seleccion_previa)
            else:
                self.lista_marcadores.SetSelection(0)

    def al_char_hook_dialogo(self, evento):
        """
        Intercepta teclas críticas a nivel de diálogo.
        Garantiza que Enter sobre la lista navegue al marcador,
        incluso cuando el sistema de diálogos de wx intercepta el evento antes.
        """
        tecla = evento.GetKeyCode()
        if tecla == wx.WXK_RETURN and self.FindFocus() == self.lista_marcadores:
            self.al_activar_item(None)
            return
        evento.Skip()

    def al_tecla_lista(self, evento):
        """Gestiona teclas de acceso rápido directamente sobre la lista de marcadores."""
        tecla = evento.GetKeyCode()
        if tecla == wx.WXK_DELETE:
            self.al_eliminar_marcador(None)
        else:
            if tecla in (wx.WXK_UP, wx.WXK_DOWN):
                reproducir(LIST_NAV)
            evento.Skip()

    def al_activar_item(self, evento):
        if not self.lista_marcadores.IsEnabled(): return
        
        idx = self.lista_marcadores.GetSelection()
        if idx != wx.NOT_FOUND:
            nombre = self.lista_marcadores.GetString(idx)
            if nombre in self.marcadores:
                self.posicion_seleccionada = self.marcadores[nombre]
                self.debe_navegar = True
                self.EndModal(wx.ID_OK)

    def al_anadir_marcador(self, evento):
        dlg = wx.TextEntryDialog(self, "Nombre del nuevo marcador:", "Añadir Marcador")
        if dlg.ShowModal() == wx.ID_OK:
            nombre = dlg.GetValue().strip()
            if nombre:
                self.marcadores[nombre] = self.posicion_actual
                self.llenar_lista()
                idx = self.lista_marcadores.FindString(nombre)
                if idx != wx.NOT_FOUND: 
                    self.lista_marcadores.SetSelection(idx)
                self.lista_marcadores.SetFocus()
        dlg.Destroy()

    def al_renombrar_marcador(self, evento):
        idx = self.lista_marcadores.GetSelection()
        if idx == wx.NOT_FOUND: return
        
        nombre_viejo = self.lista_marcadores.GetString(idx)
        dlg = wx.TextEntryDialog(self, f"Nuevo nombre para '{nombre_viejo}':", "Renombrar Marcador", value=nombre_viejo)
        
        if dlg.ShowModal() == wx.ID_OK:
            nombre_nuevo = dlg.GetValue().strip()
            if nombre_nuevo and nombre_nuevo != nombre_viejo:
                pos = self.marcadores[nombre_viejo]
                del self.marcadores[nombre_viejo]
                self.marcadores[nombre_nuevo] = pos
                self.llenar_lista()
                
                idx_nuevo = self.lista_marcadores.FindString(nombre_nuevo)
                if idx_nuevo != wx.NOT_FOUND:
                    self.lista_marcadores.SetSelection(idx_nuevo)
                self.lista_marcadores.SetFocus()
        dlg.Destroy()

    def al_eliminar_marcador(self, evento):
        idx = self.lista_marcadores.GetSelection()
        if idx == wx.NOT_FOUND: return
        
        nombre = self.lista_marcadores.GetString(idx)
        if wx.MessageBox(f"¿Borrar '{nombre}'?", "Confirmar", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            if nombre in self.marcadores:
                del self.marcadores[nombre]
                self.llenar_lista()
                self.lista_marcadores.SetFocus()

class DialogoExportacion(wx.Dialog):
    """
    Diálogo que se muestra al finalizar una grabación.
    """
    def __init__(self, padre, mensaje, ruta_carpeta):
        super().__init__(padre, title="Proceso Completado", style=wx.DEFAULT_DIALOG_STYLE)
        
        self.ruta_carpeta = ruta_carpeta
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        hbox_msg = wx.BoxSizer(wx.HORIZONTAL)
        icono = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX)
        bmp = wx.StaticBitmap(self, bitmap=icono)
        lbl = wx.StaticText(self, label=mensaje)
        
        hbox_msg.Add(bmp, 0, wx.ALL, 10)
        hbox_msg.Add(lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 10)
        sizer.Add(hbox_msg, 1, wx.EXPAND | wx.ALL, 5)
        
        sizer_botones = wx.BoxSizer(wx.HORIZONTAL)
        
        self.btn_abrir = wx.Button(self, label="Abrir carpeta de destino")
        self.btn_abrir.Bind(wx.EVT_BUTTON, self.al_abrir_carpeta)
        self.btn_abrir.SetDefault()
        
        self.btn_cerrar = wx.Button(self, wx.ID_CANCEL, "Cerrar")
        
        sizer_botones.Add(self.btn_abrir, 0, wx.ALL, 5)
        sizer_botones.Add(self.btn_cerrar, 0, wx.ALL, 5)
        
        sizer.Add(sizer_botones, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Fit()
        self.CenterOnParent()

    def al_abrir_carpeta(self, evento):
        if os.path.exists(self.ruta_carpeta):
            reproducir(OPEN_FOLDER)
            if sys.platform == 'win32':
                os.startfile(self.ruta_carpeta)
        else:
            wx.MessageBox("La carpeta ya no existe.", "Error")
        self.EndModal(wx.ID_OK)


# ANCLAJE_INICIO: DIALOGO_ARCHIVO_NO_ENCONTRADO
class DialogoArchivoNoEncontrado(wx.Dialog):
    """
    Se muestra al intentar abrir un libro de la Biblioteca cuyo archivo
    ya no está en la ruta indexada (movido o borrado). Ofrece tres
    acciones (sección 2.4 de la planificación v3.0):
      - Localizar archivo: elegir manualmente el nuevo archivo de ese libro.
      - Volver a escanear una carpeta: reconciliar en bloque toda una
        carpeta movida, casando por nombre de archivo.
      - Eliminar de la biblioteca: quita el registro, nunca el archivo físico.

    El resultado se expone en self.accion ("localizar" / "reescanear" /
    "eliminar" / None) y, según el caso, en self.ruta_localizada o
    self.carpeta_reescaneo. Quien instancie el diálogo decide qué hacer
    con esa información tras ShowModal().
    """

    def __init__(self, padre, titulo_libro, extension_original):
        super().__init__(padre, title="Archivo no encontrado", style=wx.DEFAULT_DIALOG_STYLE)

        self.extension_original = extension_original
        self.accion = None
        self.ruta_localizada = None
        self.carpeta_reescaneo = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(
            self,
            label=(
                f"No se encontró el archivo de «{titulo_libro}» en su ubicación original.\n\n"
                "¿Qué quieres hacer?"
            ),
        )
        sizer.Add(lbl, 0, wx.ALL, 10)

        self.btn_localizar = wx.Button(self, label="Localizar archivo...")
        self.btn_localizar.SetHelpText(
            "Elige manualmente dónde está ahora el archivo de este libro."
        )
        self.btn_localizar.Bind(wx.EVT_BUTTON, self.al_localizar)
        sizer.Add(self.btn_localizar, 0, wx.EXPAND | wx.ALL, 5)

        self.btn_reescanear = wx.Button(self, label="Volver a escanear una carpeta...")
        self.btn_reescanear.SetHelpText(
            "Si moviste toda una carpeta de libros, elige la nueva ubicación y se "
            "reconciliarán en bloque todos los libros de la biblioteca que falten, "
            "casando por nombre de archivo."
        )
        self.btn_reescanear.Bind(wx.EVT_BUTTON, self.al_reescanear)
        sizer.Add(self.btn_reescanear, 0, wx.EXPAND | wx.ALL, 5)

        self.btn_eliminar = wx.Button(self, label="Eliminar de la biblioteca")
        self.btn_eliminar.SetHelpText(
            "Quita el registro de este libro de la biblioteca. El archivo físico, "
            "si existiera en algún sitio, no se borra."
        )
        self.btn_eliminar.Bind(wx.EVT_BUTTON, self.al_eliminar)
        sizer.Add(self.btn_eliminar, 0, wx.EXPAND | wx.ALL, 5)

        self.btn_cancelar = wx.Button(self, wx.ID_CANCEL, "Cancelar")
        sizer.Add(self.btn_cancelar, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer)
        self.Fit()
        self.CenterOnParent()
        self.btn_localizar.SetFocus()

    def al_localizar(self, evento):
        comodin = f"Archivos ({self.extension_original})|*{self.extension_original}|Todos los archivos|*.*"
        dlg = wx.FileDialog(
            self, "Localizar el archivo del libro", wildcard=comodin,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.accion = "localizar"
            self.ruta_localizada = dlg.GetPath()
            dlg.Destroy()
            self.EndModal(wx.ID_OK)
        else:
            dlg.Destroy()

    def al_reescanear(self, evento):
        dlg = wx.DirDialog(self, "Selecciona la carpeta donde están ahora los libros")
        if dlg.ShowModal() == wx.ID_OK:
            self.accion = "reescanear"
            self.carpeta_reescaneo = dlg.GetPath()
            dlg.Destroy()
            self.EndModal(wx.ID_OK)
        else:
            dlg.Destroy()

    def al_eliminar(self, evento):
        if wx.MessageBox(
            "¿Quitar este libro de la biblioteca?\n\nEl archivo no se borrará del disco, "
            "solo su registro aquí.",
            "Quitar de la biblioteca", wx.YES_NO | wx.ICON_QUESTION,
        ) == wx.YES:
            self.accion = "eliminar"
            self.EndModal(wx.ID_OK)
# ANCLAJE_FIN: DIALOGO_ARCHIVO_NO_ENCONTRADO