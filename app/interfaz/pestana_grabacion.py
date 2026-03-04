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

Cambios respecto al diseño anterior:
  - Sin botón "Escanear" ni "Asignar": ambas acciones son automáticas.
  - La casilla "Dividir por etiquetas" actualiza en tiempo real su StaticText
    de estado para que NVDA lo anuncie sin necesidad de enfocar el control.
  - Título y capítulo son opcionales (usa el nombre del TXT como fallback).
  - JSON helpers robustos: soportan archivo vacío, corrupto o inexistente.
  - Tab cíclico: primer_control / ultimo_control para ventana_principal.py.
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
    """Panel principal de grabación multivoz, accesible con NVDA."""

    def __init__(self, padre):
        super().__init__(padre, style=wx.TAB_TRAVERSAL)

        # ── Estado interno ────────────────────────────────────────────────
        self.ruta_txt_actual    = None
        self.nombre_base_txt    = ""     # fallback cuando título/capítulo vacíos
        self.texto_cargado      = ""
        self.fragmentos         = []     # [(etiqueta, contenido), ...]
        self.etiquetas_detectadas = []   # [etiqueta_normalizada, ...]
        self.asignaciones       = {}     # {etiqueta: datos_voz}
        self.voces_disponibles  = []     # [(texto_display, datos_voz), ...]
        self.titulo_libro       = ""
        self.grabador           = None
        self._hilo_grabacion    = None
        self._ultima_carpeta    = None

        # ── Rutas de configuración (absolutas) ────────────────────────────
        self.ruta_mapeo = ruta_config("mapeo_etiquetas.json")
        self.ruta_favs  = ruta_config("voces_favoritas.json")
        self.ruta_todas = ruta_config("voces_disponibles.json")

        self._construir_interfaz()
        self._cargar_voces_disponibles()

    # ================================================================== #
    # Propiedades para Tab cíclico (usadas por ventana_principal.py)
    # ================================================================== #

    @property
    def primer_control(self):
        return self.btn_examinar

    @property
    def ultimo_control(self):
        return self.btn_abrir_carpeta

    # ================================================================== #
    # Construcción de la interfaz
    # ================================================================== #

    def _construir_interfaz(self):
        sizer_raiz = wx.BoxSizer(wx.VERTICAL)

        # ── Carga de archivo ─────────────────────────────────────────────
        box_carga  = wx.StaticBox(self, label="Archivo de texto")
        sz_carga   = wx.StaticBoxSizer(box_carga, wx.VERTICAL)

        sz_ruta = wx.BoxSizer(wx.HORIZONTAL)
        lbl_ruta = wx.StaticText(self, label="Archivo TXT:")
        self.txt_ruta = wx.TextCtrl(self, style=wx.TE_READONLY)
        self.txt_ruta.SetName("Ruta del archivo de texto seleccionado")
        self.btn_examinar = wx.Button(self, label="&Examinar…")
        self.btn_examinar.SetName(
            "Abrir explorador. Al seleccionar un archivo, las etiquetas se detectan automáticamente."
        )
        sz_ruta.Add(lbl_ruta, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_ruta.Add(self.txt_ruta, 1, wx.EXPAND)
        sz_ruta.Add(self.btn_examinar, 0, wx.LEFT, 5)

        sz_titulo = wx.BoxSizer(wx.HORIZONTAL)
        lbl_titulo = wx.StaticText(self, label="Título (opcional):")
        self.txt_titulo = wx.TextCtrl(self)
        self.txt_titulo.SetName(
            "Título del libro o proyecto. Opcional. Si se deja vacío se usa el nombre del archivo."
        )
        sz_titulo.Add(lbl_titulo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_titulo.Add(self.txt_titulo, 1, wx.EXPAND)

        sz_cap = wx.BoxSizer(wx.HORIZONTAL)
        lbl_cap = wx.StaticText(self, label="Capítulo (opcional):")
        self.txt_capitulo = wx.TextCtrl(self)
        self.txt_capitulo.SetName(
            "Nombre del capítulo o sección. Opcional. Si se deja vacío se usa el nombre del archivo."
        )
        sz_cap.Add(lbl_cap, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sz_cap.Add(self.txt_capitulo, 1, wx.EXPAND)

        sz_carga.Add(sz_ruta,   0, wx.EXPAND | wx.ALL, 5)
        sz_carga.Add(sz_titulo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        sz_carga.Add(sz_cap,    0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Casting de voces ─────────────────────────────────────────────
        box_cast = wx.StaticBox(self, label="Casting de voces")
        sz_cast  = wx.StaticBoxSizer(box_cast, wx.VERTICAL)

        sz_cols = wx.BoxSizer(wx.HORIZONTAL)

        # Columna izquierda: etiqueta activa
        sz_etiq = wx.BoxSizer(wx.VERTICAL)
        lbl_etiq = wx.StaticText(self, label="Etiqueta activa:")
        self.combo_etiquetas = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_etiquetas.SetName(
            "Etiqueta activa. Selecciona la etiqueta a la que quieres asignar una voz. "
            "Al marcar una voz en la lista de la derecha, la asignación es automática "
            "y el combo avanza a la siguiente etiqueta sin asignar."
        )
        sz_etiq.Add(lbl_etiq, 0, wx.BOTTOM, 3)
        sz_etiq.Add(self.combo_etiquetas, 0, wx.EXPAND)

        # Columna derecha: voces favoritas
        sz_voces = wx.BoxSizer(wx.VERTICAL)
        lbl_voces = wx.StaticText(self, label="Voces disponibles (favoritas):")
        self.check_voces = wx.CheckListBox(self)
        self.check_voces.SetName(
            "Lista de voces favoritas. "
            "Marca una voz para asignarla a la etiqueta activa. "
            "La misma voz puede asignarse a varias etiquetas. "
            "Formato: Nombre — Idioma — Proveedor."
        )
        sz_voces.Add(lbl_voces, 0, wx.BOTTOM, 3)
        sz_voces.Add(self.check_voces, 1, wx.EXPAND)

        sz_cols.Add(sz_etiq,  1, wx.EXPAND | wx.RIGHT, 10)
        sz_cols.Add(sz_voces, 2, wx.EXPAND)

        # Botón de previsualización de voz
        sz_btn_cast = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_probar = wx.Button(self, label="&Probar Voz seleccionada")
        self.btn_probar.SetName(
            "Reproducir una muestra de la voz actualmente marcada en la lista de favoritos."
        )
        sz_btn_cast.Add(self.btn_probar, 0)

        # Resumen de asignaciones (texto de solo lectura, navegable con Tab)
        lbl_asign = wx.StaticText(self, label="Asignaciones actuales:")
        self.txt_asignaciones = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 90),
        )
        self.txt_asignaciones.SetName(
            "Resumen de asignaciones etiqueta → voz. "
            "Muestra '(sin asignar)' para las etiquetas que aún no tienen voz."
        )

        sz_cast.Add(sz_cols,          1, wx.EXPAND | wx.ALL, 5)
        sz_cast.Add(sz_btn_cast,      0, wx.LEFT | wx.BOTTOM, 5)
        sz_cast.Add(lbl_asign,        0, wx.LEFT | wx.TOP, 5)
        sz_cast.Add(self.txt_asignaciones, 0, wx.EXPAND | wx.ALL, 5)

        # ── Opciones de salida ────────────────────────────────────────────
        box_opc = wx.StaticBox(self, label="Opciones de salida")
        sz_opc  = wx.StaticBoxSizer(box_opc, wx.VERTICAL)

        self.chk_dividir = wx.CheckBox(self, label="Dividir &por etiquetas")
        self.chk_dividir.SetName(
            "Casilla Dividir por etiquetas. "
            "Marcada: genera un archivo MP3 numerado por cada fragmento de etiqueta. "
            "Desmarcada: genera un único archivo MP3 con todo el audio unificado."
        )
        self.chk_dividir.SetValue(True)

        self.lbl_estado_division = wx.StaticText(
            self,
            label="Estado: Generando múltiples archivos numerados por etiqueta",
        )
        self.lbl_estado_division.SetName(
            "Descripción del modo de salida actualmente seleccionado."
        )

        sz_opc.Add(self.chk_dividir,          0, wx.ALL, 5)
        sz_opc.Add(self.lbl_estado_division,  0, wx.LEFT | wx.BOTTOM, 10)

        # ── Progreso ──────────────────────────────────────────────────────
        box_prog = wx.StaticBox(self, label="Progreso")
        sz_prog  = wx.StaticBoxSizer(box_prog, wx.VERTICAL)

        self.lbl_progreso = wx.StaticText(
            self,
            label="Estado: En espera. Selecciona un archivo TXT para comenzar.",
        )
        self.lbl_progreso.SetName(
            "Estado actual. Durante la grabación informa del fragmento, "
            "etiqueta y voz en curso."
        )

        self.gauge = wx.Gauge(self, range=100)
        self.gauge.SetName("Barra de progreso de la grabación")

        sz_prog.Add(self.lbl_progreso, 0, wx.EXPAND | wx.ALL, 5)
        sz_prog.Add(self.gauge,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Botones principales ───────────────────────────────────────────
        sz_botones = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_iniciar = wx.Button(self, label="&Iniciar Grabación")
        self.btn_iniciar.SetName(
            "Iniciar el proceso de grabación multivoz en segundo plano."
        )
        self.btn_iniciar.Enable(False)

        self.btn_abortar = wx.Button(self, label="A&bortar")
        self.btn_abortar.SetName(
            "Detener la grabación en curso inmediatamente sin cerrar la aplicación."
        )
        self.btn_abortar.Enable(False)

        self.btn_abrir_carpeta = wx.Button(self, label="A&brir Carpeta")
        self.btn_abrir_carpeta.SetName(
            "Abrir en el Explorador la carpeta de grabaciones del proyecto actual."
        )
        # Siempre habilitado: si no hay grabación aún, abre la raíz de Grabaciones

        sz_botones.Add(self.btn_iniciar,       0, wx.RIGHT, 5)
        sz_botones.Add(self.btn_abortar,       0, wx.RIGHT, 5)
        sz_botones.Add(self.btn_abrir_carpeta, 0)

        # ── Ensamblado ────────────────────────────────────────────────────
        sizer_raiz.Add(sz_carga,    0, wx.EXPAND | wx.ALL, 6)
        sizer_raiz.Add(sz_cast,     1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sz_opc,      0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sz_prog,     0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer_raiz.Add(sz_botones,  0, wx.ALL, 10)

        self.SetSizer(sizer_raiz)

        # ── Eventos ───────────────────────────────────────────────────────
        self.btn_examinar.Bind(wx.EVT_BUTTON,      self.al_examinar)
        self.btn_probar.Bind(wx.EVT_BUTTON,        self.al_probar_voz)
        self.chk_dividir.Bind(wx.EVT_CHECKBOX,     self.al_cambiar_division)
        self.btn_iniciar.Bind(wx.EVT_BUTTON,       self.al_iniciar_grabacion)
        self.btn_abortar.Bind(wx.EVT_BUTTON,       self.al_abortar)
        self.btn_abrir_carpeta.Bind(wx.EVT_BUTTON, self.al_abrir_carpeta)
        self.check_voces.Bind(wx.EVT_CHECKLISTBOX, self.al_marcar_voz)

    # ================================================================== #
    # JSON helpers — seguros ante archivo vacío o corrupto
    # ================================================================== #

    def _cargar_json(self, ruta: str) -> dict:
        """Devuelve el JSON como dict, o {} si el archivo no existe/está vacío/es inválido."""
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

    def _guardar_json(self, ruta: str, datos: dict):
        """Guarda datos como JSON de forma segura."""
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
    # Carga de voces disponibles
    # ================================================================== #

    def _cargar_voces_disponibles(self):
        """Puebla check_voces con favoritas (neuronales + SAPI5 local)."""
        self.voces_disponibles = []
        self.check_voces.Clear()

        # Voces neuronales favoritas
        ids_favs = []
        datos_favs = self._cargar_json(self.ruta_favs)
        if isinstance(datos_favs, list):
            ids_favs = datos_favs

        if ids_favs and os.path.exists(self.ruta_todas):
            todas = self._cargar_json(self.ruta_todas)
            for prov, lista in todas.items():
                if not isinstance(lista, list):
                    continue
                for v in lista:
                    if v.get('id') in ids_favs:
                        v_copy = dict(v)
                        v_copy['proveedor_id'] = prov
                        nombre_disp = (
                            f"{v_copy.get('nombre', 'Sin nombre')}  "
                            f"({v_copy.get('idioma', '?')})  "
                            f"[{prov.capitalize()}]"
                        )
                        self.voces_disponibles.append((nombre_disp, v_copy))

        # Voces SAPI5 locales
        try:
            import comtypes.client
            sapi  = comtypes.client.CreateObject("SAPI.SpVoice")
            voces = sapi.GetVoices()
            for i in range(voces.Count):
                v    = voces.Item(i)
                desc = v.GetDescription()
                datos = {"id": v.Id, "nombre": desc, "proveedor_id": "local"}
                self.voces_disponibles.append((f"{desc}  [Local]", datos))
        except Exception:
            pass

        if self.voces_disponibles:
            for nombre_disp, _ in self.voces_disponibles:
                self.check_voces.Append(nombre_disp)
        else:
            self.check_voces.Append(
                "No hay voces. Añade favoritas en la pestaña Ajustes."
            )

    # ================================================================== #
    # Carga y escaneo automático del archivo TXT
    # ================================================================== #

    def al_examinar(self, evento):
        """Abre el explorador; si el usuario selecciona un TXT, lo carga y escanea."""
        with wx.FileDialog(
            self,
            "Seleccionar archivo de texto con etiquetas",
            wildcard="Archivos de texto (*.txt)|*.txt|Todos (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return

            self.ruta_txt_actual  = dlg.GetPath()
            self.nombre_base_txt  = os.path.splitext(
                os.path.basename(self.ruta_txt_actual)
            )[0]
            self.txt_ruta.SetValue(self.ruta_txt_actual)

            # Sugerir título/capítulo solo si están vacíos
            if not self.txt_titulo.GetValue().strip():
                self.txt_titulo.SetValue(self.nombre_base_txt)
            if not self.txt_capitulo.GetValue().strip():
                self.txt_capitulo.SetValue(self.nombre_base_txt)

        # Escanear automáticamente
        self._cargar_y_escanear()

    def _cargar_y_escanear(self):
        """Lee el TXT, detecta etiquetas y pre-carga asignaciones previas."""
        if not self.ruta_txt_actual:
            return

        try:
            with open(self.ruta_txt_actual, 'r', encoding='utf-8') as f:
                self.texto_cargado = f.read()
        except Exception as e:
            wx.MessageBox(
                f"No se pudo leer el archivo:\n{e}",
                "Error de lectura", wx.OK | wx.ICON_ERROR,
            )
            return

        if not self.texto_cargado.strip():
            wx.MessageBox("El archivo está vacío.", "Sin contenido", wx.OK | wx.ICON_WARNING)
            return

        self.fragmentos = fragmentar_texto(self.texto_cargado)
        if not self.fragmentos:
            wx.MessageBox(
                "El archivo no contiene texto aprovechable.",
                "Sin fragmentos", wx.OK | wx.ICON_WARNING,
            )
            return

        # Etiquetas únicas preservando orden de aparición
        vistas, self.etiquetas_detectadas = set(), []
        for etiq, _ in self.fragmentos:
            if etiq not in vistas:
                self.etiquetas_detectadas.append(etiq)
                vistas.add(etiq)

        # Actualizar combo
        self.combo_etiquetas.Clear()
        for etiq in self.etiquetas_detectadas:
            self.combo_etiquetas.Append(f"@{etiq}")
        if self.combo_etiquetas.GetCount() > 0:
            self.combo_etiquetas.SetSelection(0)

        # Recuperar asignaciones previas
        titulo = self._resolver_titulo()
        self.titulo_libro  = titulo
        self.asignaciones  = {}
        self._cargar_mapeo(titulo)
        self._actualizar_resumen_asignaciones()

        total = len(self.fragmentos)
        etiq_str = ', '.join('@' + e for e in self.etiquetas_detectadas)
        self.lbl_progreso.SetLabel(
            f"Archivo cargado: {total} fragmentos, etiquetas: {etiq_str}. "
            f"Marca una voz en la lista para asignarla."
        )
        self.btn_iniciar.Enable(True)

        wx.MessageBox(
            f"Texto cargado.\nFragmentos: {total}\nEtiquetas: {etiq_str}",
            "Escaneo completado", wx.OK | wx.ICON_INFORMATION,
        )

    # ================================================================== #
    # Casting: auto-asignación al marcar una voz
    # ================================================================== #

    def al_marcar_voz(self, evento):
        """
        Al marcar una voz en el CheckListBox:
          1. Comportamiento radio (desmarca las demás).
          2. Auto-asigna la voz a la etiqueta activa en el combo.
          3. Avanza el combo a la siguiente etiqueta sin asignar.
        """
        idx_marcado = evento.GetInt()

        # Radio behavior
        for i in range(self.check_voces.GetCount()):
            if i != idx_marcado:
                self.check_voces.Check(i, False)

        if idx_marcado >= len(self.voces_disponibles):
            return  # Entrada de "No hay voces" — ignorar

        nombre_voz_disp, datos_voz = self.voces_disponibles[idx_marcado]

        idx_etiq = self.combo_etiquetas.GetSelection()
        if idx_etiq == wx.NOT_FOUND:
            return

        etiqueta = normalizar_etiqueta(
            self.combo_etiquetas.GetString(idx_etiq).lstrip('@')
        )

        self.asignaciones[etiqueta] = datos_voz
        self._guardar_mapeo()
        self._actualizar_resumen_asignaciones()

        self.lbl_progreso.SetLabel(
            f"Asignado: @{etiqueta}  →  {nombre_voz_disp}"
        )

        # Avanzar el combo a la siguiente etiqueta sin asignar
        total_etiq = self.combo_etiquetas.GetCount()
        for delta in range(1, total_etiq):
            siguiente_idx  = (idx_etiq + delta) % total_etiq
            siguiente_etiq = normalizar_etiqueta(
                self.combo_etiquetas.GetString(siguiente_idx).lstrip('@')
            )
            if siguiente_etiq not in self.asignaciones:
                self.combo_etiquetas.SetSelection(siguiente_idx)
                break

    def al_probar_voz(self, evento):
        """Reproduce una muestra de la voz marcada (hilo de fondo)."""
        datos_voz = None
        for i in range(self.check_voces.GetCount()):
            if self.check_voces.IsChecked(i) and i < len(self.voces_disponibles):
                _, datos_voz = self.voces_disponibles[i]
                break

        if datos_voz is None:
            wx.MessageBox(
                "Marca primero una voz en la lista.",
                "Sin selección", wx.OK | wx.ICON_WARNING,
            )
            return

        def _probar():
            try:
                GrabadorAudio().probar_voz(datos_voz)
            except Exception as e:
                wx.CallAfter(
                    wx.MessageBox,
                    f"Error al reproducir la muestra:\n{e}",
                    "Error de previsualización", wx.OK | wx.ICON_ERROR,
                )

        threading.Thread(target=_probar, daemon=True).start()

    def _actualizar_resumen_asignaciones(self):
        if not self.etiquetas_detectadas:
            self.txt_asignaciones.SetValue("Carga un archivo para ver las etiquetas.")
            return

        lineas = []
        for etiq in self.etiquetas_detectadas:
            voz = self.asignaciones.get(etiq)
            if voz:
                prov = voz.get('proveedor_id', 'local').capitalize()
                lineas.append(f"@{etiq}  →  {voz.get('nombre', '?')}  [{prov}]")
            else:
                lineas.append(f"@{etiq}  →  (sin asignar)")

        self.txt_asignaciones.SetValue('\n'.join(lineas))

    # ================================================================== #
    # Opciones de salida
    # ================================================================== #

    def al_cambiar_division(self, evento):
        """Actualiza el StaticText de estado para que NVDA lo anuncie."""
        if self.chk_dividir.IsChecked():
            self.lbl_estado_division.SetLabel(
                "Estado: Generando múltiples archivos numerados por etiqueta"
            )
        else:
            self.lbl_estado_division.SetLabel(
                "Estado: Generando un único archivo MP3 integrado"
            )

    # ================================================================== #
    # Persistencia del mapeo etiqueta → voz
    # ================================================================== #

    def _guardar_mapeo(self):
        mapeo = self._cargar_json(self.ruta_mapeo)
        titulo = self._resolver_titulo()
        mapeo[titulo] = self.asignaciones
        self._guardar_json(self.ruta_mapeo, mapeo)

    def _cargar_mapeo(self, titulo: str):
        mapeo = self._cargar_json(self.ruta_mapeo)
        datos = mapeo.get(titulo, {})
        self.asignaciones = {
            k: v for k, v in datos.items()
            if k in self.etiquetas_detectadas
        }
        if self.asignaciones:
            self.lbl_progreso.SetLabel(
                f"Recuperadas {len(self.asignaciones)} asignaciones previas para «{titulo}»."
            )

    # ================================================================== #
    # Proceso de grabación
    # ================================================================== #

    def al_iniciar_grabacion(self, evento):
        if not self.fragmentos:
            wx.MessageBox(
                "No hay texto cargado. Selecciona primero un archivo TXT.",
                "Error", wx.OK | wx.ICON_ERROR,
            )
            return

        titulo   = self._resolver_titulo()
        capitulo = self._resolver_capitulo()

        sin_voz = [e for e in self.etiquetas_detectadas if e not in self.asignaciones]
        if sin_voz:
            nombres = ', '.join('@' + e for e in sin_voz)
            if wx.MessageBox(
                f"Las siguientes etiquetas no tienen voz asignada:\n{nombres}\n\n"
                "Los fragmentos sin voz se omitirán.\n"
                "¿Continuar de todas formas?",
                "Etiquetas sin voz", wx.YES_NO | wx.ICON_WARNING,
            ) != wx.YES:
                return

        modo_dividido = self.chk_dividir.IsChecked()

        self.btn_iniciar.Enable(False)
        self.btn_abortar.Enable(True)
        self.gauge.SetValue(0)
        self.lbl_progreso.SetLabel("Iniciando grabación…")

        self.titulo_libro    = titulo
        self._ultima_carpeta = None
        self.grabador = GrabadorAudio(callback_progreso=self._callback_progreso)

        self._hilo_grabacion = threading.Thread(
            target=self._ejecutar_grabacion,
            args=(titulo, capitulo, modo_dividido),
            daemon=True,
        )
        self._hilo_grabacion.start()

    def _callback_progreso(self, actual, total, etiqueta, nombre_voz):
        pct = int((actual / total) * 100) if total > 0 else 0
        msg = (
            f"Grabando fragmento {actual} de {total}  "
            f"(Etiqueta: @{etiqueta}  —  Voz: {nombre_voz})"
        )
        wx.CallAfter(self._actualizar_progreso_ui, pct, msg)

    def _actualizar_progreso_ui(self, pct, msg):
        self.gauge.SetValue(pct)
        self.lbl_progreso.SetLabel(msg)

    def _ejecutar_grabacion(self, titulo, capitulo, modo_dividido):
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

    def _al_terminar_grabacion(self, archivos, errores, carpeta):
        self.btn_iniciar.Enable(True)
        self.btn_abortar.Enable(False)
        self._ultima_carpeta = carpeta
        self.gauge.SetValue(100)

        n             = len(archivos)
        nombre_carpeta = os.path.basename(carpeta)

        self.lbl_progreso.SetLabel(
            f"Proceso finalizado con éxito. {n} archivos generados en {nombre_carpeta}."
        )

        cuerpo = (
            f"Proceso finalizado con éxito.\n"
            f"{n} archivo(s) en:\n{carpeta}"
        )
        if errores:
            resumen = "\n".join(errores[:5])
            if len(errores) > 5:
                resumen += f"\n… y {len(errores) - 5} errores más."
            cuerpo += f"\n\n⚠ {len(errores)} fragmento(s) fallido(s):\n{resumen}"

        cuerpo += "\n\n¿Deseas abrir la carpeta de destino?"

        dlg = wx.MessageDialog(
            self, cuerpo, "Grabación completada", wx.YES_NO | wx.ICON_INFORMATION
        )
        resultado = dlg.ShowModal()
        dlg.Destroy()

        if resultado == wx.ID_YES and carpeta and os.path.exists(carpeta):
            self._abrir_carpeta_en_explorador(carpeta)

    def _al_error_grabacion(self, error):
        self.btn_iniciar.Enable(True)
        self.btn_abortar.Enable(False)
        self.lbl_progreso.SetLabel(f"Error durante la grabación: {error}")
        wx.MessageBox(
            f"Error durante la grabación:\n\n{error}",
            "Error de grabación", wx.OK | wx.ICON_ERROR,
        )

    def al_abortar(self, evento):
        if self.grabador:
            self.grabador.abortar()
        self.lbl_progreso.SetLabel("Estado: Grabación abortada por el usuario.")
        self.btn_abortar.Enable(False)
        self.btn_iniciar.Enable(True)

    # ================================================================== #
    # Apertura de carpeta
    # ================================================================== #

    def al_abrir_carpeta(self, evento):
        carpeta = self._ultima_carpeta

        if not carpeta or not os.path.exists(carpeta):
            # Intentar abrir la carpeta madre del proyecto
            titulo = self._resolver_titulo()
            carpeta = os.path.join(
                CARPETA_RAIZ_GRABACIONES,
                limpiar_nombre_archivo(titulo),
            )

        if not os.path.exists(carpeta):
            # Abrir la raíz de grabaciones
            carpeta = CARPETA_RAIZ_GRABACIONES
            os.makedirs(carpeta, exist_ok=True)

        self._abrir_carpeta_en_explorador(carpeta)

    def _abrir_carpeta_en_explorador(self, ruta):
        ruta_abs = os.path.abspath(ruta)
        try:
            subprocess.Popen(['explorer', ruta_abs])
        except Exception:
            try:
                os.startfile(ruta_abs)
            except Exception as e:
                wx.MessageBox(
                    f"No se pudo abrir la carpeta:\n{e}",
                    "Error", wx.OK | wx.ICON_WARNING,
                )
