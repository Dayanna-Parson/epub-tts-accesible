"""
pestana_grabacion.py
---------------------
Pestaña de grabación multivoz para producción de audiolibros accesibles.

Flujo de uso (diseñado para NVDA + teclado):
  1. Pulsa "Examinar…" → selecciona un TXT → el escaneo es automático.
  2. En el combo "Etiqueta activa" selecciona la primera etiqueta.
  3. Marca una voz en la lista de favoritos → se auto-asigna y el combo avanza.
  4. Repite hasta cubrir todas las etiquetas.
  5. Pulsa "Iniciar Grabación".
  6. "Limpiar" restablece la pestaña para cargar otro fragmento sin reiniciar.

Accesibilidad NVDA:
  - SetHelpText() en controles de entrada: NVDA lo verbaliza al recibir foco.
  - Etiquetas descriptivas en botones: NVDA las lee directamente.
  - ListaVocesCheck (CheckListCtrlMixin + EnableCheckBoxes) en lugar de
    CheckListBox: casillas nativas, Space/Enter para marcar, NVDA anuncia estado.
  - Columnas: Nombre de la voz | Género | Idioma | Proveedor.
  - Casilla "Dividir": label dinámico → NVDA anuncia el nuevo texto al cambiar.
  - pyttsx3: verbaliza el progreso de cada fragmento durante la grabación.
"""

import wx
import wx.lib.mixins.listctrl as listmix
import os
import json
import threading
import subprocess
import logging

from app.config_rutas import ruta_config, cargar_claves, CONFIG_DIR
from app.motor.gestor_proyectos import TIPOS_PROYECTO
from app.motor.procesador_etiquetas import (
    fragmentar_texto,
    normalizar_etiqueta,
    limpiar_nombre_archivo,
)
from app.motor.grabador_audio import GrabadorAudio, CARPETA_RAIZ_GRABACIONES
from app.motor.reproductor_sonidos import (
    reproducir, REC_START, PROGRESS, SUCCESS,
    ERROR as SND_ERROR, OPEN_FOLDER, CLEAR, LIST_NAV, CLICK,
)
from app.interfaz.ui_recursos import aplicar_icono_boton
from app.motor.gestor_idioma import traducir as _

logger = logging.getLogger(__name__)


