# CLAUDE.md — Epub TTS Accesible

Léelo entero antes de tocar nada. Estas reglas no son sugerencias.

---

## Identidad del proyecto

**Epub TTS Accesible** es una aplicación de escritorio para Windows que convierte libros EPUB y PDF en audiolibros multivoz con voces neuronales de nube (Azure, Amazon Polly, Deepgram, ElevenLabs) y SAPI5 local. Está diseñada por y para personas ciegas, con accesibilidad NVDA como requisito no negociable.

- Desarrolladora: Dayanna Parson (TifloTutos · tiflotutos.com)
- Versión actual: 3.0.0
- Python 3.12+ · wxPython 4.2+ · Windows como plataforma principal

---

## Reglas absolutas de colaboración

### Sin rastro de conversaciones
No incluyas en el código ni en los comentarios ninguna referencia a conversaciones anteriores, sugerencias de IA, sesiones de trabajo, ni nada que no sea parte de la lógica propia de la aplicación. El código debe parecer escrito íntegramente por la desarrolladora.

### Todo en español
Variables, funciones, clases, comentarios, mensajes de log, cadenas de texto de interfaz. Todo en español. Es una decisión consciente de la autora y no se negocia.

### Sistema de ANCLAJES obligatorio
Todo bloque de código que pueda necesitar reemplazarse en el futuro debe delimitarse con comentarios de anclaje:

```python
# ANCLAJE_INICIO: NOMBRE_DEL_BLOQUE
# ... código ...
# ANCLAJE_FIN: NOMBRE_DEL_BLOQUE
```

Cuando entregues código nuevo, indica siempre qué bloque ANCLAJE reemplaza. Nunca entregues un archivo entero sin contexto. Si el bloque es nuevo, ponle nombre descriptivo en mayúsculas con guiones bajos.

### Cambios quirúrgicos
Nunca reescribas un archivo completo si solo hay que modificar un bloque. Entrega únicamente el bloque ANCLAJE afectado y el contexto mínimo necesario para ubicarlo. Menos tokens, menos riesgo de romper lo que ya funciona.

---

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Interfaz | wxPython 4.2+ (controles nativos Windows, accesibles por defecto) |
| Lenguaje | Python 3.12+ |
| Audio | FFmpeg portable en `/bin/` |
| HTTP síncrono | `requests` |
| HTTP asíncrono (preparado) | `httpx` |
| EPUB | EbookLib + BeautifulSoup4 |
| Sonidos del sistema | `wx.adv.Sound` + `winsound` (fallback) |
| TTS local | SAPI5 64 bits (`cliente_sapi5.py`) + SAPI5 32 bits vía proceso puente (`cliente_sapi32_bridge.py`) |
| TTS nube | Azure Neural, Amazon Polly, Deepgram Aura-2, ElevenLabs |
| Asistente de Biblioteca | Google Gemini (`cliente_gemini.py`), REST puro con `requests`, sin SDK |
| Anuncios de interfaz para NVDA | `accessible_output3` (`anunciador_lector.py`) — habla directo al lector de pantalla activo |
| Voz de estado en colas rápidas | `pyttsx3` (`anunciador_voz.py`) — solo donde puede llegar una ráfaga de anuncios seguidos (ver más abajo) |
| Logs | `logging` + `RotatingFileHandler` (2 MB, 3 backups) |

No añadas dependencias sin justificación explícita. Cada librería nueva es un punto de rotura potencial en la portabilidad.

---

## Estructura de archivos

