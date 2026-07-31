# Guía de scripts del proyecto

Este documento explica **para qué sirve cada script del repositorio, cuándo hay que ejecutarlo y en qué orden**, para no tener que recordarlo de memoria cada vez que toca publicar una versión. Está pensado como referencia rápida — para el detalle técnico de cada pieza, ve a `DEVELOPMENT.md` o `GUIA_TECNICA.md`.

---

## Resumen rápido

| Script | ¿Cuándo se ejecuta? | ¿Qué hace? |
|---|---|---|
| `compilar_i18n.py` | Cada vez que edites un `.po` | Compila `locale/*.po` → `locale/*.mo` |
| `subir_version.py` | Al cerrar una versión | Sube el número de versión, prepara `novedades.txt`, hace commit |
| `crear_portable.py` | Al publicar el ZIP portable | Compila `.mo`, empaqueta con PyInstaller, genera el `.zip` de `dist/` |
| `auxiliar_sapi32.py` | Solo si cambias el puente de 32 bits | Se compila **a mano** a `bin/auxiliar_sapi32.exe` (Python de 32 bits) |
| `auxiliar_actualizador.py` | Nunca a mano | Lo compila `crear_portable.py` automáticamente a `bin/actualizador.exe` |
| `winget/*.yaml` | Al publicar una release estable | Manifiesto para enviar la app a Winget (ver más abajo) |

El orden habitual para publicar una versión nueva es:

```
1. Terminar los cambios y probarlos.
2. python compilar_i18n.py     (si tocaste algún .po)
3. python subir_version.py [patch|minor|major]
4. git push origin main
5. python crear_portable.py
6. Publicar el .zip de dist/ como GitHub Release
7. (solo cuando la versión esté estable) actualizar y enviar winget/
```

---

## `compilar_i18n.py` — compilador de traducciones

**Cuándo usarlo:** cada vez que edites cualquier archivo `.po` en `locale/` — ya sea porque añadiste una cadena nueva envuelta en `_()` en el código, ya sea porque corregiste una traducción existente.

**Qué hace:** lee `locale/es/LC_MESSAGES/epub_tts.po` y `locale/en/LC_MESSAGES/epub_tts.po` y genera los `.mo` binarios que `gettext` carga en tiempo real. Es un compilador propio (no depende de `msgfmt` del sistema, para no atar la app a tener gettext instalado en Windows), y si hay un error de sintaxis en algún `.po` te dice exactamente el archivo y la línea.

```
python compilar_i18n.py
```

**Importante:** la app carga el `.mo` directamente, no el `.po`. Si olvidas compilar después de editar un `.po`, el cambio no se verá reflejado al ejecutar la app desde el código fuente. `crear_portable.py` ya lo compila automáticamente antes de empaquetar, así que el portable siempre lleva las traducciones al día aunque tú te olvides — pero al desarrollar en local, hazlo tú mismo tras cada cambio.

Para saber cómo añadir una cadena nueva a `_()` y traducirla, consulta `TRADUCCION.md`.

---

## `subir_version.py` — asistente de versión

**Cuándo usarlo:** cuando decidas que los cambios acumulados ya forman una versión publicable (por ejemplo, tras cerrar una fase o un conjunto de correcciones).

**Qué hace:**
1. Lee la versión actual de `recursos/version.json`.
2. Calcula la nueva según el argumento (`patch`/`minor`/`major`, o un número de versión exacto).
3. Escribe `recursos/version.json` con la nueva versión y la fecha de hoy.
4. Añade una cabecera de versión a `novedades.txt` si no existe ya.
5. Hace `git commit` con esos dos archivos.

```
python subir_version.py             # solo muestra la versión actual, no cambia nada
python subir_version.py patch       # 3.0.0 → 3.0.1
python subir_version.py minor       # 3.0.0 → 3.1.0
python subir_version.py major       # 3.0.0 → 4.0.0
python subir_version.py 3.1.5       # fuerza una versión concreta
```

**Nunca hace `git push` por sí solo** — el commit se queda en local hasta que tú decidas subirlo. Tampoco toca `locale/`, así que si la versión incluye cadenas nuevas, compílalas antes con `compilar_i18n.py`.

---

## `crear_portable.py` — construcción del ZIP portable

**Cuándo usarlo:** cuando quieras generar el paquete que se distribuye a las personas usuarias finales (el `.zip` que se sube como asset de una GitHub Release).

**Qué hace, en orden:**
1. Limpia `dist/` de builds anteriores.
2. Compila `locale/*.po` → `*.mo` (para que el portable siempre lleve las traducciones al día).
3. Ejecuta PyInstaller para generar `epubtts.exe`.
4. Compila `auxiliar_actualizador.py` a `bin/actualizador.exe` (automático, misma arquitectura que la app).
5. Copia `bin/`, `recursos/`, `locale/` al portable, y `ayuda.html` y `novedades.txt` directo a su raíz (junto a `epubtts.exe`, sin carpeta `documentos/` de por medio). Avisa por consola si falta `bin/ffmpeg.exe` o `bin/auxiliar_sapi32.exe`.
6. Crea `configuraciones/` de fábrica (ajustes vacíos, carpetas de backups, etc.) y siembra `registros/` y `registros/errores/` vacías, para que un fallo en el portable tenga dónde escribirse desde el primer arranque.
7. Comprime todo en `dist/epub-tts-accesible-vX.Y.Z.zip`.

```
python crear_portable.py
```

