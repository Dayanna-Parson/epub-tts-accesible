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
2. **Navegación Semántica (intento fallido):** Incorporamos los atajos `H` y `Shift+H` para saltar entre encabezados (h1-h6) con respuesta sonora. Nunca llegaron a funcionar de verdad — el `EVT_CHAR_HOOK` del Frame principal se quedaba con la tecla antes de que le llegara al área de texto — y se retiraron varias versiones después, junto con el código muerto que dejaron. Lo que sí quedó de este intento fue útil por otro lado: los datos de posición de cada encabezado, reutilizados para aplicarles negrita.
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

### El audiolibro sin sonido

Con la fase ya cerrada y publicada, las pruebas reales de uso encontraron un puñado de bugs que ninguna revisión de código hubiera detectado sin escucharlos.

El primero, el más serio: exportar un audiolibro con voz local podía dejar un archivo "generado" con éxito, pero completamente mudo. La comprobación de que el audio estuviera bien solo miraba si el archivo pesaba más de cero bytes, y un WAV con cabecera pero sin fotogramas de audio pasa esa prueba sin más. Se cambió por una comprobación real: abrir el WAV y medir su duración de verdad. Si sale en silencio, ahora es un error, no un archivo válido.

Relacionado con esto, un botón que llevaba tiempo roto sin que nadie lo notara: "Usar voz local", el que aparece cuando se agota la cuota de todos los proveedores de nube, siempre grababa con la voz predeterminada del sistema. Por debajo se le pasaba un dict genérico sin ningún id real, así que nunca podía encontrar ninguna voz instalada por su nombre. Se le añadió un desplegable de verdad con todas las voces SAPI5 (64 y 32 bits) para elegir.

Y las voces de 32 bits (Eloquence, RealSpeak) elegidas para exportar tenían un problema más de fondo: `_llamar_motor()` las enrutaba, por defecto, al mismo motor de 64 bits que usan Elena, Pablo y Laura — un motor que nunca puede encontrarlas, porque son un proceso auxiliar aparte. Exportar con Eloquence, hasta ahora, siempre acababa hablando con la voz por defecto sin ningún aviso. Se le dio al proceso auxiliar de 32 bits un comando nuevo, `exportar_archivo`, que sintetiza directo a WAV igual que hace el motor de 64 bits, y se enrutó `local_32` ahí en vez de al motor equivocado.

### El desbordamiento al unir trozos de distinta calidad

Un error de consola nuevo, tras arreglar lo anterior: `'L' format requires 0 <= number <= 4294967295` al concatenar los trozos de un fragmento largo con Amazon Polly. La causa era que solo se normalizaba a 44100 Hz/mono el resultado final de la unión, no cada trozo individual antes de unirlo. El motor "generative" de Polly puede devolver un trozo con una frecuencia o profundidad de bits distinta a la de otro trozo del mismo fragmento, y el reajuste interno de pydub al pegarlos podía calcular mal el tamaño combinado. Ya se recuperaba solo con un respaldo (unir los MP3 en bytes crudos), así que no llegaba a romper la exportación, pero dejaba ese ruido feo en el log. Ahora cada trozo se normaliza antes de recortarle el silencio y antes de unirlo.

### "¿Dónde estaba grabando?"

La última pieza de esta ronda no fue un bug de audio, sino de orientación: no había ninguna forma de saber, desde Biblioteca, qué libro tenía una exportación de audiolibro a medias sin abrir el Creador de Audiolibros y comprobarlo a mano. La columna Estado solo hablaba de lectura (leído, leyendo, pendiente de leer). Se añadió un estado nuevo, "Audiolibro a medias", y un filtro dedicado para encontrarlos todos de un vistazo — con una consulta nueva a `exportaciones_pendientes` que no existía hasta ahora (`obtener_ids_libros_con_exportacion_pendiente`).

De paso, con el nuevo filtro al lado, el viejo "Pendientes" (un estado de lectura, "quiero leerlo pronto") se prestaba a confundirse con una exportación pendiente. Se renombró a "Pendiente de leer" en todos los sitios donde aparecía.

