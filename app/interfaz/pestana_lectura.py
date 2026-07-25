# ANCLAJE_INICIO: DEPENDENCIAS_LECTURA
import wx
import os
import json
import time
import logging
import threading
from app.motor import anunciador_lector as voz
from app.motor.gestor_epub import extraer_datos_epub
from app.motor.gestor_pdf import extraer_datos_pdf
from app.motor.reproductor_voz import ReproductorVoz
from app.interfaz.dialogos import DialogoMarcadores
from app.config_rutas import ruta_config, CONFIG_DIR
from app.motor.reproductor_sonidos import reproducir, LIST_NAV, ERROR, PAGE_SCROLLED
from app.interfaz.ui_recursos import aplicar_icono_boton

logger = logging.getLogger(__name__)
# ANCLAJE_FIN: DEPENDENCIAS_LECTURA

# ── Tablas de traducción para etiquetas del combo de voz ─────────────────────
_LOCALES_ES = {
    "es-ES": "Español (España)", "es-MX": "Español (México)",
    "es-AR": "Español (Argentina)", "es-CO": "Español (Colombia)",
    "en-US": "Inglés (EE.UU.)", "en-GB": "Inglés (R.U.)",
    "en-AU": "Inglés (Australia)", "en-CA": "Inglés (Canadá)",
    "fr-FR": "Francés (Francia)", "fr-CA": "Francés (Canadá)",
    "de-DE": "Alemán", "it-IT": "Italiano",
    "pt-BR": "Portugués (Brasil)", "pt-PT": "Portugués (Portugal)",
    "ja-JP": "Japonés", "zh-CN": "Chino (Mandarín)",
    "ko-KR": "Coreano", "ru-RU": "Ruso",
    "nl-NL": "Neerlandés", "pl-PL": "Polaco",
    "Multilingüe (v2)": "Multilingüe",
}
_GENEROS_ES = {"Female": "Femenino", "Male": "Masculino", "Neutral": "Neutro"}
_PROVEEDORES = {"polly": "Amazon Polly", "elevenlabs": "ElevenLabs", "azure": "Azure", "deepgram": "Deepgram"}


def _nombre_combo_neuronal(voz, prov_id):
    """
    Construye la etiqueta del combo de voz en formato coherente con Ajustes:
    Nombre; Género; Idioma; Proveedor
    Las etiquetas especiales ([Nueva], [HD]…) se añaden al nombre.
    """
    nombre = voz.get("nombre", "")
    id_voz = voz.get("id", "").lower()
    etiquetas = []
    if "dragonhd" in id_voz or "dragon" in id_voz:
        etiquetas.append("[Dragon]")
    if "multilingual" in id_voz:
        etiquetas.append("[Multilingüe]")
    if "hd" in id_voz and "dragonhd" not in id_voz:
        etiquetas.append("[HD]")
    nombre_completo = f"{nombre} {' '.join(etiquetas)}" if etiquetas else nombre

    genero = _GENEROS_ES.get(voz.get("genero", ""), voz.get("genero", ""))
    idioma_raw = voz.get("idioma", "")
    idioma = _LOCALES_ES.get(idioma_raw, idioma_raw)
    proveedor = _PROVEEDORES.get(prov_id.lower(), prov_id.capitalize())

    return f"{nombre_completo}; {genero}; {idioma}; {proveedor}"
# ─────────────────────────────────────────────────────────────────────────────

