# Historial de Cambios

## [Fase 3, Prompt 16b] - 2026-03-09 — Seguridad y separación de secretos

### Nuevas características
- **`configuraciones/claves_api.json`**: Nuevo archivo exclusivo para las claves API de Azure, Amazon Polly y ElevenLabs. Separado de `ajustes.json` para que los secretos nunca mezclen con la configuración general de la sesión.
- **`cargar_claves()` / `guardar_claves()`** en `app/config_rutas.py`: Funciones centralizadas para leer y escribir `claves_api.json`. Fallo seguro: si el archivo no existe (primer arranque o repo recién clonado), devuelven una estructura vacía en lugar de lanzar excepción.
- **Migración automática al primer arranque**: `migrar_archivos_config()` detecta si `claves_api.json` no existe y, en ese caso, extrae las claves de `ajustes.json` (si las había) y las mueve al nuevo archivo, dejando `ajustes.json` limpio de secretos.

### Mejoras de seguridad
- **`.gitignore` ampliado**: Ahora se excluyen correctamente:
  - `configuraciones/claves_api.json` y `configuraciones/ajustes.json` (GitHub detectó secretos en ajustes.json).
  - Todos los archivos de historial y caché del usuario (`historial_grabacion.json`, `historial_epub.json`, `estado_lectura.json`, `proyectos.json`, `mapeo_etiquetas.json`, etc.).
  - Archivos legacy con nombres anteriores a la migración.
  - `*.log`, `logs/`, `registros/`.
  - Patrones genéricos `*token*.json` y `*secret*.json`.
- **Refactorización de clientes de servicio**: `cliente_azure.py`, `cliente_polly.py`, `cliente_eleven.py` y `cliente_nube_voces.py` ahora leen las claves exclusivamente desde `claves_api.json` a través de `cargar_claves()`.
- **`PanelClaves`**: Los métodos `cargar_datos_visuales()` y `al_guardar()` usan `cargar_claves()`/`guardar_claves()` en lugar de `self.config` (ajustes.json). Las claves nunca se escriben en `ajustes.json`.

### Lógica de primer inicio
- La app puede abrirse desde un repo recién clonado sin errores: todos los archivos de configuración esenciales ausentes se tratan como configuración vacía/neutral.
- `claves_api.json` se crea automáticamente con estructura vacía si no existe, para que el usuario pueda introducir sus claves desde la interfaz.

---

## [Fase 3, Prompt 16a] - 2026-03-09 — Persistencia de eliminaciones y papelera

### Corrección de bug crítico
- **Persistencia de eliminaciones**: Se corrige el bug por el que los proyectos eliminados reaparecían al reiniciar la app. La causa raíz era que `VentanaProyectos` creaba su propia instancia de `GestorProyectos`, y cuando `PestanaGrabacion` guardaba voces u otros datos, sobreescribía `proyectos.json` con la copia antigua. Ahora `VentanaProyectos` comparte la misma instancia del gestor que `PestanaGrabacion`.

### Nuevas características
- **Papelera (soft-delete)**: `GestorProyectos.eliminar_proyecto()` ya no borra definitivamente. Mueve el subárbol completo (raíz + todos los hijos recursivos) a una clave `"papelera"` en `proyectos.json`, con timestamp y referencia al padre original.
- **`restaurar_proyecto(raiz_id)`**: Devuelve un proyecto de la papelera al árbol. Si el padre original ya no existe, el proyecto pasa a ser raíz.
- **`listar_papelera()`** y **`vaciar_papelera()`**: Inspección y limpieza definitiva de la papelera.
- **Submenú "Restaurar eliminado…"**: En el menú contextual del árbol se muestra una entrada por proyecto en la papelera (nombre + fecha de eliminación), con opción para vaciar la papelera (con confirmación).
- **"Eliminar… Supr"**: El menú contextual ya muestra el atajo de teclado como recordatorio.
- **Diálogo de confirmación mejorado**: Informa de que el elemento puede restaurarse desde el menú contextual.

---

## [Fase 3, Prompt 15] — Blindaje de atajos y menú contextual de movimiento

- `_configurar_aceleradores()` en `VentanaProyectos`: registra Ctrl+Arriba, Ctrl+Abajo y Ctrl+Intro en `wx.AcceleratorTable` a nivel de Frame (prioridad sobre NVDA).
- "Mover arriba (Ctrl+Arriba)" y "Mover abajo (Ctrl+Abajo)" añadidos al menú contextual usando los mismos IDs que la AcceleratorTable.
- `_mover_nodo()` llama a `wx.CallAfter(self.arbol.SetFocus)` y anuncia el nombre del proyecto movido.

---

## [Fase 3, Prompt 14] — Accesibilidad del árbol

- Etiquetas de nodo enriquecidas: NVDA lee `[Nombre] [tipo] — Grabado/Pendiente — Nivel N`.
- Ctrl+Intro abre la carpeta del proyecto en el Explorador.
- `actualizar_nombre_proyecto()` sincroniza el nodo del árbol cuando el título cambia en PestanaGrabacion.

---

## [Fase 3, Prompt 13] — Fluidez de lectura y control técnico

- `_dividir_en_fragmentos()` en `PestanaLectura`: chunking inteligente con jerarquía de 4 niveles de pausa (párrafo, puntuación fuerte, puntuación media, espacio, corte duro).
- `GestorVoces.actualizar_proveedor(proveedor)`: descarga voces de un único proveedor sin sobreescribir las de los demás.
- Botones de comprobación de API independientes por proveedor en PanelClaves.

---

## [0.1.0] - Inicio del Proyecto
- Definición de arquitectura MVC.
- Selección de stack tecnológico (Python 3.12 + wxPython + httpx).
