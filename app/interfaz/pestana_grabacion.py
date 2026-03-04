"""
pestana_grabacion.py
---------------------
Pestaña de grabación multivoz para producción de audiolibros accesibles.

Características:
  - Carga de archivos TXT con etiquetas {{@nombre}} (case-insensitive).
  - Panel de casting: asignación flexible de voces a etiquetas.
  - Persistencia de asignaciones en mapeo_etiquetas.json por título de libro.
  - Modos de salida: archivos divididos por etiqueta o un único MP3 concatenado.
  - Jerarquía de carpetas: Grabaciones_TifloHistorias/[Libro]/[Subcarpeta].
  - Anuncios accesibles para NVDA en cada cambio de estado relevante.
  - Título y capítulo opcionales: si se omiten se usa el nombre del archivo TXT.
  - Proceso de grabación en hilo de fondo (UI nunca se congela).
  - Botón Abortar: detiene la grabación sin cerrar la aplicación.
  - 3 reintentos por fragmento antes de registrar error.
"""

import wx
import os
import json
import threading
import subprocess
import logging

from app.config_rutas import ruta_config
from app.motor.procesador_etiquetas import (
    escanear_etiquetas,
    fragmentar_texto,
    normalizar_etiqueta,
    limpiar_nombre_archivo,
)
from app.motor.grabador_audio import GrabadorAudio, CARPETA_RAIZ_GRABACIONES

logger = logging.getLogger(__name__)


