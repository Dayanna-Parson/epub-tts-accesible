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