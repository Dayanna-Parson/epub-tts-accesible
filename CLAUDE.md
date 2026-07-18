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
│   ├── grabador_audio.py         # Grabación silenciosa a archivo: fragmentos y audiolibros completos
│   ├── procesador_etiquetas.py   # Parsea {{@voz}} y fragmenta para grabación
│   ├── reproductor_voz.py        # Cola TTS asíncrona interactiva. Orquesta todos los motores.
│   ├── reproductor_sonidos.py    # 12 efectos contextuales. Caché en RAM.
│   ├── cliente_nube_voces.py     # Descarga listas de voces desde cada API
│   ├── verificador_voces_nuevas.py  # Detecta voces nuevas con cooldown de 24h
│   ├── comprobador_actualizaciones.py  # Versioning semver contra GitHub
│   ├── control_cuota.py          # Contadores mensuales por proveedor con autoreset + coste estimado
│   ├── troceador_epub.py         # Divide EPUB por anclas HTML
│   ├── troceador_pdf.py          # Divide PDF por su índice de contenidos (o por página si no tiene)
│   ├── limpiador_lectura.py      # Limpieza de texto para TTS
│   └── diccionario_pronunciacion.py  # Sustituciones fonéticas locales para todos los motores
├── servicios/
│   ├── cliente_azure.py          # Azure Neural TTS. SSML con xml.sax.saxutils.
│   ├── cliente_polly.py          # Amazon Polly. Motor automático standard/neural/generative.
│   ├── cliente_eleven.py         # ElevenLabs. Multilingüe. Streaming.
│   ├── cliente_deepgram.py       # Deepgram Aura-2. REST puro. Pay-as-you-go. Caché LRU.
│   ├── cliente_sapi5.py          # SAPI5 64 bits. Fallback siempre disponible.
│   └── cliente_sapi32_bridge.py  # SAPI5 32 bits (Eloquence, RealSpeak). Proceso puente.
└── config_rutas.py               # Rutas absolutas. cargar_claves() / guardar_claves().

auxiliar_sapi32.py                # Proceso auxiliar de 32 bits. Se compila a bin/auxiliar_sapi32.exe.
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

### Voces locales: dos proveedores

- `local` → `cliente_sapi5.py` (64 bits, siempre disponible)
- `local_32` → `cliente_sapi32_bridge.py` (32 bits vía proceso puente, requiere `bin/auxiliar_sapi32.exe`)

El campo `proveedor_id` de cada voz indica cuál de los dos usa. El reproductor enruta automáticamente. Si el puente no está disponible, las voces `local_32` no aparecen en la lista.

---

## Reglas críticas de arquitectura

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

### Patrón `_anunciador`: verbalización inmediata en NVDA

Para que NVDA verbalice texto inmediatamente sin mover el foco visible, usa un `wx.TextCtrl` oculto de 1×1 px con el patrón establecido:

```python
# En __init__:
self._anunciador = wx.TextCtrl(self, style=wx.TE_READONLY | wx.BORDER_NONE, size=(1, 1))

# Para verbalizar:
def _anunciar(self, texto):
    control_previo = wx.Window.FindFocus()
    self._anunciador.SetValue(texto)
    self._anunciador.SetFocus()
    wx.CallLater(300, lambda: control_previo.SetFocus() if control_previo else None)
```

Usado en Ctrl+I (anunciar página), Ctrl+S en Ajustes ("Guardado."), y otros puntos donde `SetLabel()` no activa el evento de accesibilidad.

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
- `H / Shift+H` para navegación por encabezados en el lector.
- Usar siempre "Retroceder/Avanzar" en lugar de "Atrás/Adelante".

---

## Motor de sonidos

12 constantes disponibles en `reproductor_sonidos.py`:
```python
APP_READY, REC_START, REC_END, PROGRESS, LIST_NAV,
MOVE_UP, MOVE_DOWN, OPEN_FOLDER, SUCCESS, CLICK, ERROR, CLEAR
```

Los `.wav` viven en `/recursos/sonidos/` a 16-bit, 44100 Hz. Si falta alguno, falla silenciosamente (log WARNING, sin crash).

Inicialización en dos fases: `_precargar_rutas()` al importar (sin wx.App), `_inicializar_wx()` en el primer `reproducir()` (ya con wx.App activo).

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
- No uses `StaticText.SetLabel()` para mensajes que NVDA deba verbalizar sin foco — usa el patrón `_anunciador`.
