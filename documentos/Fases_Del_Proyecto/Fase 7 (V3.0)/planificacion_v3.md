# Fase 7 — Planificación de la versión 3.0

Documento de diseño cerrado antes de escribir código. Recoge el plano completo de la v3.0: base de datos, flujos, arquitectura de interfaz y decisiones pendientes. No es un registro de conversación — es la especificación de referencia para desarrollarla.

---

## 1. Resumen de alcance

La v3.0 añade a Epub TTS Accesible:

1. Pestaña **Biblioteca**: indexación de la colección de libros (EPUB y PDF) sin copiar archivos, con filtros, estado de lectura y organización por categorías/etiquetas.
2. Pestaña **Creador de Audiolibros**: exportación de libro completo o por capítulos a MP3, con cálculo de presupuesto previo y gestión de cuota insuficiente.
3. Soporte de **PDF** como formato de entrada, con limpieza propia antes de entrar a la tubería de audio.
4. **Asistente de Biblioteca** basado en Gemini, con contexto del libro activo.
5. **Actualizador automático** con ejecutable auxiliar precompilado (evita los problemas de antivirus y permisos de Windows detectados en la v2.0).
6. Internacionalización (i18n) con `gettext` y preparación del manifiesto de **Winget**.
7. Nombre comercial de la app — **pendiente de decidir al cierre de la v3.0** (se descartó "TifloReader" por posible colisión con un dispositivo lector físico existente en el mercado; "TifloVoice" y "TifloEstudio" fueron valorados y descartados por no encajar con el tono ni con el alcance real de la app).

---

## 2. Fase A — Biblioteca y base de datos

### 2.1 Por qué SQLite y no JSON

Los archivos de configuración actuales (`ajustes.json`, `claves_api.json`, etc.) siguen siendo JSON: son datos pequeños, estáticos, que solo cambian cuando el usuario entra deliberadamente a Ajustes. Se quedan como están.

La Biblioteca es un caso distinto: cientos de libros, con escritura frecuente (posición de lectura, favoritos, estado) y necesidad de filtros rápidos. Para ese perfil de uso, JSON tiene tres problemas reales:

- Cada escritura reescribe el archivo completo, aunque solo cambie un campo.
- No hay journaling: un cierre inesperado a mitad de escritura corrompe el archivo entero.
- Filtrar u ordenar requiere cargar todo en memoria y recorrerlo con bucles.

SQLite resuelve los tres de forma nativa: escrituras quirúrgicas por fila, transacciones ACID con journaling (modo WAL), e índices para filtros instantáneos. No añade ninguna dependencia nueva — `sqlite3` viene en la librería estándar de Python — y el archivo `biblioteca.db` se empaqueta igual que cualquier otro archivo de `configuraciones/`, sin instalación ni servicio adicional.

Regla general para futuras decisiones de almacenamiento: **JSON para configuración pequeña y estática; SQLite para colecciones grandes con escritura y consulta frecuentes.**

### 2.2 Esquema de base de datos (`biblioteca.db`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE autores (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE etiquetas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE libros (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta_archivo          TEXT NOT NULL UNIQUE,
    titulo                TEXT NOT NULL,
    formato               TEXT NOT NULL CHECK (formato IN ('epub', 'pdf')),
    id_categoria          INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
    fecha_añadido         TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_punto_lectura  INTEGER NOT NULL DEFAULT 0,
    metadatos_json        TEXT,
    favorito              INTEGER NOT NULL DEFAULT 0 CHECK (favorito IN (0,1)),
    en_pendientes         INTEGER NOT NULL DEFAULT 0 CHECK (en_pendientes IN (0,1)),
    leyendo_ahora         INTEGER NOT NULL DEFAULT 0 CHECK (leyendo_ahora IN (0,1)),
    leido                 INTEGER NOT NULL DEFAULT 0 CHECK (leido IN (0,1)),
    titulo_revisado       INTEGER NOT NULL DEFAULT 1 CHECK (titulo_revisado IN (0,1))
);

CREATE TABLE libro_autor (
    id_libro   INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_autor   INTEGER NOT NULL REFERENCES autores(id) ON DELETE CASCADE,
    PRIMARY KEY (id_libro, id_autor)
);

CREATE TABLE libro_etiqueta (
    id_libro    INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_etiqueta INTEGER NOT NULL REFERENCES etiquetas(id) ON DELETE CASCADE,
    PRIMARY KEY (id_libro, id_etiqueta)
);

CREATE TABLE diccionario_reglas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patron_origen  TEXT NOT NULL,
    sustitucion    TEXT NOT NULL,
    tipo_alcance   TEXT NOT NULL CHECK (tipo_alcance IN ('global','libro','saga')),
    id_referencia  INTEGER
);

CREATE TABLE exportaciones_pendientes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id_libro            INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    modo                TEXT NOT NULL CHECK (modo IN ('completo', 'capitulos')),
    proveedor           TEXT NOT NULL,
    punto_corte         INTEGER,          -- carácter donde se cortó (modo 'completo')
    capitulo_pendiente  INTEGER,          -- índice de capítulo pendiente (modo 'capitulos')
    ruta_parcial        TEXT              -- ruta del archivo parcial ya generado
);