# ANCLAJE_INICIO: DEFINICION_PESTANA_LECTURA
class PestanaLectura(wx.Panel):
    """
    Panel principal de la interfaz para la lectura de libros EPUB.
    Gestiona la navegación, el control de audio y la sincronización 
    entre el texto y la síntesis de voz.
    """
    
    # ANCLAJE_INICIO: CONSTRUCCION_INTERFAZ
    def __init__(self, padre):
        super().__init__(padre, style=wx.TAB_TRAVERSAL)
        self.padre_notebook = padre
        
        self.reproductor = ReproductorVoz()
        
        self.posiciones_capitulos = {}
        self.posiciones_encabezados = []  # [{nivel, texto, pos}] para negrita de h1-h6 en _aplicar_estilos_ricos
        self.spans_estilo = []            # [{texto, estilos, cerca_de}] para rich-text
        self.marcadores = {}
        self.longitud_texto = 0
        self._pausa_entre_fragmentos_ms = 0  # ms de pausa entre fragmentos TTS
        
        self.segundos_salto = 10
        self.cargar_config_salto()
        
        self.pos_inicio_fragmento = 0
        # Última página virtual (bloque de _CHARS_POR_PAGINA caracteres) en la
        # que sonó page_scrolled.wav — evita repetir el sonido si el cursor
        # se mueve sin cruzar un límite de página. -1 para que la primera
        # posición real (0) ya cuente como cambio.
        self._pagina_virtual_sonido = -1
        # Variables para la estimación temporal del progreso de voces neuronales
        self._tiempo_inicio_frag = 0.0
        self._longitud_frag_actual = 0
        # Cola de fragmentos para lectura continua de voces neuronales
        self._cola_lectura = []
        self._idx_fragmento_actual = 0
        # Buffer proactivo: evita silencios entre fragmentos disparando la descarga
        # del siguiente cuando queda ~30% del actual
        self._precarga_solicitada = False
        self.ruta_libro_actual = None
        self.ruta_datos_lectura = ruta_config("estado_lectura.json")
        
        sizer_principal = wx.BoxSizer(wx.VERTICAL)

        # 1. DIVISOR
        self.divisor = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        
        self.arbol_indice = wx.TreeCtrl(self.divisor, style=wx.TR_DEFAULT_STYLE | wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_HIDE_ROOT)
        self.arbol_indice.SetName("Índice")
        self.arbol_indice.SetHelpText(
            "Índice del libro cargado. Usa las flechas Arriba y Abajo para navegar por los capítulos. "
            "Pulsa Intro o Enter sobre un capítulo para saltar a él en el área de texto."
        )
        self.raiz_id = self.arbol_indice.AddRoot("Libro")
        self.arbol_indice.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.al_activar_capitulo)
        self.arbol_indice.Bind(wx.EVT_TREE_KEY_DOWN, self._al_tecla_arbol_indice)

        self.txt_contenido = wx.TextCtrl(self.divisor, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL)
        self.txt_contenido.SetName("Contenido del libro")
        self.txt_contenido.SetHelpText(
            "Área de texto de solo lectura con el contenido del capítulo activo. "
            "Puedes seleccionar texto y copiarlo. La voz TTS lee desde la posición del cursor."
        )
        self.txt_contenido.SetValue("¡Bienvenido a Epub TTS! Tu lector de EPUB y PDF con soporte para voces de alta calidad en la nube (Azure, Amazon Polly, Deepgram y ElevenLabs) y voces locales SAPI5. Pulsa Ctrl + O para abrir un libro, o usa Ctrl + 1 a Ctrl + 5 para moverte entre las pestañas. Recuerda marcar tus voces favoritas en Ajustes para empezar a leer. ¡Disfruta de la lectura!")
        self.txt_contenido.Bind(wx.EVT_KEY_UP, self.al_navegar_texto)

        self.divisor.SetMinimumPaneSize(200)
        self.divisor.SplitVertically(self.arbol_indice, self.txt_contenido, 280)
        sizer_principal.Add(self.divisor, 1, wx.EXPAND | wx.ALL, 5)

        # 2. PROGRESO
        sizer_progreso = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_progreso = wx.StaticText(self, label="Progreso: 0%")
        self.deslizador_progreso = wx.Slider(self, value=0, minValue=0, maxValue=100)
        self.deslizador_progreso.SetName("Barra de progreso de lectura")
        self.deslizador_progreso.SetHelpText(
            "Posición de lectura expresada en porcentaje del libro. "
            "Usa las flechas Izquierda y Derecha para navegar. "
            "Al soltar la tecla, la voz saltará a esa posición."
        )
        self.deslizador_progreso.Bind(wx.EVT_SLIDER, self.al_buscar_usuario)
        
        sizer_progreso.Add(self.lbl_progreso, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer_progreso.Add(self.deslizador_progreso, 1, wx.EXPAND, 0)
        sizer_principal.Add(sizer_progreso, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # 3. CONTROLES
        sizer_inferior = wx.BoxSizer(wx.HORIZONTAL)

        self.lbl_voz = wx.StaticText(self, label="Voz para lectura:")
        self.combo_voz = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_voz.SetName("Selector de voz")
        self.combo_voz.SetHelpText(
            "Voz con la que se leerá el libro. Contiene las voces favoritas marcadas en Ajustes "
            "y las voces SAPI5 locales instaladas en el sistema."
        )
        self.combo_voz.Bind(wx.EVT_COMBOBOX, self.al_cambiar_voz)

        self.btn_atras = wx.Button(self, label=f"Retroceder {self.segundos_salto}s")
        self.btn_reproducir = wx.Button(self, label="Reproducir (Ctrl+P)")
        self.btn_adelante = wx.Button(self, label=f"Avanzar {self.segundos_salto}s")
        self.btn_detener = wx.Button(self, label="Detener (Ctrl+D)")
        
        self.btn_reproducir.Bind(wx.EVT_BUTTON, self.al_alternar_reproduccion)
        self.btn_detener.Bind(wx.EVT_BUTTON, self.al_detener)
        self.btn_atras.Bind(wx.EVT_BUTTON, self.al_saltar_atras)
        self.btn_adelante.Bind(wx.EVT_BUTTON, self.al_saltar_adelante)
        aplicar_icono_boton(self.btn_detener, "detener", "Detener")
        # fijar_nombre=False: la etiqueta de estos dos botones cambia con los
        # segundos de salto configurados ("Retroceder 10s"...); un nombre
        # accesible fijo aquí congelaría ese texto para NVDA.
        aplicar_icono_boton(self.btn_atras, "retroceder", fijar_nombre=False)
        aplicar_icono_boton(self.btn_adelante, "avanzar", fijar_nombre=False)

        self.lbl_velocidad = wx.StaticText(self, label="Velocidad de lectura:")
        self.deslizador_velocidad = wx.Slider(self, value=50, minValue=0, maxValue=100)
        self.deslizador_velocidad.SetName("Velocidad de lectura")
        self.deslizador_velocidad.SetHelpText(
            "Velocidad de lectura de la voz. 0 es la más lenta, 100 la más rápida. "
            "Flechas: ±1. RePág/AvPág: ±5."
        )
        self.deslizador_velocidad.Bind(wx.EVT_SLIDER, self.al_cambiar_velocidad)
        self.deslizador_velocidad.Bind(wx.EVT_KEY_DOWN, self._al_tecla_slider_velocidad)
        self.deslizador_velocidad.Bind(wx.EVT_SCROLL_CHANGED, self._al_slider_velocidad_cambio)
        self.deslizador_velocidad.Bind(wx.EVT_SCROLL_THUMBTRACK, self._al_slider_velocidad_cambio)

        self.lbl_volumen = wx.StaticText(self, label="Volumen:")
        self.deslizador_volumen = wx.Slider(self, value=100, minValue=0, maxValue=100)
        self.deslizador_volumen.SetName("Volumen de lectura")
        self.deslizador_volumen.SetHelpText(
            "Volumen del audio de lectura. 0 es silencio, 100 es volumen máximo. "
            "Flechas: ±1. RePág/AvPág: ±5."
        )
        self.deslizador_volumen.Bind(wx.EVT_SLIDER, self.al_cambiar_volumen)
        self.deslizador_volumen.Bind(wx.EVT_KEY_DOWN, self._al_tecla_slider_volumen)

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
        # Diferir la carga de voces para que el panel reciba el foco antes de que
        # comience la lectura de JSONs y la enumeración de voces SAPI5.
        wx.CallAfter(self.cargar_voces_usuario)

        # Puntos de anclaje para el bucle de tabulación gestionado desde la ventana principal.
        # VentanaPrincipal usa estas referencias para saber dónde termina y empieza este panel.
        self.primer_control = self.arbol_indice
        self.ultimo_control = self.deslizador_volumen
    # ANCLAJE_FIN: CONSTRUCCION_INTERFAZ

    # ANCLAJE_INICIO: GESTION_CONFIGURACION_Y_PESTANAS
    def cargar_config_salto(self):
        try:
            ruta = ruta_config("ajustes.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    conf = json.load(f)
                    self.segundos_salto = int(conf.get("segundos_salto", 10))
                    self._pausa_entre_fragmentos_ms = int(conf.get("pausa_entre_fragmentos_ms", 0))
                    # Restaurar sliders solo si los widgets ya están inicializados
                    if hasattr(self, 'deslizador_velocidad'):
                        vel = int(conf.get("velocidad_lectura", 50))
                        vol = int(conf.get("volumen_lectura", 100))
                        # Aplicar la escala de velocidad guardada (puede haber cambiado en Ajustes)
                        self._aplicar_escala_velocidad(
                            conf.get("escala_velocidad", "porcentaje"), vel
                        )
                        self.deslizador_volumen.SetValue(vol)
                        self.reproductor.fijar_velocidad(vel)
                        self.reproductor.fijar_volumen(vol)
        except Exception as e:
            logger.warning("[PestanaLectura] No se pudo leer ajustes.json: %s", e)
            self.segundos_salto = 10

    def al_cambiar_pestana_padre(self, event):
        if event.GetSelection() == 0:
            self.cargar_config_salto()
            self.btn_atras.SetLabel(f"Retroceder {self.segundos_salto}s")
            self.btn_adelante.SetLabel(f"Avanzar {self.segundos_salto}s")
            # Diferir la carga de voces para que el foco llegue al panel antes
            # de que comience la lectura de JSONs. El combo se llena tras el cambio de pestaña.
            wx.CallAfter(self.cargar_voces_usuario)
        event.Skip()
    # ANCLAJE_FIN: GESTION_CONFIGURACION_Y_PESTANAS

    # ANCLAJE_INICIO: CARGA_Y_CAMBIO_VOCES
    def cargar_voces_usuario(self):
        seleccion_previa = self.combo_voz.GetStringSelection()
        self.combo_voz.Clear()
        voces_para_combo = []

        # Cargar favoritos globales (SAPI5 y neurales comparten el mismo archivo)
        ruta_favs = ruta_config("voces_favoritas.json")
        ruta_todas = ruta_config("voces_disponibles.json")

        ids_favoritos = []
        if os.path.exists(ruta_favs):
            try:
                with open(ruta_favs, "r", encoding="utf-8") as f:
                    ids_favoritos = json.load(f)
            except Exception as e:
                logger.warning("[PestanaLectura] No se pudo leer voces_favoritas.json: %s", e)

        # Carga de voces SAPI5 de 64 bits
        voces_locales_64 = []
        try:
            if hasattr(self.reproductor, "cliente_local"):
                voces_locales_64 = self.reproductor.cliente_local.obtener_voces()
        except Exception as e:
            logger.warning("[PestanaLectura] No se pudieron cargar voces SAPI5: %s", e)

        # Carga de voces SAPI5 de 32 bits (bridge Eloquence/CodeFactory)
        voces_locales_32 = []
        try:
            if hasattr(self.reproductor, "cliente_local_32") and self.reproductor.cliente_local_32.conectado:
                voces_locales_32 = self.reproductor.cliente_local_32.obtener_voces()
        except Exception as e:
            logger.warning("[PestanaLectura] No se pudieron cargar voces SAPI5 32-bits: %s", e)

        # Deduplicar: si una voz aparece tanto en 64 como en 32 bits (mismo nombre),
        # conservar solo la entrada de 64 bits (que es la que realmente funciona).
        nombres_64 = {v.get("nombre", "").strip().lower() for v in voces_locales_64}
        voces_locales_32 = [
            v for v in voces_locales_32
            if v.get("nombre", "").strip().lower() not in nombres_64
        ]

        # Combinar voces locales y filtrar por favoritos
        # Si hay favoritos marcados, mostrar solo los favoritos; si no hay ninguno marcado,
        # mostrar todas las voces locales (fallback para que siempre haya al menos una opción).
        todas_locales = voces_locales_64 + voces_locales_32
        ids_locales_favoritas = [v.get("id") for v in todas_locales if v.get("id") in ids_favoritos]
        mostrar_todas_locales = not ids_locales_favoritas

        for v in todas_locales:
            if mostrar_todas_locales or v.get("id") in ids_favoritos:
                etiqueta = "[32 bits]" if v.get("proveedor_id") == "local_32" else "[Local]"
                nombre_mostrar = f"{etiqueta} {v['nombre']}"
                voces_para_combo.append((nombre_mostrar, v))

        # Carga de voces neuronales favoritas
        if ids_favoritos and os.path.exists(ruta_todas):
            try:
                with open(ruta_todas, "r", encoding="utf-8") as f:
                    todas = json.load(f)
                    for prov, lista in todas.items():
                        for v in lista:
                            if v.get("id") in ids_favoritos:
                                v["proveedor_id"] = prov
                                nombre_mostrar = _nombre_combo_neuronal(v, prov)
                                voces_para_combo.append((nombre_mostrar, v))
            except Exception as e:
                print(f"[Aviso] No se pudo leer voces_disponibles.json: {e}")

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
        
        # Forzar actualización inicial del reproductor
        self.al_cambiar_voz(None)

    def al_cambiar_voz(self, event):
        """
        Aplica la configuración de la voz seleccionada en la interfaz 
        al motor de reproducción de audio.
        """
        idx = self.combo_voz.GetSelection()
        if idx != wx.NOT_FOUND:
            # 1. Obtiene los parámetros de la voz seleccionada
            self.voz_seleccionada = self.combo_voz.GetClientData(idx)
            
            # 2. Transfiere la configuración al motor de reproducción de forma asíncrona
            if hasattr(self.reproductor, 'fijar_voz'):
                self.reproductor.fijar_voz(self.voz_seleccionada)
            
            # 3. Detiene cualquier lectura en curso para aplicar el cambio limpiamente
            if hasattr(self.reproductor, 'detener'):
                self.reproductor.detener()
    # ANCLAJE_FIN: CARGA_Y_CAMBIO_VOCES

    # ANCLAJE_INICIO: ACCIONES_REPRODUCCION_PAUSA
    def al_alternar_reproduccion(self, evento):
        """Gestiona los estados de reproducción, pausa y reanudación del texto actual."""
        # 1. Verificación de estado
        estado = 'detenido'
        if hasattr(self.reproductor, 'obtener_estado'):
            estado = self.reproductor.obtener_estado()
        elif hasattr(self.reproductor, 'estado'):
            estado = self.reproductor.estado

        # 2. Transiciones de estado (Play/Pausa)
        if estado == 'reproduciendo':
            # Al pausar: vaciar cola y cancelar precarga para que no llegue audio
            # de un fragmento que ya no es el actual al reanudar.
            self._cola_lectura = []
            self._idx_fragmento_actual = 0
            self._precarga_solicitada = False
            if hasattr(self.reproductor, 'pausar'):
                self.reproductor.pausar()
        elif estado == 'pausado':
            tipo_motor = getattr(self.reproductor, 'tipo_motor_actual', 'local')
            if tipo_motor == 'local':
                # SAPI5 admite pausa/reanudación nativa
                if hasattr(self.reproductor, 'reanudar'):
                    self.reproductor.reanudar()
            else:
                # Las voces neuronales no pueden retomar desde mitad de fragmento.
                # Forzar estado a 'detenido' y reiniciar desde la posición exacta del cursor.
                self.reproductor.estado = 'detenido'
                self.al_alternar_reproduccion(evento)
        else:
            # 3. Inicio de nueva lectura desde la posición del cursor
            pos_actual = self.txt_contenido.GetInsertionPoint()
            self.pos_inicio_fragmento = pos_actual

            texto_completo = self.txt_contenido.GetValue()
            if not texto_completo:
                return

            fragmento_total = texto_completo[pos_actual:]
            if not fragmento_total.strip():
                return

            idx = self.combo_voz.GetSelection()
            if idx == wx.NOT_FOUND:
                return

            voz_data = self.combo_voz.GetClientData(idx)
            self.voz_seleccionada = voz_data
            if hasattr(self.reproductor, 'fijar_voz'):
                self.reproductor.fijar_voz(voz_data)

            es_voz_neuronal = False
            if voz_data:
                prov = voz_data.get('proveedor_id', 'local').lower()
                if 'azure' in prov or 'eleven' in prov or 'polly' in prov or 'deepgram' in prov:
                    es_voz_neuronal = True

            if es_voz_neuronal:
                # Voces neuronales: dividir en fragmentos y reproducir en cola continua
                self._cola_lectura = self._dividir_en_fragmentos(fragmento_total, pos_actual)
                self._idx_fragmento_actual = 0
                self._reproducir_siguiente_fragmento()
            else:
                # Voz local SAPI5: lectura párrafo a párrafo con sincronización de cursor.
                # _longitud_frag_actual = 0 → el timer usa GetInsertionPoint() (posición real)
                # en lugar de la estimación temporal usada para voces neuronales.
                self._cola_lectura = []
                self._longitud_frag_actual = 0
                self.reproductor.cargar_texto(
                    fragmento_total,
                    pos_offset=pos_actual,
                    callback_progreso=self._al_progreso_sapi,
                    callback_completado=self._al_sapi_completado,
                )

    def _dividir_en_fragmentos(self, texto, pos_base):
        """
        Divide el texto en fragmentos de máximo MAX_CHARS caracteres usando
        una jerarquía de puntos de corte para preservar la entonación natural:

          P0 · Límite de párrafo (\n\n)
          P1 · Pausas fuertes  (. ! ? … seguidos de espacio o salto de línea)
          P2 · Pausas medias   (, ; seguidos de espacio)
          P3 · Seguridad       (último espacio — nunca partir palabras)
          P4 · Último recurso  (corte estricto en MAX_CHARS)

        La búsqueda de P1–P3 se realiza en los últimos VENTANA_BUSQUEDA
        caracteres del bloque, garantizando fragmentos compactos sin silabear.
        Retorna lista de (texto_fragmento, pos_inicio_global).
        """
        # Fragmentos más grandes = menos costuras por audiolibro. Con 200
        # caracteres (una o dos frases) cada unión de fragmento dependía de
        # que la precarga del siguiente ganara la carrera contra la
        # reproducción del actual; con una API lenta, perder esa carrera
        # obligaba a sintetizar en el momento y sonaba como una pausa
        # aleatoria ajena a la puntuación real del texto.
        MAX_CHARS = 500
        VENTANA = 250  # ventana hacia atrás para buscar puntos de corte naturales
        resultado = []
        restante = texto
        pos_actual = pos_base

        while restante:
            if len(restante) <= MAX_CHARS:
                resultado.append((restante, pos_actual))
                break

            inicio = max(0, MAX_CHARS - VENTANA)
            corte = -1

            # P0: Límite de párrafo — doble salto de línea
            c = restante.rfind('\n\n', inicio, MAX_CHARS)
            if c != -1:
                corte = c + 2

            # P1: Pausas fuertes — punto, exclamación, interrogación, elipsis
            if corte <= 0:
                for sep in ('. ', '! ', '? ', '…', '...',
                            '.\n', '!\n', '?\n'):
                    c = restante.rfind(sep, inicio, MAX_CHARS)
                    if c != -1:
                        corte = c + len(sep)
                        break

            # P2: Pausas medias — coma o punto y coma
            if corte <= 0:
                for sep in (', ', '; '):
                    c = restante.rfind(sep, inicio, MAX_CHARS)
                    if c != -1:
                        corte = c + len(sep)
                        break

            # P3: Último espacio — nunca partir palabras
            if corte <= 0:
                c = restante.rfind(' ', inicio, MAX_CHARS)
                if c > 0:
                    corte = c + 1

            # P4: Último recurso — corte estricto
            if corte <= 0:
                corte = MAX_CHARS

            resultado.append((restante[:corte], pos_actual))
            pos_actual += corte
            restante = restante[corte:]

        return resultado

    def _reproducir_siguiente_fragmento(self):
        """Inicia la reproducción del siguiente fragmento de la cola."""
        if not self._cola_lectura or self._idx_fragmento_actual >= len(self._cola_lectura):
            return

        texto_frag, pos_inicio = self._cola_lectura[self._idx_fragmento_actual]

        if not texto_frag.strip():
            self._idx_fragmento_actual += 1
            self._reproducir_siguiente_fragmento()
            return

        self.pos_inicio_fragmento = pos_inicio
        self._tiempo_inicio_frag = time.time()
        self._longitud_frag_actual = len(texto_frag)

        # Resetear flag para que la precarga del fragmento N+1 se dispare
        # en cada nuevo fragmento, no solo en el primero.
        self._precarga_solicitada = False

        # Disparar precarga del fragmento siguiente de forma inmediata,
        # sin esperar al 70% del timer. Así APIs lentas como Polly tienen
        # tiempo suficiente para responder antes de que termine el fragmento.
        idx_siguiente = self._idx_fragmento_actual + 1
        if self._cola_lectura and idx_siguiente < len(self._cola_lectura):
            texto_sig, _ = self._cola_lectura[idx_siguiente]
            if texto_sig.strip():
                self._precarga_solicitada = True
                voz = self.combo_voz.GetClientData(self.combo_voz.GetSelection())
                self.reproductor.precargar_fragmento(texto_sig, voz)

        self.txt_contenido.SetInsertionPoint(pos_inicio)
        self.txt_contenido.ShowPosition(pos_inicio)

        self.reproductor.cargar_texto(texto_frag, callback_completado=self._al_fragmento_completado, modo_cola=True)

    def _al_fragmento_completado(self):
        """Callback invocado por ReproductorVoz cuando termina un fragmento neuronal."""
        self._idx_fragmento_actual += 1
        if self._cola_lectura and self._idx_fragmento_actual < len(self._cola_lectura):
            pausa = getattr(self, '_pausa_entre_fragmentos_ms', 0)
            if pausa > 0:
                wx.CallLater(pausa, self._reproducir_siguiente_fragmento)
            else:
                self._reproducir_siguiente_fragmento()

    def _al_progreso_sapi(self, pos):
        """
        Llamado por ClienteSapi5 al inicio de cada párrafo.
        Mueve el cursor exactamente al párrafo que SAPI5 acaba de empezar a leer,
        igual que el mecanismo de bookmarks de Bookworm.
        """
        self.pos_inicio_fragmento = pos
        self.txt_contenido.SetInsertionPoint(pos)
        self.txt_contenido.ShowPosition(pos)
        self._comprobar_cambio_pagina_virtual(pos)
        if self.longitud_texto > 0:
            pct = max(0, min(100, int(pos / self.longitud_texto * 100)))
            if self.deslizador_progreso.GetValue() != pct:
                self.deslizador_progreso.SetValue(pct)
                self.lbl_progreso.SetLabel(f"Progreso: {pct}%")

    def _al_sapi_completado(self):
        """Llamado por ClienteSapi5 cuando termina de leer todos los párrafos."""
        self.reproductor.estado = 'detenido'
        self.guardar_datos_libro()

    def al_detener(self, evento):
        # Cancelar la cola de lectura continua antes de detener el motor
        self._cola_lectura = []
        self._idx_fragmento_actual = 0
        self._precarga_solicitada = False
        if hasattr(self.reproductor, 'detener'):
            self.reproductor.detener()
        self.guardar_datos_libro()
    # ANCLAJE_FIN: ACCIONES_REPRODUCCION_PAUSA

    # ANCLAJE_INICIO: ACTUALIZACION_INTERFAZ_USUARIO
    def al_actualizar_ui(self, evento):
        """
        Sincroniza el estado de los botones y la barra de progreso.
        La barra solo se actualiza durante la reproducción activa para evitar
        sobreescribir la posición que el usuario haya establecido manualmente.
        """
        # 1. Actualización de etiquetas de control
        estado = "detenido"
        if hasattr(self.reproductor, 'obtener_estado'):
            estado = self.reproductor.obtener_estado()

        if estado == 'reproduciendo':
            if self.btn_reproducir.GetLabel() != "Pausar (Ctrl+P)":
                self.btn_reproducir.SetLabel("Pausar (Ctrl+P)")
        else:
            if self.btn_reproducir.GetLabel() != "Reproducir (Ctrl+P)":
                self.btn_reproducir.SetLabel("Reproducir (Ctrl+P)")

        # 2. Barra de progreso y sincronización de cursor.
        # Solo se actualiza durante la reproducción activa para no sobreescribir
        # la posición que el usuario haya establecido manualmente.
        if estado == 'reproduciendo' and self.longitud_texto > 0:
            if self._longitud_frag_actual > 0:
                # El cursor del TextCtrl no avanza solo durante la síntesis neuronal.
                # Se estima la posición usando tiempo transcurrido a ~14 caracteres/segundo.
                tiempo_transcurrido = time.time() - self._tiempo_inicio_frag
                avance_estimado = min(
                    self._longitud_frag_actual,
                    int(tiempo_transcurrido * 14)
                )
                pos_estimada = self.pos_inicio_fragmento + avance_estimado

                # Buffer proactivo: cuando queda ~30% del fragmento actual,
                # iniciar la descarga del siguiente ANTES de que este termine.
                # Esto elimina el silencio de 1-2s entre fragmentos.
                tiempo_estimado_total = self._longitud_frag_actual / 14.0
                if (not self._precarga_solicitada and
                        tiempo_estimado_total > 0 and
                        tiempo_transcurrido / tiempo_estimado_total >= 0.70):
                    idx_siguiente = self._idx_fragmento_actual + 1
                    if self._cola_lectura and idx_siguiente < len(self._cola_lectura):
                        texto_sig, _ = self._cola_lectura[idx_siguiente]
                        if texto_sig.strip():
                            self._precarga_solicitada = True
                            voz = self.combo_voz.GetClientData(
                                self.combo_voz.GetSelection()
                            )
                            self.reproductor.precargar_fragmento(texto_sig, voz)
            else:
                pos_estimada = self.txt_contenido.GetInsertionPoint()

            # Sincronización de cursor: mover el punto de inserción para que NVDA
            # pueda seguir la posición de lectura en tiempo real
            self.txt_contenido.SetInsertionPoint(pos_estimada)
            self._comprobar_cambio_pagina_virtual(pos_estimada)

            porcentaje = max(0, min(100, int((pos_estimada / self.longitud_texto) * 100)))

            # Solo actualiza si hay cambio real para no saturar a NVDA
            if self.deslizador_progreso.GetValue() != porcentaje:
                self.deslizador_progreso.SetValue(porcentaje)
                self.lbl_progreso.SetLabel(f"Progreso: {porcentaje}%")
    # ANCLAJE_FIN: ACTUALIZACION_INTERFAZ_USUARIO

    # ANCLAJE_INICIO: NAVEGACION_TEXTO_Y_SALTOS
    def al_saltar_atras(self, evento):
        pos = self.txt_contenido.GetInsertionPoint()
        caracteres = self.segundos_salto * 15
        nuevo = max(0, pos - caracteres)
        self.txt_contenido.SetInsertionPoint(nuevo)
        self.txt_contenido.ShowPosition(nuevo)
        if hasattr(self.reproductor, 'estado') and self.reproductor.estado == 'reproduciendo':
            # Detener y reiniciar desde la nueva posición (no pausar)
            self._cola_lectura = []
            self._idx_fragmento_actual = 0
            self.reproductor.detener()
            self.al_alternar_reproduccion(None)

    def al_saltar_adelante(self, evento):
        pos = self.txt_contenido.GetInsertionPoint()
        caracteres = self.segundos_salto * 15
        nuevo = min(self.longitud_texto, pos + caracteres)
        self.txt_contenido.SetInsertionPoint(nuevo)
        self.txt_contenido.ShowPosition(nuevo)
        if hasattr(self.reproductor, 'estado') and self.reproductor.estado == 'reproduciendo':
            # Detener y reiniciar desde la nueva posición (no pausar)
            self._cola_lectura = []
            self._idx_fragmento_actual = 0
            self.reproductor.detener()
            self.al_alternar_reproduccion(None)

    def al_cambiar_velocidad(self, evento):
        v = self.deslizador_velocidad.GetValue()
        logger.debug("[Lectura] al_cambiar_velocidad: slider v=%s (min=%s max=%s)",
                        v, self.deslizador_velocidad.GetMin(), self.deslizador_velocidad.GetMax())
        if hasattr(self.reproductor, 'fijar_velocidad'):
            self.reproductor.fijar_velocidad(v)
        self._guardar_ajuste_slider("velocidad_lectura", v)

    def al_cambiar_volumen(self, evento):
        v = self.deslizador_volumen.GetValue()
        if hasattr(self.reproductor, 'fijar_volumen'):
            self.reproductor.fijar_volumen(v)
        self._guardar_ajuste_slider("volumen_lectura", v)

    def _guardar_ajuste_slider(self, clave, valor):
        """Persiste el valor de un slider en ajustes.json de forma inmediata."""
        try:
            ruta = ruta_config("ajustes.json")
            datos = {}
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
            datos[clave] = valor
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[Aviso] No se pudo guardar ajuste de slider '{clave}': {e}")
    
    def _al_tecla_arbol_indice(self, evento):
        """Sonido de navegación al moverse por el árbol de índice del libro."""
        if evento.GetKeyCode() in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            reproducir(LIST_NAV)
        evento.Skip()

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
        pos_actual = self.txt_contenido.GetInsertionPoint()
        
        if not isinstance(self.marcadores, dict): self.marcadores = {}
            
        dlg = DialogoMarcadores(self, self.marcadores, pos_actual)
        resultado = dlg.ShowModal()
        
        if resultado == wx.ID_OK:
            if dlg.debe_navegar and dlg.posicion_seleccionada is not None:
                self._ir_a_posicion(dlg.posicion_seleccionada)
        
        # Guardado de seguridad al cerrar el gestor de marcadores
        self.marcadores = dlg.marcadores
        self.guardar_datos_libro()
        
        dlg.Destroy()

    def _ir_a_posicion(self, pos):
        """Desplaza el cursor de lectura a la posición indicada y actualiza el foco."""
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
            
            while True:
                idx = texto_completo.find(consulta, inicio)
                if idx == -1: break
                contexto = self.txt_contenido.GetValue()[idx:idx+50].replace("\n", " ")
                coincidencias.append((idx, f"...{contexto}..."))
                inicio = idx + 1
            
            if not coincidencias:
                reproducir(ERROR)
                wx.MessageBox("No se ha encontrado el texto especificado en este libro.", "Búsqueda finalizada")
            elif len(coincidencias) == 1:
                self._ir_a_posicion(coincidencias[0][0])
            else:
                opciones = [c[1] for c in coincidencias]
                dlg_lista = wx.SingleChoiceDialog(self, f"Se encontraron {len(coincidencias)} resultados:", "Seleccionar resultado", opciones)
                if dlg_lista.ShowModal() == wx.ID_OK:
                    seleccion = dlg_lista.GetSelection()
                    self._ir_a_posicion(coincidencias[seleccion][0])
                dlg_lista.Destroy()
        dlg.Destroy()

    # ANCLAJE_INICIO: DIALOGO_IR_A_PAGINA
    def iniciar_ir_a_pagina(self):
        """
        Ctrl+G — diálogo unificado de salto accesible para NVDA.
        Tres campos independientes: página del capítulo, página del libro,
        porcentaje global. El usuario rellena solo el que desee.
        Prioridad: porcentaje > página del libro > página del capítulo.
        """
        if not self.longitud_texto:
            wx.MessageBox("Abre un libro antes de usar esta función.", "Sin libro", wx.OK | wx.ICON_INFORMATION)
            return

        pag_cap, total_cap, pag_libro, total_libro = self._calcular_paginas()
        pct_actual = int(self.txt_contenido.GetInsertionPoint() / self.longitud_texto * 100)

        dlg = wx.Dialog(self, title="Ir a página o porcentaje")
        dlg.SetHelpText(
            "Rellena uno de los tres campos para saltar a esa posición del libro. "
            "Deja los otros dos en blanco. "
            "Prioridad si rellenas varios: porcentaje, luego página del libro, luego página del capítulo."
        )
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(
            wx.StaticText(dlg, label=f"Página del capítulo (1–{total_cap}):"),
            0, wx.ALL, 8,
        )
        txt_cap = wx.TextCtrl(dlg, value="")
        txt_cap.SetHelpText(
            f"Número de página dentro del capítulo activo. "
            f"Ahora estás en la página {pag_cap} de {total_cap}. Deja vacío para ignorar."
        )
        sizer.Add(txt_cap, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        sizer.Add(
            wx.StaticText(dlg, label=f"Página del libro (1–{total_libro}):"),
            0, wx.ALL, 8,
        )
        txt_libro = wx.TextCtrl(dlg, value="")
        txt_libro.SetHelpText(
            f"Número de página dentro del libro completo. "
            f"Ahora estás en la página {pag_libro} de {total_libro}. Deja vacío para ignorar."
        )
        sizer.Add(txt_libro, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        sizer.Add(
            wx.StaticText(dlg, label="Porcentaje del libro (0–100):"),
            0, wx.ALL, 8,
        )
        txt_pct = wx.TextCtrl(dlg, value="")
        txt_pct.SetHelpText(
            f"Posición como porcentaje del libro completo. "
            f"Ahora estás al {pct_actual}%. Deja vacío para ignorar."
        )
        sizer.Add(txt_pct, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        sizer.Add(
            wx.StaticText(dlg, label="(Rellena solo el campo que quieras usar y deja los demás vacíos.)"),
            0, wx.ALL, 8,
        )

        sz_btn = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(sz_btn, 0, wx.EXPAND | wx.ALL, 8)
        dlg.SetSizer(sizer)
        dlg.Fit()
        dlg.CentreOnParent()

        if dlg.ShowModal() == wx.ID_OK:
            val_pct   = txt_pct.GetValue().strip()
            val_libro = txt_libro.GetValue().strip()
            val_cap   = txt_cap.GetValue().strip()
            destino   = None

            if val_pct.isdigit():
                pct = max(0, min(int(val_pct), 100))
                destino = int(pct / 100 * self.longitud_texto)
            elif val_libro.isdigit():
                n = max(1, min(int(val_libro), total_libro))
                destino = (n - 1) * self._CHARS_POR_PAGINA
            elif val_cap.isdigit():
                pos_cursor = self.txt_contenido.GetInsertionPoint()
                posiciones_ordenadas = sorted(self.posiciones_capitulos.values())
                inicio_cap = 0
                for pos in posiciones_ordenadas:
                    if pos <= pos_cursor:
                        inicio_cap = pos
                n = max(1, min(int(val_cap), total_cap))
                destino = inicio_cap + (n - 1) * self._CHARS_POR_PAGINA

            if destino is not None:
                destino = max(0, min(destino, self.longitud_texto - 1))
                self.txt_contenido.SetInsertionPoint(destino)
                self.txt_contenido.ShowPosition(destino)
                if hasattr(self.reproductor, 'detener'):
                    self.reproductor.detener()
                self.anunciar_pagina_actual()

        dlg.Destroy()
    # ANCLAJE_FIN: DIALOGO_IR_A_PAGINA

    # ANCLAJE_INICIO: SELECTOR_ESCALA_VELOCIDAD
    def _aplicar_escala_velocidad(self, escala: str, valor_guardado: int):
        """
        Actualiza la etiqueta y el texto de ayuda del slider de velocidad
        según la escala activa, para que NVDA lo lea correctamente.

        El slider SIEMPRE vive en el mismo rango 0–100 que se envía al
        reproductor — antes, el modo "multiplicador" cambiaba el propio
        rango del slider a 0–25 y dependía de obtener_velocidad_normalizada()
        para reconvertirlo a 0–100 al aplicar la velocidad real, pero esa
        función nunca se llamaba desde ningún sitio: el valor crudo del
        slider (como mucho 25) se enviaba directo al motor, que lo trataba
        como un porcentaje 0–100. Con eso, el máximo alcanzable en modo
        "por puntos" (25) seguía siendo más lento que la velocidad normal
        (50) — nunca se podía llegar ni a la velocidad neutra, muchísimo
        menos a "más rápido". El modo "por puntos" es ahora solo una
        relectura del mismo valor 0–100, calculada con la misma fórmula que
        aplica realmente el motor (_multiplicador_desde_valor), así que lo
        que se lee y lo que suena son siempre la misma cifra.
        """
        self.deslizador_velocidad.SetMin(0)
        self.deslizador_velocidad.SetMax(100)
        self.deslizador_velocidad.SetValue(valor_guardado)

        if escala == "multiplicador":
            self.lbl_velocidad.SetLabel(f"Velocidad ({self._etiqueta_multiplicador(valor_guardado)}):")
            self.deslizador_velocidad.SetHelpText(
                "Velocidad de lectura en multiplicadores. 0.2× es la más lenta, "
                "1.0× es la normal, 1.8× es la más rápida. "
                "Flechas: ±1. RePág/AvPág: ±5."
            )
        else:
            self.lbl_velocidad.SetLabel("Velocidad de lectura:")
            self.deslizador_velocidad.SetHelpText(
                "Velocidad de lectura de la voz. 0 es la más lenta, 100 la más rápida. "
                "Flechas: ±1. RePág/AvPág: ±5."
            )

    @staticmethod
    def _multiplicador_desde_valor(v: int) -> float:
        """
        Multiplicador real aproximado para un valor 0–100 de velocidad, con
        la misma fórmula que aplican los motores de voz (tasa SSML
        (v-50)*1.6%, saturada en ±80%): 50 → 1.0× exacto, 0 → 0.2×, 100 → 1.8×.
        """
        return 1 + (v - 50) * 0.016

    @classmethod
    def _etiqueta_multiplicador(cls, v: int) -> str:
        m = cls._multiplicador_desde_valor(v)
        if v <= 5:
            calificativo = " (Muy lenta)"
        elif v <= 30:
            calificativo = " (Lenta)"
        elif 45 <= v <= 55:
            calificativo = " (Normal)"
        elif v >= 95:
            calificativo = " (Máxima)"
        elif v >= 70:
            calificativo = " (Muy rápida)"
        elif v >= 55:
            calificativo = " (Rápida)"
        else:
            calificativo = ""
        return f"{m:.2f}×{calificativo}"
    # ANCLAJE_FIN: SELECTOR_ESCALA_VELOCIDAD

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
        # txt_contenido es de solo lectura: cualquier KEY_UP que llegue aquí
        # viene de navegación con flechas (o RePág/AvPág/Inicio/Fin), nunca de
        # escritura — el punto de entrada correcto para el sonido sutil de
        # cambio de página al estilo Bookworm.
        self._comprobar_cambio_pagina_virtual(self.txt_contenido.GetInsertionPoint())
        e.Skip()
    # ANCLAJE_FIN: NAVEGACION_TEXTO_Y_SALTOS

    # ANCLAJE_INICIO: SONIDO_CAMBIO_PAGINA_VIRTUAL
    def _comprobar_cambio_pagina_virtual(self, pos):
        """
        Reproduce page_scrolled.wav cada vez que el cursor cruza el límite de
        una página virtual (bloque de _CHARS_POR_PAGINA caracteres) — tanto al
        navegar con las flechas como durante la lectura continua con
        cualquier motor de voz, igual que hace Bookworm con sus propias
        páginas. Si el archivo no está disponible, reproducir() ya falla en
        silencio (ver reproductor_sonidos.py), así que no hace falta
        protección adicional aquí.
        """
        pagina = pos // self._CHARS_POR_PAGINA
        if pagina != self._pagina_virtual_sonido:
            self._pagina_virtual_sonido = pagina
            reproducir(PAGE_SCROLLED)
    # ANCLAJE_FIN: SONIDO_CAMBIO_PAGINA_VIRTUAL

    def al_cargar_libro(self, evento):
        """Abre el explorador de archivos para seleccionar un libro EPUB o PDF."""
        with wx.FileDialog(
            self, "Seleccionar libro",
            wildcard="Libros compatibles (*.epub;*.pdf)|*.epub;*.pdf|Archivos EPUB (*.epub)|*.epub|Archivos PDF (*.pdf)|*.pdf",
            style=wx.FD_OPEN,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.cargar_epub_desde_ruta(dlg.GetPath())

    # ANCLAJE_INICIO: GESTION_DATOS_LIBRO
    def cargar_epub_desde_ruta(self, ruta):
        """
        Pese al nombre (histórico, mantenido para no romper las llamadas ya
        existentes desde Biblioteca y VentanaPrincipal), admite tanto EPUB
        como PDF — el formato se decide por la extensión del archivo y se
        delega en el extractor correspondiente (extraer_datos_epub /
        extraer_datos_pdf), que devuelven la misma forma de datos.
        """
        self.guardar_datos_libro()
        try:
            extractor = extraer_datos_pdf if ruta.lower().endswith('.pdf') else extraer_datos_epub
            texto, datos_arbol, self.posiciones_capitulos, self.posiciones_encabezados, self.spans_estilo = extractor(ruta)

            if hasattr(self.reproductor, 'detener'):
                self.reproductor.detener()

            self.marcadores = {}
            self.pos_inicio_fragmento = 0
            self._pagina_virtual_sonido = -1
            self.txt_contenido.SetValue(texto)
            self.longitud_texto = len(texto)
            # Aplicar negrita/cursiva/subrayado en diferido (no bloquea la carga)
            wx.CallAfter(self._aplicar_estilos_ricos)
            self.arbol_indice.DeleteAllItems()
            self.raiz_id = self.arbol_indice.AddRoot(os.path.basename(ruta))
            self._construir_arbol_indice(self.raiz_id, datos_arbol)
            self.ruta_libro_actual = ruta
            self.cargar_datos_libro(os.path.basename(ruta))
            self.arbol_indice.SetFocus()

            # Registrar en el historial de libros recientes de VentanaPrincipal
            try:
                ventana = self.padre_notebook.GetParent()
                if hasattr(ventana, 'agregar_a_recientes'):
                    ventana.agregar_a_recientes(ruta)
            except Exception:
                pass

        except Exception as e:
            reproducir(ERROR)
            wx.MessageBox(f"Se ha producido un error técnico al intentar procesar el libro.\n\nDetalle: {e}", "Error al cargar el libro")

    def _construir_arbol_indice(self, padre, nodos):
        for n in nodos:
            item = self.arbol_indice.AppendItem(padre, n['title'])
            if n['children']: self._construir_arbol_indice(item, n['children'])

    def _al_tecla_slider_velocidad(self, e):
        """PageUp/AvPág cambian la velocidad en ±5; el resto se delega al widget."""
        self._aplicar_salto_slider(e, self.deslizador_velocidad, self.al_cambiar_velocidad)

    def _al_tecla_slider_volumen(self, e):
        """PageUp/AvPág cambian el volumen en ±5; el resto se delega al widget."""
        self._aplicar_salto_slider(e, self.deslizador_volumen, self.al_cambiar_volumen)

    def _aplicar_salto_slider(self, e, slider, callback_cambio):
        """
        Intercepta RePág/AvPág para mover el slider ±5 anunciando solo el valor
        actual (sin leer la lista de números). Las flechas (±1) se delegan al widget.
        """
        key = e.GetKeyCode()
        if key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            delta = -5 if key == wx.WXK_PAGEUP else 5
            nuevo = max(slider.GetMin(), min(slider.GetMax(), slider.GetValue() + delta))
            slider.SetValue(nuevo)
            callback_cambio(None)
        else:
            e.Skip()
        
    def guardar_datos_libro(self):
        if not self.ruta_libro_actual: return
        try:
            datos = {}
            if os.path.exists(self.ruta_datos_lectura):
                with open(self.ruta_datos_lectura, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
            datos[os.path.basename(self.ruta_libro_actual)] = {
                "pos": self.txt_contenido.GetInsertionPoint(),
                "marcadores": self.marcadores,
                # Memoria de libro: velocidad, volumen y voz usados en este libro
                "velocidad": self.deslizador_velocidad.GetValue(),
                "volumen": self.deslizador_volumen.GetValue(),
                "voz": self.combo_voz.GetStringSelection(),
            }
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self.ruta_datos_lectura, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False)
        except Exception as e:
            print(f"[Error] No se pudieron guardar los datos del libro: {e}")

    def cargar_datos_libro(self, nombre):
        try:
            if os.path.exists(self.ruta_datos_lectura):
                with open(self.ruta_datos_lectura, 'r', encoding='utf-8') as f:
                    d = json.load(f).get(nombre)
                    if d:
                        # Posición y marcadores
                        self.txt_contenido.SetInsertionPoint(d.get("pos", 0))
                        self.txt_contenido.ShowPosition(d.get("pos", 0))
                        self.marcadores = d.get("marcadores", {})
                        # Restaurar velocidad guardada para este libro
                        vel = d.get("velocidad")
                        if vel is not None:
                            self.deslizador_velocidad.SetValue(int(vel))
                            self.reproductor.fijar_velocidad(int(vel))
                        # Restaurar volumen guardado para este libro
                        vol = d.get("volumen")
                        if vol is not None:
                            self.deslizador_volumen.SetValue(int(vol))
                            self.reproductor.fijar_volumen(int(vol))
                        # Restaurar voz guardada para este libro
                        voz_guardada = d.get("voz", "")
                        if voz_guardada:
                            idx = self.combo_voz.FindString(voz_guardada)
                            if idx != wx.NOT_FOUND:
                                self.combo_voz.SetSelection(idx)
                                self.al_cambiar_voz(None)
        except Exception as e:
            print(f"[Error] No se pudieron cargar los datos del libro '{nombre}': {e}")
            self.marcadores = {}
    # ANCLAJE_FIN: GESTION_DATOS_LIBRO
        
    # ANCLAJE_INICIO: CONFIGURACION_ATAJOS_TECLADO
    def configurar_aceleradores(self):
        ids = [wx.NewIdRef() for _ in range(7)]
        self.Bind(wx.EVT_MENU, self.al_abrir_marcadores,                id=ids[0])
        self.Bind(wx.EVT_MENU, self.al_alternar_reproduccion,           id=ids[1])
        self.Bind(wx.EVT_MENU, self.al_detener,                         id=ids[2])
        self.Bind(wx.EVT_MENU, lambda e: self.iniciar_busqueda(),       id=ids[3])
        self.Bind(wx.EVT_MENU, lambda e: self.iniciar_ir_a_pagina(),    id=ids[4])
        self.Bind(wx.EVT_MENU, self.al_cargar_libro,                    id=ids[5])
        self.Bind(wx.EVT_MENU, lambda e: self.anunciar_pagina_actual(), id=ids[6])
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('M'), ids[0]),
            (wx.ACCEL_CTRL, ord('P'), ids[1]),
            (wx.ACCEL_CTRL, ord('D'), ids[2]),
            (wx.ACCEL_CTRL, ord('F'), ids[3]),
            (wx.ACCEL_CTRL, ord('G'), ids[4]),
            (wx.ACCEL_CTRL, ord('O'), ids[5]),
            (wx.ACCEL_CTRL, ord('I'), ids[6]),
        ]))

    # ANCLAJE_INICIO: PAGINAS_VIRTUALES
    # 1800 caracteres por página virtual — aproxima mejor las páginas reales
    # de un libro de bolsillo estándar (~250 palabras × 7 chars promedio).
    _CHARS_POR_PAGINA = 1800

    @staticmethod
    def _longitud_normalizada(texto: str) -> int:
        """
        Devuelve la longitud del texto tras colapsar espacios en blanco
        masivos procedentes del EPUB (tabuladores, saltos dobles, etc.)
        para que el conteo de páginas virtuales sea más fiel al libro real.
        """
        import re
        texto = re.sub(r'\t', ' ', texto)
        texto = re.sub(r' {2,}', ' ', texto)
        texto = re.sub(r'\n{3,}', '\n\n', texto)
        return len(texto)

    def _calcular_paginas(self):
        """
        Devuelve (pag_cap, total_cap, pag_libro, total_libro) basándose en
        bloques virtuales de _CHARS_POR_PAGINA caracteres normalizados.
        Retorna (0, 0, 0, 0) si no hay texto cargado.
        """
        if not self.longitud_texto:
            return 0, 0, 0, 0

        pos_cursor = self.txt_contenido.GetInsertionPoint()
        texto_completo = self.txt_contenido.GetValue()
        long_norm = self._longitud_normalizada(texto_completo)

        total_libro = max(1, (long_norm + self._CHARS_POR_PAGINA - 1) // self._CHARS_POR_PAGINA)
        pag_libro = int(pos_cursor / max(1, self.longitud_texto) * long_norm) // self._CHARS_POR_PAGINA + 1
        pag_libro = min(pag_libro, total_libro)

        inicio_cap = 0
        fin_cap = self.longitud_texto
        posiciones_ordenadas = sorted(self.posiciones_capitulos.values())
        for i, pos in enumerate(posiciones_ordenadas):
            if pos <= pos_cursor:
                inicio_cap = pos
                fin_cap = posiciones_ordenadas[i + 1] if i + 1 < len(posiciones_ordenadas) else self.longitud_texto

        texto_cap = texto_completo[inicio_cap:fin_cap]
        long_cap_norm = self._longitud_normalizada(texto_cap)
        total_cap = max(1, (long_cap_norm + self._CHARS_POR_PAGINA - 1) // self._CHARS_POR_PAGINA)
        pos_en_cap = pos_cursor - inicio_cap
        pag_cap = int(pos_en_cap / max(1, fin_cap - inicio_cap) * long_cap_norm) // self._CHARS_POR_PAGINA + 1
        pag_cap = min(pag_cap, total_cap)

        return pag_cap, total_cap, pag_libro, total_libro

    def anunciar_pagina_actual(self):
        """
        Ctrl+I: verbaliza la posición de lectura con accessible_output3, sin
        mover el foco en ningún momento (antes usaba el patrón _anunciador,
        que le hacía anunciar a NVDA el rol del control oculto — "edición,
        solo lectura" — en cada pulsación, como si saltara un diálogo).
        """
        if not self.longitud_texto:
            return
        pag_cap, total_cap, pag_libro, total_libro = self._calcular_paginas()
        texto = (
            f"Página {pag_cap} de {total_cap} del capítulo. "
            f"Página {pag_libro} de {total_libro} del libro."
        )
        self.lbl_progreso.SetLabel(texto)
        voz.hablar(texto)
    # ANCLAJE_FIN: PAGINAS_VIRTUALES

    # ANCLAJE_INICIO: SLIDER_VELOCIDAD_SEMANTICO
    def _al_slider_velocidad_cambio(self, evento):
        """
        Actualiza la etiqueta con el multiplicador real en modo "por puntos".
        Usa _etiqueta_multiplicador(), la misma fórmula que aplica realmente
        el motor de voz — nunca una tabla aparte que pueda desincronizarse.
        """
        ruta = ruta_config("ajustes.json")
        escala = "porcentaje"
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                escala = json.load(f).get("escala_velocidad", "porcentaje")
        except Exception:
            pass
        if escala != "multiplicador":
            evento.Skip()
            return
        val = self.deslizador_velocidad.GetValue()
        etiqueta = self._etiqueta_multiplicador(val)
        self.deslizador_velocidad.SetHelpText(f"Velocidad: {etiqueta}")
        self.lbl_velocidad.SetLabel(f"Velocidad ({etiqueta}):")
        evento.Skip()
    # ANCLAJE_FIN: SLIDER_VELOCIDAD_SEMANTICO
    # ANCLAJE_FIN: CONFIGURACION_ATAJOS_TECLADO

    def _aplicar_estilos_ricos(self):
        """
        Aplica negrita, cursiva y subrayado al TextCtrl según los spans del EPUB,
        más negrita exacta en los encabezados h1-h6.
        Se ejecuta en un hilo de fondo para no bloquear la UI; las llamadas a
        SetStyle() se envían al hilo principal con wx.CallAfter al final.
        """
        if not self.spans_estilo and not self.posiciones_encabezados:
            return
        # Capturar datos en el hilo principal antes de lanzar el hilo
        texto = self.txt_contenido.GetValue()
        spans = list(self.spans_estilo)
        encabezados = list(self.posiciones_encabezados)
        longitud = len(texto)
        if not texto:
            return
        threading.Thread(
            target=self._calcular_operaciones_estilo,
            args=(texto, spans, encabezados, longitud),
            daemon=True,
        ).start()

    def _calcular_operaciones_estilo(self, texto, spans, encabezados, longitud):
        """
        Hilo de fondo: calcula los rangos exactos de cada span buscando su texto
        en el contenido final del TextCtrl, luego delega la aplicación al hilo UI.

        Búsqueda secuencial: como los spans están en orden de documento y el texto
        también, avanzamos 'pos_busqueda' solo hacia delante para ser O(n) en total.
        Se usa solo los primeros 40 caracteres del span como aguja para robustez
        frente a ligeras diferencias de normalización (espacios, guiones, etc.).
        """
        operaciones = []  # [(inicio, fin, frozenset_estilos)]
        pos_busqueda = 0

        for span in spans:
            texto_span = span['texto']
            cerca_de   = span.get('cerca_de', 0)
            estilos    = span['estilos']
            if len(texto_span) < 3:
                continue

            aguja = texto_span[:40]
            # Buscar desde max(pos_busqueda, cerca_de-100) para manejar
            # pequeños desfases de normalización sin retroceder mucho
            desde = max(pos_busqueda, cerca_de - 100)
            pos = texto.find(aguja, desde)
            if pos == -1:
                # Reintento con ventana más amplia (por si limpiar_lectura desplazó)
                pos = texto.find(aguja, max(0, cerca_de - 500))
            if pos >= 0:
                fin = min(pos + len(texto_span), longitud)
                operaciones.append((pos, fin, estilos))
                pos_busqueda = pos  # avanzar sin saltar

        # Encabezados: posición exacta conocida → negrita sin búsqueda
        for enc in encabezados:
            pos = enc['pos']
            fin = min(pos + len(enc['texto']), longitud)
            if fin > pos:
                operaciones.append((pos, fin, frozenset({'negrita'})))

        if operaciones:
            wx.CallAfter(self._aplicar_operaciones_estilo, operaciones)

    def _aplicar_operaciones_estilo(self, operaciones):
        """
        Hilo principal: aplica SetStyle() para todos los rangos calculados.
        Freeze/Thaw agrupa los redraws en una sola pasada, igual que Bookworm.
        """
        _cache = {}

        def _attr(estilos):
            if estilos not in _cache:
                font = wx.Font(
                    wx.NORMAL_FONT.GetPointSize(),
                    wx.FONTFAMILY_DEFAULT,
                    wx.FONTSTYLE_ITALIC if 'cursiva' in estilos else wx.FONTSTYLE_NORMAL,
                    wx.FONTWEIGHT_BOLD  if 'negrita' in estilos else wx.FONTWEIGHT_NORMAL,
                )
                a = wx.TextAttr()
                a.SetFont(font)
                if 'subrayado' in estilos:
                    a.SetFontUnderlined(True)
                _cache[estilos] = a
            return _cache[estilos]

        self.txt_contenido.Freeze()
        try:
            for inicio, fin, estilos in operaciones:
                try:
                    self.txt_contenido.SetStyle(inicio, fin, _attr(estilos))
                except Exception:
                    pass
        finally:
            self.txt_contenido.Thaw()

