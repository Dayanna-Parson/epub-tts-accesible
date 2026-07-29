import wx
import os
import json
import logging
import wx.lib.mixins.listctrl as listmix

from app.config_rutas import ruta_config
from app.motor.reproductor_sonidos import reproducir, LIST_NAV, ERROR
from app.motor.gestor_idioma import traducir as _

logger = logging.getLogger(__name__)


# ANCLAJE_INICIO: LISTA_VOCES_CHECK
class ListaVocesCheck(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    def __init__(self, parent):
        wx.ListCtrl.__init__(self, parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.EnableCheckBoxes(True)
        self.Bind(wx.EVT_LIST_KEY_DOWN, self._al_tecla)

    def _al_tecla(self, evento):
        key = evento.GetKeyCode()
        if key in (wx.WXK_UP, wx.WXK_DOWN):
            reproducir(LIST_NAV)
        evento.Skip()
# ANCLAJE_FIN: LISTA_VOCES_CHECK


# ANCLAJE_INICIO: BASE_PANEL_PROVEEDOR_IA
class PanelProveedorIA(wx.Panel):
    """
    Clase base parametrizada para los paneles de catálogo de voces de cada proveedor cloud.

    Secuencia de tabulación lineal y estricta:
        Idioma → [controles extra del proveedor] → Solo favoritas → Solo nuevas voces
        → Búsqueda → ListCtrl → Botonera

    Las casillas de favoritos y nuevas voces son locales a cada panel e independientes
    entre sí: activarlas no contamina la vista de otros proveedores.

    Ganchos de extensión para subclases:
      _construir_controles_extra(sizer)  — añade controles entre Idioma y las casillas
      _obtener_filtros_extra(voz)        — devuelve False para excluir la voz del filtrado

    Reutilizado tanto por los paneles de catálogo de Ajustes (pestana_ajustes.py)
    como por el diálogo de selección de proveedor alternativo del Creador de
    Audiolibros, para no duplicar la lógica de favoritas, filtrado y preescucha.
    """

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

    _GENEROS_ES = {
        "Female": "Femenino",
        "Male": "Masculino",
        "Neutral": "Neutro",
    }

    def __init__(self, padre, config, id_proveedor, nombre_proveedor):
        super().__init__(padre)
        self.config = config
        self.id_proveedor = id_proveedor
        self.nombre_proveedor = nombre_proveedor
        self.voces_todas = []
        self.mapa_indices = {}
        self.ruta_favs = ruta_config("voces_favoritas.json")
        self.favoritos = self._cargar_favoritos()
        self._timer_busqueda = None
        # Protege contra el "marcado en cascada": CheckItem() puede disparar
        # sintéticamente EVT_LIST_ITEM_CHECKED en wxPython, igual que si el
        # usuario marcara la casilla a mano. Sin este candado, cada
        # reconstrucción de la lista (p. ej. al cambiar de proveedor en el
        # diálogo del Creador de Audiolibros) volvía a "marcar como
        # favorita" cada voz ya favorita a través de _al_marcar_favorito(),
        # sin corromper datos por sí solo, pero dejando la puerta abierta a
        # que cualquier CheckItem programático futuro sí lo haga.
        self._poblando_lista = False
        self._construir_ui()
        wx.CallAfter(self.cargar_datos)

    def _construir_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 1. Idioma
        hbox_idioma = wx.BoxSizer(wx.HORIZONTAL)
        hbox_idioma.Add(
            wx.StaticText(self, label=_("Idioma:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        # "Todos" se compara literalmente en filtrar_y_mostrar() — no se
        # envuelve en _() por el mismo motivo que las claves de filtro de
        # PanelAzure/PanelPolly en pestana_ajustes.py.
        self.combo_idioma = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos"])
        self.combo_idioma.SetSelection(0)
        self.combo_idioma.SetHelpText(
            _("Filtra las voces de {proveedor} por idioma. "
              "Elige Todos para ver el catálogo completo del proveedor.").format(
                proveedor=self.nombre_proveedor
            )
        )
        self.combo_idioma.Bind(wx.EVT_COMBOBOX, self._al_filtrar)
        hbox_idioma.Add(self.combo_idioma, 1)
        sizer.Add(hbox_idioma, 0, wx.EXPAND | wx.ALL, 8)

        # 1b. Controles extra del proveedor (gancho: subclases añaden aquí)
        self._construir_controles_extra(sizer)

        # 2. Casillas de filtro local (independientes por panel)
        hbox_filtros = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_solo_favs = wx.CheckBox(self, label=_("Solo favoritas"))
        self.chk_solo_favs.SetHelpText(
            _("Marcada: muestra solo las voces de este proveedor que ya tienes marcadas como favoritas.")
        )
        self.chk_solo_favs.Bind(wx.EVT_CHECKBOX, self._al_filtrar)
        hbox_filtros.Add(self.chk_solo_favs, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 20)

        self.chk_solo_nuevas = wx.CheckBox(self, label=_("Solo nuevas voces"))
        self.chk_solo_nuevas.SetHelpText(
            _("Marcada: muestra solo las voces de este proveedor añadidas desde la última actualización.")
        )
        self.chk_solo_nuevas.Bind(wx.EVT_CHECKBOX, self._al_filtrar)
        hbox_filtros.Add(self.chk_solo_nuevas, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(hbox_filtros, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # 3. Búsqueda de texto con debounce (300 ms)
        hbox_busqueda = wx.BoxSizer(wx.HORIZONTAL)
        hbox_busqueda.Add(
            wx.StaticText(self, label=_("Buscar nombre de voz:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self.txt_buscar = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_buscar.SetHelpText(
            _("Escribe parte del nombre de una voz para filtrar la lista en tiempo real. "
              "Borra el campo para ver todas las voces del filtro activo.")
        )
        self.txt_buscar.Bind(wx.EVT_TEXT, self._al_filtrar_texto)
        hbox_busqueda.Add(self.txt_buscar, 1, wx.EXPAND)
        sizer.Add(hbox_busqueda, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # 4. ListCtrl de voces con casillas nativas
        self.lista_voces = ListaVocesCheck(self)
        self.lista_voces.InsertColumn(0, _("Nombre"), width=280)
        self.lista_voces.InsertColumn(1, _("Género"), width=80)
        self.lista_voces.InsertColumn(2, _("Idioma"), width=200)
        self.lista_voces.SetHelpText(
            _("Lista de voces de {proveedor}. Usa las flechas para navegar. "
              "Pulsa Intro para marcar o desmarcar una voz como favorita. "
              "Las voces marcadas aparecerán en Lectura, Creador de Audiolibros y Grabación.").format(
                proveedor=self.nombre_proveedor
            )
        )
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_CHECKED, self._al_marcar_favorito)
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._al_desmarcar_favorito)
        sizer.Add(self.lista_voces, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # 5. Botonera inferior
        sizer.Add(self._construir_botonera(), 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self.primer_control = self.combo_idioma

    # --- Ganchos de extensión para subclases ---

    def _construir_controles_extra(self, sizer):
        """
        Gancho invocado durante _construir_ui(), entre Idioma y las casillas.
        Las subclases sobreescriben este método para añadir controles de filtrado propios
        (por ejemplo, el combo de tipo de motor de Amazon Polly).
        """
        pass

    def _obtener_filtros_extra(self, voz):
        """
        Gancho de filtrado invocado en filtrar_y_mostrar() tras los filtros estándar.
        Devuelve True para incluir la voz o False para excluirla.
        Las subclases sobreescriben este método para aplicar filtros específicos del proveedor.
        """
        return True

    # --- Botonera estándar ---

    def _construir_botonera(self):
        from app.motor.reproductor_voz import ReproductorVoz
        self._reproductor = ReproductorVoz()

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_escuchar = wx.Button(self, label=_("Escuchar muestra (Alt+P)"))
        self.btn_escuchar.SetHelpText(
            _("Reproduce una muestra de texto con la voz seleccionada. "
              "Púlsalo de nuevo para detener la reproducción.")
        )
        self.btn_escuchar.Bind(wx.EVT_BUTTON, self._al_escuchar)
        hbox.Add(self.btn_escuchar, 0, wx.RIGHT, 8)

        id_play = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._al_escuchar, id=id_play)
        self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_ALT, ord('P'), id_play)]))

        return hbox

    @property
    def ultimo_control(self):
        return self.btn_escuchar

    # --- Carga de datos desde voces_disponibles.json ---

    def cargar_datos(self):
        """
        Lee perezosamente voces_disponibles.json vía GestorVoces y filtra por
        self.id_proveedor. Pobla el combo de idioma y llama a filtrar_y_mostrar.
        """
        from app.motor.cliente_nube_voces import GestorVoces
        try:
            todas = GestorVoces().obtener_todas_las_voces()
        except Exception:
            logger.exception(f"Error al obtener voces de {self.nombre_proveedor}")
            todas = {}

        self.voces_todas = []
        for v in todas.get(self.id_proveedor, []):
            entrada = dict(v)
            entrada["proveedor_id"] = self.id_proveedor
            entrada["es_nueva"] = bool(entrada.get("es_nueva", False))
            self.voces_todas.append(entrada)

        idiomas = sorted(set(v.get("idioma", "") for v in self.voces_todas if v.get("idioma")))
        self.combo_idioma.Clear()
        self.combo_idioma.Append("Todos")
        self.combo_idioma.AppendItems(idiomas)
        self.combo_idioma.SetSelection(0)

        self.filtrar_y_mostrar()

    # --- Lógica de filtrado combinada ---

    def _al_filtrar(self, evento):
        self.filtrar_y_mostrar()

    def _al_filtrar_texto(self, evento):
        # Debounce: reconstruye la lista 300 ms después de la última pulsación
        if self._timer_busqueda:
            self._timer_busqueda.Stop()
        self._timer_busqueda = wx.CallLater(300, self.filtrar_y_mostrar)
        evento.Skip()

    def filtrar_y_mostrar(self):
        # Freeze suspende el redibujado durante la inserción masiva (sin parpadeo)
        self.lista_voces.Freeze()
        self._poblando_lista = True
        self.lista_voces.DeleteAllItems()
        self.mapa_indices = {}

        f_idioma = self.combo_idioma.GetValue()
        f_texto = self.txt_buscar.GetValue().lower()
        solo_favs = self.chk_solo_favs.IsChecked()
        solo_nuevas = self.chk_solo_nuevas.IsChecked()

        idx = 0
        for voz in self.voces_todas:
            id_voz = voz.get("id", "")
            es_favorita = id_voz in self.favoritos
            es_nueva = bool(voz.get("es_nueva"))

            # Filtros especiales exclusivos: tienen prioridad sobre el resto
            if solo_nuevas:
                if not es_nueva:
                    continue
            elif solo_favs:
                if not es_favorita:
                    continue
            else:
                # 1. Idioma
                if f_idioma != "Todos" and voz.get("idioma") != f_idioma:
                    continue
                # 2. Filtro extra del proveedor (gancho: motor Polly, etc.)
                if not self._obtener_filtros_extra(voz):
                    continue
                # 3. Búsqueda por texto
                if f_texto and f_texto not in voz.get("nombre", "").lower():
                    continue

            # Traducción semántica: NVDA lee las cadenas técnicas en español
            nombre_mostrar = self._construir_nombre_enriquecido(voz)
            genero_mostrar = self._GENEROS_ES.get(voz.get("genero", ""), voz.get("genero", ""))
            idioma_raw = voz.get("idioma", "")
            idioma_mostrar = self._LOCALES_ES.get(idioma_raw, idioma_raw)

            pos = self.lista_voces.InsertItem(idx, nombre_mostrar)
            self.lista_voces.SetItem(pos, 1, genero_mostrar)
            self.lista_voces.SetItem(pos, 2, idioma_mostrar)

            if es_favorita:
                self.lista_voces.CheckItem(pos, True)

            self.mapa_indices[pos] = voz
            idx += 1

        # Thaw reactiva el redibujado y pinta todos los ítems de una sola pasada
        self.lista_voces.Thaw()
        self._poblando_lista = False

    def _construir_nombre_enriquecido(self, voz):
        """
        Inyecta etiquetas semánticas en el nombre para que NVDA las anuncie
        antes de que el usuario baje al siguiente control.
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
        if etiquetas:
            return f"{nombre_base} {' '.join(etiquetas)}"
        return nombre_base

    # --- Favoritos (guardado atómico + notificación inmediata) ---

    def _cargar_favoritos(self):
        try:
            if os.path.exists(self.ruta_favs):
                with open(self.ruta_favs, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            logger.exception("Error al leer voces_favoritas.json")
        return []

    def _guardar_favoritos(self):
        # Escritura atómica: primero .tmp, luego renombrar
        ruta_tmp = self.ruta_favs + ".tmp"
        try:
            with open(ruta_tmp, 'w', encoding='utf-8') as f:
                json.dump(self.favoritos, f, indent=4)
            os.replace(ruta_tmp, self.ruta_favs)
        except Exception:
            logger.exception("Error al guardar voces_favoritas.json")

    def _al_marcar_favorito(self, evento):
        if self._poblando_lista:
            # CheckItem() al poblar la lista dispara este mismo evento como si
            # el usuario hubiera marcado la casilla a mano; se ignora aquí.
            return
        voz = self.mapa_indices.get(evento.GetIndex())
        if voz:
            id_voz = voz.get("id")
            if id_voz not in self.favoritos:
                self.favoritos.append(id_voz)
                self._guardar_favoritos()
                wx.CallAfter(self._notificar_pestanas)

    def _al_desmarcar_favorito(self, evento):
        if self._poblando_lista:
            return
        voz = self.mapa_indices.get(evento.GetIndex())
        if voz:
            id_voz = voz.get("id")
            if id_voz in self.favoritos:
                self.favoritos.remove(id_voz)
                self._guardar_favoritos()
                wx.CallAfter(self._notificar_pestanas)

    def _notificar_pestanas(self):
        """Recarga en segundo plano los combos de voz en Lectura y Grabación."""
        try:
            ventana = wx.GetTopLevelParent(self)
            if hasattr(ventana, 'pestana_grabacion'):
                ventana.pestana_grabacion._cargar_voces_disponibles()
            if hasattr(ventana, 'pestana_lectura') and hasattr(ventana.pestana_lectura, '_recargar_combo_voces'):
                ventana.pestana_lectura._recargar_combo_voces()
            if hasattr(ventana, 'pestana_creador') and hasattr(ventana.pestana_creador, '_recargar_voces_favoritas'):
                ventana.pestana_creador._recargar_voces_favoritas()
        except Exception:
            logger.exception("Error al notificar cambio de favoritos a otras pestañas")

    # --- Preescucha ---

    def _al_escuchar(self, evento):
        if self._reproductor.obtener_estado() == "reproduciendo":
            self._reproductor.detener()
            self.btn_escuchar.SetLabel(_("Escuchar muestra (Alt+P)"))
            return

        idx = self.lista_voces.GetFirstSelected()
        if idx == -1:
            reproducir(ERROR)
            wx.MessageBox(_("Selecciona una voz."), _("Info"))
            return

        voz = self.mapa_indices.get(idx)
        nombre = voz.get('nombre', '')
        try:
            self._reproductor.fijar_voz(voz)
            texto = _(
                "Hola, mi nombre es {nombre}. "
                "El sol salía lentamente sobre las colinas cuando la ciudad comenzó a despertar."
            ).format(nombre=nombre)
            self.btn_escuchar.SetLabel(_("Detener preescucha (Alt+P)"))
            self._reproductor.cargar_texto(texto, callback_completado=self._al_terminar_escucha)
        except Exception as e:
            self.btn_escuchar.SetLabel(_("Escuchar muestra (Alt+P)"))
            reproducir(ERROR)
            wx.MessageBox(_("Error: {error}").format(error=e), _("Error"))

    def _al_terminar_escucha(self):
        wx.CallAfter(self.btn_escuchar.SetLabel, _("Escuchar muestra (Alt+P)"))
# ANCLAJE_FIN: BASE_PANEL_PROVEEDOR_IA