class PestanaGrabacion(wx.Panel):
    """Panel principal de la interfaz de grabación multivoz."""

    def __init__(self, padre):
        super().__init__(padre, style=wx.TAB_TRAVERSAL)

        # Estado interno
        self.ruta_txt_actual = None
        self.nombre_base_txt = ""       # Nombre del TXT sin extensión (fallback de título/capítulo)
        self.texto_cargado = ""
        self.fragmentos = []            # [(etiqueta, contenido), ...]
        self.etiquetas_detectadas = []  # [etiqueta_normalizada, ...]
        self.asignaciones = {}          # {etiqueta: datos_voz}
        self.voces_disponibles = []     # [(texto_display, datos_voz), ...]
        self.titulo_libro = ""
        self.grabador = None
        self._hilo_grabacion = None
        self._ultima_carpeta = None

        # Rutas de configuración (absolutas, usando config_rutas de Fase 1)
        self.ruta_mapeo = ruta_config("mapeo_etiquetas.json")
        self.ruta_favs = ruta_config("voces_favoritas.json")
        self.ruta_todas = ruta_config("voces_disponibles.json")

        self._construir_interfaz()
        self._cargar_voces_disponibles()

    # ================================================================== #
    # Construcción de la interfaz
    # ================================================================== #

    def _construir_interfaz(self):
        sizer_raiz = wx.BoxSizer(wx.VERTICAL)

        # ---- Carga de archivo ---- #
        box_carga = wx.StaticBox(self, label="Cargar texto con etiquetas")
        sizer_carga = wx.StaticBoxSizer(box_carga, wx.VERTICAL)

        # Fila: ruta del archivo
        sizer_ruta = wx.BoxSizer(wx.HORIZONTAL)
        lbl_ruta = wx.StaticText(self, label="Archivo TXT:")
        self.txt_ruta = wx.TextCtrl(self, style=wx.TE_READONLY)
        self.txt_ruta.SetName("Ruta del archivo de texto seleccionado")
        self.btn_examinar = wx.Button(self, label="&Examinar…")
        self.btn_examinar.SetName("Abrir explorador para seleccionar archivo TXT")
        sizer_ruta.Add(lbl_ruta, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer_ruta.Add(self.txt_ruta, 1, wx.EXPAND)
        sizer_ruta.Add(self.btn_examinar, 0, wx.LEFT, 5)

        # Fila: título del libro (opcional)
        sizer_titulo = wx.BoxSizer(wx.HORIZONTAL)
        lbl_titulo = wx.StaticText(self, label="Título del libro (opcional):")
        self.txt_titulo = wx.TextCtrl(self)
        self.txt_titulo.SetName(
            "Título del libro. Opcional. Si se deja vacío se usa el nombre del archivo."
        )
        sizer_titulo.Add(lbl_titulo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer_titulo.Add(self.txt_titulo, 1, wx.EXPAND)

        # Fila: nombre del capítulo (opcional)
        sizer_capitulo = wx.BoxSizer(wx.HORIZONTAL)
        lbl_cap = wx.StaticText(self, label="Nombre del capítulo (opcional):")
        self.txt_capitulo = wx.TextCtrl(self)
        self.txt_capitulo.SetName(
            "Nombre del capítulo. Opcional. Si se deja vacío se usa el nombre del archivo."
        )
        sizer_capitulo.Add(lbl_cap, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer_capitulo.Add(self.txt_capitulo, 1, wx.EXPAND)

        self.btn_cargar = wx.Button(self, label="&Cargar y Escanear Etiquetas")
        self.btn_cargar.SetName(
            "Leer el archivo y detectar todas las etiquetas de personaje"
        )

        sizer_carga.Add(sizer_ruta, 0, wx.EXPAND | wx.ALL, 5)
        sizer_carga.Add(sizer_titulo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        sizer_carga.Add(sizer_capitulo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        sizer_carga.Add(self.btn_cargar, 0, wx.LEFT | wx.BOTTOM, 5)

        # ---- Casting de voces ---- #
        box_casting = wx.StaticBox(self, label="Casting de voces")
        sizer_casting = wx.StaticBoxSizer(box_casting, wx.VERTICAL)

        sizer_cols = wx.BoxSizer(wx.HORIZONTAL)

        # Columna izquierda: Etiquetas
        sizer_etiq = wx.BoxSizer(wx.VERTICAL)
        lbl_etiq = wx.StaticText(self, label="Etiquetas detectadas:")
        self.combo_etiquetas = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_etiquetas.SetName(
            "Selector de etiqueta de personaje. Selecciona la etiqueta a la que "
            "quieres asignar una voz."
        )
        sizer_etiq.Add(lbl_etiq, 0, wx.BOTTOM, 3)
        sizer_etiq.Add(self.combo_etiquetas, 0, wx.EXPAND)

        # Columna derecha: Voces favoritas
        sizer_voces = wx.BoxSizer(wx.VERTICAL)
        lbl_voces = wx.StaticText(self, label="Voces favoritas disponibles:")
        self.check_voces = wx.CheckListBox(self)
        self.check_voces.SetName(
            "Lista de voces favoritas. Marca una voz y pulsa Asignar para "
            "vincularla a la etiqueta seleccionada. La misma voz puede asignarse "
            "a varias etiquetas."
        )
        sizer_voces.Add(lbl_voces, 0, wx.BOTTOM, 3)
        sizer_voces.Add(self.check_voces, 1, wx.EXPAND)

        sizer_cols.Add(sizer_etiq, 1, wx.EXPAND | wx.RIGHT, 10)
        sizer_cols.Add(sizer_voces, 2, wx.EXPAND)

        # Botones del panel de casting
        sizer_btn_casting = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_asignar = wx.Button(self, label="&Asignar voz a etiqueta")
        self.btn_asignar.SetName(
            "Asignar la voz marcada en la lista a la etiqueta seleccionada en el combo"
        )
        self.btn_probar = wx.Button(self, label="&Probar Voz")
        self.btn_probar.SetName(
            "Reproducir una muestra de la voz marcada en la lista de voces"
        )
        sizer_btn_casting.Add(self.btn_asignar, 0, wx.RIGHT, 5)
        sizer_btn_casting.Add(self.btn_probar, 0)

        # Resumen de asignaciones (lectura por NVDA al tabular)
        lbl_asign = wx.StaticText(self, label="Asignaciones actuales:")
        self.txt_asignaciones = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 90),
        )
        self.txt_asignaciones.SetName(
            "Resumen de asignaciones. Muestra qué voz está asignada a cada etiqueta."
        )

        sizer_casting.Add(sizer_cols, 1, wx.EXPAND | wx.ALL, 5)
        sizer_casting.Add(sizer_btn_casting, 0, wx.LEFT | wx.BOTTOM, 5)
        sizer_casting.Add(lbl_asign, 0, wx.LEFT | wx.TOP, 5)
        sizer_casting.Add(self.txt_asignaciones, 0, wx.EXPAND | wx.ALL, 5)

        # ---- Opciones de salida ---- #
        box_opciones = wx.StaticBox(self, label="Opciones de salida")
        sizer_opciones = wx.StaticBoxSizer(box_opciones, wx.VERTICAL)

        self.chk_dividir = wx.CheckBox(
            self,
            label="&Dividir en múltiples archivos numerados (uno por etiqueta)",
        )
        self.chk_dividir.SetName(
            "Casilla Dividir. Activa para generar un archivo separado por cada "
            "fragmento de etiqueta. Desactiva para obtener un único MP3 unificado."
        )
        self.chk_dividir.SetValue(True)

        # StaticText de estado — NVDA lo lee al navegar sobre él o al actualizarse
        self.lbl_estado_division = wx.StaticText(
            self,
            label="Estado: Generando múltiples archivos numerados por etiqueta",
        )
        self.lbl_estado_division.SetName(
            "Descripción del modo de salida de audio seleccionado"
        )

        sizer_opciones.Add(self.chk_dividir, 0, wx.ALL, 5)
        sizer_opciones.Add(self.lbl_estado_division, 0, wx.LEFT | wx.BOTTOM, 10)

        # ---- Progreso de la grabación ---- #
        box_progreso = wx.StaticBox(self, label="Progreso de la grabación")
        sizer_progreso_box = wx.StaticBoxSizer(box_progreso, wx.VERTICAL)

        self.lbl_progreso = wx.StaticText(
            self,
            label="Estado: En espera. Carga un archivo para comenzar.",
        )
        self.lbl_progreso.SetName(
            "Estado actual del proceso de grabación. "
            "Informa del fragmento en curso, etiqueta y voz utilizada."
        )

        self.gauge = wx.Gauge(self, range=100)
        self.gauge.SetName("Barra de progreso visual de la grabación")

        sizer_progreso_box.Add(self.lbl_progreso, 0, wx.EXPAND | wx.ALL, 5)
        sizer_progreso_box.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ---- Botones principales ---- #
        sizer_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_iniciar = wx.Button(self, label="&Iniciar Grabación")
        self.btn_iniciar.SetName(
            "Iniciar el proceso de grabación multivoz en segundo plano"
        )
        self.btn_iniciar.Enable(False)

        self.btn_abortar = wx.Button(self, label="A&bortar")
        self.btn_abortar.SetName(
            "Detener la grabación inmediatamente sin cerrar la aplicación"
        )
        self.btn_abortar.Enable(False)

        self.btn_abrir_carpeta = wx.Button(self, label="A&brir Carpeta de Destino")
        self.btn_abrir_carpeta.SetName(
            "Abrir en el Explorador de Windows la carpeta donde se guardaron "
            "los archivos de audio generados"
        )
        self.btn_abrir_carpeta.Enable(False)

        sizer_botones.Add(self.btn_iniciar, 0, wx.RIGHT, 5)
        sizer_botones.Add(self.btn_abortar, 0, wx.RIGHT, 5)
        sizer_botones.Add(self.btn_abrir_carpeta, 0)

        # ---- Ensamblado final ---- #
        sizer_raiz.Add(sizer_carga, 0, wx.EXPAND | wx.ALL, 6)
        sizer_raiz.Add(sizer_casting, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sizer_opciones, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sizer_progreso_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sizer_botones, 0, wx.ALL, 10)

        self.SetSizer(sizer_raiz)

        # ---- Vincular eventos ---- #
        self.btn_examinar.Bind(wx.EVT_BUTTON, self.al_examinar)
        self.btn_cargar.Bind(wx.EVT_BUTTON, self.al_cargar_y_escanear)
        self.btn_asignar.Bind(wx.EVT_BUTTON, self.al_asignar_voz)
        self.btn_probar.Bind(wx.EVT_BUTTON, self.al_probar_voz)
        self.chk_dividir.Bind(wx.EVT_CHECKBOX, self.al_cambiar_division)
        self.btn_iniciar.Bind(wx.EVT_BUTTON, self.al_iniciar_grabacion)
        self.btn_abortar.Bind(wx.EVT_BUTTON, self.al_abortar)
        self.btn_abrir_carpeta.Bind(wx.EVT_BUTTON, self.al_abrir_carpeta)
        self.check_voces.Bind(wx.EVT_CHECKLISTBOX, self.al_marcar_voz)

    # ================================================================== #
    # Helpers de nombre (título/capítulo opcionales)
    # ================================================================== #

    def _resolver_titulo(self) -> str:
        """Devuelve el título introducido o, si está vacío, el nombre del archivo TXT."""
        t = self.txt_titulo.GetValue().strip()
        return t if t else (self.nombre_base_txt or "Sin_Titulo")

    def _resolver_capitulo(self) -> str:
        """Devuelve el capítulo introducido o, si está vacío, el nombre del archivo TXT."""
        c = self.txt_capitulo.GetValue().strip()
        return c if c else (self.nombre_base_txt or "Sin_Capitulo")

    # ================================================================== #
    # Carga de voces disponibles
    # ================================================================== #

    def _cargar_voces_disponibles(self):
        """Puebla check_voces con las voces favoritas y las voces locales SAPI5."""
        self.voces_disponibles = []
        self.check_voces.Clear()

        # 1. Voces neuronales favoritas
        ids_favs = []
        try:
            if os.path.exists(self.ruta_favs):
                with open(self.ruta_favs, 'r', encoding='utf-8') as f:
                    ids_favs = json.load(f)
        except Exception:
            pass

        if ids_favs and os.path.exists(self.ruta_todas):
            try:
                with open(self.ruta_todas, 'r', encoding='utf-8') as f:
                    todas = json.load(f)
                for prov, lista in todas.items():
                    for v in lista:
                        if v.get('id') in ids_favs:
                            v_copy = dict(v)
                            v_copy['proveedor_id'] = prov
                            nombre_disp = (
                                f"[{prov.capitalize()}] "
                                f"{v_copy.get('nombre', 'Sin nombre')} "
                                f"({v_copy.get('idioma', '')})"
                            )
                            self.voces_disponibles.append((nombre_disp, v_copy))
            except Exception as e:
                logger.warning(f"[PestanaGrabacion] Error cargando voces favoritas: {e}")

        # 2. Voces locales SAPI5
        try:
            import comtypes.client
            sapi = comtypes.client.CreateObject("SAPI.SpVoice")
            voces_sapi = sapi.GetVoices()
            for i in range(voces_sapi.Count):
                v = voces_sapi.Item(i)
                desc = v.GetDescription()
                datos = {"id": v.Id, "nombre": desc, "proveedor_id": "local"}
                nombre_disp = f"[Local] {desc}"
                self.voces_disponibles.append((nombre_disp, datos))
        except Exception:
            pass

        # Poblar CheckListBox
        if self.voces_disponibles:
            for nombre_disp, _ in self.voces_disponibles:
                self.check_voces.Append(nombre_disp)
        else:
            self.check_voces.Append(
                "No hay voces. Marca favoritas en la pestaña Ajustes."
            )

    # ================================================================== #
    # Carga de archivo y escaneo
    # ================================================================== #

    def al_examinar(self, evento):
        """Abre el explorador de archivos para seleccionar un TXT."""
        with wx.FileDialog(
            self,
            "Seleccionar archivo de texto con etiquetas",
            wildcard=(
                "Archivos de texto (*.txt)|*.txt"
                "|Todos los archivos (*.*)|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.ruta_txt_actual = dlg.GetPath()
                self.txt_ruta.SetValue(self.ruta_txt_actual)
                self.nombre_base_txt = os.path.splitext(
                    os.path.basename(self.ruta_txt_actual)
                )[0]

                # Sugerir título/capítulo solo si están completamente vacíos
                if not self.txt_titulo.GetValue().strip():
                    self.txt_titulo.SetValue(self.nombre_base_txt)
                if not self.txt_capitulo.GetValue().strip():
                    self.txt_capitulo.SetValue(self.nombre_base_txt)

    def al_cargar_y_escanear(self, evento):
        """Lee el archivo TXT, detecta etiquetas y prepara el panel de casting."""
        if not self.ruta_txt_actual:
            wx.MessageBox(
                "Primero selecciona un archivo TXT pulsando el botón Examinar.",
                "Sin archivo",
                wx.OK | wx.ICON_WARNING,
            )
            return

        try:
            with open(self.ruta_txt_actual, 'r', encoding='utf-8') as f:
                self.texto_cargado = f.read()
        except Exception as e:
            wx.MessageBox(
                f"No se pudo leer el archivo:\n{e}",
                "Error de lectura",
                wx.OK | wx.ICON_ERROR,
            )
            return

        if not self.texto_cargado.strip():
            wx.MessageBox("El archivo está vacío.", "Sin contenido", wx.OK | wx.ICON_WARNING)
            return

        # Fragmentar y obtener etiquetas únicas en orden de aparición
        self.fragmentos = fragmentar_texto(self.texto_cargado)
        if not self.fragmentos:
            wx.MessageBox(
                "El archivo no contiene texto aprovechable.",
                "Sin fragmentos",
                wx.OK | wx.ICON_WARNING,
            )
            return

        vistas = set()
        self.etiquetas_detectadas = []
        for etiq, _ in self.fragmentos:
            if etiq not in vistas:
                self.etiquetas_detectadas.append(etiq)
                vistas.add(etiq)

        # Actualizar ComboBox de etiquetas
        self.combo_etiquetas.Clear()
        for etiq in self.etiquetas_detectadas:
            self.combo_etiquetas.Append(f"@{etiq}")
        if self.combo_etiquetas.GetCount() > 0:
            self.combo_etiquetas.SetSelection(0)

        # Recuperar asignaciones previas si existen para este título
        titulo = self._resolver_titulo()
        self.titulo_libro = titulo
        self.asignaciones = {}
        self._cargar_mapeo(titulo)
        self._actualizar_resumen_asignaciones()

        total = len(self.fragmentos)
        self.lbl_progreso.SetLabel(
            f"Estado: {total} fragmentos detectados. "
            f"Etiquetas: {', '.join('@' + e for e in self.etiquetas_detectadas)}. "
            f"Asigna voces y pulsa Iniciar Grabación."
        )
        self.btn_iniciar.Enable(True)

        wx.MessageBox(
            f"Texto cargado correctamente.\n\n"
            f"Fragmentos: {total}\n"
            f"Etiquetas únicas: {', '.join('@' + e for e in self.etiquetas_detectadas)}",
            "Escaneo completado",
            wx.OK | wx.ICON_INFORMATION,
        )

    # ================================================================== #
    # Panel de casting
    # ================================================================== #

    def al_marcar_voz(self, evento):
        """Comportamiento tipo radio: marcar una voz desmarca las demás."""
        idx_marcado = evento.GetInt()
        for i in range(self.check_voces.GetCount()):
            if i != idx_marcado:
                self.check_voces.Check(i, False)

    def _obtener_voz_marcada(self):
        """Devuelve (nombre_display, datos_voz) de la voz marcada, o (None, None)."""
        for i in range(self.check_voces.GetCount()):
            if self.check_voces.IsChecked(i):
                if i < len(self.voces_disponibles):
                    return self.voces_disponibles[i]
        return None, None

    def al_asignar_voz(self, evento):
        """Asigna la voz marcada a la etiqueta seleccionada en el combo."""
        idx_etiq = self.combo_etiquetas.GetSelection()
        if idx_etiq == wx.NOT_FOUND:
            wx.MessageBox(
                "Selecciona una etiqueta en la lista superior.",
                "Sin etiqueta seleccionada",
                wx.OK | wx.ICON_WARNING,
            )
            return

        nombre_voz_disp, datos_voz = self._obtener_voz_marcada()
        if datos_voz is None:
            wx.MessageBox(
                "Marca una voz en la lista de voces favoritas.",
                "Sin voz marcada",
                wx.OK | wx.ICON_WARNING,
            )
            return

        etiqueta_raw = self.combo_etiquetas.GetString(idx_etiq)
        etiqueta = normalizar_etiqueta(etiqueta_raw.lstrip('@'))

        self.asignaciones[etiqueta] = datos_voz
        self._guardar_mapeo()
        self._actualizar_resumen_asignaciones()

        self.lbl_progreso.SetLabel(
            f"Voz «{nombre_voz_disp}» asignada a la etiqueta «@{etiqueta}»."
        )

    def al_probar_voz(self, evento):
        """Reproduce una muestra de la voz marcada (en hilo de fondo)."""
        nombre_voz_disp, datos_voz = self._obtener_voz_marcada()
        if datos_voz is None:
            wx.MessageBox(
                "Marca una voz en la lista para poder probarla.",
                "Sin selección",
                wx.OK | wx.ICON_WARNING,
            )
            return

        def _probar():
            try:
                GrabadorAudio().probar_voz(datos_voz)
            except Exception as e:
                wx.CallAfter(
                    wx.MessageBox,
                    f"Error al probar la voz:\n{e}",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        threading.Thread(target=_probar, daemon=True).start()

    def _actualizar_resumen_asignaciones(self):
        """Actualiza el campo de texto con el estado actual de las asignaciones."""
        if not self.etiquetas_detectadas:
            self.txt_asignaciones.SetValue("Carga un archivo para ver las etiquetas.")
            return

        lineas = []
        for etiq in self.etiquetas_detectadas:
            voz = self.asignaciones.get(etiq)
            if voz:
                nombre_voz = voz.get('nombre', 'Desconocida')
                prov = voz.get('proveedor_id', 'local').capitalize()
                lineas.append(f"@{etiq}  →  {nombre_voz}  [{prov}]")
            else:
                lineas.append(f"@{etiq}  →  (sin asignar)")

        self.txt_asignaciones.SetValue('\n'.join(lineas))

    # ================================================================== #
    # Opciones de salida
    # ================================================================== #

    def al_cambiar_division(self, evento):
        """Actualiza el StaticText de estado para que NVDA lo anuncie al navegar."""
        if self.chk_dividir.IsChecked():
            self.lbl_estado_division.SetLabel(
                "Estado: Generando múltiples archivos numerados por etiqueta"
            )
        else:
            self.lbl_estado_division.SetLabel(
                "Estado: Generando un único archivo MP3 integrado"
            )

    # ================================================================== #
    # Persistencia de mapeo etiqueta → voz
    # ================================================================== #

    def _guardar_mapeo(self):
        """Guarda las asignaciones actuales en mapeo_etiquetas.json."""
        try:
            mapeo = {}
            if os.path.exists(self.ruta_mapeo):
                with open(self.ruta_mapeo, 'r', encoding='utf-8') as f:
                    mapeo = json.load(f)

            titulo = self._resolver_titulo()
            mapeo[titulo] = self.asignaciones

            os.makedirs(os.path.dirname(self.ruta_mapeo), exist_ok=True)
            with open(self.ruta_mapeo, 'w', encoding='utf-8') as f:
                json.dump(mapeo, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[PestanaGrabacion] No se pudo guardar mapeo: {e}")

    def _cargar_mapeo(self, titulo: str):
        """Recupera asignaciones previas para el título dado."""
        try:
            if os.path.exists(self.ruta_mapeo):
                with open(self.ruta_mapeo, 'r', encoding='utf-8') as f:
                    mapeo = json.load(f)

                datos_guardados = mapeo.get(titulo, {})
                self.asignaciones = {
                    k: v
                    for k, v in datos_guardados.items()
                    if k in self.etiquetas_detectadas
                }

                if self.asignaciones:
                    self.lbl_progreso.SetLabel(
                        f"Se recuperaron {len(self.asignaciones)} "
                        f"asignaciones previas para «{titulo}»."
                    )
        except Exception as e:
            logger.warning(f"[PestanaGrabacion] No se pudo cargar mapeo: {e}")

    # ================================================================== #
    # Proceso de grabación
    # ================================================================== #

    def al_iniciar_grabacion(self, evento):
        """Valida entradas y lanza el proceso de grabación en segundo plano."""
        if not self.fragmentos:
            wx.MessageBox(
                "No hay texto cargado. Carga un archivo TXT primero.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )
            return

        titulo = self._resolver_titulo()
        capitulo = self._resolver_capitulo()

        # Advertir si hay etiquetas sin voz asignada
        sin_voz = [e for e in self.etiquetas_detectadas if e not in self.asignaciones]
        if sin_voz:
            nombres = ', '.join('@' + e for e in sin_voz)
            if wx.MessageBox(
                f"Las siguientes etiquetas no tienen voz asignada:\n{nombres}\n\n"
                "Los fragmentos sin voz se omitirán del audio final.\n"
                "¿Deseas continuar de todas formas?",
                "Etiquetas sin voz",
                wx.YES_NO | wx.ICON_WARNING,
            ) != wx.YES:
                return

        modo_dividido = self.chk_dividir.IsChecked()

        # Actualizar UI
        self.btn_iniciar.Enable(False)
        self.btn_abortar.Enable(True)
        self.btn_abrir_carpeta.Enable(False)
        self.gauge.SetValue(0)
        self.lbl_progreso.SetLabel("Iniciando grabación…")

        self.titulo_libro = titulo
        self._ultima_carpeta = None
        self.grabador = GrabadorAudio(callback_progreso=self._callback_progreso)

        self._hilo_grabacion = threading.Thread(
            target=self._ejecutar_grabacion,
            args=(titulo, capitulo, modo_dividido),
            daemon=True,
        )
        self._hilo_grabacion.start()

    def _callback_progreso(self, actual: int, total: int, etiqueta: str, nombre_voz: str):
        """Llamado desde el hilo de grabación; delega la actualización a wx.CallAfter."""
        porcentaje = int((actual / total) * 100) if total > 0 else 0
        mensaje = (
            f"Grabando fragmento {actual} de {total}  "
            f"(Etiqueta: @{etiqueta}  —  Voz: {nombre_voz})"
        )
        wx.CallAfter(self._actualizar_progreso_ui, porcentaje, mensaje)

    def _actualizar_progreso_ui(self, porcentaje: int, mensaje: str):
        """Actualiza gauge y label de progreso desde el hilo principal."""
        self.gauge.SetValue(porcentaje)
        self.lbl_progreso.SetLabel(mensaje)

    def _ejecutar_grabacion(self, titulo: str, capitulo: str, modo_dividido: bool):
        """Cuerpo del hilo de grabación."""
        try:
            archivos, errores, carpeta = self.grabador.grabar_fragmentos(
                fragmentos=self.fragmentos,
                asignaciones_voz=self.asignaciones,
                titulo_libro=titulo,
                nombre_capitulo=capitulo,
                modo_dividido=modo_dividido,
            )
            wx.CallAfter(self._al_terminar_grabacion, archivos, errores, carpeta)
        except Exception as e:
            wx.CallAfter(self._al_error_grabacion, str(e))

    def _al_terminar_grabacion(self, archivos: list, errores: list, carpeta: str):
        """Ejecutado en el hilo principal cuando la grabación ha finalizado."""
        self.btn_iniciar.Enable(True)
        self.btn_abortar.Enable(False)
        self._ultima_carpeta = carpeta
        self.btn_abrir_carpeta.Enable(True)
        self.gauge.SetValue(100)

        n = len(archivos)
        nombre_carpeta = os.path.basename(carpeta)

        # Mensaje de éxito — NVDA lo lee al enfocar el label o al aparecer el diálogo
        self.lbl_progreso.SetLabel(
            f"Proceso finalizado con éxito. "
            f"{n} archivos generados en la carpeta {nombre_carpeta}."
        )

        cuerpo = (
            f"Proceso finalizado con éxito.\n"
            f"{n} archivo(s) generado(s) en la carpeta:\n{carpeta}"
        )
        if errores:
            resumen_errores = "\n".join(errores[:5])
            if len(errores) > 5:
                resumen_errores += f"\n… y {len(errores) - 5} errores más."
            cuerpo += f"\n\n⚠ Se registraron {len(errores)} errores:\n{resumen_errores}"

        cuerpo += "\n\n¿Deseas abrir la carpeta de destino?"

        dlg = wx.MessageDialog(
            self,
            cuerpo,
            "Grabación completada",
            wx.YES_NO | wx.ICON_INFORMATION,
        )
        resultado = dlg.ShowModal()
        dlg.Destroy()

        if resultado == wx.ID_YES and carpeta and os.path.exists(carpeta):
            self._abrir_carpeta_en_explorador(carpeta)

    def _al_error_grabacion(self, error: str):
        """Ejecutado en el hilo principal si la grabación lanza una excepción."""
        self.btn_iniciar.Enable(True)
        self.btn_abortar.Enable(False)
        self.lbl_progreso.SetLabel(f"Error durante la grabación: {error}")
        wx.MessageBox(
            f"Se produjo un error durante la grabación:\n\n{error}",
            "Error de grabación",
            wx.OK | wx.ICON_ERROR,
        )

    def al_abortar(self, evento):
        """Señala al grabador para que detenga el proceso en curso."""
        if self.grabador:
            self.grabador.abortar()
        self.lbl_progreso.SetLabel("Estado: Grabación abortada por el usuario.")
        self.btn_abortar.Enable(False)
        self.btn_iniciar.Enable(True)

    # ================================================================== #
    # Apertura de carpeta de destino
    # ================================================================== #

    def al_abrir_carpeta(self, evento):
        """Abre la carpeta de destino en el Explorador de Windows."""
        carpeta = self._ultima_carpeta

        if not carpeta or not os.path.exists(carpeta):
            titulo = self._resolver_titulo()
            if titulo:
                carpeta = os.path.join(
                    CARPETA_RAIZ_GRABACIONES,
                    limpiar_nombre_archivo(titulo),
                )

        if carpeta and os.path.exists(carpeta):
            self._abrir_carpeta_en_explorador(carpeta)
        else:
            wx.MessageBox(
                "No hay carpeta de destino disponible todavía.\n"
                "Realiza al menos una grabación primero.",
                "Sin carpeta",
                wx.OK | wx.ICON_INFORMATION,
            )

    def _abrir_carpeta_en_explorador(self, ruta: str):
        """Lanza el Explorador de Windows apuntando a la carpeta indicada."""
        ruta_abs = os.path.abspath(ruta)
        try:
            subprocess.Popen(['explorer', ruta_abs])
        except Exception:
            try:
                os.startfile(ruta_abs)
            except Exception as e:
                wx.MessageBox(
                    f"No se pudo abrir la carpeta:\n{e}",
                    "Error",
                    wx.OK | wx.ICON_WARNING,
                )
