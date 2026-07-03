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

VERSION_ESQUEMA = 2

_ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS autores (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS categorias (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL COLLATE NOCASE,
    id_padre  INTEGER REFERENCES categorias(id) ON DELETE CASCADE,
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
            "INSERT INTO categorias (nombre, id_padre) VALUES (?, ?)", (nombre, id_padre)
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
        """Hijos directos de una categoría (o raíces del árbol si id_padre es None)."""
        with self._conexion() as conexion:
            return conexion.execute(
                "SELECT id, nombre, id_padre FROM categorias "
                "WHERE id_padre IS ? ORDER BY nombre COLLATE NOCASE",
                (id_padre,),
            ).fetchall()

    def listar_etiquetas(self) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute("SELECT id, nombre FROM etiquetas ORDER BY nombre").fetchall()

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
                "INSERT OR IGNORE INTO libro_categoria (id_libro, id_categoria) VALUES (?, ?)",
                (id_libro, id_categoria),
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
                "INSERT OR IGNORE INTO libro_categoria (id_libro, id_categoria) VALUES (?, ?)",
                (id_libro, id_categoria),
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
