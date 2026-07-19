# Guía técnica para desarrolladores

Este documento describe la arquitectura interna de Epub TTS, las convenciones del proyecto y las decisiones técnicas que hay detrás de cada pieza. Está pensado para que cualquier desarrolladora que llegue al código pueda entender el sistema sin tener que reconstruirlo a base de pruebas.

Léelo antes de tocar nada.

---

## Mapa mental antes de abrir el código

Este apartado es para quien llega de cero. La idea es que, leyéndolo con calma, puedas construir un modelo mental de la app antes de abrir ningún archivo.

### El problema real que resuelve

El problema no es simplemente «leer libros con TTS». El problema es trabajar con libros largos y complejos, escucharlos de forma cómoda durante sesiones largas, y producir audiolibros multivoz, sin depender de flujos frágiles ni de herramientas pensadas para móvil.

El flujo previo a esta app incluía: preparar textos en Word, insertar marcas a mano para voces y personajes, usar apps móviles para generar audio, mover archivos constantemente entre móvil y PC, y editar después en Reaper. La app nace para unificar y simplificar todo eso en un entorno de escritorio accesible.

### Cómo se organiza la interfaz

Tres pestañas, porque es la forma más clara y accesible de separar usos: **Modo Lectura**, **Modo Grabación** y **Ajustes**. El usuario siempre sabe dónde está y qué puede hacer en cada momento.

### El reproductor: núcleo que no conoce nada más

El reproductor (`reproductor_voz.py`) gestiona estados (detenido, reproduciendo, pausado), decide qué motor de voz usar y asegura que nunca se quede la app en silencio. Clave: **el reproductor no conoce ni la interfaz ni el EPUB**. Recibe texto y lo envía al motor correspondiente. Si una API falla o no hay conexión, cae automáticamente a voz local.

### Las voces viven en caché local

Las voces no se consultan en tiempo real. Se descargan bajo demanda, se guardan en caché JSON y se normalizan a un formato común (id, nombre, idioma, proveedor, tipo). La interfaz siempre lee de esa caché. La API solo se consulta cuando el usuario pide actualizar.

### Si vas a tocar el código

Antes de modificar cualquier cosa, ten en cuenta:

- La accesibilidad es el eje del proyecto. Si algo deja de anunciarse bien con NVDA, es un bug crítico.
- La voz local (SAPI5) es siempre el respaldo. Nunca puede quedar sin ruta de escape.
- La interfaz no debe bloquearse. Toda llamada a una API ocurre en un hilo secundario; la UI solo se actualiza desde el hilo principal con `wx.CallAfter`.
- Las decisiones no son casuales. Antes de cambiar algo, busca si hay un comentario ANCLAJE que explique el porqué.

---

## Principio rector: la accesibilidad no es una capa

La accesibilidad con NVDA no se añadió al final. Condiciona cada decisión: qué controles usar, cómo situar el foco, cuándo hablar en los `label`, cómo evitar que las cargas pesadas bloqueen el anuncio del foco. Si modificas algo y NVDA deja de anunciar correctamente un control, eso es un bug crítico, no cosmético.

---

## Stack tecnológico

| Componente | Tecnología | Por qué |
|---|---|---|
| Interfaz | wxPython 4.2+ | Controles nativos de Windows, accesibles por definición. Sin alternativa real para NVDA. |
| Python | 3.12+ (Windows) | El proyecto se desarrolla y prueba en Windows. |
| Audio | FFmpeg portable (`/bin/`) | Sin instalación global. El usuario no necesita saber que existe. |
| HTTP | `requests` + `httpx` | `requests` para todo lo síncrono actual. `httpx` preparado para modo grabación asíncrono. |
| EPUB | EbookLib + BeautifulSoup4 | EbookLib para la estructura, BS4 para limpiar el HTML crudo. |
| Sonidos | `wx.adv.Sound` + `winsound` | Sin deps pesadas. Ambos son stdlib o parte de wxPython. |
| TTS local | SAPI5 64 bits + SAPI5 32 bits vía proceso puente | SAPI5 siempre disponible; puente para voces CodeFactory (Eloquence, RealSpeak). |
| TTS nube | Azure Neural, Amazon Polly, Deepgram Aura-2, ElevenLabs | Cada uno con su cliente propio en `/app/servicios/`. |
| Logs | `logging` + `RotatingFileHandler` | 2 MB, 3 backups. Solo WARNING+ en disco, INFO en consola. |

**El código está íntegramente en español.** Variables, funciones, clases, comentarios. Es una decisión consciente de la autora y debe mantenerse.

---

## Estructura de archivos