CREATE INDEX idx_libros_categoria   ON libros(id_categoria);
CREATE INDEX idx_libros_favorito    ON libros(favorito);
CREATE INDEX idx_libros_pendientes  ON libros(en_pendientes);
CREATE INDEX idx_libros_leyendo     ON libros(leyendo_ahora);
CREATE INDEX idx_libros_leido       ON libros(leido);
CREATE INDEX idx_libro_autor_autor  ON libro_autor(id_autor);
CREATE INDEX idx_libro_etiq_etiq    ON libro_etiqueta(id_etiqueta);
CREATE INDEX idx_dicc_alcance       ON diccionario_reglas(tipo_alcance, id_referencia);
```

Notas de diseño:

- `ruta_archivo UNIQUE` evita duplicados al reimportar la misma carpeta.
- `ON DELETE CASCADE` en las tablas de unión limpia relaciones huérfanas automáticamente al borrar un libro.
- `ON DELETE SET NULL` en `id_categoria`: borrar una categoría no borra los libros, solo los deja sin categoría.
- `COLLATE NOCASE` evita duplicar autores/categorías por diferencias de mayúsculas.
- `autores` es una tabla normalizada en relación N:N con `libros` (un libro puede tener varios autores; un autor tiene varios libros), en vez de texto libre repetido.
- `categorias` (una por libro, tipo género) y `etiquetas` (varias por libro, tipo saga o colección personalizada) son conceptos separados: un libro pertenece a un único género pero puede estar en varias colecciones a la vez.
- El estado de lectura se modela con cuatro banderas independientes (`favorito`, `en_pendientes`, `leyendo_ahora`, `leido`) en vez de un único campo, para permitir combinaciones reales de uso ("favorito y ya leído", "pendiente pero no favorito", etc.).
- `metadatos_json` almacena datos secundarios que no necesitan ser consultables por SQL (portada, idioma, editorial) sin inflar el esquema de columnas.
- `titulo_revisado` marca si el título almacenado coincide razonablemente con el nombre de archivo original o si proviene de una discrepancia sin resolver entre archivo y metadatos internos (ver sección 2.7). Por defecto `1` (revisado) para no marcar de más; se pone a `0` solo cuando el escáner detecta una discrepancia notable.
- `exportaciones_pendientes` registra exportaciones de audiolibro cortadas por falta de cuota, para poder retomarlas sin regrabar lo ya hecho (ver sección 4.3).

Migraciones futuras: se controla la versión del esquema con `PRAGMA user_version`, no con una librería externa de migraciones — con un único desarrollador y una base de datos de un solo usuario, un bloque de migración manual por versión es suficiente y no añade dependencias.

### 2.3 Escáner de carpetas en segundo plano

Objetivo: importar cientos de libros sin bloquear la interfaz ni silenciar NVDA.

1. El usuario elige una carpeta con `wx.DirDialog`.
2. Un hilo coordinador (`threading.Thread`) arranca de inmediato; la interfaz queda libre. Se anuncia con el patrón `_anunciador`: "Escaneando carpeta...".
3. El coordinador hace `os.walk` para listar rutas candidatas (`.epub`, `.pdf`) — es una operación rápida de solo listar, no de parsear contenido.
4. Se descartan las rutas que ya existan en `libros.ruta_archivo` (una única consulta `SELECT ruta_archivo FROM libros`, comparación en memoria), para que reimportar una carpeta no duplique ni reprocese libros ya indexados.
5. Las rutas nuevas se reparten entre un `ThreadPoolExecutor(max_workers=8)`. Cada worker abre el archivo y extrae metadatos ligeros (título, autor, formato) sin tocar SQLite directamente — solo devuelve los datos.
6. El coordinador acumula resultados e inserta por lotes (`executemany`, cada ~50 libros) dentro de una única transacción, en vez de una escritura por libro.
7. Cada lote insertado dispara `wx.CallAfter` para actualizar el contador visible; cada 50 libros se anuncia con NVDA un progreso discreto ("50 libros indexados...").
8. Al finalizar: anuncio final ("Escaneo completado. N libros añadidos."), refresco de la lista con `Freeze()/Thaw()`, foco a la lista de libros.
9. Un archivo que falle al parsear (EPUB corrupto, PDF protegido) se registra con `logger.exception(...)` y se salta — un archivo malo nunca detiene el escaneo completo.

### 2.3.1 Agrupamiento sugerido por carpeta (sagas y colecciones)

Es habitual organizar los libros en carpetas por saga o colección (por ejemplo, una carpeta madre con una subcarpeta por saga, y dentro los libros sueltos para autoconclusivos). El escáner no puede asumir ninguna convención de nombres concreta — guiones, guiones bajos, orden "título - autor" u otro cualquiera — porque cada usuario organiza su colección a su manera. La estructura de carpetas se trata siempre como una **pista opcional**, nunca como una regla rígida; los metadatos internos del libro siguen siendo la única fuente de verdad para título y autor (sección 2.7).

Lo único que sí se puede generalizar sin asumir una convención concreta: si una carpeta contiene **dos o más libros**, es una señal razonable de que están agrupados a propósito. Una carpeta con un único archivo suelto no genera ninguna sugerencia.

1. Durante el escaneo, el coordinador agrupa las rutas candidatas por su carpeta contenedora inmediata, además de listarlas.
2. Al finalizar, si se detectaron carpetas con 2 o más libros, se muestra un diálogo de confirmación (mismo patrón de bautizo ya usado en Grabación y en la sección 2.7) con una lista editable: una fila por carpeta detectada, con el nombre de carpeta propuesto como etiqueta y una casilla para incluirla o excluirla. El usuario puede editar el nombre antes de confirmar o desmarcar la fila si no quiere agrupar esa carpeta.
3. Al confirmar, se crea (u obtiene) la etiqueta correspondiente y se asigna a todos los libros de esa carpeta mediante `libro_etiqueta` — nunca de forma automática y silenciosa.
4. Esta sugerencia se ofrece una sola vez por carpeta detectada; las carpetas ya evaluadas (aceptadas o descartadas explícitamente) no vuelven a preguntarse en escaneos posteriores de la misma raíz.

**Nombres de archivo sin metadatos disponibles:** si un libro no tiene título en sus metadatos internos y hay que recurrir al nombre de archivo como estimación, se reemplazan guiones y guiones bajos por espacios y se recortan espacios sobrantes antes de mostrarlo como propuesta editable en el flujo de bautizo — nunca se aplican mayúsculas automáticas agresivas, que podrían destrozar acrónimos o nombres propios.

### 2.4 Re-enrutado de archivos movidos o borrados

1. Al pulsar Enter sobre un libro: `os.path.exists(ruta_archivo)` (comprobación instantánea en el hilo principal).
2. Si existe: flujo normal — cambia a Lectura, carga `ultimo_punto_lectura`, foco al área de lectura.
3. Si no existe: se abre un diálogo modal de localización con dos opciones — **Localizar archivo** (`wx.FileDialog` filtrado por la extensión original, con aviso si el nombre elegido no coincide con el original) o **Eliminar de la biblioteca**. Al localizar, se actualiza `ruta_archivo` en SQLite y continúa el flujo de apertura sin repetir la acción.
4. Para el caso de mover una carpeta completa (no un solo libro): el mismo diálogo ofrece un tercer botón, **Volver a escanear una carpeta**, que reutiliza el flujo del escáner (2.3) casando por nombre de archivo en vez de por ruta completa, para reconciliar en bloque sin preguntar libro por libro.

### 2.5 Soporte de PDF

El escaneo de la Biblioteca solo extrae metadatos ligeros de los PDF (título si existe, o nombre de archivo como respaldo, número de páginas) — la limpieza pesada no se ejecuta durante la importación masiva, solo cuando el usuario abre el libro.

**Librerías:** `PyMuPDF` (paquete `pymupdf`, se importa como `fitz`) para la extracción, y `ftfy` para normalización de texto. Se descarta `pdfplumber` como opción inicial: está más orientado a extracción tabular/precisa por coordenadas, mientras que `PyMuPDF` ofrece extracción de texto en **modo de bloques y orden de lectura lógico** (`page.get_text("blocks")`), que ya resuelve gran parte del problema de columnas y orden de lectura sin heurística propia. Es además la librería usada por Bookworm como base común para varios formatos de documento, lo que respalda su madurez y mantenimiento. `ftfy` es una dependencia mínima (una función, sin dependencias pesadas) que corrige comillas curvas y errores de codificación Unicode que de otro modo llegarían intactos al motor de voz.

Módulo nuevo `limpiador_pdf.py` (hermano de `limpiador_lectura.py`), que recibe los bloques de texto extraídos por página con `PyMuPDF` y aplica, en orden:

1. **Normalización Unicode**: cada bloque de texto pasa por `ftfy.fix_text()` antes de cualquier otro procesamiento.
2. **Números de página sueltos**: una línea compuesta solo por dígitos (o con guiones tipo "- 124 -") al inicio o final de página se descarta. El modo de bloques en orden de lectura no elimina esto por sí solo, así que se mantiene esta heurística propia.
3. **Cabeceras y pies repetidos**: se registra el primer y último bloque de cada página; si un bloque (o una variante muy similar tras normalizar espacios/números) aparece en el 70% o más de las páginas, se descarta en las páginas siguientes. Se mantiene como red de seguridad adicional, aunque el modo "orden de lectura" de `PyMuPDF` ya reduce buena parte de este ruido frente al enfoque por coordenadas crudas.
4. **Unión de líneas rotas**: dentro de cada bloque, una línea que no termine en `. ! ? : ;` ni en cierre de comillas/paréntesis se concatena con la siguiente mediante un espacio. Si termina en guion de partición de palabra, se une sin espacio y sin el guion.
5. **Notas al pie**: bloques que empiezan con un número seguido de espacio, situados al final de página y separados del cuerpo principal por su posición, se extraen aparte y no se envían al motor de voz.
6. El texto limpio resultante entra por el mismo punto que el texto de EPUB: mismo `diccionario_pronunciacion.py`, mismo motor de voz, sin bifurcar la tubería de audio.

Se incorpora además un caché en memoria (diccionario simple, sin necesidad de LRU sofisticado a la escala de esta app) de páginas ya extraídas y limpiadas por sesión de lectura, para no repetir el procesamiento si el usuario retrocede a una página ya visitada.

### 2.6 Navegación, Ctrl+I e "ir a página" en PDF

Todo el comportamiento de la pestaña Lectura ya existente para EPUB (`Ctrl+I` para anunciar posición, diálogo de "Ir a página X", navegación por encabezados con `H`/`Shift+H`) se extiende a PDF a través del mismo punto de entrada de la tubería — no se duplica lógica de interfaz, solo cambia el origen del texto y el modelo de paginación subyacente:

- **Página**: en EPUB la paginación es virtual (fragmentos de texto calculados por la propia app). En PDF, la página **es la página real y numerada del archivo** — más simple, porque no hay que calcular nada: "ir a página X" mapea directamente al índice de página de `PyMuPDF`. `Ctrl+I` anuncia el número de página real del documento, no una posición estimada.
- **Capítulo**: `PyMuPDF` expone el índice de contenidos del PDF si existe (`documento.get_toc()`), que se usa para la navegación por encabezados (`H`/`Shift+H`) igual que con los capítulos del EPUB. Si el PDF no tiene índice de contenidos embebido (muchos PDF escaneados o mal generados no lo tienen), la navegación por capítulo se desactiva para ese libro concreto y solo queda disponible la navegación por página — se anuncia este límite al abrir el libro ("Este PDF no tiene índice de capítulos; disponible solo navegación por página.") en vez de fallar silenciosamente o simular capítulos falsos.
- El resto de la experiencia (marcadores, diccionario de pronunciación, velocidad, voces) es idéntico entre EPUB y PDF, porque ambos convergen en la misma tubería de audio tras pasar por su limpiador correspondiente.

### 2.7 Coherencia entre nombre de archivo y título real

Es habitual que el nombre de archivo de un EPUB o PDF descargado no coincida con el título real del libro (mayúsculas distintas, abreviaturas, información añadida por quien lo compartió, etc.). La app ya resuelve un problema similar en Grabación de Fragmentos mediante un flujo de **"bautizo"**: un campo de texto donde el usuario confirma o corrige el título antes de que se use para nombrar carpetas y archivos, saneado con la función ya existente `limpiar_nombre_archivo()` (en `procesador_etiquetas.py`). Ese patrón de confirmación explícita es el que se reutiliza aquí, en vez de renombrar archivos de forma silenciosa y automática.

Diseño para Biblioteca y Creador de Audiolibros:

1. **Durante el escaneo** (sección 2.3), cada worker extrae, además del nombre de archivo, el título de los metadatos internos (`ebooklib`: `book.get_metadata('DC', 'title')` en EPUB; metadatos de documento de `PyMuPDF` en PDF). Si ese título difiere de forma notable del nombre de archivo (sin extensión), el libro se inserta con `titulo = <título de metadatos>` pero `titulo_revisado = 0`. Si no hay metadatos de título disponibles, o coinciden razonablemente, se inserta con `titulo_revisado = 1` sin marcar nada.
2. **No se renombra ningún archivo físico durante el escaneo masivo.** Igual que el calculador de presupuesto no lanza un diálogo por capítulo, el escáner no puede detenerse a preguntar por cada uno de 500 libros — el renombrado físico es siempre una acción explícita y posterior del usuario.
3. **En la Biblioteca**, los libros con `titulo_revisado = 0` se distinguen con un indicador discreto en la lista (por ejemplo, una columna o marca de estado, sin sonido ni interrupción). Desde el menú contextual: **Renombrar archivo según metadatos**, que abre el mismo tipo de diálogo de confirmación de Grabación (editable, con el título de metadatos como valor propuesto, no aplicado a ciegas). Al confirmar:
   - Se sanea el nombre con `limpiar_nombre_archivo()`.
   - Se renombra el archivo físico en disco (`os.rename()`).
   - Se actualiza `ruta_archivo`, `titulo` y `titulo_revisado = 1` en la misma operación sobre `libros`.
4. **Acción por lotes**, también desde el menú de Biblioteca: **Renombrar todos los pendientes de revisión**, que recorre los libros con `titulo_revisado = 0` aplicando el mismo bautizo, con opción de confirmar uno a uno o aceptar todos de una vez tras revisar la lista propuesta — para no obligar a repetir la acción manualmente en colecciones grandes.
5. **Creador de Audiolibros**: no necesita lógica adicional. La nomenclatura de salida ya definida en la sección 3.5 (`Título del libro.mp3`, `1. Capítulo uno.mp3`) toma el valor de `libros.titulo`, así que en cuanto ese campo es correcto — por venir de metadatos limpios o por haber sido bautizado manualmente — la exportación hereda el nombre correcto sin ningún cambio adicional en esa pestaña.

### 2.7.1 Seguridad del renombrado por lotes: nunca desincronizar la base de datos

El renombrado por lotes no se ejecuta como una única transacción sobre varios archivos, sino como una secuencia de operaciones atómicas independientes, cada una verificada antes de tocar SQLite:

1. Antes de iniciar el lote, se comprueba `os.access(carpeta, os.W_OK)` sobre la carpeta contenedora; si no hay permiso de escritura, se avisa y no se intenta ningún archivo.
2. Por cada libro: `os.rename()` dentro de un bloque `try/except`. Solo si el renombrado tiene éxito — verificado además comprobando `os.path.exists()` sobre la ruta nueva — se actualiza `ruta_archivo`, `titulo` y `titulo_revisado = 1` en `libros`, como una escritura individual inmediata, no como parte de un `UPDATE` conjunto.
3. Si un archivo falla (permisos, bloqueo por antivirus, carpeta sincronizada con un servicio en la nube tipo OneDrive/Dropbox que retiene el archivo momentáneamente, etc.), se captura la excepción con `logger.exception(...)`, el registro del libro se deja exactamente como estaba (misma ruta, `titulo_revisado` sigue en `0`), y el lote continúa con el siguiente archivo sin detenerse.
4. Al finalizar el lote se muestra un único resumen (no un diálogo por archivo): número de renombrados correctamente y lista de los que fallaron con su motivo, para reintentarlos cuando el usuario quiera.

Con este diseño, el peor caso posible es que algunos libros queden sin renombrar — nunca que la base de datos apunte a una ruta que ya no existe, porque la actualización de `ruta_archivo` depende siempre del resultado verificado del renombrado físico, archivo por archivo.

---

## 3. Fase B — Creador de Audiolibros

### 3.1 Flujo general

Pestaña independiente (no una variante de Grabación de Fragmentos), a la que se llega navegando manualmente (`Ctrl+O`) o desde la Biblioteca mediante la opción **Enviar a Creador de Audiolibros** del menú contextual, que precarga el libro seleccionado.

Controles: información del libro cargado, selector de modo (**Libro completo** en un solo MP3, o **Por capítulos** en un MP3 por capítulo, reutilizando `troceador_epub.py`), selector de voz/proveedor, botón **Calcular presupuesto** y botón **Iniciar exportación** (habilitado solo tras calcular presupuesto con la configuración actual).

### 3.2 Calculador de presupuesto

1. Al pulsar "Calcular presupuesto", un hilo secundario cuenta los caracteres del texto ya limpio (vía `limpiador_lectura.py` o `limpiador_pdf.py`), sin generar audio.
2. Se aplica la tarifa del proveedor seleccionado.
3. Se muestra un único `wx.MessageDialog` con: caracteres totales, coste estimado total, coste medio por capítulo si aplica, y aviso si se supera el límite de cuota configurado en Ajustes. Nunca se lanzan múltiples alertas por capítulo.
4. NVDA lo anuncia una vez, al abrirse el diálogo modal, con foco en el botón "Continuar".
5. Al confirmar, la exportación arranca en hilo de fondo reutilizando la cola TTS y la caché ya existentes en `reproductor_voz.py`.

### 3.3 Cuota insuficiente: selección de proveedor alternativo

Antes de mostrar el diálogo de presupuesto, se consulta `control_cuota.tiene_cuota(texto, proveedor)` (función ya existente en `control_cuota.py`).

Si el proveedor elegido no tiene cuota suficiente:

1. Se recorre la lista de proveedores de nube configurados (con clave API válida en `claves_api.json`) buscando el primero con `tiene_cuota(texto, proveedor) == True`. La voz local (`local`/`local_32`) tiene cuota configurada como prácticamente ilimitada, así que siempre existe una alternativa disponible.
2. Se muestra un diálogo con las opciones: **Usar [proveedor alternativo sugerido]**, **Usar voz local**, **Dividir en partes que sí quepan en la cuota actual**, **Cancelar**.
3. Si el usuario elige un proveedor alternativo, se abre un sub-diálogo de selección de voz que **reutiliza el componente ya existente** en `pestana_ajustes.py` (lista con casillas, filtro "Solo favoritas" y preescucha con `Alt+P`, sobre `voces_favoritas.json`). El filtro "Solo favoritas" se activa por defecto en este contexto; si el proveedor alternativo no tiene ninguna voz favorita guardada, se avisa y se muestran todas sus voces sin bloquear el flujo.
   - Tarea de refactor asociada: extraer ese bloque de `pestana_ajustes.py` a un componente compartido (con su propio bloque `ANCLAJE`), instanciado tanto desde Ajustes como desde este diálogo, para no duplicar lógica.
4. Tras resolver proveedor y voz, continúa el flujo normal del calculador de presupuesto (3.2) con los valores definitivos.

### 3.4 División en dos o más partes por falta de cuota

El comportamiento depende del modo de exportación elegido:

- **Modo "libro completo"**: el corte se ubica en el límite de caracteres disponible, ajustado hacia atrás hasta la frontera de capítulo real más cercana (usando los marcadores internos de `troceador_epub.py`); si cae a mitad de capítulo, se ajusta al punto de frase más próximo (nunca a mitad de palabra). El punto exacto de corte se guarda en `exportaciones_pendientes.punto_corte` para retomar sin regrabar lo ya hecho.

  Importante: retomar la exportación **no consiste en pegar audio a un archivo ya existente** — un MP3 no se puede extender añadiendo bytes al final sin volver a codificarlo. Cada tramo pendiente se genera como una **exportación completa e independiente** cuando el usuario decide continuar (con cuota renovada o cambiando de proveedor). Nomenclatura para que el resultado sea claro y no un desorden de archivos sueltos en la carpeta:
  - Mientras solo existe la primera parte, se nombra `Título del libro (parte 1 - pendiente).mp3` — sin asumir un total de partes que aún no se conoce.
  - Al generar cada parte siguiente, se numera en el mismo formato (`parte 2 - pendiente`, etc.) hasta que se completa la última.
  - Al completarse la última parte, se renombran todas las anteriores para incluir el conteo final (`parte 1 de 2`, `parte 2 de 2`, sin la marca "pendiente"), reutilizando el mecanismo de renombrado seguro descrito en 2.7.1.
  - La lista de partes y su estado ("Completada" / "Pendiente, sin cuota") se muestra también dentro de la interfaz del Creador de Audiolibros (ver 3.6), para que el usuario no dependa de leer nombres de archivo sueltos en el Explorador para entender el estado de su exportación.
- **Modo "por capítulos"**: no requiere cortes a mitad de contenido — se graban los capítulos completos que caben en la cuota disponible, y los que no caben quedan marcados como "Pendiente (sin cuota)" en la lista de capítulos, registrados en `exportaciones_pendientes.capitulo_pendiente`. El usuario puede retomarlos capítulo a capítulo cuando amplíe cuota o cambie de mes.

### 3.5 Carpetas de salida

Se reutiliza el sistema de carpetas ya existente en la v2.0 (`CARPETA_RAIZ_GRABACIONES`, hoy `Grabaciones_Epub-TTS/`), añadiendo una subcarpeta propia para no mezclar con los flujos de Grabación de Fragmentos:

```
Grabaciones_Epub-TTS/
├── <Nombre del libro>/capitulos/     (ya existe — Grabación, por fragmentos)
├── <Nombre del libro>/completo/       (ya existe — Grabación, audio completo con etiquetas)
└── Audiolibros/<Título del libro>/    (nuevo — exclusivo del Creador de Audiolibros)
    ├── Título del libro.mp3            (modo "completo")
    └── 1. Capítulo uno.mp3, 2. ...     (modo "por capítulos")
