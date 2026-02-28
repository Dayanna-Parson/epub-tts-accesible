import wx
import os
import json
import webbrowser
import wx.lib.mixins.listctrl as listmix
from app.motor.gestor_voces import GestorVoces
from app.motor.reproductor_voz import ReproductorVoz

# --- CLASE ESPECIAL PARA LA LISTA CON CASILLAS ---
class ListaVocesCheck(wx.ListCtrl, listmix.CheckListCtrlMixin, listmix.ListCtrlAutoWidthMixin):
    def __init__(self, parent):
        wx.ListCtrl.__init__(self, parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES)
        listmix.CheckListCtrlMixin.__init__(self)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        # ESTO ES CRUCIAL PARA QUE SE VEAN LAS CASILLAS
        self.EnableCheckBoxes(True) 
        
        # Evento para que NVDA anuncie el cambio al pulsar espacio
        self.Bind(wx.EVT_LIST_KEY_DOWN, self.al_tecla)

    def al_tecla(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_SPACE:
            self.ToggleItem(self.GetFirstSelected())
        event.Skip()
from app.motor.control_cuota import ControlCuota # Importar al principio del archivo

class PanelGeneral(wx.ScrolledWindow):
    def __init__(self, padre, config):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config
        self.ruta_defecto = os.path.join(os.getcwd(), "grabaciones")
        self.cuota = ControlCuota() # Instancia para leer datos
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. EXPORTACIÓN
        sb_ruta = wx.StaticBox(self, label="Exportación de Audio")
        sizer_ruta = wx.StaticBoxSizer(sb_ruta, wx.VERTICAL)
        sizer_ruta.Add(wx.StaticText(self, label="Formato: MP3 a 320kbps."), 0, wx.ALL, 5)
        
        hbox_ruta = wx.BoxSizer(wx.HORIZONTAL)
        self.txt_ruta = wx.TextCtrl(self, style=wx.TE_READONLY)
        self.txt_ruta.SetValue(self.config.get("ruta_grabaciones", self.ruta_defecto))
        
        self.btn_examinar = wx.Button(self, label="Examinar...")
        self.btn_examinar.Bind(wx.EVT_BUTTON, self.al_examinar)
        self.btn_reset = wx.Button(self, label="Restablecer")
        self.btn_reset.Bind(wx.EVT_BUTTON, self.al_resetear_ruta)
        
        hbox_ruta.Add(self.txt_ruta, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ruta.Add(self.btn_examinar, 0, wx.RIGHT, 5)
        hbox_ruta.Add(self.btn_reset, 0)
        sizer_ruta.Add(hbox_ruta, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(sizer_ruta, 0, wx.EXPAND | wx.ALL, 10)

        # 2. CONTROL DE PRESUPUESTO (¡NUEVO!)
        sb_cuota = wx.StaticBox(self, label="Control de Presupuesto y Límites (Anti-Sustos)")
        sizer_cuota = wx.StaticBoxSizer(sb_cuota, wx.VERTICAL)
        
        # Explicación clara
        lbl_info = wx.StaticText(self, label=(
            "INFORMACIÓN IMPORTANTE:\n"
            "Cada API cobra por caracteres leídos. Establece aquí un límite mensual de seguridad.\n"
            "Si te pasas, la app bloqueará esa voz para que no te cobren más.\n\n"
            "• Azure: ~15€/millón (Gratis: 500k/mes)\n"
            "• Polly: ~$16/millón (Gratis: 1M/mes el 1er año)\n"
            "• ElevenLabs: Por suscripción (Gratis: 10k/mes)"
        ))
        sizer_cuota.Add(lbl_info, 0, wx.ALL, 5)
        sizer_cuota.Add(wx.StaticLine(self), 0, wx.EXPAND|wx.ALL, 5)

        # Controles Azure
        g_az, l_az = self.cuota.get_info_uso("azure")
        sizer_cuota.Add(self._crear_fila_limite("Azure", g_az, l_az, "azure"), 0, wx.EXPAND|wx.ALL, 2)
        
        # Controles Polly
        g_po, l_po = self.cuota.get_info_uso("polly")
        sizer_cuota.Add(self._crear_fila_limite("Polly", g_po, l_po, "polly"), 0, wx.EXPAND|wx.ALL, 2)
        
        # Controles Eleven
        g_el, l_el = self.cuota.get_info_uso("elevenlabs")
        sizer_cuota.Add(self._crear_fila_limite("ElevenLabs", g_el, l_el, "elevenlabs"), 0, wx.EXPAND|wx.ALL, 2)

        sizer.Add(sizer_cuota, 0, wx.EXPAND | wx.ALL, 10)

        # 3. NAVEGACIÓN
        sb_nav = wx.StaticBox(self, label="Navegación")
        sizer_nav = wx.StaticBoxSizer(sb_nav, wx.VERTICAL)
        hbox_salto = wx.BoxSizer(wx.HORIZONTAL)
        hbox_salto.Add(wx.StaticText(self, label="Segundos de salto:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 10)
        self.txt_salto = wx.TextCtrl(self, value=str(self.config.get("segundos_salto", "10")), size=(50, -1))
        hbox_salto.Add(self.txt_salto, 0)
        sizer_nav.Add(hbox_salto, 0, wx.ALL, 5)
        sizer.Add(sizer_nav, 0, wx.EXPAND | wx.ALL, 10)
        
        # GUARDAR — guardado como atributo para que VentanaPrincipal pueda usarlo
        # como punto de anclaje del bucle de tabulación accesible
        self.btn_guardar = wx.Button(self, label="Guardar Configuración General y Límites")
        self.btn_guardar.Bind(wx.EVT_BUTTON, lambda e: self.guardar_todo())
        sizer.Add(self.btn_guardar, 0, wx.ALL, 10)
        
        self.SetSizer(sizer)

    def _crear_fila_limite(self, nombre, gastado, limite, clave):
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label=f"{nombre} (Gastado: {gastado}):", size=(180, -1))
        txt = wx.TextCtrl(self, value=str(limite))
        txt.SetName(f"limite_{clave}") # Para identificarlo al guardar
        # Guardamos referencia para leerlo luego
        if not hasattr(self, "txt_limites"): self.txt_limites = {}
        self.txt_limites[clave] = txt
        
        hbox.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        hbox.Add(txt, 1, wx.EXPAND)
        return hbox

    def al_examinar(self, event):
        dlg = wx.DirDialog(self, "Selecciona carpeta")
        if self.txt_ruta.GetValue(): dlg.SetPath(self.txt_ruta.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.txt_ruta.SetValue(dlg.GetPath())
            self.config["ruta_grabaciones"] = dlg.GetPath()
            self.guardar_todo()
        dlg.Destroy()
        
    def al_resetear_ruta(self, event):
        self.txt_ruta.SetValue(self.ruta_defecto)
        self.config["ruta_grabaciones"] = self.ruta_defecto
        self.guardar_todo()

    def guardar_todo(self):
        # Guardar config general
        self.config["segundos_salto"] = self.txt_salto.GetValue()
        padre = self.GetParent().GetParent().GetParent()
        if hasattr(padre, "guardar_config_en_archivo"):
            padre.guardar_config_en_archivo()
            
        # Guardar límites de cuota
        if hasattr(self, "txt_limites"):
            for clave, txt in self.txt_limites.items():
                val = txt.GetValue()
                if val.isdigit():
                    self.cuota.set_limite(clave, int(val))
        
        wx.MessageBox("Configuración y límites guardados.")
class PanelClaves(wx.ScrolledWindow):
    def __init__(self, padre, config):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Configura tus claves API."), 0, wx.ALL, 10)

        # --- AZURE ---
        sb_az = wx.StaticBox(self, label="Microsoft Azure TTS")
        sz_az = wx.StaticBoxSizer(sb_az, wx.VERTICAL)
        
        sz_az.Add(wx.StaticText(self, label="Clave (Key):"), 0, wx.ALL, 2)
        self.txt_az_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        sz_az.Add(self.txt_az_key, 0, wx.EXPAND|wx.ALL, 5)
        
        sz_az.Add(wx.StaticText(self, label="Región (ej: eastus):"), 0, wx.ALL, 2)
        self.txt_az_region = wx.TextCtrl(self)
        sz_az.Add(self.txt_az_region, 0, wx.EXPAND|wx.ALL, 5)
        
        hb_az = wx.BoxSizer(wx.HORIZONTAL)
        btn_az_web = wx.Button(self, label="Conseguir clave")
        btn_az_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://azure.microsoft.com/es-es/services/cognitive-services/text-to-speech/"))
        btn_az_check = wx.Button(self, label="Comprobar y descargar")
        btn_az_check.Bind(wx.EVT_BUTTON, self.al_comprobar)
        btn_az_del = wx.Button(self, label="Borrar")
        btn_az_del.Bind(wx.EVT_BUTTON, self.al_borrar_azure)
        
        hb_az.Add(btn_az_web, 0, wx.RIGHT, 5)
        hb_az.Add(btn_az_check, 0, wx.RIGHT, 5)
        hb_az.Add(btn_az_del, 0)
        sz_az.Add(hb_az, 0, wx.ALL, 5)
        sizer.Add(sz_az, 0, wx.EXPAND|wx.ALL, 10)

        # --- AMAZON POLLY (Restaurado) ---
        sb_po = wx.StaticBox(self, label="Amazon Polly")
        sz_po = wx.StaticBoxSizer(sb_po, wx.VERTICAL)
        
        sz_po.Add(wx.StaticText(self, label="Access Key ID:"), 0, wx.ALL, 2)
        self.txt_po_key = wx.TextCtrl(self)
        sz_po.Add(self.txt_po_key, 0, wx.EXPAND|wx.ALL, 5)
        
        sz_po.Add(wx.StaticText(self, label="Secret Access Key:"), 0, wx.ALL, 2)
        self.txt_po_secret = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        sz_po.Add(self.txt_po_secret, 0, wx.EXPAND|wx.ALL, 5)
        
        sz_po.Add(wx.StaticText(self, label="Región (ej: us-east-1):"), 0, wx.ALL, 2)
        self.txt_po_region = wx.TextCtrl(self)
        sz_po.Add(self.txt_po_region, 0, wx.EXPAND|wx.ALL, 5)
        
        hb_po = wx.BoxSizer(wx.HORIZONTAL)
        btn_po_web = wx.Button(self, label="Conseguir clave")
        btn_po_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://aws.amazon.com/polly/"))
        btn_po_check = wx.Button(self, label="Comprobar")
        btn_po_check.Bind(wx.EVT_BUTTON, self.al_comprobar)
        
        hb_po.Add(btn_po_web, 0, wx.RIGHT, 5)
        hb_po.Add(btn_po_check, 0)
        sz_po.Add(hb_po, 0, wx.ALL, 5)
        sizer.Add(sz_po, 0, wx.EXPAND|wx.ALL, 10)

        # --- ELEVENLABS ---
        sb_el = wx.StaticBox(self, label="ElevenLabs")
        sz_el = wx.StaticBoxSizer(sb_el, wx.VERTICAL)
        
        sz_el.Add(wx.StaticText(self, label="API Key:"), 0, wx.ALL, 2)
        self.txt_el_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        sz_el.Add(self.txt_el_key, 0, wx.EXPAND|wx.ALL, 5)
        
        hb_el = wx.BoxSizer(wx.HORIZONTAL)
        btn_el_web = wx.Button(self, label="Conseguir clave")
        btn_el_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://elevenlabs.io/"))
        btn_el_check = wx.Button(self, label="Comprobar")
        btn_el_check.Bind(wx.EVT_BUTTON, self.al_comprobar)
        
        hb_el.Add(btn_el_web, 0, wx.RIGHT, 5)
        hb_el.Add(btn_el_check, 0)
        sz_el.Add(hb_el, 0, wx.ALL, 5)
        sizer.Add(sz_el, 0, wx.EXPAND|wx.ALL, 10)

        # --- GUARDAR — atributo de instancia para el bucle de tabulación accesible ---
        self.btn_save = wx.Button(self, label="Guardar Todas las Claves")
        self.btn_save.Bind(wx.EVT_BUTTON, self.al_guardar)
        sizer.Add(self.btn_save, 0, wx.ALIGN_CENTER|wx.ALL, 15)
        
        self.SetSizer(sizer)
        self.cargar_datos_visuales()

    def cargar_datos_visuales(self):
        d_az = self.config.get("azure", {})
        self.txt_az_key.SetValue(d_az.get("key", ""))
        self.txt_az_region.SetValue(d_az.get("region", ""))
        
        d_po = self.config.get("polly", {})
        self.txt_po_key.SetValue(d_po.get("access_key", ""))
        self.txt_po_secret.SetValue(d_po.get("secret_key", ""))
        self.txt_po_region.SetValue(d_po.get("region", ""))
        
        d_el = self.config.get("elevenlabs", {})
        self.txt_el_key.SetValue(d_el.get("api_key", ""))

    def al_guardar(self, event):
        self.config["azure"] = {
            "key": self.txt_az_key.GetValue().strip(),
            "region": self.txt_az_region.GetValue().strip()
        }
        self.config["polly"] = {
            "access_key": self.txt_po_key.GetValue().strip(),
            "secret_key": self.txt_po_secret.GetValue().strip(),
            "region": self.txt_po_region.GetValue().strip()
        }
        self.config["elevenlabs"] = {
            "api_key": self.txt_el_key.GetValue().strip()
        }
        self.GetParent().GetParent().GetParent().guardar_config_en_archivo()
        if event: wx.MessageBox("Claves guardadas.", "Éxito")

    def al_borrar_azure(self, event):
        self.txt_az_key.Clear()
        self.txt_az_region.Clear()
        self.al_guardar(None)

    def al_comprobar(self, event):
        self.al_guardar(None)
        wx.BeginBusyCursor()
        try:
            gestor = GestorVoces()
            res = gestor.actualizar_voces_desde_internet()
            wx.EndBusyCursor()
            wx.MessageBox(f"Resultado:\n{res}", "Info")
        except Exception as e:
            wx.EndBusyCursor()
            wx.MessageBox(f"Error: {e}", "Error")

class PanelVoces(wx.Panel):
    def __init__(self, padre, config):
        super().__init__(padre)
        self.config = config
        self.voces_todas = [] 
        self.reproductor = ReproductorVoz()
        self.ruta_favs = os.path.join("configuraciones", "voces_favoritas.json")
        self.favoritos = self.cargar_favoritos()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. CONFIGURACIÓN LIBRO
        sb_libro = wx.StaticBox(self, label="Configuración del Libro")
        sz_libro = wx.StaticBoxSizer(sb_libro, wx.VERTICAL)
        sz_libro.Add(wx.StaticText(self, label="Idioma del libro (Para acento):"), 0, wx.BOTTOM, 5)
        self.combo_idioma_libro = wx.ComboBox(self, choices=["Detectar auto", "Español (ES)", "Español (LAT)", "Inglés"], style=wx.CB_READONLY)
        
        # Cargar selección guardada
        conf_idioma = self.config.get("idioma_libro_codigo", "es-ES")
        if conf_idioma == "es-MX": self.combo_idioma_libro.SetSelection(2)
        elif conf_idioma == "en-US": self.combo_idioma_libro.SetSelection(3)
        else: self.combo_idioma_libro.SetSelection(1) # Por defecto ES
        
        self.combo_idioma_libro.Bind(wx.EVT_COMBOBOX, self.al_cambiar_idioma_libro)
        
        sz_libro.Add(self.combo_idioma_libro, 0, wx.EXPAND|wx.ALL, 5)
        sizer.Add(sz_libro, 0, wx.EXPAND|wx.ALL, 10)
        
        # 2. FILTROS DE VOCES
        sb_filtros = wx.StaticBox(self, label="Filtros de Voces")
        sz_filtros = wx.StaticBoxSizer(sb_filtros, wx.VERTICAL)
        
        # Fila A: Idioma y Proveedor
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        hbox1.Add(wx.StaticText(self, label="Idioma:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.combo_idioma = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos"])
        self.combo_idioma.SetSelection(0)
        self.combo_idioma.Bind(wx.EVT_COMBOBOX, self.al_filtrar)
        hbox1.Add(self.combo_idioma, 1, wx.RIGHT, 15)

        hbox1.Add(wx.StaticText(self, label="Proveedor:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.combo_proveedor = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos"])
        self.combo_proveedor.SetSelection(0)
        self.combo_proveedor.Bind(wx.EVT_COMBOBOX, self.al_filtrar)
        hbox1.Add(self.combo_proveedor, 0)
        sz_filtros.Add(hbox1, 0, wx.EXPAND|wx.ALL, 5)
        
        # Fila B: Tipo y Gestión
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        hbox2.Add(wx.StaticText(self, label="Tipo:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.combo_tipo = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos", "Femenino", "Masculino", "Multilingüe", "Dragon"])
        self.combo_tipo.SetSelection(0)
        self.combo_tipo.Bind(wx.EVT_COMBOBOX, self.al_filtrar)
        hbox2.Add(self.combo_tipo, 0, wx.RIGHT, 15)
        
        # Casillas de gestión y filtros especiales
        self.chk_solo_favs = wx.CheckBox(self, label="Solo favoritas")
        self.chk_solo_favs.Bind(wx.EVT_CHECKBOX, self.al_filtrar)
        hbox2.Add(self.chk_solo_favs, 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 15)

        self.chk_solo_nuevas = wx.CheckBox(self, label="Solo nuevas voces")
        self.chk_solo_nuevas.Bind(wx.EVT_CHECKBOX, self.al_filtrar)
        hbox2.Add(self.chk_solo_nuevas, 0, wx.ALIGN_CENTER_VERTICAL)
        sz_filtros.Add(hbox2, 0, wx.EXPAND|wx.ALL, 5)

        # Fila C: Buscador
        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        hbox3.Add(wx.StaticText(self, label="Buscar nombre:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.txt_buscar = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_buscar.Bind(wx.EVT_TEXT, self.al_filtrar)
        hbox3.Add(self.txt_buscar, 1, wx.EXPAND)
        sz_filtros.Add(hbox3, 0, wx.EXPAND|wx.ALL, 5)
        
        sizer.Add(sz_filtros, 0, wx.EXPAND|wx.ALL, 10)
        
        # 3. LISTA — columnas con Carga Cognitiva Frontal para NVDA:
        # el lector anuncia primero el nombre enriquecido con etiquetas
        self.lista_voces = ListaVocesCheck(self)
        self.lista_voces.InsertColumn(0, "Nombre", width=280)
        self.lista_voces.InsertColumn(1, "Género", width=80)
        self.lista_voces.InsertColumn(2, "Idioma", width=160)
        self.lista_voces.InsertColumn(3, "Proveedor", width=110)
        
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_CHECKED, self.al_marcar_favorito)
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.al_desmarcar_favorito)
        
        sizer.Add(self.lista_voces, 1, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        
        # 4. BOTONERA — atributo de instancia para el bucle de tabulación accesible
        self.btn_escuchar = wx.Button(self, label="Escuchar muestra (Alt+P)")
        self.btn_escuchar.Bind(wx.EVT_BUTTON, self.al_escuchar)
        sizer.Add(self.btn_escuchar, 0, wx.ALIGN_RIGHT|wx.ALL, 10)
        
        id_play = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self.al_escuchar, id=id_play)
        self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_ALT, ord('P'), id_play)]))
        
        self.SetSizer(sizer)
        self.cargar_datos_y_llenar()

    def al_cambiar_idioma_libro(self, event):
        seleccion = self.combo_idioma_libro.GetSelection()
        codigo = "es-ES" 
        
        if seleccion == 2: codigo = "es-MX"
        elif seleccion == 3: codigo = "en-US"
        elif seleccion == 0: codigo = "es-ES"
        
        self.config["idioma_libro_codigo"] = codigo
        # Guardar en disco
        try:
            padre_ajustes = self.GetParent().GetParent().GetParent()
            if hasattr(padre_ajustes, "guardar_config_en_archivo"):
                padre_ajustes.guardar_config_en_archivo()
        except: pass

    def cargar_favoritos(self):
        try:
            if os.path.exists(self.ruta_favs):
                with open(self.ruta_favs, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Error] No se pudo leer voces_favoritas.json: {e}")
        return []

    def guardar_favoritos(self):
        try:
            with open(self.ruta_favs, 'w', encoding='utf-8') as f: json.dump(self.favoritos, f, indent=4)
        except Exception as e: print(f"Error guardando favs: {e}")

    def al_marcar_favorito(self, event):
        idx = event.GetIndex()
        voz = self.mapa_indices.get(idx)
        if voz:
            id_voz = voz.get("id")
            if id_voz not in self.favoritos:
                self.favoritos.append(id_voz)
                self.guardar_favoritos()

    def al_desmarcar_favorito(self, event):
        idx = event.GetIndex()
        voz = self.mapa_indices.get(idx)
        if voz:
            id_voz = voz.get("id")
            if id_voz in self.favoritos:
                self.favoritos.remove(id_voz)
                self.guardar_favoritos()

    def cargar_datos_y_llenar(self):
        ruta = os.path.join("configuraciones", "voces_disponibles.json")
        self.voces_todas = []
        idiomas = set()
        
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    for prov, lista in datos.items():
                        for v in lista:
                            v["proveedor_id"] = prov
                            self.voces_todas.append(v)
                            if v.get("idioma"): idiomas.add(v.get("idioma"))
            except Exception as e:
                print(f"[Error] No se pudo leer voces_disponibles.json: {e}")
                self.voces_todas = []
            
        lista_idiomas = sorted(list(idiomas))
        self.combo_idioma.Clear()
        self.combo_idioma.Append("Todos")
        self.combo_idioma.AppendItems(lista_idiomas)
        self.combo_idioma.SetSelection(0)
        
        self.combo_proveedor.Clear()
        self.combo_proveedor.AppendItems(["Todos", "Azure", "Amazon Polly", "ElevenLabs"])
        self.combo_proveedor.SetSelection(0)
        
        self.filtrar_y_mostrar()

    # Tabla de traducción de códigos de idioma a texto legible en español
    _LOCALES_ES = {
        "en-US": "Inglés (Estados Unidos)",
        "en-GB": "Inglés (Reino Unido)",
        "en-AU": "Inglés (Australia)",
        "en-CA": "Inglés (Canadá)",
        "es-ES": "Español (España)",
        "es-MX": "Español (México)",
        "es-AR": "Español (Argentina)",
        "es-CO": "Español (Colombia)",
        "fr-FR": "Francés (Francia)",
        "fr-CA": "Francés (Canadá)",
        "de-DE": "Alemán (Alemania)",
        "it-IT": "Italiano (Italia)",
        "pt-BR": "Portugués (Brasil)",
        "pt-PT": "Portugués (Portugal)",
        "ja-JP": "Japonés (Japón)",
        "zh-CN": "Chino (Mandarín)",
        "ko-KR": "Coreano (Corea del Sur)",
        "ar-SA": "Árabe (Arabia Saudí)",
        "ru-RU": "Ruso (Rusia)",
        "nl-NL": "Neerlandés (Países Bajos)",
        "pl-PL": "Polaco (Polonia)",
        "sv-SE": "Sueco (Suecia)",
        "Multilingüe (v2)": "Multilingüe",
    }

    # Tabla de traducción de género
    _GENEROS_ES = {
        "Female": "Femenino",
        "Male": "Masculino",
        "Neutral": "Neutro",
    }

    def _construir_nombre_enriquecido(self, voz):
        """
        Construye el nombre visible de la voz inyectando etiquetas semánticas
        que adelantan información relevante al principio para NVDA.
        Ejemplo: 'Aria [Dragon] [Multilingüe]'
        """
        nombre_base = voz.get("nombre", "")
        id_voz = voz.get("id", "").lower()
        etiquetas = []

        if "dragonhd" in id_voz or "dragon" in id_voz:
            etiquetas.append("[Dragon]")
        if "multilingual" in id_voz:
            etiquetas.append("[Multilingüe]")
        if "hd" in id_voz and "dragonhd" not in id_voz:
            etiquetas.append("[HD]")
        if voz.get("es_nueva"):
            etiquetas.append("[Nueva]")

        if etiquetas:
            return f"{nombre_base} {' '.join(etiquetas)}"
        return nombre_base

    def al_filtrar(self, event):
        self.filtrar_y_mostrar()

    def filtrar_y_mostrar(self):
        self.lista_voces.DeleteAllItems()

        f_idioma = self.combo_idioma.GetValue()
        f_tipo = self.combo_tipo.GetValue()
        f_prov = self.combo_proveedor.GetValue()
        f_texto = self.txt_buscar.GetValue().lower()

        solo_favs = self.chk_solo_favs.IsChecked() if hasattr(self, 'chk_solo_favs') else False
        solo_nuevas = self.chk_solo_nuevas.IsChecked() if hasattr(self, 'chk_solo_nuevas') else False

        self.mapa_indices = {}
        idx = 0

        for voz in self.voces_todas:
            nombre_lower = voz.get("nombre", "").lower()
            id_voz = voz.get("id", "")
            prov_raw = voz.get("proveedor_id", "local").lower()
            es_favorita = id_voz in self.favoritos
            es_nueva = bool(voz.get("es_nueva"))

            # Filtros especiales exclusivos (tienen prioridad sobre el resto)
            if solo_nuevas:
                if not es_nueva: continue
            elif solo_favs:
                if not es_favorita: continue
            else:
                if f_idioma != "Todos" and voz.get("idioma") != f_idioma: continue

                if f_prov != "Todos":
                    if f_prov == "Amazon Polly" and "polly" not in prov_raw: continue
                    elif f_prov == "Azure" and "azure" not in prov_raw: continue
                    elif f_prov == "ElevenLabs" and "eleven" not in prov_raw: continue

                if f_tipo != "Todos":
                    genero_raw = voz.get("genero", "")
                    id_lower = id_voz.lower()
                    if f_tipo == "Femenino" and genero_raw != "Female": continue
                    if f_tipo == "Masculino" and genero_raw != "Male": continue
                    if f_tipo == "Multilingüe" and "multilingual" not in id_lower: continue
                    if f_tipo == "Dragon" and "dragon" not in id_lower: continue

                if f_texto and f_texto not in nombre_lower: continue

            # Construir nombre enriquecido con etiquetas
            nombre_mostrar = self._construir_nombre_enriquecido(voz)

            # Traducir género al español
            genero_mostrar = self._GENEROS_ES.get(voz.get("genero", ""), voz.get("genero", ""))

            # Traducir código de idioma a nombre legible
            idioma_raw = voz.get("idioma", "")
            idioma_mostrar = self._LOCALES_ES.get(idioma_raw, idioma_raw)

            # Normalizar nombre del proveedor
            prov_mostrar = prov_raw.capitalize()
            if prov_raw == "polly":
                prov_mostrar = "Amazon Polly"
            elif prov_raw == "elevenlabs":
                prov_mostrar = "ElevenLabs"

            pos = self.lista_voces.InsertItem(idx, nombre_mostrar)
            self.lista_voces.SetItem(pos, 1, genero_mostrar)
            self.lista_voces.SetItem(pos, 2, idioma_mostrar)
            self.lista_voces.SetItem(pos, 3, prov_mostrar)

            if es_favorita:
                self.lista_voces.CheckItem(pos, True)

            self.mapa_indices[pos] = voz
            idx += 1

    def al_escuchar(self, event):
        idx = self.lista_voces.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Selecciona una voz.", "Info")
            return
        
        voz = self.mapa_indices.get(idx)
        nombre = voz.get('nombre')
        try:
            self.reproductor.fijar_voz(voz)
            texto = (f"Hola, soy {nombre}. "
                     "Esta es una prueba de lectura para comprobar la calidad y el acento de mi voz. "
                     "¿Qué te parece como sueno?")
            self.reproductor.cargar_texto(texto)
        except Exception as e:
            wx.MessageBox(f"Error: {e}", "Error")    
class PanelAtajos(wx.Panel):
        def __init__(self, padre):
            super().__init__(padre)
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(wx.StaticText(self, label="Atajos de teclado configurables"), 0, wx.ALL, 10)
            self.SetSizer(sizer)

class PestanaAjustes(wx.Panel):
    def __init__(self, padre):
        super().__init__(padre)
        self.ruta_config = os.path.join("configuraciones", "config_general.json")
        self.config = self.cargar_config()

        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        
        self.lista_cat = wx.ListBox(self.splitter, style=wx.LB_SINGLE)
        self.lista_cat.Append("General")
        self.lista_cat.Append("Claves y Proveedores")
        self.lista_cat.Append("Voces e Idiomas")
        self.lista_cat.Append("Atajos de teclado")
        self.lista_cat.SetSelection(0)
        self.lista_cat.Bind(wx.EVT_LISTBOX, self.al_cambiar_cat)

        self.panel_derecho = wx.Simplebook(self.splitter)
        self.pag_general = PanelGeneral(self.panel_derecho, self.config)
        self.pag_claves = PanelClaves(self.panel_derecho, self.config)
        self.pag_voces = PanelVoces(self.panel_derecho, self.config)
        self.pag_atajos = PanelAtajos(self.panel_derecho)
        
        self.panel_derecho.AddPage(self.pag_general, "General")
        self.panel_derecho.AddPage(self.pag_claves, "Claves")
        self.panel_derecho.AddPage(self.pag_voces, "Voces")
        self.panel_derecho.AddPage(self.pag_atajos, "Atajos")
        
        self.splitter.SetMinimumPaneSize(150)
        self.splitter.SplitVertically(self.lista_cat, self.panel_derecho, 200)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND|wx.ALL, 5)
        self.SetSizer(sizer)

        # Puntos de anclaje para el bucle de tabulación gestionado desde VentanaPrincipal
        self.primer_control = self.lista_cat

    def obtener_ultimo_control(self):
        """
        Devuelve el último control navegable del sub-panel activo en ese momento.
        VentanaPrincipal lo consulta para saber cuándo Tab debe volver al Notebook.
        """
        idx = self.panel_derecho.GetSelection()
        if idx == 0:
            return self.pag_general.btn_guardar
        elif idx == 1:
            return self.pag_claves.btn_save
        elif idx == 2:
            return self.pag_voces.btn_escuchar
        else:
            # PanelAtajos no tiene controles interactivos: el bucle vuelve al inicio
            return self.lista_cat

    def al_cambiar_cat(self, event):
        idx = self.lista_cat.GetSelection()
        if idx != wx.NOT_FOUND:
            self.panel_derecho.ChangeSelection(idx)
            # Sin event.Skip(): evita que EVT_LISTBOX suba al splitter/parent y
            # mueva el foco al panel derecho al navegar con flechas en la lista.
            # Sin SetFocus(): evita la doble anunciación de NVDA.
            if idx == 2:
                self.pag_voces.cargar_datos_y_llenar()

    def cargar_config(self):
        try:
            with open(self.ruta_config, "r", encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"[Error] No se pudo leer config_general.json: {e}")
            return {}

    def guardar_config_en_archivo(self):
        try:
            os.makedirs(os.path.dirname(self.ruta_config), exist_ok=True)
            with open(self.ruta_config, "w", encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            # Notificar a PestanaLectura para que actualice las etiquetas de los botones
            # de salto con el nuevo valor de segundos guardado
            try:
                ventana = self.GetParent().GetParent()  # Notebook → VentanaPrincipal
                if hasattr(ventana, 'pestana_lectura'):
                    pl = ventana.pestana_lectura
                    pl.cargar_config_salto()
                    pl.btn_atras.SetLabel(f"Atrás {pl.segundos_salto}s")
                    pl.btn_adelante.SetLabel(f"Adelante {pl.segundos_salto}s")
            except Exception:
                pass
        except Exception as e:
            wx.MessageBox(str(e))