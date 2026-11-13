"""Formato de cifras en español según la guía de estilo:
punto para miles, coma para decimales, "12 %" con espacio, fechas largas."""
import re

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def num(valor: float, decimales: int = 0) -> str:
    """1234567.891 -> '1.234.567,89' (con decimales=2)."""
    if valor is None:
        return "—"
    s = f"{abs(valor):,.{decimales}f}"            # 1,234,567.89
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if valor < 0 else "") + s


def pct(valor: float, decimales: int = 1) -> str:
    return f"{num(valor, decimales)}\u00a0%"


def puntos(valor: float, decimales: int = 1) -> str:
    """Diferencias entre porcentajes: puntos porcentuales, nunca '%'."""
    n = num(abs(valor), decimales)
    return f"{n} puntos" if n != "1" else "1 punto"


def con_unidad(valor: float, unidad: str, decimales: int) -> str:
    if unidad == "%":
        return pct(valor, decimales)
    if unidad in ("", None):
        return num(valor, decimales)
    return f"{num(valor, decimales)}\u00a0{unidad}"


def fecha_larga(iso: str) -> str:
    a, m, d = iso[:10].split("-")
    return f"{int(d)} de {MESES[int(m) - 1]} de {a}"


def por_cada(ratio: float, base: int = 100) -> str:
    """Traduce una tasa a 'X de cada 100' (redondeo a entero, se marca como aproximado)."""
    return f"unas {round(ratio * base / 100)} de cada {base}"


# --- Extracción de cifras de un texto (para la verificación automática) ---
_NUM = re.compile(r"(?<![\w.,])[−-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\w])|(?<![\w.,])[−-]?\d+(?:,\d+)?(?![\w])")


def cifras_en_texto(texto: str) -> list[float]:
    """Devuelve las cifras que aparecen en un texto en español como floats.
    Ignora años sueltos (1900-2100) y números de trimestre ("3T")."""
    salida = []
    for m in _NUM.finditer(texto):
        s = m.group(0).replace("−", "-").replace(".", "").replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            continue
        salida.append(v)
    return salida