```
app/
├── interfaz/
│   ├── ventana_principal.py      # Ventana raíz. Notebook de pestañas. Menú contextual de app.
│   ├── pestana_biblioteca.py     # Biblioteca: importar EPUB/PDF, géneros, sagas, buscador
│   ├── pestana_lectura.py        # Modo Lectura: EPUB/PDF + reproducción TTS + marcadores
│   ├── pestana_creador_audiolibros.py  # Creador de Audiolibros: exportación completa/por capítulos
│   ├── pestana_grabacion.py      # Grabación de Fragmentos: etiquetas multivoz + exportación
│   ├── pestana_ajustes.py        # Ajustes: claves API, voces, atajos, cuota, acerca de
│   ├── ventana_proyectos.py      # Gestor de proyectos de Grabación. Ventana independiente (no modal)
│   ├── selector_voz_compartido.py  # ListaVocesCheck + PanelProveedorIA: catálogo de voces reutilizable
│   ├── dialogo_proveedor_alternativo.py  # Cuota insuficiente al exportar: cambiar de proveedor/voz local
│   ├── dialogo_troceador.py      # División de EPUB por capítulos
│   ├── dialogo_voces_nuevas.py   # Notificación de voces nuevas disponibles
│   ├── dialogo_novedades.py      # Novedades de versión al actualizar
│   ├── dialogos.py               # Diálogos compartidos: marcadores, confirmaciones, etc.
│   └── ui_recursos.py            # Helper para cargar iconos con fallback a wx.ArtProvider
├── motor/
│   ├── gestor_biblioteca.py      # CRUD sobre biblioteca.db (SQLite): libros, categorías, pendientes
│   ├── escaner_biblioteca.py     # Escaneo de carpetas en hilo de fondo (ThreadPoolExecutor)
│   ├── renombrador_biblioteca.py # Renombrado de archivos según metadatos reales
│   ├── gestor_epub.py            # Abre EPUB, limpia HTML, reconstruye índice, mapea posiciones
│   ├── gestor_pdf.py             # Extrae texto/índice de PDF (fitz) para Lectura, misma forma que gestor_epub
│   ├── gestor_proyectos.py       # Lógica de proyectos de Grabación. Persistencia en proyectos.json
│   ├── gestor_atajos.py          # Atajos de teclado configurables por el usuario
│   ├── grabador_audio.py         # Grabación silenciosa a archivo: fragmentos y audiolibros completos
│   ├── procesador_etiquetas.py   # Parsea {{@voz}} en el texto y fragmenta para grabación
│   ├── reproductor_voz.py        # Cola de audio TTS asíncrona interactiva. Orquesta todos los motores.
│   ├── reproductor_sonidos.py    # 12 efectos contextuales. Caché en RAM. Motor wx + fallback.
│   ├── cliente_nube_voces.py     # Descarga listas de voces desde cada API
│   ├── verificador_voces_nuevas.py # Detecta voces nuevas con cooldown de 24h
│   ├── comprobador_actualizaciones.py # Versioning semver contra GitHub
│   ├── control_cuota.py          # Contadores mensuales por proveedor con autoreset + coste estimado
│   ├── troceador_epub.py         # Divide EPUB por anclas HTML. TOC jerárquico y plano.
│   ├── troceador_pdf.py          # Divide PDF por su índice de contenidos (o por página si no tiene)
│   └── limpiador_lectura.py      # Limpieza de texto para TTS (sin HTML, sin ruido)
├── servicios/
│   ├── cliente_azure.py          # Azure Neural TTS. SSML escapado con xml.sax.saxutils.
│   ├── cliente_polly.py          # Amazon Polly. Selección automática de motor (standard/neural/generative).
│   ├── cliente_eleven.py         # ElevenLabs. Multilingüe. Streaming de audio.
│   ├── cliente_deepgram.py       # Deepgram Aura-2. REST puro. Pay-as-you-go. Caché LRU.
│   ├── cliente_sapi5.py          # SAPI5 64 bits. Siempre disponible, siempre el fallback.
│   └── cliente_sapi32_bridge.py  # SAPI5 32 bits (Eloquence, RealSpeak). Proceso puente JSON.
└── config_rutas.py               # Rutas absolutas. cargar_claves() / guardar_claves(). RAIZ del proyecto.

auxiliar_sapi32.py                # Script 32 bits independiente. Compilar con Python 32 bits + PyInstaller.
                                  # Resultado: bin/auxiliar_sapi32.exe (incluido en el portable).
```

---

## El sistema de ANCLAJE

Todo bloque de código que puede necesitar reemplazarse en el futuro está delimitado con comentarios de anclaje:

```python
# ANCLAJE_INICIO: NOMBRE_DEL_BLOQUE
# ... código ...
# ANCLAJE_FIN: NOMBRE_DEL_BLOQUE
```

Esto sirve para dos cosas: primero, que un desarrollador (o asistente IA) pueda encontrar el bloque exacto a sustituir sin necesidad de leer el archivo entero; segundo, que el historial de git deje claro qué bloque cambió y por qué.

**Regla:** Cuando entregues código nuevo, indica qué bloque ANCLAJE reemplaza. Nunca entregues un archivo entero sin contexto.

---

## Motor de sonidos: carga en RAM y doble motor

`/app/motor/reproductor_sonidos.py`

El motor de sonidos usa una estrategia de inicialización en dos fases para evitar problemas con el orden de arranque de wxPython:

**Fase 1 — al importar el módulo** (sin `wx.App` todavía):
```python
_precargar_rutas()  # Solo lee rutas de disco → _CACHE_RUTA
```

**Fase 2 — en el primer `reproducir()`** (ya con `wx.App` activo):
```python
_inicializar_wx()   # Crea objetos wx.adv.Sound → _CACHE_SONIDOS
```

El motor principal es `wx.adv.Sound` (parte de wxPython, sin deps adicionales). Si falla por cualquier razón, cae automáticamente a `winsound` de la stdlib de Python.

**Regla crítica:** `wx.adv.Sound.Play()` solo puede llamarse desde el hilo principal de wx. Si necesitas reproducir un sonido desde un hilo de fondo, usa siempre:
```python
wx.CallAfter(reproducir, NOMBRE_SONIDO)
```