```
app/
├── interfaz/
│   ├── ventana_principal.py      # Ventana raíz. Notebook de pestañas. Menú contextual.
│   ├── pestana_biblioteca.py     # Biblioteca: importar EPUB/PDF, géneros, sagas, buscador
│   ├── pestana_lectura.py        # Modo Lectura: EPUB/PDF + TTS + marcadores
│   ├── pestana_creador_audiolibros.py  # Creador de Audiolibros: exportación completa/por capítulos
│   ├── pestana_grabacion.py      # Grabación de Fragmentos: etiquetas multivoz + exportación
│   ├── pestana_ajustes.py        # Ajustes: claves API, voces, atajos, cuota
│   ├── ventana_proyectos.py      # Gestor de proyectos de Grabación (ventana independiente, no modal)
│   ├── selector_voz_compartido.py  # ListaVocesCheck + PanelProveedorIA: catálogo de voces reutilizable
│   ├── dialogo_proveedor_alternativo.py  # Cuota insuficiente al exportar: cambia de proveedor o voz local
│   ├── dialogo_troceador.py      # División de EPUB por capítulos
│   ├── dialogo_voces_nuevas.py   # Notificación de voces nuevas
│   ├── dialogo_novedades.py      # Novedades de versión
│   ├── dialogo_asistente_biblioteca.py  # Chat accesible con el Asistente de Biblioteca (Gemini)
│   ├── dialogos.py               # Diálogos compartidos: marcadores, confirmaciones
│   └── ui_recursos.py            # Helper para iconos con fallback a wx.ArtProvider
├── motor/
│   ├── gestor_biblioteca.py      # CRUD sobre biblioteca.db: libros, categorías, etiquetas, pendientes
│   ├── escaner_biblioteca.py     # Escaneo de carpetas en hilo de fondo, extracción de metadatos
│   ├── renombrador_biblioteca.py # Renombrado de archivos según metadatos reales
│   ├── gestor_epub.py            # Abre EPUB, limpia HTML, reconstruye índice
│   ├── gestor_pdf.py             # Extrae texto/índice de PDF (fitz) para Lectura, misma forma que gestor_epub
│   ├── gestor_proyectos.py       # Lógica de proyectos de Grabación. Persistencia en proyectos.json
│   ├── gestor_atajos.py          # Atajos de teclado configurables
│   ├── gestor_chat_biblioteca.py     # Historial de conversación del Asistente de Biblioteca
│   ├── gestor_prompts_asistente.py   # Plantillas de prompt de sistema del Asistente (un .txt por plantilla)
│   ├── gestor_backups.py         # Copias rotativas de proyectos.json y biblioteca.db, solo si cambiaron
│   ├── anunciador_lector.py      # accessible_output3: anuncios de interfaz al lector de pantalla activo
│   ├── anunciador_voz.py         # pyttsx3: cola de voz para ráfagas rápidas (progreso de escaneo)
│   ├── grabador_audio.py         # Grabación silenciosa a archivo: fragmentos y audiolibros completos
│   ├── procesador_etiquetas.py   # Parsea {{@voz}} y fragmenta para grabación
│   ├── reproductor_voz.py        # Cola TTS asíncrona interactiva. Orquesta todos los motores.
│   ├── reproductor_sonidos.py    # 14 efectos contextuales (incluye bucle). Caché en RAM.
│   ├── cliente_nube_voces.py     # Descarga listas de voces desde cada API
│   ├── verificador_voces_nuevas.py  # Detecta voces nuevas con cooldown de 24h
│   ├── comprobador_actualizaciones.py  # Versioning semver contra GitHub
│   ├── actualizador_descarga.py  # Fase C: descarga y verifica la versión nueva en temp/actualizacion/
│   ├── control_cuota.py          # Contadores mensuales por proveedor con autoreset + coste estimado
│   ├── troceador_epub.py         # Divide EPUB por anclas HTML
│   ├── troceador_pdf.py          # Divide PDF por su índice de contenidos (o por página si no tiene)
│   ├── limpiador_lectura.py      # Limpieza de texto para TTS
│   ├── limpiador_markdown_chat.py    # Limpia el markdown de las respuestas de Gemini para lectura en voz
│   ├── diccionario_pronunciacion.py  # Sustituciones fonéticas locales para todos los motores
│   └── gestor_idioma.py          # i18n con gettext: detecta/aplica el idioma de interfaz, expone traducir()/_()
├── servicios/
│   ├── cliente_azure.py          # Azure Neural TTS. SSML con xml.sax.saxutils.
│   ├── cliente_polly.py          # Amazon Polly. Motor automático standard/neural/generative.
│   ├── cliente_eleven.py         # ElevenLabs. Multilingüe. Streaming.
│   ├── cliente_deepgram.py       # Deepgram Aura-2. REST puro. Pay-as-you-go. Caché LRU.
│   ├── cliente_sapi5.py          # SAPI5 64 bits. Fallback siempre disponible.
│   ├── cliente_sapi32_bridge.py  # SAPI5 32 bits (Eloquence, RealSpeak). Proceso puente.
│   └── cliente_gemini.py         # Asistente de Biblioteca: listar_modelos()/enviar_mensaje(), Google Search Grounding
└── config_rutas.py               # Rutas absolutas. cargar_claves() / guardar_claves().

auxiliar_sapi32.py                # Proceso auxiliar de 32 bits. Se compila a bin/auxiliar_sapi32.exe.
auxiliar_actualizador.py           # Fase C: instalador auxiliar de actualizaciones. Se compila a bin/actualizador.exe
                                   # (automáticamente, desde crear_portable.py — a diferencia de auxiliar_sapi32.exe).
herramientas/
└── compilar_i18n.py               # Compilador propio .po → .mo (sin depender de msgfmt/gettext del sistema).
locale/
├── epub_tts.pot                   # Plantilla: un msgid por cada cadena envuelta en _() en app/.
├── es/LC_MESSAGES/epub_tts.po(.mo)  # Catálogo español. msgstr siempre igual al msgid (nunca vacío).
└── en/LC_MESSAGES/epub_tts.po(.mo)  # Catálogo inglés, con traducción completa.
winget/                            # Manifiestos de Winget (version/installer/locale.yaml + LEEME.txt),
                                   # provisionales: ver LEEME.txt antes de tocarlos.
GUIA_SCRIPTS.md                    # Cuándo y cómo usar subir_version.py, crear_portable.py,
                                   # compilar_i18n.py y cuándo enviar winget/ a microsoft/winget-pkgs.
```

