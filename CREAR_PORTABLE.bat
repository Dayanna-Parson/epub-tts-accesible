@echo off
cd /d "%~dp0"
cls
echo ---------------------------------------------------
echo    CREANDO PORTABLE EPUB-TTS...
echo ---------------------------------------------------
python crear_portable.py
echo.
echo ---------------------------------------------------
echo    PROCESO TERMINADO
echo    (Si ves un error arriba, leelo ahora)
echo ---------------------------------------------------
pause
