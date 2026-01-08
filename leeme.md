# Tiflo Historias 🎧📚

**Aplicación de escritorio accesible para Windows desarrollada en wxPython.**
Diseñada para leer EPUBs y producir audiolibros complejos con múltiples voces (Azure, Polly, ElevenLabs).

> *Creada por una desarrolladora ciega para revolucionar la producción de audio accesible.*

---

## 🌟 La Historia: Del problema a la solución

Este proyecto nace de una necesidad personal y profesional vinculada a mi sección web **"Tiflo Historias"**, donde publico audiolibros dramatizados.

Mi flujo de trabajo actual es artesanal y tedioso:
1.  **Guionizado:** Preparo los textos y diálogos en **Microsoft Word**, insertando etiquetas manuales para cada personaje.
2.  **La Barrera:** Para convertir ese texto en audio multivoz, dependo de aplicaciones móviles (como *@Voice*) que no existen en Windows. Esto me obliga a transferir archivos constantemente entre el PC y el móvil.
3.  **Post-producción:** Debo devolver los audios al PC para editarlos en **Reaper** y crear el montaje 3D final.

Las herramientas actuales de Windows (como *Balabolka*) no ofrecen la flexibilidad de lectura en tiempo real de EPUBs ni la integración ágil con voces neuronales modernas que necesito.

**Tiflo Historias** es la solución a este problema: una herramienta unificada en el escritorio que permite **leer, etiquetar y grabar** sin salir de Windows.

---

## 🚀 Funcionalidades Principales

### 🎧 Motor Multi-Proveedor (httpx)
Integración de alto rendimiento con las mejores voces neuronales:
- **Microsoft Azure TTS**
- **Amazon Polly**
- **Eleven Labs**
- **SAPI5 / pyttsx3** (Respaldo Offline)

### 📖 Modo Lectura (Consumo)
- Carga nativa de **EPUB**.
- Lectura continua con una sola voz.
- Navegación accesible por capítulos.
- Memoria de posición (retoma donde lo dejaste).

### 🎙️ Modo Grabación (Producción para "Tiflo Historias")
Diseñado para convertir guiones de Word/TXT en assets de audio:
- **División Inteligente:** Función exclusiva para separar el audio por etiquetas. Ideal para importar pistas separadas en **Reaper**.
- **Modo Continuo:** Genera un único archivo mezclado.

### 🏷️ Sistema de Etiquetas Inteligentes
Formato estándar para asignar roles en el texto:
* `{{@narr}}` → Voz Narradora.
* `{{@personaje}}` → Voz asignada en configuración.

---

## 💻 Requisitos Técnicos

* **Sistema:** Windows 10 / 11.
* **Python:** 3.12 (Estabilidad garantizada).
* **Librerías Clave:**
    * `wxPython`: Interfaz nativa y accesible.
    * `httpx`: Cliente HTTP moderno y asíncrono para las APIs.
    * `pydub` / `sounddevice`: Procesamiento y grabación de audio.