Archivos de configuración (en `/configuraciones/`):

| Archivo | Contenido | En .gitignore |
|---|---|---|
| `claves_api.json` | Claves de Azure, Polly, ElevenLabs, Deepgram | Sí |
| `ajustes.json` | Velocidad, volumen, tiempos, favoritas, límites de cuota | No |
| `biblioteca.db` | SQLite: libros, categorías, etiquetas/sagas, exportaciones pendientes | Sí |
| `proyectos.json` | Jerarquía completa de proyectos de Grabación de Fragmentos | No |
| `pronunciacion.json` | Reglas del diccionario de pronunciación | No |
| `voces_conocidas.json` | IDs de voces ya vistas (historial para filtro «solo nuevas») | No |
| `backups_proyectos/` | Copias rotativas (últimas 5) de `proyectos.json` | Sí |
| `backups_biblioteca/` | Copias rotativas (últimas 5) de `biblioteca.db` | Sí |
| `asistente_biblioteca/plantillas/*.txt` | Plantillas de prompt del Asistente, una por archivo | Sí |
| `asistente_biblioteca/activo.json` | Nombre de la plantilla activa | Sí |
| `asistente_biblioteca/chat_biblioteca.json` | Historial de conversación del Asistente | Sí |

### Asistente de Biblioteca (Gemini)

- Atajo global: `Ctrl+Shift+B`, desde cualquier pestaña (`ATAJO_ASISTENTE_BIBLIOTECA` en `gestor_atajos.py`). También accesible desde el menú contextual de cada pestaña.
- Con un libro/saga/categoría seleccionados en Biblioteca, el chat precarga ese contexto; en modo general recibe un resumen agregado (géneros/autores/sagas más frecuentes) **más el catálogo completo** de título/autor/saga de toda la biblioteca (`GestorBiblioteca.catalogo_para_asistente()`), calculado en vivo en cada apertura — sin caché ni detección de cambios, porque el coste de recalcularlo es insignificante frente al de mantener una caché sincronizada.
- Las llamadas a Gemini se hacen siempre en hilo secundario; la respuesta llega por `wx.CallAfter`. `thinking.wav` suena en bucle mientras se espera (`iniciar_bucle`/`detener_bucle` de `reproductor_sonidos.py`).
- Plantillas de prompt de sistema: se gestionan por completo en Ajustes → Asistente de Biblioteca (crear, editar, borrar, botón "Abrir carpeta de plantillas"), no en el propio chat, que solo tiene el combo de selección rápida. Cada plantilla es un archivo `.txt` independiente en `configuraciones/asistente_biblioteca/plantillas/`, editable con cualquier editor de texto; la carpeta se reescanea cada vez que se entra en ese nodo del árbol de Ajustes.
- Temperatura (deslizador de 0 a 100 en Ajustes → Credenciales y API Keys → Google Gemini, equivalente a 0.0–1.0 al guardarse) y modelo (automático o uno concreto, con botón para refrescar la lista real de la cuenta) son configurables; Google Search Grounding se activa para fundamentar recomendaciones en fuentes reales. La escala del deslizador es 0-100, no 0.0-1.0: un `wx.Slider` en Windows expone a NVDA su posición como porcentaje del rango, así que con un rango 0-10 se anunciaba el porcentaje ("30, 40...") en vez del valor real — con el rango ya en 0-100 coinciden. El número que anuncia NVDA es literalmente la temperatura real de Gemini multiplicada por 100: si el deslizador dice "30", la temperatura que se guarda y se envía a la API es 0.3; si dice "40", es 0.4 (el valor de fábrica). No hay redondeo raro ni otra escala escondida — es una conversión directa (÷100 al guardar, ×100 al mostrar).