# ── Diálogo de bautizo: asociar TXT al Gestor de Proyectos ───────────────────
class DialogoBautizo(wx.Dialog):
    """
    Diálogo que aparece automáticamente cuando todas las etiquetas tienen voz asignada
    y el archivo TXT no está aún en ningún proyecto.

    Permite al usuario:
      - Crear un nuevo proyecto (con nombre editable y selector de tipo).
      - Añadir el TXT a un proyecto existente (seleccionable en lista).
      - Cancelar sin asociar nada ("Ahora no").
    """

    def __init__(self, parent, gestor_proyectos, nombre_sugerido: str = ""):
        super().__init__(
            parent,
            title=_("Guardar en el Gestor de Proyectos"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._gestor = gestor_proyectos
        self._resultado_proyecto_id = None

        self._panel = wx.Panel(self)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Texto informativo
        lbl_info = wx.StaticText(
            self._panel,
            label=_(
                "¡Todas las etiquetas tienen voz asignada!\n"
                "¿Deseas guardar este archivo en el Gestor de Proyectos?"
            ),
        )
        sz.Add(lbl_info, 0, wx.ALL, 10)

        # Radio: Crear nuevo / Añadir a existente
        self.radio_nuevo = wx.RadioButton(
            self._panel, label=_("Crear nuevo proyecto"), style=wx.RB_GROUP
        )
        self.radio_nuevo.SetHelpText(_("Crea un proyecto nuevo y asocia este archivo."))
        self.radio_existente = wx.RadioButton(
            self._panel, label=_("Añadir a un proyecto existente")
        )
        self.radio_existente.SetHelpText(_("Añade este archivo a un proyecto ya creado."))
        sz.Add(self.radio_nuevo,    0, wx.LEFT | wx.RIGHT, 10)
        sz.Add(self.radio_existente, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Panel: nuevo proyecto ─────────────────────────────────────────
        self._panel_nuevo = wx.Panel(self._panel)
        sz_nuevo = wx.BoxSizer(wx.VERTICAL)
        lbl_nombre = wx.StaticText(self._panel_nuevo, label=_("Nombre del proyecto:"))
        self.txt_nombre = wx.TextCtrl(self._panel_nuevo, value=nombre_sugerido, style=wx.TE_PROCESS_ENTER)
        self.txt_nombre.SetHelpText(_("Escribe el nombre del nuevo proyecto."))
        lbl_tipo = wx.StaticText(self._panel_nuevo, label=_("Tipo:"))
        self.combo_tipo = wx.Choice(self._panel_nuevo, choices=[_(t) for t in TIPOS_PROYECTO])
        self.combo_tipo.SetSelection(0)
        sz_nuevo.Add(lbl_nombre,    0, wx.BOTTOM, 2)
        sz_nuevo.Add(self.txt_nombre, 0, wx.EXPAND | wx.BOTTOM, 6)
        sz_nuevo.Add(lbl_tipo,      0, wx.BOTTOM, 2)
        sz_nuevo.Add(self.combo_tipo, 0, wx.EXPAND)
        self._panel_nuevo.SetSizer(sz_nuevo)
        sz.Add(self._panel_nuevo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Panel: proyecto existente ─────────────────────────────────────
        self._panel_existente = wx.Panel(self._panel)
        sz_ex = wx.BoxSizer(wx.VERTICAL)
        lbl_ex = wx.StaticText(self._panel_existente, label=_("Selecciona el proyecto:"))
        proyectos = gestor_proyectos.listar_todos()
        self._proyectos_lista = proyectos
        nombres = [f"{p['nombre']} [{p['tipo']}]" for p in proyectos]
        self.choice_existente = wx.Choice(
            self._panel_existente,
            choices=nombres if nombres else [_("(No hay proyectos aún)")],
        )
        self.choice_existente.SetHelpText(_("Elige el proyecto al que quieres añadir este archivo."))
        if nombres:
            self.choice_existente.SetSelection(0)
        sz_ex.Add(lbl_ex,                0, wx.BOTTOM, 2)
        sz_ex.Add(self.choice_existente, 0, wx.EXPAND)
        self._panel_existente.SetSizer(sz_ex)
        sz.Add(self._panel_existente, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Botones
        sz_btn = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_ok     = wx.Button(self._panel, wx.ID_OK,     label=_("Guardar en proyecto"))
        btn_cancel       = wx.Button(self._panel, wx.ID_CANCEL, label=_("Ahora no"))
        self._btn_ok.SetHelpText(_("Confirma la asociación del archivo al proyecto seleccionado."))
        btn_cancel.SetHelpText(_("Cierra este diálogo sin asociar el archivo a ningún proyecto."))
        aplicar_icono_boton(self._btn_ok, "guardar", _("Guardar en proyecto"))
        aplicar_icono_boton(btn_cancel, "cerrar", _("Ahora no"))
        sz_btn.Add(self._btn_ok, 0, wx.RIGHT, 8)
        sz_btn.Add(btn_cancel,  0)
        sz.Add(sz_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self._panel.SetSizer(sz)
        dlg_sz = wx.BoxSizer(wx.VERTICAL)
        dlg_sz.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(dlg_sz)
        self.Fit()

        # Eventos
        self.radio_nuevo.Bind(wx.EVT_RADIOBUTTON,    self._al_cambiar_modo)
        self.radio_existente.Bind(wx.EVT_RADIOBUTTON, self._al_cambiar_modo)
        self._btn_ok.Bind(wx.EVT_BUTTON, self._al_ok)
        self.txt_nombre.Bind(
            wx.EVT_TEXT_ENTER,
            lambda e: self._btn_ok.GetEventHandler().ProcessEvent(
                wx.CommandEvent(wx.EVT_BUTTON.typeId, self._btn_ok.GetId())
            ),
        )

        # Estado inicial
        self.radio_nuevo.SetValue(True)
        self._actualizar_paneles()
        wx.CallAfter(self.txt_nombre.SetFocus)

    def _al_cambiar_modo(self, evento):
        self._actualizar_paneles()
        evento.Skip()

    def _actualizar_paneles(self):
        modo_nuevo = self.radio_nuevo.GetValue()
        self._panel_nuevo.Show(modo_nuevo)
        self._panel_existente.Show(not modo_nuevo)
        self._panel.Layout()
        self.Fit()
        if modo_nuevo:
            wx.CallAfter(self.txt_nombre.SetFocus)
        else:
            wx.CallAfter(self.choice_existente.SetFocus)

    def _al_ok(self, evento):
        if self.radio_nuevo.GetValue():
            nombre = self.txt_nombre.GetValue().strip()
            if not nombre:
                reproducir(SND_ERROR)
                wx.MessageBox(
                    _("Escribe un nombre para el proyecto."),
                    _("Nombre requerido"), wx.OK | wx.ICON_WARNING
                )
                self.txt_nombre.SetFocus()
                return
            tipo_idx = self.combo_tipo.GetSelection()
            tipo = TIPOS_PROYECTO[tipo_idx] if tipo_idx >= 0 else "otro"
            self._resultado_proyecto_id = self._gestor.crear_proyecto(nombre, tipo)
        else:
            idx = self.choice_existente.GetSelection()
            if idx == wx.NOT_FOUND or not self._proyectos_lista:
                reproducir(SND_ERROR)
                wx.MessageBox(
                    _("Selecciona un proyecto de la lista."),
                    _("Sin selección"), wx.OK | wx.ICON_WARNING
                )
                return
            self._resultado_proyecto_id = self._proyectos_lista[idx]["id"]
        self.EndModal(wx.ID_OK)

    def obtener_resultado(self) -> tuple:
        """Devuelve (proyecto_id, None). proyecto_id es None si se canceló."""
        return self._resultado_proyecto_id, None


# ── Lista con casillas de verificación (igual que en pestana_ajustes) ────────
class ListaVocesCheck(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    """
    ListCtrl con casillas nativas (EnableCheckBoxes).
    NVDA anuncia el estado marcado/desmarcado al navegar con las flechas.
    """
    def __init__(self, parent):
        wx.ListCtrl.__init__(
            self, parent,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES,
        )
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        # Casillas nativas — imprescindible para que NVDA las detecte
        self.EnableCheckBoxes(True)
        self.Bind(wx.EVT_LIST_KEY_DOWN, self._al_tecla)

    def _al_tecla(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_UP, wx.WXK_DOWN):
            reproducir(LIST_NAV)
        elif key == wx.WXK_SPACE:
            idx = self.GetFirstSelected()
            if idx != -1:
                self.ToggleItem(idx)
        event.Skip()


# ─────────────────────────────────────────────────────────────────────────────

class PestanaGrabacion(wx.Panel):
    """Panel principal de grabación multivoz, accesible con NVDA."""

    # Traducción de códigos de idioma a texto legible
    _LOCALES_ES = {
        "es-ES": "Español (España)",
        "es-MX": "Español (México)",
        "es-AR": "Español (Argentina)",
        "es-CO": "Español (Colombia)",
        "en-US": "Inglés (EE.UU.)",
        "en-GB": "Inglés (R.U.)",
        "en-AU": "Inglés (Australia)",
        "fr-FR": "Francés",
        "de-DE": "Alemán",
        "it-IT": "Italiano",
        "pt-BR": "Portugués (Brasil)",
        "pt-PT": "Portugués",
        "ja-JP": "Japonés",
        "zh-CN": "Chino (Mandarín)",
        "ko-KR": "Coreano",
        "Multilingüe (v2)": "Multilingüe",
    }

    # Traducción de género
    _GENEROS_ES = {
        "Female": "Femenino",
        "Male":   "Masculino",
        "Neutral": "Neutro",
    }

    def __init__(self, padre):
        super().__init__(padre, style=wx.TAB_TRAVERSAL)

        # ── Estado interno ────────────────────────────────────────────────
        from app.motor.gestor_proyectos import GestorProyectos
        from app.motor.anunciador_voz import AnunciadorVoz
        self._voz_grabacion = AnunciadorVoz()
        self.Bind(wx.EVT_WINDOW_DESTROY, lambda e: (self._voz_grabacion.detener(), e.Skip()))
        self.proyecto_actual   = None          # dict del proyecto activo o None
        self.gestor_proyectos  = GestorProyectos()
        self._ofrecio_proyecto = False         # evita mostrar el diálogo dos veces por TXT
        self.ruta_txt_actual      = None
        self.nombre_base_txt      = ""
        self.texto_cargado        = ""
        self.fragmentos           = []     # [(etiqueta, contenido), ...]
        self.etiquetas_detectadas = []     # [etiqueta_normalizada, ...]
        self.asignaciones         = {}     # {etiqueta: datos_voz}
        self.voces_disponibles    = []     # [(texto_col0, datos_voz), ...]
        self._mapa_indices        = {}     # {row_idx: datos_voz}
        self.titulo_libro         = ""
        self.grabador             = None
        self._hilo_grabacion      = None
        self._ultima_carpeta      = None
        self._radio_activo        = False  # guardia anti-recursión en radio-check

        # ── Rutas de configuración ────────────────────────────────────────
        self.ruta_mapeo = ruta_config("mapeo_etiquetas.json")
        self.ruta_favs  = ruta_config("voces_favoritas.json")
        self.ruta_todas = ruta_config("voces_disponibles.json")

        self._construir_interfaz()
        self._cargar_voces_disponibles()
        self._restaurar_sliders_grabacion()

    # ================================================================== #
    # Propiedades para Tab cíclico (usadas por ventana_principal.py)
    # ================================================================== #

    @property
    def primer_control(self):
        return self.btn_dividir_epub

    @property
    def ultimo_control(self):
        return self.btn_abrir_carpeta

    # ================================================================== #
    # Construcción de la interfaz
    # ================================================================== #

    def _construir_interfaz(self):
        sizer_raiz = wx.BoxSizer(wx.VERTICAL)

        # ── Carga de archivo ─────────────────────────────────────────────
        box_carga = wx.StaticBox(self, label=_("Archivo de texto"))
        sz_carga  = wx.StaticBoxSizer(box_carga, wx.VERTICAL)

        sz_ruta = wx.BoxSizer(wx.HORIZONTAL)
        lbl_ruta = wx.StaticText(self, label=_("Archivo TXT:"))
        self.txt_ruta = wx.TextCtrl(self, style=wx.TE_READONLY)
        self.txt_ruta.SetHelpText(_("Ruta del archivo de texto actualmente cargado."))

        # Etiqueta descriptiva en el botón — NVDA la lee directamente al recibir foco
        # btn_dividir_epub se crea primero para que sea el primero en el orden de tabulación
        self.btn_dividir_epub = wx.Button(
            self, label=_("Dividir EPUB… — Divide un EPUB en archivos TXT por capítulo")
        )
        self.btn_dividir_epub.SetHelpText(
            _("Abre el diálogo para dividir un archivo EPUB en capítulos TXT independientes. "
              "Los archivos se guardan en Grabaciones_Epub-TTS/<Nombre del libro>/capitulos/.")
        )
        self.btn_examinar = wx.Button(
            self, label=_("Examinar… — Selecciona un TXT con etiquetas de personaje")
        )
        self.btn_limpiar = wx.Button(
            self, label=_("Limpiar — Restablece la pestaña para cargar otro fragmento")
        )

        sz_ruta.Add(lbl_ruta,              0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_ruta.Add(self.txt_ruta,         1, wx.EXPAND)
        sz_ruta.Add(self.btn_dividir_epub, 0, wx.LEFT, 5)
        sz_ruta.Add(self.btn_examinar,     0, wx.LEFT, 5)
        sz_ruta.Add(self.btn_limpiar,      0, wx.LEFT, 5)

        sz_titulo = wx.BoxSizer(wx.HORIZONTAL)
        lbl_titulo = wx.StaticText(self, label=_("Título (opcional):"))
        self.txt_titulo = wx.TextCtrl(self)
        self.txt_titulo.SetHelpText(
            _("Título del libro o proyecto. Si se deja vacío se usa el nombre del "
              "archivo TXT. Define la subcarpeta de grabaciones. "
              "Si el archivo está asociado a un proyecto, el título sincroniza el nombre del proyecto al salir del campo.")
        )
        sz_titulo.Add(lbl_titulo,      0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_titulo.Add(self.txt_titulo, 1, wx.EXPAND)

        sz_cap = wx.BoxSizer(wx.HORIZONTAL)
        lbl_cap = wx.StaticText(self, label=_("Capítulo (opcional):"))
        self.txt_capitulo = wx.TextCtrl(self)
        self.txt_capitulo.SetHelpText(
            _("Nombre del capítulo. Si se deja vacío se usa el nombre del archivo TXT. "
              "Define el nombre de la subcarpeta interna.")
        )
        sz_cap.Add(lbl_cap,            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_cap.Add(self.txt_capitulo,  1, wx.EXPAND)

        sz_carga.Add(sz_ruta,   0, wx.EXPAND | wx.ALL, 5)
        sz_carga.Add(sz_titulo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        sz_carga.Add(sz_cap,    0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Casting de voces ─────────────────────────────────────────────
        box_cast = wx.StaticBox(self, label=_("Asignación de voces"))
        sz_cast  = wx.StaticBoxSizer(box_cast, wx.VERTICAL)

        sz_cols = wx.BoxSizer(wx.HORIZONTAL)

        # Columna izq: etiqueta activa
        sz_etiq = wx.BoxSizer(wx.VERTICAL)
        lbl_etiq = wx.StaticText(self, label=_("Etiquetas detectadas:"))
        self.combo_etiquetas = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_etiquetas.SetHelpText(
            _("Etiquetas detectadas en el archivo. Selecciona la etiqueta a la que "
              "quieres asignar una voz. Al marcar una voz en la lista de la derecha "
              "la asignación es automática y el combo avanza a la siguiente etiqueta sin asignar.")
        )
        sz_etiq.Add(lbl_etiq,             0, wx.BOTTOM, 3)
        sz_etiq.Add(self.combo_etiquetas, 0, wx.EXPAND)

        # Columna der: voces favoritas con ListaVocesCheck + columnas
        sz_voces = wx.BoxSizer(wx.VERTICAL)
        lbl_voces = wx.StaticText(self, label=_("Asigna voces a la etiqueta seleccionada:"))
        self.check_voces = ListaVocesCheck(self)
        self.check_voces.InsertColumn(0, _("Nombre de la voz"), width=210)
        self.check_voces.InsertColumn(1, _("Género"),           width=70)
        self.check_voces.InsertColumn(2, _("Idioma"),           width=130)
        self.check_voces.InsertColumn(3, _("Proveedor"),        width=90)
        self.check_voces.SetHelpText(
            _("Lista de voces favoritas. Pulsa Espacio sobre una voz para asignarla "
              "a la etiqueta activa. Solo puede haber una voz marcada a la vez.")
        )
        sz_voces.Add(lbl_voces,        0, wx.BOTTOM, 3)
        sz_voces.Add(self.check_voces, 1, wx.EXPAND)

        sz_cols.Add(sz_etiq,  1, wx.EXPAND | wx.RIGHT, 10)
        sz_cols.Add(sz_voces, 2, wx.EXPAND)

        # Botones del panel de casting
        sz_btn_cast = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_probar = wx.Button(
            self, label=_("Probar voz — Escucha una muestra de la voz marcada")
        )
        self.btn_preescucha = wx.Button(
            self, label=_("Pre-escucha General — Oye todas las voces asignadas en secuencia")
        )
        sz_btn_cast.Add(self.btn_probar,     0, wx.RIGHT, 8)
        sz_btn_cast.Add(self.btn_preescucha, 0)

        # Resumen de asignaciones
        lbl_asign = wx.StaticText(self, label=_("Asignaciones actuales:"))
        self.txt_asignaciones = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 90),
        )
        self.txt_asignaciones.SetHelpText(
            _("Resumen de asignaciones etiqueta a voz. "
              "Muestra sin asignar para las etiquetas que aún no tienen voz.")
        )

        sz_cast.Add(sz_cols,               1, wx.EXPAND | wx.ALL, 5)
        sz_cast.Add(sz_btn_cast,           0, wx.LEFT | wx.BOTTOM, 5)
        sz_cast.Add(lbl_asign,             0, wx.LEFT | wx.TOP, 5)
        sz_cast.Add(self.txt_asignaciones, 0, wx.EXPAND | wx.ALL, 5)

        # ── Opciones de salida ────────────────────────────────────────────
        box_opc = wx.StaticBox(self, label=_("Opciones de salida"))
        sz_opc  = wx.StaticBoxSizer(box_opc, wx.VERTICAL)

        # Label dinámico: al cambiar el estado NVDA anuncia el nuevo texto del label
        self.chk_dividir = wx.CheckBox(
            self,
            label=_("Dividir por etiquetas: archivos numerados (1. Nar.mp3, 2. Pj1.mp3…)"),
        )
        self.chk_dividir.SetValue(True)
        sz_opc.Add(self.chk_dividir, 0, wx.ALL, 5)

        # ── Velocidad de grabación ────────────────────────────────────────
        sz_vel = wx.BoxSizer(wx.HORIZONTAL)
        lbl_vel = wx.StaticText(self, label=_("Velocidad de grabación:"))
        self.deslizador_velocidad_grab = wx.Slider(self, value=50, minValue=0, maxValue=100)
        self.deslizador_velocidad_grab.SetName(_("Velocidad de grabación"))
        self.deslizador_velocidad_grab.SetHelpText(
            _("Velocidad de locución de la voz. 0 es la más lenta, 100 la más rápida. "
              "Flechas: ±1. RePág/AvPág: ±5.")
        )
        self.deslizador_velocidad_grab.Bind(wx.EVT_SLIDER,   self._al_cambiar_velocidad_grab)
        self.deslizador_velocidad_grab.Bind(wx.EVT_KEY_DOWN, self._al_tecla_vel_grab)
        sz_vel.Add(lbl_vel,                        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_vel.Add(self.deslizador_velocidad_grab, 1)
        sz_opc.Add(sz_vel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Volumen de grabación ──────────────────────────────────────────
        sz_vol = wx.BoxSizer(wx.HORIZONTAL)
        lbl_vol = wx.StaticText(self, label=_("Volumen de grabación:"))
        self.deslizador_volumen_grab = wx.Slider(self, value=100, minValue=0, maxValue=100)
        self.deslizador_volumen_grab.SetName(_("Volumen de grabación"))
        self.deslizador_volumen_grab.SetHelpText(
            _("Volumen del audio generado. 0 es silencio, 100 es volumen máximo. "
              "Flechas: ±1. RePág/AvPág: ±5.")
        )
        self.deslizador_volumen_grab.Bind(wx.EVT_SLIDER,   self._al_cambiar_volumen_grab)
        self.deslizador_volumen_grab.Bind(wx.EVT_KEY_DOWN, self._al_tecla_vol_grab)
        sz_vol.Add(lbl_vol,                       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_vol.Add(self.deslizador_volumen_grab,  1)
        sz_opc.Add(sz_vol, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Progreso ──────────────────────────────────────────────────────
        box_prog = wx.StaticBox(self, label=_("Progreso"))
        sz_prog  = wx.StaticBoxSizer(box_prog, wx.VERTICAL)

        self.lbl_progreso = wx.StaticText(
            self,
            label=_("Estado: En espera. Selecciona un archivo TXT para comenzar."),
        )
        self.gauge = wx.Gauge(self, range=100)
        self.gauge.SetHelpText(_("Barra de progreso de la grabación actual."))

        sz_prog.Add(self.lbl_progreso, 0, wx.EXPAND | wx.ALL, 5)
        sz_prog.Add(self.gauge,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Botones principales ───────────────────────────────────────────
        sz_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_iniciar = wx.Button(
            self, label=_("Iniciar Grabación — Comienza el proceso de grabación multivoz")
        )
        self.btn_iniciar.Enable(False)

        self.btn_abortar = wx.Button(
            self,
            label=_("Abortar — Detiene la grabación; los archivos ya generados se conservan"),
        )
        self.btn_abortar.Enable(False)

        self.btn_abrir_carpeta = wx.Button(
            self, label=_("Abrir Carpeta — Abre la carpeta de grabaciones en el Explorador")
        )

        sz_botones.Add(self.btn_iniciar,       0, wx.RIGHT, 5)
        sz_botones.Add(self.btn_abortar,       0, wx.RIGHT, 5)
        sz_botones.Add(self.btn_abrir_carpeta, 0)

        # ── Ensamblado ────────────────────────────────────────────────────
        sizer_raiz.Add(sz_carga,   0, wx.EXPAND | wx.ALL, 6)
        sizer_raiz.Add(sz_cast,    1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sz_opc,     0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sz_prog,    0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sz_botones, 0, wx.ALL, 10)

        self.SetSizer(sizer_raiz)

        # ── Eventos ───────────────────────────────────────────────────────
        self.btn_examinar.Bind(wx.EVT_BUTTON,        self.al_examinar)
        self.btn_limpiar.Bind(wx.EVT_BUTTON,         self.al_limpiar)
        self.btn_dividir_epub.Bind(wx.EVT_BUTTON,    self._al_dividir_epub)
        self.txt_titulo.Bind(wx.EVT_KILL_FOCUS,     self._al_perder_foco_titulo)
        self.btn_probar.Bind(wx.EVT_BUTTON,         self.al_probar_voz)
        self.btn_preescucha.Bind(wx.EVT_BUTTON,     self.al_preescucha_general)
        self.chk_dividir.Bind(wx.EVT_CHECKBOX,      self.al_cambiar_division)
        self.btn_iniciar.Bind(wx.EVT_BUTTON,        self.al_iniciar_grabacion)
        self.btn_abortar.Bind(wx.EVT_BUTTON,        self.al_abortar)
        self.btn_abrir_carpeta.Bind(wx.EVT_BUTTON,  self.al_abrir_carpeta)
        self.check_voces.Bind(wx.EVT_LIST_ITEM_CHECKED,   self.al_marcar_voz)
        self.check_voces.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.al_desmarcar_voz)

    # ================================================================== #
    # JSON helpers — seguros ante archivo vacío o corrupto
    # ================================================================== #

    def _cargar_json(self, ruta: str) -> dict:
        try:
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    contenido = f.read().strip()
                if contenido:
                    return json.loads(contenido)
        except Exception as e:
            logger.warning(
                f"[PestanaGrabacion] JSON inválido en {os.path.basename(ruta)}: {e}"
            )
        return {}

    def _guardar_json(self, ruta: str, datos):
        try:
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(
                f"[PestanaGrabacion] No se pudo guardar {os.path.basename(ruta)}: {e}"
            )

    # ================================================================== #
    # Helpers de nombre (título/capítulo opcionales)
    # ================================================================== #

    def _resolver_titulo(self) -> str:
        t = self.txt_titulo.GetValue().strip()
        return t if t else (self.nombre_base_txt or "Sin_Titulo")

    def _resolver_capitulo(self) -> str:
        c = self.txt_capitulo.GetValue().strip()
        return c if c else (self.nombre_base_txt or "Sin_Capitulo")

    # ================================================================== #
    # Carga de voces disponibles — ListaVocesCheck con columnas
    # ================================================================== #

    def _cargar_voces_disponibles(self):
        """Puebla check_voces con voces favoritas (columnas) y SAPI5 locales."""
        self.voces_disponibles = []
        self._mapa_indices     = {}
        self.check_voces.DeleteAllItems()

        idx = 0

        # ── Voces neuronales favoritas ────────────────────────────────────
        ids_favs_raw = self._cargar_json(self.ruta_favs)
        ids_favs = set(ids_favs_raw) if isinstance(ids_favs_raw, list) else set()

        if ids_favs and os.path.exists(self.ruta_todas):
            todas = self._cargar_json(self.ruta_todas)
            for prov, lista in todas.items():
                if not isinstance(lista, list):
                    continue
                for v in lista:
                    if v.get('id') not in ids_favs:
                        continue
                    v_copy = dict(v)
                    v_copy['proveedor_id'] = prov

                    nombre      = v_copy.get('nombre', _("Sin nombre"))
                    genero      = self._GENEROS_ES.get(v_copy.get('genero', ''),
                                                       v_copy.get('genero', ''))
                    idioma_raw  = v_copy.get('idioma', '')
                    idioma      = self._LOCALES_ES.get(idioma_raw, idioma_raw)
                    prov_lower  = prov.lower()
                    if prov_lower == 'polly':
                        prov_mostrar = 'Amazon Polly'
                    elif prov_lower == 'elevenlabs':
                        prov_mostrar = 'ElevenLabs'
                    else:
                        prov_mostrar = prov.capitalize()

                    pos = self.check_voces.InsertItem(idx, nombre)
                    self.check_voces.SetItem(pos, 1, genero)
                    self.check_voces.SetItem(pos, 2, idioma)
                    self.check_voces.SetItem(pos, 3, prov_mostrar)
                    self._mapa_indices[pos] = v_copy
                    self.voces_disponibles.append((nombre, v_copy))
                    idx += 1

        # ── Voces SAPI5 locales ───────────────────────────────────────────
        try:
            from app.servicios.cliente_sapi5 import ClienteSapi5
            for datos in ClienteSapi5().obtener_voces():
                desc = datos["nombre"]
                pos = self.check_voces.InsertItem(idx, desc)
                self.check_voces.SetItem(pos, 1, "")
                self.check_voces.SetItem(pos, 2, "")
                self.check_voces.SetItem(pos, 3, _("Local (SAPI5)"))
                self._mapa_indices[pos] = datos
                self.voces_disponibles.append((desc, datos))
                idx += 1
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[SAPI5] No se pudieron cargar voces locales: %s", e)

        if idx == 0:
            pos = self.check_voces.InsertItem(
                0, _("No hay voces. Añade favoritas en la pestaña Ajustes.")
            )
            self.check_voces.SetItem(pos, 1, "")
            self.check_voces.SetItem(pos, 2, "")
            self.check_voces.SetItem(pos, 3, "")

    # ================================================================== #
    # Carga y escaneo automático del archivo TXT
    # ================================================================== #

    def _al_perder_foco_titulo(self, evento):
        """
        Sincroniza el campo Título con el nombre del proyecto asociado (feature f).
        Se activa al salir del campo (EVT_KILL_FOCUS).
        También actualiza el nodo en VentanaProyectos si está abierta.
        """
        evento.Skip()  # IMPRESCINDIBLE para no bloquear el ciclo de foco
        if not self.proyecto_actual:
            return
        titulo = self.txt_titulo.GetValue().strip()
        if titulo and titulo != self.proyecto_actual.get("nombre", ""):
            self.gestor_proyectos.renombrar_proyecto(self.proyecto_actual["id"], titulo)
            self.proyecto_actual["nombre"] = titulo
            # Notificar al árbol de proyectos si está abierto
            try:
                ventana = wx.GetTopLevelParent(self.GetParent())
                vp = getattr(ventana, '_ventana_proyectos', None)
                if vp and vp.IsShown():
                    vp.actualizar_nombre_proyecto(self.proyecto_actual["id"], titulo)
            except Exception:
                logger.exception("Error al notificar el renombrado del proyecto a la ventana de proyectos")
                pass

    def _ofrecer_guardar_en_proyecto(self):
        """
        Muestra el diálogo de bautizo para asociar el TXT al Gestor de Proyectos.
        Se llama automáticamente cuando todas las etiquetas tienen voz asignada.
        """
        if not self.ruta_txt_actual:
            return
        nombre_sugerido = self._resolver_titulo()
        dlg = DialogoBautizo(self, self.gestor_proyectos, nombre_sugerido)
        if dlg.ShowModal() == wx.ID_OK:
            proyecto_id, _titulo_sin_usar = dlg.obtener_resultado()
            if proyecto_id:
                self.gestor_proyectos.asociar_archivo(proyecto_id, self.ruta_txt_actual)
                self.proyecto_actual = self.gestor_proyectos.obtener_proyecto(proyecto_id)
                if self.proyecto_actual:
                    self.lbl_progreso.SetLabel(
                        _("Archivo asociado al proyecto «{nombre}».").format(
                            nombre=self.proyecto_actual["nombre"]
                        )
                    )
        dlg.Destroy()

    def al_examinar(self, evento):
        self._ofrecio_proyecto = False
        with wx.FileDialog(
            self,
            _("Seleccionar archivo de texto con etiquetas"),
            wildcard=_("Archivos de texto (*.txt)|*.txt|Todos (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return

            self.ruta_txt_actual = dlg.GetPath()
            self.nombre_base_txt = os.path.splitext(
                os.path.basename(self.ruta_txt_actual)
            )[0]
            self.txt_ruta.SetValue(self.ruta_txt_actual)

            if not self.txt_titulo.GetValue().strip():
                self.txt_titulo.SetValue(self.nombre_base_txt)
            if not self.txt_capitulo.GetValue().strip():
                self.txt_capitulo.SetValue(self.nombre_base_txt)

        # Consultar si el TXT ya pertenece a un proyecto
        self.proyecto_actual = self.gestor_proyectos.proyecto_de_archivo(
            self.ruta_txt_actual
        )
        self._cargar_y_escanear()

        # Notificar a VentanaPrincipal para añadir a TXT Recientes
        try:
            ventana = wx.GetTopLevelParent(self.GetParent())
            if hasattr(ventana, 'agregar_txt_a_recientes'):
                ventana.agregar_txt_a_recientes(self.ruta_txt_actual)
        except Exception:
            logger.exception("Error al agregar el TXT a la lista de recientes de la ventana principal")
            pass

    def cargar_txt_desde_ruta(self, ruta: str):
        """
        Carga un archivo TXT directamente (sin diálogo de apertura).
        Usado por VentanaPrincipal al restaurar la sesión anterior.
        """
        if not os.path.exists(ruta):
            return
        self.ruta_txt_actual = ruta
        self.nombre_base_txt = os.path.splitext(os.path.basename(ruta))[0]
        self.txt_ruta.SetValue(ruta)
        if not self.txt_titulo.GetValue().strip():
            self.txt_titulo.SetValue(self.nombre_base_txt)
        if not self.txt_capitulo.GetValue().strip():
            self.txt_capitulo.SetValue(self.nombre_base_txt)
        self.proyecto_actual = self.gestor_proyectos.proyecto_de_archivo(ruta)
        self._cargar_y_escanear()

    def _cargar_y_escanear(self):
        if not self.ruta_txt_actual:
            return

        try:
            with open(self.ruta_txt_actual, 'r', encoding='utf-8') as f:
                self.texto_cargado = f.read()
        except Exception as e:
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("No se pudo leer el archivo:\n{error}").format(error=e),
                _("Error de lectura"), wx.OK | wx.ICON_ERROR,
            )
            return

        if not self.texto_cargado.strip():
            reproducir(SND_ERROR)
            wx.MessageBox(_("El archivo está vacío."), _("Sin contenido"), wx.OK | wx.ICON_WARNING)
            return

        self.fragmentos = fragmentar_texto(self.texto_cargado)
        if not self.fragmentos:
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("El archivo no contiene texto aprovechable."),
                _("Sin fragmentos"), wx.OK | wx.ICON_WARNING,
            )
            return

        # Etiquetas únicas preservando orden de aparición
        vistas, self.etiquetas_detectadas = set(), []
        for etiq, _texto_frag_sin_usar in self.fragmentos:
            if etiq not in vistas:
                self.etiquetas_detectadas.append(etiq)
                vistas.add(etiq)

        # El combo se reconstruirá con estado tras cargar el mapeo

        # Desmarcar todas las voces al cargar un nuevo texto
        for i in range(self.check_voces.GetItemCount()):
            self.check_voces.CheckItem(i, False)

        # Recuperar asignaciones previas vinculadas al título
        titulo = self._resolver_titulo()
        self.titulo_libro = titulo
        self.asignaciones = {}
        # Cargar mapeo local primero y después sobrescribir con voces del proyecto
        self._cargar_mapeo(titulo)
        if self.proyecto_actual:
            voces_heredadas = self.gestor_proyectos.obtener_voces_heredadas(
                self.proyecto_actual["id"]
            )
            # Las voces del proyecto tienen prioridad sobre el mapeo local
            for etiqueta, datos_voz in voces_heredadas.items():
                if etiqueta in self.etiquetas_detectadas:
                    self.asignaciones[etiqueta] = datos_voz
        self._actualizar_resumen_asignaciones()
        # Construir combo con estado (incluye asignaciones recuperadas del mapeo)
        self._actualizar_combo_etiquetas(
            preservar_etiqueta=self.etiquetas_detectadas[0] if self.etiquetas_detectadas else None
        )

        # Bautizo en carga inicial: si todas las etiquetas ya tienen voz asignada
        # (recuperadas del mapeo local o del proyecto), ofrecer guardar en proyecto
        sin_voz_inicial = [e for e in self.etiquetas_detectadas if e not in self.asignaciones]
        if not sin_voz_inicial and not self.proyecto_actual and not self._ofrecio_proyecto:
            self._ofrecio_proyecto = True
            wx.CallAfter(self._ofrecer_guardar_en_proyecto)

        total    = len(self.fragmentos)
        etiq_str = ', '.join('@' + e for e in self.etiquetas_detectadas)
        self.lbl_progreso.SetLabel(
            _("Archivo cargado: {total} fragmentos, etiquetas: {etiquetas}. "
              "Marca una voz en la lista para asignarla.").format(total=total, etiquetas=etiq_str)
        )
        self.btn_iniciar.Enable(True)

        reproducir(SUCCESS)
        wx.MessageBox(
            _("Texto cargado.\nFragmentos: {total}\nEtiquetas: {etiquetas}").format(
                total=total, etiquetas=etiq_str
            ),
            _("Escaneo completado"), wx.OK | wx.ICON_INFORMATION,
        )

    # ================================================================== #
    # Limpiar
    # ================================================================== #

    def al_limpiar(self, evento):
        reproducir(CLEAR)
        self.ruta_txt_actual      = None
        self.nombre_base_txt      = ""
        self.texto_cargado        = ""
        self.fragmentos           = []
        self.etiquetas_detectadas = []
        self.asignaciones         = {}
        self.titulo_libro         = ""
        self._ultima_carpeta      = None
        self.proyecto_actual      = None
        self._ofrecio_proyecto    = False

        self.txt_ruta.SetValue("")
        self.txt_titulo.SetValue("")
        self.txt_capitulo.SetValue("")

        self.combo_etiquetas.Clear()
        for i in range(self.check_voces.GetItemCount()):
            self.check_voces.CheckItem(i, False)

        self.txt_asignaciones.SetValue(_("Carga un archivo para ver las etiquetas."))

        self.lbl_progreso.SetLabel(
            _("Estado: En espera. Selecciona un archivo TXT para comenzar.")
        )
        self.gauge.SetValue(0)
        self.btn_iniciar.Enable(False)
        self.btn_abortar.Enable(False)

        self.btn_examinar.SetFocus()

    # ================================================================== #
    # División de EPUB
    # ================================================================== #

    def _al_dividir_epub(self, evento=None):
        """Abre el diálogo de división de EPUB en capítulos TXT."""
        from app.interfaz.dialogo_troceador import DialogoTroceador
        from app.interfaz.ui_recursos import aplicar_icono_boton
        aplicar_icono_boton(self.btn_dividir_epub, "trocear", _("Dividir EPUB en capítulos TXT"))
        dlg = DialogoTroceador(self)
        dlg.ShowModal()
        dlg.Destroy()

    # ================================================================== #
    # Casting: auto-asignación al marcar una voz
    # ================================================================== #

    def al_marcar_voz(self, evento):
        """
        Al marcar una voz (EVT_LIST_ITEM_CHECKED):
          1. Comportamiento radio: desmarca todas las demás.
          2. Auto-asigna la voz marcada a la etiqueta activa.
          3. Avanza el combo a la siguiente etiqueta sin asignar.
        """
        if self._radio_activo:
            return

        idx_marcado = evento.GetIndex()

        # Comportamiento radio — guardia para evitar recursión
        self._radio_activo = True
        for i in range(self.check_voces.GetItemCount()):
            if i != idx_marcado:
                self.check_voces.CheckItem(i, False)
        self._radio_activo = False

        datos_voz = self._mapa_indices.get(idx_marcado)
        if datos_voz is None:
            return  # Fila de "No hay voces" — ignorar

        nombre_voz_disp = self.check_voces.GetItemText(idx_marcado)

        idx_etiq = self.combo_etiquetas.GetSelection()
        if idx_etiq == wx.NOT_FOUND:
            return

        # Parsear etiqueta del combo (formato: "@etiq → nombre" o "@etiq → (sin asignar)")
        etiqueta = self._etiqueta_de_combo(idx_etiq)

        self.asignaciones[etiqueta] = datos_voz
        # Propagar la asignación al proyecto si hay uno activo
        if self.proyecto_actual:
            self.gestor_proyectos.guardar_voces_proyecto(
                self.proyecto_actual["id"],
                self.asignaciones
            )
        self._guardar_mapeo()
        self._actualizar_resumen_asignaciones()

        # Diálogo de bautizo: solo cuando TODAS las etiquetas tienen voz
        # y el TXT no está aún en un proyecto
        sin_voz = [e for e in self.etiquetas_detectadas if e not in self.asignaciones]
        if not sin_voz and not self.proyecto_actual and not self._ofrecio_proyecto:
            self._ofrecio_proyecto = True
            wx.CallAfter(self._ofrecer_guardar_en_proyecto)

        self.lbl_progreso.SetLabel(
            _("Asignado: @{etiqueta}  →  {voz}").format(etiqueta=etiqueta, voz=nombre_voz_disp)
        )

        # Determinar la siguiente etiqueta sin asignar ANTES de reconstruir el combo
        total_etiq = len(self.etiquetas_detectadas)
        etiq_siguiente = None
        for delta in range(1, total_etiq):
            sig_etiq = self.etiquetas_detectadas[(idx_etiq + delta) % total_etiq]
            if sig_etiq not in self.asignaciones:
                etiq_siguiente = sig_etiq
                break

        # Reconstruir combo con nuevo estado y posicionar en la siguiente sin asignar
        self._actualizar_combo_etiquetas(
            preservar_etiqueta=etiq_siguiente if etiq_siguiente else etiqueta
        )

    def al_desmarcar_voz(self, evento):
        """Al desmarcar una voz manualmente no se borra la asignación."""
        # La guardia _radio_activo evita efectos secundarios al desmarcar
        # en el comportamiento radio de al_marcar_voz.
        pass

    def al_probar_voz(self, evento):
        """Reproduce una muestra de la voz marcada (hilo de fondo)."""
        datos_voz = None
        # Buscar la voz marcada (checked)
        for i in range(self.check_voces.GetItemCount()):
            if self.check_voces.IsChecked(i) and i in self._mapa_indices:
                datos_voz = self._mapa_indices[i]
                break
        # Si ninguna está marcada, usar la seleccionada (focus)
        if datos_voz is None:
            idx = self.check_voces.GetFirstSelected()
            if idx != -1 and idx in self._mapa_indices:
                datos_voz = self._mapa_indices[idx]

        if datos_voz is None:
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("Marca primero una voz en la lista."),
                _("Sin selección"), wx.OK | wx.ICON_WARNING,
            )
            return

        def _probar():
            try:
                GrabadorAudio().probar_voz(datos_voz)
            except Exception as e:
                logger.exception("Error al probar la voz seleccionada")
                wx.CallAfter(reproducir, SND_ERROR)
                wx.CallAfter(
                    wx.MessageBox,
                    _("Error al reproducir la muestra:\n{error}").format(error=e),
                    _("Error de previsualización"), wx.OK | wx.ICON_ERROR,
                )

        threading.Thread(target=_probar, daemon=True).start()

    def al_preescucha_general(self, evento):
        """
        Reproduce una muestra de cada voz asignada en orden de aparición
        de etiquetas. Útil para verificar el casting completo antes de grabar.
        """
        if not self.asignaciones:
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("No hay voces asignadas aún. Asigna al menos una voz antes "
                  "de la pre-escucha."),
                _("Sin asignaciones"), wx.OK | wx.ICON_WARNING,
            )
            return

        voces_a_probar = []
        for etiq in self.etiquetas_detectadas:
            datos_voz = self.asignaciones.get(etiq)
            if datos_voz:
                voces_a_probar.append((etiq, datos_voz))

        if not voces_a_probar:
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("Ninguna de las etiquetas detectadas tiene voz asignada."),
                _("Sin asignaciones"), wx.OK | wx.ICON_WARNING,
            )
            return

        def _preescucha():
            grabador = GrabadorAudio()
            for etiq, datos_voz in voces_a_probar:
                nombre_voz = datos_voz.get('nombre', _("voz"))
                wx.CallAfter(
                    self.lbl_progreso.SetLabel,
                    _("Pre-escucha: @{etiqueta} → {voz}").format(etiqueta=etiq, voz=nombre_voz),
                )
                try:
                    grabador.probar_voz(datos_voz)
                except Exception as e:
                    logger.warning(f"[Pre-escucha] Error con @{etiq}: {e}")
            wx.CallAfter(
                self.lbl_progreso.SetLabel,
                _("Pre-escucha completada. {n} voces verificadas.").format(n=len(voces_a_probar)),
            )

        threading.Thread(target=_preescucha, daemon=True).start()

    # ================================================================== #
    # Helpers de combo y resumen
    # ================================================================== #

    def _etiqueta_de_combo(self, idx: int) -> str:
        """
        Extrae la etiqueta normalizada del item del combo.
        Formato del item: '@etiq → nombre_voz'  o  '@etiq → (sin asignar)'
        Siempre devuelve solo la parte de etiqueta.
        """
        texto = self.combo_etiquetas.GetString(idx)
        return normalizar_etiqueta(texto.split(' →')[0].lstrip('@').strip())

    def _actualizar_combo_etiquetas(self, preservar_etiqueta: str = None):
        """
        Reconstruye los items del combo con el estado de asignación actual.
          @nar → Raul          (cuando tiene voz)
          @pj1 → (sin asignar)
        preservar_etiqueta: nombre de la etiqueta que debe quedar seleccionada
        tras la reconstrucción; si es None, se mantiene la posición actual.
        """
        if not self.etiquetas_detectadas:
            return

        # Guardar la etiqueta seleccionada antes de limpiar
        if preservar_etiqueta is None:
            sel = self.combo_etiquetas.GetSelection()
            if sel != wx.NOT_FOUND and sel < len(self.etiquetas_detectadas):
                preservar_etiqueta = self.etiquetas_detectadas[sel]

        self.combo_etiquetas.Clear()
        nueva_sel = 0
        for i, etiq in enumerate(self.etiquetas_detectadas):
            voz = self.asignaciones.get(etiq)
            if voz:
                item_texto = f"@{etiq} → {voz.get('nombre', '?')}"
            else:
                item_texto = "@{etiq} → {sin_asignar}".format(etiq=etiq, sin_asignar=_("(sin asignar)"))
            self.combo_etiquetas.Append(item_texto)
            if etiq == preservar_etiqueta:
                nueva_sel = i

        if self.combo_etiquetas.GetCount() > 0:
            self.combo_etiquetas.SetSelection(nueva_sel)

    def _actualizar_resumen_asignaciones(self):
        if not self.etiquetas_detectadas:
            self.txt_asignaciones.SetValue(_("Carga un archivo para ver las etiquetas."))
            return

        lineas = []
        for etiq in self.etiquetas_detectadas:
            voz = self.asignaciones.get(etiq)
            if voz:
                prov = voz.get('proveedor_id', 'local').capitalize()
                lineas.append(f"@{etiq}  →  {voz.get('nombre', '?')}  [{prov}]")
            else:
                lineas.append(_("@{etiqueta}  →  (sin asignar)").format(etiqueta=etiq))

        self.txt_asignaciones.SetValue('\n'.join(lineas))

    # ================================================================== #
    # Sliders velocidad / volumen de grabación
    # ================================================================== #

    def _al_cambiar_velocidad_grab(self, evento):
        v = self.deslizador_velocidad_grab.GetValue()
        self._guardar_ajuste_slider_grab("velocidad_grabacion", v)

    def _al_cambiar_volumen_grab(self, evento):
        v = self.deslizador_volumen_grab.GetValue()
        self._guardar_ajuste_slider_grab("volumen_grabacion", v)

    def _al_tecla_vel_grab(self, e):
        self._aplicar_salto_slider_grab(e, self.deslizador_velocidad_grab,
                                        self._al_cambiar_velocidad_grab)

    def _al_tecla_vol_grab(self, e):
        self._aplicar_salto_slider_grab(e, self.deslizador_volumen_grab,
                                        self._al_cambiar_volumen_grab)

    def _aplicar_salto_slider_grab(self, e, slider, callback):
        key = e.GetKeyCode()
        if key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            delta = -5 if key == wx.WXK_PAGEUP else 5
            nuevo = max(slider.GetMin(), min(slider.GetMax(), slider.GetValue() + delta))
            slider.SetValue(nuevo)
            callback(None)
        else:
            e.Skip()

    def _guardar_ajuste_slider_grab(self, clave, valor):
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
            logger.warning(f"[PestanaGrabacion] No se pudo guardar '{clave}': {e}")

    def _restaurar_sliders_grabacion(self):
        try:
            ruta = ruta_config("ajustes.json")
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                vel = int(datos.get("velocidad_grabacion", 50))
                vol = int(datos.get("volumen_grabacion", 100))
                self.deslizador_velocidad_grab.SetValue(vel)
                self.deslizador_volumen_grab.SetValue(vol)
        except Exception:
            logger.exception("Error al restaurar los deslizadores de velocidad/volumen de grabación")
            pass

    # ================================================================== #
    # Opciones de salida
    # ================================================================== #

    def al_cambiar_division(self, evento):
        """
        Actualiza el label del propio checkbox — cuando NVDA anuncia
        una casilla verbaliza su label + estado (marcada/desmarcada),
        por lo que el nuevo texto queda inmediatamente accesible.
        """
        reproducir(CLICK)
        if self.chk_dividir.IsChecked():
            self.chk_dividir.SetLabel(
                _("Dividir por etiquetas: archivos numerados (1. Nar.mp3, 2. Pj1.mp3…)")
            )
        else:
            self.chk_dividir.SetLabel(
                _("Dividir por etiquetas: un único archivo MP3 unificado")
            )

    # ================================================================== #
    # Persistencia del mapeo etiqueta → voz
    # ================================================================== #

    def _guardar_mapeo(self):
        mapeo = self._cargar_json(self.ruta_mapeo)
        if not isinstance(mapeo, dict):
            mapeo = {}
        titulo        = self._resolver_titulo()
        mapeo[titulo] = self.asignaciones
        self._guardar_json(self.ruta_mapeo, mapeo)

    def _cargar_mapeo(self, titulo: str):
        mapeo = self._cargar_json(self.ruta_mapeo)
        if not isinstance(mapeo, dict):
            return
        datos = mapeo.get(titulo, {})
        self.asignaciones = {
            k: v for k, v in datos.items()
            if k in self.etiquetas_detectadas
        }
        if self.asignaciones:
            self.lbl_progreso.SetLabel(
                _("Recuperadas {n} asignaciones previas para «{titulo}».").format(
                    n=len(self.asignaciones), titulo=titulo
                )
            )

    # ================================================================== #
    # Verbalización con pyttsx3 (voz del sistema)
    # ================================================================== #

    def _hablar(self, texto: str):
        """
        Verbaliza texto con la voz del sistema. Antes creaba una instancia
        de pyttsx3 nueva en el mismo proceso en cada llamada: ese patrón
        deja de sonar a partir del segundo o tercer aviso sin lanzar
        ninguna excepción (problema conocido del driver SAPI5, documentado
        en anunciador_voz.py), y el except: pass lo tragaba en silencio —
        así que la mitad de los fragmentos de una grabación larga podían
        quedar sin anunciar y nadie se enteraba. self._voz_grabacion
        (AnunciadorVoz) ya resuelve esto lanzando cada anuncio en un
        proceso nuevo, con el mismo mecanismo que usan el escaneo de
        Biblioteca y la Fase C del actualizador.
        """
        self._voz_grabacion.hablar(texto)

    # ================================================================== #
    # Proceso de grabación
    # ================================================================== #

    def _verificar_credenciales_previas(self) -> list:
        """
        Comprueba que cada proveedor de voz en uso tenga credenciales configuradas.
        Retorna lista de mensajes de error; vacía = todo OK.
        """
        errores = []
        # Las credenciales se guardan en claves_api.json (nunca en ajustes.json).
        config = cargar_claves()

        proveedores = set()
        for datos in self.asignaciones.values():
            if isinstance(datos, dict):
                proveedores.add(datos.get("proveedor_id", "local").lower())

        for prov in proveedores:
            if "azure" in prov:
                az = config.get("azure", {})
                if not az.get("key") or not az.get("region"):
                    errores.append(
                        _("Azure TTS: credenciales no configuradas "
                          "(clave de suscripción o región vacías).\n"
                          "Configúralas en Ajustes → Azure.")
                    )
            elif "eleven" in prov:
                el = config.get("elevenlabs", {})
                if not el.get("api_key"):
                    errores.append(
                        _("ElevenLabs: API Key no configurada.\n"
                          "Configúrala en Ajustes → ElevenLabs.")
                    )
            elif "polly" in prov:
                po = config.get("polly", {})
                if not po.get("access_key") or not po.get("secret_key"):
                    errores.append(
                        _("Amazon Polly: credenciales no configuradas "
                          "(Access Key / Secret Key vacíos).\n"
                          "Configúralas en Ajustes → Amazon Polly.")
                    )
            # 'local' (SAPI5): no requiere credenciales
        return errores

    def al_iniciar_grabacion(self, evento):
        if not self.fragmentos:
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("No hay texto cargado. Selecciona primero un archivo TXT."),
                _("Error"), wx.OK | wx.ICON_ERROR,
            )
            return

        titulo   = self._resolver_titulo()
        capitulo = self._resolver_capitulo()

        sin_voz = [e for e in self.etiquetas_detectadas if e not in self.asignaciones]
        if sin_voz:
            nombres = ', '.join('@' + e for e in sin_voz)
            reproducir(SND_ERROR)
            if wx.MessageBox(
                _("Las siguientes etiquetas no tienen voz asignada:\n{nombres}\n\n"
                  "Los fragmentos sin voz se omitirán.\n"
                  "¿Continuar de todas formas?").format(nombres=nombres),
                _("Etiquetas sin voz"), wx.YES_NO | wx.ICON_WARNING,
            ) != wx.YES:
                return

        # ── Pre-chequeo preventivo de credenciales ────────────────────────────
        fallos_cred = self._verificar_credenciales_previas()
        if fallos_cred:
            detalle = "\n\n".join(fallos_cred)
            reproducir(SND_ERROR)
            wx.MessageBox(
                _("No se puede iniciar la grabación:\n\n{detalle}\n\n"
                  "Revisa la configuración antes de continuar.").format(detalle=detalle),
                _("Credenciales no configuradas"),
                wx.OK | wx.ICON_ERROR,
            )
            return

        modo_dividido = self.chk_dividir.IsChecked()
        self._modo_dividido = modo_dividido   # accesible desde _callback_progreso
        velocidad_grab = self.deslizador_velocidad_grab.GetValue()
        volumen_grab   = self.deslizador_volumen_grab.GetValue()

        self.btn_iniciar.Enable(False)
        self.btn_abortar.Enable(True)
        self.gauge.SetValue(0)
        self.lbl_progreso.SetLabel(_("Iniciando grabación…"))
        reproducir(REC_START)

        self.titulo_libro    = titulo
        self._ultima_carpeta = None
        self.grabador = GrabadorAudio(callback_progreso=self._callback_progreso)

        self._hilo_grabacion = threading.Thread(
            target=self._ejecutar_grabacion,
            args=(titulo, capitulo, modo_dividido, velocidad_grab, volumen_grab),
            daemon=True,
        )
        self._hilo_grabacion.start()

    def _callback_progreso(self, actual, total, etiqueta, nombre_voz):
        pct = int((actual / total) * 100) if total > 0 else 0
        msg = _("Grabando fragmento {actual} de {total}  (Etiqueta: @{etiqueta}  —  Voz: {voz})").format(
            actual=actual, total=total, etiqueta=etiqueta, voz=nombre_voz
        )
        wx.CallAfter(self._actualizar_progreso_ui, pct, msg)

        modo_dividido = self._modo_dividido
        texto_voz = _("Fragmento {actual} de {total}. Etiqueta {etiqueta}.").format(
            actual=actual, total=total, etiqueta=etiqueta
        )
        # self._hablar() ya encola en AnunciadorVoz (su propio hilo de
        # fondo); envolverlo en otro hilo aquí era redundante.
        self._hablar(texto_voz)
        if not modo_dividido:
            # Modo audio único: el tick de progreso rítmico se mantiene como
            # refuerzo sonoro, pero ya no es la única señal — antes era el
            # único aviso mientras se grababa, y la voz se quedaba muda hasta
            # el final (solo decía cuántos archivos se habían completado).
            wx.CallAfter(reproducir, PROGRESS)

    def _actualizar_progreso_ui(self, pct, msg):
        self.gauge.SetValue(pct)
        self.lbl_progreso.SetLabel(msg)

    def _ejecutar_grabacion(self, titulo, capitulo, modo_dividido, velocidad=50, volumen=100):
        try:
            archivos, errores, carpeta = self.grabador.grabar_fragmentos(
                fragmentos=self.fragmentos,
                asignaciones_voz=self.asignaciones,
                titulo_libro=titulo,
                nombre_capitulo=capitulo,
                modo_dividido=modo_dividido,
                velocidad=velocidad,
                volumen=volumen,
            )
            wx.CallAfter(self._al_terminar_grabacion, archivos, errores, carpeta)
        except Exception as e:
            logger.exception("Error durante la grabación de fragmentos")
            wx.CallAfter(self._al_error_grabacion, str(e))

    def _al_terminar_grabacion(self, archivos, errores, carpeta):
        self.btn_iniciar.Enable(True)
        self.btn_abortar.Enable(False)
        self._ultima_carpeta = carpeta
        self.gauge.SetValue(100)

        # ── Validar que los archivos existen físicamente y tienen contenido ────
        archivos_reales = [
            a for a in archivos
            if os.path.exists(a) and os.path.getsize(a) > 0
        ]
        n              = len(archivos_reales)
        nombre_carpeta = os.path.basename(carpeta)

        if n == 0:
            # Ningún archivo de audio válido generado → error real
            reproducir(SND_ERROR)
            self.lbl_progreso.SetLabel(
                _("Error: no se generó ningún archivo de audio válido.")
            )
            detalle = ""
            if errores:
                resumen = "\n".join(errores[:5])
                if len(errores) > 5:
                    resumen += "\n" + _("… y {n} errores más.").format(n=len(errores) - 5)
                detalle = _("\n\nDetalle de errores:\n{resumen}").format(resumen=resumen)
            wx.MessageBox(
                _("La grabación finalizó pero no se generó ningún archivo de audio válido.\n"
                  "Es posible que las credenciales del servicio sean incorrectas "
                  "o que no haya conexión a Internet.{detalle}\n\n"
                  "Revisa la configuración y vuelve a intentarlo.").format(detalle=detalle),
                _("Error de grabación"),
                wx.OK | wx.ICON_ERROR,
            )
            return

        # ── Éxito (con o sin errores parciales) ───────────────────────────────
        self.lbl_progreso.SetLabel(
            _("Proceso finalizado. {n} archivo(s) generado(s) en {carpeta}.").format(
                n=n, carpeta=nombre_carpeta
            )
        )
        reproducir(SUCCESS)   # único feedback de finalización — no duplicar
        threading.Thread(
            target=self._hablar,
            args=(_("Grabación completada. {n} archivos generados.").format(n=n),),
            daemon=True,
        ).start()

        cuerpo = _("Proceso finalizado con éxito.\n{n} archivo(s) en:\n{carpeta}").format(
            n=n, carpeta=carpeta
        )
        if errores:
            resumen = "\n".join(errores[:5])
            if len(errores) > 5:
                resumen += "\n" + _("… y {n} errores más.").format(n=len(errores) - 5)
            cuerpo += "\n\n" + _("⚠ {n} fragmento(s) fallido(s):\n{resumen}").format(
                n=len(errores), resumen=resumen
            )

        cuerpo += "\n\n" + _("¿Deseas abrir la carpeta de destino?")

        dlg = wx.MessageDialog(
            self, cuerpo, _("Grabación completada"), wx.YES_NO | wx.ICON_INFORMATION
        )
        resultado = dlg.ShowModal()
        dlg.Destroy()

        if resultado == wx.ID_YES and carpeta and os.path.exists(carpeta):
            self._abrir_carpeta_en_explorador(carpeta)

    def _al_error_grabacion(self, error):
        self.btn_iniciar.Enable(True)
        self.btn_abortar.Enable(False)
        self.lbl_progreso.SetLabel(_("Error durante la grabación: {error}").format(error=error))
        reproducir(SND_ERROR)
        wx.MessageBox(
            _("Error durante la grabación:\n\n{error}").format(error=error),
            _("Error de grabación"), wx.OK | wx.ICON_ERROR,
        )

    def al_abortar(self, evento):
        if self.grabador:
            self.grabador.abortar()
        self.lbl_progreso.SetLabel(_("Estado: Grabación abortada por el usuario."))
        self.btn_abortar.Enable(False)
        self.btn_iniciar.Enable(True)

    # ================================================================== #
    # Apertura de carpeta
    # ================================================================== #

    def al_abrir_carpeta(self, evento):
        carpeta = self._ultima_carpeta

        if not carpeta or not os.path.exists(carpeta):
            titulo  = self._resolver_titulo()
            carpeta = os.path.join(
                CARPETA_RAIZ_GRABACIONES,
                limpiar_nombre_archivo(titulo),
            )

        if not os.path.exists(carpeta):
            carpeta = CARPETA_RAIZ_GRABACIONES
            os.makedirs(carpeta, exist_ok=True)

        self._abrir_carpeta_en_explorador(carpeta)

    def _abrir_carpeta_en_explorador(self, ruta):
        reproducir(OPEN_FOLDER)
        ruta_abs = os.path.abspath(ruta)
        try:
            subprocess.Popen(['explorer', ruta_abs])
        except Exception:
            try:
                os.startfile(ruta_abs)
            except Exception as e:
                reproducir(SND_ERROR)
                wx.MessageBox(
                    _("No se pudo abrir la carpeta:\n{error}").format(error=e),
                    _("Error"), wx.OK | wx.ICON_WARNING,
                )
