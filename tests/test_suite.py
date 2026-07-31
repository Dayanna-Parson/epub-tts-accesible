"""
Suite de tests para Epub-TTS Accessible
========================================
Cubre las partes testables sin GUI ni hardware de audio:
  - procesador_etiquetas       (puro Python)
  - limpiador_lectura          (puro Python)
  - gestor_proyectos           (stdlib + fichero temporal)
  - control_cuota              (lógica con wx + reproductor_sonidos mockeados)
  - config_rutas               (utils de rutas)
  - gestor_perfiles            (CRUD de perfiles de usuario, fichero temporal)
  - comprobador_actualizaciones (comparación de versiones semánticas)
  - gestor_atajos              (CRUD de atajos de teclado, ficheros temporales)
  - diccionario_pronunciacion  (sustituciones fonéticas, fichero temporal)
"""

import sys
import os
import json
import unittest
import tempfile
from unittest.mock import patch, MagicMock, call

# ── Añadir raíz del proyecto al path ─────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# 1. PROCESADOR DE ETIQUETAS
# ─────────────────────────────────────────────────────────────────────────────
from app.motor.procesador_etiquetas import (
    normalizar_etiqueta,
    limpiar_nombre_archivo,
    escanear_etiquetas,
    fragmentar_texto,
)


class TestNormalizarEtiqueta(unittest.TestCase):

    def test_convierte_a_minusculas(self):
        self.assertEqual(normalizar_etiqueta("REY"), "rey")

    def test_elimina_espacios_extremos(self):
        self.assertEqual(normalizar_etiqueta("  narrador  "), "narrador")

    def test_cadena_ya_normalizada(self):
        self.assertEqual(normalizar_etiqueta("soldado"), "soldado")

    def test_vacia(self):
        self.assertEqual(normalizar_etiqueta(""), "")


class TestLimpiarNombreArchivo(unittest.TestCase):

    CHARS_PROHIBIDOS = list('\\/:*?"<>|')

    def test_elimina_caracteres_prohibidos_windows(self):
        for ch in self.CHARS_PROHIBIDOS:
            resultado = limpiar_nombre_archivo(f"archivo{ch}nombre")
            self.assertNotIn(ch, resultado, f"El carácter '{ch}' debería eliminarse")

    def test_reemplaza_por_guion_bajo(self):
        self.assertEqual(limpiar_nombre_archivo("mi:libro"), "mi_libro")

    def test_nombre_limpio_sin_cambios(self):
        self.assertEqual(limpiar_nombre_archivo("Mi Libro Final"), "Mi Libro Final")

    def test_nombre_con_multiples_prohibidos(self):
        # El punto NO está prohibido en Windows; solo < > : ? * lo están aquí
        resultado = limpiar_nombre_archivo("libro<>:?*.txt")
        for ch in '<>:?*':
            self.assertNotIn(ch, resultado)
        self.assertIn('.', resultado)  # el punto debe conservarse

    def test_limpia_guiones_extremos(self):
        # Si el resultado empieza/termina con '_' se recorta
        resultado = limpiar_nombre_archivo(":nombre:")
        self.assertFalse(resultado.startswith('_'))
        self.assertFalse(resultado.endswith('_'))

    def test_nombre_vacio(self):
        # No debe lanzar excepción
        resultado = limpiar_nombre_archivo("")
        self.assertIsInstance(resultado, str)


class TestEscanearEtiquetas(unittest.TestCase):

    def test_detecta_etiquetas_simples(self):
        texto = "{{@narrador}} Hola. {{@rey}} Buenos días."
        self.assertEqual(escanear_etiquetas(texto), ["narrador", "rey"])

    def test_orden_de_aparicion(self):
        texto = "{{@c}} {{@a}} {{@b}}"
        self.assertEqual(escanear_etiquetas(texto), ["c", "a", "b"])

    def test_sin_duplicados(self):
        texto = "{{@nar}} algo {{@nar}} otra cosa {{@rey}} fin"
        self.assertEqual(escanear_etiquetas(texto), ["nar", "rey"])

    def test_insensible_a_mayusculas(self):
        texto = "{{@NAR}} texto {{@Nar}} más"
        etiquetas = escanear_etiquetas(texto)
        self.assertEqual(len(etiquetas), 1)
        self.assertEqual(etiquetas[0], "nar")

    def test_texto_sin_etiquetas(self):
        self.assertEqual(escanear_etiquetas("Texto sin etiquetas"), [])

    def test_texto_vacio(self):
        self.assertEqual(escanear_etiquetas(""), [])

    def test_normaliza_a_minusculas(self):
        etiquetas = escanear_etiquetas("{{@SOLDADO}}")
        self.assertEqual(etiquetas, ["soldado"])


class TestFragmentarTexto(unittest.TestCase):

    def test_texto_sin_etiquetas_va_a_narrador(self):
        fragmentos = fragmentar_texto("Había una vez un reino.")
        self.assertEqual(len(fragmentos), 1)
        self.assertEqual(fragmentos[0][0], "narrador")
        self.assertIn("Había una vez", fragmentos[0][1])

    def test_fragmenta_por_etiquetas(self):
        texto = "{{@nar}} La historia comienza. {{@rey}} ¡Bienvenidos!"
        frags = fragmentar_texto(texto)
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[0][0], "nar")
        self.assertEqual(frags[1][0], "rey")

    def test_texto_previo_usa_variante_narrador_existente(self):
        # Hay texto antes de la 1ª etiqueta; la variante del autor es 'nar'
        texto = "Prólogo.\n\n{{@nar}} Capítulo I."
        frags = fragmentar_texto(texto)
        # El texto previo debe asignarse a 'nar', no crear 'narrador' extra
        etiquetas = [f[0] for f in frags]
        self.assertNotIn("narrador", etiquetas)
        self.assertIn("nar", etiquetas)

    def test_fragmentos_vacios_omitidos(self):
        texto = "{{@nar}}    {{@rey}} Hola."
        frags = fragmentar_texto(texto)
        # El fragmento vacío de 'nar' no debe aparecer
        for etiq, contenido in frags:
            self.assertTrue(contenido.strip(), f"Fragmento vacío para '{etiq}'")

    def test_contenido_sin_espacios_extremos(self):
        texto = "{{@nar}}   Texto con espacios.   {{@rey}}  Otro.  "
        frags = fragmentar_texto(texto)
        for _, contenido in frags:
            self.assertEqual(contenido, contenido.strip())

    def test_multiples_personajes(self):
        texto = "{{@nar}} A. {{@rey}} B. {{@soldado}} C. {{@nar}} D."
        frags = fragmentar_texto(texto)
        etiquetas = [f[0] for f in frags]
        self.assertEqual(etiquetas, ["nar", "rey", "soldado", "nar"])

    def test_texto_completamente_vacio(self):
        self.assertEqual(fragmentar_texto(""), [])

    def test_solo_espacios(self):
        self.assertEqual(fragmentar_texto("   \n\n   "), [])

    def test_etiquetas_case_insensitive(self):
        texto = "{{@NAR}} Hola. {{@REY}} Adios."
        frags = fragmentar_texto(texto)
        self.assertEqual(frags[0][0], "nar")
        self.assertEqual(frags[1][0], "rey")


