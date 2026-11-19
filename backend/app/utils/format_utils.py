import re


def limpiar_razonamiento_interno(texto: str) -> str:
    """
    Elimina los bloques de razonamiento interno <razonamiento>...</razonamiento>
    generados por el modelo (Chain-of-Thought oculto).
    Incluye un respaldo defensivo en caso de truncamiento antes del cierre de etiqueta.
    """
    if not texto:
        return texto

    # 1. Eliminar bloques completos <razonamiento>...</razonamiento>
    texto_limpio = re.sub(
        r'<razonamiento>.*?</razonamiento>\s*',
        '',
        texto,
        flags=re.DOTALL | re.IGNORECASE
    )

    # 2. Respaldo defensivo en caso de truncamiento antes del cierre de etiqueta
    texto_limpio = re.sub(
        r'<razonamiento>.*$',
        '',
        texto_limpio,
        flags=re.DOTALL | re.IGNORECASE
    )

    return texto_limpio.strip()


def formatear_para_google_chat(texto: str) -> str:
    """
    Convierte la sintaxis Markdown estándar (producida por Gemini)
    a la sintaxis nativa de formateo de Google Chat.
    """
    if not texto:
        return texto

    # Limpiar razonamiento interno CoT antes de convertir sintaxis
    texto = limpiar_razonamiento_interno(texto)
    if not texto:
        return ""

    # 0. Convertir encabezados Markdown (# Título, ## Título) -> *Título*
    texto = re.sub(r'(?m)^#{1,6}\s+(.+)$', r'*\1*', texto)

    # 1. Convertir enlaces Markdown [Texto](URL) -> <URL|Texto>
    texto = re.sub(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', r'<\2|\1>', texto)

    # 2. Convertir Triple Asterisco ***texto*** -> _*texto*_ (Negrita + Cursiva)
    texto = re.sub(r'\*\*\*([^*]+)\*\*\*', r'_*\1*_', texto)

    # 3. Convertir Doble Asterisco **texto** -> *texto* (Negrita en Google Chat)
    texto = re.sub(r'\*\*([^*]+)\*\*', r'*\1*', texto)

    # 4. Limpiar posibles dobles guiones bajos residuales __texto__ -> _texto_
    texto = re.sub(r'__([^_]+)__', r'_\1_', texto)

    # 5. Evitar que asteriscos de negrita/cursiva queden pegados a URLs puras y rompan el clic
    texto = re.sub(r'\*+(https?://[^\s\*<>]+)\*+', r'\1', texto)

    return texto
