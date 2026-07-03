# ANCLAJE_INICIO: DEPENDENCIAS_BIBLIOTECA
import wx
import os
import logging

from app.motor.gestor_biblioteca import GestorBiblioteca
from app.motor.escaner_biblioteca import EscanerBiblioteca, confirmar_agrupamiento_por_carpeta
from app.motor.renombrador_biblioteca import (
    renombrar_libro_segun_metadatos,
    renombrar_pendientes_por_lote,
)
from app.motor.reproductor_sonidos import reproducir, SUCCESS, ERROR, LIST_NAV
# ANCLAJE_FIN: DEPENDENCIAS_BIBLIOTECA


# ANCLAJE_INICIO: DEFINICION_PESTANA_BIBLIOTECA
class PestanaBiblioteca(wx.Panel):
    """
    Pestaña de la Biblioteca: importación, filtrado y gestión de la
    colección de EPUB y PDF indexada en biblioteca.db.

    Esqueleto inicial: filtro de texto, casillas de estado y lista de
    libros. La organización por categorías/etiquetas y la apertura
    directa en Lectura/Creador de Audiolibros se conectan en pasos
    posteriores del desarrollo.
    """

    def __init__(self, padre):
        super().__init__(padre)
        self.padre_notebook = padre

        self.gestor = GestorBiblioteca()
        self.escaner = None
        self._libros_actuales = []

        self._configurar_interfaz()
        self._configurar_atajos()

        wx.CallAfter(self._cargar_libros)

    # ── Construcción de la interfaz ─────────────────────────────────────────

    def _configurar_interfaz(self):
        sizer_principal = wx.BoxSizer(wx.VERTICAL)

        # Filtro de texto
        sizer_filtro = wx.BoxSizer(wx.HORIZONTAL)
        sizer_filtro.Add(
            wx.StaticText(self, label="Buscar por título o autor (Ctrl+F):"),
            0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5,
        )
        self.txt_filtro = wx.TextCtrl(self)
        self.txt_filtro.Bind(wx.EVT_TEXT, self.al_cambiar_filtro)
        sizer_filtro.Add(self.txt_filtro, 1, wx.ALL | wx.EXPAND, 5)
        sizer_principal.Add(sizer_filtro, 0, wx.EXPAND)

        # Filtro de estado: en_pendientes/leyendo_ahora/leido son etapas
        # mutuamente excluyentes de un mismo libro (nunca coinciden a la
        # vez), así que un combo de una sola selección es más claro que
        # varias casillas independientes. Favorito sí es ortogonal al
        # estado (un libro puede ser favorito en cualquier etapa), por
        # eso se mantiene como casilla aparte, combinable con el combo.
        sizer_filtro_estado = wx.BoxSizer(wx.HORIZONTAL)
        sizer_filtro_estado.Add(
            wx.StaticText(self, label="Estado:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5
        )
        self._ESTADOS_FILTRO = ["Todos", "Pendientes", "Leyendo ahora", "Leídos"]
        self.combo_estado = wx.Choice(self, choices=self._ESTADOS_FILTRO)
        self.combo_estado.SetSelection(0)
        self.combo_estado.Bind(wx.EVT_CHOICE, self.al_cambiar_filtro)
        sizer_filtro_estado.Add(self.combo_estado, 0, wx.ALL, 5)

        self.chk_favoritos = wx.CheckBox(self, label="Solo favoritos")
        self.chk_favoritos.Bind(wx.EVT_CHECKBOX, self.al_cambiar_filtro)
        sizer_filtro_estado.Add(self.chk_favoritos, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        sizer_principal.Add(sizer_filtro_estado, 0)

        # Botón de importación (visible además del atajo Ctrl+O)
        self.btn_importar = wx.Button(self, label="Importar carpeta... (Ctrl+O)")
        self.btn_importar.Bind(wx.EVT_BUTTON, self.al_importar_carpeta)
        sizer_principal.Add(self.btn_importar, 0, wx.ALL, 5)

        # Lista principal de libros
        self.lista_libros = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self.lista_libros.InsertColumn(0, "Título", width=320)
        self.lista_libros.InsertColumn(1, "Autor", width=200)
        self.lista_libros.InsertColumn(2, "Formato", width=80)
        self.lista_libros.InsertColumn(3, "Estado", width=160)
        self.lista_libros.Bind(wx.EVT_CONTEXT_MENU, self.al_menu_contextual)
        self.lista_libros.Bind(wx.EVT_KEY_DOWN, self.al_tecla_lista)
        sizer_principal.Add(self.lista_libros, 1, wx.EXPAND | wx.ALL, 5)

        self.lbl_estado = wx.StaticText(self, label="")
        sizer_principal.Add(self.lbl_estado, 0, wx.ALL, 5)

        self.SetSizer(sizer_principal)

        # Control oculto para anuncios inmediatos de NVDA (patrón _anunciador).
        self._anunciador = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1)
        )
        self._anunciador.SetBackgroundColour(self.GetBackgroundColour())

    def _configurar_atajos(self):
        # Ctrl+O (apertura universal, contextual por pestaña) se gestiona a
        # nivel de VentanaPrincipal y llama a al_importar_carpeta() desde
        # allí — no se duplica aquí para no pisar el atajo global.
        id_buscar = wx.NewIdRef()
        id_info = wx.NewIdRef()
        id_favorito = wx.NewIdRef()

        self.Bind(wx.EVT_MENU, lambda e: self.txt_filtro.SetFocus(), id=id_buscar)
        self.Bind(wx.EVT_MENU, self.al_anunciar_info_libro, id=id_info)
        self.Bind(wx.EVT_MENU, self.al_alternar_favorito, id=id_favorito)

        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('F'), id_buscar),
            (wx.ACCEL_CTRL, ord('I'), id_info),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('F'), id_favorito),
        ]))

    # ── Propiedades para Tab cíclico (usadas por ventana_principal.py) ──────

    @property
    def primer_control(self):
        return self.txt_filtro

    @property
    def ultimo_control(self):
        return self.lista_libros

    # ── Anuncios de accesibilidad ────────────────────────────────────────────

    def _anunciar(self, texto):
        control_previo = wx.Window.FindFocus()
        self._anunciador.SetValue(texto)
        self._anunciador.SetFocus()
        wx.CallLater(300, lambda: control_previo.SetFocus() if control_previo else None)

    # ── Carga y filtrado de la lista ─────────────────────────────────────────

    def _cargar_libros(self):
        estado = self._ESTADOS_FILTRO[self.combo_estado.GetSelection()]
        libros = self.gestor.buscar_libros(
            texto=self.txt_filtro.GetValue().strip(),
            solo_favoritos=self.chk_favoritos.GetValue(),
            solo_pendientes=(estado == "Pendientes"),
            solo_leyendo=(estado == "Leyendo ahora"),
            solo_leidos=(estado == "Leídos"),
        )
        self._libros_actuales = libros

        self.lista_libros.Freeze()
        self.lista_libros.DeleteAllItems()
        for indice, libro in enumerate(libros):
            autores = self.gestor.obtener_autores_de_libro(libro["id"])
            nombres_autores = ", ".join(a["nombre"] for a in autores) or "—"
            estado = self._describir_estado(libro)

            self.lista_libros.InsertItem(indice, libro["titulo"])
            self.lista_libros.SetItem(indice, 1, nombres_autores)
            self.lista_libros.SetItem(indice, 2, libro["formato"].upper())
            self.lista_libros.SetItem(indice, 3, estado)
        self.lista_libros.Thaw()

        self.lbl_estado.SetLabel(f"{len(libros)} libro(s) en la biblioteca.")

    @staticmethod
    def _describir_estado(libro) -> str:
        partes = []
        if libro["favorito"]:
            partes.append("Favorito")
        if libro["leyendo_ahora"]:
            partes.append("Leyendo")
        elif libro["en_pendientes"]:
            partes.append("Pendiente")
        elif libro["leido"]:
            partes.append("Leído")
        if not libro["titulo_revisado"]:
            partes.append("Título sin revisar")
        return ", ".join(partes) if partes else "Sin marcar"

    def al_cambiar_filtro(self, evento):
        self._cargar_libros()
        evento.Skip()

    def _libro_seleccionado(self):
        indice = self.lista_libros.GetFirstSelected()
        if indice == -1 or indice >= len(self._libros_actuales):
            return None
        return self._libros_actuales[indice]

    # ── Importación de carpetas ──────────────────────────────────────────────

    def al_importar_carpeta(self, evento):
        with wx.DirDialog(self, "Seleccionar carpeta con libros para importar") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            carpeta = dlg.GetPath()

        self._anunciar("Escaneando carpeta...")
        self.escaner = EscanerBiblioteca(
            self.gestor,
            al_progresar=lambda n: wx.CallAfter(self._al_progresar_escaneo, n),
            al_detectar_carpetas=lambda carpetas: wx.CallAfter(
                self._al_detectar_carpetas_agrupables, carpetas
            ),
            al_terminar=lambda total: wx.CallAfter(self._al_terminar_escaneo, total),
            al_fallar=lambda error: wx.CallAfter(self._al_fallar_escaneo, error),
        )
        self.escaner.iniciar(carpeta)

    def _al_progresar_escaneo(self, total_insertados):
        self.lbl_estado.SetLabel(f"Escaneando... {total_insertados} libro(s) indexados.")

    def _al_detectar_carpetas_agrupables(self, carpetas_candidatas: dict):
        nombres_sugeridos = {
            carpeta: os.path.basename(os.path.normpath(carpeta))
            for carpeta in carpetas_candidatas
        }
        mensaje = "Se detectaron carpetas con varios libros. ¿Agrupar cada una con una etiqueta?\n\n"
        mensaje += "\n".join(
            f"· {nombres_sugeridos[carpeta]} ({len(titulos)} libros)"
            for carpeta, titulos in carpetas_candidatas.items()
        )
        if wx.MessageBox(mensaje, "Agrupar por carpeta", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            for carpeta in carpetas_candidatas:
                confirmar_agrupamiento_por_carpeta(self.gestor, carpeta, nombres_sugeridos[carpeta])

    def _al_terminar_escaneo(self, total_insertados):
        reproducir(SUCCESS)
        self._anunciar(f"Escaneo completado. {total_insertados} libro(s) añadidos.")
        self._cargar_libros()
        self.lista_libros.SetFocus()

    def _al_fallar_escaneo(self, error):
        reproducir(ERROR)
        wx.MessageBox(f"No se pudo completar el escaneo:\n{error}", "Error", wx.OK | wx.ICON_ERROR)

    # ── Acciones sobre el libro seleccionado ─────────────────────────────────

    def al_anunciar_info_libro(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            self._anunciar("No hay ningún libro seleccionado.")
            return
        autores = self.gestor.obtener_autores_de_libro(libro["id"])
        nombres_autores = ", ".join(a["nombre"] for a in autores) or "autor desconocido"
        estado = self._describir_estado(libro)
        self._anunciar(
            f"{libro['titulo']}, {nombres_autores}, {libro['formato'].upper()}, {estado}."
        )

    def al_alternar_favorito(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        nuevo_valor = not bool(libro["favorito"])
        self.gestor.establecer_bandera(libro["id"], "favorito", nuevo_valor)
        self._anunciar("Marcado como favorito." if nuevo_valor else "Quitado de favoritos.")
        self._cargar_libros()

    def al_tecla_lista(self, evento):
        codigo = evento.GetKeyCode()
        if codigo == wx.WXK_DELETE:
            self._quitar_libro_seleccionado()
            return
        if codigo == wx.WXK_F5:
            self.al_importar_carpeta(evento)
            return
        if codigo == wx.WXK_F2:
            self.al_renombrar_segun_metadatos(evento)
            return
        evento.Skip()

    def _quitar_libro_seleccionado(self):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        if wx.MessageBox(
            f"¿Quitar «{libro['titulo']}» de la biblioteca?\n\n"
            "El archivo no se borrará del disco, solo su registro aquí.",
            "Quitar de la biblioteca", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self.gestor.quitar_libro(libro["id"])
        self._anunciar("Libro quitado de la biblioteca.")
        self._cargar_libros()

    def al_renombrar_segun_metadatos(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return
        dlg = wx.TextEntryDialog(
            self,
            "Nombre de archivo propuesto (editable):",
            "Renombrar archivo (F2)",
            value=libro["titulo"],
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        titulo_confirmado = dlg.GetValue().strip()
        dlg.Destroy()
        if not titulo_confirmado:
            return

        resultado = renombrar_libro_segun_metadatos(self.gestor, libro["id"], titulo_confirmado)
        if resultado.exito:
            reproducir(SUCCESS)
            self._anunciar("Archivo renombrado correctamente.")
        else:
            reproducir(ERROR)
            wx.MessageBox(
                f"No se pudo renombrar el archivo:\n{resultado.motivo_fallo}",
                "Error al renombrar", wx.OK | wx.ICON_ERROR,
            )
        self._cargar_libros()

    def al_renombrar_todos_pendientes(self, evento):
        pendientes = self.gestor.obtener_pendientes_de_revision()
        if not pendientes:
            self._anunciar("No hay libros pendientes de revisión.")
            return

        cambios = [{"id_libro": p["id"], "titulo_nuevo": p["titulo"]} for p in pendientes]
        exitosos, fallidos = renombrar_pendientes_por_lote(self.gestor, cambios)

        mensaje = f"{len(exitosos)} de {len(cambios)} archivos renombrados correctamente."
        if fallidos:
            detalle = "\n".join(f"· {f.titulo_anterior}: {f.motivo_fallo}" for f in fallidos)
            mensaje += f"\n\nNo se pudieron renombrar:\n{detalle}"
        wx.MessageBox(mensaje, "Renombrado por lotes", wx.OK | wx.ICON_INFORMATION)
        self._cargar_libros()

    # ── Menú contextual ──────────────────────────────────────────────────────

    def al_menu_contextual(self, evento):
        libro = self._libro_seleccionado()
        if libro is None:
            return

        menu = wx.Menu()

        item_favorito = menu.Append(
            wx.ID_ANY, "Quitar de favoritos" if libro["favorito"] else "Marcar como favorito"
        )
        self.Bind(wx.EVT_MENU, self.al_alternar_favorito, item_favorito)

        menu.AppendSeparator()

        item_renombrar = menu.Append(wx.ID_ANY, "Renombrar archivo...\tF2")
        self.Bind(wx.EVT_MENU, self.al_renombrar_segun_metadatos, item_renombrar)

        item_quitar = menu.Append(wx.ID_ANY, "Quitar de la biblioteca")
        self.Bind(wx.EVT_MENU, lambda e: self._quitar_libro_seleccionado(), item_quitar)

        self.PopupMenu(menu)
        menu.Destroy()
# ANCLAJE_FIN: DEFINICION_PESTANA_BIBLIOTECA
