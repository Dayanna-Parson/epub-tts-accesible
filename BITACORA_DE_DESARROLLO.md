# Bitácora de desarrollo — Epub TTS

*Historia completa del proyecto: de dónde viene, por qué casi muere y cómo llegó hasta aquí.*

---

## El origen: un lío entre el móvil, Word y Reaper

La idea de esta aplicación no nació de querer aprender a programar. Nació de un flujo de trabajo que se había vuelto insostenible.

Producir un audiolibro multivoz siendo ciega, en Windows, implicaba esto:

1. Preparar el texto en Word, insertando manualmente etiquetas para indicar qué voz debía hablar en cada fragmento.
2. Transferir el archivo al móvil.
3. Usar una aplicación Android (Arroba Voice) que sí entendía esas etiquetas y generaba el audio con voces de Azure, Polly o ElevenLabs.
4. Volver a transferir el audio al PC.
5. Editar y montar todo en Reaper.

No era un flujo de producción. Era una carrera de obstáculos que se repetía en cada capítulo, en cada libro, en cada corrección. Si un fragmento salía mal, todo el ciclo empezaba de nuevo. El simple hecho de probar una voz nueva requería pasar por el móvil.

Lo que me rompía no era la complejidad técnica. Era la dependencia constante de un dispositivo que no era donde vivía mi trabajo. El DAW estaba en el PC. Los archivos estaban en el PC. El proyecto entero estaba en el PC. Solo el paso crítico, la síntesis de voz con calidad, tenía que pasar por el móvil.

Había una aplicación de escritorio que hacía algo parecido, pero era pesada, poco accesible y no se adaptaba a mi flujo. No podía controlarse bien con teclado y NVDA, que es como yo trabajo. Y nadie iba a hacerla más accesible porque no era un problema visible para quien la desarrollaba.

Un día entendí que si quería resolver el problema, tenía que construir la solución yo misma. No era una decisión romántica. Era una consecuencia lógica: para explicarle a otra persona cómo debía funcionar la app, primero tenía que ser capaz de describir el sistema con precisión. Y para eso necesitaba entender cómo se construye.

Así que empecé a aprender a programar.

---

## El primer intento: Gemini y la Era de la Oscuridad

Los primeros meses de desarrollo los pasé trabajando con Gemini como asistente de IA.

No fue bien.

El problema no era que Gemini no supiera programar. El problema era que no entendía el contexto acumulado. En cada sesión, había que reexplicar cómo funcionaba la app, qué ya estaba implementado, qué no debía tocarse. Y aun así, las respuestas llegaban con código que rompía cosas que ya funcionaban: funciones desaparecidas sin aviso, indentación incorrecta que hacía fallar Python en silencio, cambios que parecían razonables pero que introducían regresiones que tardaba días en encontrar.

Hay problemas concretos que recuerdo con especial claridad:

**El reproductor que no se callaba.** pyttsx3, la librería para voces locales, tenía un comportamiento irracional al pausar: seguía hablando internamente aunque visualmente pareciera detenido. Al reanudar, el audio se superponía consigo mismo. Semanas intentando arreglar eso, con parches encima de parches que nunca resolvían la causa raíz.

**Las voces SAPI que tardaban siglos.** El tiempo que pasaba entre pulsar "reproducir" y que la voz empezara a hablar era tan largo que parecía que la app se había colgado. NVDA anunciaba el botón, el usuario pulsaba, y nada durante segundos. Desesperante.

**La barra de progreso enloquecida.** Un control que debía avanzar de forma continua durante la reproducción saltaba, se congelaba y a veces retrocedía. El hilo de reproducción y el hilo de la interfaz se pisaban entre sí de formas que eran casi imposibles de reproducir de forma consistente.

**El foco de NVDA que desaparecía.** Al abrir ciertos diálogos, NVDA se quedaba sin saber dónde estaba. El usuario pulsaba Escape para cerrar y el foco no volvía al control desde el que había abierto el diálogo. Quedarse desorientado en la interfaz cuando no ves la pantalla no es un inconveniente menor. Es quedarte a ciegas dentro de la app que estás usando.

Después de meses de avances seguidos de retrocesos, paré el proyecto.

Dos meses de pausa completa.

No era rendición. Era reconocer que el método no estaba funcionando y que necesitaba tiempo para pensar qué había salido mal y cómo empezar de nuevo.

