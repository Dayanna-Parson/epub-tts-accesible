import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString, Tag
import warnings
import re
import os
from app.motor.limpiador_lectura import limpiar_para_lectura

# Filtramos advertencias de bs4 para mantener la salida limpia en la consola
warnings.filterwarnings("ignore", category=UserWarning, module='bs4')

# Elementos de bloque que generan párrafo propio
_BLOQUES = {
    'p', 'div', 'section', 'article', 'aside',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'li', 'dt', 'dd', 'blockquote',
    'td', 'th', 'caption',
    'pre', 'figure', 'figcaption',
}
# Elementos de formateo que normalmente no tienen salto pero sí espacio
_INLINE_FORMATEO = {'br'}

# Etiquetas HTML semánticas de estilo inline
_INLINE_NEGRITA   = {'strong', 'b'}
_INLINE_CURSIVA   = {'em', 'i', 'cite', 'dfn', 'var'}
_INLINE_SUBRAYADO = {'u', 'ins'}


def _extraer_texto_bloque(elemento) -> str:
    """
    Extrae el texto de un elemento BeautifulSoup respetando la estructura semántica.

    - Los elementos de bloque anidados producen párrafos separados por \\n\\n.
    - Los <br> producen un único salto de línea.
    - Los nodos de texto inline se unen con espacio para evitar palabras cortadas
      cuando el HTML tiene saltos de línea arbitrarios entre etiquetas inline.
    """
    partes = []

    for nodo in elemento.children:
        if isinstance(nodo, NavigableString):
            txt = str(nodo)
            if txt.strip():
                partes.append(txt)
            elif txt and partes and not partes[-1].endswith(' ') and not partes[-1].endswith('\n'):
                # Espacio entre nodos inline (ej. "<b>hola</b> mundo").
                # No se añade si el último elemento termina en \n: sería
                # whitespace HTML de indentación entre elementos de bloque.
                partes.append(' ')
        elif isinstance(nodo, Tag):
            nombre = nodo.name.lower() if nodo.name else ''
            if nombre in ('script', 'style', 'head', 'meta', 'link',
                          'noscript', 'template'):
                continue
            if nombre == 'br':
                if partes and not partes[-1].endswith('\n'):
                    partes.append('\n')
            elif nombre == 'img':
                # Las imágenes no dejan ningún rastro en el texto por sí
                # solas: sin este marcador, no habría nada a lo que saltar
                # con la tecla G ni nada que la voz pudiera anunciar.
                alt = (nodo.get('alt') or '').strip()
                marcador = f"[Imagen: {alt}]" if alt else "[Imagen]"
                if (partes and not partes[-1].endswith(' ')
                        and not partes[-1].endswith('\n')):
                    partes.append(' ')
                partes.append(marcador)
            elif nombre in _BLOQUES:
                subtexto = _extraer_texto_bloque(nodo).strip()
                if subtexto:
                    if partes and not partes[-1].endswith('\n\n'):
                        partes.append('\n\n')
                    partes.append(subtexto)
                    partes.append('\n\n')
            else:
                # Elemento inline (span, em, strong, a, …): unir con espacio
                subtexto = _extraer_texto_bloque(nodo)
                if subtexto:
                    if (partes and not partes[-1].endswith(' ')
                            and not subtexto.startswith(' ')):
                        partes.append(' ')
                    partes.append(subtexto)

    return ''.join(partes)

def _recopilar_spans_estilo(cuerpo, offset_archivo):
    """
    Recorre el árbol BeautifulSoup de un documento y devuelve la lista de spans
    con estilo semántico (negrita, cursiva, subrayado):
        [{'texto': str, 'estilos': frozenset, 'cerca_de': int}, ...]

    'cerca_de' es el offset global del archivo en el texto completo, usado como
    punto de partida para la búsqueda posicional en pestana_lectura.

    Solo registra el elemento donde se INTRODUCE un estilo nuevo respecto al padre
    (evita duplicar spans cuando un padre ya aplica el mismo estilo).
    Los estilos se acumulan en la recursión para manejar anidaciones:
        <strong>muy <em>importante</em></strong>
        → "muy importante" negrita
        → "importante"     negrita + cursiva
    """
    resultado = []

    def _recorrer(nodo, estilos_padres):
        if not isinstance(nodo, Tag):
            return
        nombre = nodo.name.lower() if nodo.name else ''
        if nombre in ('script', 'style', 'head', 'meta', 'link', 'noscript', 'template'):
            return

        estilos = set(estilos_padres)
        if nombre in _INLINE_NEGRITA:
            estilos.add('negrita')
        if nombre in _INLINE_CURSIVA:
            estilos.add('cursiva')
        if nombre in _INLINE_SUBRAYADO:
            estilos.add('subrayado')
        estilos_fs = frozenset(estilos)

        # Solo registrar si este elemento aporta estilos nuevos
        if estilos_fs - estilos_padres:
            texto_nodo = nodo.get_text(separator=' ', strip=True)
            if len(texto_nodo) >= 3:
                resultado.append({
                    'texto': texto_nodo,
                    'estilos': estilos_fs,
                    'cerca_de': offset_archivo,
                })

        for hijo in nodo.children:
            _recorrer(hijo, estilos_fs)

    for nodo in cuerpo.children:
        _recorrer(nodo, frozenset())

    return resultado