Y un bug de accesibilidad puro, encontrado al describir la pantalla con el visor de voz de NVDA: el buscador, el filtro de Estado y "Solo favoritos" habían quedado descolgados al final del orden de tabulación de toda la pestaña, después incluso de los botones de importar, por un `MoveAfterInTabOrder()` que solo reposicionaba la lista de libros y los botones, dando por hecho que los filtros —creados antes— se quedarían en su sitio sin más. No era así: al mover la lista, los filtros que nadie tocó explícitamente quedaron sueltos al final de todo. Se encadenó el orden completo a mano.

### El Asistente de Biblioteca: dar de comer a Gemini sin que invente

La última pieza grande de esta fase fue un chat con IA integrado en la propia app: el Asistente de Biblioteca, con Google Gemini por debajo, activable con Control + Mayús + B desde cualquier pestaña. La idea era sencilla — recomendaciones, dudas sobre autores y sagas, análisis de lo que ya tengo en la biblioteca — pero el camino hasta que fuera de fiar no lo fue tanto.

El primer problema real fue que Gemini se inventaba datos: nombres de autores que no existen, sinopsis de libros que no había leído, y hasta negaba tener una saga que sí tenía en mi propia biblioteca. La instrucción de sistema tuvo que volverse mucho más estricta (prohibir explícitamente inventar cuando no encuentra algo, apoyarse en la búsqueda web para verificar antes de afirmar), bajar la temperatura del modelo a 0.4 para respuestas menos "creativas", y —lo que de verdad resolvió lo de la saga— dejar de mandarle solo un resumen con los géneros y autores más frecuentes de la biblioteca en modo general, y mandarle el catálogo completo de títulos, autores y sagas. Calculado al vuelo desde `biblioteca.db` cada vez que se abre el chat, sin ninguna caché que mantener sincronizada: el coste real de una consulta SQL y de un texto plano de títulos es tan bajo que no compensaba la complejidad de cachearlo.

El segundo problema fue de accesibilidad pura, y aquí NVDA volvió a ser el único juez posible. El patrón que llevaba usando desde el principio del proyecto para verbalizar avisos sin mover el foco (un `wx.TextCtrl` oculto de 1×1 píxel que recibía el foco un instante) se notaba muchísimo peor en un chat: con mensajes llegando seguidos, NVDA anunciaba el rol del control oculto —"edición, solo lectura"— en cada uno, como si saltara una ventana flotante en mitad de la conversación. La solución fue una librería que no había usado antes en el proyecto, `accessible_output3`: habla directo al lector de pantalla activo, sin tocar el foco para nada. Sonó tan limpio que acabé reemplazando el patrón viejo en toda la aplicación, no solo en el chat — con una única excepción a propósito: el progreso de escaneo de Biblioteca, que sigue con la cola de voz de `pyttsx3` de siempre, porque ahí interesa más que se diga el número más reciente y se descarten los intermedios, cosa que `accessible_output3` no hace por sí solo.

Las plantillas de prompt (distintos "estilos" del asistente: fantasía épica, suspense, análisis crítico...) pasaron por tres formas de guardarse antes de quedar bien: primero un único JSON con todas dentro, después separadas en archivos de texto individuales para poder editarlas a mano desde fuera de la app. Ahí hubo un susto de verdad: una migración mal pensada dejó plantillas mías huérfanas en el formato antiguo, sin pasar nunca al nuevo, y en medio de arreglar eso un `git rm --cached` que yo entendía como "solo dejar de rastrear" acabó borrando de mi disco real, al hacer `git pull`, plantillas y hasta el historial de conversación — un recordatorio de que en Git casi nada es tan inocuo como parece, y de que probar en la propia máquina de la usuaria, no solo en la lógica del código, sigue siendo la única forma de confiar en un cambio.

