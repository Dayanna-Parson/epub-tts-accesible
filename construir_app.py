import os

# --- MAPA DE ESTRUCTURA  ---
estructura_proyecto = {
    "recursos": {
        "iconos": [],   # Carpeta para imágenes .png/.ico
        "sonidos": []   # Carpeta para audios .wav del sistema
    },
    "configuracion": [
        "ajustes_globales.json",
        "mapeo_etiquetas.json",
        "voces_favoritas.json",
        "libros_recientes.json",
        "datos_lectura.json"
    ],
    "registros": ["app.log", "errors.log"],
    "documentos": ["CHANGELOG.md"],
    "app": {
        "__init__.py": "",
        "motor": [ # Lógica pura (Antiguo 'core')
            "__init__.py",
            "gestor_epub.py",         # Antes: epub_loader.py
            "motor_tts.py",           # Antes: tts_engine.py
            "procesador_etiquetas.py",# Antes: tag_processor.py
            "grabador_audio.py",      # Antes: audio_recorder.py
            "gestor_config.py",       # Antes: config_manager.py
            "reproductor_voz.py"      # Antes: audio_player.py (Solo control)
        ],
        "interfaz": [ # Interfaz Gráfica (Antiguo 'ui')
            "__init__.py",
            "ventana_principal.py",   # Antes: main_window.py
            "pestana_lectura.py",     # Antes: read_tab.py
            "pestana_grabacion.py",   # Antes: record_tab.py
            "pestana_ajustes.py",     # Antes: utils_ui.py / settings
            "dialogos.py"             # Antes: dialogs.py
        ],
        "servicios": [ # Conexiones TTS (Antiguo 'services')
            "__init__.py",
            "cliente_azure.py",
            "cliente_polly.py",
            "cliente_eleven.py",
            "cliente_sapi5.py"        # Lógica movida aquí
        ]
    }
}

# --- CONTENIDO BÁSICO DEL LEEME (README) ---
texto_leeme = """# Tiflo Historias 🎧📚

**Aplicación de escritorio accesible para crear audiolibros.**

Estructura del Proyecto:
- **app/**: Código fuente.
  - **motor/**: Lógica de lectura y audio.
  - **interfaz/**: Ventanas y menús.
  - **servicios/**: Conexión con Azure, Polly, SAPI5.
- **configuracion/**: Archivos JSON de datos.
- **recursos/**: Iconos y sonidos.
"""

def crear_estructura():
    base = "." 
    print(f"--- Creando/Verificando estructura 'Tiflo Historias' ---")

    for carpeta, contenido in estructura_proyecto.items():
        ruta_carpeta = os.path.join(base, carpeta)
        os.makedirs(ruta_carpeta, exist_ok=True)
        print(f"[DIR] {carpeta}")
        
        if isinstance(contenido, list):
            for archivo in contenido:
                ruta = os.path.join(ruta_carpeta, archivo)
                if not os.path.exists(ruta):
                    with open(ruta, 'w', encoding='utf-8') as f: pass
                    print(f"  [+] Creado archivo: {archivo}")
        
        elif isinstance(contenido, dict):
            for subcarpeta, subarchivos in contenido.items():
                ruta_sub = os.path.join(ruta_carpeta, subcarpeta)
                
                # Si es un archivo (termina en .py pero está como clave de dict)
                if subcarpeta.endswith(".py"): 
                    if not os.path.exists(ruta_sub):
                        with open(ruta_sub, 'w', encoding='utf-8') as f: pass
                        print(f"  [+] Creado archivo: {subcarpeta}")
                else:
                    # Es una subcarpeta
                    os.makedirs(ruta_sub, exist_ok=True)
                    print(f"  [DIR] {subcarpeta}")
                    for subarch in subarchivos:
                        ruta_final = os.path.join(ruta_sub, subarch)
                        if not os.path.exists(ruta_final):
                            with open(ruta_final, 'w', encoding='utf-8') as f: pass
                            print(f"    [+] Creado archivo: {subarch}")

    # Crear LEEME si no existe
    if not os.path.exists("README.md"):
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(texto_leeme)
        print("[+] Creado README.md")

if __name__ == "__main__":
    crear_estructura()
    print("\n✅ Estructura verificada.")