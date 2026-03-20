# Guía técnica para desarrolladores

Este documento describe la arquitectura interna de Epub TTS, las convenciones del proyecto y las decisiones técnicas que hay detrás de cada pieza. Está pensado para que cualquier desarrollador que llegue al código pueda entender el sistema sin tener que reconstruirlo a base de pruebas.

Léelo antes de tocar nada.

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
| TTS local | pyttsx3 / SAPI5 | Respaldo offline siempre disponible. |
| TTS nube | Azure Neural, Amazon Polly, ElevenLabs | Cada uno con su cliente propio en `/app/servicios/`. |
| Logs | `logging` + `RotatingFileHandler` | 512 KB, 1 backup. Solo WARNING+ en disco, INFO en consola. |

**El código está íntegramente en español.** Variables, funciones, clases, comentarios. Es una decisión consciente de la autora y debe mantenerse.

---

## Estructura de archivos

```
app/
├── interfaz/
│   ├── ventana_principal.py      # Ventana raíz. Notebook de 3 pestañas. Menú contextual de app.
│   ├── pestana_lectura.py        # Modo Lectura: EPUB + reproducción TTS + marcadores
│   ├── pestana_grabacion.py      # Modo Grabación: etiquetas multivoz + grabación + exportación
│   ├── pestana_ajustes.py        # Ajustes: claves API, voces, atajos, cuota, acerca de
│   ├── ventana_proyectos.py      # Gestor de proyectos. Ventana independiente (no modal)
│   ├── dialogo_troceador.py      # División de EPUB por capítulos
│   ├── dialogo_voces_nuevas.py   # Notificación de voces nuevas disponibles
│   ├── dialogo_novedades.py      # Novedades de versión al actualizar
│   ├── dialogos.py               # Diálogos compartidos: marcadores, confirmaciones, etc.
│   └── ui_recursos.py            # Helper para cargar iconos con fallback a wx.ArtProvider
├── motor/
│   ├── gestor_epub.py            # Abre EPUB, limpia HTML, reconstruye índice, mapea posiciones
│   ├── gestor_proyectos.py       # Lógica de proyectos. Persistencia en proyectos.json
│   ├── gestor_atajos.py          # Atajos de teclado configurables por el usuario
│   ├── grabador_audio.py         # Grabación + concatenación FFmpeg + exportación MP3
│   ├── procesador_etiquetas.py   # Parsea {{@voz}} en el texto y fragmenta para grabación
│   ├── reproductor_voz.py        # Cola de audio TTS asíncrona. Orquesta todos los motores.
│   ├── reproductor_sonidos.py    # 12 efectos contextuales. Caché en RAM. Motor wx + fallback.
│   ├── cliente_nube_voces.py     # Descarga listas de voces desde cada API
│   ├── verificador_voces_nuevas.py # Detecta voces nuevas con cooldown de 24h
│   ├── comprobador_actualizaciones.py # Versioning semver contra GitHub
│   ├── control_cuota.py          # Contadores mensuales por proveedor con autoreset
│   ├── troceador_epub.py         # Divide EPUB por anclas HTML. TOC jerárquico y plano.
│   └── limpiador_lectura.py      # Limpieza de texto para TTS (sin HTML, sin ruido)
├── servicios/
│   ├── cliente_azure.py          # Azure Neural TTS. SSML escapado con xml.sax.saxutils.
│   ├── cliente_polly.py          # Amazon Polly. Selección automática de motor (standard/neural/generative).
│   ├── cliente_eleven.py         # ElevenLabs. Multilingüe. Streaming de audio.
│   └── cliente_sapi5.py          # SAPI5 local. Siempre disponible, siempre el fallback.
└── config_rutas.py               # Rutas absolutas. cargar_claves() / guardar_claves(). RAIZ del proyecto.
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

**4. `CheckListCtrlMixin` para casillas de verificación en listas.**

Las casillas nativas de wxPython (`EnableCheckBoxes(True)`) no siempre son anunciadas correctamente por NVDA al navegar con flechas. Usa `wx.lib.mixins.listctrl.CheckListCtrlMixin` combinado con `EnableCheckBoxes(True)` para garantizar el anuncio del estado.

**5. El debounce de 300ms en búsquedas.**

Las búsquedas en la lista de voces usan un temporizador de 300ms para no lanzar filtrado en cada pulsación de tecla. Sin él, NVDA anuncia el texto mientras el usuario sigue escribiendo, lo que resulta caótico.

---

## Logs

El sistema de logs está centralizado en `iniciar_epub_tts.py`:

- **Archivo:** `app/registros/app.log`, máximo 512 KB, 1 backup (`app.log.1`).
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

## Próximos motores de voz

**Piper TTS** es el motor local de alta calidad previsto para reemplazar a SAPI5 como motor local principal. Es open source, no requiere conexión, y tiene modelos en español de alta calidad. La estructura de clientes en `/app/servicios/` está preparada para añadir `cliente_piper.py` siguiendo el mismo patrón que los demás.

---

## Lo que no hacer

- No uses `except: pass` ni `except Exception: pass` sin logging. Si no sabes qué hacer con un error, al menos loguéalo: `logger.exception("contexto")`.
- No accedas a `claves_api.json` directamente desde los clientes de API. Usa `cargar_claves()`.
- No hagas llamadas a APIs desde el hilo principal. El hilo principal es para la UI.
- No añadas dependencias sin justificación. Cada nueva librería es un punto de rotura potencial en la portabilidad.
- No rompas los bloques ANCLAJE sin documentar el cambio en el mensaje de commit.

## Decisiones Técnicas Recientes (Fase 5)

### Gestión de Audio y SAPI 5
- Se ha implementado la grabación SAPI 5 usando `SAPI.SpFileStream` para volcado directo a archivo, evitando la reproducción por altavoz durante el renderizado.
- El estándar de exportación se fija en **MP3 320 kbps** para asegurar compatibilidad total con proyectos de edición profesional en Reaper.
### Reglas de Interfaz (UX Accesible)
- **Slidrs:** No deben exponer la escala completa a la API de accesibilidad. Solo el valor actual.
- **Atajos:** `Control + P` es el comando universal de reproducción. Se prohíbe el uso de la tecla `Espacio` para evitar conflictos de foco con NVDA.
- **Navegación:** Se sustituyen los términos "Atrás/Adelante" por **"Retroceder/Avanzar"** para mayor claridad semántica.
