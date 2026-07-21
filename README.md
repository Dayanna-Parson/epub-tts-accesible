## 📘 Epub TTS Accesible

Aplicación de escritorio accesible para leer libros EPUB y PDF, y para producir audiolibros mediante síntesis de voz.

---

### ¿Qué es Epub TTS Accesible?

Epub TTS Accesible es una aplicación de escritorio para Windows, desarrollada en Python, pensada para que personas ciegas puedan leer y trabajar con libros EPUB y PDF de forma cómoda, controlada y accesible, utilizando distintos motores de síntesis de voz.

La aplicación nace de una necesidad real: poder leer libros largos y complejos en el PC, y preparar posteriormente audiolibros, sin depender de flujos frágiles ni de herramientas pensadas principalmente para móvil.

---

### ¿Para quién está pensada?

Personas ciegas o con baja visión que usan lector de pantalla.

Usuarios que quieran escuchar libros EPUB o PDF con TTS en Windows.

Personas interesadas en la producción de audiolibros.

Desarrolladores que quieran explorar un proyecto real de accesibilidad en Python.

---

### Qué puedes hacer con la aplicación

Con Epub TTS Accesible puedes:

organizar tu colección de libros EPUB y PDF por géneros y sagas,

abrir y leer esos libros, navegando por su índice,

escuchar el contenido mediante distintas voces TTS,

pausar, reanudar y moverte por el texto con saltos configurables,

añadir y gestionar marcadores,

elegir qué voces usar mediante un sistema de favoritas,

exportar un libro completo a audiolibro, en un único MP3 o dividido por capítulos, sin intervención manual,

producir audiolibros multivoz a mano con etiquetas de personaje,

controlar el consumo de servicios TTS de pago,

trabajar durante sesiones largas sin perder el contexto.

---

### Interfaz y elementos principales

La aplicación se organiza de forma clara y predecible:

**Pestañas**

- Biblioteca
- Modo Lectura
- Creador de Audiolibros
- Grabación de Fragmentos
- Ajustes

**Biblioteca**

- Importar una carpeta entera o un único libro suelto (EPUB o PDF).
- Organización por géneros y por sagas/colecciones.
- Buscador por título o autor.

**Modo Lectura**

- Controles de reproducción, selector de voces basado en favoritas.
- Gestión de marcadores mediante diálogos accesibles.
- Lectura continua con memoria de posición.
- Soporte de EPUB y PDF.

**Creador de Audiolibros**

- Exportación de un libro completo a un único MP3 o dividido por capítulos.
- Cálculo de presupuesto: caracteres, coste estimado y duración prevista.
- Exportación en paralelo y reanudación ante cortes de cuota o de conexión.

Todo está pensado para poder usarse únicamente con teclado y lector de pantalla.

---

### Síntesis de voz

La aplicación permite escuchar los libros utilizando distintos motores de voz:

- Voces locales mediante SAPI5 (64 y 32 bits, incluidas Eloquence y RealSpeak).
- Microsoft Azure TTS.
- ElevenLabs.
- Amazon Polly.
- Deepgram Aura-2 (recomendado como motor principal de nube, pay-as-you-go).

Si no hay conexión a internet o se alcanza un límite de uso, la app cambia automáticamente a voz local.

---

### Sistema de favoritos y filtros

Para facilitar el uso cuando hay muchas voces disponibles, Epub TTS Accesible incluye:

- Un sistema de voces favoritas.
- Filtros por idioma, proveedor, tipo de voz y texto de búsqueda.
- Persistencia de las preferencias entre sesiones.

---

### Control de cuota y costes

La aplicación incorpora un sistema de control de uso de servicios TTS:

- Contadores mensuales por proveedor, con coste estimado.
- Límites configurables por el usuario.
- Avisos al alcanzar un límite.
- Cambio automático a voz local.

---

### Accesibilidad

Epub TTS Accesible está diseñada desde el principio para funcionar con lectores de pantalla: controles nativos accesibles, flujos claros, uso completo con teclado, diálogos que siempre devuelven el foco a donde estaba. No es una adaptación posterior — es la base del proyecto.

---

### Manual de usuario

La aplicación incluye un manual de usuario en formato HTML accesible (`ayuda.html`). Puedes abrirlo con `F1` desde cualquier pestaña de la aplicación.

---

### Instalación y ejecución

```
git clone https://github.com/Dayanna-Parson/epub-tts-accesible.git
cd epub-tts-accesible
pip install -r requisitos.txt
python iniciar_epub_tts.py
```

Requiere Python 3.12+ en Windows. La versión portable (sin necesidad de instalar Python) se genera con `crear_portable.py` y se publica en la sección de [Releases](https://github.com/Dayanna-Parson/epub-tts-accesible/releases).

---

### Documentación

- [`BITACORA_DE_DESARROLLO.md`](BITACORA_DE_DESARROLLO.md) — historia narrada del proyecto, fase a fase.
- [`DEVELOPMENT.md`](DEVELOPMENT.md) — arquitectura técnica para quien colabore en el código.
- [`CLAUDE.md`](CLAUDE.md) — reglas del proyecto (idioma, estilo, accesibilidad).
- [`estructura_proyecto.txt`](estructura_proyecto.txt) — mapa rápido de archivos.
- [`documentos/Fases_Del_Proyecto/VISION_PERSONAL.md`](documentos/Fases_Del_Proyecto/VISION_PERSONAL.md) — por qué existe el proyecto.
- [`documentos/Fases_Del_Proyecto/GUIA_TECNICA.md`](documentos/Fases_Del_Proyecto/GUIA_TECNICA.md) — visión técnica completa para desarrolladores externos.

---

### Estado actual del proyecto

Epub TTS Accesible es una aplicación completa y estable. **Versión actual: 3.0.0.**

- Biblioteca: organización de EPUB y PDF por géneros y sagas, importación de carpetas o de libros sueltos.
- Modo lectura con voces de Azure, Amazon Polly, Deepgram, ElevenLabs y SAPI5 (64 y 32 bits), con soporte de EPUB y PDF.
- Creador de Audiolibros: exportación de un libro completo o por capítulos, con presupuesto de coste y duración, exportación en paralelo y reanudación ante cortes.
- Grabación de fragmentos multivoz con etiquetas de personaje `{{@voz}}`.
- Exportación MP3 a 320 kbps, normalizado a 44 100 Hz.
- Diccionario de pronunciación para todos los motores.
- Control de cuota, coste estimado y avisos de gasto por proveedor.
- Gestor de Proyectos con árbol jerárquico, papelera y acceso directo a las grabaciones.
- 12 sonidos contextuales y navegación semántica por encabezados.
- Ajustes en árbol de navegación y actualizaciones automáticas desde la propia app.

Piper TTS, que figuró como motor local previsto, queda descartado: SAPI5 sigue siendo el único motor local.

---

### Licencia

Licencia No Comercial. Ver el archivo [`LICENSE`](LICENSE) en la raíz del repositorio.

---

Desarrollado por **Dayanna Parson** ([TifloTutos](https://tiflotutos.com)).
