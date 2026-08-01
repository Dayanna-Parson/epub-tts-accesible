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

La app trabaja con cinco motores de voz, cada uno con un rol claro:

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

limpieza de caché,

efectos de sonido (casilla global y activación individual por efecto),

credenciales, modelo y temperatura del Asistente de Biblioteca (Gemini), y gestión de sus plantillas de prompt.

Toda la configuración se guarda en archivos JSON locales (o, en el caso de las plantillas de prompt, en archivos de texto individuales pensados para poder editarse también desde fuera de la app).

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

PyMuPDF (fitz): lectura y estructura de PDF, con la misma forma de datos que EbookLib para no duplicar lógica en Lectura ni en el Creador de Audiolibros.

accessible-output3: anuncios de interfaz directos al lector de pantalla activo (NVDA, JAWS...), sin mover el foco. Es distinta de pyttsx3: esta última sigue usándose, pero solo donde puede llegar una ráfaga rápida de anuncios seguidos (el progreso de escanear una carpeta grande), porque descarta los anuncios intermedios y solo dice el más reciente.

requests, sin SDK adicional, también para el Asistente de Biblioteca (Gemini): mismo criterio que con Azure, Polly, Deepgram y ElevenLabs, para no añadir una dependencia nueva solo por un proveedor más.

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

Esto no entra en conflicto con que, desde la Fase 7, la interfaz sí hable dos idiomas (español e inglés) de cara al usuario final. El código sigue en español sin excepción; lo que cambia con el idioma es únicamente el texto que ve o escucha quien usa la aplicación.

#### Arquitectura de internacionalización (i18n)

La interfaz usa `gettext`, de la librería estándar de Python, en vez de una librería de terceros (Babel, `python-i18n`...). La razón es de portabilidad: `gettext` no añade ninguna dependencia nueva a `requisitos.txt`, y el compilador de catálogos que necesita (`msgfmt`) no viene incluido en una instalación estándar de Windows — exigiría que cada persona que quisiera compilar los catálogos instalara herramientas de gettext aparte, algo inviable para una app portable pensada para instalarse sin fricción. Por eso el proyecto tiene su propio compilador, `compilar_i18n.py`: lee cada `.po` y escribe el `.mo` binario correspondiente usando solo `struct` y `array` de la librería estándar, sin invocar ningún binario externo.

La convención de import es siempre explícita, nunca por inyección en `builtins`:

```python
from app.motor.gestor_idioma import traducir as _
```

Inyectar `_` en `builtins` (patrón común en otros proyectos con gettext) se descartó a propósito: en este proyecto hay un proceso auxiliar aparte (el puente SAPI5 de 32 bits, `auxiliar_sapi32.py`) y varios diálogos de wxPython que pueden instanciarse antes de que el intérprete principal termine de inicializarse del todo; en ambos casos depender de un builtin global es una fuente de fallos silenciosos difíciles de depurar. El import explícito por módulo es más verboso, pero nunca falla de forma invisible.

`app/motor/gestor_idioma.py` resuelve el idioma activo con una prioridad fija: parámetro explícito → variable de entorno `EPUB_TTS_IDIOMA` (para pruebas locales) → clave `"idioma"` en `ajustes.json` (el selector de Ajustes → General) → idioma detectado de Windows → español como último recurso. `traducir()` delega en `gettext.translation(...).gettext()`, con `fallback=True`: si no existe una entrada para una cadena en el idioma activo, o no hay `.mo` compilado para ese idioma, se devuelve el propio texto en español sin lanzar ninguna excepción.

Estructura del catálogo: `locale/epub_tts.pot` es la plantilla (un `msgid` por cada cadena única envuelta en `_()` en toda la app), y de ahí se derivan `locale/es/LC_MESSAGES/epub_tts.po` y `locale/en/LC_MESSAGES/epub_tts.po`. Regla fija del proyecto: en `es.po`, `msgstr` es siempre igual al `msgid` — nunca una entrada vacía — porque el español es el idioma de referencia y una entrada vacía se traduciría, en tiempo de ejecución, como una cadena vacía en vez de caer de vuelta al texto original.

