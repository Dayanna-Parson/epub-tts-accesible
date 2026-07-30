@echo off
cd /d "%~dp0"
cls
echo ---------------------------------------------------
echo    SUBIR VERSION - Epub TTS Accesible
echo ---------------------------------------------------
echo.
python subir_version.py
echo.
echo Que tipo de cambio quieres publicar?
echo   1. patch  (correcciones menores:  2.0.0 -^> 2.0.1)
echo   2. minor  (funciones nuevas:      2.0.0 -^> 2.1.0)
echo   3. major  (cambio importante:     2.0.0 -^> 3.0.0)
echo   4. Escribir el numero exacto      (ej: 2.0.0)
echo   5. Cancelar
echo.
set /p OPCION="Elige una opcion (1-5): "

if "%OPCION%"=="1" (
    python subir_version.py patch
    goto FIN
)
if "%OPCION%"=="2" (
    python subir_version.py minor
    goto FIN
)
if "%OPCION%"=="3" (
    python subir_version.py major
    goto FIN
)
if "%OPCION%"=="4" (
    set /p VERSION="Escribe el numero de version (ej: 2.0.0): "
    python subir_version.py %VERSION%
    goto FIN
)
if "%OPCION%"=="5" (
    echo Cancelado.
    goto FIN
)
echo Opcion no reconocida. Cancelando.

:FIN
echo.
pause