También cayó un control mal elegido: el deslizador de temperatura de Gemini empezó como un `wx.SpinCtrlDouble`, y NVDA lo leía como "edición, seleccionado 0.3" sin decir nunca "Temperatura", pese a tener su nombre accesible puesto por código. La causa fue que ese control no es nativo de Windows —lo dibuja la propia wxPython— y no hereda la misma exposición accesible que sí tienen los deslizadores nativos que ya uso para Velocidad y Volumen en Lectura. Cambiarlo a un `wx.Slider` normal, el mismo patrón ya probado, lo arregló sin más vueltas.

Y de propina, una reorganización pendiente desde hacía tiempo: las copias de seguridad de la biblioteca y de los proyectos vivían mezcladas en la misma carpeta, y la de la biblioteca se creaba en cada arranque de la pestaña aunque no hubiera cambiado nada. Ahora cada una tiene su propia carpeta, se compara la fecha de modificación contra la última copia antes de crear una nueva, y el nombre del archivo se acortó a algo que se sigue de oído sin esfuerzo.

## Fase 7 (cierre): idioma de interfaz y primer manifiesto Winget (julio 2026)

Con la Biblioteca, el Creador de Audiolibros y el Asistente de Gemini ya asentados, quedaba una tarea pendiente desde el principio de la Fase 7: que la interfaz pudiera hablar en otro idioma además del español, sin depender de traducir a mano cada `SetLabel()` que se fuera añadiendo.

La solución se apoyó en `gettext`, de la propia librería estándar de Python, en vez de cualquier librería externa de traducción: cada cadena visible al usuario se envuelve en una función `_()` (importada explícitamente como `from app.motor.gestor_idioma import traducir as _` en cada módulo, nunca inyectada en `builtins`, porque eso puede fallar en silencio dentro del proceso puente de SAPI5 de 32 bits o en diálogos que se instancian antes de que el intérprete principal termine de arrancar). Un catálogo de plantilla (`locale/epub_tts.pot`) reúne cada cadena única, y de ahí se derivan los catálogos por idioma (`locale/es/` y `locale/en/`), con la regla de que el español siempre lleva `msgstr` igual al `msgid` — nunca vacío — para que quede como referencia legible del texto original.

En vez de depender de `msgfmt`, que en Windows exige instalar herramientas de gettext aparte, se escribió un compilador propio y minúsculo, `herramientas/compilar_i18n.py`, que convierte cada `.po` a su `.mo` binario sin más dependencia que la propia librería estándar. El catálogo terminó reuniendo cerca de mil cadenas de interfaz completas, con el inglés traducido en su totalidad.

Un barrido posterior con el propio AST de Python (buscando llamadas a `wx.MessageBox`, `SetLabel`, `SetToolTip` y `voz.hablar` con texto español embebido) encontró dos archivos que se habían quedado completamente fuera del primer paso de envoltura —`ventana_principal.py` y `reproductor_voz.py`— además de un par de avisos sueltos en `cliente_sapi5.py` y `control_cuota.py`. Se completaron con el mismo patrón y se añadieron sus cadenas nuevas a los tres catálogos.

En Ajustes → General se añadió el selector de idioma de la interfaz (español/inglés), que guarda su elección en `ajustes.json` y se aplica por completo al reiniciar la aplicación; `crear_portable.py` ahora compila los catálogos y empaqueta `locale/` dentro del portable automáticamente, así que un `.zip` publicado ya lleva ambos idiomas listos para usar.

Por último, se preparó —sin publicarla todavía— una primera versión de los manifiestos de Winget (`winget/version.yaml`, `winget/installer.yaml`, `winget/locale.yaml`), marcados explícitamente como provisionales: el nombre comercial definitivo de la aplicación sigue sin decidirse (TifloReader, TifloVoice y TifloEstudio ya se descartaron), así que el identificador de paquete usado por ahora, `TifloTutos.EpubTTSAccesible`, es solo un nombre de trabajo a la espera de esa decisión y de la primera Release real en GitHub.

