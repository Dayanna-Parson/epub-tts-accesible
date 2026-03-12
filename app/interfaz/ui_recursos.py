# ANCLAJE_INICIO: UI_RECURSOS
"""
ui_recursos.py
───────────────
Helper para aplicar iconos PNG a botones wx de forma segura.

Características:
  · No lanza excepciones si el archivo .png no existe.
  · Siempre asigna el accessible_name (SetName) para que NVDA lo anuncie,
    independientemente de si se encontró el icono.
  · Los iconos se buscan en /recursos/iconos/<nombre>.png.

Iconos esperados (preparados para cuando existan los archivos):
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


def aplicar_icono_boton(
    btn: wx.Button,
    nombre_icono: str,
    accessible_name: str = "",
    size: tuple = (16, 16),
):
    """
    Aplica un icono PNG al botón si el archivo existe en /recursos/iconos/.
    Siempre asigna accessible_name (btn.SetName) para NVDA, con o sin icono.

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

    ruta = os.path.join(_RUTA_ICONOS, f"{nombre_icono}.png")
    if not os.path.exists(ruta):
        return

    try:
        img = wx.Image(ruta, wx.BITMAP_TYPE_PNG)
        if img.IsOk():
            img = img.Scale(*size, wx.IMAGE_QUALITY_HIGH)
            btn.SetBitmap(wx.Bitmap(img))
            btn.SetBitmapMargins(4, 2)
    except Exception:
        pass
# ANCLAJE_FIN: UI_RECURSOS
