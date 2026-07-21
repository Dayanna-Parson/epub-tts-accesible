## 👩‍💻 Documento para desarrolladores – visión completa de la app

Este documento lo escribo yo misma para cualquier desarrollador o desarrolladora a quien le vaya a pasar el código completo de la aplicación, ya sea por GitHub o de forma directa. La idea es que, leyendo este texto con calma (una o dos veces), puedas hacer un mapa mental completo de la app: qué ve el usuario, qué puede hacer en cada parte y cómo encaja eso con el código.

No pretende sustituir al código, pero sí evitar que tengas que abrirlo todo el rato para entender qué está pasando.

---

### 1. Punto de partida y contexto

Esta aplicación es una app de escritorio para Windows, escrita en Python, pensada para leer libros en formato EPUB y producir audiolibros con múltiples voces.

Está diseñada desde el principio para ser usable por personas ciegas, porque yo lo soy. Esto no es un añadido posterior: condiciona toda la app. La estructura, la interfaz, los flujos y muchas decisiones técnicas parten de cómo se usa un lector de pantalla en la práctica, durante sesiones largas de trabajo.

---

### 2. Qué problema intenta resolver realmente

El problema no es simplemente “leer libros con TTS”. El problema es trabajar con libros largos y complejos, escucharlos de forma cómoda y, más adelante, producir audiolibros, sin depender de flujos frágiles o de herramientas pensadas para móvil.

Antes de esta app, mi flujo incluía:

preparar textos en Word,

insertar manualmente marcas para voces y personajes,

usar aplicaciones móviles para generar audio,

mover archivos constantemente entre móvil y PC,

editar después en Reaper.

La app nace para unificar y simplificar todo eso en un entorno de escritorio accesible.

---

### 3. Vista general de la interfaz

La aplicación se organiza visualmente en pestañas, porque es la forma más clara y accesible de separar usos:

Biblioteca

Modo Lectura

Creador de Audiolibros

Grabación de Fragmentos

Ajustes

Además, hay un menú superior desde el que se accede a acciones generales como cargar libros o gestionar recientes.

La idea es que el usuario siempre sepa dónde está y qué puede hacer en cada momento, sin menús ocultos ni flujos confusos.

---

### 4. Modo Lectura: qué ve y qué puede hacer el usuario

El Modo Lectura es la parte más desarrollada ahora mismo y donde se concentra la mayor complejidad.

Desde aquí el usuario puede:

abrir un libro EPUB,

navegar por su índice,

moverse por el texto de forma continua,

reproducir el contenido mediante síntesis de voz,

pausar, reanudar y saltar adelante o atrás,

guardar y gestionar marcadores,

elegir qué voz usar para la lectura.

#### Elementos clave del Modo Lectura

Selector de voces: no muestra todas las voces disponibles, solo las que el usuario ha marcado previamente como favoritas.

Controles de reproducción: reproducir, pausar, detener y saltos configurables.

Marcadores: se gestionan desde un diálogo donde se pueden añadir, renombrar o eliminar.

Libros recientes: desde el menú Archivo se pueden abrir los últimos libros usados o borrar el historial.

La lectura se concibe como una experiencia continua, no como un simple botón de play.

---

### 5. EPUB como base

El formato EPUB se utiliza por su estructura real:

orden de lectura definido (spine),

índice navegable,

separación clara de contenido.

Existe un gestor específico que:

abre el EPUB,

limpia el HTML,

elimina ruido visual,

reconstruye el índice jerárquico,

mapea posiciones reales del texto.

La interfaz nunca trabaja directamente con HTML crudo.

---

### 6. El reproductor: núcleo de la app

El reproductor es una de las piezas centrales. Su responsabilidad es:

gestionar estados (detenido, reproduciendo, pausado),

decidir qué motor de voz usar,

reproducir texto sin bloquear la interfaz,

manejar errores de red o de API,

asegurar que nunca se quede la app en silencio.

El reproductor no conoce ni la interfaz ni el EPUB. Recibe texto y lo envía al motor correspondiente.

---

### 7. Motores de síntesis de voz y su papel

La app trabaja con cuatro motores de voz, cada uno con un rol claro:

SAPI5 (local): voces locales. Se usa como respaldo y para trabajar sin conexión.

Microsoft Azure TTS: motor principal para lectura en tiempo real.

Amazon Polly: motor neuronal alternativo.

ElevenLabs: voces más expresivas y multilingües.

Deepgram Aura-2: motor REST puro, pay-as-you-go. Recomendado como alternativa principal por velocidad y coste.

Si falla una API o no hay conexión, la app pasa automáticamente a voz local.

---

### 8. Gestor de voces, favoritos y filtros

Las voces no se consultan continuamente a internet. Existe un gestor que:

descarga las voces bajo demanda,

las guarda en caché local,

normaliza la información entre proveedores,

permite trabajar sin conexión.

Sobre esto se construye el sistema de favoritos, que es clave para la usabilidad.

Las voces se pueden filtrar por:

idioma,

proveedor,

tipo,

texto de búsqueda,

favoritas.

---

### 9. Control de cuota y costes

La app incluye un sistema de control de cuota que:

lleva contadores mensuales por proveedor,

permite definir límites,

se reinicia automáticamente cada mes,

avisa cuando se alcanza un límite,

cambia automáticamente a voz local.

Esto evita consumos inesperados y errores por exceso de peticiones.

---

### 10. Ajustes

Desde la pestaña de ajustes se controla:

claves API,

idioma del libro,

rutas de exportación,

límites de cuota,

tiempos de salto adelante y atrás,

limpieza de caché.

Toda la configuración se guarda en archivos JSON locales.

---