```

El Creador de Audiolibros incorpora el mismo botón "Abrir Carpeta" ya presente en Grabación. Si la exportación se originó desde la Biblioteca, la ruta de salida se referencia desde `libros.metadatos_json` (o desde `exportaciones_pendientes` si quedó parcial), para poder abrir la carpeta también desde el menú contextual de la Biblioteca.

No se crea una carpeta nueva de configuración ni se traslada nada a `ajustes.json` para este propósito: el patrón de carpeta fija + acceso directo ya resuelto en la v2.0 se extiende tal cual, sin inventar un segundo sistema.

### 3.6 Progreso durante la exportación

A diferencia de la lectura en pantalla (ver sección 5), aquí sí se usan anuncios automáticos por hitos: NVDA anuncia por capítulo completado ("Capítulo 3 de 12 completado"), nunca por página ni por carácter, en paralelo con una `wx.Gauge` actualizada vía `wx.CallAfter`.

Nomenclatura de salida y formato de audio: se mantiene el estándar ya fijado — 44 100 Hz mono, 320 kbps; `1. Capítulo uno.mp3`, `2. Capítulo dos.mp3` en modo por capítulos.

---

## 4. Fase C — Actualizador automático

### 4.1 Limitación heredada de la v2.0

La v2.0 ya implementa comprobación de versión contra GitHub, aviso accesible y volcado de novedades (`comprobador_actualizaciones.py`, `dialogo_novedades.py`). La autoinstalación quedó pospuesta porque Windows bloquea la sobrescritura de archivos mientras la app principal sigue abierta.

### 4.2 Diseño para la v3.0

No se genera ningún script (`.bat`/`.py`) al vuelo — ese enfoque dispara las alarmas heurísticas de los antivirus modernos, y si el script es bloqueado o eliminado a mitad de proceso, la app ya está cerrada y no hay forma de recuperarse.

En su lugar, se incluye desde el primer día un ejecutable auxiliar compilado y fijo, `bin/actualizador.exe` (mismo patrón de compilación ya usado para `auxiliar_sapi32.exe`):

1. Con la app abierta: se descarga el ZIP del release a `temp/actualizacion/`, se descomprime y se verifica que la estructura de archivos esperada esté completa.
2. Si la verificación falla, se avisa por NVDA y se aborta sin tocar nada — la app sigue funcionando con normalidad.
3. Si es correcta, tras confirmación del usuario, la app lanza `actualizador.exe --origen temp/actualizacion --destino <raíz_app>` como proceso independiente y se cierra, liberando los archivos.
4. `actualizador.exe`: copia la carpeta `app/` actual a `temp/backup_previo/` (respaldo), mueve los archivos nuevos a la raíz, y si cualquier paso falla, restaura automáticamente el respaldo antes de relanzar la app principal y notificar el fallo. Al no ser un script generado al vuelo, no dispara los mismos falsos positivos de antivirus, y su lógica de rollback no depende de que el propio script sobreviva al proceso (que era el fallo del diseño original).
5. Al reiniciar tras una actualización correcta, se muestra el diálogo de novedades ya existente, sin cambios.

---

## 5. Fase C — Progreso de lectura y ritmo

### 5.1 Anuncios automáticos: se mantiene el criterio de la v2.0

La v2.0 ya resolvió este problema: consulta manual instantánea con `Ctrl+I` mediante un `TextCtrl` oculto de 1×1 píxel (patrón `_anunciador`), y diálogo de "Ir a página X". Las casillas de anuncio automático por página fueron descartadas en su momento.

Para la v3.0 se mantiene ese comportamiento sin cambios en la pestaña Lectura: nada de anuncios automáticos en cada cambio de página, porque combinar varios anuncios simultáneos (páginas restantes, tiempo restante, progreso del libro) satura a NVDA por encima del propio texto que se está leyendo.

Los anuncios automáticos por hitos (cambio de capítulo, o cada 10% completado en reproducción continua) quedan reservados para contextos donde el usuario no está leyendo activamente en pantalla — como la exportación del Creador de Audiolibros (sección 3.6).

### 5.2 Métrica de progreso: caracteres procesados, no palabras por minuto

Las palabras por minuto se descartan como métrica porque cada proveedor de voz habla a un ritmo nativo distinto y no es comparable entre proveedores. En su lugar, la app puede calcular una estimación de tiempo restante basada en caracteres enviados a la API y en el tiempo real que tardó el audio devuelto en reproducirse, construyendo un histórico local por proveedor. Es una mejora candidata, no bloqueante para el resto del diseño.

---

## 6. Fase C — Asistente de Biblioteca (Gemini)

- Acceso con `Ctrl+G` desde la pestaña Biblioteca. Abre un diálogo de chat, no una pestaña nueva del notebook.
- Con un libro seleccionado en la lista, el chat se precarga con su contexto (título, autor, categoría/etiquetas, estado de lectura) y lo anuncia al abrir. Sin selección, se abre en modo general para pedir recomendaciones.
- No se envía el texto completo del libro como contexto — solo metadatos y lo que el usuario escriba en la conversación.
- Historial de conversación en un archivo JSON ligero (`configuraciones/chat_biblioteca.json`, estructurado por `id_libro`): es un caso legítimo de JSON, no de SQLite, por ser datos pequeños que no se filtran ni se consultan con SQL.
- La llamada a la API de Gemini se ejecuta siempre en hilo secundario, con indicador de "Pensando..." anunciado una vez al enviar, y respuesta entregada vía `wx.CallAfter`.
- La clave de API de Gemini sigue el mismo patrón `cargar_claves()`/`guardar_claves()` que el resto de proveedores, con su entrada correspondiente en Ajustes.

**Orden de foco al abrir el diálogo (Ctrl+G):**

1. El historial de conversación previo (si existe) se carga desde el JSON en el hilo principal antes de mostrar el diálogo — es una lectura de archivo pequeño, no requiere hilo secundario ni deja al diálogo mostrando una carga a medias.
2. El contexto del libro se anuncia con el patrón `_anunciador` ya establecido en el proyecto ("Hablando sobre: El juego de Ender"), pero en vez de devolver el foco al control previo como en sus otros usos, aquí lo entrega directamente al campo de entrada de texto del chat.
3. El foco final, con el diálogo ya visible, queda en el campo de entrada — no en el historial. Es el comportamiento esperado de cualquier chat accesible: el usuario debe poder escribir de inmediato sin tabular primero.
4. Los mensajes nuevos que llegan de la API (en hilo secundario, vía `wx.CallAfter`) se añaden al control de historial sin mover el foco del campo de entrada — el usuario puede seguir escribiendo mientras llega la respuesta, y NVDA anuncia el contenido añadido sin robar el punto de edición.

---

## 7. Fase D — Distribución de pestañas, i18n y Winget

### 7.1 Orden del notebook

1. Biblioteca (entrada principal)
2. Lectura
3. Creador de Audiolibros
4. Grabación de Fragmentos
5. Ajustes

La cercanía funcional entre Biblioteca y Creador de Audiolibros no depende de que estén adyacentes en el notebook, gracias a la acción directa "Enviar a Creador de Audiolibros" del menú contextual de la Biblioteca — no hace falta forzar una reordenación que rompa la costumbre de navegación con `Ctrl+Tab`.

### 7.2 Interfaz accesible de la pestaña Biblioteca

Orden de tabulación:

1. `TextCtrl` de filtro rápido (`Ctrl+F`), filtra en vivo por título/autor.
2. Casillas de filtro combinables: Favoritos, Pendientes, Leyendo ahora, Leídos.
3. `TreeCtrl` de categorías y etiquetas (panel izquierdo): nodo raíz "Todos los libros", hijos por categoría, rama aparte para etiquetas/sagas. Moverse con flechas filtra la lista automáticamente.
4. `ListCtrl` en modo reporte (panel derecho, control principal): columnas Título, Autor, Formato, Estado.

Atajos: `Enter` abre en Lectura (o dispara el re-enrutado); `Ctrl+I` anuncia los metadatos del libro seleccionado sin mover el foco; `Supr` quita el libro de la biblioteca (nunca borra el archivo físico); `F5` re-escanea la carpeta de origen del libro seleccionado; `Ctrl+Shift+F` alterna favorito sin salir de la lista; `Ctrl+N` importa una carpeta nueva.

Menú contextual: Abrir en Lectura · Enviar a Creador de Audiolibros · Marcar como favorito/pendiente/leyendo/leído · Añadir a etiqueta (con opción de crear una nueva) · Localizar archivo manualmente · Quitar de la biblioteca.

### 7.3 Internacionalización

Todas las cadenas visibles en la interfaz se envuelven en `_("texto")` usando `gettext` (librería estándar, sin dependencias nuevas). Estructura `locale/es/LC_MESSAGES/` y `locale/en/LC_MESSAGES/`, con detección del idioma de Windows al arrancar y fallback a español si no hay traducción disponible.

Esta regla afecta únicamente a las cadenas visibles al usuario final — el código sigue escribiéndose íntegramente en español (nombres de variables, funciones, clases, comentarios y logs), sin excepción.

Se deja como última tarea de la v3.0, después de que toda la interfaz nueva esté construida y estable, para no envolver cadenas que aún vayan a cambiar.

### 7.4 Winget

Manifiesto YAML estándar (`installer.yaml`, `locale.yaml`, `version.yaml`) apuntando al instalador ya publicado como release de GitHub. No requiere cambios en el código de la app — es una tarea de empaquetado y publicación, posterior a que la v3.0 esté estable.

### 7.5 Nombre comercial — pendiente

El repositorio de GitHub no cambia de nombre. El nombre comercial que se mostrará en Winget y en la interfaz queda **pendiente de decidir al finalizar la v3.0**, cuando todas las funciones nuevas estén probadas y estables. Se descartó "TifloReader" por posible colisión con un dispositivo lector físico ya existente en el mercado. "TifloVoice" y "TifloEstudio" fueron valorados y descartados por no transmitir con precisión el alcance real de la aplicación (biblioteca, lectura, multivoz, creación de audiolibros y asistente de IA — no solo lectura o grabación de voz).

---

## 8. Decisiones de arquitectura general (aplicables a toda la fase)

- Todo acceso a `biblioteca.db` debe ejecutarse desde hilos de fondo cuando implique escaneo o escritura masiva; las consultas puntuales de lectura (una fila, un filtro ya indexado) pueden hacerse en el hilo principal por ser prácticamente instantáneas con SQLite.
- Toda actualización de controles wx originada en un hilo secundario pasa por `wx.CallAfter`, sin excepción — regla ya vigente en el proyecto, reforzada aquí porque el escáner y la exportación de audiolibros son los puntos de mayor concurrencia de la v3.0.
- Ningún componente nuevo debe duplicar lógica ya existente: el selector de voces favoritas del Creador de Audiolibros reutiliza el de Ajustes; las carpetas de salida reutilizan `CARPETA_RAIZ_GRABACIONES`; el módulo de limpieza de PDF reutiliza la misma tubería de audio que el de EPUB.
- Bloques de código nuevos que puedan necesitar reemplazo futuro se delimitan con el sistema de anclajes ya establecido en el proyecto.

---

## 9. Referencia externa — patrones observados en Bookworm

Bookworm (lector de pantalla accesible de código abierto, `github.com/blindpandas/bookworm`) se tomó como referencia de diseño para la arquitectura de biblioteca, sin copiar código ni dependencias. Aporta tres ideas adoptadas en este documento y dos deliberadamente descartadas:

**Adoptado:**
- Autores como tabla normalizada en relación N:N con los libros, en vez de texto libre repetido (sección 2.2).
- Estados de lectura desdoblados en varias banderas independientes (favorito / pendiente / leyendo ahora / leído) en vez de un único campo booleano (sección 2.2).
- Escaneo de carpetas paralelizado con un pool de hilos en vez de un único hilo secuencial, para reducir el tiempo de indexación inicial en colecciones grandes (sección 2.3).
- Extracción de texto de PDF con `PyMuPDF` en modo de bloques y orden de lectura, en vez de extracción cruda por coordenadas, más `ftfy` para normalización Unicode (sección 2.5). Bookworm usa PyXPDF como motor principal de texto y PyMuPDF como base común entre formatos; aquí se adopta solo PyMuPDF, por ser suficiente para el caso de uso y evitar sumar una segunda librería de PDF.

**Descartado deliberadamente:**
- Bookworm usa APSW (binding alternativo de SQLite) y `peewee` como ORM, con migraciones gestionadas por `alembic`. Para esta aplicación, con un único desarrollador y una base de datos de un solo usuario, se prefiere `sqlite3` de la librería estándar con SQL directo y un control de versión de esquema manual vía `PRAGMA user_version` — menos dependencias, más alineado con el resto del proyecto.
- Bookworm indexa el contenido completo de los documentos con búsqueda de texto completo (FTS5). Se valora como mejora candidata para una versión posterior, no como parte del alcance de la v3.0.

Nota para quien retome este documento sin haber participado en su elaboración: no se dispone de una copia local del repositorio de Bookworm ni de acceso a él durante el desarrollo de esta fase; las referencias anteriores se basan en el conocimiento general de su arquitectura pública, no en una revisión línea a línea de su código fuente. Cualquier detalle de implementación de Bookworm mencionado aquí debe tomarse como orientación de diseño, no como especificación exacta a replicar.
