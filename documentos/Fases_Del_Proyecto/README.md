## 📘 Epub TTS Accesible

Aplicación de escritorio accesible para leer libros EPUB y trabajar con audiolibros mediante síntesis de voz.

---

### ¿Qué es Epub TTS Accesible?

Epub TTS Accesible es una aplicación de escritorio para Windows, desarrollada en Python, pensada para que personas ciegas puedan leer y trabajar con libros EPUB de forma cómoda, controlada y accesible, utilizando distintos motores de síntesis de voz.

La aplicación nace de una necesidad real: poder leer libros largos y complejos en el PC, y preparar posteriormente audiolibros, sin depender de flujos frágiles ni de herramientas pensadas principalmente para móvil.

---

### ¿Para quién está pensada?

Personas ciegas o con baja visión que usan lector de pantalla.

Usuarios que quieran escuchar libros EPUB con TTS en Windows.

Personas interesadas en la producción de audiolibros.

Desarrolladores que quieran explorar un proyecto real de accesibilidad en Python.

---

### Qué puedes hacer con la aplicación

Con Epub TTS Accesible puedes:

abrir y leer libros en formato EPUB,

navegar por el índice del libro,

escuchar el contenido mediante distintas voces TTS,

pausar, reanudar y moverte por el texto con saltos configurables,

añadir y gestionar marcadores,

elegir qué voces usar mediante un sistema de favoritas,

controlar el consumo de servicios TTS de pago,

consultar al Asistente de Biblioteca (Google Gemini) sobre tu catálogo, con recomendaciones y plantillas de prompt personalizables,

trabajar durante sesiones largas sin perder el contexto.

---

### Interfaz y elementos principales

La aplicación se organiza de forma clara y predecible:

Pestañas

Biblioteca

Modo Lectura

Creador de Audiolibros

Grabación de Fragmentos

Ajustes

Barra de menú

opciones para cargar libros EPUB o PDF,

acceso a libros recientes,

posibilidad de borrar el historial.

Biblioteca

importar una carpeta entera o un único libro suelto,

organización por géneros y por sagas/colecciones,

buscador por título o autor.

Modo Lectura

controles de reproducción,

selector de voces (basado en favoritas),

gestión de marcadores mediante diálogos accesibles,

lectura continua con memoria de posición,

soporte de EPUB y PDF.

Creador de Audiolibros

exportación de un libro completo a un único MP3 o dividido por capítulos,

cálculo de presupuesto: caracteres, coste estimado y duración prevista,

exportación en paralelo y reanudación ante cortes de cuota o de conexión.

Todo está pensado para poder usarse únicamente con teclado y lector de pantalla.

---

### Síntesis de voz

La aplicación permite escuchar los libros utilizando distintos motores de voz:

voces locales mediante SAPI5,

Microsoft Azure TTS,

ElevenLabs,

Amazon Polly,

Deepgram Aura-2 (recomendado como motor principal de nube, pay-as-you-go),

Si no hay conexión a internet o se alcanza un límite de uso, la app cambia automáticamente a voz local.

---

### Sistema de favoritos y filtros

Para facilitar el uso cuando hay muchas voces disponibles, Epub TTS Accesible incluye:

un sistema de voces favoritas,

filtros por idioma, proveedor, tipo de voz y texto,

persistencia de las preferencias entre sesiones.

Esto permite centrarse solo en las voces que realmente interesan.

---

### Control de cuota y costes

La aplicación incorpora un sistema de control de uso de servicios TTS:

contadores mensuales por proveedor,

límites configurables por el usuario,

avisos al alcanzar un límite,

cambio automático a voz local.

El objetivo es evitar consumos inesperados y errores durante la reproducción.

---

### Ajustes

Desde la pestaña de ajustes se pueden configurar, entre otras cosas:

claves API,

idioma del libro,

tiempos de salto adelante y atrás,

rutas de exportación,

limpieza de caché.

Toda la configuración se guarda localmente.

---

### Accesibilidad

Epub TTS Accesible está diseñada desde el principio para funcionar con lectores de pantalla:

controles nativos accesibles,

flujos claros,

uso completo con teclado,

diálogos pensados para no perder el foco.

No es una adaptación posterior, sino la base del proyecto.

---

### Atajos de teclado

La aplicación utiliza atajos de teclado para facilitar la navegación y la reproducción.

⚠️ Esta sección se completará cuando el conjunto de atajos esté definitivamente cerrado.

---

### Manual de usuario

La aplicación incluye un manual de usuario en formato HTML accesible. Puedes abrirlo con F1 desde cualquier pestaña de la aplicación.

cómo usar el modo lectura,

cómo gestionar marcadores,

cómo configurar las voces y el diccionario de pronunciación,

cómo interpretar los avisos de cuota,

cómo preparar contenidos para audiolibros.

---

### Estado actual del proyecto

Epub TTS Accesible es una aplicación completa y estable. Versión actual: 3.0.0.

Biblioteca: organización de EPUB y PDF por géneros y sagas, importación de carpetas o de libros sueltos,

modo lectura con voces de Azure, Amazon Polly, Deepgram, ElevenLabs y SAPI5 (64 y 32 bits), con soporte de EPUB y PDF,

Creador de Audiolibros: exportación de un libro completo o por capítulos, con presupuesto de coste y duración, exportación en paralelo y reanudación ante cortes,

grabación de fragmentos multivoz con etiquetas de personaje {{@voz}},

exportación MP3 a 320 kbps, normalizado a 44 100 Hz,

diccionario de pronunciación para todos los motores,

control de cuota, coste estimado y avisos de gasto por proveedor,

Gestor de Proyectos con árbol jerárquico, papelera y acceso directo a las grabaciones,

Asistente de Biblioteca con IA (Google Gemini): recomendaciones y consultas sobre tu catálogo, con plantillas de prompt personalizables,

divisor de EPUB integrado por capítulos,

14 sonidos contextuales y resalte en negrita de los encabezados (h1-h6) en el contenido leído,

copias de seguridad automáticas y rotativas de la biblioteca y los proyectos, separadas por tipo,

ajustes avanzados en árbol de navegación y actualizaciones automáticas desde la propia app,

silencio total en la consola al arrancar: NVDA no verbaliza textos técnicos de inicio.

Piper TTS, que figuró como motor local previsto, queda descartado: SAPI5 sigue siendo el único motor local.

---

### Instalación y ejecución

Este proyecto está pensado principalmente para usuarios finales y desarrolladores.

Las instrucciones técnicas de instalación, dependencias y entorno se encuentran en los archivos del repositorio (por ejemplo, requirements.txt).

---

### Documentación

📘 Documento 1: Visión personal del proyecto

👩‍💻 Documento 2: Visión técnica completa para desarrolladores

📄 Documento 3: Presentación pública / README (este documento)

---

### Licencia

Licencia No Comercial. Ver el archivo `LICENSE` en la raíz del repositorio.