import logging

import wx

from app.config_rutas import cargar_claves
from app.motor import anunciador_lector as voz
from app.motor.control_cuota import ControlCuota
from app.interfaz.pestana_ajustes import PanelAzure, PanelDeepgram, PanelPolly, PanelElevenLabs
from app.interfaz.ui_recursos import aplicar_icono_boton
from app.motor.gestor_idioma import traducir as _

logger = logging.getLogger(__name__)


# ANCLAJE_INICIO: DIALOGO_PROVEEDOR_ALTERNATIVO
class DialogoProveedorAlternativo(wx.Dialog):
    """
    Se muestra cuando el proveedor elegido en el Creador de Audiolibros no
    tiene cuota suficiente para el texto a exportar (sección 3.3 de la
    planificación). Ofrece cambiar a otro proveedor con saldo disponible,
    usar la voz local, dividir la exportación en partes, o cancelar.

    Reutiliza PanelProveedorIA (vía sus subclases ya existentes en
    pestana_ajustes.py) para el catálogo de voces del proveedor alternativo
    elegido, en vez de duplicar la lógica de favoritas/filtrado/preescucha.

    Resultado expuesto tras ShowModal():
        self.accion            "usar_alternativo" / "usar_local" / "dividir" / None (cancelar)
        self.proveedor_elegido clave del proveedor ("azure", "polly", ...) si accion == "usar_alternativo"
        self.voz_elegida       dict de la voz seleccionada en el catálogo embebido
        self.velocidad_elegida valor final del deslizador de velocidad del diálogo
    """

    _NOMBRES_PROVEEDOR = {
        "azure":      "Azure Neural",
        "polly":      "Amazon Polly",
        "elevenlabs": "ElevenLabs",
        "deepgram":   "Deepgram Aura-2",
    }

    _PANELES_PROVEEDOR = {
        "azure":      PanelAzure,
        "polly":      PanelPolly,
        "elevenlabs": PanelElevenLabs,
        "deepgram":   PanelDeepgram,
    }

    def __init__(self, padre, texto_a_exportar, nombre_proveedor_actual, velocidad_actual=50, modo_libro_completo=True):
        super().__init__(
            padre, title=_("Cuota insuficiente para continuar"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.texto_a_exportar = texto_a_exportar
        self.modo_libro_completo = modo_libro_completo

        self.accion = None
        self.proveedor_elegido = None
        self.voz_elegida = None
        self.velocidad_elegida = velocidad_actual

        self._control_previo = wx.Window.FindFocus()
        self._control_cuota = ControlCuota()
        self._panel_voces = None
        self._proveedores_disponibles = self._calcular_proveedores_disponibles(texto_a_exportar)

        self._construir_ui(nombre_proveedor_actual, velocidad_actual)

        self.Fit()
        self.SetMinSize((520, 480))
        self.CenterOnParent()

        if self._proveedores_disponibles:
            self._actualizar_panel_voces()

        wx.CallAfter(self._anunciar_estado_inicial, nombre_proveedor_actual)

    # ------------------------------------------------------------------ #
    # Cálculo de proveedores con cuota suficiente (consulta silenciosa)
    # ------------------------------------------------------------------ #

    def _calcular_proveedores_disponibles(self, texto):
        """
        Recorre los proveedores de nube con clave API configurada y devuelve
        los que sí tienen cuota suficiente para `texto`, ordenados de mayor
        a menor saldo disponible. Usa exclusivamente tiene_cuota()/
        get_info_uso() — ninguna consulta levanta interfaz.
        """
        claves = cargar_claves()
        disponibles = []
        for clave, nombre in self._NOMBRES_PROVEEDOR.items():
            conf = claves.get(clave, {})
            configurado = isinstance(conf, dict) and any(str(v).strip() for v in conf.values())
            if not configurado:
                continue
            if not self._control_cuota.tiene_cuota(texto, clave):
                continue
            gastado, limite = self._control_cuota.get_info_uso(clave)
            saldo = max(0, limite - gastado)
            disponibles.append((clave, nombre, saldo))

        disponibles.sort(key=lambda t: t[2], reverse=True)
        return disponibles

    @staticmethod
    def _formatear_saldo(cantidad: int) -> str:
        return f"{cantidad:,}".replace(",", ".")

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #

    def _construir_ui(self, nombre_proveedor_actual, velocidad_actual):
        sizer = wx.BoxSizer(wx.VERTICAL)

        caracteres = len(self.texto_a_exportar)
        lbl_info = wx.StaticText(
            self,
            label=_(
                "{proveedor} no tiene cuota suficiente para este texto "
                "({caracteres} caracteres)."
            ).format(proveedor=nombre_proveedor_actual, caracteres=self._formatear_saldo(caracteres)),
        )
        sizer.Add(lbl_info, 0, wx.EXPAND | wx.ALL, 10)

        # 1. Selector de proveedor alternativo — primer control, recibe el foco inicial.
        lbl_combo = wx.StaticText(self, label=_("Proveedor alternativo:"))
        sizer.Add(lbl_combo, 0, wx.LEFT | wx.RIGHT, 10)

        opciones = [
            _("{nombre} (Disponible: {saldo} caracteres)").format(
                nombre=nombre, saldo=self._formatear_saldo(saldo)
            )
            for _clave, nombre, saldo in self._proveedores_disponibles
        ] or [_("Ningún proveedor de nube configurado tiene cuota suficiente")]

        self.combo_proveedores = wx.Choice(self, choices=opciones)
        self.combo_proveedores.SetHelpText(
            _("Proveedores de nube configurados que sí tienen cuota disponible para este "
              "texto, ordenados de mayor a menor saldo. Al cambiar de proveedor se actualiza "
              "el catálogo de voces de abajo.")
        )
        if self._proveedores_disponibles:
            self.combo_proveedores.SetSelection(0)
        else:
            self.combo_proveedores.SetSelection(0)
            self.combo_proveedores.Disable()
        self.combo_proveedores.Bind(wx.EVT_CHOICE, self._al_cambiar_proveedor)
        sizer.Add(self.combo_proveedores, 0, wx.EXPAND | wx.ALL, 10)

        # 2. Contenedor donde se incrusta el PanelProveedorIA del proveedor elegido.
        self.panel_contenedor = wx.Panel(self)
        self.sizer_contenedor = wx.BoxSizer(wx.VERTICAL)
        self.panel_contenedor.SetSizer(self.sizer_contenedor)
        sizer.Add(self.panel_contenedor, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # 3. Velocidad independiente para la preescucha de este diálogo.
        sz_vel = wx.BoxSizer(wx.HORIZONTAL)
        lbl_vel = wx.StaticText(self, label=_("Velocidad de preescucha:"))
        self.slider_velocidad = wx.Slider(self, value=velocidad_actual, minValue=0, maxValue=100)
        self.slider_velocidad.SetName(_("Velocidad de preescucha"))
        self.slider_velocidad.SetHelpText(
            _("Velocidad usada solo para la preescucha (Alt+P) y devuelta a la ventana "
              "principal al aceptar. 0 es la más lenta, 100 la más rápida. "
              "Flechas: ±1. RePág/AvPág: ±5.")
        )
        self.slider_velocidad.Bind(wx.EVT_SLIDER, self._al_cambiar_velocidad)
        self.slider_velocidad.Bind(wx.EVT_KEY_DOWN, self._al_tecla_velocidad)
        sz_vel.Add(lbl_vel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_vel.Add(self.slider_velocidad, 1)
        sizer.Add(sz_vel, 0, wx.EXPAND | wx.ALL, 10)

        # 3b. Voz local SAPI5 para "Usar voz local" — antes se usaba siempre
        # la voz predeterminada del sistema (sin dejar elegir ninguna otra),
        # porque se le pasaba a GrabadorAudio un dict genérico sin id real.
        sz_local = wx.BoxSizer(wx.HORIZONTAL)
        lbl_local = wx.StaticText(self, label=_("Voz local para «Usar voz local»:"))
        self.combo_voz_local = wx.Choice(self, choices=[_("Cargando voces locales...")])
        self.combo_voz_local.SetSelection(0)
        self.combo_voz_local.SetHelpText(
            _("Voz SAPI5 (64 o 32 bits) que se usará si pulsas «Usar voz local». "
              "Incluye todas las voces instaladas en tu equipo, no solo las favoritas.")
        )
        sz_local.Add(lbl_local, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sz_local.Add(self.combo_voz_local, 1)
        sizer.Add(sz_local, 0, wx.EXPAND | wx.ALL, 10)
        self._voces_locales = []
        wx.CallAfter(self._cargar_voces_locales)

        # 4. Botonera de acciones.
        sz_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_usar_alternativo = wx.Button(self, label=_("Usar proveedor alternativo"))
        self.btn_usar_alternativo.SetHelpText(
            _("Continúa la exportación con el proveedor y la voz seleccionados arriba.")
        )
        self.btn_usar_alternativo.Enable(bool(self._proveedores_disponibles))
        self.btn_usar_alternativo.Bind(wx.EVT_BUTTON, self._al_usar_alternativo)
        sz_botones.Add(self.btn_usar_alternativo, 0, wx.RIGHT, 8)

        self.btn_usar_local = wx.Button(self, label=_("Usar voz local"))
        self.btn_usar_local.SetHelpText(
            _("Continúa la exportación con la voz local SAPI5 elegida en el combo de "
              "arriba, sin coste ni límite de cuota.")
        )
        self.btn_usar_local.Bind(wx.EVT_BUTTON, self._al_usar_local)
        sz_botones.Add(self.btn_usar_local, 0, wx.RIGHT, 8)

        self.btn_dividir = wx.Button(self, label=_("Dividir en partes"))
        self.btn_dividir.SetHelpText(
            _("Genera hasta donde alcance la cuota actual y guarda el resto como parte "
              "pendiente para retomar más tarde. Solo disponible en modo Libro completo.")
        )
        self.btn_dividir.Enable(self.modo_libro_completo)
        self.btn_dividir.Bind(wx.EVT_BUTTON, self._al_dividir)
        aplicar_icono_boton(self.btn_dividir, "trocear", _("Dividir en partes"))
        sz_botones.Add(self.btn_dividir, 0, wx.RIGHT, 8)

        self.btn_cancelar = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
        self.btn_cancelar.Bind(wx.EVT_BUTTON, self._al_cancelar)
        aplicar_icono_boton(self.btn_cancelar, "cerrar", _("Cancelar"))
        sz_botones.Add(self.btn_cancelar, 0)

        sizer.Add(sz_botones, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, lambda e: self._cerrar(wx.ID_CANCEL))

    # ------------------------------------------------------------------ #
    # Catálogo de voces embebido (reutiliza PanelProveedorIA sin duplicar)
    # ------------------------------------------------------------------ #

    def _al_cambiar_proveedor(self, evento):
        self._actualizar_panel_voces()

    def _actualizar_panel_voces(self):
        idx = self.combo_proveedores.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._proveedores_disponibles):
            return

        clave, _nombre, _saldo = self._proveedores_disponibles[idx]

        if self._panel_voces:
            self.sizer_contenedor.Detach(self._panel_voces)
            self._panel_voces.Destroy()
            self._panel_voces = None

        clase_panel = self._PANELES_PROVEEDOR[clave]
        self._panel_voces = clase_panel(self.panel_contenedor, {})
        # "Solo favoritas" activado por defecto en este contexto (sección 3.3
        # de la planificación): cargar_datos() todavía no ha corrido —
        # SetValue() no dispara EVT_CHECKBOX, así que el primer filtrado ya
        # sale con este estado. Si el proveedor alternativo no tiene ninguna
        # favorita, _al_datos_cargados lo detecta y lo desmarca sin bloquear.
        self._panel_voces.chk_solo_favs.SetValue(True)
        self.sizer_contenedor.Add(self._panel_voces, 1, wx.EXPAND)
        self.panel_contenedor.Layout()
        self.GetSizer().Layout()
        self.Fit()

        wx.CallAfter(self._sincronizar_velocidad_panel)
        wx.CallLater(200, self._comprobar_favoritas_vacias, self._panel_voces)

    def _comprobar_favoritas_vacias(self, panel_voces):
        """
        Si tras cargar el catálogo del proveedor alternativo "Solo favoritas"
        no deja ninguna voz visible, se desmarca automáticamente y se avisa,
        para no dejar al usuario atascado ante una lista vacía sin explicación.
        """
        if (
            self._panel_voces is not panel_voces
            or not panel_voces.chk_solo_favs.IsChecked()
            or panel_voces.lista_voces.GetItemCount() > 0
        ):
            return
        panel_voces.chk_solo_favs.SetValue(False)
        panel_voces.filtrar_y_mostrar()
        voz.hablar(
            _("Este proveedor no tiene voces favoritas guardadas. Se muestran todas sus voces.")
        )

    def _sincronizar_velocidad_panel(self):
        # PanelProveedorIA no aplica velocidad por defecto en su preescucha
        # (Ajustes no la necesita); aquí sí se pide que Alt+P respete el
        # deslizador del diálogo, así que se sincroniza sobre su reproductor
        # interno sin modificar el componente compartido.
        if self._panel_voces and hasattr(self._panel_voces, '_reproductor'):
            try:
                self._panel_voces._reproductor.fijar_velocidad(self.slider_velocidad.GetValue())
            except Exception:
                logger.exception(
                    "[DialogoProveedorAlternativo] No se pudo sincronizar la velocidad de preescucha."
                )

    # ------------------------------------------------------------------ #
    # Velocidad: pasos de 1 (flechas, nativo de wx.Slider) y 5 (RePág/AvPág)
    # ------------------------------------------------------------------ #

    def _al_cambiar_velocidad(self, evento):
        self._sincronizar_velocidad_panel()

    def _al_tecla_velocidad(self, evento):
        key = evento.GetKeyCode()
        if key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            delta = -5 if key == wx.WXK_PAGEUP else 5
            slider = self.slider_velocidad
            nuevo = max(slider.GetMin(), min(slider.GetMax(), slider.GetValue() + delta))
            slider.SetValue(nuevo)
            self._sincronizar_velocidad_panel()
        else:
            evento.Skip()

    # ------------------------------------------------------------------ #
    # Anuncio de accesibilidad al abrir — accessible_output3
    # ------------------------------------------------------------------ #

    def _anunciar_estado_inicial(self, nombre_proveedor_actual):
        n = len(self._proveedores_disponibles)
        if n == 0:
            mensaje = _(
                "{proveedor} sin cuota suficiente. "
                "Ningún otro proveedor de nube tiene saldo disponible. "
                "Puedes usar la voz local o dividir en partes."
            ).format(proveedor=nombre_proveedor_actual)
        else:
            plural = _("proveedor alternativo") if n == 1 else _("proveedores alternativos")
            mensaje = _("{proveedor} sin cuota suficiente. {n} {plural} disponible con saldo.").format(
                proveedor=nombre_proveedor_actual, n=n, plural=plural
            )

        voz.hablar(mensaje)
        # El foco va directo al selector de proveedor (primer control útil
        # del diálogo), no de vuelta al control previo — ya no hace falta
        # esperar: accessible_output3 no necesita el foco para hablar.
        self._enfocar_combo_inicial()

    def _enfocar_combo_inicial(self):
        if self.combo_proveedores:
            self.combo_proveedores.SetFocus()

    # ------------------------------------------------------------------ #
    # Acciones
    # ------------------------------------------------------------------ #

    def _al_usar_alternativo(self, evento):
        idx = self.combo_proveedores.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._proveedores_disponibles) or not self._panel_voces:
            wx.MessageBox(_("Selecciona un proveedor con cuota disponible."), _("Info"))
            return

        idx_voz = self._panel_voces.lista_voces.GetFirstSelected()
        if idx_voz == -1:
            wx.MessageBox(_("Selecciona una voz del catálogo antes de continuar."), _("Info"))
            return

        voz = self._panel_voces.mapa_indices.get(idx_voz)
        if not voz:
            wx.MessageBox(_("Selecciona una voz del catálogo antes de continuar."), _("Info"))
            return

        clave, _nombre, _saldo = self._proveedores_disponibles[idx]
        self.accion = "usar_alternativo"
        self.proveedor_elegido = clave
        self.voz_elegida = voz
        self.velocidad_elegida = self.slider_velocidad.GetValue()
        self._cerrar(wx.ID_OK)

    def _cargar_voces_locales(self):
        """
        Carga todas las voces SAPI5 instaladas (64 y 32 bits), no solo las
        favoritas — a diferencia del selector principal del Creador de
        Audiolibros, aquí interesa poder elegir cualquier voz local
        disponible en el sistema en el momento en que falta cuota.
        """
        voces = []
        try:
            from app.servicios.cliente_sapi5 import ClienteSapi5
            voces.extend(ClienteSapi5().obtener_voces())
        except Exception:
            logger.exception("[DialogoProveedorAlternativo] Error al cargar voces SAPI5 de 64 bits")
        try:
            from app.servicios.cliente_sapi32_bridge import ClienteSapi32Bridge
            bridge = ClienteSapi32Bridge()
            if bridge.conectado:
                ids_existentes = {v.get("id") for v in voces}
                for v in bridge.obtener_voces():
                    if v.get("id") not in ids_existentes:
                        voces.append(v)
                bridge.cerrar()
        except Exception:
            logger.exception("[DialogoProveedorAlternativo] Error al cargar voces SAPI5 de 32 bits")

        self._voces_locales = voces
        if voces:
            self.combo_voz_local.Set([v.get("nombre", "") for v in voces])
            self.combo_voz_local.SetSelection(0)
        else:
            self.combo_voz_local.Set([_("No se encontró ninguna voz SAPI5 instalada")])
            self.combo_voz_local.SetSelection(0)
            self.btn_usar_local.Enable(False)

    def _al_usar_local(self, evento):
        self.accion = "usar_local"
        idx = self.combo_voz_local.GetSelection()
        if self._voces_locales and 0 <= idx < len(self._voces_locales):
            self.voz_elegida = dict(self._voces_locales[idx])
        else:
            self.voz_elegida = {"proveedor_id": "local", "nombre": _("Voz local (SAPI5)")}
        self.velocidad_elegida = self.slider_velocidad.GetValue()
        self._cerrar(wx.ID_OK)

    def _al_dividir(self, evento):
        self.accion = "dividir"
        self.velocidad_elegida = self.slider_velocidad.GetValue()
        self._cerrar(wx.ID_OK)

    def _al_cancelar(self, evento):
        self.accion = None
        self._cerrar(wx.ID_CANCEL)

    def _cerrar(self, resultado):
        control_previo = self._control_previo
        self.EndModal(resultado)
        if control_previo:
            wx.CallAfter(lambda: control_previo.SetFocus() if control_previo else None)
# ANCLAJE_FIN: DIALOGO_PROVEEDOR_ALTERNATIVO