# ─────────────────────────────────────────────────────────────────────────────
# 2. LIMPIADOR DE LECTURA
# ─────────────────────────────────────────────────────────────────────────────
from app.motor.limpiador_lectura import limpiar_para_lectura


class TestLimpiarParaLectura(unittest.TestCase):

    def test_none_devuelve_none(self):
        self.assertIsNone(limpiar_para_lectura(None))

    def test_vacio_devuelve_vacio(self):
        self.assertEqual(limpiar_para_lectura(""), "")

    def test_une_palabra_cortada_con_guion(self):
        resultado = limpiar_para_lectura("cami-\nnando")
        self.assertEqual(resultado, "caminando")

    def test_elimina_espacios_multiples(self):
        resultado = limpiar_para_lectura("hola   mundo")
        self.assertEqual(resultado, "hola mundo")

    def test_reaune_puntuacion_separada(self):
        resultado = limpiar_para_lectura("frase .")
        self.assertIn("frase.", resultado)

    def test_reaune_coma_separada(self):
        resultado = limpiar_para_lectura("hola ,mundo")
        self.assertIn("hola,", resultado)

    def test_preserva_salto_de_parrafo(self):
        texto = "Párrafo uno.\n\nPárrafo dos."
        resultado = limpiar_para_lectura(texto)
        self.assertIn("\n", resultado)
        partes = resultado.split("\n")
        self.assertGreaterEqual(len(partes), 2)

    def test_une_lineas_dentro_del_mismo_parrafo(self):
        texto = "Esta es una línea\nque continúa en la siguiente."
        resultado = limpiar_para_lectura(texto)
        self.assertNotIn("\n", resultado)

    def test_no_blank_lines_dobles(self):
        texto = "A.\n\n\n\nB."
        resultado = limpiar_para_lectura(texto)
        self.assertNotIn("\n\n", resultado)

    def test_texto_normal_sin_cambios_sustanciales(self):
        texto = "Era una noche oscura y tormentosa."
        resultado = limpiar_para_lectura(texto)
        self.assertIn("noche oscura", resultado)

    def test_sin_espacios_al_inicio_o_fin(self):
        resultado = limpiar_para_lectura("  texto  ")
        self.assertEqual(resultado, resultado.strip())


# ─────────────────────────────────────────────────────────────────────────────
# 3. GESTOR DE PROYECTOS
# ─────────────────────────────────────────────────────────────────────────────
from app.motor.gestor_proyectos import GestorProyectos, TIPOS_PROYECTO