Las 12 constantes disponibles:
```python
APP_READY, REC_START, REC_END, PROGRESS, LIST_NAV,
MOVE_UP, MOVE_DOWN, OPEN_FOLDER, SUCCESS, CLICK, ERROR, CLEAR
```

Todos los `wav` viven en `/recursos/sonidos/` a 16-bit, 44100 Hz. Si el directorio no existe o un archivo falta, el sistema falla silenciosamente (log WARNING, sin crash).

---

## Gestión de voces: caché local y normalización

Las voces no se consultan en tiempo real. El flujo es:

1. `cliente_nube_voces.py` descarga la lista completa desde la API bajo demanda.
2. Se guarda en caché local (JSON) en `/configuraciones/`.
3. La app siempre lee de la caché. La API solo se consulta cuando el usuario pide actualizar.

Cada proveedor devuelve datos con estructura distinta. `cliente_nube_voces.py` normaliza todo a un formato común con campos: `id`, `nombre`, `idioma`, `proveedor`, `tipo` (femenino/masculino/multilingüe/dragon).

El sistema de favoritas funciona sobre esa lista normalizada: guarda los IDs marcados en `ajustes.json` y filtra en lectura.

---

## Latencia de foco: por qué usamos `wx.CallAfter` y no threading puro

Problema: Al cambiar de pestaña en wxPython, si la pestaña destino tiene que cargar datos pesados (listas de voces, diccionarios de idioma), el foco de NVDA llega tarde o no llega. El usuario se queda sin saber dónde está.

Solución aplicada en Fase 4:

```python
def _al_activar_pestana(self, evento):
    wx.CallAfter(self._cargar_datos_pesados)  # Difiere la carga
    evento.Skip()
```

Con `wx.CallAfter`, el cambio de pestaña ocurre primero (NVDA anuncia el nombre de la pestaña), y la carga pesada llega después en el siguiente tick del bucle de eventos.

**Por qué no usamos `threading.Thread` directamente:** wxPython no es thread-safe. Actualizar controles wx desde hilos secundarios produce crashes o comportamientos impredecibles, especialmente con NVDA activo. La regla es: toda actualización de UI ocurre en el hilo principal, usando `wx.CallAfter` para llamadas diferidas.

En casos donde sí hay hilo secundario (grabación de audio, llamadas a APIs), el patrón es:
```python
def _hilo_grabacion(self):
    resultado = self._grabar()          # Trabajo pesado en hilo secundario
    wx.CallAfter(self._actualizar_ui, resultado)  # UI siempre en hilo principal
```

Adicionalmente, para inserción masiva de ítems en listas:
```python
self.lista.Freeze()
for item in items:
    self.lista.Append(item)
self.lista.Thaw()
```
`Freeze()/Thaw()` evita el redibujado en cada inserción, reduciendo la latencia perceptible.

---

## Prevención de ciclos en el árbol de proyectos

`/app/motor/gestor_proyectos.py` — función `mover_proyecto()`

El árbol de proyectos permite arrastrar y soltar nodos, lo que crea el riesgo de ciclos: que un proyecto acabe siendo su propio ancestro.

La función `mover_proyecto()` recorre hacia arriba la jerarquía del destino antes de aceptar el movimiento:

```python
def _es_descendiente(self, posible_descendiente_id, ancestro_id):
    """Sube por la jerarquía desde posible_descendiente_id.
    Devuelve True si en algún punto encuentra ancestro_id (ciclo detectado)."""
    actual = posible_descendiente_id
    visitados = set()
    while actual:
        if actual in visitados:
            return True   # Ciclo detectado independientemente
        if actual == ancestro_id:
            return True   # Es descendiente: movimiento no permitido
        visitados.add(actual)
        actual = self._datos["proyectos"].get(actual, {}).get("padre")
    return False
```

Si se detecta ciclo, `mover_proyecto()` lanza `ValueError` y la interfaz lo captura para mostrar un aviso. La estructura JSON nunca queda en estado corrupto.

---

## Arquitectura portable: FFmpeg en `/bin/`

La exportación de audio a MP3 usa FFmpeg. En lugar de requerir que el usuario lo instale globalmente, el ejecutable vive en `/bin/ffmpeg.exe` (Windows) o `/bin/ffmpeg` (Linux).

`config_rutas.py` define `RAIZ` como el directorio real del proyecto (no el directorio de trabajo actual), y todas las rutas de la app se construyen sobre él:

```python
import os
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(RAIZ, "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
```

**Nunca uses rutas relativas** en el código. Una ruta relativa funciona si el usuario lanza la app desde el directorio del proyecto, pero falla si la lanza desde otro directorio o desde un acceso directo. Todo usa `RAIZ` como base.

---

## Configuración: tres archivos JSON con roles distintos

| Archivo | Qué contiene | En .gitignore |
|---|---|---|
| `configuraciones/claves_api.json` | Claves de Azure, Polly, ElevenLabs | **Sí** |
| `configuraciones/ajustes.json` | Todo lo demás: idioma, velocidad, volumen, tiempos de salto, favoritas, límites de cuota | No |
| `configuraciones/proyectos.json` | Jerarquía completa de proyectos y subproyectos | No |

`cargar_claves()` y `guardar_claves()` en `config_rutas.py` son las únicas funciones que tocan `claves_api.json`. El resto de la app no tiene acceso directo a ese archivo.

**Migración automática:** Si la app encuentra claves en `ajustes.json` (formato antiguo), las migra automáticamente a `claves_api.json` y las elimina del primero. El usuario no necesita hacer nada.

