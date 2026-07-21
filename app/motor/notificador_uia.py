# ANCLAJE_INICIO: NOTIFICADOR_LIVE_REGION_UIA
"""
Notificación "en vivo" de accesibilidad (UI Automation de Windows) para
anunciar texto con NVDA sin mover el foco de ningún control.

Usa UiaRaiseNotificationEvent (uiautomationcore.dll, disponible desde
Windows 10 versión 1709/RS3), la misma API que usan las apps modernas de
Windows para notificaciones tipo "toast" accesibles. No hace falta
implementar un proveedor de automatización propio: UiaHostProviderFromHwnd
da un proveedor genérico válido para el HWND de cualquier control ya
existente, sin tocar su vtable COM directamente — solo se llaman
funciones planas exportadas por las DLL de sistema.

Si algo falla (versión de Windows antigua, DLL no disponible, plataforma
no Windows...) se devuelve False sin lanzar excepción, para que quien
llame pueda recurrir a un anuncio alternativo (patrón _anunciador con
toque de foco).
"""
import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

_DISPONIBLE = sys.platform == "win32"

# Constantes del enum UIAutomationClient (NotificationKind / NotificationProcessing).
_NOTIFICATION_KIND_OTHER = 3
_NOTIFICATION_PROCESSING_ALL = 2

_uia = None
_oleaut32 = None


def _preparar_firmas():
    global _uia, _oleaut32
    if _uia is not None:
        return
    _uia = ctypes.windll.uiautomationcore
    _oleaut32 = ctypes.windll.oleaut32

    _oleaut32.SysAllocString.restype = ctypes.c_void_p
    _oleaut32.SysAllocString.argtypes = [ctypes.c_wchar_p]
    _oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]

    _uia.UiaHostProviderFromHwnd.restype = ctypes.c_long
    _uia.UiaHostProviderFromHwnd.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

    _uia.UiaRaiseNotificationEvent.restype = ctypes.c_long
    _uia.UiaRaiseNotificationEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
    ]


def anunciar_en_vivo(hwnd, texto: str) -> bool:
    """
    Anuncia `texto` con el lector de pantalla activo sin mover el foco de
    ningún control. `hwnd` es el handle nativo de un wx.Window ya creado
    (control.GetHandle()). Devuelve True si se pudo emitir la notificación
    UIA, False si no (el llamador debe recurrir a un anuncio alternativo).
    """
    if not _DISPONIBLE or not texto or not hwnd:
        return False
    try:
        _preparar_firmas()

        proveedor = ctypes.c_void_p()
        hr = _uia.UiaHostProviderFromHwnd(ctypes.c_void_p(hwnd), ctypes.byref(proveedor))
        if hr != 0 or not proveedor.value:
            return False

        bstr_texto = _oleaut32.SysAllocString(texto)
        bstr_id = _oleaut32.SysAllocString("AsistenteBiblioteca")
        try:
            hr = _uia.UiaRaiseNotificationEvent(
                proveedor, _NOTIFICATION_KIND_OTHER, _NOTIFICATION_PROCESSING_ALL,
                bstr_texto, bstr_id,
            )
        finally:
            _oleaut32.SysFreeString(bstr_texto)
            _oleaut32.SysFreeString(bstr_id)
        # El proveedor devuelto por UiaHostProviderFromHwnd no se libera
        # explícitamente (evita manipular su vtable COM a mano con ctypes,
        # frágil sin poder probarlo aquí): es un objeto ligero, uno por
        # notificación, y el proceso lo libera al salir. Coste despreciable
        # frente al riesgo de una llamada a Release() mal construida.
        return hr == 0
    except Exception:
        logger.exception("Error al emitir notificación UIA en vivo")
        return False
# ANCLAJE_FIN: NOTIFICADOR_LIVE_REGION_UIA
