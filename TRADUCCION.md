# Guía de traducción

Epub TTS Accesible usa `gettext` (librería estándar de Python) para las cadenas de la interfaz que ve la persona usuaria final. El código interno (nombres de variables, funciones, comentarios, logs) sigue siempre en español, sin excepción — esta guía solo trata de los textos visibles y de los anuncios que se envían al lector de pantalla.

## Estructura de archivos

```
locale/
├── epub_tts.pot              # plantilla con todas las cadenas originales en español
├── es/LC_MESSAGES/epub_tts.po   # traducción al español (normalmente vacía, ver más abajo)
└── en/LC_MESSAGES/epub_tts.po   # traducción al inglés
```

Cada `.po` es un archivo de texto plano con pares `msgid`/`msgstr`:

```
msgid "Ajustes"
msgstr "Settings"
```

- `msgid` es siempre el texto original en español, tal como aparece en el código (`_("Ajustes")`).
- `msgstr` es la traducción a ese idioma.

**En `es/LC_MESSAGES/epub_tts.po` normalmente se deja `msgstr` vacío.** El español es el idioma en el que ya está escrita la aplicación, así que no hace falta traducir nada: si `msgstr` está vacío, la app muestra el propio `msgid` (el texto español original) tal cual.

## Cómo editar un `.po`

Cualquiera de estas dos opciones funciona igual de bien:

1. **Bloc de notas o Notepad++** (o cualquier editor de texto plano): abre el archivo `.po` del idioma que quieras corregir y edita el contenido entre comillas después de `msgstr`. No toques la línea de `msgid`.
2. **[Poedit](https://poedit.net/)**: una aplicación gratuita pensada específicamente para archivos `.po`, con una tabla de dos columnas (original / traducción) más cómoda que un editor de texto plano. Abre el `.po`, escribe la traducción en la columna derecha y guarda.

Si añades una cadena nueva que no exista todavía en el `.po` (por ejemplo, porque se envolvió una cadena nueva en `_("...")` en el código), añade al final del archivo un bloque:

```
msgid "Texto nuevo en español"
msgstr "Traducción en el idioma de este archivo"
```

## Cómo probar la traducción en local

Los archivos `.po` no se leen directamente en tiempo de ejecución — hay que compilarlos primero a su formato binario `.mo`. Para no depender de tener `gettext`/`msgfmt` instalado en el sistema (especialmente en Windows), el proyecto incluye su propio compilador:

```
python herramientas/compilar_i18n.py
```

Esto recorre todos los `.po` bajo `locale/` y genera (o actualiza) el `.mo` correspondiente junto a cada uno. Ejecútalo cada vez que edites un `.po`, antes de abrir la app, para ver el resultado.

La aplicación detecta el idioma de Windows al arrancar y usa automáticamente el `.mo` correspondiente si existe; si no hay traducción para ese idioma, cae a español sin errores.

## Añadir un idioma nuevo

1. Crea la carpeta `locale/<código>/LC_MESSAGES/` (por ejemplo, `locale/fr/LC_MESSAGES/`).
2. Copia `locale/epub_tts.pot` dentro como `epub_tts.po` y traduce cada `msgstr`.
3. Ejecuta `python herramientas/compilar_i18n.py`.
4. Añade el código de idioma a `IDIOMAS_DISPONIBLES` en `app/motor/gestor_idioma.py`.
