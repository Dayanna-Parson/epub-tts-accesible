"""
Suite de tests para Epub-TTS Accessible
========================================
Cubre las partes testables sin GUI ni hardware de audio:
  - procesador_etiquetas  (puro Python)
  - limpiador_lectura     (puro Python)
  - gestor_proyectos      (stdlib + fichero temporal)
  - control_cuota         (lógica con wx + reproductor_sonidos mockeados)
  - config_rutas          (utils de rutas)
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
if __name__ == "__main__":
    unittest.main(verbosity=2)