### Voces locales: dos proveedores

- `local` → `cliente_sapi5.py` (64 bits, siempre disponible)
- `local_32` → `cliente_sapi32_bridge.py` (32 bits vía proceso puente, requiere `bin/auxiliar_sapi32.exe`)

El campo `proveedor_id` de cada voz indica cuál de los dos usa. El reproductor enruta automáticamente. Si el puente no está disponible, las voces `local_32` no aparecen en la lista.

---

## Reglas críticas de arquitectura

### Internacionalización (i18n): toda cadena nueva de interfaz va envuelta en `_()`

Desde la Fase 7, la interfaz soporta español e inglés mediante `gettext` (librería estándar). Cualquier código nuevo que muestre texto al usuario o lo diga por voz (NVDA, `pyttsx3`) debe seguir esta regla, sin excepción:

- Importa la función de traducción explícitamente en cada módulo, nunca por inyección en `builtins`:
  ```python
  from app.motor.gestor_idioma import traducir as _
  ```
- Envuelve toda cadena visible/audible: labels, títulos de diálogo, ítems de menú, `wx.MessageBox`, `SetToolTip`, `voz.hablar()`, `anunciador_voz`, etc.
- **Prohibido** interpolar con f-string dentro de `_(...)`. Usa siempre `.format()` con marcadores nombrados, después de traducir:
  ```python
  _("Se ha borrado {cantidad} elemento(s).").format(cantidad=n)   # correcto
  _(f"Se ha borrado {n} elemento(s).")                             # PROHIBIDO
  ```
- **Nunca envuelvas** una cadena cuyo valor literal se compare, persista o use para lógica de programa: claves de `dict`/JSON, ids de proveedor, rutas de archivo, constantes técnicas, ni texto de menú/acelerador que la propia app lea de vuelta con `GetStringSelection()`/`GetItemText()` para decidir algo. Traducir esas rompería la lógica en cuanto el idioma activo no fuera español.
- Cada cadena nueva se añade como `msgid` en `locale/epub_tts.pot`, con `msgstr` igual al `msgid` en `locale/es/LC_MESSAGES/epub_tts.po` (nunca vacío) y con su traducción real en `locale/en/LC_MESSAGES/epub_tts.po`.
- Tras tocar cualquier `.po`, hay que recompilar los `.mo` con `python herramientas/compilar_i18n.py` antes de dar el cambio por terminado — la app carga el `.mo` directamente, no el `.po`.

### Rutas: siempre absolutas
Nunca uses rutas relativas. Usa siempre `RAIZ` de `config_rutas.py` como base:

```python
from app.config_rutas import RAIZ
ruta = os.path.join(RAIZ, "configuraciones", "ajustes.json")
```

### Hilos: wxPython no es thread-safe
Toda actualización de UI ocurre en el hilo principal. Si estás en un hilo secundario, usa siempre `wx.CallAfter`:

```python
def _hilo_trabajo(self):
    resultado = self._procesar()          # trabajo pesado en hilo secundario
    wx.CallAfter(self._actualizar_ui, resultado)  # UI siempre en hilo principal
```

No actualices controles wx directamente desde hilos secundarios. Produce crashes impredecibles con NVDA activo.

### Foco de NVDA: diferir cargas pesadas
Al cambiar de pestaña, si hay carga de datos, difiere siempre con `wx.CallAfter`:

```python
def _al_activar_pestana(self, evento):
    wx.CallAfter(self._cargar_datos_pesados)
    evento.Skip()
```

Así NVDA anuncia la pestaña primero, y la carga llega después.

### Listas: Freeze/Thaw para inserciones masivas
```python
self.lista.Freeze()
for item in items:
    self.lista.Append(item)
self.lista.Thaw()
```

### Sonidos: solo desde el hilo principal
`wx.adv.Sound.Play()` solo puede llamarse desde el hilo principal. Desde hilos secundarios:
```python
wx.CallAfter(reproducir, NOMBRE_SONIDO)
```

### Claves API: solo a través de config_rutas
Nunca accedas a `claves_api.json` directamente. Usa siempre:
```python
from app.config_rutas import cargar_claves, guardar_claves
```

