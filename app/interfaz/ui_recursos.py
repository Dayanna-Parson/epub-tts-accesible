# ANCLAJE_INICIO: UI_RECURSOS
"""
ui_recursos.py
───────────────
Helpers para aplicar iconos a botones wx de forma segura.

Fuentes de icono (por orden de prioridad):
  1. PNG propio en /recursos/iconos/<nombre>.png
  2. wx.ArtProvider (iconos del sistema operativo)
  El AccessibleName (SetName) se asigna siempre para que NVDA
  anuncie la función del botón independientemente del icono.

Iconos PNG esperados (opcionales):
  examinar.png       buscar / abrir archivo
  trocear.png        dividir / cortar EPUB
  carpeta.png        abrir carpeta en el explorador
  seleccionar.png    seleccionar todo
  deseleccionar.png  deseleccionar todo
  eliminar.png       eliminar proyecto
  cerrar.png         cerrar ventana
  buscar.png         buscar actualizaciones
  proyectos.png      gestión de proyectos

Uso:
    from app.interfaz.ui_recursos import aplicar_icono_boton
    aplicar_icono_boton(self.btn_abrir, "carpeta", "Abrir carpeta de destino")
"""

import os
import wx

from app.config_rutas import RAIZ

_RUTA_ICONOS = os.path.join(RAIZ, "recursos", "iconos")

# ── Mapa de nombre interno → wx.ArtProvider ID  ──────────────────────────────
# Usado como fallback cuando no existe el PNG propio.
_ART_FALLBACK = {
    "examinar":      wx.ART_FILE_OPEN,
    "carpeta":       wx.ART_FOLDER_OPEN,
    "trocear":       wx.ART_CUT,
    "seleccionar":   wx.ART_TICK_MARK,
    "deseleccionar": wx.ART_CROSS_MARK,
    "eliminar":      wx.ART_DELETE,
    "cerrar":        wx.ART_QUIT,
    "limpiar":       wx.ART_DELETE,
    "buscar":        wx.ART_FIND,
    "proyectos":     wx.ART_LIST_VIEW,
    "grabar":        getattr(wx, "ART_RECORD", wx.ART_EXECUTABLE_FILE),  # ART_RECORD no existe en wxPython < 4.2
    "detener":       getattr(wx, "ART_STOP", wx.ART_DELETE),
    "añadir":        getattr(wx, "ART_PLUS", wx.ART_NEW),
    "nuevo":         wx.ART_NEW,
    "guardar":       wx.ART_FILE_SAVE,
    "informacion":   wx.ART_INFORMATION,
    "advertencia":   wx.ART_WARNING,
    "error":         wx.ART_ERROR,
}


def aplicar_icono_boton(
    btn: wx.Button,
    nombre_icono: str,
    accessible_name: str = "",
    size: tuple = (16, 16),
):
    """
    Aplica un icono al botón manteniendo el texto label intacto.

    Prioridad:
      1. PNG propio en /recursos/iconos/<nombre_icono>.png
      2. wx.ArtProvider (icono del sistema, si hay mapeo)

    Siempre asigna accessible_name (btn.SetName) para NVDA.
    No lanza excepciones si el archivo no existe.

    Parámetros
    ----------
    btn             : wx.Button
    nombre_icono    : str    nombre sin extensión, ej. "carpeta", "trocear"
    accessible_name : str    texto que NVDA leerá; si vacío, usa el label del botón
    size            : tuple  tamaño del icono en píxeles (ancho, alto)
    """
    # AccessibleName siempre, aunque no haya icono
    nombre = accessible_name or btn.GetLabel()
    if nombre:
        btn.SetName(nombre)

    bmp = _cargar_bmp_png(nombre_icono, size) or _cargar_bmp_art(nombre_icono, size)
    if bmp and bmp.IsOk():
        btn.SetBitmap(bmp)
        btn.SetBitmapMargins(4, 2)


# ── Helpers privados ──────────────────────────────────────────────────────────

def _cargar_bmp_png(nombre: str, size: tuple):
    """Intenta cargar un PNG propio; devuelve Bitmap o None."""
    ruta = os.path.join(_RUTA_ICONOS, f"{nombre}.png")
    if not os.path.isfile(ruta):
        return None
    try:
        img = wx.Image(ruta, wx.BITMAP_TYPE_PNG)
        if img.IsOk():
            img = img.Scale(*size, wx.IMAGE_QUALITY_HIGH)
            return wx.Bitmap(img)
    except Exception:
        pass
    return None


def _cargar_bmp_art(nombre: str, size: tuple):
    """Intenta obtener un icono del wx.ArtProvider; devuelve Bitmap o None."""
    art_id = _ART_FALLBACK.get(nombre)
    if art_id is None:
        return None
    try:
        bmp = wx.ArtProvider.GetBitmap(art_id, wx.ART_BUTTON, size)
        return bmp if bmp.IsOk() else None
    except Exception:
        return None
# ANCLAJE_FIN: UI_RECURSOS
