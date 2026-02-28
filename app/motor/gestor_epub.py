import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import warnings
import re
import os
from app.motor.procesador_etiquetas import limpiar_texto

# Filtramos advertencias de bs4 para mantener la salida limpia en la consola
warnings.filterwarnings("ignore", category=UserWarning, module='bs4')

def extraer_datos_epub(ruta_epub):
    """
    Extrae el texto completo y la estructura del índice (TOC) de un archivo EPUB.
    Retorna:
        - texto_completo (str): El texto del libro limpio.
        - datos_indice (list): Estructura jerárquica para el árbol de navegación.
        - posiciones_capitulos (dict): Diccionario {titulo_capitulo: posicion_caracter}.
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
    
    # --- 1. PROCESAR LA COLUMNA VERTEBRAL (Orden de lectura lineal) ---
    for id_item in libro.spine:
        item = libro.get_item_with_id(id_item[0])
        
        if not item:
            continue
            
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            posiciones_inicio_archivo[item.file_name] = len(texto_completo)
            
            # Corrección de indentación aquí:
            sopa = BeautifulSoup(item.get_content(), 'html.parser')
            
            for script in sopa(["script", "style", "head", "title", "meta"]): 
                script.extract()
            
            texto_crudo = sopa.get_text(separator='\n')
            
            lines = []
            for line in texto_crudo.splitlines():
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
            
            fragmento_limpio = "\n\n".join(lines)
            
            texto_completo += fragmento_limpio + "\n\n"

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
        
        if not titulo: return None

        nombre_archivo = enlace.split('#')[0]
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

    # Limpieza final: eliminar artefactos de formato del EPUB
    texto_completo = limpiar_texto(texto_completo)

    return texto_completo, datos_indice, posiciones_capitulos