Nada más probar el cambio de idioma en caliente saltó un crash repetido en Modo Lectura: `UnboundLocalError` sobre la propia función `_()`. La causa, una vez encontrada, resultó tonta y peligrosa a la vez — la costumbre de usar `_` como nombre de variable de descarte en desempaquetados de tupla (`for etiq, _ in ...`, `texto_sig, _ = ...`) llevaba años siendo inofensiva, hasta que `_` empezó a significar también "la función de traducir" en el mismo archivo. Python trata `_` como local a toda la función en cuanto se le asigna en algún punto, así que cualquier llamada a `_("...")` anterior a esa asignación, dentro de la misma función, revienta. Apareció en seis funciones repartidas entre Lectura, Grabación, Ajustes y el Gestor de Proyectos — un barrido con el AST de Python, buscando funciones que a la vez asignan a `_` y llaman a `_(...)`, confirmó que no quedaba ninguna más. La costumbre, de aquí en adelante, es no volver a usar `_` suelto como descarte en ningún archivo que importe el traductor.

Y para no tener que recordar de memoria el orden de los scripts de publicación (traducir, subir de versión, empaquetar, y cuándo —si alguna vez— tocaría enviar Winget), se documentó todo en `GUIA_SCRIPTS.md`, con una tabla resumen y el paso a paso de cada uno.

— Dayanna Parson, julio de 2026

---

## Fase 8: V4.0 — Perfiles de usuario (julio 2026)

Con la Biblioteca, el Creador de Audiolibros y el Asistente de Gemini ya asentados, la última pieza de la lista de "cosas para la v4" era mucho más pequeña en superficie, pero tocaba directamente el día a día de usar la app: perfiles de usuario. Guardar de un tirón la voz, la velocidad, el volumen y las preferencias de lectura, para compartir el ordenador con otra persona o para tener listas distintas configuraciones según el tipo de libro.

### La primera versión no era la buena

El primer diseño del panel en Ajustes → Perfiles de Usuario tenía botones separados: "Crear perfil con el estado actual de Lectura" y "Guardar estado actual en el perfil seleccionado". Para crear o actualizar un perfil había que ir primero a la pestaña Lectura a dejar puestas la voz, la velocidad y el volumen que se querían guardar, y aparte a Ajustes → Configuración General para los segundos de salto y la pausa entre fragmentos, y solo entonces volver a Perfiles a pulsar el botón de guardar.

Después de probarlo de verdad, la respuesta fue directa: demasiados pasos, demasiados saltos de foco entre pestañas para algo que debería sentirse simple. La petición fue clara — "que todo esté en la lista de perfiles y un botón para crear un nuevo perfil donde se puedan traer todos los ajustes necesarios [...] pulso Guardar perfil para que se guarde y se aplique directamente". El panel se rediseñó con un único formulario (voz, velocidad, volumen, segundos de salto y pausa, los cinco campos a la vez) que al guardar crea o actualiza el perfil, lo marca activo y lo aplica de inmediato, sin salir de Ajustes → Perfiles de Usuario para nada. Fue el mismo tipo de corrección de rumbo que ya pasó con el selector de voz del Creador de Audiolibros en la Fase 7: proponer algo, que el uso real lo tumbe, y reconstruir con lo aprendido.

### El atajo que casi colisiona

`Ctrl+Shift+P` parecía la elección obvia para alternar entre perfiles — es casi un estándar de facto en otras apps para "perfiles" o "paletas de comandos". Antes de que llegara a implementarse, surgió la duda correcta: "¿este atajo no lo uso ya para abrir la ventana de proyectos?". Sí, lo usaba. Un repaso completo de todos los atajos ya asignados en la app confirmó que `Ctrl+Shift+U` estaba libre, y se usó ese en su lugar. Un recordatorio de que "lo que hacen otras apps" no sustituye a comprobar lo que ya hace la propia.

### El mismo bug de `_`, otra vez

Este fue el momento más irónico de la fase. En la Fase 7, un `UnboundLocalError` sobre la propia función de traducir `_()` había costado una ronda entera de investigación: la costumbre de usar `_` como variable de descarte en desempaquetados de tupla, en un archivo que también usa `_` como el traductor de `gettext`. Se documentó la regla en `DEVELOPMENT.md` para que no volviera a pasar.

