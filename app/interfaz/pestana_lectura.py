import wx
import os
import json
from app.motor.gestor_epub import extraer_datos_epub
from app.motor.reproductor_voz import ReproductorVoz
from app.interfaz.dialogos import DialogoMarcadores

class PestanaLectura(wx.Panel):
    def __init__(self, padre):
        super().__init__(padre, style=wx.TAB_TRAVERSAL)
        self.padre_notebook = padre
        
        self.reproductor = ReproductorVoz()
        
        self.posiciones_capitulos = {} 
        self.marcadores = {}       
        self.longitud_texto = 0
        
        self.segundos_salto = 10
        self.cargar_config_salto()
        
        self.pos_inicio_fragmento = 0
        self.ruta_libro_actual = None
        self.ruta_datos_lectura = os.path.join("configuraciones", "datos_lectura.json")
        
        sizer_principal = wx.BoxSizer(wx.VERTICAL)

        # 1. DIVISOR
        self.divisor = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        
        self.arbol_indice = wx.TreeCtrl(self.divisor, style=wx.TR_DEFAULT_STYLE | wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_HIDE_ROOT)
        self.arbol_indice.SetName("Índice")
        self.raiz_id = self.arbol_indice.AddRoot("Libro")
        self.arbol_indice.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.al_activar_capitulo) 

        self.txt_contenido = wx.TextCtrl(self.divisor, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL)
        self.txt_contenido.SetName("Contenido del libro") 
        self.txt_contenido.SetValue("Bienvenida. Pulsa Ctrl+A para abrir un libro EPUB.")
        self.txt_contenido.Bind(wx.EVT_KEY_UP, self.al_navegar_texto)
        
        self.divisor.SetMinimumPaneSize(200)
        self.divisor.SplitVertically(self.arbol_indice, self.txt_contenido, 280)
        sizer_principal.Add(self.divisor, 1, wx.EXPAND | wx.ALL, 5)

        # 2. PROGRESO
        sizer_progreso = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_progreso = wx.StaticText(self, label="Progreso: 0%")
        self.deslizador_progreso = wx.Slider(self, value=0, minValue=0, maxValue=100)
        self.deslizador_progreso.SetName("Barra de progreso")
        self.deslizador_progreso.Bind(wx.EVT_SLIDER, self.al_buscar_usuario)
        
        sizer_progreso.Add(self.lbl_progreso, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer_progreso.Add(self.deslizador_progreso, 1, wx.EXPAND, 0)
        sizer_principal.Add(sizer_progreso, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # 3. CONTROLES
        sizer_inferior = wx.BoxSizer(wx.HORIZONTAL)

        self.lbl_voz = wx.StaticText(self, label="Voz:")
        self.combo_voz = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_voz.SetName("Selector de voz")
        self.combo_voz.Bind(wx.EVT_COMBOBOX, self.al_cambiar_voz) # Evento clave

        self.btn_atras = wx.Button(self, label=f"Atrás {self.segundos_salto}s")
        self.btn_reproducir = wx.Button(self, label="Reproducir (Ctrl+P)")
        self.btn_adelante = wx.Button(self, label=f"Adelante {self.segundos_salto}s")
        self.btn_detener = wx.Button(self, label="Detener (Ctrl+D)")
        
        self.btn_reproducir.Bind(wx.EVT_BUTTON, self.al_alternar_reproduccion)
        self.btn_detener.Bind(wx.EVT_BUTTON, self.al_detener)
        self.btn_atras.Bind(wx.EVT_BUTTON, self.al_saltar_atras)
        self.btn_adelante.Bind(wx.EVT_BUTTON, self.al_saltar_adelante)

        self.lbl_velocidad = wx.StaticText(self, label="Velocidad:")
        self.deslizador_velocidad = wx.Slider(self, value=50, minValue=0, maxValue=100)
        self.deslizador_velocidad.SetName("Velocidad")
        self.deslizador_velocidad.Bind(wx.EVT_SLIDER, self.al_cambiar_velocidad)

        self.lbl_volumen = wx.StaticText(self, label="Volumen:")
        self.deslizador_volumen = wx.Slider(self, value=100, minValue=0, maxValue=100)
        self.deslizador_volumen.SetName("Volumen")
        self.deslizador_volumen.Bind(wx.EVT_SLIDER, self.al_cambiar_volumen)
        self.deslizador_volumen.Bind(wx.EVT_KEY_DOWN, self.al_tecla_volumen)

        sizer_inferior.Add(self.lbl_voz, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        sizer_inferior.Add(self.combo_voz, 1, wx.LEFT, 5)
        sizer_inferior.Add(self.btn_atras, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        sizer_inferior.Add(self.btn_reproducir, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        sizer_inferior.Add(self.btn_adelante, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        sizer_inferior.Add(self.btn_detener, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 15)
        sizer_inferior.Add(self.lbl_velocidad, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        sizer_inferior.Add(self.deslizador_velocidad, 1, wx.LEFT, 5)
        sizer_inferior.Add(self.lbl_volumen, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        sizer_inferior.Add(self.deslizador_volumen, 1, wx.LEFT, 5)

        sizer_principal.Add(sizer_inferior, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer_principal)
        self.configurar_aceleradores()
        
        self.temporizador_ui = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.al_actualizar_ui, self.temporizador_ui)
        self.temporizador_ui.Start(200)

        self.padre_notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.al_cambiar_pestana_padre)
        self.cargar_voces_usuario()
# --- Navegación accesible hacia las pestañas (Notebook) ---
        self.primer_control = self.arbol_indice
        self.ultimo_control = self.deslizador_volumen
        self.Bind(wx.EVT_CHAR_HOOK, self.al_navegacion_tab)





    def cargar_config_salto(self):
        try:
            ruta = os.path.join("configuraciones", "config_general.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    conf = json.load(f)
                    self.segundos_salto = int(conf.get("segundos_salto", 10))
        except: pass

    def al_cambiar_pestana_padre(self, event):
        if event.GetSelection() == 0:
            self.cargar_voces_usuario()
            self.cargar_config_salto()
            self.btn_atras.SetLabel(f"Atrás {self.segundos_salto}s")
            self.btn_adelante.SetLabel(f"Adelante {self.segundos_salto}s")
        event.Skip()

                    

    def cargar_voces_usuario(self):
        seleccion_previa = self.combo_voz.GetStringSelection()
        self.combo_voz.Clear()
        voces_para_combo = []
        
        # Locales
        try:
            if hasattr(self.reproductor, 'cliente_local'):
                voces_locales = self.reproductor.cliente_local.obtener_voces()
                for v in voces_locales:
                    nombre_mostrar = f"[Local] {v['nombre']}"
                    voces_para_combo.append((nombre_mostrar, v))
        except: pass

        # Nube Favoritas
        ruta_favs = os.path.join("configuraciones", "voces_favoritas.json")
        ruta_todas = os.path.join("configuraciones", "voces_disponibles.json")
        
        ids_favoritos = []
        if os.path.exists(ruta_favs):
            try:
                with open(ruta_favs, 'r', encoding='utf-8') as f: ids_favoritos = json.load(f)
            except: pass
            
        if ids_favoritos and os.path.exists(ruta_todas):
            try:
                with open(ruta_todas, 'r', encoding='utf-8') as f:
                    todas = json.load(f)
                    for prov, lista in todas.items():
                        for v in lista:
                            if v.get("id") in ids_favoritos:
                                v["proveedor_id"] = prov 
                                nombre_mostrar = f"[{prov.capitalize()}] {v['nombre']} ({v.get('idioma')})"
                                voces_para_combo.append((nombre_mostrar, v))
            except: pass

        if not voces_para_combo:
            self.combo_voz.Append("No hay voces disponibles")
        else:
            for nombre, datos in voces_para_combo:
                idx = self.combo_voz.Append(nombre)
                self.combo_voz.SetClientData(idx, datos)
            
            if seleccion_previa:
                res = self.combo_voz.FindString(seleccion_previa)
                if res != wx.NOT_FOUND:
                    self.combo_voz.SetSelection(res)
                else:
                    self.combo_voz.SetSelection(0)
            else:
                self.combo_voz.SetSelection(0)
        
        # Forzar actualización inicial
        # Nota: Aquí llamamos a al_cambiar_voz para que guarde la selección internamente,
        # pero como estamos en el init, no reproducirá nada.
        self.al_cambiar_voz(None)

    # --- FUNCIÓN CORREGIDA 1: CAMBIO DE VOZ ---
    def al_cambiar_voz(self, event):
        idx = self.combo_voz.GetSelection()
        if idx != wx.NOT_FOUND:
            # 1. Cogemos los datos de la voz que has seleccionado
            self.voz_seleccionada = self.combo_voz.GetClientData(idx)
            
            # 2. Le decimos al reproductor: "Prepara esta voz" 
            # (Con el nuevo reproductor, esto es instantáneo y no bloquea)
            if hasattr(self.reproductor, 'fijar_voz'):
                self.reproductor.fijar_voz(self.voz_seleccionada)
            
            # 3. Forzamos que se calle lo anterior por si acaso
            if hasattr(self.reproductor, 'detener'):
                self.reproductor.detener()

    # --- FUNCIÓN 2: REPRODUCCIÓN ---
    def al_alternar_reproduccion(self, evento):
        # 1. Estado
        estado = 'detenido'
        if hasattr(self.reproductor, 'obtener_estado'):
            estado = self.reproductor.obtener_estado()
        elif hasattr(self.reproductor, 'estado'):
            estado = self.reproductor.estado
            
        # 2. Play/Pausa
        if estado == 'reproduciendo':
            if hasattr(self.reproductor, 'pausar'): self.reproductor.pausar()
        elif estado == 'pausado':
            if hasattr(self.reproductor, 'reanudar'): self.reproductor.reanudar()
        else:
            # 3. Estado DETENIDO: Hablar
            pos_actual = self.txt_contenido.GetInsertionPoint()
            self.pos_inicio_fragmento = pos_actual
            
            texto_completo = self.txt_contenido.GetValue()
            if not texto_completo: return 
            
            fragmento = texto_completo[pos_actual:]
            
            # --- LÍMITE SOLO PARA NUBE ---
            es_nube = False
            if hasattr(self, 'voz_seleccionada') and self.voz_seleccionada:
                prov = self.voz_seleccionada.get('proveedor_id', 'local').lower()
                if 'azure' in prov or 'eleven' in prov or 'polly' in prov:
                    es_nube = True
            
            # Cortamos a 500 solo si es nube (para rapidez)
            if es_nube and len(fragmento) > 500:
                fragmento = fragmento[:500]
            
            if fragmento.strip():
                # Asegurar voz
                idx = self.combo_voz.GetSelection()
                if idx != wx.NOT_FOUND:
                    voz_data = self.combo_voz.GetClientData(idx)
                    if hasattr(self.reproductor, 'fijar_voz'):
                        self.reproductor.fijar_voz(voz_data)
                
                    self.reproductor.cargar_texto(fragmento)
    
    def al_actualizar_ui(self, evento):
        # 1. Actualizar etiqueta del botón Play/Pausa
        estado = "detenido"
        if hasattr(self.reproductor, 'obtener_estado'):
            estado = self.reproductor.obtener_estado()
        
        if estado == 'reproduciendo':
            if self.btn_reproducir.GetLabel() != "Pausar (Ctrl+P)": 
                self.btn_reproducir.SetLabel("Pausar (Ctrl+P)")
        elif estado == 'pausado':
            if self.btn_reproducir.GetLabel() != "Reanudar (Ctrl+P)": 
                self.btn_reproducir.SetLabel("Reanudar (Ctrl+P)")
        else:
            if self.btn_reproducir.GetLabel() != "Reproducir (Ctrl+P)": 
                self.btn_reproducir.SetLabel("Reproducir (Ctrl+P)")

        # 2. SINCRONIZAR BARRA DE PROGRESO CON TEXTO
        # Si hay texto cargado, actualizamos la barra según donde esté el cursor
        if self.longitud_texto > 0:
            pos_actual = self.txt_contenido.GetInsertionPoint()
            porcentaje = int((pos_actual / self.longitud_texto) * 100)
            
            # Solo actualizamos si ha cambiado para no saturar a NVDA
            if self.deslizador_progreso.GetValue() != porcentaje:
                self.deslizador_progreso.SetValue(porcentaje)
                self.lbl_progreso.SetLabel(f"Progreso: {porcentaje}%")
    def al_detener(self, evento): 
        if hasattr(self.reproductor, 'detener'):
            self.reproductor.detener()
        self.guardar_datos_libro()

    def al_saltar_atras(self, evento):
        pos = self.txt_contenido.GetInsertionPoint()
        caracteres = self.segundos_salto * 15 
        nuevo = max(0, pos - caracteres)
        self.txt_contenido.SetInsertionPoint(nuevo)
        self.txt_contenido.ShowPosition(nuevo)
        if hasattr(self.reproductor, 'estado') and self.reproductor.estado == 'reproduciendo':
             self.al_alternar_reproduccion(None)

    def al_saltar_adelante(self, evento):
        pos = self.txt_contenido.GetInsertionPoint()
        caracteres = self.segundos_salto * 15
        nuevo = min(self.longitud_texto, pos + caracteres)
        self.txt_contenido.SetInsertionPoint(nuevo)
        self.txt_contenido.ShowPosition(nuevo)
        if hasattr(self.reproductor, 'estado') and self.reproductor.estado == 'reproduciendo':
             self.al_alternar_reproduccion(None)

    def al_cambiar_velocidad(self, evento):
        if hasattr(self.reproductor, 'fijar_velocidad'): self.reproductor.fijar_velocidad(self.deslizador_velocidad.GetValue())
    
    def al_cambiar_volumen(self, evento):
        if hasattr(self.reproductor, 'fijar_volumen'): self.reproductor.fijar_volumen(self.deslizador_volumen.GetValue())
    
    def al_cargar_libro(self, evento):
        with wx.FileDialog(self, "Seleccionar EPUB", wildcard="Archivos EPUB (*.epub)|*.epub", style=wx.FD_OPEN) as dlg:
            if dlg.ShowModal() == wx.ID_OK: self.cargar_epub_desde_ruta(dlg.GetPath())
    
    def al_activar_capitulo(self, evento):
        id_item = evento.GetItem()
        titulo = self.arbol_indice.GetItemText(id_item)
        if titulo in self.posiciones_capitulos:
            pos = self.posiciones_capitulos[titulo]
            
            if hasattr(self.reproductor, 'detener'):
                self.reproductor.detener()
            
            self.txt_contenido.SetInsertionPoint(pos)
            self.txt_contenido.ShowPosition(pos)
            self.pos_inicio_fragmento = pos
            wx.CallAfter(self.txt_contenido.SetFocus)

    def iniciar_marcadores(self):
        self.al_abrir_marcadores(None)

    def al_abrir_marcadores(self, evento):
        # Importación local para evitar errores circulares
        from app.interfaz.dialogos import DialogoMarcadores
        pos_actual = self.txt_contenido.GetInsertionPoint()
        
        if not isinstance(self.marcadores, dict): self.marcadores = {}
            
        dlg = DialogoMarcadores(self, self.marcadores, pos_actual)
        resultado = dlg.ShowModal()
        
        # 1. Si elegimos ir a un marcador
        if resultado == wx.ID_OK:
            if dlg.debe_navegar and dlg.posicion_seleccionada is not None:
                self._ir_a_posicion(dlg.posicion_seleccionada)
        
        # 2. Guardamos SIEMPRE al cerrar la ventana (por si añadiste/borraste marcadores)
        self.marcadores = dlg.marcadores
        self.guardar_datos_libro()
        
        dlg.Destroy()

    def _ir_a_posicion(self, pos):
        """Ayuda para mover el cursor y parar audio"""
        if hasattr(self.reproductor, 'detener'): self.reproductor.detener()
        self.txt_contenido.SetInsertionPoint(pos)
        self.txt_contenido.ShowPosition(pos)
        self.txt_contenido.SetFocus()
        self.pos_inicio_fragmento = pos

    def iniciar_busqueda(self):
        dlg = wx.TextEntryDialog(self, "Texto o frase a buscar:", "Buscar en el libro")
        if dlg.ShowModal() == wx.ID_OK:
            consulta = dlg.GetValue().lower()
            if not consulta: return
            
            texto_completo = self.txt_contenido.GetValue().lower()
            coincidencias = []
            inicio = 0
            
            # Buscamos todas las apariciones
            while True:
                idx = texto_completo.find(consulta, inicio)
                if idx == -1: break
                # Guardamos posición y un fragmento de contexto (50 caracteres)
                contexto = self.txt_contenido.GetValue()[idx:idx+50].replace("\n", " ")
                coincidencias.append((idx, f"...{contexto}..."))
                inicio = idx + 1
            
            if not coincidencias:
                wx.MessageBox("No se encontraron coincidencias.", "Buscar")
            elif len(coincidencias) == 1:
                # Si solo hay una, vamos directo
                self._ir_a_posicion(coincidencias[0][0])
            else:
                # Si hay varias, mostramos lista para elegir
                opciones = [c[1] for c in coincidencias]
                dlg_lista = wx.SingleChoiceDialog(self, f"Se encontraron {len(coincidencias)} resultados:", "Seleccionar resultado", opciones)
                if dlg_lista.ShowModal() == wx.ID_OK:
                    seleccion = dlg_lista.GetSelection()
                    self._ir_a_posicion(coincidencias[seleccion][0])
                dlg_lista.Destroy()
        dlg.Destroy()

                
    def iniciar_ir_a_porcentaje(self): 
        dlg = wx.TextEntryDialog(self, "Porcentaje (0-100):", "Ir a")
        if dlg.ShowModal() == wx.ID_OK:
            val = dlg.GetValue()
            if val.isdigit():
                self.deslizador_progreso.SetValue(int(val))
                self.al_buscar_usuario(None)
        dlg.Destroy()

    def cargar_epub_desde_ruta(self, ruta):
        self.guardar_datos_libro()
        try:
            texto, datos_arbol, self.posiciones_capitulos = extraer_datos_epub(ruta)
            
            if hasattr(self.reproductor, 'detener'):
                self.reproductor.detener()
            
            self.marcadores = {}
            self.pos_inicio_fragmento = 0
            self.txt_contenido.SetValue(texto)
            self.longitud_texto = len(texto)
            self.arbol_indice.DeleteAllItems()
            self.raiz_id = self.arbol_indice.AddRoot(os.path.basename(ruta))
            self._construir_arbol_indice(self.raiz_id, datos_arbol)
            self.ruta_libro_actual = ruta
            self.cargar_datos_libro(os.path.basename(ruta))
            self.arbol_indice.SetFocus()
        except Exception as e: wx.MessageBox(f"Error: {e}")

    def _construir_arbol_indice(self, padre, nodos):
        for n in nodos:
            item = self.arbol_indice.AppendItem(padre, n['title'])
            if n['children']: self._construir_arbol_indice(item, n['children'])

    def al_tecla_volumen(self, e): e.Skip()
    
    def al_buscar_usuario(self, e):
        if self.longitud_texto > 0:
            objetivo = int((self.deslizador_progreso.GetValue()/100)*self.longitud_texto)
            self.txt_contenido.SetInsertionPoint(objetivo)
            self.txt_contenido.ShowPosition(objetivo)
            
            if hasattr(self.reproductor, 'detener'):
                self.reproductor.detener()
                
    def al_navegar_texto(self, e):
        estado = 'detenido'
        if hasattr(self.reproductor, 'obtener_estado'):
            estado = self.reproductor.obtener_estado()
            
        if estado != 'reproduciendo' and self.longitud_texto > 0:
            p = int((self.txt_contenido.GetInsertionPoint()/self.longitud_texto)*100)
            if self.deslizador_progreso.GetValue() != p: self.deslizador_progreso.SetValue(p)
        e.Skip()
        
    def guardar_datos_libro(self):
        if not self.ruta_libro_actual: return
        try:
            datos = {}
            if os.path.exists(self.ruta_datos_lectura):
                with open(self.ruta_datos_lectura, 'r') as f: datos = json.load(f)
            datos[os.path.basename(self.ruta_libro_actual)] = {"pos": self.txt_contenido.GetInsertionPoint(), "marcadores": self.marcadores}
            os.makedirs(os.path.dirname(self.ruta_datos_lectura), exist_ok=True)
            with open(self.ruta_datos_lectura, 'w') as f: json.dump(datos, f)
        except: pass
        
    def cargar_datos_libro(self, nombre):
        try:
            if os.path.exists(self.ruta_datos_lectura):
                with open(self.ruta_datos_lectura, 'r') as f:
                    d = json.load(f).get(nombre)
                    if d:
                        self.txt_contenido.SetInsertionPoint(d.get("pos", 0))
                        self.txt_contenido.ShowPosition(d.get("pos", 0))
                        self.marcadores = d.get("marcadores", {})
        except: pass
        
    def configurar_aceleradores(self):
        ids = [wx.NewIdRef() for _ in range(6)]
        self.Bind(wx.EVT_MENU, self.al_cargar_libro, id=ids[0])
        self.Bind(wx.EVT_MENU, self.al_abrir_marcadores, id=ids[1])
        self.Bind(wx.EVT_MENU, self.al_alternar_reproduccion, id=ids[2])
        self.Bind(wx.EVT_MENU, self.al_detener, id=ids[3])
        self.Bind(wx.EVT_MENU, lambda e: self.iniciar_busqueda(), id=ids[4])
        self.Bind(wx.EVT_MENU, lambda e: self.iniciar_ir_a_porcentaje(), id=ids[5])
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('A'), ids[0]), (wx.ACCEL_CTRL, ord('M'), ids[1]),
            (wx.ACCEL_CTRL, ord('P'), ids[2]), (wx.ACCEL_CTRL, ord('D'), ids[3]),
            (wx.ACCEL_CTRL, ord('B'), ids[4]), (wx.ACCEL_CTRL, ord('G'), ids[5])
        ]))