**Requisitos previos:** `pip install pyinstaller`, y `bin/ffmpeg.exe` ya colocado a mano (ver `bin/INSTRUCCIONES.txt`). El `.exe` de `auxiliar_sapi32.py` (ver abajo) también debe existir ya en `bin/` si quieres que el portable soporte voces de 32 bits (Eloquence, RealSpeak) — este script no lo genera, porque necesita un intérprete de Python de 32 bits aparte. Si falta cualquiera de los dos, el script avisa por consola al llegar al paso 5, pero sigue empaquetando igual.

**Cuándo NO hace falta ejecutarlo:** durante el desarrollo normal, cuando pruebas la app con `python iniciar_epub_tts.py`. Es solo para el paso de empaquetado final.

---

## `auxiliar_sapi32.py` — puente de voces SAPI5 de 32 bits

**Cuándo tocarlo:** solo si cambias la lógica de comunicación con voces de 32 bits (Eloquence, RealSpeak de CodeFactory), que no pueden cargarse directamente en el proceso de 64 bits de la app.

**Compilación — es el único ejecutable auxiliar que sigue siendo manual**, porque necesita un intérprete de Python de 32 bits (no el mismo que compila la app principal):

```
python -m PyInstaller --noconsole --onefile --name auxiliar_sapi32 auxiliar_sapi32.py
```

Copia el `.exe` resultante a `bin/auxiliar_sapi32.exe`. Si no está presente, la app simplemente no ofrece voces `local_32` en la lista — no falla, se degrada con elegancia.

---

## `auxiliar_actualizador.py` — instalador del actualizador automático (Fase C)

**Cuándo tocarlo:** si cambias la lógica de respaldo/reemplazo/rollback del actualizador automático.

**Nunca lo compiles a mano** — a diferencia de `auxiliar_sapi32.py`, `crear_portable.py` ya lo compila automáticamente en su paso 4 (misma arquitectura que la app principal, sin necesidad de un intérprete aparte).

**Estado actual:** validado de extremo a extremo en Windows real con NVDA (descarga, verificación, respaldo, reemplazo y reinicio automático) y ya conectado a producción, tanto al botón «Buscar actualizaciones ahora» como a la comprobación automática al arrancar. El botón interno "Probar descarga y verificación (Fase C)" que servía solo para esa validación ya se retiró de Ajustes, porque cumplió su función. El bloque `ANCLAJE_INICIO: ACTUALIZADOR_SCRIPT_CLON` en `pestana_ajustes.py` se conserva sin usarse, como red de seguridad, hasta confirmar dos o tres actualizaciones reales seguidas sin sobresaltos con este mecanismo — entonces se retira del todo.

---

## `winget/` — manifiesto de Windows Package Manager

**Qué es:** los tres archivos YAML estándar (`installer.yaml`, `locale.yaml`, `version.yaml`) que describen la app para que se pueda instalar con `winget install`. No es un script que se ejecute — es un manifiesto que se **envía** al repositorio oficial `microsoft/winget-pkgs` mediante una pull request.

**Cuándo enviarlo (no antes):**
1. **El nombre comercial de la app debe estar decidido de forma definitiva.** Ahora mismo `winget/` usa `TifloTutos.EpubTTSAccesible` como identificador **provisional** — está marcado así con comentarios en los tres archivos. Si cambia el nombre, hay que actualizar `PackageIdentifier`/`PackageName` en los tres YAML antes de enviarlo.
2. **Debe existir una GitHub Release publicada** con el `.zip` portable como asset (el que genera `crear_portable.py`). Winget no acepta manifiestos que apunten a un archivo que no está publicado.
3. **Hay que calcular el SHA256 real** del `.zip` publicado y sustituir el placeholder `PENDIENTE_SHA256_AL_PUBLICAR_RELEASE` en `winget/installer.yaml`:
   ```
   certutil -hashfile epub-tts-accesible-vX.Y.Z.zip SHA256
   ```
   (o en PowerShell: `Get-FileHash epub-tts-accesible-vX.Y.Z.zip -Algorithm SHA256`).

**Cómo enviarlo, una vez cumplidos esos tres puntos:**
1. Valida el manifiesto localmente si tienes el `winget` CLI instalado:
   ```
   winget validate winget/
   winget install --manifest winget/
   ```
2. Haz un fork de `microsoft/winget-pkgs` y copia los tres archivos a la ruta que exige su estructura de carpetas:
   `manifests/t/TifloTutos/EpubTTSAccesible/X.Y.Z/`
3. Abre una pull request contra `microsoft/winget-pkgs`. Su bot de validación automática (`AzurePipelines`) revisa el manifiesto; si todo está bien, un revisor humano lo aprueba y la app queda disponible vía `winget install`.
4. **Cada versión nueva es un manifiesto nuevo** — hay que repetir el proceso completo con la carpeta `X.Y.Z` correspondiente (aunque solo cambien versión y SHA256, ya que el `PackageIdentifier` no cambia entre versiones).

Más detalle y contexto en `winget/LEEME.txt`.

---

## Otros archivos que no son scripts pero conviene ubicar

- `bin/INSTRUCCIONES.txt` — qué colocar a mano en `bin/` antes de generar el portable (FFmpeg, y opcionalmente el `.exe` de `auxiliar_sapi32.py`).
- `TRADUCCION.md` — guía paso a paso para traducir cadenas nuevas, pensada para quien no conoce el formato `.po`.
- `iniciar_epub_tts.py` — el punto de entrada de la app cuando se ejecuta desde el código fuente (`python iniciar_epub_tts.py`); es lo que empaqueta `crear_portable.py` con PyInstaller, no un script de mantenimiento.