class TestGestorProyectos(unittest.TestCase):
    """Usa un directorio temporal aislado para no tocar configuraciones reales."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Parchear ruta_config para que apunte al directorio temporal
        patcher = patch(
            "app.motor.gestor_proyectos.RUTA_PROYECTOS",
            os.path.join(self.tmpdir, "proyectos.json"),
        )
        self.mock_ruta = patcher.start()
        self.addCleanup(patcher.stop)
        self.gestor = GestorProyectos()

    # ── CRUD básico ───────────────────────────────────────────────────────────

    def test_crear_proyecto_retorna_id(self):
        pid = self.gestor.crear_proyecto("Mi libro", "Libro")
        self.assertIsInstance(pid, str)
        self.assertTrue(len(pid) > 0)

    def test_obtener_proyecto_creado(self):
        pid = self.gestor.crear_proyecto("Novela", "Libro")
        proyecto = self.gestor.obtener_proyecto(pid)
        self.assertIsNotNone(proyecto)
        self.assertEqual(proyecto["nombre"], "Novela")

    def test_obtener_proyecto_inexistente_devuelve_none(self):
        self.assertIsNone(self.gestor.obtener_proyecto("id-que-no-existe"))

    def test_tipo_invalido_se_filtra(self):
        pid = self.gestor.crear_proyecto("X", "TipoInexistente")
        proyecto = self.gestor.obtener_proyecto(pid)
        self.assertEqual(proyecto["tipo"], [])

    def test_tipo_valido_se_guarda(self):
        pid = self.gestor.crear_proyecto("X", "Libro")
        proyecto = self.gestor.obtener_proyecto(pid)
        self.assertIn("Libro", proyecto["tipo"])

    def test_renombrar_proyecto(self):
        pid = self.gestor.crear_proyecto("Nombre viejo", "Libro")
        self.gestor.renombrar_proyecto(pid, "Nombre nuevo")
        self.assertEqual(self.gestor.obtener_proyecto(pid)["nombre"], "Nombre nuevo")

    def test_renombrar_proyecto_inexistente_no_falla(self):
        # No debe lanzar excepción
        self.gestor.renombrar_proyecto("id-fake", "Nuevo nombre")

    # ── Jerarquía padre-hijo ──────────────────────────────────────────────────

    def test_crear_proyecto_con_padre(self):
        saga_id = self.gestor.crear_proyecto("Saga", "Serie")
        libro_id = self.gestor.crear_proyecto("Libro 1", "Libro", padre_id=saga_id)
        saga = self.gestor.obtener_proyecto(saga_id)
        self.assertIn(libro_id, saga["hijos"])
        libro = self.gestor.obtener_proyecto(libro_id)
        self.assertEqual(libro["padre"], saga_id)

    def test_listar_hijos(self):
        saga_id = self.gestor.crear_proyecto("Saga", "Serie")
        lid1 = self.gestor.crear_proyecto("Libro 1", "Libro", padre_id=saga_id)
        lid2 = self.gestor.crear_proyecto("Libro 2", "Libro", padre_id=saga_id)
        hijos = self.gestor.listar_hijos(saga_id)
        ids_hijos = [h["id"] for h in hijos]
        self.assertIn(lid1, ids_hijos)
        self.assertIn(lid2, ids_hijos)

    def test_listar_hijos_de_inexistente_devuelve_lista_vacia(self):
        self.assertEqual(self.gestor.listar_hijos("no-existe"), [])

    def test_listar_proyectos_raiz_solo_raices(self):
        saga_id = self.gestor.crear_proyecto("Saga", "Serie")
        self.gestor.crear_proyecto("Libro hijo", "Libro", padre_id=saga_id)
        raices = self.gestor.listar_proyectos_raiz()
        ids_raiz = [p["id"] for p in raices]
        self.assertIn(saga_id, ids_raiz)
        # El hijo NO debe aparecer en raíces
        for p in raices:
            self.assertIsNone(p.get("padre"))

    def test_ruta_completa_jerarquia(self):
        saga_id  = self.gestor.crear_proyecto("Saga",  "Serie")
        libro_id = self.gestor.crear_proyecto("Libro", "Libro", padre_id=saga_id)
        cap_id   = self.gestor.crear_proyecto("Cap 1", "Libro", padre_id=libro_id)
        ruta = self.gestor.obtener_ruta_completa(cap_id)
        nombres = [p["nombre"] for p in ruta]
        self.assertEqual(nombres, ["Saga", "Libro", "Cap 1"])

    # ── Herencia de voces ─────────────────────────────────────────────────────

    def test_voces_heredadas_desde_padre(self):
        saga_id  = self.gestor.crear_proyecto("Saga", "Serie")
        libro_id = self.gestor.crear_proyecto("Libro", "Libro", padre_id=saga_id)
        cap_id   = self.gestor.crear_proyecto("Cap 1", "Libro", padre_id=libro_id)
        voz_a = {"nombre": "vozA", "proveedor_id": "local"}
        self.gestor.guardar_voces_proyecto(saga_id, {"nar": voz_a})
        voces = self.gestor.obtener_voces_heredadas(cap_id)
        self.assertIn("nar", voces)
        self.assertEqual(voces["nar"]["nombre"], "vozA")

    def test_voces_hijo_sobreescriben_padre(self):
        saga_id  = self.gestor.crear_proyecto("Saga", "Serie")
        libro_id = self.gestor.crear_proyecto("Libro", "Libro", padre_id=saga_id)
        voz_saga  = {"nombre": "vozPadre", "proveedor_id": "local"}
        voz_libro = {"nombre": "vozHijo",  "proveedor_id": "azure"}
        self.gestor.guardar_voces_proyecto(saga_id,  {"nar": voz_saga})
        self.gestor.guardar_voces_proyecto(libro_id, {"nar": voz_libro})
        voces = self.gestor.obtener_voces_heredadas(libro_id)
        self.assertEqual(voces["nar"]["nombre"], "vozHijo")

    def test_actualizar_voz_individual(self):
        pid = self.gestor.crear_proyecto("Libro", "Libro")
        self.gestor.actualizar_voz_proyecto(pid, "rey", {"nombre": "VozRey"})
        voces = self.gestor.obtener_voces_heredadas(pid)
        self.assertIn("rey", voces)

    # ── Asociación de archivos ────────────────────────────────────────────────

    def test_asociar_archivo(self):
        pid = self.gestor.crear_proyecto("Libro", "Libro")
        ruta = "/ruta/al/archivo.txt"
        self.gestor.asociar_archivo(pid, ruta)
        proyecto = self.gestor.obtener_proyecto(pid)
        self.assertTrue(any(ruta in a for a in proyecto["archivos"]))

    def test_asociar_mueve_de_proyecto_anterior(self):
        pid1 = self.gestor.crear_proyecto("Libro 1", "Libro")
        pid2 = self.gestor.crear_proyecto("Libro 2", "Libro")
        ruta = "/ruta/unico.txt"
        self.gestor.asociar_archivo(pid1, ruta)
        self.gestor.asociar_archivo(pid2, ruta)
        p1 = self.gestor.obtener_proyecto(pid1)
        # Ya no debe estar en el proyecto anterior
        self.assertFalse(any(ruta in a for a in p1["archivos"]))

    def test_proyecto_de_archivo(self):
        pid = self.gestor.crear_proyecto("Libro", "Libro")
        ruta = "/mi/archivo.txt"
        self.gestor.asociar_archivo(pid, ruta)
        encontrado = self.gestor.proyecto_de_archivo(ruta)
        self.assertIsNotNone(encontrado)
        self.assertEqual(encontrado["id"], pid)

    def test_proyecto_de_archivo_no_asociado(self):
        self.assertIsNone(self.gestor.proyecto_de_archivo("/no/existe.txt"))

    # ── Papelera (soft-delete) ────────────────────────────────────────────────

    def test_eliminar_proyecto_simple(self):
        pid = self.gestor.crear_proyecto("Para eliminar", "Libro")
        self.gestor.eliminar_proyecto(pid)
        self.assertIsNone(self.gestor.obtener_proyecto(pid))

    def test_eliminar_con_hijos_sin_recursivo_lanza_error(self):
        padre_id = self.gestor.crear_proyecto("Padre", "Serie")
        self.gestor.crear_proyecto("Hijo", "Libro", padre_id=padre_id)
        with self.assertRaises(ValueError):
            self.gestor.eliminar_proyecto(padre_id, recursivo=False)

    def test_eliminar_recursivo(self):
        padre_id = self.gestor.crear_proyecto("Padre", "Serie")
        hijo_id  = self.gestor.crear_proyecto("Hijo", "Libro", padre_id=padre_id)
        self.gestor.eliminar_proyecto(padre_id, recursivo=True)
        self.assertIsNone(self.gestor.obtener_proyecto(padre_id))
        self.assertIsNone(self.gestor.obtener_proyecto(hijo_id))

    def test_proyecto_eliminado_va_a_papelera(self):
        pid = self.gestor.crear_proyecto("Papelera test", "Libro")
        self.gestor.eliminar_proyecto(pid)
        papelera = self.gestor.listar_papelera()
        ids_papelera = [e["raiz_id"] for e in papelera]
        self.assertIn(pid, ids_papelera)

    def test_restaurar_proyecto_desde_papelera(self):
        pid = self.gestor.crear_proyecto("Restaurable", "Libro")
        self.gestor.eliminar_proyecto(pid)
        resultado = self.gestor.restaurar_proyecto(pid)
        self.assertTrue(resultado)
        self.assertIsNotNone(self.gestor.obtener_proyecto(pid))

    def test_restaurar_proyecto_inexistente_devuelve_false(self):
        self.assertFalse(self.gestor.restaurar_proyecto("id-no-existe"))

    def test_vaciar_papelera(self):
        pid = self.gestor.crear_proyecto("X", "Libro")
        self.gestor.eliminar_proyecto(pid)
        self.gestor.vaciar_papelera()
        self.assertEqual(self.gestor.listar_papelera(), [])

    # ── Persistencia ──────────────────────────────────────────────────────────

    def test_persistencia_en_disco(self):
        pid = self.gestor.crear_proyecto("Persistente", "Libro")
        # Crear nueva instancia: debe cargar desde disco
        gestor2 = GestorProyectos()
        self.assertIsNotNone(gestor2.obtener_proyecto(pid))

    def test_listar_proyectos_raiz_ordenados_alfabeticamente(self):
        self.gestor.crear_proyecto("Zebra",     "Libro")
        self.gestor.crear_proyecto("Alfa",      "Libro")
        self.gestor.crear_proyecto("Mediana",   "Libro")
        raices = self.gestor.listar_proyectos_raiz()
        nombres = [p["nombre"] for p in raices]
        self.assertEqual(nombres, sorted(nombres, key=str.lower))

    # ── Reordenación ──────────────────────────────────────────────────────────

    def test_mover_hijo_abajo(self):
        padre_id = self.gestor.crear_proyecto("Padre", "Serie")
        h1 = self.gestor.crear_proyecto("H1", "Libro", padre_id=padre_id)
        h2 = self.gestor.crear_proyecto("H2", "Libro", padre_id=padre_id)
        resultado = self.gestor.mover_proyecto(h1, +1)
        self.assertTrue(resultado)
        padre = self.gestor.obtener_proyecto(padre_id)
        self.assertEqual(padre["hijos"][0], h2)

    def test_mover_raiz_devuelve_false(self):
        pid = self.gestor.crear_proyecto("Raíz", "Libro")
        self.assertFalse(self.gestor.mover_proyecto(pid, -1))


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONTROL DE CUOTA
# ─────────────────────────────────────────────────────────────────────────────

class TestControlCuota(unittest.TestCase):
    """Mockea wx y reproductor_sonidos para aislar la lógica pura."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ruta_cuota = os.path.join(self.tmpdir, "uso_cuota.json")

        # 1. Limpiar módulo cacheado para empezar desde cero
        sys.modules.pop("app.motor.control_cuota", None)

        # 2. Mocks de dependencias ANTES de importar el módulo
        self.mock_wx   = MagicMock()
        self.mock_repr = MagicMock()
        patcher_mods = patch.dict("sys.modules", {
            "wx":                            self.mock_wx,
            "app.motor.reproductor_sonidos": self.mock_repr,
        })
        patcher_mods.start()
        self.addCleanup(patcher_mods.stop)

        # 3. Importar ahora (usa wx mockeado)
        from app.motor.control_cuota import ControlCuota
        self.ControlCuota = ControlCuota

        # 4. Parchear ruta_config YA en el módulo importado
        patcher_ruta = patch(
            "app.motor.control_cuota.ruta_config",
            return_value=self.ruta_cuota,
        )
        patcher_ruta.start()
        self.addCleanup(patcher_ruta.stop)

    def tearDown(self):
        # Limpiar módulo para que el siguiente test empiece fresco
        sys.modules.pop("app.motor.control_cuota", None)

    def _nueva_instancia(self):
        return self.ControlCuota()

    # ── Carga y persistencia ──────────────────────────────────────────────────

    def test_carga_defaults_si_no_hay_fichero(self):
        cc = self._nueva_instancia()
        self.assertIn("azure", cc.datos["gastado"])
        self.assertIn("polly", cc.datos["limites"])

    def test_guarda_y_recarga(self):
        cc = self._nueva_instancia()
        cc.datos["gastado"]["azure"] = 1234
        cc.guardar_datos()
        cc2 = self._nueva_instancia()
        self.assertEqual(cc2.datos["gastado"]["azure"], 1234)

    def test_carga_json_corrupto_usa_defaults(self):
        with open(self.ruta_cuota, "w") as f:
            f.write("ESTO NO ES JSON {{{")
        cc = self._nueva_instancia()
        self.assertEqual(cc.datos["gastado"]["azure"], 0)

    # ── tiene_cuota ───────────────────────────────────────────────────────────

    def test_tiene_cuota_cuando_hay_saldo(self):
        cc = self._nueva_instancia()
        cc.datos["gastado"]["azure"] = 0
        cc.datos["limites"]["azure"] = 500000
        self.assertTrue(cc.tiene_cuota("hola", "azure"))

    def test_no_tiene_cuota_cuando_excede(self):
        cc = self._nueva_instancia()
        cc.datos["gastado"]["azure"] = 499999
        cc.datos["limites"]["azure"] = 500000
        texto_largo = "x" * 2  # 2 chars → 499999+2 > 500000
        self.assertFalse(cc.tiene_cuota(texto_largo, "azure"))

    def test_tiene_cuota_en_el_limite_exacto(self):
        cc = self._nueva_instancia()
        cc.datos["gastado"]["azure"] = 499995
        cc.datos["limites"]["azure"] = 500000
        texto = "x" * 5  # exactamente 500000: 499995+5 <= 500000
        self.assertTrue(cc.tiene_cuota(texto, "azure"))

    def test_voz_local_siempre_tiene_cuota(self):
        cc = self._nueva_instancia()
        self.assertTrue(cc.tiene_cuota("texto muy largo " * 1000, "local"))

    def test_proveedor_polly_detectado(self):
        cc = self._nueva_instancia()
        cc.datos["limites"]["polly"] = 1000000
        cc.datos["gastado"]["polly"] = 0
        self.assertTrue(cc.tiene_cuota("hola", "polly"))

    def test_proveedor_eleven_detectado(self):
        cc = self._nueva_instancia()
        cc.datos["limites"]["elevenlabs"] = 10000
        cc.datos["gastado"]["elevenlabs"] = 0
        self.assertTrue(cc.tiene_cuota("hola", "elevenlabs"))

    # ── verificar_y_registrar ─────────────────────────────────────────────────

    def test_verifica_y_registra_cuando_hay_cuota(self):
        cc = self._nueva_instancia()
        cc.datos["limites"]["azure"] = 500000
        cc.datos["gastado"]["azure"] = 0
        resultado = cc.verificar_y_registrar("hola mundo", "azure")
        self.assertTrue(resultado)
        self.assertEqual(cc.datos["gastado"]["azure"], len("hola mundo"))

    def test_verifica_retorna_false_y_llama_callafter_si_excede(self):
        cc = self._nueva_instancia()
        cc.datos["limites"]["azure"] = 5
        cc.datos["gastado"]["azure"] = 4
        resultado = cc.verificar_y_registrar("exceeeede", "azure")  # > 5
        self.assertFalse(resultado)
        self.mock_wx.CallAfter.assert_called_once()

    def test_voz_local_siempre_retorna_true(self):
        cc = self._nueva_instancia()
        resultado = cc.verificar_y_registrar("texto", "local")
        self.assertTrue(resultado)
        self.mock_wx.CallAfter.assert_not_called()

    def test_gasto_no_se_registra_si_excede(self):
        cc = self._nueva_instancia()
        cc.datos["limites"]["polly"] = 10
        cc.datos["gastado"]["polly"] = 8
        gasto_antes = cc.datos["gastado"]["polly"]
        cc.verificar_y_registrar("texto largo que excede", "polly")
        # El gasto NO debe haberse incrementado
        self.assertEqual(cc.datos["gastado"]["polly"], gasto_antes)

    # ── registrar_gasto ───────────────────────────────────────────────────────

    def test_registrar_gasto_acumula(self):
        cc = self._nueva_instancia()
        cc.datos["gastado"]["azure"] = 100
        cc.registrar_gasto("hola", "azure")      # +4
        cc.registrar_gasto("mundo", "azure")     # +5
        self.assertEqual(cc.datos["gastado"]["azure"], 109)

    def test_registrar_gasto_local_ignorado(self):
        cc = self._nueva_instancia()
        cc.registrar_gasto("texto", "local")
        # No debe modificar nada ni lanzar excepción

    # ── get_info_uso / set_limite ─────────────────────────────────────────────

    def test_get_info_uso(self):
        cc = self._nueva_instancia()
        cc.datos["gastado"]["azure"] = 1500
        cc.datos["limites"]["azure"] = 500000
        gastado, limite = cc.get_info_uso("azure")
        self.assertEqual(gastado, 1500)
        self.assertEqual(limite, 500000)

    def test_set_limite_actualiza(self):
        cc = self._nueva_instancia()
        cc.set_limite("azure", 250000)
        self.assertEqual(cc.datos["limites"]["azure"], 250000)

    # ── Reinicio de contadores al cambiar mes ─────────────────────────────────

    def test_reinicia_contadores_en_mes_nuevo(self):
        cc = self._nueva_instancia()
        cc.datos["mes_actual"] = 1   # enero
        cc.datos["gastado"]["azure"] = 99999
        with patch("app.motor.control_cuota.datetime") as mock_dt:
            mock_dt.now.return_value.month = 2  # febrero
            cc.reiniciar_contadores_si_mes_nuevo()
        self.assertEqual(cc.datos["gastado"]["azure"], 0)
        self.assertEqual(cc.datos["mes_actual"], 2)

    def test_no_reinicia_en_mismo_mes(self):
        cc = self._nueva_instancia()
        mes = cc.datos["mes_actual"]
        cc.datos["gastado"]["azure"] = 5000
        with patch("app.motor.control_cuota.datetime") as mock_dt:
            mock_dt.now.return_value.month = mes  # mismo mes
            cc.reiniciar_contadores_si_mes_nuevo()
        self.assertEqual(cc.datos["gastado"]["azure"], 5000)