---

## El renacimiento: a finales de enero, con Claude

A finales de enero retomé el proyecto. Esta vez con Claude.

La diferencia fue inmediata. No en velocidad, sino en calidad de la colaboración. El contexto se mantenía. Las decisiones previas se respetaban. Cuando decía "esto ya lo intentamos y no funcionó por X razón", esa información se incorporaba al razonamiento en lugar de ignorarse.

En dos semanas se arregló lo que en meses no había conseguido estabilizar:

- El reproductor TTS dejó de superponerse consigo mismo al pausar y reanudar.
- La latencia de las voces locales se redujo a algo aceptable.
- Los hilos de reproducción y UI dejaron de pisarse, con una arquitectura clara: el hilo principal solo toca la UI, los hilos secundarios solo tocan los datos, y `wx.CallAfter` hace de puente entre ambos mundos.
- El foco de NVDA empezó a volver correctamente a su lugar después de cada diálogo.

Pero más que los fixes, lo que cambió fue la forma de construir. En lugar de parchear código que ya existía y que nadie entendía del todo, empezamos desde los cimientos.

---

## Fase 1: los cimientos

La primera fase no fue añadir funciones. Fue decidir sobre qué construir.

wxPython en lugar de Tkinter o Qt. La razón es pragmática: wxPython usa controles nativos de Windows. NVDA los entiende sin configuración especial. Las alternativas tienen sus virtudes, pero en accesibilidad con lector de pantalla en Windows, los controles nativos son la única opción que funciona de forma predecible y sin sorpresas.

La estructura en tres pestañas (Lectura, Grabación, Ajustes) en lugar de un cuadro combinado para cambiar de modo. Un cuadro combinado parecía más compacto, pero la práctica mostró que las pestañas son mucho más claras para navegar con NVDA: el lector de pantalla anuncia el nombre de la pestaña activa, el usuario siempre sabe dónde está.

Los archivos de configuración en JSON locales, separados por propósito: uno para claves de API, otro para ajustes generales, otro para la jerarquía de proyectos. Nunca mezclados. Las claves de API en `.gitignore` desde el primer día.

El código en español. Deliberadamente. Hay quien argumenta que el código debería estar en inglés por convención. Pero este es mi primer proyecto grande y trabajar en mi idioma reduce los errores conceptuales, hace el código más legible para mí y es coherente con la interfaz y el público. No es una limitación técnica, es una decisión que facilita el mantenimiento.

---

## Fase 2: el modo grabación nace

La Fase 2 fue el modo grabación, que es la razón original por la que empezó todo esto.

El sistema de etiquetas: `{{@narrador}}`, `{{@adam}}`, `{{@personaje}}`. El usuario escribe su texto con esas marcas y la app sabe qué fragmento tiene que sintetizar con qué voz. El procesador de etiquetas (`procesador_etiquetas.py`) hace el análisis del texto y produce la lista de fragmentos que el grabador necesita.