---

## Escritura atómica en JSON

Todos los archivos JSON de configuración se escriben de forma atómica: primero a un archivo temporal, luego se renombra sobre el destino. Esto evita dejar archivos corruptos a medias si la app se cierra mientras escribe.

```python
import tempfile, os

def guardar_json(ruta, datos):
    dir_ = os.path.dirname(ruta)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                     suffix=".tmp", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, ruta)  # Atómico en Windows y Linux
```

---

## Accesibilidad: reglas que no se negocian

**1. El `label` es la fuente de verdad para NVDA.**

NVDA no siempre lee `SetHelpText()` de forma automática. Toda información que el usuario necesite para entender un control debe estar en el `label`, no solo en el helptext. El helptext es un complemento, nunca el único lugar donde está la instrucción.

**2. Los diálogos devuelven el foco.**

Cuando un diálogo se cierra, el foco debe volver exactamente al control desde el que se abrió. Si no se gestiona, NVDA puede quedar desorientado.

```python
control_previo = wx.Window.FindFocus()
dlg.ShowModal()
dlg.Destroy()
if control_previo:
    control_previo.SetFocus()
```

**3. `wx.GetTopLevelParent()` en lugar de cadenas de `GetParent()`.**

Navegar la jerarquía de widgets con `GetParent().GetParent().GetParent()` es frágil. Si cambia la estructura del layout, se rompe. Usa `wx.GetTopLevelParent(self)` para llegar a la ventana raíz.

**4. Casillas de verificación en listas.**

Usa `EnableCheckBoxes(True)` directamente sobre el `ListCtrl`. En wxPython 4.2+ es suficiente para que NVDA anuncie el estado al navegar con flechas.

**No uses `CheckListCtrlMixin.__init__(self)`** — en wxPython 4.2+ genera `DeprecationWarning` en consola. Si el código hereda de `CheckListCtrlMixin`, elimina la llamada al `__init__` del mixin (la herencia en sí no causa problemas, pero la llamada sí).

**5. Verbalización inmediata sin mover el foco visible (`_anunciador`).**

`StaticText.SetLabel()` no dispara eventos de accesibilidad. Para que NVDA anuncie texto en respuesta a una acción (Ctrl+I para la página, Ctrl+S para "Guardado."), usa un `wx.TextCtrl` oculto de 1×1 px:

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

El control recibe el foco brevemente, NVDA anuncia su valor, y el foco vuelve tras 300 ms. El usuario no nota ningún movimiento visible.

**6. El debounce de 300ms en búsquedas.**

Las búsquedas en la lista de voces usan un temporizador de 300ms para no lanzar filtrado en cada pulsación de tecla. Sin él, NVDA anuncia el texto mientras el usuario sigue escribiendo, lo que resulta caótico.

---

## Logs

El sistema de logs está centralizado en `iniciar_epub_tts.py`:

- **Archivo:** `app/registros/app.log`, máximo 2 MB, 3 backups (`app.log.1`, `app.log.2`, `app.log.3`).
- **Nivel en disco:** WARNING y superior. Los mensajes de depuración rutinarios no van al archivo.
- **Nivel en consola:** INFO. Para sesiones de desarrollo.

Formato: `%(asctime)s — %(name)s — %(levelname)s — %(message)s`

Cada módulo obtiene su logger con `logging.getLogger(__name__)`. No uses `print()` para depuración en el código definitivo.

---

## Pruebas manuales antes de un commit

No hay suite de tests automatizados todavía. Antes de hacer commit de cambios en la interfaz, comprueba manualmente con NVDA activo:

1. ¿El foco llega a donde debe al cambiar de pestaña?
2. ¿Los diálogos devuelven el foco al cerrarse?
3. ¿Las casillas de verificación anuncian "marcado/desmarcado" al navegar con flechas?
4. ¿Los sonidos se reproducen sin superponer la voz de NVDA?
5. ¿El árbol de proyectos anuncia nombre, nivel y estado correctamente?

---

## Motor local

Piper TTS estuvo previsto como motor local de alta calidad para sustituir a SAPI5. Se descartó explícitamente en la Fase 7. SAPI5 (64 bits + puente de 32 bits) sigue siendo el único motor local de la app.

---

## Lo que no hacer

- No uses `except: pass` ni `except Exception: pass` sin logging. Si no sabes qué hacer con un error, al menos loguéalo: `logger.exception("contexto")`.
- No accedas a `claves_api.json` directamente desde los clientes de API. Usa `cargar_claves()`.
- No hagas llamadas a APIs desde el hilo principal. El hilo principal es para la UI.
- No añadas dependencias sin justificación. Cada nueva librería es un punto de rotura potencial en la portabilidad.
- No rompas los bloques ANCLAJE sin documentar el cambio en el mensaje de commit.

---

## Registro técnico v1.1 y v1.2

### Mudanza de carpetas al directorio del ejecutable

**Problema:** Al empaquetar con PyInstaller, `sys.executable` apunta a un directorio temporal de extracción que se borra al cerrar la app. Las carpetas `Grabaciones_Epub-TTS/` y el archivo `ayuda.html` desaparecían con cada cierre.

**Solución:** `config_rutas.py` define `RAIZ` como el directorio del `.exe` real (o del script Python en desarrollo), no del directorio de trabajo actual. Todas las rutas de salida se construyen sobre `RAIZ`.

---

### Corrección del mensaje de progreso en grabación

