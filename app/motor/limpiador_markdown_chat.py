# ANCLAJE_INICIO: LIMPIADOR_MARKDOWN_CHAT
"""
Limpieza de Markdown en las respuestas del Asistente de Biblioteca (Gemini).

Gemini devuelve texto con formato Markdown (negritas, encabezados, listas,
enlaces...). Mostrado tal cual en el historial del chat, NVDA lee los
símbolos de marcado en voz alta (asterisco, almohadilla, guion...), lo que
resulta ruidoso e innecesario en una conversación. Esta función convierte
el Markdown más habitual a texto plano bien estructurado, pensado para
lectura con lector de pantalla, no para renderizarse visualmente.
"""
import re


def limpiar_markdown(texto: str) -> str:
    if not texto:
        return texto

    # Bloques de código ```...```: se quitan las marcas, se conserva el contenido.
    texto = re.sub(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", r"\1", texto, flags=re.DOTALL)
    # Código en línea `texto`.
    texto = re.sub(r"`([^`]+)`", r"\1", texto)

    # Encabezados "## Título" → "Título" (con salto de línea extra para pausa).
    texto = re.sub(r"^#{1,6}\s*(.+)$", r"\1\n", texto, flags=re.MULTILINE)

    # Negrita/cursiva: **texto**, __texto__, *texto*, _texto_ → texto.
    # Primero los dobles (negrita), luego los simples (cursiva), para no
    # dejar un asterisco suelto al procesar **texto** como par de *texto*.
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"__(.+?)__", r"\1", texto)
    texto = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", texto)
    texto = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", texto)

    # Tachado ~~texto~~ → texto.
    texto = re.sub(r"~~(.+?)~~", r"\1", texto)

    # Enlaces [texto](url) → "texto (url)"; imágenes ![alt](url) → alt.
    texto = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", texto)
    texto = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", texto)

    # Viñetas "- ", "* ", "+ " al inicio de línea → "• " (NVDA lo lee como
    # "viñeta", no como el símbolo suelto). Las listas numeradas ("1. ") se
    # dejan tal cual: ya se leen con naturalidad.
    texto = re.sub(r"^[ \t]*[-*+]\s+", "• ", texto, flags=re.MULTILINE)

    # Citas "> texto" → texto.
    texto = re.sub(r"^>\s?", "", texto, flags=re.MULTILINE)

    # Líneas horizontales (---, ***, ___ solas en su línea) → se eliminan.
    texto = re.sub(r"^\s*([-*_])\1{2,}\s*$", "", texto, flags=re.MULTILINE)

    # Colapsar espacios en blanco sobrantes que dejan las sustituciones.
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()
# ANCLAJE_FIN: LIMPIADOR_MARKDOWN_CHAT
