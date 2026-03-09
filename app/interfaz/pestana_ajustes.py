import wx
import os
import json
import webbrowser
import wx.lib.mixins.listctrl as listmix
from app.motor.cliente_nube_voces import GestorVoces
from app.motor.reproductor_voz import ReproductorVoz
from app.config_rutas import ruta_config, CONFIG_DIR, cargar_claves, guardar_claves

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
from app.motor.control_cuota import ControlCuota


_CHARS_POR_LIBRO = 300_000  # aprox. 300 paginas de 1000 caracteres


def _texto_ayuda_limite(proveedor, gastado, limite_chars):
    """
    Genera el texto de SetHelpText que NVDA verbalizara al tabular al campo de limite.
    Conciso y sin simbolos especiales para que el lector de pantalla lo lea limpio.
    Precios 2026 pay-as-you-go (USD): Azure/Polly Neural 16 dolares por millon.
    """
    try:
        lim = int(limite_chars)
        gas = int(gastado)
    except (ValueError, TypeError):
        return ""
    if lim <= 0:
        return ""
    restante = max(0, lim - gas)
    libros = restante // _CHARS_POR_LIBRO
    if proveedor in ("azure", "polly"):
        coste_gas = round(gas * 16 / 1_000_000, 2)
        coste_lim = round(lim * 16 / 1_000_000, 2)
        return (
            f"Gasto: {gas} caracteres, unos {coste_gas} dolares. "
            f"Restante: {restante} caracteres, aprox {libros} libros. "
            f"Coste total al limite: {coste_lim} dolares al mes."
        )
    elif proveedor == "elevenlabs":
        if lim <= 30_000:    plan = "Plan Starter, 5 dolares al mes"
        elif lim <= 100_000: plan = "Plan Creator, 22 dolares al mes"
        elif lim <= 500_000: plan = "Plan Pro, 99 dolares al mes"
        else:                plan = "Plan Scale, 330 dolares al mes"
        return (
            f"Gasto: {gas} caracteres. "
            f"Restante: {restante} caracteres, aprox {libros} libros. "
            f"Suscripcion sugerida: {plan}."
        )
    return ""