### 11. Librerías utilizadas y por qué

Las principales librerías del proyecto son:

wxPython: interfaz gráfica de escritorio con accesibilidad nativa. Es la librería con la que he aprendido a hacer apps y la que mejor se adapta al uso con lector de pantalla.

requests: comunicación HTTP simple y suficiente para el estado actual del proyecto.

httpx: incluida pensando en el futuro (modo grabación y uso asíncrono).

pyttsx3 / SAPI5: acceso a voces locales mediante SAPI5.

pydub: manipulación básica de audio.

sounddevice / soundfile: reproducción y manejo de audio.

numpy: soporte para trabajo con audio.

EbookLib: lectura y estructura de EPUB.

BeautifulSoup: limpieza del HTML del EPUB.

Dependencias técnicas internas (como h2) se mantienen en requirements, pero no son relevantes a nivel conceptual.

---

### 12. Versión de Python

La app se ha desarrollado y probado con Python 3.12.x en Windows. No se garantiza compatibilidad con versiones anteriores.

---

### 13. Idioma del código

Todo el código está escrito en español de forma deliberada.

Es mi primer proyecto grande y trabajar en mi idioma:

reduce errores conceptuales,

facilita el mantenimiento,

hace el código más legible,

es coherente con la interfaz.

---

### 14. Qué no forma parte del proyecto

No se utiliza OpenVoice.

No se clonan voces.

No se intenta eludir límites de servicios TTS.

---

### 15. Estado actual del proyecto

Implementado en v1.0.0:

modo lectura completo,

reproducción multivoz,

favoritos y filtros,

control de cuota,

ajustes.

Añadido en v1.1.0:

Amazon Polly integrado como motor alternativo,

modo grabación con exportación MP3 a 44 100 Hz mono,

sistema de etiquetas {{@voz}} para producción multivoz,

deslizadores de velocidad y volumen en grabación,

descarga automática de actualizaciones.

Añadido en v1.2.0:

Deepgram Aura-2 como cuarto motor de voz neuronal,

diccionario de pronunciación (pronunciacion.json),

historial de voces nuevas (voces_conocidas.json),

control de cuota extendido a Deepgram,

lectura sin pausas entre fragmentos de nube (modo_cola en cargar_texto()).

nivel de consola elevado a WARNING: los mensajes de arranque no aparecen en la terminal ni son verbalizados por NVDA.

Añadido en versiones posteriores (hasta v2.0.0):

Gestor de Proyectos independiente, con árbol jerárquico, multicategoría, papelera y acceso directo a la carpeta de grabaciones con `Ctrl+Intro`,

Divisor de EPUB integrado por capítulos, sin depender de herramientas externas,

12 sonidos contextuales con doble motor (`wx.adv.Sound` y `winsound` de respaldo),

soporte de voces SAPI5 de 32 bits (Eloquence, RealSpeak) mediante un proceso puente de 32 bits,

navegación semántica por encabezados (`H` / `Shift+H`) y patrón `_anunciador` para verbalizaciones inmediatas sin mover el foco,

árbol de navegación en Ajustes (`wx.TreeCtrl`), sustituyendo la disposición lineal anterior,

sistema de actualizaciones automáticas completo (Script Clon): descarga, sustitución de archivos y reinicio sin perder configuración ni grabaciones.

Añadido en v3.0.0 (Fase 7):

Pestaña Biblioteca: importación de carpetas y de libros sueltos (EPUB y PDF), organización por géneros y por sagas/etiquetas, buscador. Persistencia en `biblioteca.db` (SQLite), no en JSON, para poder manejar colecciones grandes con consultas relacionales,

Soporte de PDF además de EPUB, tanto en Lectura como en el nuevo Creador de Audiolibros, vía PyMuPDF (`fitz`),

Creador de Audiolibros: exportación de un libro completo a un único MP3 o dividido por capítulos, con calculador de presupuesto (caracteres, coste estimado, duración prevista), selector de voz favorita embebido con preescucha, exclusión de capítulos antes de exportar, carpetas de salida organizadas por saga, exportación en paralelo con `ThreadPoolExecutor` y reanudación de exportaciones cortadas por cuota o corte de conexión,

filtro de características en las voces de Azure (Multilingüe, Dragon, MaiVoice, Flash),

corrección de fondo del puente SAPI5 de 32 bits (cada hilo que habla crea y usa su propia instancia del motor COM, sin compartir punteros entre hilos),

silencio digital real al final de cada síntesis de Amazon Polly (motor estándar) para evitar el corte de la última sílaba a velocidades altas.

Piper TTS, que figuraba como motor local previsto desde la Fase 4, queda descartado explícitamente.

En desarrollo dentro de v3.0.0 (Fase C — actualizador automático): sustitución del script `.bat` generado al vuelo (v2.0) por un ejecutable auxiliar fijo, `bin/actualizador.exe`, con el mismo patrón de compilación que `auxiliar_sapi32.exe`. Respaldo por copia verificada (no por movimiento) antes de reemplazar cualquier archivo, y rollback automático si algo falla. Implementado y probado con simulaciones y con el tramo de descarga/verificación en Windows real; pendiente de validar en Windows real el ciclo completo de instalación antes de retirar el sistema anterior, que sigue activo en producción mientras tanto.

Nada más pendiente en las funciones esenciales.

---

### 16. Si vas a tocar el código

Si vas a colaborar, es importante tener en cuenta que:

la accesibilidad es el eje del proyecto,

la voz local es siempre el respaldo,

la interfaz no debe bloquearse,

las decisiones actuales no son casuales.

La idea es que este documento, junto con el código, te permita entender toda la app sin tener que reconstruirla a base de pruebas.