La regla arquitectónica que no se negocia es que ninguna cadena usada para lógica de control se envuelve en `_()`: claves de diccionario o de JSON persistido, ids internos de proveedor (`"azure"`, `"local_32"`...), rutas de archivo, ni ningún texto de menú o combo que la propia aplicación lea de vuelta con `GetStringSelection()`/`GetItemText()` para decidir un flujo. Envolver esas cadenas las haría depender del idioma activo, y el enrutamiento interno de la app dejaría de funcionar en cuanto alguien cambiara el idioma a inglés.

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

patrón `_anunciador` para verbalizaciones inmediatas sin mover el foco (retirado en la Fase 7 a favor de `accessible_output3`, ver más abajo),

árbol de navegación en Ajustes (`wx.TreeCtrl`), sustituyendo la disposición lineal anterior,

sistema de actualizaciones automáticas completo (Script Clon): descarga, sustitución de archivos y reinicio sin perder configuración ni grabaciones.

Añadido en v3.0.0 (Fase 7):

Pestaña Biblioteca: importación de carpetas y de libros sueltos (EPUB y PDF), organización por géneros y por sagas/etiquetas, buscador. Persistencia en `biblioteca.db` (SQLite), no en JSON, para poder manejar colecciones grandes con consultas relacionales,

Soporte de PDF además de EPUB, tanto en Lectura como en el nuevo Creador de Audiolibros, vía PyMuPDF (`fitz`),

Creador de Audiolibros: exportación de un libro completo a un único MP3 o dividido por capítulos, con calculador de presupuesto (caracteres, coste estimado, duración prevista), selector de voz favorita embebido con preescucha, exclusión de capítulos antes de exportar, carpetas de salida organizadas por saga, exportación en paralelo con `ThreadPoolExecutor` y reanudación de exportaciones cortadas por cuota o corte de conexión,

filtro de características en las voces de Azure (Multilingüe, Dragon, MaiVoice, Flash),

corrección de fondo del puente SAPI5 de 32 bits (cada hilo que habla crea y usa su propia instancia del motor COM, sin compartir punteros entre hilos),

silencio digital real al final de cada síntesis de Amazon Polly (motor estándar) para evitar el corte de la última sílaba a velocidades altas,

Asistente de Biblioteca con Google Gemini (`cliente_gemini.py`, REST puro sin SDK): chat accesible con `Ctrl+Shift+B`, contexto automático del libro/saga/categoría seleccionados o del catálogo completo en modo general, plantillas de prompt de sistema personalizables (Ajustes → Asistente de Biblioteca, un archivo `.txt` por plantilla), modelo y temperatura configurables, Google Search Grounding para fundamentar recomendaciones,

reemplazo del patrón `_anunciador` por `accessible_output3` (`anunciador_lector.py`) en toda la app, hablando directo al lector de pantalla activo sin mover el foco; se mantiene `pyttsx3` solo para secuencias de anuncios muy rápidas (progreso de escaneo de Biblioteca),

14 sonidos contextuales (se añaden `thinking.wav` en bucle y `page_scrolled.wav`), con casilla global y activación individual por efecto desde Ajustes → Efectos de Sonido,

copias de seguridad de biblioteca y proyectos separadas por tipo, con historial rotativo de 5 copias y creación solo ante cambios reales.

Piper TTS, que figuraba como motor local previsto desde la Fase 4, queda descartado explícitamente.

Fase C — actualizador automático (v4.0): sustitución del script `.bat` generado al vuelo (v2.0) por un ejecutable auxiliar fijo, `bin/actualizador.exe`, con el mismo patrón de compilación que `auxiliar_sapi32.exe`. Respaldo por copia verificada (no por movimiento) antes de reemplazar cualquier archivo, y rollback automático si algo falla. Ya validado de extremo a extremo en Windows real (descarga, verificación e instalación) y conectado al botón real de producción "Buscar actualizaciones ahora"; el sistema anterior ("Script Clon") se mantiene aparte, sin usarse, como red de seguridad mientras se acumulan más actualizaciones reales confirmadas antes de retirarlo.

Añadido en v4.0.0 (Fase 8):

