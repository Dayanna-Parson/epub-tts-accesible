import wx
import os
import re
import sys
import json
import logging
import webbrowser
import wx.lib.mixins.listctrl as listmix

from app.config_rutas import ruta_config, CONFIG_DIR, cargar_claves, guardar_claves
from app.motor import anunciador_lector as voz
from app.motor import gestor_prompts_asistente as prompts
from app.motor.reproductor_sonidos import (
    reproducir, LIST_NAV, SUCCESS, ERROR, OPEN_FOLDER,
    SONIDOS_DISPONIBLES, sonidos_habilitados, fijar_sonidos_habilitados,
    sonido_habilitado, fijar_sonido_habilitado,
)
from app.interfaz.selector_voz_compartido import ListaVocesCheck, PanelProveedorIA
from app.interfaz.ui_recursos import aplicar_icono_boton
from app.servicios.cliente_gemini import TEMPERATURA_DEFECTO as TEMPERATURA_DEFECTO_GEMINI

logger = logging.getLogger(__name__)


# ListaVocesCheck se mudó a app/interfaz/selector_voz_compartido.py (bloque
# ANCLAJE LISTA_VOCES_CHECK), importada arriba junto a PanelProveedorIA.


# ANCLAJE_INICIO: HELPER_TEXTO_LIMITE
_CHARS_POR_LIBRO = 300_000


def _texto_ayuda_limite(proveedor, gastado, limite_chars):
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
        if lim <= 30_000:
            plan = "Plan Starter, 5 dolares al mes"
        elif lim <= 100_000:
            plan = "Plan Creator, 22 dolares al mes"
        elif lim <= 500_000:
            plan = "Plan Pro, 99 dolares al mes"
        else:
            plan = "Plan Scale, 330 dolares al mes"
        return (
            f"Gasto: {gas} caracteres. "
            f"Restante: {restante} caracteres, aprox {libros} libros. "
            f"Suscripcion sugerida: {plan}."
        )
    elif proveedor == "deepgram":
        coste_gas = round(gas * 15 / 1_000_000, 2)
        coste_lim = round(lim * 15 / 1_000_000, 2)
        return (
            f"Gasto: {gas} caracteres, unos {coste_gas} dolares. "
            f"Restante: {restante} caracteres, aprox {libros} libros. "
            f"Coste total al limite: {coste_lim} dolares al mes."
        )
    return ""
# ANCLAJE_FIN: HELPER_TEXTO_LIMITE