class PanelGeneral(wx.ScrolledWindow):
    def __init__(self, padre, config):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config
        self.cuota = ControlCuota() # Instancia para leer datos

        sizer = wx.BoxSizer(wx.VERTICAL)

        # CONTROL DE PRESUPUESTO
        # La información de costes se integra en el AccessibleDescription (SetHelpText)
        # de cada campo — NVDA la verbalizará al tabular, sin texto suelto que sature.
        sb_cuota = wx.StaticBox(self, label="Control de Presupuesto y Límites")
        sizer_cuota = wx.StaticBoxSizer(sb_cuota, wx.VERTICAL)

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
        hbox_salto.Add(wx.StaticText(self, label="Segundos de salto (botones Atrás y Adelante en Lectura):"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 10)
        self.txt_salto = wx.TextCtrl(self, value=str(self.config.get("segundos_salto", "10")), size=(50, -1))
        self.txt_salto.SetHelpText(
            "Número de segundos que avanza o retrocede el audio al pulsar los botones "
            "Atrás y Adelante en la pestaña Lectura. Introduce un número entero. Valor recomendado: 10."
        )
        hbox_salto.Add(self.txt_salto, 0)
        sizer_nav.Add(hbox_salto, 0, wx.ALL, 5)
        sizer.Add(sizer_nav, 0, wx.EXPAND | wx.ALL, 10)
        
        # GUARDAR — guardado como atributo para que VentanaPrincipal pueda usarlo
        # como punto de anclaje del bucle de tabulación accesible
        self.btn_guardar = wx.Button(self, label="Guardar Configuración General y Límites de presupuesto")
        self.btn_guardar.SetHelpText(
            "Guarda los segundos de salto y los límites de presupuesto de cada proveedor "
            "en el archivo de configuración."
        )
        self.btn_guardar.Bind(wx.EVT_BUTTON, lambda e: self.guardar_todo())
        sizer.Add(self.btn_guardar, 0, wx.ALL, 10)

        self.btn_limpiar = wx.Button(self, label="Limpiar caché")
        self.btn_limpiar.SetHelpText(
            "Elimina carpetas __pycache__, archivos .tmp y audio temporal generado "
            "por la aplicación. Al terminar muestra cuántos archivos se borraron y "
            "cuánto espacio se liberó."
        )
        self.btn_limpiar.Bind(wx.EVT_BUTTON, self._limpiar_cache)
        sizer.Add(self.btn_limpiar, 0, wx.ALL, 10)

        self.SetSizer(sizer)

    def _crear_fila_limite(self, nombre, gastado, limite, clave):
        if not hasattr(self, "txt_limites"): self.txt_limites = {}

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label=f"{nombre} (Gastado: {gastado}):", size=(180, -1))
        txt = wx.TextCtrl(self, value=str(limite))
        txt.SetName(f"limite_{clave}")
        # SetHelpText: NVDA lo verbalizará al recibir foco — gasto, restante y libros equiv.
        txt.SetHelpText(_texto_ayuda_limite(clave, gastado, limite))
        self.txt_limites[clave] = txt

        def _on_texto(event, _clave=clave, _gas=gastado, _txt=txt):
            _txt.SetHelpText(_texto_ayuda_limite(_clave, _gas, event.GetString()))
            event.Skip()

        txt.Bind(wx.EVT_TEXT, _on_texto)
        hbox.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        hbox.Add(txt, 1, wx.EXPAND)
        return hbox

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

    def _limpiar_cache(self, event=None):
        from app.config_rutas import RAIZ
        import shutil

        total_archivos = 0
        total_bytes = 0
        errores = 0

        # 1. Carpetas __pycache__ en el árbol del proyecto
        for dirpath, dirnames, _ in os.walk(RAIZ):
            # No entrar en carpetas ocultas ni en el entorno virtual
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith('.') and d not in ('venv', '.venv', 'env', 'node_modules')
            ]
            if os.path.basename(dirpath) == '__pycache__':
                try:
                    size = sum(
                        os.path.getsize(os.path.join(dirpath, f))
                        for f in os.listdir(dirpath)
                        if os.path.isfile(os.path.join(dirpath, f))
                    )
                    n = len(os.listdir(dirpath))
                    shutil.rmtree(dirpath, ignore_errors=True)
                    total_archivos += n
                    total_bytes += size
                except Exception:
                    errores += 1

        # 2. Archivos .tmp en todo el proyecto
        for dirpath, dirnames, filenames in os.walk(RAIZ):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith('.') and d not in ('venv', '.venv', 'env', 'node_modules')
            ]
            for fname in filenames:
                if fname.endswith('.tmp'):
                    fpath = os.path.join(dirpath, fname)
                    try:
                        total_bytes += os.path.getsize(fpath)
                        os.remove(fpath)
                        total_archivos += 1
                    except Exception:
                        errores += 1

        # 3. Archivos de audio temporal en la carpeta 'cache' del proyecto
        carpeta_cache = os.path.join(RAIZ, 'cache')
        if os.path.isdir(carpeta_cache):
            for fname in os.listdir(carpeta_cache):
                if fname.endswith(('.mp3', '.wav', '.ogg', '.pcm')):
                    fpath = os.path.join(carpeta_cache, fname)
                    try:
                        total_bytes += os.path.getsize(fpath)
                        os.remove(fpath)
                        total_archivos += 1
                    except Exception:
                        errores += 1

        # Formatear tamaño legible
        if total_bytes >= 1_048_576:
            tam_str = f"{total_bytes / 1_048_576:.1f} MB"
        elif total_bytes >= 1024:
            tam_str = f"{total_bytes / 1024:.1f} KB"
        else:
            tam_str = f"{total_bytes} bytes"

        if total_archivos == 0:
            msg = "No se encontró ningún archivo temporal que limpiar."
        else:
            msg = f"Limpieza completada.\n{total_archivos} archivo(s) eliminado(s) — {tam_str} liberado(s)."
        if errores:
            msg += f"\n({errores} archivo(s) no pudieron borrarse por estar en uso.)"

        wx.MessageBox(msg, "Limpiar caché", wx.OK | wx.ICON_INFORMATION)


