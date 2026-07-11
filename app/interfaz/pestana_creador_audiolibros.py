import os
import json
import logging

import wx

from app.config_rutas import ruta_config

logger = logging.getLogger(__name__)


# ANCLAJE_INICIO: PESTANA_CREADOR_AUDIOLIBROS
class PestanaCreadorAudiolibros(wx.Panel):
    """
    Pestaña independiente del Creador de Audiolibros (Fase B de la
    planificación v3.0). Exportación de un libro de la Biblioteca a MP3,
    completo o por capítulos, con su propio control de velocidad/volumen
    y de presupuesto de cuota.

    Este archivo contiene únicamente la maqueta accesible (esqueleto
    visual): construcción de controles, habilitado/deshabilitado según
    haya o no libro cargado, y la lista de capítulos. El cálculo real de
    presupuesto y los hilos de exportación (grabador_audio.py) se
    conectan en un paso posterior.

    Flujo de entrada único: esta pestaña nunca abre su propio selector de
    archivos. Solo recibe libros ya indexados en biblioteca.db a través
    de cargar_libro(), llamado desde el menú contextual «Enviar a Creador
    de Audiolibros» de la pestaña Biblioteca. Ctrl+O aquí no abre ningún
    diálogo: anuncia por voz que hay que ir a Biblioteca.
    """

    ESTADO_PENDIENTE = "Pendiente"
    ESTADO_COMPLETADO = "Completado"
    ESTADO_SIN_CUOTA = "Pendiente (sin cuota)"

    def __init__(self, padre):
        super().__init__(padre)

        self.libro_actual = None   # dict con id/titulo/autor/formato/ruta_archivo
        self.voz_actual = None     # dict de la voz por defecto (favorita o local)

        self._construir_interfaz()
        self._configurar_atajos()
        self._deshabilitar_controles()

        wx.CallAfter(self._cargar_voz_por_defecto)

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #

    def _construir_interfaz(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Información del libro cargado ───────────────────────────────
        box_libro = wx.StaticBox(self, label="Libro")
        sz_libro = wx.StaticBoxSizer(box_libro, wx.VERTICAL)
        self.lbl_libro = wx.StaticText(
            self,
            label=(
                "Ningún libro cargado. Ve a Biblioteca (Ctrl+1) y usa "
                "«Enviar a Creador de Audiolibros» sobre el libro que quieras exportar."
            ),
        )
        sz_libro.Add(self.lbl_libro, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(sz_libro, 0, wx.EXPAND | wx.ALL, 8)

        # ── Modo de exportación ──────────────────────────────────────────
        hbox_modo = wx.BoxSizer(wx.HORIZONTAL)
        lbl_modo = wx.StaticText(self, label="Modo de exportación:")
        self.combo_modo = wx.Choice(self, choices=["Libro completo", "Por capítulos"])
        self.combo_modo.SetSelection(0)
        self.combo_modo.SetHelpText(
            "Libro completo genera un único archivo MP3 con todo el libro. "
            "Por capítulos genera un MP3 independiente por cada capítulo, numerado."
        )
        self.combo_modo.Bind(wx.EVT_CHOICE, self.al_cambiar_modo)
        hbox_modo.Add(lbl_modo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        hbox_modo.Add(self.combo_modo, 1)
        sizer.Add(hbox_modo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Voz por defecto ───────────────────────────────────────────────
        self.lbl_voz = wx.StaticText(self, label="Voz: comprobando favoritas...")
        self.lbl_voz.SetHelpText(
            "Voz que se usará para la exportación: la primera voz favorita marcada "
            "en Ajustes, o la voz local si no hay ninguna favorita guardada."
        )
        sizer.Add(self.lbl_voz, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Presupuesto / exportación ────────────────────────────────────
        hbox_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_calcular = wx.Button(self, label="Calcular presupuesto")
        self.btn_calcular.SetHelpText(
            "Cuenta los caracteres del libro (o de los capítulos) y comprueba si caben "
            "en la cuota configurada, sin generar audio."
        )
        self.btn_calcular.Bind(wx.EVT_BUTTON, self.al_calcular_presupuesto)
        hbox_botones.Add(self.btn_calcular, 0, wx.RIGHT, 8)

        self.btn_iniciar = wx.Button(self, label="Iniciar exportación")
        self.btn_iniciar.SetHelpText(
            "Empieza a generar el audiolibro. Se habilita después de calcular el "
            "presupuesto con la configuración actual."
        )
        self.btn_iniciar.Bind(wx.EVT_BUTTON, self.al_iniciar_exportacion)
        self.btn_iniciar.Enable(False)
        hbox_botones.Add(self.btn_iniciar, 0)

        sizer.Add(hbox_botones, 0, wx.EXPAND | wx.ALL, 8)

        # ── Velocidad ─────────────────────────────────────────────────────
        sz_vel = wx.BoxSizer(wx.HORIZONTAL)
        lbl_vel = wx.StaticText(self, label="Velocidad:")
        self.deslizador_velocidad = wx.Slider(self, value=50, minValue=0, maxValue=100)
        self.deslizador_velocidad.SetName("Velocidad de exportación")
        self.deslizador_velocidad.SetHelpText(
            "Velocidad de locución de la voz. 0 es la más lenta, 100 la más rápida. "
            "Flechas: ±1. RePág/AvPág: ±5."
        )
        self.deslizador_velocidad.Bind(wx.EVT_SLIDER, self._al_cambiar_velocidad)
        self.deslizador_velocidad.Bind(wx.EVT_KEY_DOWN, self._al_tecla_velocidad)
        sz_vel.Add(lbl_vel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_vel.Add(self.deslizador_velocidad, 1)
        sizer.Add(sz_vel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Volumen ───────────────────────────────────────────────────────
        sz_vol = wx.BoxSizer(wx.HORIZONTAL)
        lbl_vol = wx.StaticText(self, label="Volumen:")
        self.deslizador_volumen = wx.Slider(self, value=100, minValue=0, maxValue=100)
        self.deslizador_volumen.SetName("Volumen de exportación")
        self.deslizador_volumen.SetHelpText(
            "Volumen del audio generado. 0 es silencio, 100 es volumen máximo. "
            "Flechas: ±1. RePág/AvPág: ±5."
        )
        self.deslizador_volumen.Bind(wx.EVT_SLIDER, self._al_cambiar_volumen)
        self.deslizador_volumen.Bind(wx.EVT_KEY_DOWN, self._al_tecla_volumen)
        sz_vol.Add(lbl_vol, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_vol.Add(self.deslizador_volumen, 1)
        sizer.Add(sz_vol, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Lista de capítulos (solo visible en modo "Por capítulos") ────
        box_caps = wx.StaticBox(self, label="Capítulos")
        self.sz_caps = wx.StaticBoxSizer(box_caps, wx.VERTICAL)
        self.lista_capitulos = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES
        )
        self.lista_capitulos.InsertColumn(0, "Nº", width=50)
        self.lista_capitulos.InsertColumn(1, "Título", width=380)
        self.lista_capitulos.InsertColumn(2, "Estado", width=180)
        self.lista_capitulos.SetHelpText(
            "Estado de cada capítulo durante la exportación por capítulos: "
            "pendiente, completado o pendiente por falta de cuota."
        )
        self.sz_caps.Add(self.lista_capitulos, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.sz_caps, 1, wx.EXPAND | wx.ALL, 8)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador).
        self._anunciador = wx.TextCtrl(self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1))
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())
        sizer.Add(self._anunciador, 0, wx.LEFT, 0)

        self.SetSizer(sizer)

        # Oculta por defecto: el modo inicial es "Libro completo".
        self.sz_caps.ShowItems(False)
        self.Layout()

    def _configurar_atajos(self):
        # Ctrl+O se gestiona a nivel de VentanaPrincipal (apertura universal
        # contextual) y llama a al_ctrl_o() desde allí — no se duplica aquí.
        pass

    # ------------------------------------------------------------------ #
    # Propiedades para Tab cíclico (usadas por ventana_principal.py)
    # ------------------------------------------------------------------ #

    @property
    def primer_control(self):
        return self.combo_modo

    @property
    def ultimo_control(self):
        return self.lista_capitulos if self.lista_capitulos.IsShown() else self.deslizador_volumen

    # ------------------------------------------------------------------ #
    # Habilitado / deshabilitado según haya libro cargado
    # ------------------------------------------------------------------ #

    def _controles_dependientes_de_libro(self):
        return (
            self.combo_modo,
            self.btn_calcular,
            self.deslizador_velocidad,
            self.deslizador_volumen,
            self.lista_capitulos,
        )

    def _deshabilitar_controles(self):
        for control in self._controles_dependientes_de_libro():
            control.Enable(False)
        self.btn_iniciar.Enable(False)

    def _habilitar_controles(self):
        for control in self._controles_dependientes_de_libro():
            control.Enable(True)
        # btn_iniciar se queda deshabilitado hasta calcular presupuesto.

    # ------------------------------------------------------------------ #
    # Carga de libro desde Biblioteca (único punto de entrada)
    # ------------------------------------------------------------------ #

    def cargar_libro(self, datos_libro: dict):
        """
        Único punto de entrada de esta pestaña. Lo llama la pestaña
        Biblioteca desde «Enviar a Creador de Audiolibros» con un dict
        con, al menos: id, titulo, autor, formato, ruta_archivo.
        """
        self.libro_actual = datos_libro
        titulo = datos_libro.get("titulo", "(sin título)")
        autor = datos_libro.get("autor", "")
        formato = datos_libro.get("formato", "").upper()

        descripcion = f"{titulo}" + (f" — {autor}" if autor else "") + (f" ({formato})" if formato else "")
        self.lbl_libro.SetLabel(descripcion)

        self._habilitar_controles()
        self.btn_iniciar.Enable(False)

        self._poblar_lista_capitulos([])
        self.Layout()

    def al_ctrl_o(self, evento=None):
        """
        Ctrl+O contextual en esta pestaña: nunca abre un selector propio.
        Esta pestaña solo trabaja con libros ya indexados en la Biblioteca
        (sección 3.1 de la planificación), así que se limita a indicar por
        voz el camino correcto, sin duplicar el buscador ya existente allí.
        """
        self._anunciar(
            "Esta pestaña solo trabaja con libros de la Biblioteca. "
            "Ve a Biblioteca con Ctrl+1 y usa «Enviar a Creador de Audiolibros» "
            "sobre el libro que quieras exportar."
        )

    # ------------------------------------------------------------------ #
    # Modo de exportación: muestra/oculta la lista de capítulos
    # ------------------------------------------------------------------ #

    def al_cambiar_modo(self, evento):
        por_capitulos = self.combo_modo.GetSelection() == 1
        self.sz_caps.ShowItems(por_capitulos)
        self.Layout()

    # ------------------------------------------------------------------ #
    # Lista de capítulos: inserción masiva protegida y actualización silenciosa
    # ------------------------------------------------------------------ #

    def _poblar_lista_capitulos(self, capitulos: list):
        """
        capitulos: lista de tuplas (titulo_capitulo, texto_capitulo) o dicts
        con clave "titulo". Inserción protegida con Freeze()/Thaw() para no
        parpadear ni saturar a NVDA con una fila por evento.
        """
        self.lista_capitulos.Freeze()
        try:
            self.lista_capitulos.DeleteAllItems()
            for i, capitulo in enumerate(capitulos):
                titulo_cap = capitulo[0] if isinstance(capitulo, tuple) else capitulo.get("titulo", "")
                pos = self.lista_capitulos.InsertItem(i, str(i + 1))
                self.lista_capitulos.SetItem(pos, 1, titulo_cap)
                self.lista_capitulos.SetItem(pos, 2, self.ESTADO_PENDIENTE)
        finally:
            self.lista_capitulos.Thaw()

    def _actualizar_estado_capitulo(self, indice: int, estado: str):
        """
        Actualiza solo la celda de estado de una fila ya insertada.
        SetItem() no mueve el foco ni la selección: no dispara un evento de
        accesibilidad por cada actualización, así que el progreso en
        segundo plano no satura a NVDA con anuncios repetidos. El progreso
        audible pasa por wx.Gauge y anuncios de hito, no por esta lista.
        """
        if 0 <= indice < self.lista_capitulos.GetItemCount():
            self.lista_capitulos.SetItem(indice, 2, estado)

    # ------------------------------------------------------------------ #
    # Velocidad / volumen: pasos de 1 (flechas) y 5 (RePág/AvPág)
    # ------------------------------------------------------------------ #

    def _al_cambiar_velocidad(self, evento):
        pass  # El valor se lee directamente del deslizador al exportar.

    def _al_cambiar_volumen(self, evento):
        pass  # El valor se lee directamente del deslizador al exportar.

    def _al_tecla_velocidad(self, evento):
        self._aplicar_salto_slider(evento, self.deslizador_velocidad)

    def _al_tecla_volumen(self, evento):
        self._aplicar_salto_slider(evento, self.deslizador_volumen)

    def _aplicar_salto_slider(self, evento, slider):
        key = evento.GetKeyCode()
        if key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            delta = -5 if key == wx.WXK_PAGEUP else 5
            nuevo = max(slider.GetMin(), min(slider.GetMax(), slider.GetValue() + delta))
            slider.SetValue(nuevo)
        else:
            evento.Skip()

    # ------------------------------------------------------------------ #
    # Voz por defecto: primera favorita guardada, o voz local como respaldo
    # ------------------------------------------------------------------ #

    def _cargar_voz_por_defecto(self):
        try:
            self.voz_actual = self._buscar_primera_voz_favorita()
        except Exception:
            logger.exception("[PestanaCreadorAudiolibros] Error al cargar la voz por defecto")
            self.voz_actual = None

        if self.voz_actual:
            nombre = self.voz_actual.get("nombre", "")
            proveedor = self.voz_actual.get("proveedor_id", "")
            self.lbl_voz.SetLabel(f"Voz: {nombre} ({proveedor})")
        else:
            self.lbl_voz.SetLabel("Voz: local (SAPI5) — no hay ninguna voz marcada como favorita.")

    def _buscar_primera_voz_favorita(self):
        ruta_favs = ruta_config("voces_favoritas.json")
        if not os.path.exists(ruta_favs):
            return None
        with open(ruta_favs, "r", encoding="utf-8") as f:
            favoritos = json.load(f)
        if not favoritos:
            return None

        from app.motor.cliente_nube_voces import GestorVoces
        todas = GestorVoces().obtener_todas_las_voces()
        for proveedor_id, voces in todas.items():
            for voz in voces:
                if voz.get("id") in favoritos:
                    entrada = dict(voz)
                    entrada["proveedor_id"] = proveedor_id
                    return entrada
        return None

    # ------------------------------------------------------------------ #
    # Presupuesto / exportación — cableado real pendiente del siguiente paso
    # ------------------------------------------------------------------ #

    def al_calcular_presupuesto(self, evento):
        # La extracción de texto limpio del libro (limpiador_lectura.py /
        # limpiador_pdf.py) y el hilo de cálculo silencioso sobre
        # GrabadorAudio.calcular_presupuesto() se conectan en el siguiente
        # paso. Aquí solo existe la maqueta accesible del control.
        self._anunciar("El cálculo de presupuesto se conectará en el siguiente paso.")

    def al_iniciar_exportacion(self, evento):
        # Cableado real (hilo de exportación sobre grabador_audio.py,
        # diálogo de proveedor alternativo si falta cuota) pendiente.
        self._anunciar("La exportación se conectará en un paso posterior.")

    # ------------------------------------------------------------------ #
    # Anuncios de accesibilidad (patrón _anunciador)
    # ------------------------------------------------------------------ #

    def _anunciar(self, texto):
        control_previo = wx.Window.FindFocus()
        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()
        wx.CallLater(300, lambda: control_previo.SetFocus() if control_previo else None)
# ANCLAJE_FIN: PESTANA_CREADOR_AUDIOLIBROS