# ANCLAJE_INICIO: PANEL_GENERAL
class PanelGeneral(wx.ScrolledWindow):
    def __init__(self, padre, config, pestana_ajustes=None):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config
        # wx.GetTopLevelParent(self) llega hasta ventana_principal (el Frame),
        # no hasta PestanaAjustes (un wx.Panel intermedio) — por eso se guarda
        # aquí una referencia directa, en vez de subir por la jerarquía de ventanas.
        self._pestana_ajustes = pestana_ajustes
        from app.motor.control_cuota import ControlCuota
        self.cuota = ControlCuota()

        sizer = wx.BoxSizer(wx.VERTICAL)

        # ANCLAJE_INICIO: IDIOMA_LIBRO_GENERAL
        sb_idioma = wx.StaticBox(self, label="Idioma del libro")
        sz_idioma = wx.StaticBoxSizer(sb_idioma, wx.VERTICAL)
        sz_idioma.Add(
            wx.StaticText(self, label="Idioma principal del libro (preselecciona el acento de voz en Lectura):"),
            0, wx.ALL, 2,
        )
        self.combo_idioma_libro = wx.ComboBox(
            self,
            choices=["Español (ES)", "Español (LAT)", "Inglés", "Detectar auto"],
            style=wx.CB_READONLY,
        )
        self.combo_idioma_libro.SetHelpText(
            "Define el idioma principal del libro para preseleccionar el acento correcto "
            "en el combo de voz de la pestaña Lectura. "
            "Elige Español (ES) para España, Español (LAT) para Latinoamérica, "
            "Inglés para textos en inglés, o Detectar auto para dejar que la aplicación lo decida."
        )
        _codigo_guardado = self.config.get("idioma_libro_codigo", "es-ES")
        _mapa_codigo_idx = {"es-ES": 0, "es-MX": 1, "en-US": 2, "auto": 3}
        self.combo_idioma_libro.SetSelection(_mapa_codigo_idx.get(_codigo_guardado, 0))
        self.combo_idioma_libro.Bind(wx.EVT_COMBOBOX, self._al_cambiar_idioma_libro)
        sz_idioma.Add(self.combo_idioma_libro, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(sz_idioma, 0, wx.EXPAND | wx.ALL, 10)
        # ANCLAJE_FIN: IDIOMA_LIBRO_GENERAL

        sb_cuota = wx.StaticBox(self, label="Control de Presupuesto y Límites")
        sizer_cuota = wx.StaticBoxSizer(sb_cuota, wx.VERTICAL)

        g_az, l_az = self.cuota.get_info_uso("azure")
        sizer_cuota.Add(self._crear_fila_limite("Azure", g_az, l_az, "azure"), 0, wx.EXPAND | wx.ALL, 2)

        g_po, l_po = self.cuota.get_info_uso("polly")
        sizer_cuota.Add(self._crear_fila_limite("Polly", g_po, l_po, "polly"), 0, wx.EXPAND | wx.ALL, 2)

        g_el, l_el = self.cuota.get_info_uso("elevenlabs")
        sizer_cuota.Add(self._crear_fila_limite("ElevenLabs", g_el, l_el, "elevenlabs"), 0, wx.EXPAND | wx.ALL, 2)

        g_dg, l_dg = self.cuota.get_info_uso("deepgram")
        sizer_cuota.Add(self._crear_fila_limite("Deepgram", g_dg, l_dg, "deepgram"), 0, wx.EXPAND | wx.ALL, 2)

        sizer.Add(sizer_cuota, 0, wx.EXPAND | wx.ALL, 10)

        sb_nav = wx.StaticBox(self, label="Navegación")
        sizer_nav = wx.StaticBoxSizer(sb_nav, wx.VERTICAL)
        hbox_salto = wx.BoxSizer(wx.HORIZONTAL)
        hbox_salto.Add(
            wx.StaticText(self, label="Segundos de salto (botones Retroceder y Avanzar en Lectura):"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10,
        )
        self.txt_salto = wx.TextCtrl(self, value=str(self.config.get("segundos_salto", "10")), size=(50, -1))
        self.txt_salto.SetHelpText(
            "Número de segundos que avanza o retrocede el audio al pulsar los botones "
            "Retroceder y Avanzar en la pestaña Lectura. Introduce un número entero. Valor recomendado: 10."
        )
        hbox_salto.Add(self.txt_salto, 0)
        sizer_nav.Add(hbox_salto, 0, wx.ALL, 5)

        hbox_pausa = wx.BoxSizer(wx.HORIZONTAL)
        hbox_pausa.Add(
            wx.StaticText(self, label="Pausa entre párrafos en voces de IA (milisegundos):"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10,
        )
        self.spin_pausa = wx.SpinCtrl(
            self,
            value=str(self.config.get("pausa_entre_fragmentos_ms", 0)),
            min=0, max=3000, size=(70, -1),
        )
        self.spin_pausa.SetHelpText(
            "Tiempo de espera entre fragmentos consecutivos cuando se usan voces de IA. "
            "0 = sin pausa adicional. Ejemplo: 300 añade 0,3 segundos de silencio entre párrafos."
        )
        hbox_pausa.Add(self.spin_pausa, 0)
        sizer_nav.Add(hbox_pausa, 0, wx.ALL, 5)

        sizer.Add(sizer_nav, 0, wx.EXPAND | wx.ALL, 10)

        sb_updates = wx.StaticBox(self, label="Actualizaciones")
        sizer_updates = wx.StaticBoxSizer(sb_updates, wx.VERTICAL)

        self.chk_actualizar = wx.CheckBox(
            self, label="Buscar actualizaciones automáticamente al iniciar la app"
        )
        self.chk_actualizar.SetValue(self.config.get("actualizar_automaticamente", True))
        self.chk_actualizar.SetHelpText(
            "Si está marcado, la aplicación comprueba si hay una nueva versión disponible "
            "cada vez que se inicia. La comprobación se hace en segundo plano."
        )
        sizer_updates.Add(self.chk_actualizar, 0, wx.ALL, 5)

        self.btn_buscar_updates = wx.Button(self, label="Buscar actualizaciones ahora")
        self.btn_buscar_updates.SetHelpText(
            "Comprueba si hay una versión nueva comparando tu version.json local "
            "con el del repositorio de GitHub."
        )
        self.btn_buscar_updates.Bind(wx.EVT_BUTTON, self._al_buscar_actualizaciones)
        aplicar_icono_boton(self.btn_buscar_updates, "buscar", "Buscar actualizaciones ahora")
        sizer_updates.Add(self.btn_buscar_updates, 0, wx.ALL, 5)

        self.lbl_progreso = wx.StaticText(self, label="")
        self.lbl_progreso.SetHelpText(
            "Estado del proceso de actualización. NVDA lo leerá automáticamente al cambiar."
        )
        sizer_updates.Add(self.lbl_progreso, 0, wx.ALL, 5)

        # ANCLAJE_INICIO: BOTON_PRUEBA_ACTUALIZADOR_FASE_C
        # Botón temporal de desarrollo, independiente del flujo de producción
        # de arriba (btn_buscar_updates). Prueba en aislamiento el nuevo
        # gestor de descarga/verificación a temp/actualizacion/ (Fase C).
        # Se retira cuando el flujo completo con actualizador.exe sustituya
        # al bloque ACTUALIZADOR_SCRIPT_CLON.
        self.btn_probar_descarga_nueva = wx.Button(
            self, label="Probar descarga y verificación (Fase C)"
        )
        self.btn_probar_descarga_nueva.SetHelpText(
            "Descarga la última versión a temp/actualizacion/ y verifica su estructura, "
            "sin instalar nada. Herramienta de desarrollo de la Fase C."
        )
        self.btn_probar_descarga_nueva.Bind(wx.EVT_BUTTON, self._al_probar_descarga_nueva)
        sizer_updates.Add(self.btn_probar_descarga_nueva, 0, wx.ALL, 5)
        # ANCLAJE_FIN: BOTON_PRUEBA_ACTUALIZADOR_FASE_C

        sizer.Add(sizer_updates, 0, wx.EXPAND | wx.ALL, 10)

        # ANCLAJE_INICIO: SELECTOR_ESCALA_VELOCIDAD_AJUSTES
        sb_vel = wx.StaticBox(self, label="Deslizadores de velocidad")
        sz_vel = wx.StaticBoxSizer(sb_vel, wx.VERTICAL)
        sz_vel.Add(
            wx.StaticText(self, label="Sistema de visualización de velocidad:"),
            0, wx.ALL, 2,
        )
        self.combo_escala_vel = wx.ComboBox(
            self,
            choices=["Porcentaje (0 – 100)", "Multiplicador por puntos (0.2× – 1.8×)"],
            style=wx.CB_READONLY,
        )
        self.combo_escala_vel.SetHelpText(
            "Elige cómo se muestra la velocidad en el deslizador de la pestaña Lectura. "
            "Porcentaje: valores del 0 al 100. "
            "Multiplicador: etiquetas tipo 1.0× (Normal), 1.4× (Rápida), 1.8× (Muy rápida). "
            "El motor de audio recibe siempre el mismo valor 0-100 del deslizador; "
            "el multiplicador es solo su lectura equivalente."
        )
        _escala_guardada = self.config.get("escala_velocidad", "porcentaje")
        self.combo_escala_vel.SetSelection(0 if _escala_guardada == "porcentaje" else 1)
        sz_vel.Add(self.combo_escala_vel, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(sz_vel, 0, wx.EXPAND | wx.ALL, 10)
        # ANCLAJE_FIN: SELECTOR_ESCALA_VELOCIDAD_AJUSTES

        self.btn_guardar = wx.Button(self, label="Guardar Configuración General y Límites de presupuesto")
        self.btn_guardar.SetHelpText(
            "Guarda los segundos de salto, la escala de velocidad y los límites de presupuesto de cada proveedor."
        )
        self.btn_guardar.Bind(wx.EVT_BUTTON, lambda e: self.guardar_todo())
        aplicar_icono_boton(self.btn_guardar, "guardar", "Guardar Configuración General y Límites de presupuesto")
        sizer.Add(self.btn_guardar, 0, wx.ALL, 10)

        self.btn_borrar_recientes = wx.Button(self, label="Borrar historial de libros recientes")
        self.btn_borrar_recientes.SetHelpText(
            "Vacía la lista de «Libros Recientes» del menú de la pestaña Lectura. "
            "No borra ningún archivo, solo el atajo a los últimos libros abiertos."
        )
        self.btn_borrar_recientes.Bind(wx.EVT_BUTTON, self._al_borrar_recientes)
        aplicar_icono_boton(self.btn_borrar_recientes, "eliminar", "Borrar historial de libros recientes")
        sizer.Add(self.btn_borrar_recientes, 0, wx.ALL, 10)

        self.btn_limpiar = wx.Button(self, label="Limpiar caché")
        self.btn_limpiar.SetHelpText(
            "Elimina carpetas __pycache__, archivos .tmp y audio temporal."
        )
        self.btn_limpiar.Bind(wx.EVT_BUTTON, self._limpiar_cache)
        aplicar_icono_boton(self.btn_limpiar, "limpiar", "Limpiar caché")
        sizer.Add(self.btn_limpiar, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        self.primer_control = self.txt_salto

    @property
    def ultimo_control(self):
        return self.btn_limpiar

    def _crear_fila_limite(self, nombre, gastado, limite, clave):
        if not hasattr(self, "txt_limites"):
            self.txt_limites = {}
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label=f"{nombre} (Gastado: {gastado}):", size=(180, -1))
        txt = wx.TextCtrl(self, value=str(limite))
        txt.SetName(f"limite_{clave}")
        txt.SetHelpText(_texto_ayuda_limite(clave, gastado, limite))
        self.txt_limites[clave] = txt

        def _on_texto(evento, _clave=clave, _gas=gastado, _txt=txt):
            _txt.SetHelpText(_texto_ayuda_limite(_clave, _gas, evento.GetString()))
            evento.Skip()

        txt.Bind(wx.EVT_TEXT, _on_texto)
        hbox.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        hbox.Add(txt, 1, wx.EXPAND)
        return hbox

    def _al_cambiar_idioma_libro(self, evento):
        _mapa_idx_codigo = {0: "es-ES", 1: "es-MX", 2: "en-US", 3: "auto"}
        self.config["idioma_libro_codigo"] = _mapa_idx_codigo.get(
            self.combo_idioma_libro.GetSelection(), "es-ES"
        )
        if self._pestana_ajustes is not None:
            self._pestana_ajustes.guardar_config_en_archivo()

    def sincronizar_config(self):
        """Vuelca en self.config el valor actual de todos los controles del panel.

        Se llama tanto desde el botón «Guardar» (guardar_todo) como desde
        Ctrl+S (PestanaAjustes._al_guardar_global), para que la casilla de
        actualizaciones y el resto de campos queden reflejados en self.config
        aunque el usuario nunca haya pulsado el botón «Guardar» de este panel.
        """
        self.config["segundos_salto"] = self.txt_salto.GetValue()
        self.config["pausa_entre_fragmentos_ms"] = self.spin_pausa.GetValue()
        self.config["actualizar_automaticamente"] = self.chk_actualizar.GetValue()
        self.config["escala_velocidad"] = (
            "porcentaje" if self.combo_escala_vel.GetSelection() == 0 else "multiplicador"
        )
        _mapa_idx_codigo = {0: "es-ES", 1: "es-MX", 2: "en-US", 3: "auto"}
        self.config["idioma_libro_codigo"] = _mapa_idx_codigo.get(
            self.combo_idioma_libro.GetSelection(), "es-ES"
        )

    def guardar_todo(self):
        self.sincronizar_config()
        if self._pestana_ajustes is not None:
            self._pestana_ajustes.guardar_config_en_archivo()

    def _al_borrar_recientes(self, evento):
        ventana = wx.GetTopLevelParent(self)
        if not hasattr(ventana, 'al_borrar_recientes'):
            return
        if not ventana.archivos_recientes:
            reproducir(ERROR)
            wx.MessageBox("El historial de libros recientes ya está vacío.", "Info")
            return
        ventana.al_borrar_recientes(evento)
        if hasattr(self, "txt_limites"):
            for clave, txt in self.txt_limites.items():
                val = txt.GetValue()
                if val.isdigit():
                    self.cuota.set_limite(clave, int(val))
        reproducir(SUCCESS)
        wx.MessageBox("Configuración y límites guardados.")

    def _limpiar_cache(self, evento=None):
        from app.config_rutas import RAIZ
        import shutil

        total_archivos = 0
        total_bytes = 0
        errores = 0

        for dirpath, dirnames, _ in os.walk(RAIZ):
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

        reproducir(SUCCESS)
        wx.MessageBox(msg, "Limpiar caché", wx.OK | wx.ICON_INFORMATION)

    # ANCLAJE_INICIO: ACTUALIZADOR_SCRIPT_CLON
    def _al_buscar_actualizaciones(self, evento=None):
        from app.motor.comprobador_actualizaciones import ComprobadorActualizaciones
        self.btn_buscar_updates.Disable()
        self.btn_buscar_updates.SetLabel("Comprobando…")
        wx.CallAfter(
            self.lbl_progreso.SetLabel,
            "Comprobando versiones en el repositorio de GitHub...",
        )
        comp = ComprobadorActualizaciones()
        comp.comprobar_en_hilo(
            lambda r: wx.CallAfter(self._al_resultado_actualizacion, r)
        )

    def _al_resultado_actualizacion(self, resultado: dict):
        self.btn_buscar_updates.Enable()
        self.btn_buscar_updates.SetLabel("Buscar actualizaciones ahora")

        if resultado.get("error"):
            wx.CallAfter(self.lbl_progreso.SetLabel, "")
            reproducir(ERROR)
            wx.MessageBox(
                f"No se pudo comprobar la actualización:\n{resultado['error']}",
                "Error de conexión", wx.OK | wx.ICON_WARNING,
            )
            return

        v_local = resultado.get("version_local", "—")
        v_remota = resultado.get("version_remota", "—")

        if not resultado.get("hay_nueva"):
            reproducir(SUCCESS)
            wx.CallAfter(self.lbl_progreso.SetLabel, "")
            wx.MessageBox(
                f"Ya tienes la versión más reciente ({v_local}).",
                "Sin actualizaciones", wx.OK | wx.ICON_INFORMATION,
            )
            return

        reproducir(SUCCESS)
        from app.interfaz.dialogo_novedades import DialogoNovedades
        dlg = DialogoNovedades(self, v_remota, resultado.get("novedades", ""))
        respuesta = dlg.ShowModal()
        dlg.Destroy()

        if respuesta != wx.ID_OK:
            wx.CallAfter(self.lbl_progreso.SetLabel, "")
            return

        wx.CallAfter(
            self.lbl_progreso.SetLabel,
            "Descargando el archivo de actualización en segundo plano, por favor espera...",
        )
        self.btn_buscar_updates.Disable()
        import threading
        hilo = threading.Thread(
            target=self._hilo_descargar_e_instalar,
            args=(v_remota,),
            daemon=True,
        )
        hilo.start()

    def _hilo_descargar_e_instalar_desde_arranque(self, version_remota: str):
        """Lanza la descarga e instalación desde la comprobación automática al arrancar."""
        import threading
        hilo = threading.Thread(
            target=self._hilo_descargar_e_instalar,
            args=(version_remota,),
            daemon=True,
        )
        hilo.start()

    def _hilo_descargar_e_instalar(self, version_remota: str):
        import shutil
        import urllib.request
        import zipfile
        from app.config_rutas import RAIZ

        _URL_ZIP = (
            "https://github.com/Dayanna-Parson/epub-tts-accesible"
            "/archive/refs/heads/main.zip"
        )

        carpeta_actualizacion = os.path.join(RAIZ, "actualizacion")
        os.makedirs(carpeta_actualizacion, exist_ok=True)
        ruta_zip = os.path.join(carpeta_actualizacion, "nueva_version.zip")

        try:
            req = urllib.request.Request(
                _URL_ZIP,
                headers={"User-Agent": "epub-tts-accesible/updater"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(ruta_zip, "wb") as f_out:
                    bloque = 65536
                    while True:
                        chunk = resp.read(bloque)
                        if not chunk:
                            break
                        f_out.write(chunk)
        except Exception as exc:
            logger.exception("Error al descargar el ZIP de actualización")
            wx.CallAfter(self.lbl_progreso.SetLabel, "")
            wx.CallAfter(self.btn_buscar_updates.Enable)
            wx.CallAfter(
                wx.MessageBox,
                f"No se pudo descargar la actualización:\n{exc}",
                "Error de descarga",
                wx.OK | wx.ICON_ERROR,
            )
            return

        wx.CallAfter(
            self.lbl_progreso.SetLabel,
            "Descarga completada con éxito. Preparando la instalación...",
        )

        try:
            self._escribir_y_lanzar_bat(ruta_zip, RAIZ)
        except Exception as exc:
            logger.exception("Error al generar el script de actualización")
            wx.CallAfter(self.lbl_progreso.SetLabel, "")
            wx.CallAfter(self.btn_buscar_updates.Enable)
            wx.CallAfter(
                wx.MessageBox,
                f"No se pudo preparar la instalación:\n{exc}",
                "Error interno",
                wx.OK | wx.ICON_ERROR,
            )
            return

    def _escribir_y_lanzar_bat(self, ruta_zip: str, raiz: str):
        import subprocess

        lanzador = os.path.join(raiz, "INICIAR_APP.bat")
        bat_path = os.path.join(raiz, "actualizador.bat")

        # Carpetas y archivos que el .bat debe conservar intactos
        # Solo se preservan los datos del usuario; todo lo demás (recursos/,
        # app/, epubtts.exe…) se sobreescribe con la versión nueva, incluyendo
        # recursos/version.json para que el comprobador detecte futuras actualizaciones.
        _PRESERVAR = {
            "configuraciones",
            "Grabaciones_Epub-TTS",
            "bin",
            "actualizacion",
            "INICIAR_APP.bat",
        }

        # Genera las líneas del .bat que borran lo que NO está en _PRESERVAR
        lineas_borrado = []
        try:
            for entrada in os.listdir(raiz):
                if entrada in _PRESERVAR or entrada == "actualizador.bat":
                    continue
                ruta_entrada = os.path.join(raiz, entrada)
                if os.path.isdir(ruta_entrada):
                    lineas_borrado.append(f'rmdir /s /q "{ruta_entrada}"')
                else:
                    lineas_borrado.append(f'del /f /q "{ruta_entrada}"')
        except Exception:
            logger.exception("Error al listar raíz para el script de borrado")

        bloque_borrado = "\n".join(lineas_borrado)

        contenido_bat = (
            "@echo off\n"
            "timeout /t 2 /nobreak >nul\n"
            "\n"
            ":: Eliminar archivos y carpetas de la versión anterior\n"
            f"{bloque_borrado}\n"
            "\n"
            ":: Descomprimir la nueva versión (PowerShell incluido en Windows 10+)\n"
            f'powershell -Command "Expand-Archive -Path \\"{ruta_zip}\\" -DestinationPath \\"{raiz}\\" -Force"\n'
            "\n"
            ":: Mover el contenido de la subcarpeta del ZIP a la raíz del portable\n"
            f'for /d %%D in ("{raiz}\\epub-tts-accesible-*") do (\n'
            f'    robocopy "%%D" "{raiz}" /e /move /xd configuraciones Grabaciones_Epub-TTS bin actualizacion >nul\n'
            "    rmdir /s /q \"%%D\" 2>nul\n"
            ")\n"
            "\n"
            ":: Eliminar el ZIP temporal\n"
            f'rmdir /s /q "{os.path.join(raiz, "actualizacion")}"\n'
            "\n"
            ":: Relanzar la aplicación\n"
            f'start "" "{lanzador}"\n'
            "\n"
            ":: Autoeliminar este script\n"
            "del %0\n"
        )

        ruta_bat_tmp = bat_path + ".tmp"
        with open(ruta_bat_tmp, "w", encoding="cp1252", errors="replace") as f:
            f.write(contenido_bat)
        os.replace(ruta_bat_tmp, bat_path)

        subprocess.Popen(
            ["cmd.exe", "/c", bat_path],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )

        wx.CallAfter(wx.GetTopLevelParent(self).Close)
    # ANCLAJE_FIN: ACTUALIZADOR_SCRIPT_CLON

    # ANCLAJE_INICIO: ACTUALIZADOR_DESCARGA_VERIFICACION_FASE_C
    def _al_probar_descarga_nueva(self, evento=None):
        from app.motor.actualizador_descarga import GestorDescargaActualizacion

        self.btn_probar_descarga_nueva.Disable()
        wx.CallAfter(self.lbl_progreso.SetLabel, "Iniciando descarga de prueba...")

        gestor = GestorDescargaActualizacion()
        gestor.descargar_y_verificar_en_hilo(
            callback_resultado=lambda r: wx.CallAfter(self._al_resultado_descarga_nueva, r),
            callback_progreso=lambda msg, pct: wx.CallAfter(self.lbl_progreso.SetLabel, msg),
        )

    def _al_resultado_descarga_nueva(self, resultado: dict):
        self.btn_probar_descarga_nueva.Enable()
        wx.CallAfter(self.lbl_progreso.SetLabel, "")

        if not resultado.get("ok"):
            logger.warning(
                "Verificación de la descarga de prueba fallida: %s",
                resultado.get("error"),
            )
            reproducir(ERROR)
            wx.MessageBox(
                f"No se pudo verificar la actualización descargada:\n{resultado.get('error')}",
                "Verificación fallida", wx.OK | wx.ICON_ERROR,
            )
            return

        reproducir(SUCCESS)
        ruta_extraida = resultado.get("ruta_extraida")

        from app.config_rutas import RAIZ
        ruta_exe = os.path.join(RAIZ, "bin", "actualizador.exe")

        if not os.path.isfile(ruta_exe):
            # Todavía no se ha compilado/copiado actualizador.exe a bin/ — es
            # el caso esperado mientras se prueba solo la descarga/verificación
            # (Fase C en desarrollo). Se avisa sin ambigüedad y sin cerrar la
            # app, dejando temp/actualizacion/ intacto para poder revisarlo.
            reproducir(ERROR)
            wx.MessageBox(
                "Descarga y verificación completadas correctamente en:\n"
                f"«{ruta_extraida}».\n\n"
                f"El instalador auxiliar todavía no está disponible en:\n{ruta_exe}\n\n"
                "No se instalará nada. Los archivos ya verificados se conservan "
                "en temp/actualizacion/ para que puedas revisarlos.",
                "Instalador no disponible", wx.OK | wx.ICON_WARNING,
            )
            return

        respuesta = wx.MessageBox(
            "Descarga y verificación completadas correctamente.\n\n"
            "Para instalarla, la aplicación se cerrará y un proceso auxiliar "
            "independiente (actualizador.exe) hará el cambio con respaldo "
            "automático. ¿Instalar ahora?",
            "Verificación correcta", wx.YES_NO | wx.ICON_QUESTION,
        )
        if respuesta != wx.YES:
            from app.motor.actualizador_descarga import GestorDescargaActualizacion
            GestorDescargaActualizacion().limpiar()
            return

        self._lanzar_actualizador_auxiliar(ruta_extraida)

    def _lanzar_actualizador_auxiliar(self, ruta_extraida: str):
        """
        Lanza bin/actualizador.exe como proceso independiente con --origen
        apuntando a la versión ya verificada, --destino a la raíz de la
        instalación actual, --pid de este proceso (para que el auxiliar
        espere a que cierre antes de tocar archivos) y --lanzador (más
        --python si la app corre en modo desarrollo) para que el auxiliar
        sepa relanzarla sin depender de INICIAR_APP.bat. Cierra la app para
        liberar los archivos que el auxiliar va a reemplazar.
        """
        import subprocess
        import sys
        from app.config_rutas import RAIZ

        ruta_exe = os.path.join(RAIZ, "bin", "actualizador.exe")
        if not os.path.isfile(ruta_exe):
            reproducir(ERROR)
            wx.MessageBox(
                f"No se encontró el instalador auxiliar en:\n{ruta_exe}\n\n"
                "La actualización no se puede instalar automáticamente en este portable.",
                "Instalador no disponible", wx.OK | wx.ICON_ERROR,
            )
            from app.motor.actualizador_descarga import GestorDescargaActualizacion
            GestorDescargaActualizacion().limpiar()
            return

        if getattr(sys, "frozen", False):
            # Build congelada con PyInstaller: sys.executable ya es el propio
            # epubtts.exe, se relanza directamente sin intérprete.
            lanzador = sys.executable
            interprete = ""
        else:
            # Modo desarrollo: se relanza el script de entrada con el mismo
            # intérprete de Python que está ejecutando esta sesión.
            lanzador = os.path.join(RAIZ, "iniciar_epub_tts.py")
            interprete = sys.executable

        argumentos = [
            ruta_exe,
            "--origen", ruta_extraida,
            "--destino", RAIZ,
            "--pid", str(os.getpid()),
            "--lanzador", lanzador,
        ]
        if interprete:
            argumentos += ["--python", interprete]

        try:
            subprocess.Popen(
                argumentos,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        except Exception as exc:
            logger.exception("No se pudo lanzar actualizador.exe")
            reproducir(ERROR)
            wx.MessageBox(
                f"No se pudo iniciar el instalador auxiliar:\n{exc}",
                "Error al instalar", wx.OK | wx.ICON_ERROR,
            )
            return

        wx.CallAfter(wx.GetTopLevelParent(self).Close)
    # ANCLAJE_FIN: ACTUALIZADOR_DESCARGA_VERIFICACION_FASE_C
# ANCLAJE_FIN: PANEL_GENERAL


# ANCLAJE_INICIO: PANEL_CLAVES
class PanelClaves(wx.ScrolledWindow):
    def __init__(self, padre, config):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Configura tus claves API."), 0, wx.ALL, 10)

        # Azure
        sb_az = wx.StaticBox(self, label="Microsoft Azure TTS")
        sz_az = wx.StaticBoxSizer(sb_az, wx.VERTICAL)
        sz_az.Add(wx.StaticText(self, label="Clave de suscripción (Key). Formato: 32 caracteres hexadecimales:"), 0, wx.ALL, 2)
        self.txt_az_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_az_key.SetHelpText(
            "Clave de suscripción de Azure Text to Speech. "
            "Puedes encontrarla en el Portal de Azure, en tu recurso de Servicios Cognitivos, "
            "sección Claves y Punto de conexión."
        )
        sz_az.Add(self.txt_az_key, 0, wx.EXPAND | wx.ALL, 5)
        sz_az.Add(wx.StaticText(self, label="Región del recurso (ej: eastus, westeurope):"), 0, wx.ALL, 2)
        self.txt_az_region = wx.TextCtrl(self)
        self.txt_az_region.SetHelpText(
            "Región de Azure donde está creado tu recurso. "
            "Ejemplos: eastus, westus2, westeurope."
        )
        sz_az.Add(self.txt_az_region, 0, wx.EXPAND | wx.ALL, 5)
        hb_az = wx.BoxSizer(wx.HORIZONTAL)
        btn_az_web = wx.Button(self, label="Conseguir clave Azure")
        btn_az_web.SetHelpText("Abre el navegador en la página de Azure Text to Speech.")
        btn_az_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://azure.microsoft.com/es-es/services/cognitive-services/text-to-speech/"))
        btn_az_check = wx.Button(self, label="Comprobar clave y descargar voces Azure")
        btn_az_check.SetHelpText("Guarda la clave, la verifica contra el servidor de Azure y descarga la lista de voces disponibles.")
        btn_az_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "azure"))
        aplicar_icono_boton(btn_az_check, "buscar", "Comprobar clave y descargar voces Azure")
        btn_az_del = wx.Button(self, label="Borrar clave Azure")
        btn_az_del.SetHelpText("Borra los datos de acceso de Azure guardados en la aplicación.")
        btn_az_del.Bind(wx.EVT_BUTTON, self.al_borrar_azure)
        aplicar_icono_boton(btn_az_del, "eliminar", "Borrar clave Azure")
        hb_az.Add(btn_az_web, 0, wx.RIGHT, 5)
        hb_az.Add(btn_az_check, 0, wx.RIGHT, 5)
        hb_az.Add(btn_az_del, 0)
        sz_az.Add(hb_az, 0, wx.ALL, 5)
        sizer.Add(sz_az, 0, wx.EXPAND | wx.ALL, 10)

        # Amazon Polly
        sb_po = wx.StaticBox(self, label="Amazon Polly")
        sz_po = wx.StaticBoxSizer(sb_po, wx.VERTICAL)
        sz_po.Add(wx.StaticText(self, label="Access Key ID (identificador de la clave AWS):"), 0, wx.ALL, 2)
        self.txt_po_key = wx.TextCtrl(self)
        self.txt_po_key.SetHelpText(
            "Identificador de clave de acceso de AWS. "
            "Lo encontrarás en la consola de AWS, sección IAM, Mis credenciales de seguridad."
        )
        sz_po.Add(self.txt_po_key, 0, wx.EXPAND | wx.ALL, 5)
        sz_po.Add(wx.StaticText(self, label="Secret Access Key (clave secreta, se muestra solo al crearla):"), 0, wx.ALL, 2)
        self.txt_po_secret = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_po_secret.SetHelpText(
            "Clave de acceso secreta de AWS. Solo se muestra una vez al crearla."
        )
        sz_po.Add(self.txt_po_secret, 0, wx.EXPAND | wx.ALL, 5)
        sz_po.Add(wx.StaticText(self, label="Región AWS (ej: us-east-1, eu-west-1):"), 0, wx.ALL, 2)
        self.txt_po_region = wx.TextCtrl(self)
        self.txt_po_region.SetHelpText("Región de AWS donde usarás Amazon Polly.")
        sz_po.Add(self.txt_po_region, 0, wx.EXPAND | wx.ALL, 5)
        hb_po = wx.BoxSizer(wx.HORIZONTAL)
        btn_po_web = wx.Button(self, label="Conseguir clave Amazon Polly")
        btn_po_web.SetHelpText("Abre el navegador en la página de Amazon Polly.")
        btn_po_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://aws.amazon.com/polly/"))
        btn_po_check = wx.Button(self, label="Comprobar clave y descargar voces Polly")
        btn_po_check.SetHelpText("Guarda las credenciales, las verifica contra AWS y descarga la lista de voces de Amazon Polly.")
        btn_po_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "polly"))
        aplicar_icono_boton(btn_po_check, "buscar", "Comprobar clave y descargar voces Polly")
        btn_po_del = wx.Button(self, label="Borrar clave Polly")
        btn_po_del.SetHelpText("Borra los datos de acceso de Amazon Polly guardados en la aplicación.")
        btn_po_del.Bind(wx.EVT_BUTTON, self.al_borrar_polly)
        aplicar_icono_boton(btn_po_del, "eliminar", "Borrar clave Polly")
        hb_po.Add(btn_po_web, 0, wx.RIGHT, 5)
        hb_po.Add(btn_po_check, 0, wx.RIGHT, 5)
        hb_po.Add(btn_po_del, 0)
        sz_po.Add(hb_po, 0, wx.ALL, 5)
        sizer.Add(sz_po, 0, wx.EXPAND | wx.ALL, 10)

        # ElevenLabs
        sb_el = wx.StaticBox(self, label="ElevenLabs")
        sz_el = wx.StaticBoxSizer(sb_el, wx.VERTICAL)
        sz_el.Add(wx.StaticText(self, label="API Key (clave de acceso de ElevenLabs):"), 0, wx.ALL, 2)
        self.txt_el_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_el_key.SetHelpText(
            "Clave API de ElevenLabs. La encontrarás en tu perfil, sección API Key."
        )
        sz_el.Add(self.txt_el_key, 0, wx.EXPAND | wx.ALL, 5)
        hb_el = wx.BoxSizer(wx.HORIZONTAL)
        btn_el_web = wx.Button(self, label="Conseguir clave ElevenLabs")
        btn_el_web.SetHelpText("Abre el navegador en la página de ElevenLabs.")
        btn_el_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://elevenlabs.io/"))
        btn_el_check = wx.Button(self, label="Comprobar clave y descargar voces ElevenLabs")
        btn_el_check.SetHelpText("Guarda la clave API, la verifica contra ElevenLabs y descarga la lista de voces.")
        btn_el_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "elevenlabs"))
        aplicar_icono_boton(btn_el_check, "buscar", "Comprobar clave y descargar voces ElevenLabs")
        btn_el_del = wx.Button(self, label="Borrar clave ElevenLabs")
        btn_el_del.SetHelpText("Borra la API Key de ElevenLabs guardada en la aplicación.")
        btn_el_del.Bind(wx.EVT_BUTTON, self.al_borrar_elevenlabs)
        aplicar_icono_boton(btn_el_del, "eliminar", "Borrar clave ElevenLabs")
        hb_el.Add(btn_el_web, 0, wx.RIGHT, 5)
        hb_el.Add(btn_el_check, 0, wx.RIGHT, 5)
        hb_el.Add(btn_el_del, 0)
        sz_el.Add(hb_el, 0, wx.ALL, 5)
        sizer.Add(sz_el, 0, wx.EXPAND | wx.ALL, 10)

        # Deepgram
        sb_dg = wx.StaticBox(self, label="Deepgram Aura-2 TTS")
        sz_dg = wx.StaticBoxSizer(sb_dg, wx.VERTICAL)
        sz_dg.Add(wx.StaticText(self, label="API Key de Deepgram:"), 0, wx.ALL, 2)
        self.txt_dg_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_dg_key.SetHelpText(
            "Clave API de Deepgram. La encontrarás en el panel de Deepgram, sección API Keys."
        )
        sz_dg.Add(self.txt_dg_key, 0, wx.EXPAND | wx.ALL, 5)
        hb_dg = wx.BoxSizer(wx.HORIZONTAL)
        btn_dg_web = wx.Button(self, label="Conseguir clave Deepgram")
        btn_dg_web.SetHelpText("Abre el navegador en la página de Deepgram.")
        btn_dg_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://console.deepgram.com/"))
        btn_dg_check = wx.Button(self, label="Comprobar clave y descargar voces Deepgram")
        btn_dg_check.SetHelpText("Guarda la API Key, la verifica contra Deepgram y descarga la lista de modelos Aura-2.")
        btn_dg_check.Bind(wx.EVT_BUTTON, lambda e: self.al_comprobar(e, "deepgram"))
        aplicar_icono_boton(btn_dg_check, "buscar", "Comprobar clave y descargar voces Deepgram")
        btn_dg_del = wx.Button(self, label="Borrar clave Deepgram")
        btn_dg_del.SetHelpText("Borra la API Key de Deepgram guardada en la aplicación.")
        btn_dg_del.Bind(wx.EVT_BUTTON, self.al_borrar_deepgram)
        aplicar_icono_boton(btn_dg_del, "eliminar", "Borrar clave Deepgram")
        hb_dg.Add(btn_dg_web, 0, wx.RIGHT, 5)
        hb_dg.Add(btn_dg_check, 0, wx.RIGHT, 5)
        hb_dg.Add(btn_dg_del, 0)
        sz_dg.Add(hb_dg, 0, wx.ALL, 5)
        sizer.Add(sz_dg, 0, wx.EXPAND | wx.ALL, 10)

        # ANCLAJE_INICIO: PANEL_CLAVES_GEMINI
        sb_ge = wx.StaticBox(self, label="Google Gemini (Asistente de Biblioteca)")
        sz_ge = wx.StaticBoxSizer(sb_ge, wx.VERTICAL)
        sz_ge.Add(wx.StaticText(self, label="API Key de Gemini (AI Studio):"), 0, wx.ALL, 2)
        self.txt_ge_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.txt_ge_key.SetHelpText(
            "Clave API de Google AI Studio para el Asistente de Biblioteca. "
            "Google cambia periódicamente el formato de estas claves (por ejemplo, "
            "de prefijo AIza a prefijo AQ.), así que se guarda tal cual la pegues, "
            "sin comprobar formato ni longitud."
        )
        sz_ge.Add(self.txt_ge_key, 0, wx.EXPAND | wx.ALL, 5)
        sz_ge.Add(wx.StaticText(self, label="Modelo a usar:"), 0, wx.ALL, 2)
        self.combo_ge_modelo = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Automático"])
        self.combo_ge_modelo.SetHelpText(
            "Automático elige el modelo según la consulta: Flash para preguntas rápidas "
            "y Pro para análisis profundos. La lista se completa con los modelos reales "
            "de tu cuenta al comprobar la clave."
        )
        self.combo_ge_modelo.SetSelection(0)
        sz_ge.Add(self.combo_ge_modelo, 0, wx.EXPAND | wx.ALL, 5)
        sz_ge.Add(wx.StaticText(self, label="Temperatura (creatividad de las respuestas):"), 0, wx.ALL, 2)
        # wx.Slider en vez de wx.SpinCtrlDouble: el mismo patrón ya probado con
        # NVDA real en Velocidad/Volumen de Lectura. SpinCtrlDouble no es un
        # control nativo de Windows (lo dibuja la propia wx), y no hereda la
        # misma exposición accesible — NVDA lo anunciaba como "edición,
        # seleccionado 0.3" sin el nombre, pese al SetName().
        self.slider_ge_temperatura = wx.Slider(
            self, value=round(TEMPERATURA_DEFECTO_GEMINI * 10), minValue=0, maxValue=10,
        )
        self.slider_ge_temperatura.SetName("Temperatura de Gemini")
        self.slider_ge_temperatura.SetHelpText(
            "De 0.0 a 1.0, en pasos de 0.1. Valores bajos (0.1 a 0.4) dan "
            "respuestas más precisas y ajustadas al catálogo real, con menos "
            "probabilidad de que el asistente invente títulos, autores o "
            "tramas. Valores altos (0.7 a 1.0) dan respuestas más variadas y "
            "creativas, a costa de más alucinaciones ocasionales. "
            f"Valor de fábrica: {TEMPERATURA_DEFECTO_GEMINI} (recomendado)."
        )
        sz_ge.Add(self.slider_ge_temperatura, 0, wx.EXPAND | wx.ALL, 5)
        hb_ge = wx.BoxSizer(wx.HORIZONTAL)
        btn_ge_web = wx.Button(self, label="Conseguir clave Gemini")
        btn_ge_web.SetHelpText("Abre el navegador en Google AI Studio para crear o copiar tu clave.")
        btn_ge_web.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://aistudio.google.com/apikey"))
        btn_ge_check = wx.Button(self, label="Comprobar clave y listar modelos Gemini")
        btn_ge_check.SetHelpText("Guarda la clave, la verifica contra Gemini y actualiza la lista de modelos disponibles.")
        btn_ge_check.Bind(wx.EVT_BUTTON, self.al_comprobar_gemini)
        aplicar_icono_boton(btn_ge_check, "buscar", "Comprobar clave y listar modelos Gemini")
        btn_ge_del = wx.Button(self, label="Borrar clave Gemini")
        btn_ge_del.SetHelpText("Borra la API Key de Gemini guardada en la aplicación.")
        btn_ge_del.Bind(wx.EVT_BUTTON, self.al_borrar_gemini)
        aplicar_icono_boton(btn_ge_del, "eliminar", "Borrar clave Gemini")
        hb_ge.Add(btn_ge_web, 0, wx.RIGHT, 5)
        hb_ge.Add(btn_ge_check, 0, wx.RIGHT, 5)
        hb_ge.Add(btn_ge_del, 0)
        sz_ge.Add(hb_ge, 0, wx.ALL, 5)
        sizer.Add(sz_ge, 0, wx.EXPAND | wx.ALL, 10)
        # ANCLAJE_FIN: PANEL_CLAVES_GEMINI

        self.btn_save = wx.Button(self, label="Guardar Todas las Claves")
        self.btn_save.Bind(wx.EVT_BUTTON, self.al_guardar)
        aplicar_icono_boton(self.btn_save, "guardar", "Guardar todas las claves")
        sizer.Add(self.btn_save, 0, wx.ALIGN_CENTER | wx.ALL, 15)

        self.SetSizer(sizer)
        self.primer_control = self.txt_az_key
        self.cargar_datos_visuales()

    @property
    def ultimo_control(self):
        return self.btn_save

    def cargar_datos_visuales(self):
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
        d_dg = claves.get("deepgram", {})
        self.txt_dg_key.SetValue(d_dg.get("api_key", ""))
        d_ge = claves.get("gemini", {})
        self.txt_ge_key.SetValue(d_ge.get("api_key", ""))
        self._fijar_modelo_gemini(d_ge.get("modelo", "auto"))
        temperatura = d_ge.get("temperatura", TEMPERATURA_DEFECTO_GEMINI)
        self.slider_ge_temperatura.SetValue(round(temperatura * 10))

    def _fijar_modelo_gemini(self, id_modelo):
        # "auto" (o vacío) siempre es la primera entrada del combo.
        if not id_modelo or id_modelo == "auto":
            self.combo_ge_modelo.SetSelection(0)
            return
        indice = self.combo_ge_modelo.FindString(id_modelo)
        if indice == wx.NOT_FOUND:
            self.combo_ge_modelo.Append(id_modelo)
            indice = self.combo_ge_modelo.FindString(id_modelo)
        self.combo_ge_modelo.SetSelection(indice)

    def al_guardar(self, evento, mensaje="Ajustes de proveedores guardados correctamente."):
        seleccion_ge = self.combo_ge_modelo.GetStringSelection()
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
            "elevenlabs": {"api_key": self.txt_el_key.GetValue().strip()},
            "deepgram": {"api_key": self.txt_dg_key.GetValue().strip()},
            "gemini": {
                "api_key": self.txt_ge_key.GetValue().strip(),
                "modelo": "auto" if seleccion_ge in ("", "Automático") else seleccion_ge,
                "temperatura": round(self.slider_ge_temperatura.GetValue() / 10, 1),
            },
        }
        guardar_claves(claves)
        if evento:
            reproducir(SUCCESS)
            wx.MessageBox(mensaje, "Éxito")

    def al_borrar_azure(self, evento):
        self.txt_az_key.Clear()
        self.txt_az_region.Clear()
        self.al_guardar(evento, "Clave de Azure borrada.")

    def al_borrar_polly(self, evento):
        self.txt_po_key.Clear()
        self.txt_po_secret.Clear()
        self.txt_po_region.Clear()
        self.al_guardar(evento, "Clave de Amazon Polly borrada.")

    def al_borrar_elevenlabs(self, evento):
        self.txt_el_key.Clear()
        self.al_guardar(evento, "Clave de ElevenLabs borrada.")

    def al_borrar_deepgram(self, evento):
        self.txt_dg_key.Clear()
        self.al_guardar(evento, "Clave de Deepgram borrada.")

    def al_borrar_gemini(self, evento):
        self.txt_ge_key.Clear()
        while self.combo_ge_modelo.GetCount() > 1:
            self.combo_ge_modelo.Delete(1)
        self.combo_ge_modelo.SetSelection(0)
        self.al_guardar(evento, "Clave de Gemini borrada.")

    def al_comprobar_gemini(self, evento):
        from app.servicios.cliente_gemini import listar_modelos
        self.al_guardar(None)
        seleccion_previa = self.combo_ge_modelo.GetStringSelection()
        wx.BeginBusyCursor()
        try:
            modelos = listar_modelos()
            wx.EndBusyCursor()
            while self.combo_ge_modelo.GetCount() > 1:
                self.combo_ge_modelo.Delete(1)
            for id_modelo in modelos:
                self.combo_ge_modelo.Append(id_modelo)
            self._fijar_modelo_gemini(seleccion_previa)
            reproducir(SUCCESS)
            wx.MessageBox(f"Clave de Gemini válida. Modelos disponibles: {len(modelos)}.", "Info")
        except Exception as e:
            wx.EndBusyCursor()
            logger.exception("Error al comprobar la clave de Gemini")
            reproducir(ERROR)
            wx.MessageBox(f"Error: {e}", "Error")

    def al_comprobar(self, evento, proveedor=None):
        from app.motor.cliente_nube_voces import GestorVoces
        self.al_guardar(None)
        wx.BeginBusyCursor()
        try:
            gestor = GestorVoces()
            res = gestor.actualizar_proveedor(proveedor) if proveedor else gestor.actualizar_voces_desde_internet()
            wx.EndBusyCursor()
            reproducir(SUCCESS)
            wx.MessageBox(f"Resultado:\n{res}", "Info")
            try:
                ventana = wx.GetTopLevelParent(self)
                if hasattr(ventana, 'pestana_ajustes'):
                    wx.CallAfter(ventana.pestana_ajustes._recargar_panel_proveedor, proveedor)
            except Exception:
                logger.exception("Error al recargar panel de proveedor tras descarga de voces")
        except Exception as e:
            wx.EndBusyCursor()
            reproducir(ERROR)
            wx.MessageBox(f"Error: {e}", "Error")
