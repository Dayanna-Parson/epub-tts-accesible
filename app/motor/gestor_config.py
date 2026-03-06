"""
gestor_config.py  →  GestorProyectos
--------------------------------------
Motor de gestión de proyectos para TifloHistorias.

Gestiona la organización jerárquica de cualquier tipo de trabajo:
  Saga → Libro → Capítulo
  Autoconclusivo
  Podcast / Episodio
  Vídeo / YouTube
  Guion / Diálogo / etc.

Responsabilidades:
  - Crear, leer, actualizar y eliminar proyectos con jerarquía libre.
  - Asociar archivos TXT a proyectos sin tocar los propios TXT
    (los metadatos se guardan en proyectos.json, no en el archivo).
  - Heredar perfiles de voces de padre a hijo:
      Saga  define nar→vozA, jon→vozB
      Libro añade  ned→vozC
      Capítulo → hereda nar→vozA, jon→vozB, ned→vozC
  - Ofrecer una API limpia lista para conectar con la UI de fase 3.

Nota de arquitectura:
  Este módulo es puro motor (sin wx). La UI que lo consuma (ventana de
  gestión de proyectos + combo en PestanaGrabacion) se implementará en
  la Fase 3 del proyecto.
"""

import json
import os
import uuid
from typing import Optional

from app.config_rutas import ruta_config


# ── Tipos de proyecto disponibles ────────────────────────────────────────────
TIPOS_PROYECTO = [
    "saga",
    "libro",
    "capitulo",
    "autoconclusivo",
    "podcast",
    "episodio",
    "video_youtube",
    "guion",
    "dialogo",
    "otro",
]

# Ruta del archivo de persistencia
RUTA_PROYECTOS = ruta_config("proyectos.json")


