@echo off
cd /d "%~dp0"
cls
echo ---------------------------------------------------
echo    INICIANDO EPUB-TTS...
echo ---------------------------------------------------

rem ANCLAJE_INICIO: INSTALAR_REQUISITOS_PRIMERA_VEZ
rem Instala las librerias de requisitos.txt la primera vez que se abre la
rem app, y de nuevo solo cuando requisitos.txt cambia (por ejemplo, tras una
rem actualizacion que necesita una libreria nueva). La copia guardada en
rem configuraciones\requisitos_instalados.txt marca lo que ya se instalo bien:
rem si pip falla, no se guarda y se reintenta en el siguiente arranque.
set "MARCA_REQUISITOS=configuraciones\requisitos_instalados.txt"
fc /b "requisitos.txt" "%MARCA_REQUISITOS%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo    Instalando las librerias necesarias. La primera vez puede tardar
    echo    varios minutos: no cierres esta ventana.
    echo.
    python -m pip install -r requisitos.txt
    if errorlevel 1 (
        echo.
        echo    No se pudieron instalar todas las librerias. Revisa el error de
        echo    arriba. Se volvera a intentar la proxima vez que abras la app.
        echo.
        pause
    ) else (
        if not exist "configuraciones" mkdir "configuraciones"
        copy /y "requisitos.txt" "%MARCA_REQUISITOS%" >nul
        echo.
        echo    Librerias instaladas correctamente.
        echo.
    )
)
rem ANCLAJE_FIN: INSTALAR_REQUISITOS_PRIMERA_VEZ

python iniciar_epub_tts.py
echo.
echo ---------------------------------------------------
echo    PROGRAMA CERRADO O FINALIZADO
echo    (Si ves un error arriba, leelo ahora)
echo ---------------------------------------------------
pause