**Problema:** El callback `_actualizar_progreso_ui()` en `pestana_grabacion.py` actualizaba `lbl_progreso` con la ruta completa de la carpeta de salida en cada fragmento procesado. NVDA verbalizaba esa ruta larga entre cada fragmento durante toda la grabación.

**Solución:** Los mensajes de progreso se limitan a contadores de fragmento (`"Fragmento 3 de 12…"`). Solo el mensaje final de éxito incluye el nombre corto de la carpeta de salida.

---

### Deslizadores en modo grabación

Los deslizadores de velocidad y volumen de `pestana_grabacion.py` siguen exactamente el mismo patrón que los de `pestana_lectura.py`: valor inicial desde `ajustes.json`, guardado en cada cambio, pasos de 1 con flechas y 5 con RePág/AvPág. Solo exponen el valor actual a la API de accesibilidad (no la escala completa).

---

### Cliente Deepgram REST (`app/servicios/cliente_deepgram.py`)

Deepgram TTS usa la API REST `POST https://api.deepgram.com/v1/speak` con cabecera `Authorization: Token <key>`. El cuerpo es JSON `{"text": "..."}` y el parámetro de voz va en la query string (`model=aura-2-...`).

La respuesta devuelve audio en formato MP3 directamente en el cuerpo de la respuesta HTTP, sin necesidad de pasos intermedios.

**Limitación de la API:** Deepgram rechaza peticiones con más de ~1 900 caracteres.

**Solución implementada en `_dividir_texto()`:** Los textos largos se fraccionan en fragmentos de máximo 1 900 caracteres, cortando siempre en límite de palabra (sin partir palabras). `_llamar_api()` coordina la división y llama a `_peticion_http()` por cada fragmento, concatenando los bytes de audio resultantes antes de reproducirlos.

**Precarga:** `preparar(texto, datos_voz)` inicia en segundo plano la misma llamada que haría `hablar()` y guarda el resultado en `_cache_audio`. Cuando `hablar()` llega después, encuentra el audio ya listo y lo reproduce sin latencia de red.

---

### Lectura continua sin pausas entre fragmentos (`modo_cola`)

**Problema original:** Al terminar un fragmento, `cargar_texto()` llamaba a `detener()`, que a su vez cerraba la sesión HTTP activa de todos los clientes de nube. El audio predesargado por `preparar()` quedaba invalidado al cerrar su conexión. Además, `time.sleep(0.05)` añadía 50 ms adicionales. El resultado eran pausas de 1-2 s entre cada bloque.

**Solución — parámetro `modo_cola=True`:**

Cuando `PestanaLectura` encadena fragmentos desde la cola de lectura continua, llama a `cargar_texto(..., modo_cola=True)`. En este modo:

- Se omite `self.detener()` (el audio anterior ya terminó; `sd.wait()` lo garantiza antes de que llegue el callback).
- Se omite `time.sleep(0.05)`.
- La sesión HTTP permanece abierta y el audio predesargado está disponible de inmediato.

El resultado son transiciones de ~5 ms entre fragmentos, imperceptibles al oído.

**Importante:** `_precarga_solicitada` se reinicia a `False` al inicio de cada `_reproducir_siguiente_fragmento()`, no al final. Esto garantiza que cada fragmento intente precargar el siguiente, no solo el primero.

---

### Sistema de historial de voces nuevas (`voces_conocidas.json`)

**Problema anterior:** La UI calculaba `es_nueva` en tiempo de visualización comparando con `voces_conocidas.json`, pero el archivo se sobreescribía antes de la descarga, haciendo que la comparación siempre resultara vacía.

**Solución:** `_marcar_y_guardar()` en `cliente_nube_voces.py` inyecta el campo `es_nueva` directamente en la caché JSON en el momento de la descarga, antes de que la UI la lea.

Flujo:
1. `_cargar_ids_conocidos()` lee `voces_conocidas.json` (IDs ya vistos antes de esta descarga).
2. Si el archivo está vacío, `primera_vez=True` → ninguna voz se marca nueva (evita marcar 400 voces como nuevas en la primera instalación).
3. `_aplicar_marca_nuevas()` recorre `self.voces_cache` y pone `v["es_nueva"] = True` solo a las IDs que no estaban en `ids_conocidos`.
4. `_guardar_ids_conocidos()` actualiza el archivo con la unión de IDs anteriores y actuales (escritura atómica con `.tmp` + `os.replace()`).
5. `_guardar_cache()` persiste la caché con los campos `es_nueva` ya incluidos.

La UI en `pestana_ajustes.py` solo lee `bool(v.get("es_nueva", False))` directamente del JSON; no recalcula nada.

---

### Control de cuota ampliado a Deepgram

`control_cuota.py` añade `"deepgram"` a todos sus diccionarios internos: `limites_defecto`, el bloque `"gastado"` de `datos_base`, y la lógica de `tiene_cuota()` / `registrar_gasto()`. El panel de presupuesto en `pestana_ajustes.py` (`PanelGeneral`) muestra una fila Deepgram junto a Azure, Polly y ElevenLabs, con el mismo cálculo de coste aproximado en dólares.

## Decisiones Técnicas Recientes (Fase 5)

