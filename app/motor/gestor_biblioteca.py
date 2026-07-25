"""
gestor_biblioteca.py  →  GestorBiblioteca
------------------------------------------
Motor de acceso a la base de datos de la Biblioteca (biblioteca.db).

Responsabilidades:
  - Crear y versionar el esquema SQLite de libros, autores, categorías,
    etiquetas, reglas de diccionario y exportaciones pendientes.
  - Ofrecer una API de alto nivel para insertar, consultar y actualizar
    libros sin que el resto de la app escriba SQL directamente.
  - Garantizar que ninguna operación deje la base de datos apuntando a
    un archivo físico que no coincide con la realidad del disco.

Nota de arquitectura:
  Este módulo es puro motor (sin wx). El escaneo de carpetas en segundo
  plano y la interfaz de la pestaña Biblioteca se implementan aparte y
  consumen esta API.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

from app.config_rutas import ruta_config

logger = logging.getLogger(__name__)

RUTA_BIBLIOTECA = ruta_config("biblioteca.db")

VERSION_ESQUEMA = 3

_ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS autores (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS categorias (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL COLLATE NOCASE,
    id_padre  INTEGER REFERENCES categorias(id) ON DELETE CASCADE,
    orden     INTEGER,
    UNIQUE (nombre, id_padre)
);

CREATE TABLE IF NOT EXISTS etiquetas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS libros (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ruta_archivo          TEXT NOT NULL UNIQUE,
    titulo                TEXT NOT NULL,
    formato               TEXT NOT NULL CHECK (formato IN ('epub', 'pdf')),
    fecha_añadido         TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_punto_lectura  INTEGER NOT NULL DEFAULT 0,
    metadatos_json        TEXT,
    favorito              INTEGER NOT NULL DEFAULT 0 CHECK (favorito IN (0,1)),
    en_pendientes         INTEGER NOT NULL DEFAULT 0 CHECK (en_pendientes IN (0,1)),
    leyendo_ahora         INTEGER NOT NULL DEFAULT 0 CHECK (leyendo_ahora IN (0,1)),
    leido                 INTEGER NOT NULL DEFAULT 0 CHECK (leido IN (0,1)),
    titulo_revisado       INTEGER NOT NULL DEFAULT 1 CHECK (titulo_revisado IN (0,1))
);

CREATE TABLE IF NOT EXISTS libro_autor (
    id_libro   INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_autor   INTEGER NOT NULL REFERENCES autores(id) ON DELETE CASCADE,
    PRIMARY KEY (id_libro, id_autor)
);

CREATE TABLE IF NOT EXISTS libro_categoria (
    id_libro      INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_categoria  INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
    orden         INTEGER,
    PRIMARY KEY (id_libro, id_categoria)
);

CREATE TABLE IF NOT EXISTS libro_etiqueta (
    id_libro    INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_etiqueta INTEGER NOT NULL REFERENCES etiquetas(id) ON DELETE CASCADE,
    orden       INTEGER,
    PRIMARY KEY (id_libro, id_etiqueta)
);

CREATE TABLE IF NOT EXISTS diccionario_reglas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patron_origen  TEXT NOT NULL,
    sustitucion    TEXT NOT NULL,
    tipo_alcance   TEXT NOT NULL CHECK (tipo_alcance IN ('global','libro','saga')),
    id_referencia  INTEGER
);

CREATE TABLE IF NOT EXISTS exportaciones_pendientes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id_libro            INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    modo                TEXT NOT NULL CHECK (modo IN ('completo', 'capitulos')),
    proveedor           TEXT NOT NULL,
    punto_corte         INTEGER,
    capitulo_pendiente  INTEGER,
    ruta_parcial        TEXT
);

CREATE INDEX IF NOT EXISTS idx_libros_favorito    ON libros(favorito);
CREATE INDEX IF NOT EXISTS idx_libros_pendientes  ON libros(en_pendientes);
CREATE INDEX IF NOT EXISTS idx_libros_leyendo     ON libros(leyendo_ahora);
CREATE INDEX IF NOT EXISTS idx_libros_leido       ON libros(leido);
CREATE INDEX IF NOT EXISTS idx_libro_autor_autor  ON libro_autor(id_autor);
CREATE INDEX IF NOT EXISTS idx_libro_cat_cat      ON libro_categoria(id_categoria);
CREATE INDEX IF NOT EXISTS idx_categorias_padre   ON categorias(id_padre);
CREATE INDEX IF NOT EXISTS idx_libro_etiq_etiq    ON libro_etiqueta(id_etiqueta);
CREATE INDEX IF NOT EXISTS idx_dicc_alcance       ON diccionario_reglas(tipo_alcance, id_referencia);
"""


