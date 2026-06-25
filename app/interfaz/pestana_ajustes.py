import wx
import os
import json
import logging
import webbrowser
import wx.lib.mixins.listctrl as listmix

from app.config_rutas import ruta_config, CONFIG_DIR, cargar_claves, guardar_claves
from app.motor.reproductor_sonidos import reproducir, LIST_NAV, SUCCESS, ERROR

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
    def __init__(self, padre, config):
        super().__init__(padre, style=wx.VSCROLL)
        self.SetScrollRate(0, 20)
        self.config = config
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
        sizer_updates.Add(self.btn_buscar_updates, 0, wx.ALL, 5)

        self.lbl_progreso = wx.StaticText(self, label="")
        self.lbl_progreso.SetHelpText(
            "Estado del proceso de actualización. NVDA lo leerá automáticamente al cambiar."
        )
        sizer_updates.Add(self.lbl_progreso, 0, wx.ALL, 5)

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
            choices=["Porcentaje (0 – 100)", "Multiplicador por puntos (0.5× – 3.0×)"],
            style=wx.CB_READONLY,
        )
        self.combo_escala_vel.SetHelpText(
            "Elige cómo se muestra la velocidad en el deslizador de la pestaña Lectura. "
            "Porcentaje: valores del 0 al 100. "
            "Multiplicador: etiquetas tipo 1.0× (Normal), 1.5× (Rápida), 2.0× (Muy rápida). "
            "El motor de audio recibe siempre un valor normalizado 0-100."
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
        sizer.Add(self.btn_guardar, 0, wx.ALL, 10)

        self.btn_limpiar = wx.Button(self, label="Limpiar caché")
        self.btn_limpiar.SetHelpText(
            "Elimina carpetas __pycache__, archivos .tmp y audio temporal."
        )
        self.btn_limpiar.Bind(wx.EVT_BUTTON, self._limpiar_cache)
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
        padre = wx.GetTopLevelParent(self)
        if hasattr(padre, "guardar_config_en_archivo"):
            padre.guardar_config_en_archivo()

    def guardar_todo(self):
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
        padre = wx.GetTopLevelParent(self)
        if hasattr(padre, "guardar_config_en_archivo"):
            padre.guardar_config_en_archivo()
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
        btn_az_del = wx.Button(self, label="Borrar clave Azure")
        btn_az_del.SetHelpText("Borra los datos de acceso de Azure guardados en la aplicación.")
        btn_az_del.Bind(wx.EVT_BUTTON, self.al_borrar_azure)
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
        btn_po_del = wx.Button(self, label="Borrar clave Polly")
        btn_po_del.SetHelpText("Borra los datos de acceso de Amazon Polly guardados en la aplicación.")
        btn_po_del.Bind(wx.EVT_BUTTON, self.al_borrar_polly)
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
        btn_el_del = wx.Button(self, label="Borrar clave ElevenLabs")
        btn_el_del.SetHelpText("Borra la API Key de ElevenLabs guardada en la aplicación.")
        btn_el_del.Bind(wx.EVT_BUTTON, self.al_borrar_elevenlabs)
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
        btn_dg_del = wx.Button(self, label="Borrar clave Deepgram")
        btn_dg_del.SetHelpText("Borra la API Key de Deepgram guardada en la aplicación.")
        btn_dg_del.Bind(wx.EVT_BUTTON, self.al_borrar_deepgram)
        hb_dg.Add(btn_dg_web, 0, wx.RIGHT, 5)
        hb_dg.Add(btn_dg_check, 0, wx.RIGHT, 5)
        hb_dg.Add(btn_dg_del, 0)
        sz_dg.Add(hb_dg, 0, wx.ALL, 5)
        sizer.Add(sz_dg, 0, wx.EXPAND | wx.ALL, 10)

        self.btn_save = wx.Button(self, label="Guardar Todas las Claves")
        self.btn_save.Bind(wx.EVT_BUTTON, self.al_guardar)
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

    def al_guardar(self, evento):
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
        }
        guardar_claves(claves)
        if evento:
            reproducir(SUCCESS)
            wx.MessageBox("Claves guardadas en claves_api.json.", "Éxito")

    def al_borrar_azure(self, evento):
        self.txt_az_key.Clear()
        self.txt_az_region.Clear()
        self.al_guardar(None)

    def al_borrar_polly(self, evento):
        self.txt_po_key.Clear()
        self.txt_po_secret.Clear()
        self.txt_po_region.Clear()
        self.al_guardar(None)

    def al_borrar_elevenlabs(self, evento):
        self.txt_el_key.Clear()
        self.al_guardar(None)

    def al_borrar_deepgram(self, evento):
        self.txt_dg_key.Clear()
        self.al_guardar(None)

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
        self._construir_ui()
        wx.CallAfter(self.cargar_datos)

    def _construir_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 1. Idioma
        hbox_idioma = wx.BoxSizer(wx.HORIZONTAL)
        hbox_idioma.Add(
            wx.StaticText(self, label="Idioma:"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self.combo_idioma = wx.ComboBox(self, style=wx.CB_READONLY, choices=["Todos"])
        self.combo_idioma.SetSelection(0)
        self.combo_idioma.SetHelpText(
            f"Filtra las voces de {self.nombre_proveedor} por idioma. "
            "Elige Todos para ver el catálogo completo del proveedor."
        )
        self.combo_idioma.Bind(wx.EVT_COMBOBOX, self._al_filtrar)
        hbox_idioma.Add(self.combo_idioma, 1)
        sizer.Add(hbox_idioma, 0, wx.EXPAND | wx.ALL, 8)

        # 1b. Controles extra del proveedor (gancho: subclases añaden aquí)
        self._construir_controles_extra(sizer)

        # 2. Casillas de filtro local (independientes por panel)
        hbox_filtros = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_solo_favs = wx.CheckBox(self, label="Solo favoritas")
        self.chk_solo_favs.SetHelpText(
            "Marcada: muestra solo las voces de este proveedor que ya tienes marcadas como favoritas."
        )
        self.chk_solo_favs.Bind(wx.EVT_CHECKBOX, self._al_filtrar)
        hbox_filtros.Add(self.chk_solo_favs, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 20)

        self.chk_solo_nuevas = wx.CheckBox(self, label="Solo nuevas voces")
        self.chk_solo_nuevas.SetHelpText(
            "Marcada: muestra solo las voces de este proveedor añadidas desde la última actualización."
        )
        self.chk_solo_nuevas.Bind(wx.EVT_CHECKBOX, self._al_filtrar)
        hbox_filtros.Add(self.chk_solo_nuevas, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(hbox_filtros, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # 3. Búsqueda de texto con debounce (300 ms)
        hbox_busqueda = wx.BoxSizer(wx.HORIZONTAL)
        hbox_busqueda.Add(
            wx.StaticText(self, label="Buscar nombre de voz:"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self.txt_buscar = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt_buscar.SetHelpText(
            "Escribe parte del nombre de una voz para filtrar la lista en tiempo real. "
            "Borra el campo para ver todas las voces del filtro activo."
        )
        self.txt_buscar.Bind(wx.EVT_TEXT, self._al_filtrar_texto)
        hbox_busqueda.Add(self.txt_buscar, 1, wx.EXPAND)
        sizer.Add(hbox_busqueda, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # 4. ListCtrl de voces con casillas nativas
        self.lista_voces = ListaVocesCheck(self)
        self.lista_voces.InsertColumn(0, "Nombre", width=280)
        self.lista_voces.InsertColumn(1, "Género", width=80)
        self.lista_voces.InsertColumn(2, "Idioma", width=200)
        self.lista_voces.SetHelpText(
            f"Lista de voces de {self.nombre_proveedor}. Usa las flechas para navegar. "
            "Pulsa Intro para marcar o desmarcar una voz como favorita. "
            "Las voces marcadas aparecerán en Grabación para asignarlas a personajes."
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
        self.btn_escuchar = wx.Button(self, label="Escuchar muestra (Alt+P)")
        self.btn_escuchar.SetHelpText(
            "Reproduce una muestra de texto con la voz seleccionada. "
            "Púlsalo de nuevo para detener la reproducción."
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
        except Exception:
            logger.exception("Error al notificar cambio de favoritos a otras pestañas")

    # --- Preescucha ---

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
                "El sol salía lentamente sobre las colinas cuando la ciudad comenzó a despertar."
            )
            self.btn_escuchar.SetLabel("Detener preescucha (Alt+P)")
            self._reproductor.cargar_texto(texto, callback_completado=self._al_terminar_escucha)
        except Exception as e:
            self.btn_escuchar.SetLabel("Escuchar muestra (Alt+P)")
            reproducir(ERROR)
            wx.MessageBox(f"Error: {e}", "Error")

    def _al_terminar_escucha(self):
        wx.CallAfter(self.btn_escuchar.SetLabel, "Escuchar muestra (Alt+P)")
# ANCLAJE_FIN: BASE_PANEL_PROVEEDOR_IA


# ANCLAJE_INICIO: PANEL_AZURE
class PanelAzure(PanelProveedorIA):
    def __init__(self, padre, config):
        super().__init__(padre, config, "azure", "Azure Neural")
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
        self._construir_ui()
        wx.CallAfter(self._rellenar_lista)

    def _construir_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

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
        self.btn_eliminar = wx.Button(self, label="Eliminar seleccionada")
        self.btn_eliminar.SetHelpText("Elimina la entrada seleccionada en la lista.")
        self.btn_eliminar.Bind(wx.EVT_BUTTON, self._al_eliminar)
        self.btn_guardar = wx.Button(self, label="Guardar cambios\tAlt+G")
        self.btn_guardar.SetHelpText(
            "Guarda todos los cambios del diccionario en disco y recarga la pronunciación activa."
        )
        self.btn_guardar.Bind(wx.EVT_BUTTON, self._al_guardar_cambios)
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

    def _rellenar_lista(self):
        self.lista.Freeze()
        self.lista.DeleteAllItems()
        for i, (original, pronunciacion) in enumerate(sorted(self._dic.obtener_tabla().items())):
            self.lista.InsertItem(i, original)
            self.lista.SetItem(i, 1, pronunciacion)
        self.lista.Thaw()

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
        self._dic.anadir_entrada(original, pronunciacion)
        self._pendiente = True
        self.txt_original.Clear()
        self.txt_pronunciacion.Clear()
        self._rellenar_lista()

    def _al_eliminar(self, evento):
        idx = self.lista.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Selecciona una entrada de la lista.", "Aviso")
            return
        original = self.lista.GetItemText(idx, 0)
        self._dic.eliminar_entrada(original)
        self._pendiente = True
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
        hbox.Add(self.btn_asignar, 0, wx.RIGHT, 10)
        hbox.Add(self.btn_eliminar, 0, wx.RIGHT, 10)
        hbox.Add(self.btn_restablecer, 0)
        sizer.Add(hbox, 0, wx.ALL, 10)

        sb_fijos = wx.StaticBox(self, label="Atajos fijos del menú (no configurables)")
        sz_fijos = wx.StaticBoxSizer(sb_fijos, wx.VERTICAL)
        _FIJOS = [
            ("Ctrl+A",       "Abrir libro EPUB (menú Archivo)"),
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

        self.pag_general     = PanelGeneral(self.panel_derecho, self.config)
        self.pag_claves      = PanelClaves(self.panel_derecho, self.config)
        self.pag_azure       = PanelAzure(self.panel_derecho, self.config)
        self.pag_deepgram    = PanelDeepgram(self.panel_derecho, self.config)
        self.pag_polly       = PanelPolly(self.panel_derecho, self.config)
        self.pag_elevenlabs  = PanelElevenLabs(self.panel_derecho, self.config)
        self.pag_sapi5       = PanelSapi5(self.panel_derecho, self.config)
        self.pag_diccionario = PanelDiccionario(self.panel_derecho)
        self.pag_atajos      = PanelAtajos(self.panel_derecho)

        self.panel_derecho.AddPage(self.pag_general,     "Configuración General")
        self.panel_derecho.AddPage(self.pag_claves,      "Credenciales y API Keys")
        self.panel_derecho.AddPage(self.pag_azure,       "Azure Neural")
        self.panel_derecho.AddPage(self.pag_deepgram,    "Deepgram Aura-2")
        self.panel_derecho.AddPage(self.pag_polly,       "Amazon Polly")
        self.panel_derecho.AddPage(self.pag_elevenlabs,  "ElevenLabs")
        self.panel_derecho.AddPage(self.pag_sapi5,       "Voces Locales SAPI5")
        self.panel_derecho.AddPage(self.pag_diccionario, "Reglas del Diccionario")
        self.panel_derecho.AddPage(self.pag_atajos,      "Atajos de Teclado")

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

        # Anunciador oculto: recibe el foco un instante para que NVDA verbalice el texto
        self._anunciador = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1)
        )
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())
        sizer.Add(self._anunciador, 0, wx.LEFT, 0)

        # Punto de entrada para el bucle de tabulación de ventana_principal.py
        self.primer_control = self.arbol_cat

        # Seleccionar el primer nodo visible para que NVDA lo anuncie al entrar
        wx.CallAfter(self._seleccionar_nodo_inicial)

    # ANCLAJE_INICIO: GUARDAR_GLOBAL_CTRL_S
    def _al_guardar_global(self, evento=None):
        """Ctrl+S: guarda las claves de PanelGeneral y sincroniza el slider de lectura."""
        try:
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
            # NVDA verbaliza "Guardado" mediante el anunciador oculto
            def _anunciar():
                foco_anterior = wx.Window.FindFocus()
                self._anunciador.SetValue("Guardado.")
                self._anunciador.SetFocus()
                if foco_anterior:
                    wx.CallLater(300, lambda: foco_anterior.SetFocus()
                                 if foco_anterior.IsShownOnScreen() else None)
            wx.CallAfter(_anunciar)
        except Exception:
            logger.exception("Error al guardar configuración global con Ctrl+S")
            reproducir(ERROR)
            def _anunciar_error():
                foco_anterior = wx.Window.FindFocus()
                self._anunciador.SetValue("Error al guardar.")
                self._anunciador.SetFocus()
                if foco_anterior:
                    wx.CallLater(300, lambda: foco_anterior.SetFocus()
                                 if foco_anterior.IsShownOnScreen() else None)
            wx.CallAfter(_anunciar_error)
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

        nodo_atajos = self.arbol_cat.AppendItem(raiz, "Atajos de Teclado")
        self._nodos[nodo_atajos] = self._PAG_ATAJOS

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