### Gestión de Audio y SAPI 5
- Se ha implementado la grabación SAPI 5 usando `SAPI.SpFileStream` para volcado directo a archivo, evitando la reproducción por altavoz durante el renderizado.
- El estándar de exportación se fija en **MP3 320 kbps** para asegurar compatibilidad total con proyectos de edición profesional en Reaper.
### Reglas de Interfaz (UX Accesible)
- **Slidrs:** No deben exponer la escala completa a la API de accesibilidad. Solo el valor actual.
- **Atajos:** `Control + P` es el comando universal de reproducción. Se prohíbe el uso de la tecla `Espacio` para evitar conflictos de foco con NVDA.
- **Navegación:** Se sustituyen los términos "Atrás/Adelante" por **"Retroceder/Avanzar"** para mayor claridad semántica.

## Decisiones Técnicas Recientes (Fase 5)

### Sincronización de Audio y Foco
- **Motor SAPI 5:** Se procesa mediante una cola de párrafos en un hilo secundario utilizando `WaitUntilDone()` y callbacks de progreso. El cursor debe seguir a la voz en tiempo real. Prohibido usar estimaciones temporales.
- **Pausa Neuronal:** Para voces de API, se mantiene la lógica de reenvío desde la posición del cursor, con un tiempo de pausa configurable (ms) en Ajustes para evitar solapamientos.

### Procesamiento de EPUB y Estilos
- **Extracción Estilo Bookworm:** Uso de un patrón de bloques para separar contenido inline de estructural, asegurando que no existan palabras cortadas.
- **Renderizado de Estilos:** El formateo de texto rico se aplica asíncronamente tras la carga del texto. Se utiliza `Freeze/Thaw` en el `TextCtrl` para realizar todas las operaciones de estilo de una sola vez sin afectar el rendimiento.

### UX y Atajos
- **Slidrs:** Solo exponen el valor actual a la API de accesibilidad. Pasos de 1 (flechas) y 10 (RePág/AvPág).
- **Atajos:** `Control + O` es el comando universal de apertura. `H / Shift+H` para navegación por encabezados. Se prohíbe el uso de la tecla `Espacio` para evitar conflictos de foco.

---

## Decisiones técnicas — Fase 6 (v2.0, junio 2026)

### Puente SAPI5 de 32 bits

Las voces de CodeFactory (Eloquence, RealSpeak) son motores COM de 32 bits. Un proceso de 64 bits no puede cargar un COM de 32 bits directamente.

**Arquitectura implementada:**

- `auxiliar_sapi32.py` — script independiente, compilado con Python 32 bits + PyInstaller a `bin/auxiliar_sapi32.exe`. Carga el motor SAPI5 de 32 bits y escucha comandos JSON por stdin.
- `app/servicios/cliente_sapi32_bridge.py` — cliente en la app principal (64 bits). Lanza el ejecutable como subproceso con `subprocess.Popen(stdin=PIPE, stdout=PIPE, creationflags=0x08000000)`. Se comunica con líneas JSON.

**Protocolo JSON (stdin → auxiliar / stdout → bridge):**

```
→ {"cmd": "listar_voces"}
← {"evento": "voces", "datos": [{"id": "...", "nombre": "...", "idioma": "..."}, ...]}

→ {"cmd": "cambiar_voz", "id": "..."}
← {"evento": "voz_cambiada"}

→ {"cmd": "hablar", "texto": "...", "velocidad": 50, "volumen": 100, "generacion": 3}
← {"evento": "progreso", "posicion": 42}
← {"evento": "completado"}

→ {"cmd": "detener"}
→ {"cmd": "salir"}

→ {"cmd": "exportar_archivo", "texto": "...", "ruta_wav": "...", "voz_nombre": "...", "rate": 0, "volume": 100}
← {"evento": "exportado", "exito": true/false, "msg": "..."}
```

`exportar_archivo` es síncrono (bloquea el bucle de comandos del auxiliar hasta terminar de escribir el WAV con `SpFileStream`, igual que `_grabar_sapi5` hace con el motor de 64 bits) — pensado para exportación silenciosa desde el Creador de Audiolibros, no para lectura interactiva.

`ClienteSapi32Bridge` expone exactamente la misma interfaz pública que `ClienteSapi5`. `reproductor_voz.py` enruta según `proveedor_id`: `"local"` → `cliente_sapi5`, `"local_32"` → `cliente_sapi32_bridge`. `grabador_audio.py` hace lo mismo para exportación: `_llamar_motor()` enruta `proveedor_id == "local_32"` a `_grabar_sapi5_32()` (que usa `exportar_archivo` sobre una instancia de `ClienteSapi32Bridge` cacheada en `self._bridge_sapi32`, cerrada explícitamente con `GrabadorAudio.cerrar()` al terminar cada exportación), y cualquier otro proveedor local a `_grabar_sapi5()` de 64 bits.

**Para compilar el auxiliar** (una sola vez, en un entorno Python 32 bits):
```
python -m PyInstaller --noconsole --onefile --name auxiliar_sapi32 auxiliar_sapi32.py
```
El resultado (`auxiliar_sapi32.exe`) se copia a `/bin/` antes de empaquetar el portable.

---

### Contador de generación en `reproductor_voz.py`

El problema de los silencios de ~7 segundos y la superposición de voces tenía una causa concreta: los hilos de precarga terminaban su descarga después de que el usuario había pausado o cambiado de voz, y reproducían el audio sin comprobar si seguía siendo válido.

**Fix:** `detener()` incrementa `_generacion` como primera operación. Cada hilo de precarga captura `generacion_precarga = self._generacion` al lanzarse. Al terminar la descarga, compara:

```python
if self._generacion != generacion_precarga:
    motor.invalidar_cache(texto)
    return
```

