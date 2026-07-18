## 📘 Visión personal del proyecto – Documento completo

Documento privado. Este texto está pensado para sustituir por completo al documento original extenso, en caso de que se pierda. No presupone ningún otro contexto.

---

### 1. Punto de partida real (por qué empiezo a programar)

Este proyecto no nace solo de una idea creativa ni de una inquietud técnica. Nace del momento en el que me doy cuenta de algo muy concreto:

si yo no era capaz de construir la aplicación, tampoco iba a ser capaz de explicarle a otra persona en qué consistía mi programa, ni cómo debía funcionar.

Hasta entonces, la programación era algo secundario para mí. Pero al intentar trasladar mi idea a otros desarrolladores, me di cuenta de que:

la idea estaba clara en mi cabeza,

el problema estaba perfectamente identificado,

pero no tenía el lenguaje ni la estructura para explicarlo con precisión.

Aprender a programar fue, en realidad, una consecuencia lógica: necesitaba convertir una intuición en un sistema concreto, desmontable y explicable.

---

### 2. El problema real que quiero resolver

El problema no es “leer libros” ni “usar voces”. El problema es producir audiolibros complejos de forma accesible y sostenible en Windows, siendo una persona ciega.

Mi flujo previo incluía:

preparación de textos en Word,

inserción manual de marcas para narrador y personajes,

uso de aplicaciones móviles para generar audio multivoz,

transferencia constante entre móvil y PC,

edición final en Reaper.

Este flujo era frágil, lento y mentalmente agotador. Las herramientas existentes en Windows no cubrían esta necesidad de forma integrada ni accesible.

---

### 3. Decisión de plataforma: escritorio y Windows

El proyecto se concibe desde el inicio como una aplicación de escritorio para Windows, porque:

el DAW y la postproducción viven en el PC,

los proyectos largos se gestionan mejor en escritorio,

la accesibilidad real con lector de pantalla es más controlable.

No es una elección ideológica, es una elección práctica.

---

### 4. Elección de tecnología: wxPython

Se elige wxPython porque:

ofrece controles nativos accesibles,

funciona de forma predecible con lectores de pantalla,

permite interfaces claras y estables,

evita dependencias web que suelen romper accesibilidad.

La prioridad nunca fue la estética, sino la fiabilidad y el control.

---

### 5. Estructura final de la aplicación

Aunque en un planteamiento inicial se barajó el uso de un cuadro combinado para cambiar de modo, la experiencia real mostró que la mejor solución era una estructura por pestañas.

La aplicación se divide en:

Modo Lectura

Modo Grabación

Ajustes

Esta estructura mejora:

la comprensión mental del flujo,

la navegación con lector de pantalla,

la escalabilidad futura.

---

### 6. Modo Lectura: más que leer

El modo lectura no es un visor pasivo. Incluye:

carga nativa de EPUB,

extracción limpia del texto,

navegación por índice jerárquico,

marcadores personalizados (gestionados desde un diálogo que muestra un listado de marcadores previamente guardados, con posibilidad de añadir, renombrar o eliminar),

memoria de posición,

control de reproducción,

integración con múltiples motores TTS.

También permite escuchar los libros en tiempo real utilizando voces de Azure, Amazon Polly y ElevenLabs, siempre a partir de las voces que el usuario haya marcado previamente como favoritas. Estas voces favoritas aparecen directamente en el cuadro combinado de selección de voz durante la lectura.

Para evitar un uso excesivo de las APIs y prevenir costes inesperados o errores de reproducción, el código incorpora límites de caracteres y tiempos de espera específicos cuando se utilizan voces en la nube.

Además, desde el menú Archivo existe un submenú de Recientes, que permite abrir los últimos libros utilizados y borrar el historial cuando se desee.

La lectura se concibe como una experiencia continua y controlada, no como un simple play/stop.

---

### 7. Formato EPUB como base

El EPUB se utiliza por su estructura real:

orden de lectura (inspirado en el índice de Bookworm),

índice navegable,

separación clara del contenido,

compatibilidad con libros digitales en este formato.

Existe un gestor dedicado que:

limpia el HTML,

elimina ruido visual,

reconstruye el índice,

mapea posiciones reales del texto.

Esto permite tanto la lectura como la producción posterior.

---

### 8. El reproductor: núcleo lógico de la app

El reproductor se diseña como una pieza independiente con reglas claras:

nunca dejar la app muda,

no bloquear la interfaz,

proteger al usuario frente a errores y costes.

Gestiona estados explícitos (detenido, reproduciendo, pausado) y trata de forma distinta voces locales y de nube.

---

### 9. Motores de voz soportados

La aplicación utiliza actualmente cuatro motores de voz, cada uno con un rol claro:

SAPI5 (local): respaldo offline, siempre disponible.

Microsoft Azure TTS: voz neuronal principal.

Amazon Polly: voz neuronal alternativa.