Volvió a pasar. Esta vez en el panel de Perfiles recién construido: `_, datos = gestor_perfiles.obtener_perfil_activo()`, seguido a las pocas líneas de `voz.hablar(_("Perfil activo: {nombre}").format(...))`. La app crasheó en cuanto se activaba un perfil, con `TypeError: 'str' object is not callable` en vez del `UnboundLocalError` de la vez anterior (la diferencia: esta vez la asignación a `_` iba antes de la llamada a `_("...")`, no después, así que el fallo se manifestó de otra forma, pero la causa de fondo es exactamente la misma). Se corrigió en todo el panel, y quedó anotado en `CLAUDE.md` y en `DEVELOPMENT.md` con las dos apariciones documentadas juntas, no solo una: si ha pasado dos veces en dos fases distintas, es un patrón a vigilar activamente en cualquier código nuevo, no un accidente aislado.

### Un primer paso hacia los tests

Junto con el panel se añadió `TestGestorPerfiles` a `tests/test_suite.py`: CRUD básico, alternancia circular entre perfiles, reasignación del perfil activo al eliminarlo, persistencia atómica. No es la "suite de tests automatizados" completa que llevaba pendiente desde la Fase 4 — sigue sin haber ninguna cobertura de la interfaz gráfica —, pero es el primer módulo del proyecto que nace con sus propios tests desde el primer commit, en vez de sumarlos después.

### Lo que se queda anotado, no resuelto, para la fase de estabilización

Al cerrar esta fase se revisó también, de forma externa, el estado general del proyecto: las librerías elegidas, la profundidad real de la accesibilidad, y dos puntos de mejora concretos. `requisitos.txt` ya existía y cubre las dependencias reales del proyecto, así que ese punto ya estaba resuelto. El otro punto sí es real: hay `except: pass` o `except Exception: pass` sin logging repartidos entre clientes de voz, motor e interfaz — código que esta fase no tocó y que no se puede validar sin NVDA ni wxPython instalados en el entorno de desarrollo actual. En vez de tocarlo de rondón dentro de la rama de Perfiles de usuario, queda anotado explícitamente aquí y en `DEVELOPMENT.md` como tarea pendiente para la fase de estabilización que viene después de la v4.0: la propia planificación de esta fase ya decía que, más allá de la v4.0, el foco del proyecto debía pasar de añadir funciones a pulir, estabilizar y dar soporte a quien use la app. Esta limpieza, y ampliar la cobertura de tests más allá de `gestor_perfiles.py`, son justo ese tipo de trabajo.

### El primer portable real: cuatro bugs que solo existían congelados

Con Perfiles ya terminado y aprobado, tocaba probar todo el ciclo de verdad: generar el `.zip` portable con `crear_portable.py` y usarlo en Windows, no solo el modo desarrollo con Python instalado. Y como suele pasar, el portable encontró errores que el modo desarrollo llevaba meses sin mostrar, porque solo existen cuando la app corre congelada con PyInstaller.

El más ruidoso: el anunciador de voz de las colas rápidas (`AnunciadorVoz`, pyttsx3) se quedaba completamente mudo en el `.exe`, tanto en el progreso de escaneo de Biblioteca como en cualquier otro sitio que lo usara. La causa no era velocidad ni una cola mal gestionada, como parecía a primera vista — cada anuncio lanzaba un proceso auxiliar con `sys.executable -c "código"`, y `sys.executable` dentro de un ejecutable PyInstaller ya no es un intérprete de Python real: es el propio `.exe` de la app, que no entiende `-c`. El proceso auxiliar fallaba en silencio en cada intento. Se corrigió con un modo de re-ejecución explícito: `iniciar_epub_tts.py` ahora intercepta `--hablar-interno <texto>` al arrancar, antes de crear la `wx.App`, y en el `.exe` congelado el propio `sys.executable` se relanza con ese flag en vez de intentar `-c`.