FFmpeg portable en `/bin/`. En lugar de requerir que el usuario instale FFmpeg globalmente en el sistema, el ejecutable vive dentro del proyecto. El usuario no necesita saber que existe. La app lo usa directamente con la ruta absoluta. Esto fue una decisión que pareció un detalle menor pero que resultó ser crítica para la portabilidad: la app funciona igual instalada en `C:\Usuarios\Jacqui\` que en un USB, sin que el usuario tenga que configurar nada.

MP3 a 320 kbps como formato de salida. Para audiolibros de calidad, nada de 128 kbps.

---

## Fase 3: el gestor de proyectos y la arquitectura de privacidad

En Fase 3 llegó el gestor de proyectos, que en apariencia podría parecer una función secundaria. En la práctica es una de las piezas más usadas de la app.

El Gestor de Proyectos de Calibre es la herramienta estándar para organizar libros, pero es pesado y su accesibilidad con NVDA es limitada. El gestor de TifloHistorias tiene un objetivo mucho más concreto: organizar los proyectos de grabación de forma que sea fácil volver a cualquiera de ellos y encontrar los archivos de audio generados.

El árbol de proyectos con `Ctrl+Intro` que abre directamente la carpeta de grabaciones en el Explorador de Windows fue una de esas funciones que, una vez que existe, parece que siempre debería haber estado ahí. Es eficiencia real: en lugar de navegar carpetas anidadas con el Explorador, vas al proyecto en el árbol y pulsas `Ctrl+Intro`. Llegas directo.

También en Fase 3 se separaron las claves de API a su propio archivo (`claves_api.json`), blindado en `.gitignore`, con migración automática desde el formato anterior. GitHub había detectado una clave en un commit anterior y la había invalidado. Nunca más.

---

## Fase 4: la estabilización final

La Fase 4 no fue una fase de nuevas funciones. Fue la fase de convertir un proyecto funcional en una herramienta estable y lista para ser usada por otras personas.

### La auditoría de 40 bugs

Al inicio de la Fase 4 hicimos una auditoría completa del código: 40 problemas identificados, 11 de ellos críticos o graves. Los más importantes:

**Grabación en nube que fallaba en silencio.** El cliente de Azure intentaba leer las claves de API en el momento de la petición, pero el archivo `claves_api.json` no se cargaba en la inicialización del grabador. El resultado era que la grabación fallaba sin dar ningún error claro. El fix fue añadir `cargar_claves()` en el `__init__` del grabador.

**XML escaping incorrecto en Azure y Polly.** Al enviar texto con `&` (el símbolo ampersand) a la API de Azure, el carácter se enviaba sin escapar, lo que rompía el SSML y producía errores de la API. El fix fue usar `xml.sax.saxutils.escape()` correctamente. Silencioso, fácil de no ver, crítico para cualquier libro con nombres propios o títulos.

**`PanelVoces.mapa_indices` no inicializado.** Si el panel de ajustes se abría antes de que terminara la carga de voces, el código intentaba acceder a un diccionario que no existía todavía. Crash sin mensaje claro. Fix: inicializar el dict vacío en `__init__`.

**Sliders leyendo el archivo incorrecto.** Los controles de velocidad y volumen leían sus valores desde `config_general.json` (que ya no existía) en lugar de `ajustes.json`. Resultado: los valores que el usuario configuraba no se guardaban ni se recuperaban correctamente entre sesiones.

### Multicategoría de proyectos

El tipo de un proyecto pasó de ser un string a ser una lista. Un mismo libro puede ser a la vez "Fantasía" y "Serie". La migración es automática: si la app encuentra un tipo como string al cargar `proyectos.json`, lo convierte a lista sin pedirle nada al usuario.

El control de selección usa `CheckListCtrlMixin` con `EnableCheckBoxes(True)`. NVDA anuncia el estado de cada casilla al navegar con las flechas. Las 10 categorías son fijas: Serie, Libro, Fantasía, Distopía, Tecno-thriller, Diálogos, Tutorial, Publicidad, Artículo, Otros.

### Los 12 sonidos contextuales

Los sonidos no son decoración. Son información. Para una usuaria de NVDA que trabaja con la pantalla apagada o sin mirarla, saber que la grabación ha terminado sin tener que preguntar a NVDA dónde está el foco es eficiencia real.

Los 12 efectos cubren: arranque de la app, inicio y fin de grabación, tick de progreso, navegación por listas, mover elementos arriba/abajo, apertura de carpetas, éxito, clic, error, borrado. Todos en RAM desde el arranque. Todos asíncronos. Con un fallback al `winsound` de la stdlib si `wx.adv.Sound` falla.

Una decisión de diseño que tomó un tiempo llegar: los sonidos deben ser sutiles y breves, no llamativos. Cuando NVDA está hablando, el sonido no debe competir con él. El feedback sonoro existe para los momentos en que NVDA no está diciendo nada y el usuario necesita confirmación de que algo ocurrió.

### La latencia de foco

El problema de la latencia al cambiar de pestaña fue uno de los primeros que se resolvieron en Fase 4, y fue un ejemplo de por qué entender la causa raíz importa más que el fix rápido.

El síntoma: al cambiar a la pestaña de Lectura o de Ajustes, NVDA tardaba hasta 2 segundos en anunciar el nombre de la pestaña. El usuario pulsaba `Ctrl+Tab` y se quedaba en silencio durante un momento que se hacía eterno.

La causa: esas pestañas cargaban datos pesados (listas de voces, diccionarios de idioma) en el evento de activación, bloqueando el hilo principal antes de que wxPython pudiera actualizar el foco.

La solución no fue threading (que en wxPython es un territorio peligroso para la UI). Fue `wx.CallAfter`: diferir la carga hasta el siguiente tick del bucle de eventos, después de que el cambio de pestaña ya se haya procesado. Un cambio de una línea que convierte 2 segundos de silencio en respuesta inmediata.

### Los textos de la interfaz

En las últimas sesiones de Fase 4 se revisaron todos los textos visibles para el usuario: labels, helptexts, mensajes de diálogo. El objetivo era que sonaran naturales, coherentes y estándar para una app de escritorio, no generados por una IA.

"Nuevo hijo" pasó a "Nuevo subproyecto". "Restaurar eliminados" pasó a "Restaurar proyectos eliminados recientemente". Pequeños cambios que hacen que la app se sienta como algo hecho por personas, para personas.

---

## El estado actual

La Fase 4 terminó con esto:

- Cuatro motores TTS integrados y funcionando: Azure Neural, Amazon Polly, ElevenLabs, SAPI5.
- Modo Lectura completo: EPUB, navegación por índice, marcadores, memoria de posición, control de cuota.
- Modo Grabación funcional: etiquetas multivoz, fragmentación, exportación MP3 320kbps.
- Gestor de Proyectos: árbol jerárquico, multicategoría, papelera, `Ctrl+Intro` para carpetas.
- Divisor de EPUB integrado: sin depender de herramientas externas.
- 12 sonidos contextuales con doble motor y carga en RAM.
- Sistema de versiones con diálogo de novedades.
- Notificaciones de voces nuevas con cooldown de 24h.
- Logs limpios en `app/registros/app.log`.
- Accesibilidad NVDA comprobada en todos los controles.
- Portabilidad Windows/Linux con rutas absolutas y FFmpeg portable.

Esto es mucho más de lo que imaginé cuando escribí la primera línea de código.

---

## Lo que viene

**Piper TTS** como motor local de alta calidad. El objetivo es que la app funcione bien sin conexión y sin coste, con voces que suenen como algo más que los sintetizadores de Windows del año 2000. Piper es open source, no requiere conexión y tiene modelos en español que suenan bien. La arquitectura de clientes está preparada para recibirlo.

**Manual de usuario.** Una guía paso a paso para alguien que llega a la app por primera vez: cómo configurar las voces, cómo usar los marcadores, cómo preparar un archivo para grabación.

**Suite de tests automatizados.** El proyecto ha llegado hasta aquí con pruebas manuales. Funciona, pero es frágil en ese sentido. Los tests deben llegar.

---

## Una nota personal

Este proyecto empezó porque nadie había construido la herramienta que yo necesitaba.

En algún punto dejó de ser solo eso. Se convirtió en la prueba de que podía construirla yo misma. Y en el proceso de construirla, entendí cosas sobre cómo funcionan los programas, sobre arquitectura de software, sobre accesibilidad y sobre mis propios límites que no habría aprendido de ninguna otra forma.

La Era de la Oscuridad con Gemini fue frustrante. Pero también fue necesaria. Me enseñó a reconocer cuándo un enfoque no está funcionando, a parar a tiempo en lugar de seguir acumulando deuda técnica, y a ser más precisa al describir lo que quiero que haga el código.

La Fase 4 es el resultado de todo eso. Una versión estable, accesible y lista para ser usada. Una herramienta que hace exactamente lo que imaginé aquel día en que decidí que si nadie la iba a construir, la construiría yo.

— Dayanna Parson, marzo de 2026

## Fase 5: La Consolidación y el Motor de Alta Fidelidad (Marzo 2026)

Esta fase marca la transformación de Epub TTS en una herramienta profesional, integrando lógicas avanzadas de navegación y sincronización inspiradas en referentes como Bookworm.

**Hitos alcanzados:**
1. **Sincronización Exacta SAPI 5:** Implementamos una cola de párrafos con callbacks de progreso. El cursor se mueve en tiempo real con la voz local, permitiendo pausas quirúrgicas y una reanudación perfecta sin pérdida de posición.
2. **Navegación Semántica:** Incorporamos los atajos `H` y `Shift+H` para saltar entre encabezados (h1-h6) con respuesta sonora, mejorando drásticamente la navegación estructural.
3. **Soporte de Rich Text:** El motor ahora preserva visualmente negritas, cursivas y subrayados, permitiendo que el lector de pantalla brinde una lectura mucho más rica en matices.
4. **Optimización de Interfaz:** Unificamos atajos en `Control + O` (contextual) y refinamos los deslizadores de precisión (saltos de 1 y 10 unidades) para un control total sin fatiga auditiva.

Epub TTS es ahora la estación de trabajo que siempre soñé para mis audiolibros con multivoces.

---

## Fase 6: V2.0 — Accesibilidad profunda y voces Eloquence (Junio 2026)

La Fase 6 nació de una sesión larga de pruebas reales con NVDA. No de teoría ni de auditorías de código escritas a distancia, sino de sentarse con la app encendida, el lector de pantalla activo, y hacer exactamente lo que hace una usuaria ciega en su día a día.

Lo que salió fue una lista de cosas que no funcionaban como debían. Algunas eran bugs evidentes; otras eran detalles que solo se notan cuando usas la app de verdad y no solo la programas.

### Las voces Eloquence, por fin

La primera semana de junio llegó con una noticia: compré la licencia de CodeFactory para usar Eloquence y RealSpeak en Windows. Son voces SAPI5 de 32 bits, y mi app corre en 64 bits. No hablan entre sí.

El problema parecía difícil al principio. Una solución habitual sería pedir al usuario que instale una versión especial, o que configure algo manualmente. Eso no es una opción en una app pensada para personas ciegas que no tienen por qué saber si su Python es de 32 o 64 bits.

La solución fue un proceso puente: `auxiliar_sapi32.py` es un script pequeño que se compila con Python de 32 bits en un ejecutable independiente. La app principal de 64 bits lo lanza como subproceso y se comunica con él por líneas JSON en stdin/stdout. El usuario instala la app portable y todo funciona. No tiene que saber que ese puente existe.

El ejecutable `auxiliar_sapi32.exe` va en `/bin/`. Si no está, las voces de 32 bits simplemente no aparecen en la lista. Si el usuario intenta seleccionar una voz de CodeFactory sin el puente, aparece un mensaje claro que le dice qué está pasando, en lugar de silencio.

### Lo que NVDA no verbalizaba

Ctrl+I existía. Calculaba la página correctamente. Pero el mensaje se ponía en un `StaticText` y NVDA no lo anunciaba porque ese control no tenía el foco.

La solución fue el patrón `_anunciador`: un `wx.TextCtrl` de 1×1 píxeles, de solo lectura, que normalmente es invisible al usuario. Cuando hay que verbalizar algo urgente —la página actual, la confirmación de guardado—, ese control recibe el texto y el foco brevemente. NVDA lo anuncia. Luego el foco vuelve al control anterior, con `wx.CallLater(300ms)`.

Lo mismo ocurría con Ctrl+S en Ajustes. El usuario guardaba y no sabía si se había guardado. Con el mismo patrón, al pulsar Ctrl+S en cualquier panel de Ajustes, NVDA dice "Guardado." de inmediato.

### Las páginas que no cuadraban

El modo lectura mostraba 701 páginas para un libro de 432. El problema tenía dos causas: la unidad de página era de 1000 caracteres (demasiado pequeña), y los EPUBs suelen tener whitespace en exceso (espacios dobles, tabuladores, saltos de línea triples) que inflaba el recuento.

La solución fue elevar la unidad a 1800 caracteres y normalizar el texto antes de contarlo: una función `_longitud_normalizada()` que colapsa todo el espacio sobrante con regex antes de medir. Cada libro y cada capítulo calculan sus páginas sobre la longitud real del texto limpio.

### Los silencios de siete segundos

Uno de los bugs más desagradables: al pausar la reproducción, si había voces de nube en vuelo, los hilos de descarga seguían corriendo. El audio que llegaba después se reproducía igualmente, produciendo silencios raros y, a veces, que la voz anterior se superponiera con la nueva.

El fix fue quirúrgico: la primera línea de `detener()` incrementa `_generacion`. Todos los hilos de precarga capturan la generación en el momento de lanzarse. Si al volver comparan y la generación cambió, descartan el resultado sin reproducirlo.

### La pestaña que tardó en tener nombre correcto

En el primer boceto de la app, la pestaña de producción se llamaba "Modo Grabación". Pasó tiempo antes de que el nombre reflejara bien para qué sirve realmente. Pasó a llamarse "Crear Audiolibro" en esta versión.

### Las voces SAPI5 y el filtro de favoritas

Las voces de nube se filtraban por el archivo de favoritas. Las voces SAPI5 locales no. Si una usuaria quería ver solo sus voces locales preferidas en el combo del modo lectura, el filtro las ignoraba y mostraba todas.

Se corrigió unificando el filtro: ahora las voces SAPI5 (tanto 64 como 32 bits) pasan por el mismo sistema de favoritas que los proveedores de nube. Si no hay ninguna SAPI5 marcada como favorita, se muestran todas como respaldo.

### El árbol de ajustes y el `CheckListCtrlMixin`

En la versión anterior, la interfaz de ajustes era lineal. En esta versión, los ajustes se reorganizaron en un árbol de navegación (`wx.TreeCtrl` a la izquierda, contenido a la derecha). Es más limpio, más escalable, y NVDA navega por él con las flechas igual que por cualquier árbol nativo de Windows.

Durante ese trabajo, apareció un aviso en consola: `DeprecationWarning: CheckListCtrlMixin`. La causa era que las listas con casillas de verificación usaban `CheckListCtrlMixin.__init__(self)`, que en wxPython 4.2+ ya no hace falta y genera esa advertencia. Se eliminó de todos los archivos donde aparecía: `pestana_ajustes.py`, `dialogo_troceador.py`, `ventana_proyectos.py`, `pestana_grabacion.py`. `EnableCheckBoxes(True)` es suficiente.

### Actualizaciones automáticas completadas (Script Clon)

El sistema de actualizaciones automáticas estaba implementado desde la versión 1.1 en forma básica. En la versión 2.0 el flujo quedó completo: al detectar una versión nueva en GitHub, la app avisa de forma accesible. Si la usuaria acepta, descarga el ZIP en segundo plano, escribe `actualizador.bat` y se cierra. El script bat reemplaza los archivos y vuelve a abrir la app. Las grabaciones, configuraciones y la carpeta `/bin/` se conservan siempre.

— Dayanna Parson, junio de 2026

---

## Fase 7: V3.0 — Biblioteca y el Creador de Audiolibros (julio 2026)

La Fase 6 había resuelto la accesibilidad profunda de lo que ya existía. La Fase 7 fue distinta: añadió una pieza que no existía en absoluto. Hasta entonces, producir un audiolibro completo de un libro entero significaba abrirlo en Lectura y grabarlo yo misma, en tiempo real, escuchando cada palabra. Funcionaba, pero no era lo mismo que exportar un libro de 800.000 caracteres mientras hago otra cosa.

### La Biblioteca, primero

Antes del Creador de Audiolibros hacía falta un sitio de donde sacar los libros: la pestaña Biblioteca. Importar una carpeta entera de golpe (con detección de sagas por subcarpeta) o un único archivo suelto, organizar por géneros y por sagas, buscar por título o autor. No es una pestaña vistosa, pero es la que hace que todo lo demás tenga sentido: sin un sitio central de libros, "enviar a Creador de Audiolibros" no significaría nada.

### El Creador de Audiolibros: construir y volver a construir

La primera versión del selector de voz en el Creador de Audiolibros no fue la que quedó. Puse un campo de solo lectura llamado "Voz por defecto" con un botón "Elegir voz..." que abría un diálogo aparte. Funcionaba, pero no era lo que había en mi propio documento de planificación, y me lo dijo sin rodeos: *"¿por qué hay dos por defecto si yo en ningún momento recuerdo haber dicho que quería una voz por defecto?"*. Volví al documento, encontré la frase exacta que me había saltado — "selector de voz/proveedor" como control directo, al mismo nivel que el selector de modo — y lo rehice: un combo embebido en la propia pestaña con todas las voces favoritas de todos los proveedores, incluidas las locales SAPI5, en formato plano para que NVDA no tuviera que adivinar de qué proveedor era cada voz.

Ese patrón se repitió más veces de las que me gustaría admitir en esta fase: proponer algo, que las pruebas reales con NVDA lo tumben, y reconstruir con lo aprendido. No lo cuento como fracaso. Es exactamente el método que ya funcionó en la Fase 4 y la Fase 6: nada se da por bueno hasta que se prueba con el lector de pantalla encendido.

### El bug de "todo marcado"

Al construir el catálogo de voces reutilizable (`selector_voz_compartido.py`), apareció un bug sutil: al poblar la lista de voces con casillas de verificación, `CheckItem()` de wxPython dispara el mismo evento que si el usuario marcara la casilla a mano. El resultado era que cada voz ya favorita "contagiaba" el marcado a las demás, y cambiar de proveedor en un diálogo dejaba todas las casillas marcadas sin que nadie las hubiera tocado. El fix fue un candado (`_poblando_lista`) que ignora esos eventos sintéticos mientras la lista se está construyendo. El mismo patrón tuvo que repetirse después para la lista de capítulos del Creador de Audiolibros, que tiene el mismo problema de raíz.

### Polly, la investigación más larga de la fase

Ningún bug de esta fase me costó tantas vueltas como el de Amazon Polly comiéndose la última sílaba de la palabra, y solo con las cuatro voces estándar, y solo a partir de cierta velocidad. Fueron, en orden, cuatro intentos:

1. Ajustar el umbral de recorte de silencio en la costura entre fragmentos. No era eso: el problema aparecía también en la lectura en vivo, sin ninguna costura de por medio.
2. Un `<break>` SSML al final del texto, dentro de la etiqueta de velocidad. No bastaba a velocidades altas: el propio `<break>` se aceleraba junto con el resto del texto.
3. Sacar el `<break>` fuera de la etiqueta de velocidad y escalarlo con la propia velocidad. Ayudó, pero seguía fallando en algunos casos.
4. La solución real: rellenar el array de audio con silencio digital puro (ceros) al final, antes de mandarlo a los altavoces. Nada de temporización, nada de SSML — silencio real que el hardware nunca puede recortar porque no hay nada real que cortar detrás.

El motivo de que costara tanto fue estructural, no solo técnico: yo no puedo escuchar el audio que genera la app. Cada uno de esos cuatro intentos lo hice a ciegas (en el sentido literal de "no puedo verificarlo yo misma"), razonando desde el código y desde patrones conocidos de la comunidad de AWS, y esperando a que la usuaria lo probara con sus propios oídos antes de saber si había funcionado. Fue el recordatorio más claro de la fase de que "funciona en la teoría" y "funciona de verdad" son cosas distintas, y de que hacía falta ese diálogo constante y honesto sobre qué se podía verificar y qué no.

### El puente SAPI32, otra vez

El puente a las voces de 32 bits (Eloquence, RealSpeak) que se había resuelto en la Fase 6 volvió a fallar, esta vez de forma intermitente: "No se ha llamado a CoInitialize." El primer parche —añadir `CoInitialize()` en el hilo que habla— no fue suficiente. La causa real era más de fondo: un objeto COM creado en un hilo no se puede usar de forma fiable desde otro hilo aunque ese segundo hilo llame a `CoInitialize()`, porque falta el traspaso correcto entre apartamentos de Windows (marshaling). La solución robusta fue que cada hilo que habla cree y use su propia instancia del motor de voz, de principio a fin, sin compartir ningún puntero COM entre hilos.

### La exportación en paralelo

El cierre de la fase fue la pieza más grande de ingeniería: paralelizar la exportación con `ThreadPoolExecutor`, de forma que varios fragmentos o capítulos se generen a la vez en vez de uno detrás de otro. La parte delicada no fue lanzar hilos — eso es sencillo. Fue mantener dos garantías al mismo tiempo: que la comprobación de cuota siguiera siendo estrictamente secuencial y en el orden real del libro (para no dejar huecos), y que la numeración de los archivos generados en paralelo fuera atómica por índice, no por orden de llegada, para que el audiolibro final sonara exactamente en el mismo orden que el libro, sin importar qué hilo terminara antes.

Justo después llegó la reanudación de exportaciones pendientes: si una exportación se corta por cuota agotada o un corte de internet, la app recuerda dónde se quedó y permite continuar sin regrabar nada, numerando la continuación como una parte nueva del audiolibro.

### Lo que se descartó

Piper TTS, que llevaba desde la Fase 4 en la lista de "próximos motores", se descarta explícitamente en esta fase. SAPI5 sigue siendo, y se queda siendo, el único motor local de la app.

— Dayanna Parson, julio de 2026