# ═════════════════════════════════════════════════════════════════════════════
class GestorBiblioteca:
    """
    Motor de acceso a biblioteca.db.

    Cada método abre y cierra su propia conexión (SQLite permite esto sin
    coste relevante gracias al modo WAL), lo que evita mantener una
    conexión compartida entre el hilo de escaneo y el hilo principal.
    """

    def __init__(self, ruta_db: str = RUTA_BIBLIOTECA):
        self.ruta_db = ruta_db
        self._inicializar_esquema()

    # ── Conexión y esquema ──────────────────────────────────────────────────

    @contextmanager
    def _conexion(self):
        os.makedirs(os.path.dirname(self.ruta_db), exist_ok=True)
        conexion = sqlite3.connect(self.ruta_db)
        conexion.execute("PRAGMA journal_mode = WAL;")
        conexion.execute("PRAGMA foreign_keys = ON;")
        conexion.row_factory = sqlite3.Row
        try:
            yield conexion
            conexion.commit()
        except Exception:
            conexion.rollback()
            raise
        finally:
            conexion.close()

    def _inicializar_esquema(self):
        with self._conexion() as conexion:
            conexion.executescript(_ESQUEMA_SQL)
            version_actual = conexion.execute("PRAGMA user_version;").fetchone()[0]
            if version_actual < 3:
                # CREATE TABLE IF NOT EXISTS no añade columnas nuevas a
                # tablas que ya existían de antes (bases de datos reales
                # con libros ya importados) — hace falta ALTER TABLE para
                # las columnas "orden" nuevas, envuelto en try/except
                # porque ALTER TABLE ADD COLUMN falla si ya existe (por
                # ejemplo, en una base de datos creada de cero que ya
                # nació con estas columnas desde _ESQUEMA_SQL).
                for sentencia in (
                    "ALTER TABLE categorias ADD COLUMN orden INTEGER",
                    "ALTER TABLE libro_categoria ADD COLUMN orden INTEGER",
                ):
                    try:
                        conexion.execute(sentencia)
                    except sqlite3.OperationalError:
                        pass
                # A las filas ya existentes sin orden se les da uno según
                # su orden actual (por id de creación), para no perder ni
                # desordenar nada de golpe al actualizar.
                conexion.execute(
                    "UPDATE categorias SET orden = id WHERE orden IS NULL"
                )
                conexion.execute(
                    "UPDATE libro_categoria SET orden = rowid WHERE orden IS NULL"
                )
            if version_actual < VERSION_ESQUEMA:
                conexion.execute(f"PRAGMA user_version = {VERSION_ESQUEMA};")

    # ── Autores, categorías y etiquetas ─────────────────────────────────────

    def obtener_o_crear_autor(self, conexion, nombre: str) -> int:
        nombre = nombre.strip()
        fila = conexion.execute(
            "SELECT id FROM autores WHERE nombre = ? COLLATE NOCASE", (nombre,)
        ).fetchone()
        if fila:
            return fila["id"]
        cursor = conexion.execute("INSERT INTO autores (nombre) VALUES (?)", (nombre,))
        return cursor.lastrowid

    def obtener_o_crear_categoria(self, conexion, nombre: str, id_padre: Optional[int] = None) -> int:
        """
        Géneros y subgéneros forman un árbol: id_padre es NULL para un
        género raíz (ej. "Fantasía") y apunta al id del padre para un
        subgénero (ej. "Fantasía épica" bajo "Fantasía"). El mismo
        nombre puede existir bajo padres distintos sin chocar.
        """
        nombre = nombre.strip()
        fila = conexion.execute(
            "SELECT id FROM categorias WHERE nombre = ? COLLATE NOCASE AND id_padre IS ?",
            (nombre, id_padre),
        ).fetchone()
        if fila:
            return fila["id"]
        cursor = conexion.execute(
            "INSERT INTO categorias (nombre, id_padre, orden) VALUES "
            "(?, ?, (SELECT COALESCE(MAX(orden), 0) + 1 FROM categorias WHERE id_padre IS ?))",
            (nombre, id_padre, id_padre),
        )
        return cursor.lastrowid

    def obtener_o_crear_etiqueta(self, conexion, nombre: str) -> int:
        nombre = nombre.strip()
        fila = conexion.execute(
            "SELECT id FROM etiquetas WHERE nombre = ? COLLATE NOCASE", (nombre,)
        ).fetchone()
        if fila:
            return fila["id"]
        cursor = conexion.execute("INSERT INTO etiquetas (nombre) VALUES (?)", (nombre,))
        return cursor.lastrowid

    def crear_categoria(self, nombre: str, id_padre: Optional[int] = None) -> int:
        with self._conexion() as conexion:
            return self.obtener_o_crear_categoria(conexion, nombre, id_padre)

    def listar_categorias_hijas(self, id_padre: Optional[int] = None) -> list[sqlite3.Row]:
        """
        Hijos directos de una categoría (o raíces del árbol si id_padre es
        None). Por defecto, en el orden en que se crearon — no alfabético.
        La categoría que la autora crea primero (ej. "Fantasía", su género
        principal) debe seguir apareciendo primero aunque después cree
        "Distopía" — pero mover_categoria() puede cambiar ese orden a mano.
        """
        with self._conexion() as conexion:
            return conexion.execute(
                "SELECT id, nombre, id_padre, orden FROM categorias "
                "WHERE id_padre IS ? ORDER BY (orden IS NULL), orden, id",
                (id_padre,),
            ).fetchall()

    def mover_categoria(self, id_categoria: int, direccion: int) -> bool:
        """
        Cambia el orden de id_categoria respecto a sus hermanas (mismo
        id_padre), intercambiando su valor de "orden" con la vecina
        inmediatamente anterior (direccion=-1) o siguiente (direccion=+1).
        Devuelve False sin hacer nada si ya está en un extremo. Mismo
        principio que _mover_nodo() en ventana_proyectos.py.
        """
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT id_padre, orden FROM categorias WHERE id = ?", (id_categoria,)
            ).fetchone()
            if fila is None:
                return False
            hermanas = conexion.execute(
                "SELECT id, orden FROM categorias WHERE id_padre IS ? "
                "ORDER BY (orden IS NULL), orden, id",
                (fila["id_padre"],),
            ).fetchall()
            indices = [h["id"] for h in hermanas]
            posicion = indices.index(id_categoria)
            nueva_posicion = posicion + direccion
            if nueva_posicion < 0 or nueva_posicion >= len(hermanas):
                return False
            vecina = hermanas[nueva_posicion]
            conexion.execute(
                "UPDATE categorias SET orden = ? WHERE id = ?", (vecina["orden"], id_categoria)
            )
            conexion.execute(
                "UPDATE categorias SET orden = ? WHERE id = ?", (fila["orden"], vecina["id"])
            )
            return True

    def contar_libros_por_categoria(self) -> dict[int, int]:
        """
        Nº de libros asignados directamente a cada categoría (sin sumar
        los de sus subcategorías) en una sola consulta, para mostrarlo
        junto a cada nodo del árbol sin repetir un SELECT por nodo.
        """
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT id_categoria, COUNT(*) AS total FROM libro_categoria GROUP BY id_categoria"
            ).fetchall()
        return {fila["id_categoria"]: fila["total"] for fila in filas}

    def listar_etiquetas(self) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute("SELECT id, nombre FROM etiquetas ORDER BY nombre").fetchall()

    def crear_etiqueta(self, nombre: str) -> int:
        with self._conexion() as conexion:
            return self.obtener_o_crear_etiqueta(conexion, nombre)

    def renombrar_etiqueta(self, id_etiqueta: int, nuevo_nombre: str) -> bool:
        nuevo_nombre = nuevo_nombre.strip()
        if not nuevo_nombre:
            return False
        with self._conexion() as conexion:
            choque = conexion.execute(
                "SELECT id FROM etiquetas WHERE nombre = ? COLLATE NOCASE AND id != ?",
                (nuevo_nombre, id_etiqueta),
            ).fetchone()
            if choque:
                return False
            conexion.execute(
                "UPDATE etiquetas SET nombre = ? WHERE id = ?", (nuevo_nombre, id_etiqueta)
            )
            return True

    def eliminar_etiqueta(self, id_etiqueta: int):
        with self._conexion() as conexion:
            conexion.execute("DELETE FROM etiquetas WHERE id = ?", (id_etiqueta,))

    def obtener_etiquetas_de_libro(self, id_libro: int) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute(
                """
                SELECT e.id, e.nombre FROM etiquetas e
                JOIN libro_etiqueta le ON le.id_etiqueta = e.id
                WHERE le.id_libro = ?
                ORDER BY e.nombre COLLATE NOCASE
                """,
                (id_libro,),
            ).fetchall()

    def quitar_etiqueta_de_libro(self, id_libro: int, id_etiqueta: int):
        with self._conexion() as conexion:
            conexion.execute(
                "DELETE FROM libro_etiqueta WHERE id_libro = ? AND id_etiqueta = ?",
                (id_libro, id_etiqueta),
            )

    def asignar_categoria_por_ruta(self, id_libro: int, ruta_categorias: list[str]) -> int:
        """
        Asigna un género/subgénero a un libro a partir de una ruta de
        nombres desde la raíz (ej. ["Fantasía", "Fantasía épica"]),
        creando los niveles que falten. Un libro puede tener varias
        categorías asignadas (llamar una vez por cada una) — no es
        exclusivo como en la v1 de este esquema.
        """
        with self._conexion() as conexion:
            id_padre = None
            id_categoria = None
            for parte in ruta_categorias:
                id_categoria = self.obtener_o_crear_categoria(conexion, parte, id_padre)
                id_padre = id_categoria
            conexion.execute(
                "INSERT OR IGNORE INTO libro_categoria (id_libro, id_categoria, orden) VALUES "
                "(?, ?, (SELECT COALESCE(MAX(orden), 0) + 1 FROM libro_categoria WHERE id_categoria = ?))",
                (id_libro, id_categoria, id_categoria),
            )
            return id_categoria

    def quitar_categoria_de_libro(self, id_libro: int, id_categoria: int):
        with self._conexion() as conexion:
            conexion.execute(
                "DELETE FROM libro_categoria WHERE id_libro = ? AND id_categoria = ?",
                (id_libro, id_categoria),
            )

    def obtener_categorias_de_libro(self, id_libro: int) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute(
                """
                SELECT c.id, c.nombre, c.id_padre FROM categorias c
                JOIN libro_categoria lc ON lc.id_categoria = c.id
                WHERE lc.id_libro = ?
                ORDER BY c.nombre COLLATE NOCASE
                """,
                (id_libro,),
            ).fetchall()

    def _descendientes_categoria(self, conexion, id_categoria: int) -> list[int]:
        ids = [id_categoria]
        hijos = conexion.execute(
            "SELECT id FROM categorias WHERE id_padre = ?", (id_categoria,)
        ).fetchall()
        for hijo in hijos:
            ids.extend(self._descendientes_categoria(conexion, hijo["id"]))
        return ids

    def renombrar_categoria(self, id_categoria: int, nuevo_nombre: str) -> bool:
        nuevo_nombre = nuevo_nombre.strip()
        if not nuevo_nombre:
            return False
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT id_padre FROM categorias WHERE id = ?", (id_categoria,)
            ).fetchone()
            if fila is None:
                return False
            choque = conexion.execute(
                "SELECT id FROM categorias WHERE nombre = ? COLLATE NOCASE "
                "AND id_padre IS ? AND id != ?",
                (nuevo_nombre, fila["id_padre"], id_categoria),
            ).fetchone()
            if choque:
                return False
            conexion.execute(
                "UPDATE categorias SET nombre = ? WHERE id = ?", (nuevo_nombre, id_categoria)
            )
            return True

    def reparentar_categoria(self, id_categoria: int, nuevo_id_padre: Optional[int]) -> bool:
        """
        Mueve una categoría (con todo su subárbol) bajo otra, o a raíz si
        nuevo_id_padre es None. Rechaza la operación si crearía un ciclo
        (mover una categoría dentro de sí misma o de un descendiente suyo).
        """
        if id_categoria == nuevo_id_padre:
            return False
        with self._conexion() as conexion:
            if nuevo_id_padre is not None:
                descendientes = self._descendientes_categoria(conexion, id_categoria)
                if nuevo_id_padre in descendientes:
                    return False
            conexion.execute(
                "UPDATE categorias SET id_padre = ? WHERE id = ?",
                (nuevo_id_padre, id_categoria),
            )
            return True

    def eliminar_categoria(self, id_categoria: int):
        """Elimina la categoría y todo su subárbol (ON DELETE CASCADE)."""
        with self._conexion() as conexion:
            conexion.execute("DELETE FROM categorias WHERE id = ?", (id_categoria,))

    def obtener_ruta_categoria(self, id_categoria: int) -> list[str]:
        """Nombres desde la raíz hasta la categoría dada, ej. ['Fantasía', 'Fantasía épica']."""
        with self._conexion() as conexion:
            ruta = []
            actual = conexion.execute(
                "SELECT id, nombre, id_padre FROM categorias WHERE id = ?", (id_categoria,)
            ).fetchone()
            while actual:
                ruta.insert(0, actual["nombre"])
                if actual["id_padre"] is None:
                    break
                actual = conexion.execute(
                    "SELECT id, nombre, id_padre FROM categorias WHERE id = ?",
                    (actual["id_padre"],),
                ).fetchone()
            return ruta

    # ── Rutas ya indexadas (para el escáner) ────────────────────────────────

    def obtener_rutas_indexadas(self) -> set[str]:
        with self._conexion() as conexion:
            filas = conexion.execute("SELECT ruta_archivo FROM libros").fetchall()
            return {fila["ruta_archivo"] for fila in filas}

    # ── Inserción de libros ─────────────────────────────────────────────────

    def insertar_libro(
        self,
        ruta_archivo: str,
        titulo: str,
        formato: str,
        autores: Optional[list[str]] = None,
        categorias: Optional[list[list[str]]] = None,
        titulo_revisado: bool = True,
    ) -> int:
        """
        Inserta un único libro con sus autores y categorías, resolviendo
        las tablas auxiliares dentro de la misma transacción.

        `categorias` es una lista de rutas de género (cada ruta es una
        lista de nombres desde la raíz), ya que un libro puede
        pertenecer a varios géneros/subgéneros a la vez. Ejemplo:
        [["Fantasía", "Fantasía épica"], ["Aventuras"]].
        """
        with self._conexion() as conexion:
            return self._insertar_libro_en_conexion(
                conexion, ruta_archivo, titulo, formato, autores, categorias, titulo_revisado
            )

    def insertar_libros_lote(self, libros: list[dict]) -> int:
        """
        Inserta varios libros en una única transacción.

        Cada elemento de `libros` es un dict con las claves:
        ruta_archivo, titulo, formato, autores (list[str], opcional),
        categorias (list[list[str]], opcional), titulo_revisado (bool, opcional).

        Devuelve el número de libros insertados con éxito. Los que
        fallen individualmente (por ejemplo ruta duplicada) se registran
        y se saltan, sin abortar el resto del lote.
        """
        insertados = 0
        with self._conexion() as conexion:
            for datos in libros:
                try:
                    self._insertar_libro_en_conexion(
                        conexion,
                        datos["ruta_archivo"],
                        datos["titulo"],
                        datos["formato"],
                        datos.get("autores"),
                        datos.get("categorias"),
                        datos.get("titulo_revisado", True),
                    )
                    insertados += 1
                except sqlite3.IntegrityError:
                    logger.warning(
                        "[GestorBiblioteca] Ruta ya indexada, se omite: %s", datos.get("ruta_archivo")
                    )
        return insertados

    def _insertar_libro_en_conexion(
        self, conexion, ruta_archivo, titulo, formato, autores, categorias, titulo_revisado
    ) -> int:
        cursor = conexion.execute(
            """
            INSERT INTO libros (ruta_archivo, titulo, formato, titulo_revisado)
            VALUES (?, ?, ?, ?)
            """,
            (ruta_archivo, titulo, formato, int(titulo_revisado)),
        )
        id_libro = cursor.lastrowid
        for nombre_autor in (autores or []):
            id_autor = self.obtener_o_crear_autor(conexion, nombre_autor)
            conexion.execute(
                "INSERT OR IGNORE INTO libro_autor (id_libro, id_autor) VALUES (?, ?)",
                (id_libro, id_autor),
            )
        for ruta_categoria in (categorias or []):
            if not ruta_categoria:
                continue
            id_padre = None
            id_categoria = None
            for parte in ruta_categoria:
                id_categoria = self.obtener_o_crear_categoria(conexion, parte, id_padre)
                id_padre = id_categoria
            conexion.execute(
                "INSERT OR IGNORE INTO libro_categoria (id_libro, id_categoria, orden) VALUES "
                "(?, ?, (SELECT COALESCE(MAX(orden), 0) + 1 FROM libro_categoria WHERE id_categoria = ?))",
                (id_libro, id_categoria, id_categoria),
            )
        return id_libro

    # ── Consulta de libros ──────────────────────────────────────────────────

    def obtener_libro(self, id_libro: int) -> Optional[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute("SELECT * FROM libros WHERE id = ?", (id_libro,)).fetchone()

    def obtener_libro_por_ruta(self, ruta_archivo: str) -> Optional[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute(
                "SELECT * FROM libros WHERE ruta_archivo = ?", (ruta_archivo,)
            ).fetchone()

    def obtener_libros_de_carpeta(self, carpeta: str) -> list[sqlite3.Row]:
        """
        Libros cuya carpeta contenedora inmediata (no subcarpetas) es
        exactamente `carpeta`. Filtra en SQL con un LIKE por prefijo
        (aprovecha el índice de ruta_archivo) en vez de traer toda la
        biblioteca y filtrar en Python — con cientos de carpetas
        candidatas tras un escaneo grande, repetir un SELECT * FROM libros
        completo por cada una es demasiado lento y bloquea el hilo
        principal (ver confirmar_agrupamiento_por_carpeta en
        escaner_biblioteca.py).
        """
        carpeta_normalizada = os.path.normpath(carpeta)
        prefijo = carpeta_normalizada + os.sep
        comodin = (
            prefijo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT * FROM libros WHERE ruta_archivo LIKE ? ESCAPE '\\'",
                (comodin,),
            ).fetchall()
        # El LIKE por prefijo también trae subcarpetas más profundas; el
        # filtro final en Python ya solo opera sobre las pocas filas de
        # esta carpeta, no sobre toda la biblioteca.
        return [
            fila for fila in filas
            if os.path.dirname(os.path.normpath(fila["ruta_archivo"])) == carpeta_normalizada
        ]

    def buscar_libros(
        self,
        texto: str = "",
        id_categoria: Optional[int] = None,
        id_etiqueta: Optional[int] = None,
        solo_favoritos: bool = False,
        solo_pendientes: bool = False,
        solo_leyendo: bool = False,
        solo_leidos: bool = False,
    ) -> list[sqlite3.Row]:
        """
        Si se filtra por id_etiqueta (una saga/colección concreta), el
        resultado se ordena por libro_etiqueta.orden — para respetar el
        orden de lectura de la saga en vez del alfabético. Si se filtra
        por id_categoria, incluye también los libros de sus subgéneros.
        Sin ninguno de los dos, se ordena alfabéticamente por título.
        """
        condiciones = []
        parametros = []

        if texto:
            condiciones.append("(l.titulo LIKE ? OR a.nombre LIKE ?)")
            comodin = f"%{texto}%"
            parametros.extend([comodin, comodin])
        if id_categoria is not None:
            with self._conexion() as conexion_aux:
                ids_categoria = self._descendientes_categoria(conexion_aux, id_categoria)
            marcadores = ",".join("?" * len(ids_categoria))
            condiciones.append(
                f"l.id IN (SELECT id_libro FROM libro_categoria WHERE id_categoria IN ({marcadores}))"
            )
            parametros.extend(ids_categoria)
        if id_etiqueta is not None:
            condiciones.append(
                "l.id IN (SELECT id_libro FROM libro_etiqueta WHERE id_etiqueta = ?)"
            )
            parametros.append(id_etiqueta)
        if solo_favoritos:
            condiciones.append("l.favorito = 1")
        if solo_pendientes:
            condiciones.append("l.en_pendientes = 1")
        if solo_leyendo:
            condiciones.append("l.leyendo_ahora = 1")
        if solo_leidos:
            condiciones.append("l.leido = 1")

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

        if id_etiqueta is not None:
            consulta = f"""
                SELECT DISTINCT l.*, le.orden AS orden_en_etiqueta
                FROM libros l
                LEFT JOIN libro_autor la ON la.id_libro = l.id
                LEFT JOIN autores a ON a.id = la.id_autor
                LEFT JOIN libro_etiqueta le
                    ON le.id_libro = l.id AND le.id_etiqueta = ?
                {where}
                ORDER BY (le.orden IS NULL), le.orden, l.titulo COLLATE NOCASE
            """
            parametros = [id_etiqueta] + parametros
        elif id_categoria is not None:
            # Igual que con id_etiqueta: se respeta el orden en que se
            # fueron añadiendo los libros a esta categoría en concreto
            # (no a sus subgéneros) en vez del alfabético — así añadir
            # varios libros de golpe a un género no los deja
            # "desordenados" frente al orden en que se importaron.
            consulta = f"""
                SELECT DISTINCT l.*, lc.orden AS orden_en_categoria
                FROM libros l
                LEFT JOIN libro_autor la ON la.id_libro = l.id
                LEFT JOIN autores a ON a.id = la.id_autor
                LEFT JOIN libro_categoria lc
                    ON lc.id_libro = l.id AND lc.id_categoria = ?
                {where}
                ORDER BY (lc.orden IS NULL), lc.orden, l.titulo COLLATE NOCASE
            """
            parametros = [id_categoria] + parametros
        else:
            consulta = f"""
                SELECT DISTINCT l.*
                FROM libros l
                LEFT JOIN libro_autor la ON la.id_libro = l.id
                LEFT JOIN autores a ON a.id = la.id_autor
                {where}
                ORDER BY l.titulo COLLATE NOCASE
            """

        with self._conexion() as conexion:
            return conexion.execute(consulta, parametros).fetchall()

    def obtener_autores_por_libros(self, ids_libro: list[int]) -> dict[int, list[str]]:
        """
        Devuelve los autores de varios libros en una sola consulta, en vez
        de una consulta por libro — evita el problema N+1 al construir la
        lista completa de la Biblioteca (una conexión SQLite por libro es
        lento incluso con WAL cuando hay cientos de libros).
        """
        if not ids_libro:
            return {}
        marcadores = ",".join("?" * len(ids_libro))
        with self._conexion() as conexion:
            filas = conexion.execute(
                f"""
                SELECT la.id_libro AS id_libro, a.nombre AS nombre
                FROM libro_autor la
                JOIN autores a ON a.id = la.id_autor
                WHERE la.id_libro IN ({marcadores})
                ORDER BY a.nombre COLLATE NOCASE
                """,
                ids_libro,
            ).fetchall()
        resultado: dict[int, list[str]] = {id_libro: [] for id_libro in ids_libro}
        for fila in filas:
            resultado[fila["id_libro"]].append(fila["nombre"])
        return resultado

    def obtener_autores_de_libro(self, id_libro: int) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute(
                """
                SELECT a.id, a.nombre FROM autores a
                JOIN libro_autor la ON la.id_autor = a.id
                WHERE la.id_libro = ?
                ORDER BY a.nombre
                """,
                (id_libro,),
            ).fetchall()

    # ANCLAJE_INICIO: RESUMEN_BIBLIOTECA_ASISTENTE
    def resumen_para_asistente(self, limite_top=5, limite_sagas=10) -> dict:
        """
        Agregados de biblioteca.db para el contexto del Asistente de
        Biblioteca en modo general (sin libro/saga/categoría concretos
        seleccionados): total de libros, conteos por estado, autores y
        géneros más frecuentes, y sagas con su número de libros. Se
        calcula al vuelo en cada apertura del chat —directamente sobre el
        estado actual de la base de datos—, así que altas y bajas de
        libros se reflejan solas sin necesidad de mantener nada
        sincronizado aparte.
        """
        with self._conexion() as conexion:
            total = conexion.execute("SELECT COUNT(*) AS n FROM libros").fetchone()["n"]
            estados = conexion.execute(
                "SELECT SUM(favorito) AS favoritos, SUM(leido) AS leidos, "
                "SUM(en_pendientes) AS pendientes, SUM(leyendo_ahora) AS leyendo "
                "FROM libros"
            ).fetchone()
            autores = conexion.execute(
                """
                SELECT a.nombre, COUNT(*) AS total FROM autores a
                JOIN libro_autor la ON la.id_autor = a.id
                GROUP BY a.id ORDER BY total DESC, a.nombre LIMIT ?
                """,
                (limite_top,),
            ).fetchall()
            generos = conexion.execute(
                """
                SELECT c.nombre, COUNT(*) AS total FROM categorias c
                JOIN libro_categoria lc ON lc.id_categoria = c.id
                GROUP BY c.id ORDER BY total DESC, c.nombre LIMIT ?
                """,
                (limite_top,),
            ).fetchall()
            sagas = conexion.execute(
                """
                SELECT e.nombre, COUNT(*) AS total FROM etiquetas e
                JOIN libro_etiqueta le ON le.id_etiqueta = e.id
                GROUP BY e.id ORDER BY total DESC, e.nombre LIMIT ?
                """,
                (limite_sagas,),
            ).fetchall()
        return {
            "total": total,
            "favoritos": estados["favoritos"] or 0,
            "leidos": estados["leidos"] or 0,
            "pendientes": estados["pendientes"] or 0,
            "leyendo": estados["leyendo"] or 0,
            "autores_frecuentes": [dict(a) for a in autores],
            "generos_frecuentes": [dict(g) for g in generos],
            "sagas": [dict(s) for s in sagas],
        }
    # ANCLAJE_FIN: RESUMEN_BIBLIOTECA_ASISTENTE

    # ANCLAJE_INICIO: CATALOGO_COMPLETO_ASISTENTE
    def catalogo_para_asistente(self, limite=800) -> dict:
        """
        Listado completo (título, autor, saga) de toda la Biblioteca para el
        contexto del Asistente en modo general, además del resumen agregado
        de resumen_para_asistente(). Se calcula al vuelo sobre el estado
        actual de biblioteca.db —sin caché ni detección de cambios—, así que
        siempre está al día con solo volver a abrir el chat: el coste real
        de recalcularlo (una consulta SQL) y de reenviarlo (texto plano de
        títulos y autores) es insignificante frente al de cachearlo y tener
        que invalidar esa caché cada vez que se añade o borra un libro.

        limite acota el número de libros listados (no las consultas del
        resumen agregado), para no generar un texto desproporcionado en
        bibliotecas realmente enormes.
        """
        with self._conexion() as conexion:
            filas = conexion.execute(
                """
                SELECT
                    l.titulo,
                    (SELECT GROUP_CONCAT(a.nombre, ', ')
                     FROM autores a JOIN libro_autor la ON la.id_autor = a.id
                     WHERE la.id_libro = l.id) AS autores,
                    (SELECT GROUP_CONCAT(e.nombre, ', ')
                     FROM etiquetas e JOIN libro_etiqueta le ON le.id_etiqueta = e.id
                     WHERE le.id_libro = l.id) AS sagas
                FROM libros l
                ORDER BY l.titulo COLLATE NOCASE
                """
            ).fetchall()
        total = len(filas)
        return {"total": total, "libros": [dict(f) for f in filas[:limite]]}
    # ANCLAJE_FIN: CATALOGO_COMPLETO_ASISTENTE

    # ── Actualización de estado ─────────────────────────────────────────────

    def actualizar_punto_lectura(self, id_libro: int, posicion: int):
        with self._conexion() as conexion:
            conexion.execute(
                "UPDATE libros SET ultimo_punto_lectura = ? WHERE id = ?", (posicion, id_libro)
            )

    _CAMPOS_ESTADO_EXCLUYENTE = ("en_pendientes", "leyendo_ahora", "leido")

    def establecer_bandera(self, id_libro: int, campo: str, valor: bool):
        """
        favorito es independiente y se combina con cualquier estado.
        en_pendientes / leyendo_ahora / leido son mutuamente excluyentes
        entre sí — marcar uno desmarca los otros dos automáticamente,
        porque un libro solo puede estar en una etapa de lectura a la vez.
        """
        campos_validos = {"favorito", *self._CAMPOS_ESTADO_EXCLUYENTE}
        if campo not in campos_validos:
            raise ValueError(f"Campo de bandera no válido: {campo}")
        with self._conexion() as conexion:
            if campo in self._CAMPOS_ESTADO_EXCLUYENTE and valor:
                for otro_campo in self._CAMPOS_ESTADO_EXCLUYENTE:
                    if otro_campo != campo:
                        conexion.execute(
                            f"UPDATE libros SET {otro_campo} = 0 WHERE id = ?", (id_libro,)
                        )
            conexion.execute(
                f"UPDATE libros SET {campo} = ? WHERE id = ?", (int(valor), id_libro)
            )

    def asignar_etiqueta(self, id_libro: int, nombre_etiqueta: str, orden: Optional[int] = None):
        with self._conexion() as conexion:
            id_etiqueta = self.obtener_o_crear_etiqueta(conexion, nombre_etiqueta)
            conexion.execute(
                "INSERT OR IGNORE INTO libro_etiqueta (id_libro, id_etiqueta, orden) VALUES (?, ?, ?)",
                (id_libro, id_etiqueta, orden),
            )

    def quitar_libro(self, id_libro: int):
        with self._conexion() as conexion:
            conexion.execute("DELETE FROM libros WHERE id = ?", (id_libro,))

    # ── Re-enrutado y renombrado seguro ─────────────────────────────────────

    def actualizar_ruta_archivo(self, id_libro: int, ruta_nueva: str):
        """
        Actualiza la ruta física de un libro. Debe llamarse únicamente
        después de haber verificado que el archivo existe en la ruta
        nueva (ya sea por relocalización manual o por renombrado físico
        con éxito verificado) — nunca a ciegas.
        """
        with self._conexion() as conexion:
            conexion.execute(
                "UPDATE libros SET ruta_archivo = ? WHERE id = ?", (ruta_nueva, id_libro)
            )

    def confirmar_titulo_revisado(self, id_libro: int, ruta_nueva: str, titulo_nuevo: str):
        with self._conexion() as conexion:
            conexion.execute(
                """
                UPDATE libros
                SET ruta_archivo = ?, titulo = ?, titulo_revisado = 1
                WHERE id = ?
                """,
                (ruta_nueva, titulo_nuevo, id_libro),
            )

    def obtener_pendientes_de_revision(self) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute(
                "SELECT * FROM libros WHERE titulo_revisado = 0 ORDER BY titulo COLLATE NOCASE"
            ).fetchall()

    # ── Reglas de pronunciación por libro/saga ──────────────────────────────
    # Las reglas de alcance "global" siguen viviendo en pronunciacion.json
    # (DiccionarioPronunciacion) — esta tabla solo cubre "libro" y "saga",
    # que necesitan quedar asociadas a un id_referencia concreto y por
    # tanto encajan mejor en la base de datos que en un JSON plano.

    def listar_reglas_diccionario(self, tipo_alcance: str, id_referencia: int) -> list[sqlite3.Row]:
        if tipo_alcance not in ("libro", "saga"):
            raise ValueError("tipo_alcance debe ser 'libro' o 'saga' aquí")
        with self._conexion() as conexion:
            return conexion.execute(
                """
                SELECT id, patron_origen, sustitucion FROM diccionario_reglas
                WHERE tipo_alcance = ? AND id_referencia = ?
                ORDER BY patron_origen COLLATE NOCASE
                """,
                (tipo_alcance, id_referencia),
            ).fetchall()

    def anadir_regla_diccionario(
        self, patron_origen: str, sustitucion: str, tipo_alcance: str, id_referencia: int
    ) -> int:
        if tipo_alcance not in ("libro", "saga"):
            raise ValueError("tipo_alcance debe ser 'libro' o 'saga' aquí")
        with self._conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO diccionario_reglas (patron_origen, sustitucion, tipo_alcance, id_referencia)
                VALUES (?, ?, ?, ?)
                """,
                (patron_origen, sustitucion, tipo_alcance, id_referencia),
            )
            return cursor.lastrowid

    def actualizar_regla_diccionario(self, id_regla: int, patron_origen: str, sustitucion: str):
        with self._conexion() as conexion:
            conexion.execute(
                "UPDATE diccionario_reglas SET patron_origen = ?, sustitucion = ? WHERE id = ?",
                (patron_origen, sustitucion, id_regla),
            )

    def eliminar_regla_diccionario(self, id_regla: int):
        with self._conexion() as conexion:
            conexion.execute("DELETE FROM diccionario_reglas WHERE id = ?", (id_regla,))

    def listar_reglas_diccionario_para_libro(self, id_libro: int) -> list[sqlite3.Row]:
        """
        Reglas aplicables a un libro concreto al leerlo: las suyas propias
        (tipo_alcance='libro') más las de todas las sagas/etiquetas a las
        que pertenezca (tipo_alcance='saga'). No incluye las globales,
        que se aplican aparte desde DiccionarioPronunciacion.
        """
        etiquetas = self.obtener_etiquetas_de_libro(id_libro)
        with self._conexion() as conexion:
            filas = list(
                conexion.execute(
                    """
                    SELECT id, patron_origen, sustitucion FROM diccionario_reglas
                    WHERE tipo_alcance = 'libro' AND id_referencia = ?
                    """,
                    (id_libro,),
                ).fetchall()
            )
            for etiqueta in etiquetas:
                filas.extend(
                    conexion.execute(
                        """
                        SELECT id, patron_origen, sustitucion FROM diccionario_reglas
                        WHERE tipo_alcance = 'saga' AND id_referencia = ?
                        """,
                        (etiqueta["id"],),
                    ).fetchall()
                )
        return filas

    # ANCLAJE_INICIO: EXPORTACIONES_PENDIENTES
    # Persistencia de exportaciones del Creador de Audiolibros cortadas por
    # falta de cuota o canceladas a medias (sección 3.4 de la planificación
    # v3.0). El motor de exportación (grabador_audio.py) no toca SQLite —
    # solo calcula y devuelve el punto de corte; esta capa es quien lo
    # persiste, respetando la separación de responsabilidades ya acordada.

    def registrar_exportacion_pendiente(
        self,
        id_libro: int,
        modo: str,
        proveedor: str,
        punto_corte: Optional[int] = None,
        capitulo_pendiente: Optional[int] = None,
        ruta_parcial: Optional[str] = None,
    ) -> int:
        with self._conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO exportaciones_pendientes
                    (id_libro, modo, proveedor, punto_corte, capitulo_pendiente, ruta_parcial)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (id_libro, modo, proveedor, punto_corte, capitulo_pendiente, ruta_parcial),
            )
            return cursor.lastrowid

    def obtener_exportaciones_pendientes(self, id_libro: int) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute(
                "SELECT * FROM exportaciones_pendientes WHERE id_libro = ? ORDER BY id",
                (id_libro,),
            ).fetchall()

    def obtener_ids_libros_con_exportacion_pendiente(self) -> set[int]:
        """
        IDs de todos los libros con al menos una exportación de audiolibro
        a medias, sin importar el proveedor ni el modo — para poder
        marcarlos en la Biblioteca y no depender de recordar cuál era el
        último libro que se estaba exportando.
        """
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT DISTINCT id_libro FROM exportaciones_pendientes"
            ).fetchall()
        return {fila["id_libro"] for fila in filas}

    def eliminar_exportacion_pendiente(self, id_exportacion: int):
        with self._conexion() as conexion:
            conexion.execute(
                "DELETE FROM exportaciones_pendientes WHERE id = ?", (id_exportacion,)
            )

    def eliminar_exportaciones_pendientes_de_libro(self, id_libro: int):
        """
        Limpia cualquier pendiente anterior de este libro antes de arrancar
        una exportación nueva desde cero, para no acumular registros de
        intentos ya abandonados junto a los de la exportación actual.
        """
        with self._conexion() as conexion:
            conexion.execute(
                "DELETE FROM exportaciones_pendientes WHERE id_libro = ?", (id_libro,)
            )
    # ANCLAJE_FIN: EXPORTACIONES_PENDIENTES