# ─────────────────────────────────────────────────────────────────────────────
# 5. CONFIG RUTAS
# ─────────────────────────────────────────────────────────────────────────────
from app.config_rutas import ruta_config, cargar_claves, guardar_claves


class TestConfigRutas(unittest.TestCase):

    def test_ruta_config_es_absoluta(self):
        ruta = ruta_config("ajustes.json")
        self.assertTrue(os.path.isabs(ruta))

    def test_ruta_config_termina_con_nombre(self):
        ruta = ruta_config("ajustes.json")
        self.assertTrue(ruta.endswith("ajustes.json"))

    def test_cargar_claves_sin_fichero_devuelve_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "claves_api.json")
            with patch("app.config_rutas.ruta_config", return_value=ruta):
                claves = cargar_claves()
        self.assertIn("azure",      claves)
        self.assertIn("polly",      claves)
        self.assertIn("elevenlabs", claves)

    def test_guardar_y_cargar_claves_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "claves_api.json")
            claves_orig = {
                "azure":      {"key": "KEY123", "region": "westeurope"},
                "polly":      {"access_key": "AK", "secret_key": "SK", "region": "eu-west-1"},
                "elevenlabs": {"api_key": "EL_KEY"},
            }
            with patch("app.config_rutas.ruta_config", return_value=ruta):
                guardar_claves(claves_orig)
                claves_leidas = cargar_claves()
        self.assertEqual(claves_leidas["azure"]["key"],      "KEY123")
        self.assertEqual(claves_leidas["polly"]["region"],   "eu-west-1")
        self.assertEqual(claves_leidas["elevenlabs"]["api_key"], "EL_KEY")

    def test_cargar_claves_json_corrupto_devuelve_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "claves_api.json")
            with open(ruta, "w") as f:
                f.write("{{CORRUPTO}}")
            with patch("app.config_rutas.ruta_config", return_value=ruta):
                claves = cargar_claves()
        self.assertIn("azure", claves)


