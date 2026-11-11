import re


def formatear_para_google_chat(texto: str) -> str:
    """
    Convierte la sintaxis Markdown estándar (producida por Gemini)
    a la sintaxis nativa de formateo de Google Chat.
    """
    if not texto:
        return texto

    # 1. Convertir enlaces Markdown [Texto](URL) -> <URL|Texto>
    texto = re.sub(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', r'<\2|\1>', texto)

    # 2. Convertir Triple Asterisco ***texto*** -> _*texto*_ (Negrita + Cursiva)
    texto = re.sub(r'\*\*\*([^*]+)\*\*\*', r'_*\1*_', texto)

    # 3. Convertir Doble Asterisco **texto** -> *texto* (Negrita en Google Chat)
    texto = re.sub(r'\*\*([^*]+)\*\*', r'*\1*', texto)

    # 4. Limpiar posibles dobles guiones bajos residuales __texto__ -> _texto_
    texto = re.sub(r'__([^_]+)__', r'_\1_', texto)

    return texto