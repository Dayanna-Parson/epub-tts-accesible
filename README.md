# TifloHistorias — Epub TTS Accesible

**Aplicación de escritorio para Windows que convierte libros EPUB en audiolibros con síntesis de voz multivoz, diseñada desde cero por y para personas ciegas.**

[![Versión](https://img.shields.io/badge/versión-1.0.0-blue)](https://github.com/Dayanna-Parson/epub-tts-accesible/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-yellow)](https://www.python.org/)
[![Accesibilidad](https://img.shields.io/badge/accesibilidad-NVDA%20100%25-green)](#accesibilidad)
[![Licencia](https://img.shields.io/badge/licencia-por%20definir-lightgrey)](#licencia)

---

## ¿Qué es esto?

TifloHistorias no es un reproductor de EPUB con TTS añadido a posteriori. Es una herramienta de producción de audiolibros multivoz construida desde el primer día con una premisa clara: **funcionar completamente con lector de pantalla, sin compromisos**.

La aplicación nace de un problema real. Producir audiolibros complejos en Windows siendo ciega implicaba saltar entre Word, una aplicación Android, transferencias de archivos y Reaper. Era un flujo frágil, lento y mentalmente agotador. No había ninguna herramienta de escritorio que lo hiciera todo junto de forma accesible.

TifloHistorias es esa herramienta.

---

## Para quién es

- Personas ciegas o con baja visión que usan NVDA u otro lector de pantalla.
- Usuarios que quieren escuchar libros EPUB con voces neurales de calidad en Windows.
- Productores de audiolibros que necesitan flujos multivoz controlados y portables.
- Desarrolladores que quieren explorar cómo se construye una app real de accesibilidad en Python.

---

## Qué puedes hacer

### Modo Lectura
- Abrir y leer libros en formato EPUB con navegación por índice jerárquico.
- Escuchar el contenido con cualquiera de tus voces favoritas: Azure Neural, Amazon Polly, ElevenLabs o SAPI5 local.
- Pausar, reanudar y saltar adelante o atrás con tiempos configurables.
- Guardar marcadores con nombre y volver a ellos cuando quieras.
- La app recuerda exactamente en qué posición estabas la última vez que ceraste el libro.
- Control de cuota mensual por proveedor: si te acercas al límite, la app cambia automáticamente a voz local.

### Modo Grabación
- Carga de archivos TXT con etiquetas de voz (`{{@narrador}}`, `{{@personaje}}`, etc.).
- Asignación de voces distintas a cada etiqueta, de cualquier proveedor.
- Grabación fragmentada por voz o grabación continua, según la opción de etiquetas.
- Exportación a MP3 a 320 kbps mediante FFmpeg portable (sin instalación global).
- Retroalimentación sonora en tiempo real: sonidos de inicio, progreso y finalización.

### Gestor de Proyectos
- Árbol jerárquico de proyectos y subproyectos con accesibilidad NVDA total.
- Multicategorización con casillas de verificación: Serie, Libro, Fantasía, Distopía, Tecno-thriller y más.
- `Ctrl+Intro` abre directamente la carpeta de grabaciones del proyecto en el Explorador.
- `Ctrl+Shift+P` abre el gestor desde cualquier parte de la app.
- Papelera con posibilidad de restaurar proyectos eliminados recientemente.
- El árbol navega automáticamente al nodo del archivo TXT que tengas cargado en el modo Grabación.

### Otras funciones
- **Divisor de EPUB integrado**: trocea cualquier EPUB por capítulos sin salir de la app, con soporte para anclas HTML y dos tipos de tabla de contenidos.
- **Sistema de versiones**: la app te avisa cuando hay una actualización disponible y muestra las novedades.
- **Notificaciones de voces nuevas**: si un proveedor añade voces nuevas desde la última vez que consultaste, la app te lo dice al arrancar (con cooldown de 24h para no molestar).
- **Feedback sonoro**: 12 efectos contextuales que refuerzan cada acción sin interferir con NVDA. Inicio y fin de grabación, navegación por listas, éxito, error, apertura de carpetas.

---

## Motores de voz

| Motor | Tipo | Rol |
|---|---|---|
| **Microsoft Azure Neural TTS** | Nube | Motor principal para lectura y grabación |
| **Amazon Polly** | Nube | Motor alternativo con voces generativas |
| **ElevenLabs** | Nube | Voces expresivas y multilingües |
| **SAPI5** | Local | Respaldo offline, siempre disponible sin coste |
| **Piper TTS** *(próximo)* | Local | Motor local de alta calidad, sin dependencias de nube |

Si falla una API o no hay conexión, la app pasa automáticamente a voz local. Si además se supera el límite mensual configurado, también cambia automáticamente.

---

## Sistema de voces

Las voces no se consultan en tiempo real en cada reproducción. La app las descarga una sola vez, las guarda en caché local y trabaja desde ahí. Puedes usar la app sin conexión usando las voces ya descargadas o SAPI5.

El sistema de **favoritas** es clave para el día a día: marcas las voces que usas habitualmente y son las únicas que aparecen en el selector durante la lectura. Puedes filtrar por idioma, proveedor, tipo de voz (femenino, masculino, multilingüe, Dragon HD) y texto libre.

---

## Accesibilidad

TifloHistorias está diseñada para funcionar al 100% con teclado y lector de pantalla. No es una adaptación posterior, es la base del proyecto.

- Todos los controles usan controles nativos de Windows (wxPython), anunciados correctamente por NVDA.
- Los diálogos devuelven el foco exactamente al control desde el que se abrieron.
- Las casillas de verificación anuncian su estado (marcado/desmarcado) al navegar con las flechas.
- Los árboles de proyectos anuncian el nombre, nivel y estado de cada nodo.
- Ninguna operación pesada bloquea la interfaz: las cargas ocurren en hilos secundarios con `wx.CallAfter` para que el foco llegue de forma inmediata.
- Los 12 sonidos contextuales están diseñados para no superponerse con la voz de NVDA.

---

## Atajos principales

| Atajo | Acción |
|---|---|
| `Ctrl+O` | Abrir libro EPUB |
| `Ctrl+Shift+P` | Abrir Gestor de Proyectos |
| `Ctrl+Intro` (en proyecto) | Abrir carpeta del proyecto en el Explorador |
| `Ctrl+Arriba / Ctrl+Abajo` | Reordenar proyecto en el árbol |
| `F2` (en proyecto) | Renombrar inline |
| `Supr` (en proyecto) | Eliminar proyecto |
| `Tecla Menú / Shift+F10` | Menú contextual del nodo |
| `Escape` (en diálogos) | Cerrar y devolver foco |

> Los atajos de reproducción (play, pausa, salto) son configurables desde la pestaña de Ajustes.

---

## Instalación

**Requisitos:** Windows 10/11, Python 3.12+, FFmpeg (incluido en `/bin/`).

```bash
git clone https://github.com/Dayanna-Parson/epub-tts-accesible.git
cd epub-tts-accesible
pip install -r requisitos.txt
python iniciar_epub_tts.py
```

O usa el ejecutable portable desde [Releases](https://github.com/Dayanna-Parson/epub-tts-accesible/releases) si prefieres no instalar nada.

### Configuración de claves API

Crea el archivo `configuraciones/claves_api.json` con tus claves:

```json
{
  "azure_key": "TU_CLAVE_AZURE",
  "azure_region": "TU_REGION",
  "polly_key": "TU_ACCESS_KEY",
  "polly_secret": "TU_SECRET_KEY",
  "eleven_key": "TU_CLAVE_ELEVEN"
}
```

Sin claves, la app funciona con SAPI5 local sin ningún problema.

---

## Estructura del proyecto

```
epub-tts-accesible/
├── app/
│   ├── interfaz/          # Ventanas, pestañas y diálogos (wxPython)
│   ├── motor/             # Lógica: proyectos, grabación, TTS, sonidos, EPUB
│   └── servicios/         # Clientes de APIs: Azure, Polly, ElevenLabs, SAPI5
├── bin/                   # FFmpeg portable (no requiere instalación global)
├── configuraciones/       # JSON locales (claves, ajustes, proyectos) — en .gitignore
├── recursos/
│   ├── iconos/            # Iconos .png de la interfaz
│   └── sonidos/           # Efectos .wav (12 archivos, cargados en RAM al arrancar)
├── documentos/            # Bitácora de desarrollo y documentación interna
├── version.json           # Versión actual para el sistema de actualizaciones
├── requisitos.txt         # Dependencias Python
└── iniciar_epub_tts.py    # Punto de entrada
```

---

## Por qué el código está en español

Es una decisión deliberada. Este es mi primer proyecto grande y trabajar en mi idioma reduce los errores conceptuales, mejora la legibilidad y es coherente con la interfaz y el público. No es una limitación técnica.

---

## Documentación adicional

- [`DEVELOPMENT.md`](DEVELOPMENT.md) — Guía técnica para desarrolladores: arquitectura, convenciones y decisiones de diseño.
- [`BITACORA_DE_DESARROLLO.md`](BITACORA_DE_DESARROLLO.md) — Historia completa del proyecto: de dónde viene, por qué casi muere y cómo llegó hasta aquí.

---

## Audiolibros

¿Te gusta el proyecto? Descubre [Tiflohistorias](https://tiflotutos.com/tiflohistorias), la sección de audiolibros de tiflotutos.com, pensada especialmente para personas con discapacidad visual.

---

## Créditos

- **Desarrollo y diseño:** Dayanna Parson
- **Asistencia técnica IA:** Claude (Anthropic)

---

## Licencia

Por definir.
