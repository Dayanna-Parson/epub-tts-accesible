# Epub TTS Accesible

> Aplicación de escritorio accesible para Windows — lee libros EPUB y crea audiolibros multivoz con síntesis de voz neuronal.

**Desarrollada por [Dayanna Parson (TifloTutos)](https://tiflotutos.com) · Versión 1.2.0**

---

## ¿Qué es?

Epub TTS Accesible es una aplicación de escritorio para Windows, escrita en Python, pensada para que personas ciegas puedan leer y trabajar con libros EPUB de forma cómoda, controlada y accesible, utilizando distintos motores de síntesis de voz.

Nace de una necesidad real: poder leer libros largos en el PC y preparar audiolibros multivoz, sin depender de flujos frágiles ni de herramientas pensadas para móvil.

---

## ¿Para quién está pensada?

- Personas ciegas o con baja visión que usan lector de pantalla (NVDA).
- Usuarios que quieran escuchar libros EPUB con TTS en Windows.
- Personas interesadas en la producción de audiolibros.
- Desarrolladoras que quieran explorar un proyecto real de accesibilidad en Python.

---

## Qué puedes hacer

- Abrir y leer libros en formato EPUB con navegación por índice.
- Escuchar el contenido con distintas voces TTS, sin pausas entre fragmentos.
- Pausar, reanudar y moverte por el texto con saltos configurables.
- Añadir y gestionar marcadores.
- Grabar audiolibros multivoz con etiquetas de personaje (`{{@narrador}}`, `{{@james}}`...).
- Exportar en MP3 a 320 kbps, normalizado a 44 100 Hz para edición en DAW.
- Corregir pronunciaciones incorrectas con el diccionario propio.
- Controlar el consumo de cada API con límites y avisos automáticos.
- Instalar actualizaciones directamente desde la propia aplicación.

---

## Síntesis de voz

| Motor | Tipo | Notas |
|---|---|---|
| SAPI5 | Local | Siempre disponible, sin conexión ni coste |
| Microsoft Azure TTS | Nube | Motor neuronal principal |
| Amazon Polly | Nube | Motor neuronal alternativo |
| **Deepgram Aura-2** | Nube | **Recomendado** — pay-as-you-go, sin suscripción mensual fija |
| ElevenLabs | Nube | Voces expresivas y multilingües |

Si no hay conexión o se alcanza un límite de cuota, la app cambia automáticamente a voz local.

---

## Accesibilidad

Diseñada desde el principio para funcionar con NVDA y lectores de pantalla:

- Controles nativos de Windows, accesibles por definición.
- Uso completo con teclado — ningún flujo requiere ratón.
- Diálogos que no pierden el foco al cerrarse.
- Sin ventanas de consola al arrancar: NVDA no verbaliza textos técnicos de inicio.

---

## Atajos principales

| Atajo | Acción |
|---|---|
| `Control + 1` | Modo Lectura |
| `Control + 2` | Modo Grabación |
| `Control + 3` | Ajustes |
| `Control + O` | Abrir EPUB / carpeta |
| `Control + P` | Reproducir / Pausar |
| `F1` | Abrir manual de usuario |

---

## Estado actual

**Versión 1.2.0 — aplicación completa y estable.**

- Modo lectura con voces de Azure, Amazon Polly, Deepgram y ElevenLabs.
- Modo grabación multivoz con etiquetas de personaje.
- Exportación MP3 a 320 kbps, normalizado a 44 100 Hz.
- Diccionario de pronunciación para todos los motores.
- Control de cuota y avisos de gasto por proveedor.
- Actualizaciones automáticas desde la propia app.
- Manual de usuario accesible integrado (`F1`).

---

## Manual de usuario

Incluido en la aplicación. Ábrelo con **F1** desde cualquier pestaña, o abre directamente el archivo `ayuda.html`.

---

## Descarga

Visita la [página de releases](https://github.com/Dayanna-Parson/epub-tts-accesible/releases) para descargar la última versión.

---

## Documentación

| Archivo | Contenido |
|---|---|
| [`novedades.txt`](novedades.txt) | Historial de cambios por versión |
| [`ayuda.html`](ayuda.html) | Manual de usuario completo |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Guía técnica para desarrolladoras |

---

## Licencia

Por definir.
