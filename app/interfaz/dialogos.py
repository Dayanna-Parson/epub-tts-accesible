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