# ═════════════════════════════════════════════════════════════════════════════
class GestorProyectos:
    """
    Motor de gestión de proyectos.

    Estructura del JSON interno (proyectos.json):
    {
      "version": 1,
      "proyectos": {
        "<uuid>": {
          "id":       str,
          "nombre":   str,
          "tipo":     str,           # ver TIPOS_PROYECTO
          "padre":    str | null,    # id del proyecto padre (null = raíz)
          "hijos":    [str, ...],    # ids de proyectos hijos
          "voces":    {              # perfil de voces propio de este nivel
            "<etiqueta>": { datos_voz }
          },
          "archivos": [str, ...]     # rutas absolutas de TXT asociados
        }
      }
    }

    Uso básico:
        gestor = GestorProyectos()
        saga_id = gestor.crear_proyecto("Crónicas del Hielo y Fuego", "saga")
        libro_id = gestor.crear_proyecto("Juego de Tronos", "libro", padre_id=saga_id)
        cap_id   = gestor.crear_proyecto("Capítulo 01", "capitulo", padre_id=libro_id)
        gestor.asociar_archivo(cap_id, "/ruta/cap01.txt")
        gestor.guardar_voces_proyecto(saga_id, {"nar": voz_a, "jon": voz_b})
        voces = gestor.obtener_voces_heredadas(cap_id)
        # → {"nar": voz_a, "jon": voz_b}
    """

    def __init__(self):
        self._datos = self._cargar()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _cargar(self) -> dict:
        try:
            if os.path.exists(RUTA_PROYECTOS):
                with open(RUTA_PROYECTOS, "r", encoding="utf-8") as f:
                    contenido = f.read().strip()
                if contenido:
                    datos = json.loads(contenido)
                    # Migración: asegurar que existe orden_raiz
                    if "orden_raiz" not in datos:
                        raices = [
                            p["id"] for p in datos.get("proyectos", {}).values()
                            if p.get("padre") is None
                        ]
                        datos["orden_raiz"] = sorted(
                            raices,
                            key=lambda pid: datos["proyectos"].get(pid, {}).get("nombre", "").lower()
                        )
                    return datos
        except Exception:
            pass
        return {"version": 1, "proyectos": {}, "orden_raiz": []}

    def guardar(self):
        """Persiste el estado actual en proyectos.json."""
        try:
            os.makedirs(os.path.dirname(RUTA_PROYECTOS), exist_ok=True)
            with open(RUTA_PROYECTOS, "w", encoding="utf-8") as f:
                json.dump(self._datos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise RuntimeError(f"No se pudo guardar proyectos.json: {e}")

    def recargar(self):
        """Recarga desde disco (útil si otra instancia modificó el archivo)."""
        self._datos = self._cargar()

    # ── CRUD de proyectos ─────────────────────────────────────────────────────

    def crear_proyecto(
        self, nombre: str, tipo: str, padre_id: Optional[str] = None
    ) -> str:
        """
        Crea un nuevo proyecto y devuelve su id.
        Si se especifica padre_id, lo registra como hijo del padre.
        """
        if tipo not in TIPOS_PROYECTO:
            tipo = "otro"

        nuevo_id = str(uuid.uuid4())
        self._datos["proyectos"][nuevo_id] = {
            "id":       nuevo_id,
            "nombre":   nombre,
            "tipo":     tipo,
            "padre":    padre_id,
            "hijos":    [],
            "voces":    {},
            "archivos": [],
        }

        if padre_id and padre_id in self._datos["proyectos"]:
            self._datos["proyectos"][padre_id]["hijos"].append(nuevo_id)
        else:
            # Proyecto raíz: añadir al orden
            self._datos.setdefault("orden_raiz", []).append(nuevo_id)

        self.guardar()
        return nuevo_id

    def obtener_proyecto(self, proyecto_id: str) -> Optional[dict]:
        """Devuelve el dict del proyecto o None si no existe."""
        return self._datos["proyectos"].get(proyecto_id)

    def listar_proyectos_raiz(self) -> list:
        """Devuelve los proyectos sin padre (nivel raíz), en orden personalizado."""
        orden = self._datos.get("orden_raiz", [])
        proyectos = self._datos["proyectos"]
        # Proyectos en el orden guardado
        resultado = [proyectos[pid] for pid in orden if pid in proyectos]
        # Agregar los que no estén en orden_raiz (por si acaso)
        ids_en_orden = set(orden)
        for p in proyectos.values():
            if p.get("padre") is None and p["id"] not in ids_en_orden:
                resultado.append(p)
        return resultado

    def listar_hijos(self, proyecto_id: str) -> list:
        """Devuelve los proyectos hijos directos de un proyecto."""
        proyecto = self.obtener_proyecto(proyecto_id)
        if not proyecto:
            return []
        return [
            self._datos["proyectos"][h]
            for h in proyecto.get("hijos", [])
            if h in self._datos["proyectos"]
        ]

    def obtener_ruta_completa(self, proyecto_id: str) -> list:
        """
        Devuelve la cadena de ancestros desde la raíz hasta el proyecto.
        Útil para mostrar breadcrumbs: [saga, libro, capítulo]
        """
        cadena = []
        actual_id = proyecto_id
        visitados = set()
        while actual_id and actual_id not in visitados:
            visitados.add(actual_id)
            proyecto = self._datos["proyectos"].get(actual_id)
            if not proyecto:
                break
            cadena.append(proyecto)
            actual_id = proyecto.get("padre")
        cadena.reverse()
        return cadena

    def renombrar_proyecto(self, proyecto_id: str, nuevo_nombre: str):
        """Cambia el nombre de un proyecto."""
        if proyecto_id in self._datos["proyectos"]:
            self._datos["proyectos"][proyecto_id]["nombre"] = nuevo_nombre
            self.guardar()

    def cambiar_tipo(self, proyecto_id: str, nuevo_tipo: str):
        """Cambia el tipo de un proyecto."""
        if proyecto_id in self._datos["proyectos"]:
            self._datos["proyectos"][proyecto_id]["tipo"] = nuevo_tipo
            self.guardar()

    def eliminar_proyecto(self, proyecto_id: str, recursivo: bool = False):
        """
        Elimina un proyecto.
        Si recursivo=True, elimina también todos sus hijos en cascada.
        Si recursivo=False y tiene hijos, lanza ValueError.
        """
        proyecto = self._datos["proyectos"].get(proyecto_id)
        if not proyecto:
            return

        hijos = proyecto.get("hijos", [])
        if hijos and not recursivo:
            raise ValueError(
                f"El proyecto '{proyecto['nombre']}' tiene {len(hijos)} hijo(s). "
                "Usa recursivo=True para eliminarlo junto con sus hijos."
            )

        # Eliminar hijos primero si es recursivo
        if recursivo:
            for hijo_id in list(hijos):
                self.eliminar_proyecto(hijo_id, recursivo=True)

        # Desvincularse del padre o del orden raíz
        padre_id = proyecto.get("padre")
        if padre_id and padre_id in self._datos["proyectos"]:
            hijos_padre = self._datos["proyectos"][padre_id]["hijos"]
            if proyecto_id in hijos_padre:
                hijos_padre.remove(proyecto_id)
        else:
            orden_raiz = self._datos.get("orden_raiz", [])
            if proyecto_id in orden_raiz:
                orden_raiz.remove(proyecto_id)

        del self._datos["proyectos"][proyecto_id]
        self.guardar()

    # ── Asociación de archivos TXT ────────────────────────────────────────────

    def asociar_archivo(self, proyecto_id: str, ruta_txt: str):
        """
        Asocia un archivo TXT a un proyecto.
        Si el TXT ya estaba en otro proyecto, se desvincula de allí primero.
        """
        ruta_abs = os.path.abspath(ruta_txt)

        # Desasociar de cualquier proyecto anterior
        self.desasociar_archivo(ruta_abs)

        if proyecto_id not in self._datos["proyectos"]:
            return

        archivos = self._datos["proyectos"][proyecto_id].setdefault("archivos", [])
        if ruta_abs not in archivos:
            archivos.append(ruta_abs)

        self.guardar()

    def desasociar_archivo(self, ruta_txt: str):
        """Elimina la asociación de un TXT con cualquier proyecto."""
        ruta_abs = os.path.abspath(ruta_txt)
        for proyecto in self._datos["proyectos"].values():
            archivos = proyecto.get("archivos", [])
            if ruta_abs in archivos:
                archivos.remove(ruta_abs)
        self.guardar()

    def proyecto_de_archivo(self, ruta_txt: str) -> Optional[dict]:
        """
        Devuelve el proyecto al que pertenece un TXT, o None si no está asociado.
        """
        ruta_abs = os.path.abspath(ruta_txt)
        for proyecto in self._datos["proyectos"].values():
            if ruta_abs in proyecto.get("archivos", []):
                return proyecto
        return None

    # ── Gestión de perfiles de voces ──────────────────────────────────────────

    def guardar_voces_proyecto(self, proyecto_id: str, voces: dict):
        """
        Guarda (o reemplaza) el perfil de voces propio de un proyecto.
        voces = { etiqueta: datos_voz }
        """
        if proyecto_id in self._datos["proyectos"]:
            self._datos["proyectos"][proyecto_id]["voces"] = dict(voces)
            self.guardar()

    def actualizar_voz_proyecto(
        self, proyecto_id: str, etiqueta: str, datos_voz: dict
    ):
        """Añade o actualiza una sola etiqueta en el perfil de voces del proyecto."""
        if proyecto_id in self._datos["proyectos"]:
            self._datos["proyectos"][proyecto_id].setdefault("voces", {})[
                etiqueta
            ] = datos_voz
            self.guardar()

    def obtener_voces_heredadas(self, proyecto_id: str) -> dict:
        """
        Resuelve el perfil de voces completo para un proyecto aplicando herencia.

        Sube por la jerarquía (hijo → padre → abuelo → …) y combina los perfiles.
        Las voces del nivel más específico tienen prioridad sobre las del padre.

        Ejemplo:
          Saga  define: nar→vozA, jon→vozB
          Libro define: ned→vozC
          Capítulo:     (sin voces propias)
          → Resultado:  nar→vozA, jon→vozB, ned→vozC
        """
        cadena = []
        actual_id = proyecto_id
        visitados = set()

        while actual_id and actual_id not in visitados:
            visitados.add(actual_id)
            proyecto = self._datos["proyectos"].get(actual_id)
            if not proyecto:
                break
            cadena.append(proyecto.get("voces", {}))
            actual_id = proyecto.get("padre")

        # Combinar de lo más general (raíz) a lo más específico (proyecto actual)
        voces_combinadas = {}
        for nivel in reversed(cadena):
            voces_combinadas.update(nivel)

        return voces_combinadas

    # ── Utilidades ────────────────────────────────────────────────────────────

    def listar_todos(self) -> list:
        """Devuelve todos los proyectos en lista plana, ordenados por nombre."""
        return sorted(
            self._datos["proyectos"].values(),
            key=lambda p: p["nombre"].lower(),
        )

    def total_proyectos(self) -> int:
        return len(self._datos["proyectos"])

    # ── Reordenación de nodos ─────────────────────────────────────────────────

    def mover_proyecto(self, proyecto_id: str, direccion: str) -> bool:
        """
        Mueve un proyecto arriba o abajo dentro de su contenedor (hijos del padre
        o lista raíz). direccion='arriba' | 'abajo'.
        Devuelve True si el movimiento se realizó, False si ya estaba en el límite.
        """
        proyecto = self._datos["proyectos"].get(proyecto_id)
        if not proyecto:
            return False

        padre_id = proyecto.get("padre")
        if padre_id and padre_id in self._datos["proyectos"]:
            lista = self._datos["proyectos"][padre_id]["hijos"]
        else:
            lista = self._datos.setdefault("orden_raiz", [])
            if proyecto_id not in lista:
                lista.append(proyecto_id)

        try:
            idx = lista.index(proyecto_id)
        except ValueError:
            return False

        if direccion == "arriba":
            if idx == 0:
                return False
            lista[idx], lista[idx - 1] = lista[idx - 1], lista[idx]
        else:
            if idx >= len(lista) - 1:
                return False
            lista[idx], lista[idx + 1] = lista[idx + 1], lista[idx]

        self.guardar()
        return True

    # ── Gestión de archivos (verificación y relocalización) ───────────────────

    def verificar_archivos_proyecto(self, proyecto_id: str) -> list:
        """
        Devuelve lista de rutas que ya no existen en disco para el proyecto dado.
        """
        proyecto = self._datos["proyectos"].get(proyecto_id)
        if not proyecto:
            return []
        return [r for r in proyecto.get("archivos", []) if not os.path.exists(r)]

    def relocalizar_archivo(self, ruta_antigua: str, ruta_nueva: str):
        """Reemplaza la ruta de un TXT en todos los proyectos donde aparezca."""
        ruta_antigua_abs = os.path.abspath(ruta_antigua)
        ruta_nueva_abs   = os.path.abspath(ruta_nueva)
        modificado = False
        for proyecto in self._datos["proyectos"].values():
            archivos = proyecto.get("archivos", [])
            for i, r in enumerate(archivos):
                if os.path.abspath(r) == ruta_antigua_abs:
                    archivos[i] = ruta_nueva_abs
                    modificado = True
        if modificado:
            self.guardar()