El segundo, más sutil: `Ctrl+I` (anunciar página) a veces caía en la pestaña equivocada. La causa era que varias pestañas registraban su propio acelerador local para la misma combinación además del despacho centralizado en `ventana_principal.py` — con dos tablas de aceleradores compitiendo por la misma tecla, cuál ganaba dependía de detalles de foco poco predecibles. Se centralizó del todo en la ventana principal y se quitaron los registros duplicados en `pestana_lectura.py` y `pestana_biblioteca.py`. De paso se hizo la misma limpieza preventiva en `Ctrl+O`, aunque ese no había dado síntomas todavía.

El tercero fue el que más despistó en las pruebas: el comprobador de actualizaciones ofrecía instalar versiones antiguas, o repetía la misma pregunta después de "actualizar". La causa, una vez encontrada, era ridículamente simple: `comprobador_actualizaciones.py` leía la versión local desde una ruta a la que le faltaba el segmento `recursos/`, así que nunca encontraba el `version.json` real y siempre asumía la versión `0.0.0` de fábrica. Cualquier versión remota parecía más nueva, incluida una v2.0 puesta a mano para probar. Corregida la ruta, el comprobador empezó a comparar versiones de verdad.

El cuarto fue de empaquetado: `accessible_output3` no llevaba hook propio de PyInstaller, así que el `.exe` no incluía todo lo necesario para hablarle al lector de pantalla activo. Se añadió `--collect-all=accessible_output3` a los argumentos de PyInstaller en `crear_portable.py`.

### Grabación de Fragmentos tenía el mismo problema de fondo que el escaneo de Biblioteca

Al revisar `pestana_grabacion.py` con el bug de `AnunciadorVoz` ya resuelto, apareció otro caso del mismo patrón: los anuncios de voz de la pestaña lanzaban `pyttsx3` directamente dentro de un hilo del propio proceso de la app, en vez de en un proceso auxiliar aparte. `pyttsx3` con el motor SAPI5 de Windows no tolera bien compartir el mismo proceso con wxPython — es la misma razón por la que `grabador_audio.py` ya usaba un proceso separado desde hace tiempo. Se sustituyó por el mismo `AnunciadorVoz` ya corregido, quitando el `threading.Thread` manual que envolvía la llamada porque `AnunciadorVoz.hablar()` ya es seguro para llamarse desde cualquier hilo.

### El actualizador automático, validado de extremo a extremo por fin

Con el bug de la ruta de `version.json` corregido, se pudo por fin probar en Windows real el mecanismo de la Fase C (`actualizador_descarga.py` + `bin/actualizador.exe`) con casos reales: instalación correcta, y confirmación de que la barra de progreso y los anuncios de voz llegaban a NVDA sin cortes ni solapamientos. El resultado fue bueno — "me lo han leído absolutamente todo" — así que se conectó el mecanismo ya validado al botón real de producción "Buscar actualizaciones ahora", sustituyendo el viejo "Script Clon" como ruta activa para la instalación (el Script Clon se mantiene aparte, sin usarse, como red de seguridad durante un tiempo antes de retirarlo del todo). El botón de prueba interno que solo servía para validar la descarga durante el desarrollo se retiró, porque ya cumplió su función. También se corrigió un `AttributeError` que habría hecho fallar la ruta de "actualización aceptada al arrancar la app": llamaba a un método que en realidad vive en `PanelGeneral`, no en `PestanaAjustes`.

Aparte, se probó el proceso de construir el propio portable: un `PermissionError` al borrar la carpeta anterior del build (resultó ser atributos de solo lectura en los archivos, no un bloqueo temporal) y los tres `.bat` fallando con "no encuentro el archivo" al lanzarse sin el directorio de trabajo correcto — les faltaba fijar su propio directorio antes de llamar a Python. Ambos, corregidos.

### Ampliando la búsqueda de bugs y los tests

Después de esta ronda de pruebas reales se hizo un repaso más amplio de todo el código en busca de patrones similares, y se ampliaron los tests automatizados con `TestComprobadorActualizaciones`, `TestGestorAtajos` y `TestDiccionarioPronunciacion` — de 106 a 126 tests en total. El barrido de `except: pass` sin logging, revisado con más detalle esta vez, resultó tener 65 apariciones en unos 20 archivos; la mayoría son patrones defensivos deliberados y no bugs escondidos, así que la limpieza sigue tal y como se planificó: pendiente para la fase de estabilización, no para esta rama.