### Escritura JSON: siempre atómica
Primero escribe a un archivo temporal, luego renombra sobre el destino. Evita archivos corruptos si la app se cierra a medias.

### Errores: nunca silenciosos
Prohibido `except: pass` o `except Exception: pass` sin logging. Mínimo:
```python
logger.exception("contexto descriptivo del error")
```

### Anuncios de interfaz: `accessible_output3`, no el patrón `_anunciador`

El patrón antiguo (un `wx.TextCtrl` oculto de 1×1 px que recibía el foco un instante para forzar la verbalización) se retiró de toda la aplicación. Hacía que NVDA anunciara el rol del control oculto ("edición, solo lectura") en cada aviso, como si saltara una ventana flotante — molesto en secuencias con varios anuncios seguidos (el chat del Asistente de Biblioteca fue el caso que lo dejó en evidencia).

En su lugar, `app/motor/anunciador_lector.py` habla directo al lector de pantalla activo con `accessible_output3`, sin mover el foco ni simular controles:

```python
from app.motor import anunciador_lector as voz
voz.hablar("Guardado.")
```

Es perezoso y a prueba de fallos: si la librería no está instalada o no hay ningún lector de pantalla en ejecución, `hablar()` no hace nada (ni lanza excepción). Se usa en Ctrl+I (anunciar página), Ctrl+S en Ajustes, el chat del Asistente de Biblioteca y en general en cualquier punto donde antes se habría usado `_anunciador` o donde `SetLabel()` no activa el evento de accesibilidad.

**Excepción — `pyttsx3` en secuencias rápidas:** cuando pueden llegar varios anuncios seguidos muy rápido (por ejemplo, el progreso de escanear una carpeta con cientos de libros), `accessible_output3` los encolaría todos y NVDA acabaría leyendo un progreso desfasado. Para esos casos concretos se mantiene `app/motor/anunciador_voz.py` (`AnunciadorVoz`, pyttsx3): descarta los anuncios intermedios y solo dice el más reciente. Se usa hoy en el progreso de escaneo de Biblioteca y en la ventana de gestión de Proyectos — no lo uses para anuncios puntuales, solo para bucles de progreso.

---

## Accesibilidad NVDA: checklist obligatorio

Antes de dar cualquier cambio de interfaz por terminado, verificar:

1. ¿El foco llega a donde debe al cambiar de pestaña?
2. ¿Los diálogos devuelven el foco al cerrarse?
3. ¿Las casillas de verificación anuncian "marcado/desmarcado" al navegar con flechas?
4. ¿Los sonidos se reproducen sin superponer la voz de NVDA?
5. ¿El árbol de proyectos anuncia nombre, nivel y estado correctamente?

Si algo de esto falla tras un cambio, es un bug crítico, no cosmético.

**Reglas de UX accesible:**
- Los deslizadores solo exponen el valor actual a la API de accesibilidad (no la escala completa). Pasos de 1 (flechas) y 5 (RePág/AvPág) en lectura; igual en grabación.
- `Control + P` es el comando universal de reproducción. Prohibido usar la tecla `Espacio` para evitar conflictos de foco con NVDA.
- `Control + O` es el comando universal de apertura (contextual según pestaña activa).
- Usar siempre "Retroceder/Avanzar" en lugar de "Atrás/Adelante".

---

## Motor de sonidos

14 constantes disponibles en `reproductor_sonidos.py`:
```python
APP_READY, REC_START, REC_END, PROGRESS, LIST_NAV,
MOVE_UP, MOVE_DOWN, OPEN_FOLDER, SUCCESS, CLICK, ERROR, CLEAR,
THINKING, PAGE_SCROLLED
```

Los `.wav` viven en `/recursos/sonidos/` a 16-bit, 44100 Hz. Si falta alguno, falla silenciosamente (log WARNING, sin crash).

Inicialización en dos fases: `_precargar_rutas()` al importar (sin wx.App), `_inicializar_wx()` en el primer `reproducir()` (ya con wx.App activo).

`THINKING` (`thinking.wav`) se reproduce en bucle con `iniciar_bucle()`/`detener_bucle()` mientras el Asistente de Biblioteca espera respuesta de Gemini. `PAGE_SCROLLED` (`page_scrolled.wav`) suena en Lectura al cruzar el límite de una página virtual, tanto navegando con flechas como durante la lectura continua con cualquier motor (estilo Bookworm).