ElevenLabs: voces expresivas y multilingües.

Deepgram Aura-2: motor neuronal rápido, sin suscripción mensual fija.

La voz local actúa siempre como paracaídas de seguridad.

---

### 10. Gestión de voces y favoritos

Las voces no se consultan en tiempo real continuamente. Existe un sistema que:

descarga las voces desde internet bajo demanda,

las guarda en caché local,

permite trabajar sin conexión,

normaliza datos entre proveedores.

Sobre esa base se construye un sistema de favoritos, que permite:

marcar voces preferidas,

filtrarlas,

reutilizarlas rápidamente,

mantener consistencia entre sesiones.

---

### 11. Filtros de voces

La app incluye un sistema completo de filtrado:

por idioma,

por proveedor,

por tipo (femenino, masculino, multilingüe, Dragon),

por texto de búsqueda,

por favoritas.

Esto permite manejar listas grandes de voces sin perderse.

---

### 12. Control de cuota y costes

Uno de los pilares del proyecto es el control consciente del gasto.

Cada proveedor tiene:

contadores mensuales,

límites configurables,

reinicio automático por mes.

Si se supera un límite:

la lectura se detiene,

se informa al usuario,

se pasa automáticamente a voz local.

Esto protege al usuario de facturas inesperadas.

---

### 13. Ajustes centralizados

La pestaña de ajustes centraliza:

rutas de exportación (para exportar libros en formato MP3 a 320 kbps; solo se pueden exportar grabaciones completas de libros, o según el estado de la opción de etiquetas en el modo grabación),

claves API,

idioma del libro,

gestión de voces,

límites de cuota,

personalización del tiempo de salto hacia adelante y hacia atrás,

un botón específico para eliminar la caché local.

Toda la configuración se guarda en archivos locales claros y legibles.

---

### 14. Diálogos y accesibilidad

Los diálogos (marcadores, exportación, confirmaciones) están diseñados para:

uso completo con teclado,

foco controlado,

mensajes claros,

compatibilidad total con lectores de pantalla.

---

### 15. Por qué el código está en español

Este es mi primer proyecto grande.

Usar español en el código:

reduce errores conceptuales,

mejora mi comprensión del sistema,

facilita el mantenimiento,

es coherente con el público y la interfaz.

No es una limitación técnica, sino una decisión consciente.

---

### 16. Qué no forma parte del proyecto

No se utiliza OpenVoice.

No se clonan voces.

No se persiguen atajos éticamente dudosos.

El foco está en el uso responsable de TTS existentes.

---

### 17. De los planes a la realidad

Los tres grandes bloques que quedaban pendientes se completaron en dos versiones:

Versión 1.1.0:

Amazon Polly, integrado como motor neuronal alternativo.

Sistema de etiquetas {{@voz}} para producción multivoz.

Modo Grabación: exportación MP3 a 320 kbps, normalizado a 44 100 Hz.

Deslizadores de velocidad y volumen en modo grabación.

Descarga automática de actualizaciones desde el repositorio.

Versión 1.2.0:

Deepgram Aura-2, integrado como motor de síntesis neuronal recomendado.

Diccionario de pronunciación: correcciones fonéticas locales para todos los motores.

Historial de voces nuevas: detección automática entre actualizaciones del catálogo.

Control de cuota extendido a Deepgram.

Lectura continua sin pausas entre fragmentos en la nube.

Mensajes de arranque silenciados: NVDA ya no verbaliza textos técnicos de la consola al abrir la app.

Versión 2.0.0:

Gestor de Proyectos independiente, con árbol jerárquico, papelera y acceso directo a las grabaciones.

Divisor de EPUB integrado, 12 sonidos contextuales y voces SAPI5 de 32 bits (Eloquence, RealSpeak) mediante un proceso puente.

Árbol de navegación en Ajustes, navegación semántica por encabezados y verbalización inmediata sin mover el foco.

Sistema de actualizaciones automáticas completo, con reinicio de la app sin perder configuración ni grabaciones.

Versión 3.0.0:

Pestaña Biblioteca, con importación de carpetas y de libros sueltos, organización por géneros y sagas.

Soporte de PDF además de EPUB, en Lectura y en el nuevo Creador de Audiolibros.

Creador de Audiolibros: exportación de un libro completo o por capítulos, con presupuesto de coste y duración, exportación en paralelo y reanudación de exportaciones cortadas por cuota o corte de conexión.

Piper TTS, previsto desde hacía tiempo como motor local futuro, queda descartado. SAPI5 sigue siendo, y se queda siendo, el único motor local.

El criterio ha sido el mismo a lo largo de todo el proceso: que funcione, que sea accesible, que el coste sea transparente.

---

### 18. Cierre personal

Este proyecto no nace para impresionar.

Nace para resolver un problema real desde la experiencia real de la ceguera.

Si algún día dudo, este documento es la prueba de que cada decisión tuvo un motivo.