Cualquier descarga que llegue con una generación obsoleta se descarta sin reproducirse.

---

### Páginas virtuales con texto normalizado

La unidad de página virtual es de **1800 caracteres normalizados**. El método `_longitud_normalizada(texto)` usa regex para colapsar el whitespace sobrante antes de contar:

```python
@staticmethod
def _longitud_normalizada(texto: str) -> int:
    t = re.sub(r"[ \t]+", " ", texto)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return len(t)
```

Esto compensa el exceso de whitespace habitual en EPUBs exportados desde Word o LibreOffice, que sin normalizar inflan el recuento hasta un 40%.

---

### Limpieza de temporales al arrancar

`iniciar_epub_tts.py` ejecuta una limpieza de archivos huérfanos antes de mostrar la ventana principal. Solo toca archivos con prefijo `tfh_` (los que genera `grabador_audio.py` con `tempfile.mkstemp(prefix="tfh_")`). Nunca borra archivos de configuración.

Criterios: archivos con más de 7 días, o, si la carpeta supera 50 MB, los más antiguos primero hasta bajar del límite.

---

### Ajustes — árbol de navegación

La pestaña de Ajustes usa `wx.TreeCtrl` (completamente expandido, sin colapsar) a la izquierda y `wx.Simplebook` a la derecha. Cada nodo del árbol corresponde a un panel. NVDA navega el árbol con flechas; Tab entra en el panel.

**Contrato de cada panel de ajustes:**
- Expone `primer_control` y `ultimo_control`.
- `pestana_ajustes.py` intercepta Tab en `ultimo_control` para devolver el foco al árbol (ciclo de navegación cerrado).
- `EVT_CHAR_HOOK` gestiona el Tab antes de que wxPython lo procese como cambio de foco estándar.

---

### Selector de escala de velocidad

El deslizador de velocidad del modo lectura puede **mostrarse** en dos escalas, pero el valor real que recibe el motor de voz es siempre el mismo rango 0–100 — no hay dos sliders ni dos rangos internos. La versión anterior de este documento describía un slider de 0 a 25 para el modo multiplicador; ese diseño tenía un bug (la conversión de vuelta a 0-100 nunca se llamaba desde ningún sitio) y se descartó:

- **Porcentaje (0–100):** el valor del slider se muestra tal cual.
- **Multiplicador (0.2×–1.8×):** el slider sigue yendo de 0 a 100 igual que en modo porcentaje; solo cambia la etiqueta mostrada, calculada en vivo como `1 + (v-50) * 0.016` (coincide con la fórmula real de la tasa SSML: `pct = (v-50)*1.6%`, acotada a ±80%).

El selector está en Ajustes → Configuración General. Al guardar con Ctrl+S, `pestana_lectura._aplicar_escala_velocidad()` reconfigura solo la etiqueta/helptext del slider, nunca su rango.

---

## Decisiones técnicas — Fase 7 (v3.0, julio 2026)

### Biblioteca: SQLite en vez de JSON

A diferencia del resto de la app (todo JSON), la Biblioteca usa SQLite (`configuraciones/biblioteca.db`) vía `gestor_biblioteca.py`. La razón es de escala: una colección real puede tener cientos o miles de libros con categorías, etiquetas y exportaciones pendientes relacionadas entre sí — consultas como "libros de esta etiqueta" o "exportaciones pendientes de este libro" son mucho más baratas y correctas con `JOIN`/índices que recorriendo listas en Python. El escaneo de una carpeta usa un `ThreadPoolExecutor` en `escaner_biblioteca.py` para extraer metadatos de varios archivos a la vez; la escritura en SQLite siempre pasa por el hilo principal del escáner, nunca desde los workers.

### `TroceadorPdf` y `gestor_pdf.py`: misma interfaz que EPUB, sin duplicar lógica

`troceador_pdf.py` (para el Creador de Audiolibros) y `gestor_pdf.py` (para Lectura) exponen exactamente la misma forma de retorno que sus equivalentes de EPUB (`troceador_epub.py` / `gestor_epub.py`), usando PyMuPDF (`fitz`) para extraer texto y el índice de contenidos embebido (`documento.get_toc()`). Si el PDF no tiene índice, se genera uno sintético de una entrada por página, igual que hacen otros lectores accesibles de referencia con este mismo caso.

Un detalle que costó una ronda extra: `gestor_pdf.py` limpia cada página individualmente (`limpiar_para_lectura()` por página, no sobre el texto concatenado completo) y registra el offset de cada página ya sobre el texto limpio. La primera versión limpiaba todo de una vez al final, con offsets calculados en crudo — a diferencia de EPUB, donde los encabezados se reubican tras la limpieza buscando su propio texto, un marcador de PDF no siempre aparece literal en el cuerpo de la página, así que ese margen de imprecisión no se podía corregir con el mismo truco. Limpiar página a página evita el problema de raíz: la posición ya es la definitiva.

### El selector de voz del Creador de Audiolibros: un candado contra eventos sintéticos

`ListaVocesCheck` (la lista de voces con casillas, en `selector_voz_compartido.py`) tiene un problema conocido de wxPython: `CheckItem()` llamado programáticamente dispara el mismo evento (`EVT_LIST_ITEM_CHECKED`) que si el usuario marcara la casilla a mano. Al poblar la lista marcando las voces ya favoritas, eso disparaba el manejador de "marcar como favorita" para cada una, en cascada.