# ANCLAJE_FIN: PANEL_CLAVES


# PanelProveedorIA se mudó a app/interfaz/selector_voz_compartido.py (bloque
# ANCLAJE BASE_PANEL_PROVEEDOR_IA), importada arriba junto a ListaVocesCheck.


# ANCLAJE_INICIO: PANEL_AZURE
class PanelAzure(PanelProveedorIA):
    """
    Panel de Azure Neural. Añade un combo de características (Neural,
    Multilingüe, Dragon, MaiVoice, Flash) mediante los ganchos
    _construir_controles_extra y _obtener_filtros_extra — mismo patrón que
    PanelPolly. Azure no expone estas características como un campo propio
    en la API de voces; se detectan por palabras clave en el id de la voz
    (p. ej. "es-ES-XimenaMultilingualNeural", "en-US-Emma2:DragonHDLatestNeural").
    """

    _CARACTERISTICAS_ETIQUETA = {
        "Multilingüe": "multilingual",
        "Dragon":      "dragon",
        "MaiVoice":    "maivoice",
        "Flash":       "flash",
        "Neural":      "neural",
    }

    def __init__(self, padre, config):
        super().__init__(padre, config, "azure", "Azure Neural")

    def _construir_controles_extra(self, sizer):
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(
            wx.StaticText(self, label="Característica:"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self.combo_caracteristica = wx.ComboBox(
            self,
            style=wx.CB_READONLY,
            choices=["Todas"] + list(self._CARACTERISTICAS_ETIQUETA.keys()),
        )
        self.combo_caracteristica.SetSelection(0)
        self.combo_caracteristica.SetHelpText(
            "Filtra las voces de Azure por características detectadas en su "
            "nombre técnico: Multilingüe (varios idiomas), Dragon (calidad HD "
            "más reciente), MaiVoice, Flash (baja latencia) o Neural genérica."
        )
        self.combo_caracteristica.Bind(wx.EVT_COMBOBOX, self._al_filtrar)
        hbox.Add(self.combo_caracteristica, 0)
        sizer.Add(hbox, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    @staticmethod
    def _normalizar_id(texto: str) -> str:
        """
        Quita guiones, dos puntos, guiones bajos y espacios antes de
        comparar, y pasa a minúsculas. El id técnico de Azure (ShortName)
        combina estos separadores de forma inconsistente entre familias de
        voces (p. ej. "MaiVoice2", "Mai-Voice", "Dragon HD") — sin esta
        normalización, "MaiVoice" no coincidía con variantes que llevan
        separador, y el filtro se quedaba con la lista vacía.
        """
        return re.sub(r'[\s\-_:]', '', texto or '').lower()

    def _obtener_filtros_extra(self, voz):
        if not hasattr(self, 'combo_caracteristica'):
            return True
        etiqueta = self.combo_caracteristica.GetValue()
        if etiqueta == "Todas":
            return True
        clave_buscada = self._CARACTERISTICAS_ETIQUETA.get(etiqueta)
        if clave_buscada is None:
            return True
        id_voz = self._normalizar_id(voz.get("id", ""))
        if clave_buscada == "neural":
            # "Neural" como filtro genérico: cualquier voz que NO tenga
            # ninguna de las otras características más específicas.
            otras = [v for k, v in self._CARACTERISTICAS_ETIQUETA.items() if v != "neural"]
            return not any(c in id_voz for c in otras)
        return clave_buscada in id_voz
# ANCLAJE_FIN: PANEL_AZURE


# ANCLAJE_INICIO: PANEL_DEEPGRAM
class PanelDeepgram(PanelProveedorIA):
    def __init__(self, padre, config):
        super().__init__(padre, config, "deepgram", "Deepgram Aura-2")
# ANCLAJE_FIN: PANEL_DEEPGRAM


# ANCLAJE_INICIO: PANEL_POLLY
class PanelPolly(PanelProveedorIA):
    """
    Panel de Amazon Polly. Añade un combo de tipo de motor (Neural / Estándar /
    Generativa) mediante los ganchos _construir_controles_extra y _obtener_filtros_extra.
    """

    # Mapa de etiquetas legibles → valores que aparecen en voz["motores"]
    _MOTORES_ETIQUETA = {
        "Neural":                  "neural",
        "Estándar":                "standard",
        "Generativa (Long-form)":  "long-form",
        "Generativa":              "generative",
    }

    def __init__(self, padre, config):
        super().__init__(padre, config, "polly", "Amazon Polly")

    def _construir_controles_extra(self, sizer):
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(
            wx.StaticText(self, label="Tipo de motor:"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self.combo_motor = wx.ComboBox(
            self,
            style=wx.CB_READONLY,
            choices=["Todos"] + list(self._MOTORES_ETIQUETA.keys()),
        )
        self.combo_motor.SetSelection(0)
        self.combo_motor.SetHelpText(
            "Filtra las voces de Amazon Polly por tipo de motor. "
            "Neural: mayor calidad y naturalidad. "
            "Estándar: compatible con todos los planes. "
            "Generativa Long-form: optimizada para textos largos. "
            "Generativa: motor generativo estándar."
        )
        self.combo_motor.Bind(wx.EVT_COMBOBOX, self._al_filtrar)
        hbox.Add(self.combo_motor, 0)
        sizer.Add(hbox, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    def _obtener_filtros_extra(self, voz):
        if not hasattr(self, 'combo_motor'):
            return True
        f_motor = self.combo_motor.GetValue()
        if f_motor == "Todos":
            return True
        valor_buscado = self._MOTORES_ETIQUETA.get(f_motor)
        if valor_buscado is None:
            return True
        motores_voz = voz.get("motores", [])
        return valor_buscado in motores_voz
# ANCLAJE_FIN: PANEL_POLLY


# ANCLAJE_INICIO: PANEL_ELEVENLABS
class PanelElevenLabs(PanelProveedorIA):
    def __init__(self, padre, config):
        super().__init__(padre, config, "elevenlabs", "ElevenLabs")
# ANCLAJE_FIN: PANEL_ELEVENLABS


# ANCLAJE_INICIO: PANEL_SAPI5
class PanelSapi5(wx.Panel):
    """
    Panel de catálogo para voces locales SAPI5.
    Más simple que los paneles cloud: sin filtro de idioma ni voces nuevas.
    Solo casilla de favoritas, lista con casillas nativas y preescucha.
    """

    def __init__(self, padre, config):
        super().__init__(padre)
        self.config = config
        self.voces_todas = []
        self.mapa_indices = {}
        self.ruta_favs = ruta_config("voces_favoritas.json")
        self.favoritos = self._cargar_favoritos()
        self._construir_ui()
        wx.CallAfter(self.cargar_datos)

    def _construir_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(
            wx.StaticText(self, label="Voces SAPI5 instaladas en este equipo:"),
            0, wx.ALL, 8,
        )

        self.chk_solo_favs = wx.CheckBox(self, label="Solo favoritas")
        self.chk_solo_favs.SetHelpText(
            "Marcada: muestra solo las voces SAPI5 marcadas como favoritas. "
            "Desmarcada: muestra todas las voces SAPI5 del sistema."
        )
        self.chk_solo_favs.Bind(wx.EVT_CHECKBOX, self._al_filtrar)
        sizer.Add(self.chk_solo_favs, 0, wx.LEFT | wx.BOTTOM, 8)

        self.lista_voces = ListaVocesCheck(self)
        self.lista_voces.InsertColumn(0, "Nombre", width=320)
        self.lista_voces.InsertColumn(1, "Idioma", width=200)
        self.lista_voces.SetHelpText(
            "Lista de voces SAPI5 locales instaladas en este equipo. "
            "Usa las flechas para navegar. "
            "Pulsa Intro para marcar o desmarcar una voz como favorita. "
            "Las voces marcadas aparecerán en las pestañas Lectura y Grabación."
        )
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_CHECKED, self._al_marcar_favorito)
        self.lista_voces.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._al_desmarcar_favorito)
        sizer.Add(self.lista_voces, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        from app.motor.reproductor_voz import ReproductorVoz
        self._reproductor = ReproductorVoz()

        self.btn_escuchar = wx.Button(self, label="Escuchar muestra (Alt+P)")
        self.btn_escuchar.SetHelpText(
            "Reproduce una muestra de texto con la voz SAPI5 seleccionada. "
            "Púlsalo de nuevo para detener la reproducción."
        )
        self.btn_escuchar.Bind(wx.EVT_BUTTON, self._al_escuchar)
        sizer.Add(self.btn_escuchar, 0, wx.ALL, 8)

        id_play = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._al_escuchar, id=id_play)
        self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_ALT, ord('P'), id_play)]))

        self.SetSizer(sizer)
        self.primer_control = self.chk_solo_favs

    @property
    def ultimo_control(self):
        return self.btn_escuchar

    def cargar_datos(self):
        self.voces_todas = []
        try:
            from app.servicios.cliente_sapi5 import ClienteSapi5
            for v in ClienteSapi5().obtener_voces():
                v["es_nueva"] = False
                self.voces_todas.append(v)
        except Exception:
            logger.exception("Error al cargar voces SAPI5 locales")
        # Añadir voces de 32 bits si el proceso auxiliar está disponible
        try:
            from app.servicios.cliente_sapi32_bridge import ClienteSapi32Bridge
            bridge = ClienteSapi32Bridge()
            if bridge.conectado:
                ids_existentes = {v.get("id") for v in self.voces_todas}
                for v in bridge.obtener_voces():
                    if v.get("id") not in ids_existentes:
                        v["es_nueva"] = False
                        self.voces_todas.append(v)
                bridge.cerrar()
        except Exception:
            logger.exception("Error al cargar voces SAPI5 de 32 bits")
        self._filtrar_y_mostrar()

    def _al_filtrar(self, evento):
        self._filtrar_y_mostrar()

    def _filtrar_y_mostrar(self):
        self.lista_voces.Freeze()
        self.lista_voces.DeleteAllItems()
        self.mapa_indices = {}
        solo_favs = self.chk_solo_favs.IsChecked()
        idx = 0
        for voz in self.voces_todas:
            id_voz = voz.get("id", "")
            es_favorita = id_voz in self.favoritos
            if solo_favs and not es_favorita:
                continue
            pos = self.lista_voces.InsertItem(idx, voz.get("nombre", ""))
            self.lista_voces.SetItem(pos, 1, voz.get("idioma", ""))
            if es_favorita:
                self.lista_voces.CheckItem(pos, True)
            self.mapa_indices[pos] = voz
            idx += 1
        self.lista_voces.Thaw()

    def _cargar_favoritos(self):
        try:
            if os.path.exists(self.ruta_favs):
                with open(self.ruta_favs, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            logger.exception("Error al leer voces_favoritas.json (SAPI5)")
        return []

    def _guardar_favoritos(self):
        # Escritura atómica: primero .tmp, luego renombrar
        ruta_tmp = self.ruta_favs + ".tmp"
        try:
            with open(ruta_tmp, 'w', encoding='utf-8') as f:
                json.dump(self.favoritos, f, indent=4)
            os.replace(ruta_tmp, self.ruta_favs)
        except Exception:
            logger.exception("Error al guardar voces_favoritas.json (SAPI5)")

    def _al_marcar_favorito(self, evento):
        voz = self.mapa_indices.get(evento.GetIndex())
        if voz:
            id_voz = voz.get("id")
            if id_voz not in self.favoritos:
                self.favoritos.append(id_voz)
                self._guardar_favoritos()
                wx.CallAfter(self._notificar_pestanas)

    def _al_desmarcar_favorito(self, evento):
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
            logger.exception("Error al notificar cambio de favoritos SAPI5 a otras pestañas")

    def _al_escuchar(self, evento):
        if self._reproductor.obtener_estado() == "reproduciendo":
            self._reproductor.detener()
            self.btn_escuchar.SetLabel("Escuchar muestra (Alt+P)")
            return
        idx = self.lista_voces.GetFirstSelected()
        if idx == -1:
            reproducir(ERROR)
            wx.MessageBox("Selecciona una voz.", "Info")
            return
        voz = self.mapa_indices.get(idx)
        nombre = voz.get('nombre', '')
        try:
            self._reproductor.fijar_voz(voz)
            texto = (
                f"Hola, mi nombre es {nombre}. "
                "Esta es una muestra de voz local de tu sistema."
            )
            self.btn_escuchar.SetLabel("Detener preescucha (Alt+P)")
            self._reproductor.cargar_texto(texto, callback_completado=self._al_terminar_escucha)
        except Exception as e:
            self.btn_escuchar.SetLabel("Escuchar muestra (Alt+P)")
            reproducir(ERROR)
            wx.MessageBox(f"Error: {e}", "Error")

    def _al_terminar_escucha(self):
        wx.CallAfter(self.btn_escuchar.SetLabel, "Escuchar muestra (Alt+P)")
# ANCLAJE_FIN: PANEL_SAPI5


# ANCLAJE_INICIO: PANEL_DICCIONARIO
class PanelDiccionario(wx.Panel):
    """
    Habitación del diccionario de pronunciación local (pronunciacion.json).
    Permite añadir, editar y eliminar entradas sin reiniciar la aplicación.
    Guarda cambios de forma explícita con el botón «Guardar Cambios (Alt+G)».
    Si hay cambios pendientes al navegar a otro nodo del árbol, solicita confirmación.
    """

    def __init__(self, padre):
        super().__init__(padre)
        from app.motor.diccionario_pronunciacion import DiccionarioPronunciacion
        self._dic = DiccionarioPronunciacion()
        self._pendiente = False
        # id_libro a preseleccionar cuando se abre este panel desde el menú
        # contextual de Biblioteca ("Reglas de pronunciación de este libro").
        # Ver PestanaAjustes.abrir_diccionario_para_libro().
        self._id_libro_a_preseleccionar = None
        self._construir_ui()
        wx.CallAfter(self._rellenar_lista)

    def _construir_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ANCLAJE_INICIO: SELECTOR_ALCANCE_DICCIONARIO
        sz_alcance = wx.BoxSizer(wx.HORIZONTAL)
        sz_alcance.Add(
            wx.StaticText(self, label="Alcance:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5,
        )
        self.combo_alcance = wx.Choice(self, choices=["Global", "Este libro", "Esta saga"])
        self.combo_alcance.SetSelection(0)
        self.combo_alcance.SetHelpText(
            "Global aplica a todos los libros. Este libro o Esta saga solo afectan "
            "al libro o a la saga/etiqueta que elijas a la derecha, sin tocar el resto "
            "de tu biblioteca."
        )
        self.combo_alcance.Bind(wx.EVT_CHOICE, self._al_cambiar_alcance)
        sz_alcance.Add(self.combo_alcance, 0, wx.RIGHT, 15)

        self.combo_referencia = wx.Choice(self, choices=[])
        self.combo_referencia.SetHelpText(
            "Elige el libro o la saga/etiqueta a la que se aplicarán las reglas de esta lista."
        )
        self.combo_referencia.Bind(wx.EVT_CHOICE, self._al_cambiar_referencia)
        self.combo_referencia.Hide()
        sz_alcance.Add(self.combo_referencia, 1)
        sizer.Add(sz_alcance, 0, wx.EXPAND | wx.ALL, 8)
        # ANCLAJE_FIN: SELECTOR_ALCANCE_DICCIONARIO

        sizer.Add(
            wx.StaticText(self, label="Palabras con pronunciación personalizada:"),
            0, wx.ALL, 8,
        )

        self.lista = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.lista.InsertColumn(0, "Palabra original", width=200)
        self.lista.InsertColumn(1, "Pronunciación fonética", width=320)
        self.lista.SetHelpText(
            "Lista de sustituciones activas. Selecciona una entrada y usa los botones "
            "para editarla o eliminarla."
        )
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self._al_seleccionar)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        sz_form = wx.BoxSizer(wx.HORIZONTAL)
        sz_form.Add(wx.StaticText(self, label="Palabra:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.txt_original = wx.TextCtrl(self)
        self.txt_original.SetHelpText("Escribe la palabra o sigla tal como aparece en el texto.")
        self.txt_original.Bind(wx.EVT_TEXT, self._al_modificar_campo)
        sz_form.Add(self.txt_original, 1, wx.RIGHT, 10)
        sz_form.Add(wx.StaticText(self, label="Pronunciación:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.txt_pronunciacion = wx.TextCtrl(self)
        self.txt_pronunciacion.SetHelpText(
            "Escribe la pronunciación fonética que usará la voz. "
            "Ejemplo: NVDA → en-ví-di-ei"
        )
        self.txt_pronunciacion.Bind(wx.EVT_TEXT, self._al_modificar_campo)
        sz_form.Add(self.txt_pronunciacion, 1)
        sizer.Add(sz_form, 0, wx.EXPAND | wx.ALL, 8)

        sz_btn = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_anadir = wx.Button(self, label="Añadir / Actualizar")
        self.btn_anadir.SetHelpText(
            "Guarda la entrada del formulario en la lista. "
            "Si la palabra ya existe, actualiza su pronunciación."
        )
        self.btn_anadir.Bind(wx.EVT_BUTTON, self._al_anadir)
        aplicar_icono_boton(self.btn_anadir, "añadir", "Añadir o actualizar")
        self.btn_eliminar = wx.Button(self, label="Eliminar seleccionada")
        self.btn_eliminar.SetHelpText("Elimina la entrada seleccionada en la lista.")
        self.btn_eliminar.Bind(wx.EVT_BUTTON, self._al_eliminar)
        aplicar_icono_boton(self.btn_eliminar, "eliminar", "Eliminar seleccionada")
        self.btn_guardar = wx.Button(self, label="Guardar cambios\tAlt+G")
        self.btn_guardar.SetHelpText(
            "Guarda todos los cambios del diccionario en disco y recarga la pronunciación activa."
        )
        self.btn_guardar.Bind(wx.EVT_BUTTON, self._al_guardar_cambios)
        aplicar_icono_boton(self.btn_guardar, "guardar", "Guardar cambios")
        sz_btn.Add(self.btn_anadir, 0, wx.RIGHT, 8)
        sz_btn.Add(self.btn_eliminar, 0, wx.RIGHT, 8)
        sz_btn.Add(self.btn_guardar, 0)
        sizer.Add(sz_btn, 0, wx.ALL, 8)

        tabla_accel = wx.AcceleratorTable([
            (wx.ACCEL_ALT, ord('G'), self.btn_guardar.GetId()),
        ])
        self.SetAcceleratorTable(tabla_accel)

        self.SetSizer(sizer)
        self.primer_control = self.txt_original

    @property
    def ultimo_control(self):
        return self.btn_guardar

    def tiene_cambios_pendientes(self):
        return self._pendiente

    def _al_modificar_campo(self, evento):
        self._pendiente = True
        evento.Skip()

    # ── Alcance: Global (JSON) vs. Este libro / Esta saga (biblioteca.db) ──

    def _alcance_actual(self) -> str:
        return {0: "global", 1: "libro", 2: "saga"}[self.combo_alcance.GetSelection()]

    def _al_cambiar_alcance(self, evento):
        alcance = self._alcance_actual()
        self.combo_referencia.Show(alcance != "global")
        self.btn_guardar.Enable(alcance == "global")
        self.Layout()
        if alcance == "global":
            self._rellenar_lista()
            return
        self._rellenar_combo_referencia(alcance)

    def _rellenar_combo_referencia(self, alcance: str):
        from app.motor.gestor_biblioteca import GestorBiblioteca
        gestor = GestorBiblioteca()
        self.combo_referencia.Clear()
        self._referencias = []  # lista paralela: (id, nombre) por índice del combo
        if alcance == "libro":
            for libro in gestor.buscar_libros():
                self._referencias.append((libro["id"], libro["titulo"]))
        else:  # saga
            for etiqueta in gestor.listar_etiquetas():
                self._referencias.append((etiqueta["id"], etiqueta["nombre"]))
        self.combo_referencia.Set([nombre for _id, nombre in self._referencias])

        indice_preseleccion = 0
        if alcance == "libro" and self._id_libro_a_preseleccionar is not None:
            for i, (id_ref, _nombre) in enumerate(self._referencias):
                if id_ref == self._id_libro_a_preseleccionar:
                    indice_preseleccion = i
                    break
        self._id_libro_a_preseleccionar = None

        if self._referencias:
            self.combo_referencia.SetSelection(indice_preseleccion)
            self._rellenar_lista()
        else:
            self.lista.DeleteAllItems()

    def _al_cambiar_referencia(self, evento):
        self._rellenar_lista()

    def preseleccionar_libro(self, id_libro: int):
        """Llamado desde Biblioteca para abrir este panel ya en alcance 'Este libro'."""
        self._id_libro_a_preseleccionar = id_libro
        self.combo_alcance.SetSelection(1)
        self._al_cambiar_alcance(None)

    def _rellenar_lista(self):
        self.lista.Freeze()
        self.lista.DeleteAllItems()
        alcance = self._alcance_actual()
        if alcance == "global":
            for i, (original, pronunciacion) in enumerate(sorted(self._dic.obtener_tabla().items())):
                self.lista.InsertItem(i, original)
                self.lista.SetItem(i, 1, pronunciacion)
        else:
            self._reglas_mostradas = self._obtener_reglas_alcance_actual()
            for i, regla in enumerate(self._reglas_mostradas):
                self.lista.InsertItem(i, regla["patron_origen"])
                self.lista.SetItem(i, 1, regla["sustitucion"])
        self.lista.Thaw()

    def _referencia_seleccionada(self):
        indice = self.combo_referencia.GetSelection()
        if indice == wx.NOT_FOUND or not getattr(self, "_referencias", None):
            return None
        return self._referencias[indice][0]

    def _obtener_reglas_alcance_actual(self):
        id_referencia = self._referencia_seleccionada()
        if id_referencia is None:
            return []
        from app.motor.gestor_biblioteca import GestorBiblioteca
        gestor = GestorBiblioteca()
        return gestor.listar_reglas_diccionario(self._alcance_actual(), id_referencia)

    def _al_seleccionar(self, evento):
        idx = evento.GetIndex()
        self.txt_original.SetValue(self.lista.GetItemText(idx, 0))
        self.txt_pronunciacion.SetValue(self.lista.GetItemText(idx, 1))

    def _al_anadir(self, evento):
        original = self.txt_original.GetValue().strip()
        pronunciacion = self.txt_pronunciacion.GetValue().strip()
        if not original or not pronunciacion:
            wx.MessageBox("Rellena los dos campos.", "Aviso")
            return

        alcance = self._alcance_actual()
        if alcance == "global":
            self._dic.anadir_entrada(original, pronunciacion)
            self._pendiente = True
        else:
            id_referencia = self._referencia_seleccionada()
            if id_referencia is None:
                wx.MessageBox("Elige primero un libro o una saga a la derecha.", "Aviso")
                return
            from app.motor.gestor_biblioteca import GestorBiblioteca
            gestor = GestorBiblioteca()
            existente = next(
                (r for r in self._obtener_reglas_alcance_actual()
                 if r["patron_origen"].lower() == original.lower()),
                None,
            )
            if existente:
                gestor.actualizar_regla_diccionario(existente["id"], original, pronunciacion)
            else:
                gestor.anadir_regla_diccionario(original, pronunciacion, alcance, id_referencia)

        self.txt_original.Clear()
        self.txt_pronunciacion.Clear()
        self._rellenar_lista()

    def _al_eliminar(self, evento):
        idx = self.lista.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Selecciona una entrada de la lista.", "Aviso")
            return

        alcance = self._alcance_actual()
        if alcance == "global":
            original = self.lista.GetItemText(idx, 0)
            self._dic.eliminar_entrada(original)
            self._pendiente = True
        else:
            regla = self._reglas_mostradas[idx]
            from app.motor.gestor_biblioteca import GestorBiblioteca
            GestorBiblioteca().eliminar_regla_diccionario(regla["id"])

        self._rellenar_lista()

    def _al_guardar_cambios(self, evento):
        try:
            self._dic.guardar()
            self._pendiente = False
            from app.motor.limpiador_lectura import recargar_diccionario_pronunciacion
            recargar_diccionario_pronunciacion()
            wx.MessageBox("Diccionario guardado correctamente.", "Guardado", wx.OK | wx.ICON_INFORMATION)
        except Exception:
            logger.exception("Error al guardar el diccionario de pronunciación")
            wx.MessageBox("No se pudo guardar el diccionario.", "Error", wx.OK | wx.ICON_ERROR)
# ANCLAJE_FIN: PANEL_DICCIONARIO


# ANCLAJE_INICIO: DIALOGO_CAPTURA_TECLA
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
        self.resultado = None

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

    def _al_capturar(self, evento):
        key = evento.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.resultado = None
            self.EndModal(wx.ID_CANCEL)
            return
        if key in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT,
                   wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT, wx.WXK_WINDOWS_MENU):
            return
        mods = []
        if evento.ControlDown(): mods.append("Ctrl")
        if evento.AltDown():     mods.append("Alt")
        if evento.ShiftDown():   mods.append("Shift")
        if key in self._ESPECIALES:
            nombre_tecla = self._ESPECIALES[key]
        elif 32 <= key <= 127:
            nombre_tecla = chr(key).upper()
        else:
            return
        self.resultado = ("+".join(mods), nombre_tecla)
        combo = f"{'+'.join(mods)}+{nombre_tecla}" if mods else nombre_tecla
        self.lbl_capturada.SetLabel(f"Asignando: {combo}")
        self.EndModal(wx.ID_OK)
# ANCLAJE_FIN: DIALOGO_CAPTURA_TECLA


# ANCLAJE_INICIO: PANEL_ATAJOS
class PanelAtajos(wx.Panel):
    def __init__(self, padre):
        super().__init__(padre)

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
            "Pulsa Intro para abrir el diálogo de asignación de la acción seleccionada."
        )
        self.lista.Bind(wx.EVT_KEY_DOWN, self._al_tecla_lista)
        sizer.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_asignar = wx.Button(self, label="Asignar nueva tecla al atajo seleccionado")
        self.btn_asignar.SetHelpText(
            "Abre un diálogo donde puedes pulsar la combinación de teclas que quieres asignar."
        )
        self.btn_eliminar = wx.Button(self, label="Eliminar asignación personalizada")
        self.btn_eliminar.SetHelpText(
            "Elimina la asignación personalizada y vuelve a la tecla predeterminada."
        )
        self.btn_restablecer = wx.Button(self, label="Restablecer todos los atajos a valores predeterminados")
        self.btn_restablecer.SetHelpText(
            "Borra todas las personalizaciones y devuelve todos los atajos a sus valores de fábrica."
        )
        self.btn_asignar.Bind(wx.EVT_BUTTON, self._al_asignar)
        self.btn_eliminar.Bind(wx.EVT_BUTTON, self._al_eliminar)
        self.btn_restablecer.Bind(wx.EVT_BUTTON, self._al_restablecer)
        aplicar_icono_boton(self.btn_eliminar, "eliminar", "Eliminar asignación personalizada")
        aplicar_icono_boton(self.btn_restablecer, "restablecer", "Restablecer todos los atajos a valores predeterminados")
        hbox.Add(self.btn_asignar, 0, wx.RIGHT, 10)
        hbox.Add(self.btn_eliminar, 0, wx.RIGHT, 10)
        hbox.Add(self.btn_restablecer, 0)
        sizer.Add(hbox, 0, wx.ALL, 10)

        sb_fijos = wx.StaticBox(self, label="Atajos fijos del menú (no configurables)")
        sz_fijos = wx.StaticBoxSizer(sb_fijos, wx.VERTICAL)
        _FIJOS = [
            ("Ctrl+A",       "Cargar libro (menú Archivo)"),
            ("Ctrl+T",       "Abrir TXT para grabar (menú Archivo, activo en pestaña Grabación)"),
            ("Ctrl+Shift+P", "Abrir gestor de proyectos (menú Proyectos)"),
            ("Ctrl+B",       "Buscar en el texto (pestaña Lectura)"),
            ("Ctrl+G",       "Ir a página del capítulo, del libro o porcentaje (pestaña Lectura)"),
            ("Ctrl+I",       "Consultar páginas virtuales actuales del capítulo y del libro (pestaña Lectura)"),
            ("Ctrl+S",       "Guardar configuración general (pestaña Ajustes)"),
            ("Ctrl+M",       "Gestor de marcadores (pestaña Lectura)"),
            ("Alt+F4",       "Salir de la aplicación"),
        ]
        for atajo, desc in _FIJOS:
            sz_fijos.Add(wx.StaticText(self, label=f"  {atajo:<20}  {desc}"), 0, wx.LEFT | wx.TOP, 4)
        sizer.Add(sz_fijos, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)
        self.primer_control = self.lista
        self._rellenar_lista()

    @property
    def ultimo_control(self):
        return self.btn_restablecer

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
            col_accion = f"{desc} ({tecla_def})"
            col_tecla = tecla_actual if tecla_actual == tecla_def else f"{tecla_actual}  [personalizada]"
            self.lista.InsertItem(i, col_accion)
            self.lista.SetItem(i, 1, col_tecla)
        if self.lista.GetItemCount() > 0:
            self.lista.Select(0)

    def _al_tecla_lista(self, evento):
        key = evento.GetKeyCode()
        if key == wx.WXK_RETURN:
            self._al_asignar(None)
        else:
            if key in (wx.WXK_UP, wx.WXK_DOWN):
                reproducir(LIST_NAV)
            evento.Skip()

    def _refrescar_aceleradores_frame(self):
        ventana = wx.GetTopLevelParent(self)
        if hasattr(ventana, '_configurar_aceleradores_globales'):
            ventana._configurar_aceleradores_globales()

    def _al_asignar(self, evento):
        from app.motor.gestor_atajos import guardar_atajo_usuario
        idx = self.lista.GetFirstSelected()
        if idx == -1:
            reproducir(ERROR)
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

    def _al_eliminar(self, evento):
        from app.motor.gestor_atajos import eliminar_atajo_usuario
        idx = self.lista.GetFirstSelected()
        if idx == -1:
            reproducir(ERROR)
            wx.MessageBox("Selecciona un atajo de la lista primero.", "Info")
            return
        clave = self._claves[idx]
        eliminar_atajo_usuario(clave)
        self._rellenar_lista()
        self._refrescar_aceleradores_frame()
        if idx < self.lista.GetItemCount():
            self.lista.Select(idx)

    def _al_restablecer(self, evento):
        from app.motor.gestor_atajos import restablecer_todos
        if wx.MessageBox(
            "¿Restablecer todos los atajos a los valores predeterminados?",
            "Confirmar", wx.YES_NO | wx.ICON_QUESTION,
        ) == wx.YES:
            restablecer_todos()
            self._rellenar_lista()
            self._refrescar_aceleradores_frame()
            reproducir(SUCCESS)
            wx.MessageBox("Todos los atajos han vuelto a sus valores predeterminados.", "Listo")
# ANCLAJE_FIN: PANEL_ATAJOS


# ANCLAJE_INICIO: PANEL_SONIDOS
class PanelSonidos(wx.Panel):
    """Casilla global de sonidos de la app + selector de prueba individual."""

    def __init__(self, padre):
        super().__init__(padre)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Efectos de sonido:"), 0, wx.LEFT | wx.TOP, 8)

        self.chk_habilitados = wx.CheckBox(
            self, label="Habilitar todos los efectos de sonido de la aplicación"
        )
        self.chk_habilitados.SetValue(sonidos_habilitados())
        self.chk_habilitados.SetHelpText(
            "Desmarca esta casilla para silenciar todos los sonidos de la app: "
            "navegación, éxito, error, y el resto de efectos."
        )
        self.chk_habilitados.Bind(wx.EVT_CHECKBOX, self.al_cambiar_habilitados)
        sizer.Add(self.chk_habilitados, 0, wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Probar un efecto:"), 0, wx.LEFT, 8)
        self._ids_sonidos = list(SONIDOS_DISPONIBLES.keys())
        self.combo_sonidos = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_sonidos.Set([SONIDOS_DISPONIBLES[i] for i in self._ids_sonidos])
        self.combo_sonidos.SetSelection(0)
        self.combo_sonidos.Bind(wx.EVT_COMBOBOX, self.al_cambiar_sonido_seleccionado)
        sizer.Add(self.combo_sonidos, 0, wx.EXPAND | wx.ALL, 8)

        self.btn_probar = wx.Button(self, label="Probar sonido")
        self.btn_probar.SetHelpText(
            "Reproduce el efecto seleccionado, incluso si está desactivado "
            "(individualmente o con la casilla global)."
        )
        self.btn_probar.Bind(wx.EVT_BUTTON, self.al_probar_sonido)
        sizer.Add(self.btn_probar, 0, wx.ALL, 8)

        # Activar/desactivar únicamente el efecto elegido en el combo de
        # arriba, independiente de la casilla global. La propia etiqueta del
        # botón lleva el nombre del efecto para que NVDA la lea entera al
        # llegar con Tab, sin tener que adivinar a qué sonido se refiere.
        self.btn_alternar_individual = wx.Button(self)
        self.btn_alternar_individual.Bind(wx.EVT_BUTTON, self.al_alternar_individual)
        sizer.Add(self.btn_alternar_individual, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.primer_control = self.chk_habilitados
        self.ultimo_control = self.btn_alternar_individual

        self._actualizar_boton_alternar()

    def al_cambiar_habilitados(self, evento):
        # Sin voz.hablar() aquí: wx.CheckBox ya anuncia "marcado"/"desmarcado"
        # de forma nativa con NVDA al pulsar Espacio o Intro; añadir una
        # confirmación propia duplicaría esa lectura, el mismo problema que
        # se corrigió en el combo de "Estilo del asistente".
        fijar_sonidos_habilitados(self.chk_habilitados.GetValue())

    def al_cambiar_sonido_seleccionado(self, evento):
        self._actualizar_boton_alternar()

    def _sonido_seleccionado(self):
        idx = self.combo_sonidos.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        return self._ids_sonidos[idx]

    def _actualizar_boton_alternar(self):
        nombre_id = self._sonido_seleccionado()
        if nombre_id is None:
            return
        nombre_legible = SONIDOS_DISPONIBLES[nombre_id]
        # Cambiar la etiqueta de un botón que tiene el foco sí lo vuelve a
        # anunciar con NVDA (a diferencia de wx.StaticText.SetLabel()): es
        # el mismo patrón ya usado en los botones de Retroceder/Avanzar de
        # Lectura, que también cambian de texto según el ajuste actual.
        if sonido_habilitado(nombre_id):
            self.btn_alternar_individual.SetLabel(f"Desactivar sonido «{nombre_legible}»")
        else:
            self.btn_alternar_individual.SetLabel(f"Activar sonido «{nombre_legible}»")

    def al_alternar_individual(self, evento):
        nombre_id = self._sonido_seleccionado()
        if nombre_id is None:
            return
        fijar_sonido_habilitado(nombre_id, not sonido_habilitado(nombre_id))
        self._actualizar_boton_alternar()

    def al_probar_sonido(self, evento):
        idx = self.combo_sonidos.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        reproducir(self._ids_sonidos[idx], forzar=True)
# ANCLAJE_FIN: PANEL_SONIDOS


# ANCLAJE_INICIO: PANEL_ASISTENTE_BIBLIOTECA
class PanelAsistenteBiblioteca(wx.Panel):
    """
    Gestión completa de las plantillas de prompt de sistema del Asistente de
    Biblioteca: crear, editar, borrar, y acceso directo a la carpeta donde
    se guardan como archivos .txt individuales
    (configuraciones/asistente_biblioteca/plantillas/). El combo del chat
    del asistente (dialogo_asistente_biblioteca.py) solo permite elegir
    entre las ya creadas aquí.
    """

    _NUEVA = "(Nueva plantilla...)"

    def __init__(self, padre):
        super().__init__(padre)
        self._plantillas = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(
            wx.StaticText(self, label="Plantillas de prompt del Asistente de Biblioteca:"),
            0, wx.LEFT | wx.TOP, 8,
        )

        sizer.Add(wx.StaticText(self, label="Plantilla:"), 0, wx.LEFT, 8)
        self.combo_plantillas = wx.ComboBox(self, style=wx.CB_READONLY)
        self.combo_plantillas.Bind(wx.EVT_COMBOBOX, self.al_seleccionar_plantilla)
        sizer.Add(self.combo_plantillas, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Nombre:"), 0, wx.LEFT, 8)
        self.txt_nombre = wx.TextCtrl(self)
        sizer.Add(self.txt_nombre, 0, wx.EXPAND | wx.ALL, 8)

        sizer.Add(wx.StaticText(self, label="Texto del prompt:"), 0, wx.LEFT, 8)
        self.txt_prompt = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.txt_prompt.SetName("Texto del prompt")
        sizer.Add(self.txt_prompt, 1, wx.EXPAND | wx.ALL, 8)

        sizer_botones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_guardar = wx.Button(self, label="Guardar plantilla")
        self.btn_guardar.Bind(wx.EVT_BUTTON, self.al_guardar)
        aplicar_icono_boton(self.btn_guardar, "guardar", "Guardar plantilla")
        self.btn_borrar = wx.Button(self, label="Borrar plantilla")
        self.btn_borrar.Bind(wx.EVT_BUTTON, self.al_borrar)
        aplicar_icono_boton(self.btn_borrar, "eliminar", "Borrar plantilla")
        self.btn_abrir_carpeta = wx.Button(self, label="Abrir carpeta de plantillas")
        self.btn_abrir_carpeta.SetHelpText(
            "Abre en el Explorador de Windows la carpeta donde se guarda cada "
            "plantilla como un archivo .txt independiente, editable desde fuera de la app."
        )
        self.btn_abrir_carpeta.Bind(wx.EVT_BUTTON, self.al_abrir_carpeta)
        aplicar_icono_boton(self.btn_abrir_carpeta, "carpeta", "Abrir carpeta de plantillas")
        for boton in (self.btn_guardar, self.btn_borrar, self.btn_abrir_carpeta):
            sizer_botones.Add(boton, 0, wx.RIGHT, 5)
        sizer.Add(sizer_botones, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.primer_control = self.combo_plantillas
        self.ultimo_control = self.btn_abrir_carpeta

        self._recargar_combo()

    def al_activar(self):
        """
        Llamado por PestanaAjustes cada vez que se entra en este nodo del
        árbol: vuelve a escanear configuraciones/asistente_biblioteca/plantillas/
        por si se añadió o borró algún archivo .txt desde fuera de la app.
        """
        self._recargar_combo()

    def _recargar_combo(self, seleccionar=None):
        self._plantillas = prompts.listar_prompts()
        nombres = [p["nombre"] for p in self._plantillas] + [self._NUEVA]
        objetivo = seleccionar or self.combo_plantillas.GetStringSelection()
        self.combo_plantillas.Set(nombres)
        if objetivo not in nombres:
            objetivo = nombres[0]
        self.combo_plantillas.SetStringSelection(objetivo)
        self._mostrar_plantilla(objetivo)

    def al_seleccionar_plantilla(self, evento):
        # No mueve el foco a "Nombre" para las plantillas ya existentes:
        # navegar con flechas por un combo de solo selección dispara este
        # mismo evento en cada elemento que se cruza, y robar el foco ahí
        # obligaría a salir con Escape para seguir recorriendo la lista.
        # "(Nueva plantilla...)" es la excepción: siempre es el último
        # elemento (no se "pasa por encima" al recorrer la lista, es donde
        # se termina), y sin mover el foco ahí el texto que se escribiera a
        # continuación no llegaba a ningún campo — se quedaba en el propio
        # combo, de solo lectura, y "Guardar plantilla" veía Nombre y Texto
        # del prompt vacíos.
        self._mostrar_plantilla(self.combo_plantillas.GetStringSelection())

    def _mostrar_plantilla(self, seleccion):
        if seleccion == self._NUEVA:
            self.txt_nombre.Clear()
            self.txt_prompt.Clear()
            self.txt_nombre.SetFocus()
            return
        plantilla = next((p for p in self._plantillas if p["nombre"] == seleccion), None)
        if plantilla:
            self.txt_nombre.SetValue(plantilla["nombre"])
            self.txt_prompt.SetValue(plantilla["texto"])

    def al_guardar(self, evento):
        nombre = self.txt_nombre.GetValue().strip()
        texto = self.txt_prompt.GetValue().strip()
        if not nombre or not texto:
            reproducir(ERROR)
            wx.MessageBox("El nombre y el texto del prompt no pueden estar vacíos.", "Error")
            return
        prompts.guardar_prompt(nombre, texto)
        reproducir(SUCCESS)
        voz.hablar(f"Plantilla «{nombre}» guardada.")
        self._recargar_combo(seleccionar=nombre)

    def al_borrar(self, evento):
        nombre = self.txt_nombre.GetValue().strip()
        if not nombre:
            return
        if wx.MessageBox(
            f"¿Borrar la plantilla «{nombre}»?", "Borrar plantilla",
            wx.YES_NO | wx.ICON_WARNING,
        ) != wx.YES:
            return
        if prompts.borrar_prompt(nombre):
            reproducir(SUCCESS)
            voz.hablar(f"Plantilla «{nombre}» borrada.")
            self._recargar_combo()
        else:
            reproducir(ERROR)
            wx.MessageBox("No se puede borrar: tiene que quedar al menos una plantilla.", "Error")

    def al_abrir_carpeta(self, evento):
        carpeta = prompts.ruta_carpeta_plantillas()
        try:
            os.makedirs(carpeta, exist_ok=True)
            reproducir(OPEN_FOLDER)
            if sys.platform == 'win32':
                os.startfile(carpeta)
        except Exception:
            logger.exception("Error al abrir la carpeta de plantillas del Asistente de Biblioteca")
            reproducir(ERROR)
            wx.MessageBox("No se pudo abrir la carpeta de plantillas.", "Error")
# ANCLAJE_FIN: PANEL_ASISTENTE_BIBLIOTECA


# ANCLAJE_INICIO: PESTANA_AJUSTES_PRINCIPAL
class PestanaAjustes(wx.Panel):
    """
    Pestaña de Ajustes — modelo híbrido V2.0.

    Árbol de categorías completamente expandido (izquierda) + Simplebook de
    habitaciones independientes (derecha).

    Navegación con teclado:
      - Flechas dentro del árbol para moverse entre categorías.
      - Tab desde el árbol salta directamente al primer control interactivo
        de la habitación activa, sin quedarse atrapado en sizers.
      - Cada habitación expone primer_control y ultimo_control para que
        ventana_principal.py cierre el ciclo de tabulación accesible.
    """

    # Índices de página en el Simplebook — deben coincidir con el orden de AddPage
    _PAG_GENERAL    = 0
    _PAG_CLAVES     = 1
    _PAG_AZURE      = 2
    _PAG_DEEPGRAM   = 3
    _PAG_POLLY      = 4
    _PAG_ELEVENLABS = 5
    _PAG_SAPI5      = 6
    _PAG_DICCIONARIO = 7
    _PAG_ATAJOS     = 8
    _PAG_SONIDOS    = 9
    _PAG_ASISTENTE  = 10

    def __init__(self, padre):
        super().__init__(padre)
        self.ruta_config = ruta_config("ajustes.json")
        self.config = self._cargar_config()
        self._bloqueo_anuncio = False  # evita re-anuncio doble al re-enfocar el árbol

        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)

        # --- Árbol de categorías ---
        self.arbol_cat = wx.TreeCtrl(
            self.splitter,
            style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE | wx.TR_HIDE_ROOT,
        )
        self.arbol_cat.SetHelpText(
            "Árbol de categorías de ajustes. Usa las flechas Arriba y Abajo para navegar "
            "entre categorías. Flecha Derecha expande una rama; Flecha Izquierda la contrae. "
            "Tab salta al primer control de la habitación seleccionada."
        )
        self._nodos = {}
        self._construir_arbol()
        self.arbol_cat.Bind(wx.EVT_TREE_SEL_CHANGING, self._al_previa_cambio_nodo)
        self.arbol_cat.Bind(wx.EVT_TREE_SEL_CHANGED, self._al_cambiar_nodo)
        self.arbol_cat.Bind(wx.EVT_KEY_DOWN, self._al_tecla_arbol)

        # --- Simplebook de habitaciones (inicialización temprana: evita punteros nulos) ---
        self.panel_derecho = wx.Simplebook(self.splitter)

        self.pag_general     = PanelGeneral(self.panel_derecho, self.config, pestana_ajustes=self)
        self.pag_claves      = PanelClaves(self.panel_derecho, self.config)
        self.pag_azure       = PanelAzure(self.panel_derecho, self.config)
        self.pag_deepgram    = PanelDeepgram(self.panel_derecho, self.config)
        self.pag_polly       = PanelPolly(self.panel_derecho, self.config)
        self.pag_elevenlabs  = PanelElevenLabs(self.panel_derecho, self.config)
        self.pag_sapi5       = PanelSapi5(self.panel_derecho, self.config)
        self.pag_diccionario = PanelDiccionario(self.panel_derecho)
        self.pag_atajos      = PanelAtajos(self.panel_derecho)
        self.pag_sonidos     = PanelSonidos(self.panel_derecho)
        self.pag_asistente   = PanelAsistenteBiblioteca(self.panel_derecho)

        self.panel_derecho.AddPage(self.pag_general,     "Configuración General")
        self.panel_derecho.AddPage(self.pag_claves,      "Credenciales y API Keys")
        self.panel_derecho.AddPage(self.pag_azure,       "Azure Neural")
        self.panel_derecho.AddPage(self.pag_deepgram,    "Deepgram Aura-2")
        self.panel_derecho.AddPage(self.pag_polly,       "Amazon Polly")
        self.panel_derecho.AddPage(self.pag_elevenlabs,  "ElevenLabs")
        self.panel_derecho.AddPage(self.pag_sapi5,       "Voces Locales SAPI5")
        self.panel_derecho.AddPage(self.pag_diccionario, "Reglas del Diccionario")
        self.panel_derecho.AddPage(self.pag_atajos,      "Atajos de Teclado")
        self.panel_derecho.AddPage(self.pag_sonidos,     "Efectos de Sonido")
        self.panel_derecho.AddPage(self.pag_asistente,   "Asistente de Biblioteca")

        self.splitter.SetMinimumPaneSize(180)
        self.splitter.SplitVertically(self.arbol_cat, self.panel_derecho, 220)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

        # Ctrl+S guarda la configuración general desde cualquier control de la pestaña
        id_guardar = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._al_guardar_global, id=id_guardar)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('S'), id_guardar),
        ]))

        # Punto de entrada para el bucle de tabulación de ventana_principal.py
        self.primer_control = self.arbol_cat

        # Seleccionar el primer nodo visible para que NVDA lo anuncie al entrar
        wx.CallAfter(self._seleccionar_nodo_inicial)

    # ANCLAJE_INICIO: GUARDAR_GLOBAL_CTRL_S
    def _al_guardar_global(self, evento=None):
        """Ctrl+S: guarda las claves de PanelGeneral y sincroniza el slider de lectura."""
        try:
            if hasattr(self, "pag_general"):
                self.pag_general.sincronizar_config()
            ruta = self.ruta_config
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception:
                datos = {}
            datos.update(self.config)
            ruta_tmp = ruta + ".tmp"
            with open(ruta_tmp, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            os.replace(ruta_tmp, ruta)
            reproducir(SUCCESS)
            # Sincronizar el slider de velocidad en la pestaña de lectura
            padre = wx.GetTopLevelParent(self)
            if hasattr(padre, "pestana_lectura"):
                wx.CallAfter(padre.pestana_lectura.cargar_config_salto)
            voz.hablar("Guardado.")
        except Exception:
            logger.exception("Error al guardar configuración global con Ctrl+S")
            reproducir(ERROR)
            voz.hablar("Error al guardar.")
    # ANCLAJE_FIN: GUARDAR_GLOBAL_CTRL_S

    # ANCLAJE_INICIO: CONSTRUIR_ARBOL_CATEGORIAS
    def _construir_arbol(self):
        raiz = self.arbol_cat.AddRoot("Ajustes")

        nodo_general = self.arbol_cat.AppendItem(raiz, "Configuración General")
        self._nodos[nodo_general] = self._PAG_GENERAL

        nodo_claves = self.arbol_cat.AppendItem(raiz, "Credenciales y API Keys")
        self._nodos[nodo_claves] = self._PAG_CLAVES

        # Rama de Catálogos de Voces con sub-nodos por proveedor
        nodo_voces = self.arbol_cat.AppendItem(raiz, "Catálogos de Voces")
        # La rama padre no tiene página propia; su selección abre Azure por defecto
        self._nodos[nodo_voces] = self._PAG_AZURE

        nodo_azure = self.arbol_cat.AppendItem(nodo_voces, "Azure Neural")
        self._nodos[nodo_azure] = self._PAG_AZURE

        nodo_deepgram = self.arbol_cat.AppendItem(nodo_voces, "Deepgram Aura-2")
        self._nodos[nodo_deepgram] = self._PAG_DEEPGRAM

        nodo_polly = self.arbol_cat.AppendItem(nodo_voces, "Amazon Polly")
        self._nodos[nodo_polly] = self._PAG_POLLY

        nodo_eleven = self.arbol_cat.AppendItem(nodo_voces, "ElevenLabs")
        self._nodos[nodo_eleven] = self._PAG_ELEVENLABS

        nodo_sapi5 = self.arbol_cat.AppendItem(nodo_voces, "Voces Locales SAPI5")
        self._nodos[nodo_sapi5] = self._PAG_SAPI5

        nodo_diccionario = self.arbol_cat.AppendItem(raiz, "Reglas del Diccionario")
        self._nodos[nodo_diccionario] = self._PAG_DICCIONARIO
        self._nodo_diccionario = nodo_diccionario

        nodo_atajos = self.arbol_cat.AppendItem(raiz, "Atajos de Teclado")
        self._nodos[nodo_atajos] = self._PAG_ATAJOS

        nodo_sonidos = self.arbol_cat.AppendItem(raiz, "Efectos de Sonido")
        self._nodos[nodo_sonidos] = self._PAG_SONIDOS

        nodo_asistente = self.arbol_cat.AppendItem(raiz, "Asistente de Biblioteca")
        self._nodos[nodo_asistente] = self._PAG_ASISTENTE

        # Expandir todas las ramas para que el usuario ciego conozca la estructura
        # completa desde el primer momento que el árbol recibe el foco.
        self.arbol_cat.ExpandAll()
    # ANCLAJE_FIN: CONSTRUIR_ARBOL_CATEGORIAS

    def _seleccionar_nodo_inicial(self):
        raiz = self.arbol_cat.GetRootItem()
        if raiz.IsOk():
            primer_hijo, _ = self.arbol_cat.GetFirstChild(raiz)
            if primer_hijo.IsOk():
                self.arbol_cat.SelectItem(primer_hijo)

    def abrir_diccionario_para_libro(self, id_libro: int):
        """
        Acceso rápido desde el menú contextual de Biblioteca: navega al
        nodo "Reglas del Diccionario" y lo deja ya en alcance "Este libro"
        con el libro indicado preseleccionado.
        """
        self.arbol_cat.SelectItem(self._nodo_diccionario)
        self.pag_diccionario.preseleccionar_libro(id_libro)
        self.pag_diccionario.txt_original.SetFocus()

    # ANCLAJE_INICIO: NAVEGACION_ARBOL_TAB
    def _al_tecla_arbol(self, evento):
        """
        Intercepta Tab para saltar al primer control interactivo de la habitación
        activa sin quedar atrapado en los sizers del Simplebook.
        Las flechas se dejan pasar (Skip) para que el TreeCtrl las procese de forma
        nativa: así NVDA anuncia cada nodo al moverse.
        """
        key = evento.GetKeyCode()
        if key == wx.WXK_TAB:
            panel = self._panel_activo()
            if panel is not None:
                primer = getattr(panel, 'primer_control', None)
                if primer is not None and primer.IsShownOnScreen():
                    primer.SetFocus()
                    return  # absorber el Tab — no hacer Skip
        elif key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            reproducir(LIST_NAV)
        evento.Skip()
    # ANCLAJE_FIN: NAVEGACION_ARBOL_TAB

    # ANCLAJE_INICIO: VETO_CAMBIO_NODO_PENDIENTE
    def _al_previa_cambio_nodo(self, evento):
        panel_actual = self.panel_derecho.GetCurrentPage()
        if (
            isinstance(panel_actual, PanelDiccionario)
            and panel_actual.tiene_cambios_pendientes()
        ):
            respuesta = wx.MessageBox(
                "Tienes cambios sin guardar en el diccionario de pronunciación.\n"
                "¿Deseas descartarlos y continuar?",
                "Cambios sin guardar",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            )
            if respuesta != wx.YES:
                evento.Veto()
                return
            panel_actual._pendiente = False
        evento.Skip()
    # ANCLAJE_FIN: VETO_CAMBIO_NODO_PENDIENTE

    def _al_cambiar_nodo(self, evento):
        nodo = evento.GetItem()
        if nodo.IsOk() and nodo in self._nodos:
            indice = self._nodos[nodo]
            self.panel_derecho.ChangeSelection(indice)
            pagina = self.panel_derecho.GetCurrentPage()
            if hasattr(pagina, 'al_activar'):
                pagina.al_activar()
            # Devolver el foco al árbol después de cambiar la página.
            # La bandera _bloqueo_anuncio evita que el re-enfoque dispare
            # un segundo anuncio de NVDA para el mismo nodo.
            # Guardia: el evento puede llegar durante el cierre de la ventana,
            # cuando el TreeCtrl ya ha sido destruido por wx.
            if not self._bloqueo_anuncio and self.arbol_cat:
                try:
                    self._bloqueo_anuncio = True
                    self.arbol_cat.SetFocus()
                    wx.CallAfter(self._desbloquear_anuncio)
                except RuntimeError:
                    self._bloqueo_anuncio = False
        evento.Skip()

    def _desbloquear_anuncio(self):
        self._bloqueo_anuncio = False

    def _panel_activo(self):
        """Devuelve el panel wx del Simplebook que está visible en este momento."""
        idx = self.panel_derecho.GetSelection()
        paneles = [
            self.pag_general, self.pag_claves,
            self.pag_azure, self.pag_deepgram, self.pag_polly,
            self.pag_elevenlabs, self.pag_sapi5,
            self.pag_diccionario, self.pag_atajos,
            self.pag_sonidos, self.pag_asistente,
        ]
        if 0 <= idx < len(paneles):
            return paneles[idx]
        return None

    def obtener_ultimo_control(self):
        """
        Devuelve el último control navegable de la habitación activa.
        ventana_principal.py lo consulta para cerrar el ciclo de tabulación accesible.
        Usa GetCurrentPage() para delegar dinámicamente sin mantener un índice paralelo.
        """
        pagina = self.panel_derecho.GetCurrentPage()
        if pagina is not None and hasattr(pagina, 'ultimo_control'):
            return pagina.ultimo_control
        return None

    def _recargar_panel_proveedor(self, id_proveedor):
        """
        Recarga el panel del proveedor indicado tras una descarga de voces.
        Se llama desde PanelClaves tras una verificación exitosa.
        """
        mapa = {
            "azure":      self.pag_azure,
            "deepgram":   self.pag_deepgram,
            "polly":      self.pag_polly,
            "elevenlabs": self.pag_elevenlabs,
        }
        panel = mapa.get(id_proveedor)
        if panel is not None:
            panel.cargar_datos()

    def _cargar_config(self):
        try:
            with open(self.ruta_config, "r", encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("Error al leer ajustes.json")
            return {}

    def guardar_config_en_archivo(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            ruta_tmp = self.ruta_config + ".tmp"
            with open(ruta_tmp, "w", encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            os.replace(ruta_tmp, self.ruta_config)
            try:
                ventana = wx.GetTopLevelParent(self)
                if hasattr(ventana, 'pestana_lectura'):
                    pl = ventana.pestana_lectura
                    pl.cargar_config_salto()
                    pl.btn_atras.SetLabel(f"Retroceder {pl.segundos_salto}s")
                    pl.btn_adelante.SetLabel(f"Avanzar {pl.segundos_salto}s")
            except Exception:
                logger.exception("Error al actualizar etiquetas de botones de salto en Lectura")
        except Exception:
            logger.exception("Error al guardar ajustes.json")
            reproducir(ERROR)
            wx.MessageBox("No se pudo guardar la configuración.")
# ANCLAJE_FIN: PESTANA_AJUSTES_PRINCIPAL
