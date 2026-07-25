# El origen de la app: conversación con Gemini

Este documento era originalmente la transcripción completa (casi 6000 líneas) de la conversación
en la que le planteé por primera vez a Gemini la idea de esta aplicación, antes de escribir una
sola línea de código. La resumo aquí para que quede el hilo real de cómo surgió la idea, sin la
longitud del original.

---

**Yo:** ¿Con Python puedo hacer una aplicación como Arroba Voice para Android, pero para Windows?
Que use las voces de Azure, Polly y ElevenLabs a través de sus claves API, que permita insertar
etiquetas en el texto para cambiar de voz, con una casilla para dividir o no esas etiquetas, y que
exporte a WAV o MP3, o incluso grabe. Mira esto: `{{@+adam=com.hyperionics.msaz,es_ES,en-US-AdamMultilingualNeural}}` (y le pegué el resto de mis definiciones de voz de Arroba Voice).

**Gemini:** Sí, es totalmente factible con Python. Bibliotecas como `requests` o `httpx` para las
APIs, expresiones regulares para analizar las etiquetas, `pydub`/`soundfile` para el audio, y una
interfaz gráfica con Tkinter, PyQt o Kivy para Windows.

**Yo:** Obviamente no puedo usar esas mismas etiquetas porque son de la aplicación que uso, y no le
quiero quitar mérito a quien la hizo.

**Gemini:** No se trata de replicar las etiquetas de Arroba Voice, sino de inspirarme en su
funcionalidad para diseñar mi propio sistema. Por ejemplo, algo como `[azure:adam:es-ES]`.

**Yo:** ¿Y se podría hacer que la voz cambie al insertar una etiqueta, sin importar el proveedor?

Le mostré entonces mi propio formato ya elaborado: `{{@+narr=com.hyperionics.msaz,es_ES,es-ES-ElviraNeural}}`, `{{@+james=...}}`, `{{@+lara=...}}`, y un fragmento narrativo real (un caso de mi
personaje detective Lara Hallman) usando `{{@narr}}`, `{{@james}}`, `{{@lara}}` para marcar quién
habla en cada línea.

**Gemini:** Con un diccionario `definiciones_de_voz` en Python (proveedor, región, voz) y expresiones
regulares para detectar `{{@nombre}}` en el texto, es perfectamente replicable. Y sí, el mismo
sistema puede extenderse a ElevenLabs añadiendo el `voice_id`.

**Yo:** Se me ocurren dos funciones más: casillas junto a cada voz para marcarlas como favoritas, y
un buscador. Y que el botón de grabar se comporte distinto según si la casilla de dividir etiquetas
está marcada o no. Y una sección de configuración unificada por proveedor. Quiero que tenga interfaz
gráfica, la quiero usar así.

**Gemini:** Todo eso es alcanzable: una lista de voces con checkbox de favorita, un campo de
búsqueda que filtre por nombre/proveedor/región, y una pestaña de ajustes con las claves API y los
parámetros propios de cada proveedor (estilos y roles en Azure, motor estándar/neuronal en Polly,
estabilidad y similitud en ElevenLabs).

**Yo:** Ten en cuenta que lo haré desde la accesibilidad, soy ciega. Uso NVDA y JAWS.

**Gemini:** No existe una biblioteca que haga una GUI accesible por arte de magia, pero sí buenas
prácticas: navegación completa por teclado, etiquetas descriptivas asociadas a cada control, orden
de tabulación lógico, comunicar los cambios de estado (una casilla marcada/desmarcada) a los
lectores de pantalla, y sobre todo, probar constantemente con NVDA y JAWS mientras se construye.

**Yo:** Creo que lo más complicado para mí, siendo ciega total, va a ser situar los elementos en la
interfaz.

**Gemini:** Piénsalo no como "poner algo en un lugar visual", sino como construir una estructura
lógica y secuencial que un lector de pantalla pueda recorrer con Tab de forma predecible. Con
layouts como `grid()` en vez de posicionamiento absoluto, y agrupando controles relacionados, el
orden de navegación puede tener sentido aunque tú no lo veas.

**Yo:** ¿Empiezo directamente con este proyecto grande, o con algo pequeño primero?

**Gemini:** Dado que no tienes experiencia previa programando, mejor ir poco a poco: fundamentos de
Python, luego una interfaz mínima con Tkinter, y dejar la integración con las voces (Azure, Polly,
ElevenLabs) para más adelante, cuando ya tengas una base sólida.

**Yo:** Sí, quiero ir muy poco a poco. El tema de las voces lo dejo para cuando esté seguro de que
esto me gusta.

También hablamos de organizar los ajustes como un árbol con menús desplegables (General, Voces,
Audio, API) en vez de una pantalla única — la idea que terminó siendo el árbol de navegación de la
pestaña Ajustes en la versión 2.0. Y en otro tramo de la conversación exploramos, solo como
posibilidad futura, un sistema de voces clonadas con OpenVoice: nunca se implementó, y quedó
descartado explícitamente más adelante (ver `GUIA_TECNICA.md`, sección "Qué no forma parte del
proyecto").

---

## Nota histórica — junio 2026

La aplicación fue publicada y ha alcanzado tres versiones estables:

**Versión 1.0.0 (marzo 2026):**
Primera versión pública. Modo lectura, voces de Azure y ElevenLabs, favoritos, filtros y control de cuota.

**Versión 1.1.0 (abril 2026):**
Los tres bloques pendientes completados: Amazon Polly, sistema de etiquetas {{@voz}} y Modo Grabación. Exportación MP3 a 44 100 Hz, deslizadores de velocidad y volumen, y descarga automática de actualizaciones.

**Versión 1.2.0 (junio 2026):**
Deepgram Aura-2 integrado como motor de síntesis recomendado. Diccionario de pronunciación, historial de voces nuevas, control de cuota extendido a Deepgram, lectura continua sin pausas entre fragmentos.

**Versión 2.0.0:**
Gestor de Proyectos, divisor de EPUB integrado, 12 sonidos contextuales, voces SAPI5 de 32 bits (Eloquence, RealSpeak), árbol de navegación en Ajustes y actualizaciones automáticas completas.

**Versión 3.0.0 (julio 2026):**
Pestaña Biblioteca con soporte de PDF, Creador de Audiolibros con exportación en paralelo, y un Asistente de Biblioteca con Google Gemini — el mismo tipo de conversación que dio origen a este documento, ahora integrado dentro de la propia aplicación para hablar sobre mis libros.
