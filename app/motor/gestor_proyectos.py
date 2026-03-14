"""
gestor_config.py  →  GestorProyectos
--------------------------------------
Motor de gestión de proyectos para Epub-TTS.

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


# ── Categorías de proyecto disponibles ───────────────────────────────────────
# Lista fija de 10 categorías. El campo 'tipo' en proyectos.json es ahora
# una lista, por lo que un proyecto puede pertenecer a varias a la vez.
TIPOS_PROYECTO = [
    "Serie",
    "Libro",
    "Fantasía",
    "Distopía",
    "Tecno-thriller",
    "Diálogos",
    "Tutorial",
    "Publicidad",
    "Artículo",
    "Otros",
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
                    # Migración: convierte el campo 'tipo' de str a list
                    for p in datos.get("proyectos", {}).values():
                        if isinstance(p.get("tipo"), str):
                            t = p["tipo"]
                            p["tipo"] = [t] if t else []
                    return datos
        except Exception:
            pass
        return {"version": 1, "proyectos": {}}

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
        # Normalizar tipo a lista y filtrar solo categorías válidas
        if isinstance(tipo, str):
            tipo = [tipo] if tipo else []
        tipo = [t for t in tipo if t in TIPOS_PROYECTO]

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

        self.guardar()
        return nuevo_id

    def obtener_proyecto(self, proyecto_id: str) -> Optional[dict]:
        """Devuelve el dict del proyecto o None si no existe."""
        return self._datos["proyectos"].get(proyecto_id)

    def listar_proyectos_raiz(self) -> list:
        """Devuelve los proyectos sin padre (nivel raíz), ordenados por nombre."""
        raices = [
            p for p in self._datos["proyectos"].values()
            if p.get("padre") is None
        ]
        return sorted(raices, key=lambda p: p["nombre"].lower())

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

    def cambiar_tipo(self, proyecto_id: str, nuevo_tipo):
        """Cambia las categorías de un proyecto. nuevo_tipo es una lista de strings."""
        if isinstance(nuevo_tipo, str):
            nuevo_tipo = [nuevo_tipo] if nuevo_tipo else []
        if proyecto_id in self._datos["proyectos"]:
            self._datos["proyectos"][proyecto_id]["tipo"] = list(nuevo_tipo)
            self.guardar()

    def eliminar_proyecto(self, proyecto_id: str, recursivo: bool = False):
        """
        Mueve un proyecto (y opcionalmente sus hijos) a la papelera (soft-delete).
        Si recursivo=True, incluye todos los hijos en cascada en la misma entrada.
        Si recursivo=False y tiene hijos, lanza ValueError.
        Permite restaurar con restaurar_proyecto(raiz_id).
        """
        import datetime

        proyecto = self._datos["proyectos"].get(proyecto_id)
        if not proyecto:
            return

        hijos = proyecto.get("hijos", [])
        if hijos and not recursivo:
            raise ValueError(
                f"El proyecto '{proyecto['nombre']}' tiene {len(hijos)} hijo(s). "
                "Usa recursivo=True para eliminarlo junto con sus hijos."
            )

        # Recolectar todo el subárbol en una sola entrada de papelera
        entrada = {
            "timestamp": datetime.datetime.now().isoformat(),
            "raiz_id": proyecto_id,
            "padre_original": proyecto.get("padre"),
            "proyectos": {},   # {id: copia_del_proyecto}
        }

        def _recolectar(pid):
            p = self._datos["proyectos"].get(pid)
            if p:
                entrada["proyectos"][pid] = dict(p)
                for hijo_id in p.get("hijos", []):
                    _recolectar(hijo_id)

        _recolectar(proyecto_id)

        # Desvincularse del padre
        padre_id = proyecto.get("padre")
        if padre_id and padre_id in self._datos["proyectos"]:
            hijos_padre = self._datos["proyectos"][padre_id]["hijos"]
            if proyecto_id in hijos_padre:
                hijos_padre.remove(proyecto_id)

        # Eliminar del dict activo (en orden: hijos antes que raíz)
        def _borrar_recursivo(pid):
            p = self._datos["proyectos"].get(pid)
            if p:
                for hijo_id in list(p.get("hijos", [])):
                    _borrar_recursivo(hijo_id)
                del self._datos["proyectos"][pid]

        _borrar_recursivo(proyecto_id)

        # Añadir a la papelera
        self._datos.setdefault("papelera", []).append(entrada)
        self.guardar()

    # ── Papelera (soft-delete) ─────────────────────────────────────────────────

    def listar_papelera(self) -> list:
        """
        Devuelve la lista de entradas en la papelera.
        Cada entrada es un dict con: raiz_id, timestamp, padre_original, proyectos.
        """
        return list(self._datos.get("papelera", []))

    def restaurar_proyecto(self, raiz_id: str) -> bool:
        """
        Restaura un proyecto desde la papelera al lugar que ocupaba antes.
        Si el padre original ya no existe, se restaura como raíz.
        Devuelve True si se restauró, False si no se encontró en la papelera.
        """
        papelera = self._datos.get("papelera", [])
        idx = next(
            (i for i, e in enumerate(papelera) if e["raiz_id"] == raiz_id),
            None,
        )
        if idx is None:
            return False

        entrada = papelera.pop(idx)

        # Reintegrar todos los proyectos del subárbol
        for pid, p in entrada["proyectos"].items():
            self._datos["proyectos"][pid] = p

        # Re-vincular al padre original si sigue existiendo
        padre_id = entrada.get("padre_original")
        if padre_id and padre_id in self._datos["proyectos"]:
            padre = self._datos["proyectos"][padre_id]
            if raiz_id not in padre.get("hijos", []):
                padre.setdefault("hijos", []).append(raiz_id)
        else:
            # El padre ya no existe: la raíz pasa a ser proyecto raíz
            self._datos["proyectos"][raiz_id]["padre"] = None

        self.guardar()
        return True

    def vaciar_papelera(self):
        """Elimina definitiva e irreversiblemente todos los proyectos en la papelera."""
        self._datos["papelera"] = []
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

    def mover_proyecto(self, proyecto_id: str, delta: int) -> bool:
        """
        Mueve un proyecto una posición arriba (delta=-1) o abajo (delta=+1)
        dentro de la lista de hijos de su padre.
        Los proyectos raíz no son reordenables manualmente (se muestran alfabéticamente).
        Devuelve True si se realizó el movimiento, False si ya está en el límite.
        """
        proyecto = self.obtener_proyecto(proyecto_id)
        if not proyecto:
            return False
        padre_id = proyecto.get("padre")
        if not padre_id:
            return False  # Proyectos raíz: ordenados alfabéticamente, no reordenables
        padre = self._datos["proyectos"].get(padre_id)
        if not padre:
            return False
        hijos = padre.get("hijos", [])
        if proyecto_id not in hijos:
            return False
        idx = hijos.index(proyecto_id)
        nuevo_idx = idx + delta
        if nuevo_idx < 0 or nuevo_idx >= len(hijos):
            return False
        hijos[idx], hijos[nuevo_idx] = hijos[nuevo_idx], hijos[idx]
        self.guardar()
        return True

    def reparentar_proyecto(
        self, proyecto_id: str, nuevo_padre_id: Optional[str]
    ) -> bool:
        """
        Mueve un proyecto a un nuevo padre (o a raíz si nuevo_padre_id es None).

        Previene ciclos: no se puede hacer un proyecto hijo de sí mismo ni de
        alguno de sus propios descendientes.
        Devuelve True si el movimiento se realizó, False si no es posible.
        """
        proyecto = self.obtener_proyecto(proyecto_id)
        if not proyecto:
            return False

        # Sin cambio real
        if proyecto.get("padre") == nuevo_padre_id:
            return False

        # No puede ser hijo de sí mismo
        if nuevo_padre_id == proyecto_id:
            return False

        # Prevenir ciclos: recorrer la cadena de ancestros del destino
        if nuevo_padre_id:
            actual = nuevo_padre_id
            visitados: set = set()
            while actual and actual not in visitados:
                visitados.add(actual)
                if actual == proyecto_id:
                    return False  # ciclo detectado
                p = self._datos["proyectos"].get(actual)
                if not p:
                    break
                actual = p.get("padre")

        # Desvincularse del padre actual
        padre_actual_id = proyecto.get("padre")
        if padre_actual_id and padre_actual_id in self._datos["proyectos"]:
            hijos = self._datos["proyectos"][padre_actual_id]["hijos"]
            if proyecto_id in hijos:
                hijos.remove(proyecto_id)

        # Vincularse al nuevo padre
        proyecto["padre"] = nuevo_padre_id
        if nuevo_padre_id and nuevo_padre_id in self._datos["proyectos"]:
            hijos_nuevo = self._datos["proyectos"][nuevo_padre_id].setdefault("hijos", [])
            if proyecto_id not in hijos_nuevo:
                hijos_nuevo.append(proyecto_id)

        self.guardar()
        return True

    def listar_todos(self) -> list:
        """Devuelve todos los proyectos en lista plana, ordenados por nombre."""
        return sorted(
            self._datos["proyectos"].values(),
            key=lambda p: p["nombre"].lower(),
        )

    def total_proyectos(self) -> int:
        return len(self._datos["proyectos"])