## Fase 9: v4.1.0 — Estabilización, rendimiento y pruebas automatizadas (julio 2026)

Con la v4.0 congelada, esta fase no añadió ni una sola función nueva: fue exclusivamente pulir lo que ya existía, tal y como quedó anotado al cerrar la Fase 8.

**Auditoría completa de `except: pass` sin logging.** El barrido de la Fase 8 había contado 65 apariciones "a ojo" en unos 20 archivos; un recorrido con AST más riguroso sobre todo `app/`, los dos ejecutables auxiliares (`auxiliar_sapi32.py`, `auxiliar_actualizador.py`) e `iniciar_epub_tts.py` encontró 359 bloques `except` en total, de los cuales 174 en 31 archivos capturaban el error sin dejar ningún rastro útil (`pass`, `print()` suelto, o un `return`/reasignación silenciosa). Se corrigieron todos: la mayoría con `logger.exception(...)` cuando el fallo es real e inesperado, `logger.debug()`/`logger.warning()` cuando es un caso esperado (widget de wx ya destruido, dependencia opcional no instalada, archivo de configuración que aún no existe), y sustituyendo los `print()` sueltos que quedaban de fases anteriores por el logger central del módulo correspondiente. Los dos procesos auxiliares, que no tienen logger central de `app/` por diseño (se comunican por IPC o corren fuera del ciclo de vida de wx), quedaron reportando cada fallo por su canal ya existente (`_log()`/`_enviar()` en `auxiliar_actualizador.py`) o por un `_log_error()` nuevo a stderr en `auxiliar_sapi32.py`, consistente con no tener consola visible en producción. Una segunda verificación posterior, también con AST, confirmó cero bloques pendientes en el alcance auditado. Se dejaron intactos, con justificación explícita en el propio código, los `except queue.Empty: break` (vaciado normal de una cola) y `except EscaneoCancelado` (cancelación cooperativa del usuario, no un error).

**Ampliación de tests: de 126 a 169.** Se añadió `TestGestorBiblioteca` (33 tests: CRUD de libros, banderas mutuamente excluyentes, categorías con jerarquía padre-hijo, etiquetas/sagas, exportaciones pendientes, y una regresión explícita sobre la migración de esquema — crear el gestor dos veces seguidas no debe fallar por "la columna ya existe") y `TestPersistenciaJsonAtomica` (3 tests sobre `gestor_perfiles.py`: el archivo final queda con el JSON esperado, no queda ningún `.tmp` residual tras una escritura exitosa, y una interrupción simulada a mitad de escritura no corrompe el archivo anterior).

**Rendimiento: cinco correcciones reales, sin cambiar comportamiento.** Una revisión dirigida (no especulativa: solo patrones que de verdad se ejecutan en un flujo de uso normal) encontró y corrigió:
- `_aplicar_reglas_de_biblioteca()` en `limpiador_lectura.py` abría una conexión SQLite nueva y repetía las mismas dos consultas en cada página de un PDF (y cada fragmento de un EPUB troceado) para el mismo libro. Ahora las reglas se cachean compiladas por `ruta_libro`, con `recargar_reglas_biblioteca()` invalidando la caché al editar/eliminar reglas desde Ajustes.
- `check_voces` en Grabación de Fragmentos insertaba fila a fila sin `Freeze()`/`Thaw()`, a diferencia de `selector_voz_compartido.py` para el mismo tipo de lista.
- El índice de capítulos del Troceador de EPUB, la lista de atajos y la de perfiles en Ajustes, y el árbol de proyectos (`TreeCtrl`) tenían el mismo problema: inserciones sin `Freeze`/`Thaw`. Los cuatro quedaron envueltos con `try/finally` para garantizar el `Thaw()` incluso si algo falla a mitad.
- `DiccionarioPronunciacion.aplicar()` recorría todas las reglas del usuario y probaba un `re.sub` por cada una aunque no apareciera en el texto; ahora se salta con un `in` barato antes del `re.sub`, sin cambiar el resultado final.