# ─────────────────────────────────────────────────────────────────────────────
# GESTOR DE PERFILES DE USUARIO (v4.0)
# ─────────────────────────────────────────────────────────────────────────────
from app.motor import gestor_perfiles


class TestGestorPerfiles(unittest.TestCase):
    """Usa un archivo temporal aislado para no tocar configuraciones reales."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        patcher = patch(
            "app.motor.gestor_perfiles._RUTA_PERFILES",
            os.path.join(self.tmpdir, "perfiles.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cargar_perfiles_sin_archivo_devuelve_estructura_vacia(self):
        datos = gestor_perfiles.cargar_perfiles()
        self.assertEqual(datos["perfiles"], {})
        self.assertIsNone(datos["perfil_activo"])

    def test_crear_perfil_lo_deja_como_activo_por_defecto(self):
        self.assertTrue(gestor_perfiles.crear_perfil("Novela"))
        nombre, datos = gestor_perfiles.obtener_perfil_activo()
        self.assertEqual(nombre, "Novela")
        self.assertEqual(datos["velocidad"], 50)

    def test_crear_perfil_duplicado_falla(self):
        gestor_perfiles.crear_perfil("Novela")
        self.assertFalse(gestor_perfiles.crear_perfil("Novela"))

    def test_crear_perfil_nombre_vacio_falla(self):
        self.assertFalse(gestor_perfiles.crear_perfil("   "))

    def test_renombrar_perfil(self):
        gestor_perfiles.crear_perfil("Antiguo")
        self.assertTrue(gestor_perfiles.renombrar_perfil("Antiguo", "Nuevo"))
        self.assertTrue(gestor_perfiles.existe_perfil("Nuevo"))
        self.assertFalse(gestor_perfiles.existe_perfil("Antiguo"))

    def test_renombrar_a_nombre_ya_usado_falla(self):
        gestor_perfiles.crear_perfil("A")
        gestor_perfiles.crear_perfil("B")
        self.assertFalse(gestor_perfiles.renombrar_perfil("A", "B"))

    def test_renombrar_perfil_activo_actualiza_referencia(self):
        gestor_perfiles.crear_perfil("A")
        gestor_perfiles.renombrar_perfil("A", "B")
        nombre, _datos = gestor_perfiles.obtener_perfil_activo()
        self.assertEqual(nombre, "B")

    def test_eliminar_perfil(self):
        gestor_perfiles.crear_perfil("A")
        self.assertTrue(gestor_perfiles.eliminar_perfil("A"))
        self.assertFalse(gestor_perfiles.existe_perfil("A"))

    def test_eliminar_perfil_activo_pasa_activo_a_otro_restante(self):
        gestor_perfiles.crear_perfil("A")
        gestor_perfiles.crear_perfil("B")
        gestor_perfiles.fijar_perfil_activo("A")
        gestor_perfiles.eliminar_perfil("A")
        nombre, _datos = gestor_perfiles.obtener_perfil_activo()
        self.assertEqual(nombre, "B")

    def test_eliminar_ultimo_perfil_deja_activo_en_none(self):
        gestor_perfiles.crear_perfil("A")
        gestor_perfiles.eliminar_perfil("A")
        nombre, datos = gestor_perfiles.obtener_perfil_activo()
        self.assertIsNone(nombre)
        self.assertIsNone(datos)

    def test_siguiente_perfil_sin_perfiles_devuelve_vacio(self):
        self.assertEqual(gestor_perfiles.siguiente_perfil(), "")

    def test_siguiente_perfil_cicla_circularmente(self):
        gestor_perfiles.crear_perfil("A")
        gestor_perfiles.crear_perfil("B")
        gestor_perfiles.crear_perfil("C")
        gestor_perfiles.fijar_perfil_activo("A")
        self.assertEqual(gestor_perfiles.siguiente_perfil(), "B")
        gestor_perfiles.fijar_perfil_activo("C")
        self.assertEqual(gestor_perfiles.siguiente_perfil(), "A")

    def test_guardar_estado_en_perfil_sobrescribe_valores(self):
        gestor_perfiles.crear_perfil("A")
        ok = gestor_perfiles.guardar_estado_en_perfil(
            "A",
            voz_activa={"proveedor_id": "azure", "id_voz": "Elvira"},
            voces_favoritas={"azure": "Elvira"},
            velocidad=80, volumen=60,
            segundos_salto=15, pausa_entre_fragmentos_ms=300,
        )
        self.assertTrue(ok)
        _nombre, datos = gestor_perfiles.obtener_perfil_activo()
        self.assertEqual(datos["velocidad"], 80)
        self.assertEqual(datos["voz_activa"]["id_voz"], "Elvira")
        self.assertEqual(datos["pausa_entre_fragmentos_ms"], 300)

    def test_guardar_estado_en_perfil_inexistente_falla(self):
        self.assertFalse(gestor_perfiles.guardar_estado_en_perfil(
            "NoExiste", {}, {}, 50, 100, 10, 0,
        ))

    def test_persistencia_atomica_sobrevive_recarga(self):
        gestor_perfiles.crear_perfil("A")
        gestor_perfiles.fijar_perfil_activo("A")
        # Simula una nueva ejecución de la app releyendo el archivo desde cero
        datos_releidos = gestor_perfiles.cargar_perfiles()
        self.assertIn("A", datos_releidos["perfiles"])
        self.assertEqual(datos_releidos["perfil_activo"], "A")


# ─────────────────────────────────────────────────────────────────────────────
# COMPROBADOR DE ACTUALIZACIONES (comparación de versiones semánticas)
# ─────────────────────────────────────────────────────────────────────────────
from app.motor.comprobador_actualizaciones import ComprobadorActualizaciones


class TestComprobadorActualizaciones(unittest.TestCase):
    """
    hay_actualizacion() es la comparación que decide si se ofrece instalar
    algo: un fallo aquí ya causó un bug real en esta fase (leer_version_local
    apuntando a una ruta equivocada, sin lanzar ninguna excepción visible).
    """

    def setUp(self):
        self.comp = ComprobadorActualizaciones()

    def test_remota_mayor_hay_actualizacion(self):
        self.assertTrue(self.comp.hay_actualizacion("3.0.0", "4.0.0"))

    def test_remota_menor_no_hay_actualizacion(self):
        self.assertFalse(self.comp.hay_actualizacion("4.0.0", "3.0.0"))

    def test_versiones_iguales_no_hay_actualizacion(self):
        self.assertFalse(self.comp.hay_actualizacion("3.0.0", "3.0.0"))

    def test_local_con_menos_segmentos_que_remota(self):
        # "1.0" (sin parche) frente a "3.0.0": la comparación por tuplas debe
        # seguir decidiendo bien aunque los segmentos no cuadren en longitud.
        self.assertTrue(self.comp.hay_actualizacion("1.0", "3.0.0"))

    def test_local_vacia_no_lanza_excepcion(self):
        self.assertFalse(self.comp.hay_actualizacion("", "3.0.0"))

    def test_version_no_numerica_no_lanza_excepcion(self):
        self.assertFalse(self.comp.hay_actualizacion("no-es-una-version", "3.0.0"))

    def test_leer_version_local_sin_archivo_devuelve_0_0_0(self):
        with patch(
            "app.motor.comprobador_actualizaciones._RUTA_VERSION_LOCAL",
            "/ruta/que/no/existe/version.json",
        ):
            self.assertEqual(self.comp.leer_version_local(), "0.0.0")

    def test_leer_version_local_lee_el_archivo_real(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "version.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"version": "4.0.0"}, f)
            with patch("app.motor.comprobador_actualizaciones._RUTA_VERSION_LOCAL", ruta):
                self.assertEqual(self.comp.leer_version_local(), "4.0.0")


# ─────────────────────────────────────────────────────────────────────────────
# GESTOR DE ATAJOS DE TECLADO
# ─────────────────────────────────────────────────────────────────────────────
from app.motor import gestor_atajos


class TestGestorAtajos(unittest.TestCase):
    """Usa archivos temporales aislados para no tocar teclas_*.json reales."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        patcher_def = patch(
            "app.motor.gestor_atajos._RUTA_DEFAULTS",
            os.path.join(self.tmpdir, "teclas_predeterminadas.json"),
        )
        patcher_usr = patch(
            "app.motor.gestor_atajos._RUTA_USUARIO",
            os.path.join(self.tmpdir, "teclas_usuario.json"),
        )
        patcher_def.start()
        patcher_usr.start()
        self.addCleanup(patcher_def.stop)
        self.addCleanup(patcher_usr.stop)

    def test_cargar_atajos_crea_defaults_si_no_existen(self):
        atajos = gestor_atajos.cargar_atajos()
        self.assertIn("reproducir_pausar", atajos)
        self.assertEqual(atajos["reproducir_pausar"]["tecla"], "P")

    def test_guardar_atajo_usuario_sobrescribe_el_default(self):
        gestor_atajos.guardar_atajo_usuario("reproducir_pausar", "Ctrl+Shift", "Z")
        atajos = gestor_atajos.cargar_atajos()
        self.assertEqual(atajos["reproducir_pausar"]["modificador"], "Ctrl+Shift")
        self.assertEqual(atajos["reproducir_pausar"]["tecla"], "Z")

    def test_eliminar_atajo_usuario_restaura_el_default(self):
        gestor_atajos.guardar_atajo_usuario("detener", "Alt", "X")
        gestor_atajos.eliminar_atajo_usuario("detener")
        atajos = gestor_atajos.cargar_atajos()
        defaults = gestor_atajos.cargar_defaults()
        self.assertEqual(atajos["detener"], defaults["detener"])

    def test_restablecer_todos_borra_todos_los_overrides(self):
        gestor_atajos.guardar_atajo_usuario("detener", "Alt", "X")
        gestor_atajos.guardar_atajo_usuario("buscar", "Alt", "Y")
        gestor_atajos.restablecer_todos()
        atajos = gestor_atajos.cargar_atajos()
        defaults = gestor_atajos.cargar_defaults()
        self.assertEqual(atajos, defaults)

    def test_texto_atajo_con_modificador_y_tecla(self):
        self.assertEqual(
            gestor_atajos.texto_atajo({"modificador": "Ctrl+Shift", "tecla": "U"}),
            "Ctrl+Shift+U",
        )

    def test_texto_atajo_sin_asignar(self):
        self.assertEqual(gestor_atajos.texto_atajo({"modificador": "", "tecla": ""}), "(sin asignar)")