class PanelClaves(wx.ScrolledWindow):
    def __init__(self, padre, config):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config   # ajustes generales (NO contiene claves API)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Configura tus claves API."), 0, wx.ALL, 10)

        # --- AZURE ---
        sb_az = wx.StaticBox(self, label="Microsoft Azure TTS")
        sz_az = wx.StaticBoxSizer(sb_az, wx.VERTICAL)
        
        sz_az.Add(wx.StaticText(self, label="Clave de suscripción (Key). Formato: 32 caracteres hexadecimales:"), 0, wx.ALL, 2)
        self.txt_az_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_az_key.SetHelpText(
            "Clave de suscripción de Azure Text to Speech. "
            "Puedes encontrarla en el Portal de Azure, en tu recurso de Servicios Cognitivos, "
            "sección Claves y Punto de conexión."
        )
        sz_az.Add(self.txt_az_key, 0, wx.EXPAND|wx.ALL, 5)

        sz_az.Add(wx.StaticText(self, label="Región del recurso (ej: eastus, westeurope):"), 0, wx.ALL, 2)
        self.txt_az_region = wx.TextCtrl(self)
        self.txt_az_region.SetHelpText(
            "Región de Azure donde está creado tu recurso. "
            "Ejemplos: eastus, westus2, westeurope. "
            "La encontrarás junto a la clave en el Portal de Azure."
        )
        sz_az.Add(self.txt_az_region, 0, wx.EXPAND|wx.ALL, 5)
        
        hb_az = wx.BoxSizer(wx.HORIZONTAL)
        btn_az_web = wx.Button(self, label="Conseguir clave Azure")
        btn_az_web.SetHelpText("Abre el navegador en la página de Azure Text to Speech para crear o consultar tu clave.")
        btn_az_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://azure.microsoft.com/es-es/services/cognitive-services/text-to-speech/"))
        btn_az_check = wx.Button(self, label="Comprobar clave y descargar voces Azure")
        btn_az_check.SetHelpText("Guarda la clave, la verifica contra el servidor de Azure y descarga la lista de voces disponibles.")
        btn_az_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "azure"))
        btn_az_del = wx.Button(self, label="Borrar clave Azure")
        btn_az_del.SetHelpText("Borra los datos de acceso de Azure guardados en la aplicación.")
        btn_az_del.Bind(wx.EVT_BUTTON, self.al_borrar_azure)
        
        hb_az.Add(btn_az_web, 0, wx.RIGHT, 5)
        hb_az.Add(btn_az_check, 0, wx.RIGHT, 5)
        hb_az.Add(btn_az_del, 0)
        sz_az.Add(hb_az, 0, wx.ALL, 5)
        sizer.Add(sz_az, 0, wx.EXPAND|wx.ALL, 10)

        # --- AMAZON POLLY (Restaurado) ---
        sb_po = wx.StaticBox(self, label="Amazon Polly")
        sz_po = wx.StaticBoxSizer(sb_po, wx.VERTICAL)
        
        sz_po.Add(wx.StaticText(self, label="Access Key ID (identificador de la clave AWS):"), 0, wx.ALL, 2)
        self.txt_po_key = wx.TextCtrl(self)
        self.txt_po_key.SetHelpText(
            "Identificador de clave de acceso de AWS. "
            "Lo encontrarás en la consola de AWS, sección IAM, Mis credenciales de seguridad."
        )
        sz_po.Add(self.txt_po_key, 0, wx.EXPAND|wx.ALL, 5)

        sz_po.Add(wx.StaticText(self, label="Secret Access Key (clave secreta, se muestra solo al crearla):"), 0, wx.ALL, 2)
        self.txt_po_secret = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_po_secret.SetHelpText(
            "Clave de acceso secreta de AWS. Solo se muestra una vez al crearla. "
            "Si la perdiste, debes generar una nueva en la consola de AWS."
        )
        sz_po.Add(self.txt_po_secret, 0, wx.EXPAND|wx.ALL, 5)

        sz_po.Add(wx.StaticText(self, label="Región AWS (ej: us-east-1, eu-west-1):"), 0, wx.ALL, 2)
        self.txt_po_region = wx.TextCtrl(self)
        self.txt_po_region.SetHelpText(
            "Región de AWS donde usarás Amazon Polly. "
            "Ejemplos: us-east-1, us-west-2, eu-west-1."
        )
        sz_po.Add(self.txt_po_region, 0, wx.EXPAND|wx.ALL, 5)
        
        hb_po = wx.BoxSizer(wx.HORIZONTAL)
        btn_po_web = wx.Button(self, label="Conseguir clave Amazon Polly")
        btn_po_web.SetHelpText("Abre el navegador en la página de Amazon Polly para crear o gestionar tus credenciales AWS.")
        btn_po_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://aws.amazon.com/polly/"))
        btn_po_check = wx.Button(self, label="Comprobar clave y descargar voces Polly")
        btn_po_check.SetHelpText("Guarda las credenciales, las verifica contra AWS y descarga la lista de voces de Amazon Polly.")
        btn_po_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "polly"))
        
        hb_po.Add(btn_po_web, 0, wx.RIGHT, 5)
        hb_po.Add(btn_po_check, 0)
        sz_po.Add(hb_po, 0, wx.ALL, 5)
        sizer.Add(sz_po, 0, wx.EXPAND|wx.ALL, 10)

        # --- ELEVENLABS ---
        sb_el = wx.StaticBox(self, label="ElevenLabs")
        sz_el = wx.StaticBoxSizer(sb_el, wx.VERTICAL)
        
        sz_el.Add(wx.StaticText(self, label="API Key (clave de acceso de ElevenLabs):"), 0, wx.ALL, 2)
        self.txt_el_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_el_key.SetHelpText(
            "Clave API de ElevenLabs. La encontrarás en tu perfil de ElevenLabs, "
            "sección Profile Settings, apartado API Key."
        )
        sz_el.Add(self.txt_el_key, 0, wx.EXPAND|wx.ALL, 5)
        
        hb_el = wx.BoxSizer(wx.HORIZONTAL)
        btn_el_web = wx.Button(self, label="Conseguir clave ElevenLabs")
        btn_el_web.SetHelpText("Abre el navegador en la página de ElevenLabs para crear una cuenta o consultar tu clave API.")
        btn_el_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://elevenlabs.io/"))
        btn_el_check = wx.Button(self, label="Comprobar clave y descargar voces ElevenLabs")
        btn_el_check.SetHelpText("Guarda la clave API, la verifica contra ElevenLabs y descarga la lista de voces disponibles.")
        btn_el_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "elevenlabs"))
        
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
        """Carga las claves desde configuraciones/claves_api.json (separado de ajustes)."""
        claves = cargar_claves()
        d_az = claves.get("azure", {})
        self.txt_az_key.SetValue(d_az.get("key", ""))
        self.txt_az_region.SetValue(d_az.get("region", ""))

        d_po = claves.get("polly", {})
        self.txt_po_key.SetValue(d_po.get("access_key", ""))
        self.txt_po_secret.SetValue(d_po.get("secret_key", ""))
        self.txt_po_region.SetValue(d_po.get("region", ""))

        d_el = claves.get("elevenlabs", {})
        self.txt_el_key.SetValue(d_el.get("api_key", ""))

    def al_guardar(self, event):
        """Guarda las claves en configuraciones/claves_api.json (nunca en ajustes.json)."""
        claves = {
            "azure": {
                "key": self.txt_az_key.GetValue().strip(),
                "region": self.txt_az_region.GetValue().strip(),
            },
            "polly": {
                "access_key": self.txt_po_key.GetValue().strip(),
                "secret_key": self.txt_po_secret.GetValue().strip(),
                "region": self.txt_po_region.GetValue().strip(),
            },
            "elevenlabs": {
                "api_key": self.txt_el_key.GetValue().strip(),
            },
        }
        guardar_claves(claves)
        if event:
            wx.MessageBox("Claves guardadas en claves_api.json.", "Éxito")

    def al_borrar_azure(self, event):
        self.txt_az_key.Clear()
        self.txt_az_region.Clear()
        self.al_guardar(None)

    def al_comprobar(self, event, proveedor=None):
        self.al_guardar(None)
        # Guardar snapshot de IDs actuales ANTES de descargar nuevas voces
        # Así el filtro "Solo nuevas voces" detectará solo las recién llegadas
        try:
            ruta_voces = ruta_config("voces_disponibles.json")
            ruta_conocidas = ruta_config("voces_conocidas.json")
            if os.path.exists(ruta_voces):
                with open(ruta_voces, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                ids_actuales = [v.get("id","") for lista in datos.values() for v in lista if v.get("id")]
                os.makedirs(os.path.dirname(ruta_conocidas), exist_ok=True)
                with open(ruta_conocidas, 'w', encoding='utf-8') as f:
                    json.dump(ids_actuales, f)
        except Exception:
            pass
        wx.BeginBusyCursor()
        try:
            gestor = GestorVoces()
            if proveedor:
                res = gestor.actualizar_proveedor(proveedor)
            else:
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
        self.ruta_favs = ruta_config("voces_favoritas.json")
        self.favoritos = self.cargar_favoritos()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. CONFIGURACIÓN LIBRO
        sb_libro = wx.StaticBox(self, label="Configuración del Libro")
        sz_libro = wx.StaticBoxSizer(sb_libro, wx.VERTICAL)
        sz_libro.Add(wx.StaticText(self, label="Idioma del libro, usado para seleccionar el acento de la voz por defecto:"), 0, wx.BOTTOM, 5)
        self.combo_idioma_libro = wx.ComboBox(self, choices=["Detectar auto", "Español (ES)", "Español (LAT)", "Inglés"], style=wx.CB_READONLY)
        self.combo_idioma_libro.SetHelpText(
            "Define el idioma principal del libro para preseleccionar el acento correcto "
            "en el combo de voz de la pestaña Lectura. "
            "Elige Español (ES) para España, Español (LAT) para Latinoamérica, o Inglés."
        )
        
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
        
        # Fila A: Proveedor primero, luego Idioma (el idioma se filtra según el proveedor)
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        hbox1.Add(wx.StaticText(self, label="Proveedor:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.combo_proveedor = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos"])
        self.combo_proveedor.SetSelection(0)
        self.combo_proveedor.SetHelpText("Filtra la lista de voces por proveedor: Azure, Amazon Polly, ElevenLabs, o Todos. Al cambiar el proveedor, el filtro de idioma se actualiza automáticamente.")
        self.combo_proveedor.Bind(wx.EVT_COMBOBOX, self.al_cambiar_proveedor)
        hbox1.Add(self.combo_proveedor, 0, wx.RIGHT, 15)

        hbox1.Add(wx.StaticText(self, label="Idioma:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.combo_idioma = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos"])
        self.combo_idioma.SetSelection(0)
        self.combo_idioma.SetHelpText("Filtra la lista de voces por idioma. Muestra solo los idiomas del proveedor seleccionado.")
        self.combo_idioma.Bind(wx.EVT_COMBOBOX, self.al_filtrar)
        hbox1.Add(self.combo_idioma, 1)
        sz_filtros.Add(hbox1, 0, wx.EXPAND|wx.ALL, 5)
        
        # Fila B: Tipo y Gestión
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        hbox2.Add(wx.StaticText(self, label="Tipo:"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.combo_tipo = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos", "Femenino", "Masculino", "Multilingüe", "Dragon"])
        self.combo_tipo.SetSelection(0)
        self.combo_tipo.SetHelpText("Filtra por tipo de voz: Femenino, Masculino, voces Multilingüe, voces Dragon HD, o Todos.")
        self.combo_tipo.Bind(wx.EVT_COMBOBOX, self.al_filtrar)
        hbox2.Add(self.combo_tipo, 0, wx.RIGHT, 15)

        # Casillas de gestión y filtros especiales
        self.chk_solo_favs = wx.CheckBox(self, label="Solo favoritas")
        self.chk_solo_favs.SetHelpText(
            "Marcada: muestra solo las voces que ya tienes marcadas como favoritas. "
            "Desmarcada: muestra todas las voces según los demás filtros activos."
        )
        self.chk_solo_favs.Bind(wx.EVT_CHECKBOX, self.al_filtrar)
        hbox2.Add(self.chk_solo_favs, 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 15)

        self.chk_solo_nuevas = wx.CheckBox(self, label="Solo nuevas voces")
        self.chk_solo_nuevas.SetHelpText(
            "Marcada: muestra solo las voces marcadas como nuevas desde la última actualización. "
            "Desmarcada: muestra todas las voces según los demás filtros activos."
        )
        self.chk_solo_nuevas.Bind(wx.EVT_CHECKBOX, self.al_filtrar)
        hbox2.Add(self.chk_solo_nuevas, 0, wx.ALIGN_CENTER_VERTICAL)
        sz_filtros.Add(hbox2, 0, wx.EXPAND|wx.ALL, 5)

        # Fila C: Buscador
        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        hbox3.Add(wx.StaticText(self, label="Buscar nombre de voz (filtro en tiempo real):"), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 5)
        self.txt_buscar = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_buscar.SetHelpText(
            "Escribe parte del nombre de una voz para filtrar la lista en tiempo real. "
            "Borra el campo para volver a ver todas las voces del filtro activo."
        )
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
        self.lista_voces.SetHelpText(
            "Lista de voces disponibles. Usa las flechas Arriba y Abajo para navegar. "
            "Pulsa Espacio para marcar o desmarcar una voz como favorita. "
            "Las voces marcadas aparecerán en la pestaña Grabación para asignarlas a personajes."
        )
        
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_CHECKED, self.al_marcar_favorito)
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.al_desmarcar_favorito)
        
        sizer.Add(self.lista_voces, 1, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        
        # 4. BOTONERA — atributo de instancia para el bucle de tabulación accesible
        self.btn_escuchar = wx.Button(self, label="Escuchar muestra de la voz seleccionada (Alt+P)")
        self.btn_escuchar.SetHelpText(
            "Reproduce una muestra de texto con la voz seleccionada en la lista "
            "para que puedas evaluar su sonido antes de usarla."
        )
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
                self._notificar_grabacion()

    def al_desmarcar_favorito(self, event):
        idx = event.GetIndex()
        voz = self.mapa_indices.get(idx)
        if voz:
            id_voz = voz.get("id")
            if id_voz in self.favoritos:
                self.favoritos.remove(id_voz)
                self.guardar_favoritos()
                self._notificar_grabacion()

    def _notificar_grabacion(self):
        """Recarga la lista de voces en PestanaGrabacion al instante."""
        try:
            # PanelVoces → Simplebook → SplitterWindow → PestanaAjustes → Notebook → VentanaPrincipal
            ventana = self.GetParent().GetParent().GetParent().GetParent().GetParent()
            if hasattr(ventana, 'pestana_grabacion'):
                ventana.pestana_grabacion._cargar_voces_disponibles()
        except Exception:
            pass

    def cargar_datos_y_llenar(self):
        ruta = ruta_config("voces_disponibles.json")
        ruta_conocidas = ruta_config("voces_conocidas.json")
        self.voces_todas = []

        # Cargar IDs de voces conocidas (para detectar novedades)
        voces_conocidas = set()
        try:
            if os.path.exists(ruta_conocidas):
                with open(ruta_conocidas, 'r', encoding='utf-8') as f:
                    voces_conocidas = set(json.load(f))
        except Exception:
            pass

        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    for prov, lista in datos.items():
                        for v in lista:
                            v["proveedor_id"] = prov
                            # Es nueva si hay conocidas previas y esta no estaba
                            v["es_nueva"] = bool(voces_conocidas) and v.get("id","") not in voces_conocidas
                            self.voces_todas.append(v)
            except Exception as e:
                print(f"[Error] No se pudo leer voces_disponibles.json: {e}")
                self.voces_todas = []

        # Proveedor con opciones fijas; idioma se rellena según proveedor seleccionado
        self.combo_proveedor.Clear()
        self.combo_proveedor.AppendItems(["Todos", "Azure", "Amazon Polly", "ElevenLabs"])
        self.combo_proveedor.SetSelection(0)

        # Con proveedor=Todos, poblar idioma con todos los disponibles
        idiomas = sorted(set(v.get("idioma","") for v in self.voces_todas if v.get("idioma")))
        self.combo_idioma.Clear()
        self.combo_idioma.Append("Todos")
        self.combo_idioma.AppendItems(idiomas)
        self.combo_idioma.SetSelection(0)

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

    def al_cambiar_proveedor(self, event):
        """Actualiza el combo de idioma para mostrar solo los del proveedor seleccionado."""
        f_prov = self.combo_proveedor.GetValue()
        if f_prov == "Todos":
            voces_prov = self.voces_todas
        elif f_prov == "Amazon Polly":
            voces_prov = [v for v in self.voces_todas if "polly" in v.get("proveedor_id","").lower()]
        elif f_prov == "Azure":
            voces_prov = [v for v in self.voces_todas if "azure" in v.get("proveedor_id","").lower()]
        elif f_prov == "ElevenLabs":
            voces_prov = [v for v in self.voces_todas if "eleven" in v.get("proveedor_id","").lower()]
        else:
            voces_prov = self.voces_todas

        idiomas = sorted(set(v.get("idioma","") for v in voces_prov if v.get("idioma")))
        idioma_actual = self.combo_idioma.GetValue()
        self.combo_idioma.Clear()
        self.combo_idioma.Append("Todos")
        self.combo_idioma.AppendItems(idiomas)
        if idioma_actual in idiomas:
            self.combo_idioma.SetValue(idioma_actual)
        else:
            self.combo_idioma.SetSelection(0)
        self.filtrar_y_mostrar()

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
class _DialogoCapturaTecla(wx.Dialog):
    """
    Diálogo modal que espera una pulsación de tecla y la almacena.
    Compatible con NVDA: anuncia el título y la instrucción al abrirse.
    Escape cancela; cualquier otra tecla (con o sin modificador) confirma.
    """
    _ESPECIALES = {
        wx.WXK_SPACE: "Espacio", wx.WXK_RETURN: "Intro",
        wx.WXK_F1: "F1",  wx.WXK_F2: "F2",  wx.WXK_F3: "F3",
        wx.WXK_F4: "F4",  wx.WXK_F5: "F5",  wx.WXK_F6: "F6",
        wx.WXK_F7: "F7",  wx.WXK_F8: "F8",  wx.WXK_F9: "F9",
        wx.WXK_F10: "F10", wx.WXK_F11: "F11", wx.WXK_F12: "F12",
        wx.WXK_UP: "Arriba", wx.WXK_DOWN: "Abajo",
        wx.WXK_LEFT: "Izquierda", wx.WXK_RIGHT: "Derecha",
        wx.WXK_HOME: "Inicio", wx.WXK_END: "Fin",
        wx.WXK_PAGEUP: "RePág", wx.WXK_PAGEDOWN: "AvPág",
        wx.WXK_TAB: "Tab", wx.WXK_BACK: "Retroceso",
        wx.WXK_DELETE: "Supr", wx.WXK_INSERT: "Insert",
    }

    def __init__(self, parent, descripcion_atajo):
        super().__init__(parent, title="Asignar tecla",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        self.resultado = None  # (modificador, tecla) o None tras Escape

        sizer = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(self, label=(
            f"Atajo: {descripcion_atajo}\n\n"
            "Presiona la combinación de teclas que quieres asignar.\n"
            "Escape para cancelar sin cambios."
        ))
        sizer.Add(lbl, 0, wx.ALL, 20)

        self.lbl_capturada = wx.StaticText(self, label="Esperando tecla...")
        sizer.Add(self.lbl_capturada, 0, wx.ALIGN_CENTER | wx.BOTTOM, 20)

        self.SetSizer(sizer)
        self.Fit()
        self.CenterOnParent()

        self.Bind(wx.EVT_CHAR_HOOK, self._al_capturar)

    def _al_capturar(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.resultado = None
            self.EndModal(wx.ID_CANCEL)
            return

        # Ignorar pulsaciones de solo modificador
        if key in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT, wx.WXK_WINDOWS_LEFT,
                   wx.WXK_WINDOWS_RIGHT, wx.WXK_WINDOWS_MENU):
            return

        mods = []
        if event.ControlDown(): mods.append("Ctrl")
        if event.AltDown():     mods.append("Alt")
        if event.ShiftDown():   mods.append("Shift")

        if key in self._ESPECIALES:
            nombre_tecla = self._ESPECIALES[key]
        elif 32 <= key <= 127:
            nombre_tecla = chr(key).upper()
        else:
            return  # Tecla no reconocida: ignorar

        self.resultado = ("+".join(mods), nombre_tecla)
        combo = f"{'+'.join(mods)}+{nombre_tecla}" if mods else nombre_tecla
        self.lbl_capturada.SetLabel(f"Asignando: {combo}")
        self.EndModal(wx.ID_OK)


class PanelAtajos(wx.Panel):
    def __init__(self, padre):
        super().__init__(padre)
        from app.motor.gestor_atajos import cargar_atajos, cargar_defaults

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=(
            "Lista de atajos de teclado. Selecciona uno y pulsa Intro o el botón Asignar para cambiarlo. "
            "La tecla predeterminada aparece entre paréntesis junto al nombre."
        )), 0, wx.ALL, 10)

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.lista.InsertColumn(0, "Acción (tecla predeterminada entre paréntesis)", width=340)
        self.lista.InsertColumn(1, "Tecla asignada actualmente", width=200)
        self.lista.SetHelpText(
            "Lista de acciones con sus atajos de teclado. "
            "Usa las flechas Arriba y Abajo para navegar. "
            "Pulsa Intro para abrir el diálogo de asignación de la acción seleccionada. "
            "Las teclas personalizadas se marcan con la etiqueta personalizada."
        )
        self.lista.Bind(wx.EVT_KEY_DOWN, self._al_tecla_lista)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_asignar = wx.Button(self, label="Asignar nueva tecla al atajo seleccionado")
        self.btn_asignar.SetHelpText(
            "Abre un diálogo donde puedes pulsar la combinación de teclas que quieres "
            "asignar a la acción seleccionada en la lista."
        )
        self.btn_eliminar = wx.Button(self, label="Eliminar asignación personalizada")
        self.btn_eliminar.SetHelpText(
            "Elimina la asignación personalizada de la acción seleccionada y vuelve a la tecla predeterminada."
        )
        self.btn_restablecer = wx.Button(self, label="Restablecer todos los atajos a valores predeterminados")
        self.btn_restablecer.SetHelpText(
            "Borra todas las personalizaciones y devuelve todos los atajos de teclado "
            "a sus valores predeterminados de fábrica. Se pedirá confirmación."
        )
        self.btn_asignar.Bind(wx.EVT_BUTTON, self._al_asignar)
        self.btn_eliminar.Bind(wx.EVT_BUTTON, self._al_eliminar)
        self.btn_restablecer.Bind(wx.EVT_BUTTON, self._al_restablecer)
        hbox.Add(self.btn_asignar, 0, wx.RIGHT, 10)
        hbox.Add(self.btn_eliminar, 0, wx.RIGHT, 10)
        hbox.Add(self.btn_restablecer, 0)
        sizer.Add(hbox, 0, wx.ALL, 10)

        # Sección de atajos fijos del menú (no configurables desde esta lista)
        sb_fijos = wx.StaticBox(self, label="Atajos fijos del menú (no configurables)")
        sz_fijos = wx.StaticBoxSizer(sb_fijos, wx.VERTICAL)
        _FIJOS = [
            ("Ctrl+A",           "Abrir libro EPUB (menú Archivo)"),
            ("Ctrl+T",           "Abrir TXT para grabar (menú Archivo, activo en pestaña Grabación)"),
            ("Ctrl+Shift+P",     "Abrir gestor de proyectos (menú Proyectos)"),
            ("Ctrl+B",           "Buscar en el texto (menú Ir a...)"),
            ("Ctrl+G",           "Ir a porcentaje del libro (menú Ir a...)"),
            ("Ctrl+M",           "Gestor de marcadores (menú Ir a...)"),
            ("Alt+F4",           "Salir de la aplicación"),
        ]
        for atajo, desc in _FIJOS:
            lbl = wx.StaticText(self, label=f"  {atajo:<20}  {desc}")
            sz_fijos.Add(lbl, 0, wx.LEFT | wx.TOP, 4)
        sizer.Add(sz_fijos, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)
        self._rellenar_lista()

    def _rellenar_lista(self):
        from app.motor.gestor_atajos import cargar_atajos, cargar_defaults, texto_atajo
        self._atajos = cargar_atajos()
        self._defaults = cargar_defaults()
        self._claves = list(self._atajos.keys())

        self.lista.DeleteAllItems()
        for i, clave in enumerate(self._claves):
            entrada = self._atajos[clave]
            entrada_def = self._defaults.get(clave, {})
            desc = entrada.get("descripcion", clave)
            tecla_def = texto_atajo(entrada_def)
            tecla_actual = texto_atajo(entrada)

            # Columna 1: descripción con el default entre paréntesis
            col_accion = f"{desc} ({tecla_def})"
            # Columna 2: tecla actual, marcada si es personalizada
            if tecla_actual == tecla_def:
                col_tecla = tecla_actual
            else:
                col_tecla = f"{tecla_actual}  [personalizada]"

            self.lista.InsertItem(i, col_accion)
            self.lista.SetItem(i, 1, col_tecla)

        if self.lista.GetItemCount() > 0:
            self.lista.Select(0)

    def _al_tecla_lista(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._al_asignar(None)
        else:
            event.Skip()

    def _refrescar_aceleradores_frame(self):
        """Pide al Frame principal que reconstruya el AcceleratorTable con los atajos actuales."""
        ventana = wx.GetTopLevelParent(self)
        if hasattr(ventana, '_configurar_aceleradores_globales'):
            ventana._configurar_aceleradores_globales()

    def _al_asignar(self, event):
        from app.motor.gestor_atajos import guardar_atajo_usuario
        idx = self.lista.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Selecciona un atajo de la lista primero.", "Info")
            return

        clave = self._claves[idx]
        desc = self._atajos[clave].get("descripcion", clave)
        dlg = _DialogoCapturaTecla(self, desc)
        if dlg.ShowModal() == wx.ID_OK and dlg.resultado:
            mod, tecla = dlg.resultado
            guardar_atajo_usuario(clave, mod, tecla)
            self._rellenar_lista()
            self._refrescar_aceleradores_frame()
            if idx < self.lista.GetItemCount():
                self.lista.Select(idx)
                self.lista.EnsureVisible(idx)
        dlg.Destroy()

    def _al_eliminar(self, event):
        from app.motor.gestor_atajos import eliminar_atajo_usuario
        idx = self.lista.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Selecciona un atajo de la lista primero.", "Info")
            return
        clave = self._claves[idx]
        eliminar_atajo_usuario(clave)
        self._rellenar_lista()
        self._refrescar_aceleradores_frame()
        if idx < self.lista.GetItemCount():
            self.lista.Select(idx)

    def _al_restablecer(self, event):
        from app.motor.gestor_atajos import restablecer_todos
        if wx.MessageBox(
            "¿Restablecer todos los atajos a los valores predeterminados?",
            "Confirmar", wx.YES_NO | wx.ICON_QUESTION
        ) == wx.YES:
            restablecer_todos()
            self._rellenar_lista()
            self._refrescar_aceleradores_frame()
            wx.MessageBox("Todos los atajos han vuelto a sus valores predeterminados.", "Listo")

class PanelAcercaDe(wx.ScrolledWindow):
    def __init__(self, padre):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        sizer = wx.BoxSizer(wx.VERTICAL)

        lineas = [
            ("Epub TTS Accesible", True),
            ("Versión: Fase 3 (2026)", False),
            ("", False),
            ("Aplicación de texto a voz accesible para libros EPUB y archivos TXT.", False),
            ("Diseñada para usuarios de lectores de pantalla como NVDA.", False),
            ("", False),
            ("Créditos", True),
            ("Desarrollo: Dayanna Parson", False),
            ("Asistencia IA: Claude (Anthropic)", False),
            ("", False),
            ("Proveedores de voz:", True),
            ("  Microsoft Azure Text to Speech", False),
            ("  Amazon Polly (AWS)", False),
            ("  ElevenLabs", False),
            ("  Microsoft SAPI5 (voces del sistema, sin coste)", False),
        ]
        for texto, negrita in lineas:
            if not texto:
                sizer.Add((0, 6))
                continue
            lbl = wx.StaticText(self, label=texto)
            if negrita:
                f = lbl.GetFont()
                f.SetWeight(wx.FONTWEIGHT_BOLD)
                lbl.SetFont(f)
            sizer.Add(lbl, 0, wx.LEFT | wx.TOP, 10 if negrita else 4)

        self.btn_github = wx.Button(self, label="Abrir repositorio en GitHub")
        self.btn_github.SetHelpText("Abre el repositorio del proyecto en el navegador.")
        self.btn_github.Bind(
            wx.EVT_BUTTON,
            lambda e: webbrowser.open("https://github.com/Dayanna-Parson/epub-tts-accesible")
        )
        sizer.Add(self.btn_github, 0, wx.ALL, 12)
        self.SetSizer(sizer)


class PestanaAjustes(wx.Panel):
    def __init__(self, padre):
        super().__init__(padre)
        self.ruta_config = ruta_config("ajustes.json")
        self.config = self.cargar_config()

        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)

        self.lista_cat = wx.ListBox(self.splitter, style=wx.LB_SINGLE)
        self.lista_cat.Append("General")
        self.lista_cat.Append("Claves y Proveedores")
        self.lista_cat.Append("Voces e Idiomas")
        self.lista_cat.Append("Atajos de teclado")
        self.lista_cat.Append("Acerca de")
        self.lista_cat.SetSelection(0)
        self.lista_cat.SetHelpText(
            "Categorías de ajustes. Usa las flechas Arriba y Abajo para navegar. "
            "Pulsa Intro o Espacio para abrir la categoría seleccionada en el panel de la derecha."
        )
        self.lista_cat.Bind(wx.EVT_LISTBOX, self.al_cambiar_cat)

        self.panel_derecho = wx.Simplebook(self.splitter)
        self.pag_general = PanelGeneral(self.panel_derecho, self.config)
        self.pag_claves = PanelClaves(self.panel_derecho, self.config)
        self.pag_voces = PanelVoces(self.panel_derecho, self.config)
        self.pag_atajos = PanelAtajos(self.panel_derecho)
        self.pag_acerca = PanelAcercaDe(self.panel_derecho)

        self.panel_derecho.AddPage(self.pag_general, "General")
        self.panel_derecho.AddPage(self.pag_claves, "Claves")
        self.panel_derecho.AddPage(self.pag_voces, "Voces")
        self.panel_derecho.AddPage(self.pag_atajos, "Atajos")
        self.panel_derecho.AddPage(self.pag_acerca, "Acerca de")

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
            return self.pag_general.btn_limpiar
        elif idx == 1:
            return self.pag_claves.btn_save
        elif idx == 2:
            return self.pag_voces.btn_escuchar
        elif idx == 3:
            return self.pag_atajos.btn_restablecer
        else:
            return self.pag_acerca.btn_github

    def al_cambiar_cat(self, event):
        idx = self.lista_cat.GetSelection()
        if idx != wx.NOT_FOUND:
            self.panel_derecho.ChangeSelection(idx)
            # wx.CallAfter garantiza que el foco vuelve a la lista DESPUÉS de que
            # ChangeSelection termine, evitando que NVDA anuncie dos veces el mismo ítem.
            # Sin este SetFocus, al cambiar de página el panel derecho roba el foco
            # y NVDA deja de leer las flechas de navegación en la lista de categorías.
            wx.CallAfter(self.lista_cat.SetFocus)
            # Sin event.Skip(): evita que EVT_LISTBOX suba al splitter y mueva el foco.
            if idx == 2:
                self.pag_voces.cargar_datos_y_llenar()

    def cargar_config(self):
        try:
            with open(self.ruta_config, "r", encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"[Error] No se pudo leer ajustes.json: {e}")
            return {}

    def guardar_config_en_archivo(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
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