**`requisitos.txt`:** se retiró `ftfy`, que nunca llegó a integrarse en el código (solo se había mencionado en documentos de planificación de la Fase 7) — el resto del archivo ya reflejaba con exactitud las dependencias reales.

Con esto se cierra por completo el desarrollo de Epub TTS Accesible: la v4.1.0 queda como la versión final, y el proyecto pasa a distribución. Queda fuera a propósito, como red de seguridad, el bloque `ANCLAJE_INICIO: ACTUALIZADOR_SCRIPT_CLON` en `pestana_ajustes.py` — se retirará una vez confirmadas dos o tres actualizaciones reales seguidas sin sobresaltos con el actualizador de la Fase C.

Antes de dar la fase por cerrada del todo repasé también `crear_portable.py` con ojo crítico, ya sin código nuevo que probar, solo puliendo el propio empaquetado: `novedades.txt` ya no va en una carpeta `documentos/` para un único archivo, se copia directo a la raíz del portable junto a `ayuda.html` y `epubtts.exe`; `registros/` y `registros/errores/` se crean de fábrica en el propio `.zip`, en vez de esperar al primer arranque real; y el script avisa si detecta que faltan `bin/ffmpeg.exe` o `bin/auxiliar_sapi32.exe`, para no generar nunca un portable incompleto sin darme cuenta. Con eso ya cerrado, subí la versión oficial con `subir_version.py minor`: 4.0.0 → 4.1.0, confirmada en `recursos/version.json`.

### Última pasada: leer todo el código de nuevo, buscando lo que no se ve al usar la app

Con todo lo demás ya cerrado, hice una última ronda antes de dar la v4.1.0 por terminada del todo: releer el proyecto entero, módulo a módulo, buscando fallos que ninguna prueba manual iba a encontrar nunca — porque solo pasan en una ventana de tiempo muy concreta (la app cerrándose justo mientras guarda algo, dos acciones casi simultáneas, un hilo de fondo que sigue vivo después de cerrar la ventana que lo lanzó). Encontré 23 casos reales, y los corregí todos.

Los que más me preocuparon: `gestor_proyectos.py` y la parte de `config_rutas.py` que guarda las claves de API no escribían de forma atómica (a diferencia de `gestor_perfiles.py`, que sí seguía el patrón desde el principio) — un corte justo a mitad de guardado podía dejar el archivo corrupto y perder toda la jerarquía de proyectos, o todas las claves guardadas, sin ningún aviso. Corregido con el mismo patrón tmp+`os.replace()` que ya usaba el resto del proyecto. Y en la exportación por capítulos del Creador de Audiolibros, la comprobación de cuota de la Fase 1 no tenía en cuenta lo que los capítulos anteriores del mismo lote ya iban a gastar — varios capítulos que individualmente cabían en el límite, juntos podían superarlo con creces, justo lo que el "Escudo de Presupuesto" estaba pensado para impedir.

También encontré el mismo patrón de crash repetido en tres sitios distintos (el Asistente de Biblioteca, el divisor de EPUB, el diálogo de proveedor alternativo): cerrar la ventana mientras un hilo de fondo seguía trabajando hacía que, al terminar ese hilo, intentara tocar controles ya destruidos. Los tres se corrigieron con el mismo patrón (una bandera `_cerrado` comprobada al principio de cada callback diferido) en vez de arreglar cada uno por separado con una solución distinta.

Del lado de las voces de nube: Azure, Polly y ElevenLabs no troceaban el texto largo antes de enviarlo a la API (Deepgram sí lo hacía desde hace tiempo), así que un párrafo largo podía hacer fallar la síntesis a mitad de la lectura. Y la caché de audio de los cuatro clientes de nube se indexaba solo por texto, no por voz — al cambiar de voz y repetir un texto ya cacheado, sonaba la voz vieja en vez de la nueva. Los cuatro clientes quedaron con el mismo comportamiento consistente.

Con esto sí, la v4.1.0 queda cerrada del todo.

— Dayanna Parson, julio de 2026