# ANCLAJE_INICIO: DEPENDENCIAS_LECTURA
import wx
import os
import json
import time
from app.motor.gestor_epub import extraer_datos_epub
from app.motor.reproductor_voz import ReproductorVoz
from app.interfaz.dialogos import DialogoMarcadores
from app.config_rutas import ruta_config, CONFIG_DIR
from app.motor.reproductor_sonidos import reproducir, LIST_NAV
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
_PROVEEDORES = {"polly": "Amazon Polly", "elevenlabs": "ElevenLabs", "azure": "Azure"}


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
        self.marcadores = {}       
        self.longitud_texto = 0
        
        self.segundos_salto = 10
        self.cargar_config_salto()
        
        self.pos_inicio_fragmento = 0
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
        self.txt_contenido.SetValue("Bienvenida a Epub TTS Accesible. Pulsa Ctrl+A para abrir un libro EPUB.")
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

        self.btn_atras = wx.Button(self, label=f"Atrás {self.segundos_salto}s")
        self.btn_reproducir = wx.Button(self, label="Reproducir (Ctrl+P)")
        self.btn_adelante = wx.Button(self, label=f"Adelante {self.segundos_salto}s")
        self.btn_detener = wx.Button(self, label="Detener (Ctrl+D)")
        
        self.btn_reproducir.Bind(wx.EVT_BUTTON, self.al_alternar_reproduccion)
        self.btn_detener.Bind(wx.EVT_BUTTON, self.al_detener)
        self.btn_atras.Bind(wx.EVT_BUTTON, self.al_saltar_atras)
        self.btn_adelante.Bind(wx.EVT_BUTTON, self.al_saltar_adelante)

        self.lbl_velocidad = wx.StaticText(self, label="Velocidad de lectura:")
        self.deslizador_velocidad = wx.Slider(self, value=50, minValue=0, maxValue=100)
        self.deslizador_velocidad.SetName("Velocidad de lectura")
        self.deslizador_velocidad.SetHelpText(
            "Velocidad de lectura de la voz. 0 es la más lenta, 100 la más rápida. "
            "Usa las flechas Izquierda y Derecha para ajustar."
        )
        self.deslizador_velocidad.Bind(wx.EVT_SLIDER, self.al_cambiar_velocidad)

        self.lbl_volumen = wx.StaticText(self, label="Volumen:")
        self.deslizador_volumen = wx.Slider(self, value=100, minValue=0, maxValue=100)
        self.deslizador_volumen.SetName("Volumen de lectura")
        self.deslizador_volumen.SetHelpText(
            "Volumen del audio de lectura. 0 es silencio, 100 es volumen máximo. "
            "Usa las flechas Izquierda y Derecha para ajustar."
        )
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
                    # Restaurar sliders solo si los widgets ya están inicializados
                    if hasattr(self, 'deslizador_velocidad'):
                        vel = int(conf.get("velocidad_lectura", 50))
                        vol = int(conf.get("volumen_lectura", 100))
                        self.deslizador_velocidad.SetValue(vel)
                        self.deslizador_volumen.SetValue(vol)
                        self.reproductor.fijar_velocidad(vel)
                        self.reproductor.fijar_volumen(vol)
        except Exception as e:
            print(f"[Aviso] No se pudo leer la configuración de salto: {e}")
            self.segundos_salto = 10

    def al_cambiar_pestana_padre(self, event):
        if event.GetSelection() == 0:
            self.cargar_config_salto()
            self.btn_atras.SetLabel(f"Atrás {self.segundos_salto}s")
            self.btn_adelante.SetLabel(f"Adelante {self.segundos_salto}s")
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

        # Carga de voces locales SAPI5
        try:
            if hasattr(self.reproductor, 'cliente_local'):
                voces_locales = self.reproductor.cliente_local.obtener_voces()
                for v in voces_locales:
                    nombre_mostrar = f"[Local] {v['nombre']}"
                    voces_para_combo.append((nombre_mostrar, v))
        except Exception as e:
            print(f"[Aviso] No se pudieron cargar las voces locales SAPI5: {e}")

        # Carga de voces neuronales favoritas
        ruta_favs = ruta_config("voces_favoritas.json")
        ruta_todas = ruta_config("voces_disponibles.json")

        ids_favoritos = []
        if os.path.exists(ruta_favs):
            try:
                with open(ruta_favs, 'r', encoding='utf-8') as f:
                    ids_favoritos = json.load(f)
            except Exception as e:
                print(f"[Aviso] No se pudo leer voces_favoritas.json: {e}")
                ids_favoritos = []

        if ids_favoritos and os.path.exists(ruta_todas):
            try:
                with open(ruta_todas, 'r', encoding='utf-8') as f:
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
            # Al pausar, cancelar la cola pendiente (las voces neuronales requieren
            # reenviar el texto desde la nueva posición al reanudar)
            self._cola_lectura = []
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
                if 'azure' in prov or 'eleven' in prov or 'polly' in prov:
                    es_voz_neuronal = True

            if es_voz_neuronal:
                # Voces neuronales: dividir en fragmentos y reproducir en cola continua
                self._cola_lectura = self._dividir_en_fragmentos(fragmento_total, pos_actual)
                self._idx_fragmento_actual = 0
                self._reproducir_siguiente_fragmento()
            else:
                # Voz local SAPI5: gestiona su propia cola internamente, enviar todo el texto
                self._cola_lectura = []
                self._tiempo_inicio_frag = time.time()
                self._longitud_frag_actual = len(fragmento_total)
                self.reproductor.cargar_texto(fragmento_total)

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
        MAX_CHARS = 200
        VENTANA = 200  # ventana hacia atrás para buscar puntos de corte naturales
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
            # Saltar fragmento vacío y continuar con el siguiente
            self._idx_fragmento_actual += 1
            self._reproducir_siguiente_fragmento()
            return

        self.pos_inicio_fragmento = pos_inicio
        self._tiempo_inicio_frag = time.time()
        self._longitud_frag_actual = len(texto_frag)
        # Resetear flag de precarga para este nuevo fragmento
        self._precarga_solicitada = False

        # Mover el cursor al inicio del fragmento para que NVDA sepa dónde empieza
        self.txt_contenido.SetInsertionPoint(pos_inicio)
        self.txt_contenido.ShowPosition(pos_inicio)

        self.reproductor.cargar_texto(texto_frag, callback_completado=self._al_fragmento_completado)

    def _al_fragmento_completado(self):
        """Callback invocado por ReproductorVoz cuando termina un fragmento neuronal."""
        self._idx_fragmento_actual += 1
        if self._cola_lectura and self._idx_fragmento_actual < len(self._cola_lectura):
            self._reproducir_siguiente_fragmento()

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
        elif estado == 'pausado':
            if self.btn_reproducir.GetLabel() != "Reanudar (Ctrl+P)":
                self.btn_reproducir.SetLabel("Reanudar (Ctrl+P)")
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
        from app.interfaz.dialogos import DialogoMarcadores
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

    def iniciar_ir_a_porcentaje(self): 
        dlg = wx.TextEntryDialog(self, "Porcentaje (0-100):", "Ir a")
        if dlg.ShowModal() == wx.ID_OK:
            val = dlg.GetValue()
            if val.isdigit():
                self.deslizador_progreso.SetValue(int(val))
                self.al_buscar_usuario(None)
        dlg.Destroy()

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
    # ANCLAJE_FIN: NAVEGACION_TEXTO_Y_SALTOS

    def al_cargar_libro(self, evento):
        """Abre el explorador de archivos para seleccionar un libro EPUB."""
        with wx.FileDialog(self, "Seleccionar EPUB", wildcard="Archivos EPUB (*.epub)|*.epub", style=wx.FD_OPEN) as dlg:
            if dlg.ShowModal() == wx.ID_OK: 
                self.cargar_epub_desde_ruta(dlg.GetPath())

    # ANCLAJE_INICIO: GESTION_DATOS_LIBRO
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

            # Registrar en el historial de libros recientes de VentanaPrincipal
            try:
                ventana = self.padre_notebook.GetParent()
                if hasattr(ventana, 'agregar_a_recientes'):
                    ventana.agregar_a_recientes(ruta)
            except Exception:
                pass

        except Exception as e:
            wx.MessageBox(f"Se ha producido un error técnico al intentar procesar el libro EPUB.\n\nDetalle: {e}", "Error al cargar el libro")

    def _construir_arbol_indice(self, padre, nodos):
        for n in nodos:
            item = self.arbol_indice.AppendItem(padre, n['title'])
            if n['children']: self._construir_arbol_indice(item, n['children'])

    def al_tecla_volumen(self, e): e.Skip()
        
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
    # ANCLAJE_FIN: CONFIGURACION_ATAJOS_TECLADO