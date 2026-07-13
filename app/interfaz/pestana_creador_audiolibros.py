import os
import json
import logging
import threading

import wx

from app.config_rutas import ruta_config
from app.motor.reproductor_sonidos import reproducir, REC_START, SUCCESS, ERROR

logger = logging.getLogger(__name__)


class _TextoInformativoAccesible(wx.TextCtrl):
    """
    TextCtrl de solo lectura (wx.TE_READONLY) que sigue siendo alcanzable
    con Tab. Comprobado con el Visor de voz de NVDA: wx excluye del orden
    de tabulación real a los TextCtrl de solo lectura en esta pestaña —
    ni MoveAfterInTabOrder lo corrige, porque no es un problema de orden,
    es que wx no los trata como parada de teclado en absoluto. Se
    sobreescribe AcceptsFocusFromKeyboard() para forzarlo, igual que
    cualquier campo de solo lectura de una aplicación accesible.
    """

    def AcceptsFocusFromKeyboard(self):
        return True


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

        self._calculando = False
        self._exportando = False
        self._resultado_presupuesto = None   # dict: modo_capitulos/capitulos/texto_completo/fronteras/presupuesto
        self._grabador = None
        self._gestor_biblioteca = None

        self._construir_interfaz()
        self._configurar_atajos()
        self._deshabilitar_controles()

        wx.CallAfter(self._cargar_voz_por_defecto)

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #

    def _construir_interfaz(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador).
        # Creado aquí, al principio, para que no le quede ningún StaticBox con
        # texto justo delante en el orden de creación/tabulación — MSAA puede
        # "heredar" el título del grupo más cercano como nombre accesible de
        # un control sin nombre propio si se crea justo después de uno.
        self._anunciador = _TextoInformativoAccesible(self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1))
        self._anunciador.SetName("Anuncios")
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())
        sizer.Add(self._anunciador, 0, wx.LEFT, 0)

        # ── Información del libro cargado ───────────────────────────────
        # TextCtrl de solo lectura (no wx.StaticText): un StaticText suelto,
        # sin un control focalizable justo después, nunca entra en el orden
        # de tabulación y el lector de pantalla no lo alcanza salvo con el
        # navegador de objetos. Mismo patrón que txt_ruta en pestana_grabacion.py.
        box_libro = wx.StaticBox(self, label="Libro")
        sz_libro = wx.StaticBoxSizer(box_libro, wx.VERTICAL)
        lbl_libro_caption = wx.StaticText(self, label="Libro cargado:")
        self.txt_libro = _TextoInformativoAccesible(self, style=wx.TE_READONLY)
        self.txt_libro.SetValue(
            "Ningún libro cargado. Ve a Biblioteca (Ctrl+1) y usa "
            "«Enviar a Creador de Audiolibros» sobre el libro que quieras exportar."
        )
        sz_libro.Add(lbl_libro_caption, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        sz_libro.Add(self.txt_libro, 0, wx.EXPAND | wx.ALL, 5)

        self.btn_eliminar_libro = wx.Button(self, label="Eliminar libro cargado")
        self.btn_eliminar_libro.SetHelpText(
            "Quita el libro actual de esta pestaña, por si se cargó el libro "
            "equivocado, sin afectar a la Biblioteca ni al archivo original."
        )
        self.btn_eliminar_libro.Bind(wx.EVT_BUTTON, self.al_eliminar_libro)
        self.btn_eliminar_libro.Enable(False)
        sz_libro.Add(self.btn_eliminar_libro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

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
        lbl_voz_caption = wx.StaticText(self, label="Voz por defecto:")
        self.txt_voz = _TextoInformativoAccesible(self, style=wx.TE_READONLY)
        self.txt_voz.SetValue("Comprobando favoritas...")
        self.txt_voz.SetHelpText(
            "Voz que se usará para la exportación: la primera voz favorita marcada "
            "en Ajustes, o la voz local si no hay ninguna favorita guardada."
        )
        sizer.Add(lbl_voz_caption, 0, wx.LEFT | wx.RIGHT, 8)
        sizer.Add(self.txt_voz, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.btn_elegir_voz = wx.Button(self, label="Elegir voz...")
        self.btn_elegir_voz.SetHelpText(
            "Abre un diálogo para elegir manualmente el proveedor y la voz de "
            "exportación, en vez de usar siempre la primera voz favorita."
        )
        self.btn_elegir_voz.Bind(wx.EVT_BUTTON, self.al_elegir_voz)
        sizer.Add(self.btn_elegir_voz, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

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
        hbox_botones.Add(self.btn_iniciar, 0, wx.RIGHT, 8)

        self.btn_abortar = wx.Button(self, label="Abortar exportación")
        self.btn_abortar.SetHelpText(
            "Detiene la exportación en curso. Lo ya generado hasta ese punto se "
            "conserva y queda registrado como pendiente para retomarlo más tarde."
        )
        self.btn_abortar.Bind(wx.EVT_BUTTON, self.al_abortar_exportacion)
        self.btn_abortar.Enable(False)
        hbox_botones.Add(self.btn_abortar, 0)

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

        # ── Progreso de la exportación ────────────────────────────────────
        box_prog = wx.StaticBox(self, label="Progreso")
        sz_prog = wx.StaticBoxSizer(box_prog, wx.VERTICAL)
        lbl_progreso_caption = wx.StaticText(self, label="Estado:")
        self.txt_progreso = _TextoInformativoAccesible(self, style=wx.TE_READONLY)
        self.txt_progreso.SetValue("Sin exportación en curso.")
        self.gauge = wx.Gauge(self, range=100)
        self.gauge.SetHelpText("Progreso de la exportación actual.")
        sz_prog.Add(lbl_progreso_caption, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        sz_prog.Add(self.txt_progreso, 0, wx.EXPAND | wx.ALL, 5)
        sz_prog.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        sizer.Add(sz_prog, 0, wx.EXPAND | wx.ALL, 8)

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

        self.SetSizer(sizer)

        # Orden de tabulación forzado explícitamente. Confirmado con el
        # Visor de voz de NVDA que, pese a construirse en este mismo orden,
        # el Tab nativo saltaba directo de deslizador_volumen de vuelta a la
        # pestaña sin pasar por txt_libro/txt_voz/txt_progreso/_anunciador
        # (los TextCtrl de solo lectura) ni por lista_capitulos — ninguno
        # deshabilitado ni oculto en ese punto, así que no dependía de
        # nuestra propia lógica de habilitar/deshabilitar. Mismo remedio ya
        # usado en pestana_biblioteca.py (lista_libros.MoveAfterInTabOrder).
        self.txt_libro.MoveAfterInTabOrder(self._anunciador)
        self.btn_eliminar_libro.MoveAfterInTabOrder(self.txt_libro)
        self.combo_modo.MoveAfterInTabOrder(self.btn_eliminar_libro)
        self.txt_voz.MoveAfterInTabOrder(self.combo_modo)
        self.btn_elegir_voz.MoveAfterInTabOrder(self.txt_voz)
        self.btn_calcular.MoveAfterInTabOrder(self.btn_elegir_voz)
        self.btn_iniciar.MoveAfterInTabOrder(self.btn_calcular)
        self.btn_abortar.MoveAfterInTabOrder(self.btn_iniciar)
        self.deslizador_velocidad.MoveAfterInTabOrder(self.btn_abortar)
        self.deslizador_volumen.MoveAfterInTabOrder(self.deslizador_velocidad)
        self.txt_progreso.MoveAfterInTabOrder(self.deslizador_volumen)
        self.lista_capitulos.MoveAfterInTabOrder(self.txt_progreso)

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
        return self.txt_libro

    @property
    def ultimo_control(self):
        return self.lista_capitulos if self.lista_capitulos.IsShown() else self.txt_progreso

    # ------------------------------------------------------------------ #
    # Habilitado / deshabilitado según haya libro cargado
    # ------------------------------------------------------------------ #

    def _controles_dependientes_de_libro(self):
        return (
            self.combo_modo,
            self.btn_calcular,
            self.btn_eliminar_libro,
            self.btn_elegir_voz,
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
        self.txt_libro.SetValue(descripcion)

        self._habilitar_controles()
        self.btn_iniciar.Enable(False)
        self._resultado_presupuesto = None
        self._calculando = False
        self._exportando = False
        self.gauge.SetValue(0)
        self.txt_progreso.SetValue("Sin exportación en curso.")

        self._poblar_lista_capitulos([])
        self.Layout()

        # Anuncio inmediato: sin esto, cargar un libro desde Biblioteca era
        # silencioso para el lector de pantalla — el título quedaba escrito
        # en el campo, pero nadie lo verbalizaba hasta que el usuario lo
        # encontrara a mano.
        self._anunciar(f"Libro cargado en el Creador de Audiolibros: {descripcion}")

    def al_eliminar_libro(self, evento=None):
        """
        Quita el libro actual de esta pestaña (por ejemplo, si se cargó el
        libro equivocado desde Biblioteca), sin tocar la Biblioteca ni el
        archivo original. No tiene efecto si hay una exportación en curso.
        """
        if self._exportando:
            self._anunciar("No se puede eliminar el libro mientras hay una exportación en curso.")
            return

        self.libro_actual = None
        self.voz_actual = None
        self._resultado_presupuesto = None
        self._calculando = False

        self.txt_libro.SetValue(
            "Ningún libro cargado. Ve a Biblioteca (Ctrl+1) y usa "
            "«Enviar a Creador de Audiolibros» sobre el libro que quieras exportar."
        )
        self.txt_voz.SetValue("Comprobando favoritas...")
        self.txt_progreso.SetValue("Sin exportación en curso.")
        self.gauge.SetValue(0)
        self._poblar_lista_capitulos([])
        self._deshabilitar_controles()
        self.Layout()

        self._anunciar("Libro eliminado del Creador de Audiolibros.")
        wx.CallAfter(self._cargar_voz_por_defecto)

    def al_elegir_voz(self, evento=None):
        """
        Abre un diálogo para elegir manualmente proveedor y voz, en vez de
        depender siempre de la primera voz favorita detectada.
        """
        from app.interfaz.dialogo_elegir_voz import DialogoElegirVoz

        dlg = DialogoElegirVoz(self)
        respuesta = dlg.ShowModal()

        if respuesta == wx.ID_OK and dlg.accion == "elegida":
            voz = dict(dlg.voz_elegida)
            voz["proveedor_id"] = dlg.proveedor_elegido
            self.voz_actual = voz
            nombre_proveedor = DialogoElegirVoz._NOMBRES_PROVEEDOR.get(dlg.proveedor_elegido, dlg.proveedor_elegido)
            self.txt_voz.SetValue(f"Voz: {voz.get('nombre', '')} ({nombre_proveedor})")
            self._anunciar(f"Voz seleccionada: {voz.get('nombre', '')}, {nombre_proveedor}.")
            self._resultado_presupuesto = None
            self.btn_iniciar.Enable(False)
        elif respuesta == wx.ID_OK and dlg.accion == "local":
            self.voz_actual = {"proveedor_id": "local", "nombre": "Voz local (SAPI5)"}
            self.txt_voz.SetValue("Voz: local (SAPI5)")
            self._anunciar("Voz seleccionada: local, SAPI5.")
            self._resultado_presupuesto = None
            self.btn_iniciar.Enable(False)

        dlg.Destroy()

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
        # El presupuesto ya calculado corresponde al modo anterior — hay que
        # recalcular antes de poder exportar con el modo nuevo.
        self._resultado_presupuesto = None
        self.btn_iniciar.Enable(False)
        if not por_capitulos:
            self._poblar_lista_capitulos([])
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
            self.txt_voz.SetValue(f"Voz: {nombre} ({proveedor})")
        else:
            self.txt_voz.SetValue("Voz: local (SAPI5) — no hay ninguna voz marcada como favorita.")

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
    # Cálculo de presupuesto (hilo de fondo — extracción + conteo silencioso)
    # ------------------------------------------------------------------ #

    def al_calcular_presupuesto(self, evento):
        if not self.libro_actual or self._calculando or self._exportando:
            return

        formato = self.libro_actual.get("formato", "")
        if formato != "epub":
            reproducir(ERROR)
            self._anunciar(
                "El Creador de Audiolibros todavía solo admite libros EPUB. "
                "El soporte de PDF llegará en un paso posterior."
            )
            return

        self._calculando = True
        self._resultado_presupuesto = None
        self.btn_iniciar.Enable(False)
        self.btn_calcular.Enable(False)
        self.combo_modo.Enable(False)
        self.txt_progreso.SetValue("Calculando presupuesto...")
        self._anunciar("Calculando presupuesto...")

        ruta_archivo = self.libro_actual["ruta_archivo"]
        modo_capitulos = self.combo_modo.GetSelection() == 1
        voz = self.voz_actual or {"proveedor_id": "local", "nombre": "Voz local (SAPI5)"}
        proveedor_id = voz.get("proveedor_id", "local")

        threading.Thread(
            target=self._hilo_calcular_presupuesto,
            args=(ruta_archivo, modo_capitulos, proveedor_id),
            daemon=True,
        ).start()

    def _hilo_calcular_presupuesto(self, ruta_archivo, modo_capitulos, proveedor_id):
        try:
            from app.motor.troceador_epub import TroceadorEpub
            from app.motor.grabador_audio import GrabadorAudio

            troceador = TroceadorEpub()
            troceador.cargar(ruta_archivo)

            if modo_capitulos:
                capitulos = troceador.extraer_capitulos_texto()
                texto_completo = None
                fronteras = None
                texto_para_contar = "".join(texto for _titulo, texto in capitulos)
            else:
                capitulos = None
                texto_completo, fronteras = troceador.extraer_texto_completo_con_fronteras()
                texto_para_contar = texto_completo

            presupuesto = GrabadorAudio().calcular_presupuesto(texto_para_contar, proveedor_id)
        except Exception as e:
            logger.exception("[PestanaCreadorAudiolibros] Error al calcular presupuesto")
            wx.CallAfter(self._al_error_presupuesto, str(e))
            return

        resultado = {
            "modo_capitulos": modo_capitulos,
            "capitulos": capitulos,
            "texto_completo": texto_completo,
            "fronteras": fronteras,
            "presupuesto": presupuesto,
            "proveedor_id": proveedor_id,
        }
        wx.CallAfter(self._al_presupuesto_calculado, resultado)

    def _al_presupuesto_calculado(self, resultado: dict):
        self._calculando = False
        self._resultado_presupuesto = resultado
        self.btn_calcular.Enable(True)
        self.combo_modo.Enable(True)

        if resultado["modo_capitulos"]:
            self._poblar_lista_capitulos(resultado["capitulos"])

        presupuesto = resultado["presupuesto"]
        caracteres = presupuesto["caracteres"]
        cabe = presupuesto["cabe_en_cuota"]
        estado_cuota = "cabe en la cuota actual" if cabe else "NO cabe en la cuota actual del proveedor elegido"
        mensaje = f"Presupuesto calculado: {caracteres} caracteres. Estado: {estado_cuota}."

        self.txt_progreso.SetValue(mensaje)
        self._anunciar(mensaje)
        self.btn_iniciar.Enable(True)

    def _al_error_presupuesto(self, error: str):
        self._calculando = False
        self.btn_calcular.Enable(True)
        self.combo_modo.Enable(True)
        reproducir(ERROR)
        self.txt_progreso.SetValue(f"Error al calcular presupuesto: {error}")
        self._anunciar(f"Error al calcular presupuesto: {error}")

    # ------------------------------------------------------------------ #
    # Exportación (hilo de fondo — un único hilo de exportación a la vez)
    # ------------------------------------------------------------------ #

    def al_iniciar_exportacion(self, evento):
        if not self.libro_actual or self._exportando:
            return
        if not self._resultado_presupuesto:
            self._anunciar("Calcula el presupuesto antes de iniciar la exportación.")
            return

        resultado = self._resultado_presupuesto
        voz = self.voz_actual or {"proveedor_id": "local", "nombre": "Voz local (SAPI5)"}
        velocidad = self.deslizador_velocidad.GetValue()
        volumen = self.deslizador_volumen.GetValue()

        if not resultado["presupuesto"]["cabe_en_cuota"]:
            self._abrir_dialogo_proveedor_alternativo(resultado, voz, velocidad, volumen)
            return

        self._arrancar_exportacion(voz, velocidad, volumen, resultado)

    def _abrir_dialogo_proveedor_alternativo(self, resultado, voz_actual, velocidad, volumen):
        from app.interfaz.dialogo_proveedor_alternativo import DialogoProveedorAlternativo

        if resultado["modo_capitulos"]:
            texto_a_exportar = "".join(texto for _titulo, texto in resultado["capitulos"])
        else:
            texto_a_exportar = resultado["texto_completo"]

        nombre_proveedor_actual = DialogoProveedorAlternativo._NOMBRES_PROVEEDOR.get(
            voz_actual.get("proveedor_id", ""), voz_actual.get("proveedor_id", "el proveedor actual")
        )
        modo_libro_completo = not resultado["modo_capitulos"]

        dlg = DialogoProveedorAlternativo(
            self, texto_a_exportar, nombre_proveedor_actual,
            velocidad_actual=velocidad, modo_libro_completo=modo_libro_completo,
        )
        respuesta = dlg.ShowModal()

        if respuesta != wx.ID_OK or not dlg.accion:
            dlg.Destroy()
            self._anunciar("Exportación cancelada.")
            return

        # La velocidad ajustada dentro del diálogo se sincroniza de vuelta al
        # deslizador de esta pestaña — grabador_audio.py no lee el estado de
        # reproductor_voz.py, así que el ritmo corregido tiene que viajar
        # explícito hasta los métodos de exportación.
        self.deslizador_velocidad.SetValue(dlg.velocidad_elegida)
        velocidad_final = dlg.velocidad_elegida
        accion = dlg.accion

        if accion == "usar_alternativo":
            nueva_voz = dict(dlg.voz_elegida)
            nueva_voz["proveedor_id"] = dlg.proveedor_elegido
            dlg.Destroy()
            self._arrancar_exportacion(nueva_voz, velocidad_final, volumen, resultado)
        elif accion == "usar_local":
            dlg.Destroy()
            self._arrancar_exportacion(
                {"proveedor_id": "local", "nombre": "Voz local (SAPI5)"},
                velocidad_final, volumen, resultado,
            )
        elif accion == "dividir":
            # El propio motor (grabador_audio.py) ya calcula el punto de
            # corte por cuota y guarda la parte pendiente — "dividir" solo
            # significa seguir adelante con el proveedor actual sin cambiar
            # de voz.
            dlg.Destroy()
            self._arrancar_exportacion(voz_actual, velocidad_final, volumen, resultado)
        else:
            dlg.Destroy()
            self._anunciar("Exportación cancelada.")

    def _arrancar_exportacion(self, voz, velocidad, volumen, resultado):
        from app.motor.grabador_audio import GrabadorAudio

        self._exportando = True
        self.btn_iniciar.Enable(False)
        self.btn_calcular.Enable(False)
        self.combo_modo.Enable(False)
        self.btn_abortar.Enable(True)
        self.gauge.SetValue(0)
        self.txt_progreso.SetValue("Iniciando exportación...")
        reproducir(REC_START)

        self._grabador = GrabadorAudio(callback_progreso=self._callback_progreso_hilo)

        threading.Thread(
            target=self._ejecutar_exportacion,
            args=(voz, velocidad, volumen, resultado),
            daemon=True,
        ).start()

    def _ejecutar_exportacion(self, voz, velocidad, volumen, resultado):
        titulo_libro = self.libro_actual.get("titulo", "Audiolibro")
        proveedor = voz.get("proveedor_id", "local")
        try:
            if resultado["modo_capitulos"]:
                salida = self._grabador.exportar_audiolibro_por_capitulos(
                    resultado["capitulos"], voz, titulo_libro,
                    velocidad=velocidad, volumen=volumen,
                )
            else:
                salida = self._grabador.exportar_audiolibro_completo(
                    resultado["texto_completo"], resultado["fronteras"], voz, titulo_libro,
                    velocidad=velocidad, volumen=volumen,
                )
        except Exception as e:
            logger.exception("[PestanaCreadorAudiolibros] Error durante la exportación")
            wx.CallAfter(self._al_error_exportacion, str(e))
            return

        salida["modo_capitulos"] = resultado["modo_capitulos"]
        salida["proveedor"] = proveedor
        wx.CallAfter(self._al_terminar_exportacion, salida)

    def _callback_progreso_hilo(self, actual, total, etiqueta, nombre_voz):
        # Llamado desde el hilo de exportación — toda actualización de UI
        # pasa por wx.CallAfter, sin excepción.
        wx.CallAfter(self._actualizar_progreso_ui, actual, total, etiqueta)

    def _actualizar_progreso_ui(self, actual: int, total: int, etiqueta: str):
        pct = int((actual / total) * 100) if total > 0 else 0
        self.gauge.SetValue(pct)
        self.txt_progreso.SetValue(f"Exportando: {actual} de {total} — {etiqueta}")

        if self.lista_capitulos.IsShown() and total > 1:
            self._actualizar_estado_capitulo(actual - 1, self.ESTADO_COMPLETADO)

        # Prohibido cantar porcentajes: solo se anuncia un hito completo por
        # capítulo (modo "por capítulos"). En modo "libro completo" (total=1)
        # el único anuncio es el de finalización, en _al_terminar_exportacion,
        # para no duplicar el aviso.
        if total > 1:
            self._anunciar(f"Capítulo {actual} de {total} completado.")

    def _al_terminar_exportacion(self, salida: dict):
        self._exportando = False
        self.btn_iniciar.Enable(True)
        self.btn_calcular.Enable(True)
        self.combo_modo.Enable(True)
        self.btn_abortar.Enable(False)
        self.gauge.SetValue(100)

        errores = salida.get("errores", [])
        if errores:
            logger.warning(
                "[PestanaCreadorAudiolibros] Errores durante la exportación: %s", errores
            )

        if salida["modo_capitulos"]:
            self._finalizar_exportacion_capitulos(salida)
        else:
            self._finalizar_exportacion_completa(salida)

    def _finalizar_exportacion_capitulos(self, salida: dict):
        estados = salida.get("capitulos", [])
        for c in estados:
            estado_visual = self.ESTADO_COMPLETADO if c["estado"] == "completado" else self.ESTADO_SIN_CUOTA
            self._actualizar_estado_capitulo(c["indice"], estado_visual)

        pendientes = [c for c in estados if c["estado"] != "completado"]
        completados = len(estados) - len(pendientes)
        total = len(estados)

        if pendientes:
            self._registrar_pendiente_capitulos(pendientes[0]["indice"], salida.get("proveedor", "local"))
            mensaje = (
                f"Exportación detenida por falta de cuota. "
                f"{completados} de {total} capítulos completados. Queda registrado como pendiente."
            )
            reproducir(ERROR)
        else:
            self._limpiar_pendientes_de_libro()
            mensaje = f"Exportación finalizada. {total} capítulos completados."
            reproducir(SUCCESS)

        self.txt_progreso.SetValue(mensaje)
        self._anunciar(mensaje)

    def _finalizar_exportacion_completa(self, salida: dict):
        if salida.get("completo"):
            self._limpiar_pendientes_de_libro()
            mensaje = "Exportación del libro completo finalizada."
            reproducir(SUCCESS)
        else:
            self._registrar_pendiente_completo(salida)
            mensaje = (
                "Exportación detenida por falta de cuota. Se guardó una parte "
                "pendiente para retomar más tarde."
            )
            reproducir(ERROR)

        self.txt_progreso.SetValue(mensaje)
        self._anunciar(mensaje)

    def _al_error_exportacion(self, error: str):
        self._exportando = False
        self.btn_iniciar.Enable(True)
        self.btn_calcular.Enable(True)
        self.combo_modo.Enable(True)
        self.btn_abortar.Enable(False)
        reproducir(ERROR)
        self.txt_progreso.SetValue(f"Error durante la exportación: {error}")
        self._anunciar(f"Error durante la exportación: {error}")

    def al_abortar_exportacion(self, evento):
        if self._grabador:
            self._grabador.abortar()
        self.btn_abortar.Enable(False)
        self.txt_progreso.SetValue("Cancelando exportación...")
        # El hilo en curso detecta el aborto en el siguiente punto de control
        # (frontera de capítulo, o antes de generar en modo completo) y
        # termina llamando a _al_terminar_exportacion, que registra el
        # pendiente si quedó algo sin generar.

    # ------------------------------------------------------------------ #
    # Persistencia de exportaciones pendientes en biblioteca.db
    # ------------------------------------------------------------------ #

    def _obtener_gestor_biblioteca(self):
        if self._gestor_biblioteca is None:
            from app.motor.gestor_biblioteca import GestorBiblioteca
            self._gestor_biblioteca = GestorBiblioteca()
        return self._gestor_biblioteca

    def _limpiar_pendientes_de_libro(self):
        try:
            gestor = self._obtener_gestor_biblioteca()
            gestor.eliminar_exportaciones_pendientes_de_libro(self.libro_actual["id"])
        except Exception:
            logger.exception("[PestanaCreadorAudiolibros] No se pudo limpiar pendientes del libro")

    def _registrar_pendiente_capitulos(self, indice_capitulo_pendiente: int, proveedor: str):
        try:
            gestor = self._obtener_gestor_biblioteca()
            id_libro = self.libro_actual["id"]
            gestor.eliminar_exportaciones_pendientes_de_libro(id_libro)
            gestor.registrar_exportacion_pendiente(
                id_libro=id_libro,
                modo="capitulos",
                proveedor=proveedor,
                capitulo_pendiente=indice_capitulo_pendiente,
            )
        except Exception:
            logger.exception(
                "[PestanaCreadorAudiolibros] No se pudo registrar el pendiente por capítulos"
            )

    def _registrar_pendiente_completo(self, salida: dict):
        try:
            gestor = self._obtener_gestor_biblioteca()
            id_libro = self.libro_actual["id"]
            gestor.eliminar_exportaciones_pendientes_de_libro(id_libro)
            archivos = salida.get("archivos_generados") or []
            gestor.registrar_exportacion_pendiente(
                id_libro=id_libro,
                modo="completo",
                proveedor=salida.get("proveedor", "local"),
                punto_corte=salida.get("punto_corte"),
                ruta_parcial=archivos[0] if archivos else None,
            )
        except Exception:
            logger.exception(
                "[PestanaCreadorAudiolibros] No se pudo registrar el pendiente del libro completo"
            )

    # ------------------------------------------------------------------ #
    # Anuncios de accesibilidad (patrón _anunciador)
    # ------------------------------------------------------------------ #

    def _anunciar(self, texto):
        control_previo = wx.Window.FindFocus()
        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()
        wx.CallLater(300, lambda: control_previo.SetFocus() if control_previo else None)
# ANCLAJE_FIN: PESTANA_CREADOR_AUDIOLIBROS