Perfiles de usuario (`gestor_perfiles.py`): cada perfil guarda la voz activa, las voces favoritas por proveedor, velocidad, volumen, segundos de salto y pausa entre fragmentos, en `configuraciones/perfiles.json`. Panel único en Ajustes → Perfiles de Usuario, con un formulario que reúne los cinco campos a la vez (crear o editar), aplicando el perfil de inmediato al guardar. Atajo global `Ctrl+Shift+U` para alternar circularmente entre perfiles desde cualquier pestaña. Tests unitarios del proyecto ampliados a 126 (`tests/test_suite.py`), cubriendo proyectos, cuota, config, perfiles, comprobador de versiones, atajos y diccionario de pronunciación — sin cobertura todavía de la interfaz gráfica.

Corregido durante las pruebas reales del primer portable de la Fase 8: ruta incorrecta de lectura de versión local en `comprobador_actualizaciones.py` (comparaba siempre contra `0.0.0` y ofrecía instalar versiones antiguas); `AnunciadorVoz` (pyttsx3) mudo dentro del `.exe` congelado por depender de `sys.executable -c`, que dentro de PyInstaller ya no es un intérprete real (se resolvió con un modo de re-ejecución `--hablar-interno`); `Ctrl+I` cayendo en la pestaña equivocada por aceleradores duplicados entre paneles y ventana principal; falta de `--collect-all=accessible_output3` en el empaquetado con PyInstaller. El mismo patrón de voz/progreso ya usado en el escaneo de Biblioteca se replicó en el divisor de capítulos de EPUB (`dialogo_troceador.py`) y se corrigió en Grabación de Fragmentos, que llamaba a `pyttsx3` dentro del propio proceso en vez de en uno auxiliar.

Añadido en v4.1.0 (Fase 9 — Estabilización, sin funciones nuevas):

Auditoría completa de excepciones silenciosas: un recorrido con AST (no solo texto) sobre `app/`, los dos ejecutables auxiliares e `iniciar_epub_tts.py` encontró 359 bloques `except` en total, de los cuales 174 en 31 archivos capturaban el error sin ningún rastro observable. Todos corregidos con `logger.exception`/`logger.debug`/`logger.warning` según la severidad real del caso, o por el canal propio de cada auxiliar (`_log()`/`_enviar()`/`_log_error()` a stderr) donde no hay logger central de `app/` disponible.

Tests unitarios ampliados de 126 a 169 (`tests/test_suite.py`): `TestGestorBiblioteca` (CRUD de libros, categorías jerárquicas, etiquetas/sagas, exportaciones pendientes, regresión de migración de esquema `ALTER TABLE`) y `TestPersistenciaJsonAtomica` (escritura atómica, incluida una interrupción simulada a mitad de escritura).

Rendimiento: `_aplicar_reglas_de_biblioteca()` en `limpiador_lectura.py` abría una conexión SQLite nueva por cada página de un PDF; ahora las reglas se cachean compiladas por `ruta_libro`. `Freeze`/`Thaw` añadido en cuatro listas/árboles que insertaban fila a fila sin él (Grabación, Troceador, Ajustes ×2, ventana de Proyectos). Prefiltrado con `in` antes del `re.sub` en `DiccionarioPronunciacion.aplicar()`.

Empaquetado (`crear_portable.py`): `novedades.txt`, `LEEME.txt` y `LICENSE` van ahora directos a la raíz del portable junto a `ayuda.html` y `epubtts.exe`, sin la subcarpeta `documentos/` que antes solo contenía un archivo. `registros/` y `registros/errores/` se siembran de fábrica en el ZIP. Aviso explícito por consola si faltan `bin/ffmpeg.exe` o `bin/auxiliar_sapi32.exe` al empaquetar.

Documentación de usuario reescrita a fondo (`ayuda.html`, `README.md`, `novedades.txt`, `LEEME.txt` nuevo): guías paso a paso para conseguir cada clave de API, tabla de contenidos, secciones que faltaban por completo (Ventana de Proyectos, sistema de voces favoritas y filtros, significado de cada sonido), y preguntas frecuentes.

Nada más pendiente en las funciones esenciales. La v4.1.0 es la versión final antes de pasar a distribución pública.

---

### 16. Si vas a tocar el código

Si vas a colaborar, es importante tener en cuenta que:

la accesibilidad es el eje del proyecto,

la voz local es siempre el respaldo,

la interfaz no debe bloquearse,

las decisiones actuales no son casuales.

La idea es que este documento, junto con el código, te permita entender toda la app sin tener que reconstruirla a base de pruebas.