def extraer_datos_epub(ruta_epub):
    """
    Extrae el texto completo y la estructura del índice (TOC) de un archivo EPUB.
    Retorna:
        - texto_completo (str): El texto del libro limpio.
        - datos_indice (list): Estructura jerárquica para el árbol de navegación.
        - posiciones_capitulos (dict): Diccionario {titulo_capitulo: posicion_caracter}.
        - posiciones_encabezados (list): [{nivel, texto, pos}] para aplicar negrita a h1-h6 en Lectura.
        - spans_estilo (list): [{texto, estilos, cerca_de}] para rich-text en Lectura.
        - posiciones_imagenes (list): [{texto, pos}] — texto es el alt (o "" si no tiene).
        - posiciones_enlaces (list): [{texto, pos}] — texto es el texto visible del enlace.
        - posiciones_tablas (list): [{texto, pos}] — texto es el contenido de la primera celda.
    """
    if not os.path.exists(ruta_epub):
        raise FileNotFoundError(f"No se encontró el archivo: {ruta_epub}")

    try:
        libro = epub.read_epub(ruta_epub)
    except Exception as e:
        raise Exception(f"Error al leer el formato EPUB: {e}")

    texto_completo = ""
    posiciones_capitulos = {}
    # Mapeo para saber en qué carácter del texto global empieza cada archivo interno
    posiciones_inicio_archivo = {}
    # Mapa {nombre_archivo#anchor_id: pos_global} para TOC con fragmentos (#section1)
    posiciones_anchors = {}
    # Lista de encabezados [{nivel, texto, pos}] para navegación semántica
    posiciones_encabezados = []
    # Lista de spans con estilo [{texto, estilos, cerca_de}] para rich-text en TextCtrl
    spans_estilo = []
    # Listas para navegación semántica de imágenes, enlaces y tablas [{texto, pos}]
    posiciones_imagenes = []
    posiciones_enlaces = []
    posiciones_tablas = []

    # --- 1. PROCESAR LA COLUMNA VERTEBRAL (Orden de lectura lineal) ---
    for id_item in libro.spine:
        item = libro.get_item_with_id(id_item[0])

        if not item:
            continue

        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            offset_archivo = len(texto_completo)
            posiciones_inicio_archivo[item.file_name] = offset_archivo

            sopa = BeautifulSoup(item.get_content(), 'html.parser')

            # Extraer texto desde el body (o todo el documento si no hay body)
            cuerpo = sopa.find('body') or sopa
            fragmento = _extraer_texto_bloque(cuerpo)

            # Normalizar múltiples saltos consecutivos en un máximo de dos
            fragmento = re.sub(r'\n{3,}', '\n\n', fragmento).strip()

            if fragmento:
                # Registrar posiciones de anchors (id=) para soporte de TOC con #fragmento
                for elem in cuerpo.find_all(id=True):
                    anchor_id = elem.get('id', '').strip()
                    if not anchor_id:
                        continue
                    # Buscar el texto del elemento para localizarlo en el fragmento
                    elem_texto = elem.get_text(separator=' ', strip=True)
                    if elem_texto:
                        aguja = elem_texto[:30]
                        pos_en_frag = fragmento.find(aguja)
                        pos_global = offset_archivo + (pos_en_frag if pos_en_frag >= 0 else 0)
                    else:
                        pos_global = offset_archivo
                    posiciones_anchors[f"{item.file_name}#{anchor_id}"] = pos_global

                # Registrar posiciones de encabezados h1–h6
                for hx in cuerpo.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    nivel = int(hx.name[1])
                    texto_h = hx.get_text(separator=' ', strip=True)
                    if texto_h:
                        pos_en_frag = fragmento.find(texto_h[:50])
                        if pos_en_frag >= 0:
                            posiciones_encabezados.append({
                                'nivel': nivel,
                                'texto': texto_h,
                                'pos': offset_archivo + pos_en_frag,
                            })

                # Registrar posiciones de imágenes, por el marcador [Imagen: ...]
                # ya insertado en el fragmento por _extraer_texto_bloque
                for img in cuerpo.find_all('img'):
                    alt = (img.get('alt') or '').strip()
                    aguja = f"[Imagen: {alt}]" if alt else "[Imagen]"
                    pos_en_frag = fragmento.find(aguja)
                    if pos_en_frag >= 0:
                        posiciones_imagenes.append({
                            'texto': alt,
                            'pos': offset_archivo + pos_en_frag,
                        })

                # Registrar posiciones de enlaces con texto visible
                for a in cuerpo.find_all('a', href=True):
                    texto_a = a.get_text(separator=' ', strip=True)
                    if texto_a:
                        pos_en_frag = fragmento.find(texto_a[:50])
                        if pos_en_frag >= 0:
                            posiciones_enlaces.append({
                                'texto': texto_a,
                                'pos': offset_archivo + pos_en_frag,
                            })

                # Registrar posiciones de tablas, por el texto de su primera celda
                for tabla in cuerpo.find_all('table'):
                    celda = tabla.find(['td', 'th'])
                    texto_tabla = celda.get_text(separator=' ', strip=True) if celda else ""
                    if texto_tabla:
                        pos_en_frag = fragmento.find(texto_tabla[:50])
                        if pos_en_frag >= 0:
                            posiciones_tablas.append({
                                'texto': texto_tabla,
                                'pos': offset_archivo + pos_en_frag,
                            })

                # Recopilar spans con estilo inline (negrita, cursiva, subrayado)
                spans_estilo.extend(_recopilar_spans_estilo(cuerpo, offset_archivo))

                texto_completo += fragmento + "\n\n"

    # --- 2. PROCESAR EL ÍNDICE (TOC Jerárquico) ---
    datos_indice = []

    def procesar_nodo_indice(nodo):
        titulo = ""
        enlace = ""
        hijos = []

        if isinstance(nodo, epub.Link):
            titulo = nodo.title
            enlace = nodo.href
        elif isinstance(nodo, (tuple, list)):
            cabecera = nodo[0]
            if isinstance(cabecera, (epub.Section, epub.Link)):
                titulo = cabecera.title
                enlace = cabecera.href
            if len(nodo) > 1 and isinstance(nodo[1], list):
                for hijo in nodo[1]:
                    datos_hijo = procesar_nodo_indice(hijo)
                    if datos_hijo:
                        hijos.append(datos_hijo)

        if not titulo:
            return None

        # Soporte de TOC con anclas: "cap1.html#seccion2"
        nombre_archivo = enlace.split('#')[0]
        fragmento_id = enlace.split('#')[1] if '#' in enlace else ''
        if fragmento_id:
            clave_anchor = f"{nombre_archivo}#{fragmento_id}"
            pos_inicio = posiciones_anchors.get(
                clave_anchor,
                posiciones_inicio_archivo.get(nombre_archivo, 0)
            )
        else:
            pos_inicio = posiciones_inicio_archivo.get(nombre_archivo, 0)

        posiciones_capitulos[titulo] = pos_inicio

        return {
            'title': titulo,
            'offset': pos_inicio,
            'children': hijos
        }

    for item in libro.toc:
        datos_nodo = procesar_nodo_indice(item)
        if datos_nodo:
            datos_indice.append(datos_nodo)

    # Limpieza final: eliminar artefactos de formato y líneas vacías para NVDA
    texto_completo = limpiar_para_lectura(texto_completo, ruta_libro=ruta_epub)

    # Recalcular posiciones de encabezados/imágenes/enlaces/tablas en el texto
    # ya limpiado. limpiar_para_lectura colapsa \n\n → \n, desplazando todas
    # las posiciones calculadas sobre el texto en bruto; hay que buscarlas de
    # nuevo, cada lista con su propio puntero de búsqueda secuencial.
    def _reubicar(lista, aguja_de):
        pos_busqueda = 0
        reubicados = []
        for elem in lista:
            aguja = aguja_de(elem)
            pos = texto_completo.find(aguja, pos_busqueda)
            if pos >= 0:
                reubicados.append({**elem, 'pos': pos})
                pos_busqueda = pos + 1
        return reubicados

    posiciones_encabezados = _reubicar(posiciones_encabezados, lambda e: e['texto'][:50])
    posiciones_imagenes = _reubicar(
        posiciones_imagenes,
        lambda e: f"[Imagen: {e['texto']}]" if e['texto'] else "[Imagen]",
    )
    posiciones_enlaces = _reubicar(posiciones_enlaces, lambda e: e['texto'][:50])
    posiciones_tablas = _reubicar(posiciones_tablas, lambda e: e['texto'][:50])

    return (
        texto_completo, datos_indice, posiciones_capitulos, posiciones_encabezados,
        spans_estilo, posiciones_imagenes, posiciones_enlaces, posiciones_tablas,
    )