```python
self._poblando_lista = True
try:
    # ... CheckItem(pos, True) para cada favorita ...
finally:
    self._poblando_lista = False

def _al_marcar_favorito(self, evento):
    if self._poblando_lista:
        return
    # ... lógica real de marcado ...
```

El mismo patrón se repite en `pestana_creador_audiolibros.py` para la lista de capítulos (`_poblando_capitulos`), que tiene el mismo problema de raíz al marcar por defecto todos los capítulos como incluidos.

### Exportación en paralelo: `ThreadPoolExecutor` con dos garantías

`grabador_audio.py` genera en paralelo (hasta 4 hilos, `_MAX_WORKERS_EXPORTACION`) tanto los trozos internos de un fragmento largo (modo "Libro completo") como los capítulos de un audiolibro (modo "Por capítulos"). Dos cosas tenían que seguir siendo ciertas después de paralelizar:

1. **La cuota se sigue comprobando en orden estricto y sin llamadas de red.** `ControlCuota.tiene_cuota()` es aritmética pura, así que la fase de "qué capítulos caben" sigue siendo secuencial y casi instantánea — solo la síntesis real (la parte lenta) se paraleliza, sobre los capítulos que ya se sabe que caben.
2. **La numeración de archivos es atómica por índice, no por orden de llegada.** Cada trozo/capítulo escribe a una posición fija de una lista pre-dimensionada (`archivos_tmp = [None] * total`) o a un nombre de archivo que incluye su índice fijo (`f"{indice + 1}. {titulo}.mp3"`), nunca al orden en que termina el hilo. `_concatenar_audios()` siempre recibe la lista ya en el orden real del texto.

```python
futuros = {executor.submit(_generar, j, trozo): j for j, trozo in enumerate(trozos)}
for futuro in as_completed(futuros):
    indice = futuros[futuro]
    archivos_tmp[indice] = futuro.result()   # posición fija, no append()
```

El progreso reportado a la UI pasó de "vamos por el capítulo N" a "van completados N de total" — con varios hilos terminando en paralelo, la posición ya no tiene por qué coincidir con el orden del libro. `pestana_creador_audiolibros.py` localiza la fila a actualizar en la lista de capítulos buscando por título, no por índice.

### Reanudación de exportaciones pendientes

`exportaciones_pendientes` (tabla en `biblioteca.db`) guarda, por libro: modo, proveedor, y el punto de corte (capítulo o carácter) donde se quedó. Un detalle importante para que una tercera reanudación no se desincronice: el punto de corte que se registra es siempre **absoluto sobre el texto completo del libro**, nunca relativo al tramo que se estaba generando en ese intento — si no, una segunda reanudación heredaría un offset calculado sobre un texto ya recortado, y cortaría en el sitio equivocado.

Retomar en modo "Por capítulos" reutiliza el flujo normal de exclusión de capítulos (desmarca automáticamente los ya generados). Retomar en modo "Libro completo" genera solo el texto restante como una parte nueva numerada (`numero_parte`), calculada mirando qué archivos "(parte N...)" existen ya en la carpeta del libro — más robusto que llevar un contador en la base de datos.

### El puente SAPI32: un objeto COM por hilo, nunca compartido

`auxiliar_sapi32.py` tenía un bug de fondo desde su creación en la Fase 6, que solo se manifestaba de forma intermitente: el objeto COM `SAPI.SpVoice` se creaba en el hilo principal del proceso auxiliar, pero se usaba también desde el hilo que habla párrafo a párrafo. Un objeto COM de apartamento simple (STA, que es lo que es `SAPI.SpVoice`) no se puede usar de forma fiable desde un hilo distinto al que lo creó, ni siquiera si ese segundo hilo llama a `CoInitialize()` — falta el marshaling entre apartamentos. La solución no fue añadir más inicialización: fue que cada hilo que habla cree su propia instancia del motor, de principio a fin, y que el hilo principal solo comparta datos planos (voz elegida, velocidad, volumen) — nunca un puntero COM — para que cada hilo nuevo pueda reaplicarlos sobre su propio motor.

### Polly "standard": silencio digital, no temporización

El motor `standard` de Amazon Polly recortaba la última sílaba de la última palabra a velocidades altas. Tres intentos basados en temporización (ajustar el recorte de silencio en la costura, un `<break>` SSML dentro de la etiqueta de velocidad, el mismo `<break>` fuera de la etiqueta y escalado con la velocidad) mejoraron el problema sin eliminarlo. La causa raíz resultó estar en el reproductor en vivo, no en la síntesis: `sd.wait()` (de la librería `sounddevice`) puede devolver el control antes de que el hardware de audio termine de vaciar físicamente su búfer; a velocidad alta, el siguiente fragmento arrancaba con `sd.play()` casi de inmediato, interrumpiendo la cola de audio del fragmento anterior.

La solución definitiva combina dos cosas:

```python
# cliente_polly.py — antes de sd.play(), solo para el motor "standard"
relleno = np.zeros((int(fs * 0.4),) + data.shape[1:], dtype=data.dtype)
data = np.concatenate([data, relleno], axis=0)
```

400 ms de silencio digital real (ceros) al final del array de audio, para que el hardware nunca tenga sonido real que cortar en el borde. Además, un margen de 120 ms tras `sd.wait()` en los cuatro clientes de nube (Azure, Polly, ElevenLabs, Deepgram), por si acaso, ya que el mismo mecanismo de fondo podía en teoría afectar a cualquiera de ellos.

---