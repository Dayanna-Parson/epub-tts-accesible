@echo off
cd /d "%~dp0"
cls
echo ---------------------------------------------------
echo    INICIANDO EPUB-TTS...
echo ---------------------------------------------------
python iniciar_epub_tts.py
echo.
echo ---------------------------------------------------
echo    PROGRAMA CERRADO O FINALIZADO
echo    (Si ves un error arriba, leelo ahora)
echo ---------------------------------------------------
pause