# ─────────────────────────────────────────────────────────────────────────────
# DICCIONARIO DE PRONUNCIACIÓN
# ─────────────────────────────────────────────────────────────────────────────
from app.motor.diccionario_pronunciacion import DiccionarioPronunciacion
from app.motor.gestor_biblioteca import GestorBiblioteca


class TestDiccionarioPronunciacion(unittest.TestCase):
    """Usa un archivo temporal aislado para no tocar pronunciacion.json real."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        patcher = patch(
            "app.motor.diccionario_pronunciacion._RUTA",
            os.path.join(self.tmpdir, "pronunciacion.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dic = DiccionarioPronunciacion()

    def test_diccionario_vacio_sin_archivo(self):
        self.assertEqual(self.dic.obtener_tabla(), {})

    def test_anadir_entrada_y_aplicar_sustitucion(self):
        self.dic.anadir_entrada("EPUB", "í-pub")
        self.assertEqual(self.dic.aplicar("Un archivo EPUB nuevo"), "Un archivo í-pub nuevo")

    def test_aplicar_respeta_limites_de_palabra(self):
        # "EPUB" no debe sustituirse dentro de "EPUBook" (coincidencia parcial).
        self.dic.anadir_entrada("EPUB", "í-pub")
        self.assertEqual(self.dic.aplicar("Un EPUBook nuevo"), "Un EPUBook nuevo")

    def test_eliminar_entrada(self):
        self.dic.anadir_entrada("NVDA", "en-ví-di-ei")
        self.dic.eliminar_entrada("NVDA")
        self.assertEqual(self.dic.aplicar("Uso NVDA a diario"), "Uso NVDA a diario")

    def test_guardar_y_recargar_persiste_en_disco(self):
        self.dic.anadir_entrada("Tolkien", "Tól-kien")
        otro = DiccionarioPronunciacion()
        self.assertEqual(otro.obtener_tabla(), {"Tolkien": "Tól-kien"})

    def test_texto_vacio_devuelve_igual(self):
        self.assertEqual(self.dic.aplicar(""), "")


class TestGestorBiblioteca(unittest.TestCase):
    """Usa una base de datos SQLite temporal aislada para no tocar la real."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        patcher = patch(
            "app.motor.gestor_biblioteca.RUTA_BIBLIOTECA",
            os.path.join(self.tmpdir, "biblioteca.db"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ruta_db = os.path.join(self.tmpdir, "biblioteca.db")
        self.gestor = GestorBiblioteca(self.ruta_db)

    # ── Inserción y consulta de libros ──────────────────────────────────────

    def test_insertar_libro_devuelve_id(self):
        id_libro = self.gestor.insertar_libro("/ruta/libro.epub", "Mi libro", "epub")
        self.assertIsInstance(id_libro, int)
        self.assertGreater(id_libro, 0)

    def test_obtener_libro_creado(self):
        id_libro = self.gestor.insertar_libro("/ruta/libro.epub", "Mi libro", "epub")
        libro = self.gestor.obtener_libro(id_libro)
        self.assertIsNotNone(libro)
        self.assertEqual(libro["titulo"], "Mi libro")
        self.assertEqual(libro["formato"], "epub")

    def test_obtener_libro_inexistente_devuelve_none(self):
        self.assertIsNone(self.gestor.obtener_libro(9999))

    def test_obtener_libro_por_ruta(self):
        self.gestor.insertar_libro("/ruta/libro.epub", "Mi libro", "epub")
        libro = self.gestor.obtener_libro_por_ruta("/ruta/libro.epub")
        self.assertIsNotNone(libro)
        self.assertEqual(libro["titulo"], "Mi libro")

    def test_obtener_libro_por_ruta_inexistente_devuelve_none(self):
        self.assertIsNone(self.gestor.obtener_libro_por_ruta("/no/existe.epub"))

    def test_insertar_libro_con_autores_y_categorias(self):
        id_libro = self.gestor.insertar_libro(
            "/ruta/libro.epub",
            "Mi libro",
            "epub",
            autores=["Tolkien"],
            categorias=[["Fantasía", "Fantasía épica"]],
        )
        autores = self.gestor.obtener_autores_de_libro(id_libro)
        self.assertEqual(len(autores), 1)
        self.assertEqual(autores[0]["nombre"], "Tolkien")
        categorias = self.gestor.obtener_categorias_de_libro(id_libro)
        self.assertEqual(len(categorias), 1)
        self.assertEqual(categorias[0]["nombre"], "Fantasía épica")

    def test_insertar_libros_lote(self):
        libros = [
            {"ruta_archivo": "/a.epub", "titulo": "A", "formato": "epub"},
            {"ruta_archivo": "/b.epub", "titulo": "B", "formato": "epub"},
        ]
        total = self.gestor.insertar_libros_lote(libros)
        self.assertEqual(total, 2)

    def test_insertar_libros_lote_omite_ruta_duplicada(self):
        self.gestor.insertar_libro("/a.epub", "A", "epub")
        libros = [
            {"ruta_archivo": "/a.epub", "titulo": "A duplicado", "formato": "epub"},
            {"ruta_archivo": "/b.epub", "titulo": "B", "formato": "epub"},
        ]
        total = self.gestor.insertar_libros_lote(libros)
        self.assertEqual(total, 1)

    # ── Actualización de metadatos y estado ─────────────────────────────────

    def test_establecer_bandera_favorito(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.establecer_bandera(id_libro, "favorito", True)
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["favorito"], 1)

    def test_establecer_bandera_en_pendientes(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.establecer_bandera(id_libro, "en_pendientes", True)
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["en_pendientes"], 1)

    def test_establecer_bandera_leyendo_ahora_desmarca_las_otras(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.establecer_bandera(id_libro, "en_pendientes", True)
        self.gestor.establecer_bandera(id_libro, "leyendo_ahora", True)
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["leyendo_ahora"], 1)
        self.assertEqual(libro["en_pendientes"], 0)

    def test_establecer_bandera_leido_desmarca_leyendo_ahora(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.establecer_bandera(id_libro, "leyendo_ahora", True)
        self.gestor.establecer_bandera(id_libro, "leido", True)
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["leido"], 1)
        self.assertEqual(libro["leyendo_ahora"], 0)

    def test_establecer_bandera_favorito_no_afecta_estado_lectura(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.establecer_bandera(id_libro, "leyendo_ahora", True)
        self.gestor.establecer_bandera(id_libro, "favorito", True)
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["favorito"], 1)
        self.assertEqual(libro["leyendo_ahora"], 1)

    def test_establecer_bandera_campo_invalido_lanza_valueerror(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        with self.assertRaises(ValueError):
            self.gestor.establecer_bandera(id_libro, "campo_inventado", True)

    def test_actualizar_punto_lectura(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.actualizar_punto_lectura(id_libro, 42)
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["ultimo_punto_lectura"], 42)

    def test_confirmar_titulo_revisado(self):
        id_libro = self.gestor.insertar_libro(
            "/a.epub", "Sin revisar", "epub", titulo_revisado=False
        )
        self.gestor.confirmar_titulo_revisado(id_libro, "/a_final.epub", "Título final")
        libro = self.gestor.obtener_libro(id_libro)
        self.assertEqual(libro["titulo"], "Título final")
        self.assertEqual(libro["ruta_archivo"], "/a_final.epub")
        self.assertEqual(libro["titulo_revisado"], 1)

    def test_obtener_pendientes_de_revision(self):
        self.gestor.insertar_libro("/a.epub", "A", "epub", titulo_revisado=False)
        self.gestor.insertar_libro("/b.epub", "B", "epub", titulo_revisado=True)
        pendientes = self.gestor.obtener_pendientes_de_revision()
        self.assertEqual(len(pendientes), 1)
        self.assertEqual(pendientes[0]["titulo"], "A")

    def test_quitar_libro(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.quitar_libro(id_libro)
        self.assertIsNone(self.gestor.obtener_libro(id_libro))

    # ── Categorías con jerarquía padre-hijo ─────────────────────────────────

    def test_crear_categoria_raiz(self):
        id_categoria = self.gestor.crear_categoria("Fantasía")
        self.assertIsInstance(id_categoria, int)

    def test_crear_categoria_hija(self):
        id_padre = self.gestor.crear_categoria("Fantasía")
        id_hija = self.gestor.crear_categoria("Fantasía épica", id_padre)
        ruta = self.gestor.obtener_ruta_categoria(id_hija)
        self.assertEqual(ruta, ["Fantasía", "Fantasía épica"])

    def test_listar_categorias_hijas_raiz(self):
        self.gestor.crear_categoria("Fantasía")
        self.gestor.crear_categoria("Distopía")
        raices = self.gestor.listar_categorias_hijas(None)
        nombres = [c["nombre"] for c in raices]
        self.assertEqual(set(nombres), {"Fantasía", "Distopía"})

    def test_listar_categorias_hijas_de_un_padre(self):
        id_padre = self.gestor.crear_categoria("Fantasía")
        self.gestor.crear_categoria("Fantasía épica", id_padre)
        hijas = self.gestor.listar_categorias_hijas(id_padre)
        self.assertEqual(len(hijas), 1)
        self.assertEqual(hijas[0]["nombre"], "Fantasía épica")

    def test_renombrar_categoria(self):
        id_categoria = self.gestor.crear_categoria("Fantasía")
        self.assertTrue(self.gestor.renombrar_categoria(id_categoria, "Fantástico"))
        ruta = self.gestor.obtener_ruta_categoria(id_categoria)
        self.assertEqual(ruta, ["Fantástico"])

    def test_eliminar_categoria_elimina_subarbol(self):
        id_padre = self.gestor.crear_categoria("Fantasía")
        id_hija = self.gestor.crear_categoria("Fantasía épica", id_padre)
        self.gestor.eliminar_categoria(id_padre)
        hijas = self.gestor.listar_categorias_hijas(id_padre)
        self.assertEqual(hijas, [])

    def test_asignar_categoria_por_ruta(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.asignar_categoria_por_ruta(id_libro, ["Fantasía", "Fantasía épica"])
        categorias = self.gestor.obtener_categorias_de_libro(id_libro)
        self.assertEqual(len(categorias), 1)
        self.assertEqual(categorias[0]["nombre"], "Fantasía épica")

    def test_quitar_categoria_de_libro(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        id_categoria = self.gestor.asignar_categoria_por_ruta(id_libro, ["Fantasía"])
        self.gestor.quitar_categoria_de_libro(id_libro, id_categoria)
        self.assertEqual(self.gestor.obtener_categorias_de_libro(id_libro), [])

    # ── Etiquetas / sagas ────────────────────────────────────────────────────

    def test_crear_etiqueta(self):
        id_etiqueta = self.gestor.crear_etiqueta("Trilogía del Anillo")
        self.assertIsInstance(id_etiqueta, int)

    def test_asignar_etiqueta_a_libro(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.asignar_etiqueta(id_libro, "Saga X")
        etiquetas = self.gestor.obtener_etiquetas_de_libro(id_libro)
        self.assertEqual(len(etiquetas), 1)
        self.assertEqual(etiquetas[0]["nombre"], "Saga X")

    def test_quitar_etiqueta_de_libro(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.asignar_etiqueta(id_libro, "Saga X")
        id_etiqueta = self.gestor.listar_etiquetas()[0]["id"]
        self.gestor.quitar_etiqueta_de_libro(id_libro, id_etiqueta)
        self.assertEqual(self.gestor.obtener_etiquetas_de_libro(id_libro), [])

    def test_renombrar_etiqueta(self):
        id_etiqueta = self.gestor.crear_etiqueta("Saga X")
        self.assertTrue(self.gestor.renombrar_etiqueta(id_etiqueta, "Saga Y"))
        nombres = [e["nombre"] for e in self.gestor.listar_etiquetas()]
        self.assertIn("Saga Y", nombres)

    def test_renombrar_etiqueta_a_nombre_ya_usado_falla(self):
        self.gestor.crear_etiqueta("Saga X")
        id_etiqueta_y = self.gestor.crear_etiqueta("Saga Y")
        self.assertFalse(self.gestor.renombrar_etiqueta(id_etiqueta_y, "Saga X"))

    def test_eliminar_etiqueta(self):
        id_etiqueta = self.gestor.crear_etiqueta("Saga X")
        self.gestor.eliminar_etiqueta(id_etiqueta)
        self.assertEqual(self.gestor.listar_etiquetas(), [])

    # ── Exportaciones pendientes ─────────────────────────────────────────────

    def test_registrar_exportacion_pendiente(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        id_exportacion = self.gestor.registrar_exportacion_pendiente(
            id_libro, "completo", "azure", punto_corte=1000
        )
        self.assertIsInstance(id_exportacion, int)

    def test_obtener_exportaciones_pendientes(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.registrar_exportacion_pendiente(id_libro, "completo", "azure")
        pendientes = self.gestor.obtener_exportaciones_pendientes(id_libro)
        self.assertEqual(len(pendientes), 1)
        self.assertEqual(pendientes[0]["proveedor"], "azure")

    def test_obtener_exportaciones_pendientes_libro_sin_pendientes(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.assertEqual(self.gestor.obtener_exportaciones_pendientes(id_libro), [])

    def test_obtener_ids_libros_con_exportacion_pendiente(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.registrar_exportacion_pendiente(id_libro, "completo", "azure")
        ids = self.gestor.obtener_ids_libros_con_exportacion_pendiente()
        self.assertEqual(ids, {id_libro})

    def test_eliminar_exportacion_pendiente(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        id_exportacion = self.gestor.registrar_exportacion_pendiente(id_libro, "completo", "azure")
        self.gestor.eliminar_exportacion_pendiente(id_exportacion)
        self.assertEqual(self.gestor.obtener_exportaciones_pendientes(id_libro), [])

    def test_eliminar_exportaciones_pendientes_de_libro(self):
        id_libro = self.gestor.insertar_libro("/a.epub", "A", "epub")
        self.gestor.registrar_exportacion_pendiente(id_libro, "completo", "azure")
        self.gestor.registrar_exportacion_pendiente(id_libro, "capitulos", "polly")
        self.gestor.eliminar_exportaciones_pendientes_de_libro(id_libro)
        self.assertEqual(self.gestor.obtener_exportaciones_pendientes(id_libro), [])

    # ── Migración de esquema ─────────────────────────────────────────────────

    def test_crear_gestor_dos_veces_no_falla(self):
        """Regresión: ALTER TABLE ADD COLUMN no debe fallar si ya existe la columna."""
        try:
            GestorBiblioteca(self.ruta_db)
            GestorBiblioteca(self.ruta_db)
        except Exception as error:
            self.fail(f"Crear el gestor dos veces lanzó una excepción: {error}")

    def test_buscar_libros_devuelve_lista_vacia_sin_coincidencias(self):
        self.assertEqual(self.gestor.buscar_libros(texto="No existe"), [])


class TestPersistenciaJsonAtomica(unittest.TestCase):
    """Verifica el patrón de escritura atómica (.tmp + os.replace) de gestor_perfiles."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ruta_perfiles = os.path.join(self.tmpdir, "perfiles.json")
        patcher = patch("app.motor.gestor_perfiles._RUTA_PERFILES", self.ruta_perfiles)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_guardar_perfil_deja_json_valido_en_destino(self):
        gestor_perfiles.crear_perfil("Novela")
        with open(self.ruta_perfiles, "r", encoding="utf-8") as f:
            contenido = json.load(f)
        self.assertIn("Novela", contenido["perfiles"])

    def test_guardar_perfil_no_deja_archivo_tmp_residual(self):
        gestor_perfiles.crear_perfil("Novela")
        self.assertFalse(os.path.exists(self.ruta_perfiles + ".tmp"))

    def test_escritura_interrumpida_no_corrompe_archivo_original(self):
        gestor_perfiles.crear_perfil("Novela")
        with open(self.ruta_perfiles, "r", encoding="utf-8") as f:
            contenido_original = f.read()

        with patch("os.replace", side_effect=OSError("fallo simulado a mitad de escritura")):
            self.assertFalse(gestor_perfiles.crear_perfil("Otro perfil"))

        with open(self.ruta_perfiles, "r", encoding="utf-8") as f:
            contenido_tras_fallo = f.read()
        self.assertEqual(contenido_original, contenido_tras_fallo)
        self.assertTrue(os.path.exists(self.ruta_perfiles + ".tmp"))


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    unittest.main(verbosity=2)