Ajustes → Efectos de Sonido tiene una casilla global (`sonidos_habilitados`/`fijar_sonidos_habilitados()`) para silenciar todos los efectos, y un selector con botón para activar/desactivar un efecto concreto (`sonido_habilitado()`/`fijar_sonido_habilitado()`, persistido en `ajustes.json` como `sonidos_deshabilitados`) además de un botón "Probar sonido" (`forzar=True`) que ignora ambas preferencias.

---

## Estándar de exportación de audio

Todos los MP3 generados se normalizan a **44 100 Hz mono, 320 kbps**. Es el estándar para compatibilidad con proyectos de edición en Reaper y otros DAW.

Las etiquetas de personaje siguen el formato `{{@nombre}}`. El texto tras cada etiqueta se envía a la voz asignada. Ejemplo: `{{@nar}}Había una vez...{{@james}}¡Buenos días!`

En modo "Dividir por etiquetas", los archivos se nombran `1. Narr.mp3`, `2. James.mp3` (no `001_narr.mp3`).

Los audiolibros generados desde el Creador de Audiolibros van en `Grabaciones_Epub-TTS/Audiolibros/<Título>/` (o `Audiolibros/<Saga>/<Título>/` si el libro tiene alguna etiqueta en Biblioteca), separados de las carpetas de Grabación de Fragmentos. En modo "Libro completo" el archivo es `<Título>.mp3`; en "Por capítulos", `1. Capítulo uno.mp3`, `2. ...`. Si una exportación se corta por cuota o corte de conexión, la continuación se numera como parte: `<Título> (parte 2).mp3` (o `... (parte 2 - pendiente).mp3` si vuelve a cortarse).

---

## Motor local previsto

Se descartó **Piper TTS** como candidato a motor local de alta calidad. SAPI5 (64 y 32 bits vía puente) sigue siendo el único motor local de la app y así se queda.

---

## Actualizador automático (Fase C, v3.0)

Sustituye el enfoque de la v2.0 de generar un `.bat` al vuelo (bloque `ANCLAJE_INICIO: ACTUALIZADOR_SCRIPT_CLON` en `pestana_ajustes.py`) por un ejecutable auxiliar fijo y compilado, `bin/actualizador.exe`, igual que ya se hace con `auxiliar_sapi32.exe`:

- `actualizador_descarga.py` descarga y verifica la versión nueva en `temp/actualizacion/` sin tocar la instalación actual.
- `auxiliar_actualizador.py` (compilado a `bin/actualizador.exe`, automáticamente desde `crear_portable.py`) hace el respaldo por copia verificada en `temp/backup_previo/`, reemplaza los archivos y revierte solo si algo falla.

**Estado:** implementado y probado con simulaciones (instalación correcta, fallo a mitad de proceso, fallo de verificación del respaldo), pero pendiente de una validación completa de extremo a extremo en Windows real con NVDA antes de sustituir el bloque `ACTUALIZADOR_SCRIPT_CLON`, que sigue siendo el sistema activo en producción. No retirar ese bloque hasta confirmar esa validación.

---

## Lo que no hacer (resumen)

- No uses rutas relativas.
- No actualices la UI desde hilos secundarios sin `wx.CallAfter`.
- No accedas a `claves_api.json` directamente desde los clientes de API.
- No hagas llamadas a APIs desde el hilo principal.
- No uses `except: pass` sin logging.
- No añadas dependencias sin justificación.
- No rompas bloques ANCLAJE sin documentar el cambio en el mensaje de commit.
- No incluyas ninguna referencia a conversaciones, sesiones de IA ni proceso de desarrollo en el código ni en los comentarios.
- No uses la tecla `Espacio` como atajo de teclado.
- No escribes código en inglés. Todo en español.
- No uses `CheckListCtrlMixin.__init__(self)` — en wxPython 4.2+ genera `DeprecationWarning`. Usa solo `EnableCheckBoxes(True)` directamente sobre el `ListCtrl`.
- No uses `StaticText.SetLabel()` para mensajes que NVDA deba verbalizar sin foco — usa `accessible_output3` (`app.motor.anunciador_lector.hablar()`).
- No dejes ninguna cadena nueva de interfaz sin envolver en `_()` (ver "Internacionalización" más arriba), ni uses f-strings dentro de `_(...)`.
- No olvides recompilar los `.mo` (`python herramientas/compilar_i18n.py`) después de tocar cualquier `.po`.
