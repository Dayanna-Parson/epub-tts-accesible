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

VERSION_ESQUEMA = 1

_ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS autores (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
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

CREATE TABLE IF NOT EXISTS libro_autor (
    id_libro   INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_autor   INTEGER NOT NULL REFERENCES autores(id) ON DELETE CASCADE,
    PRIMARY KEY (id_libro, id_autor)
);

CREATE TABLE IF NOT EXISTS libro_etiqueta (
    id_libro    INTEGER NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    id_etiqueta INTEGER NOT NULL REFERENCES etiquetas(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_libros_categoria   ON libros(id_categoria);
CREATE INDEX IF NOT EXISTS idx_libros_favorito    ON libros(favorito);
CREATE INDEX IF NOT EXISTS idx_libros_pendientes  ON libros(en_pendientes);
CREATE INDEX IF NOT EXISTS idx_libros_leyendo     ON libros(leyendo_ahora);
CREATE INDEX IF NOT EXISTS idx_libros_leido       ON libros(leido);
CREATE INDEX IF NOT EXISTS idx_libro_autor_autor  ON libro_autor(id_autor);
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

    def obtener_o_crear_categoria(self, conexion, nombre: str) -> int:
        nombre = nombre.strip()
        fila = conexion.execute(
            "SELECT id FROM categorias WHERE nombre = ? COLLATE NOCASE", (nombre,)
        ).fetchone()
        if fila:
            return fila["id"]
        cursor = conexion.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
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

    def listar_categorias(self) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute("SELECT id, nombre FROM categorias ORDER BY nombre").fetchall()

    def listar_etiquetas(self) -> list[sqlite3.Row]:
        with self._conexion() as conexion:
            return conexion.execute("SELECT id, nombre FROM etiquetas ORDER BY nombre").fetchall()

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
        categoria: Optional[str] = None,
        titulo_revisado: bool = True,
    ) -> int:
        """
        Inserta un único libro con sus autores y categoría, resolviendo
        las tablas auxiliares dentro de la misma transacción.
        """
        with self._conexion() as conexion:
            return self._insertar_libro_en_conexion(
                conexion, ruta_archivo, titulo, formato, autores, categoria, titulo_revisado
            )

    def insertar_libros_lote(self, libros: list[dict]) -> int:
        """
        Inserta varios libros en una única transacción.

        Cada elemento de `libros` es un dict con las claves:
        ruta_archivo, titulo, formato, autores (list[str], opcional),
        categoria (str, opcional), titulo_revisado (bool, opcional).

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
                        datos.get("categoria"),
                        datos.get("titulo_revisado", True),
                    )
                    insertados += 1
                except sqlite3.IntegrityError:
                    logger.warning(
                        "[GestorBiblioteca] Ruta ya indexada, se omite: %s", datos.get("ruta_archivo")
                    )
        return insertados

    def _insertar_libro_en_conexion(
        self, conexion, ruta_archivo, titulo, formato, autores, categoria, titulo_revisado
    ) -> int:
        id_categoria = self.obtener_o_crear_categoria(conexion, categoria) if categoria else None
        cursor = conexion.execute(
            """
            INSERT INTO libros (ruta_archivo, titulo, formato, id_categoria, titulo_revisado)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ruta_archivo, titulo, formato, id_categoria, int(titulo_revisado)),
        )
        id_libro = cursor.lastrowid
        for nombre_autor in (autores or []):
            id_autor = self.obtener_o_crear_autor(conexion, nombre_autor)
            conexion.execute(
                "INSERT OR IGNORE INTO libro_autor (id_libro, id_autor) VALUES (?, ?)",
                (id_libro, id_autor),
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
        condiciones = []
        parametros = []

        if texto:
            condiciones.append("(l.titulo LIKE ? OR a.nombre LIKE ?)")
            comodin = f"%{texto}%"
            parametros.extend([comodin, comodin])
        if id_categoria is not None:
            condiciones.append("l.id_categoria = ?")
            parametros.append(id_categoria)
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

    def establecer_bandera(self, id_libro: int, campo: str, valor: bool):
        campos_validos = {"favorito", "en_pendientes", "leyendo_ahora", "leido"}
        if campo not in campos_validos:
            raise ValueError(f"Campo de bandera no válido: {campo}")
        with self._conexion() as conexion:
            conexion.execute(
                f"UPDATE libros SET {campo} = ? WHERE id = ?", (int(valor), id_libro)
            )

    def asignar_etiqueta(self, id_libro: int, nombre_etiqueta: str):
        with self._conexion() as conexion:
            id_etiqueta = self.obtener_o_crear_etiqueta(conexion, nombre_etiqueta)
            conexion.execute(
                "INSERT OR IGNORE INTO libro_etiqueta (id_libro, id_etiqueta) VALUES (?, ?)",
                (id_libro, id_etiqueta),
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
