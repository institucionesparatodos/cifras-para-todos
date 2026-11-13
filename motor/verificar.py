"""Control automático de lo que redacta la IA. Se ejecuta en un nodo Code de n8n (versión JS en
n8n/verificar.js) y aquí en Python para las pruebas. Reglas:

1. Toda cifra del texto debe coincidir con el 'texto_valor' o el 'valor' de alguna afirmación
   del carrusel (con el redondeo que se indica). Si no, el carrusel no pasa.
2. Los años y los ordinales de trimestre se permiten si aparecen en algún 'periodo'.
3. Vocabulario causal prohibido cuando el insight es un cruce entre variables.
4. Vocabulario sensacionalista o valorativo prohibido siempre.
"""
from __future__ import annotations
import re
import unicodedata

from .formato import cifras_en_texto

CAUSALES = ["provoca", "provocó", "causa", "causó", "debido a", "por culpa de", "gracias a",
            "hace que", "dispara", "se debe a", "como consecuencia", "consecuencia de", "explica que"]
SENSACIONALISTAS = ["brutal", "histórico desastre", "escándalo", "alarmante", "dramático", "increíble",
                    "bomba", "se dispara", "se desploma", "hundimiento", "catástrofe", "por fin",
                    "vergüenza", "lamentable", "afortunadamente", "por desgracia"]


def _norm(t: str) -> str:
    return unicodedata.normalize("NFC", t.lower())


def verificar(textos: list[str], afirmaciones: list[dict], es_cruce: bool = False) -> list[str]:
    problemas = []
    permitidos = []
    for a in afirmaciones:
        permitidos.append(float(a["valor"]))
        permitidos += cifras_en_texto(a["texto_valor"])
        permitidos += cifras_en_texto(a.get("periodo", ""))
        for o in a.get("origenes", []):                 # números de tabla, códigos de serie…
            permitidos += cifras_en_texto(o.get("dataset", ""))
    for texto in textos:
        for c in cifras_en_texto(texto):
            if 1900 <= c <= 2100 and c == int(c):
                if any(str(int(c)) in a.get("periodo", "") or str(int(c)) in a.get("descripcion", "")
                       for a in afirmaciones):
                    continue
            if c in (1, 2, 3, 4, 5, 10) and re.search(rf"\b(las|los|top)\s+{int(c)}\b", _norm(texto)):
                continue                                 # "las 5 provincias…"
            if not any(abs(c - p) <= max(0.005 * abs(p), 0.051) for p in permitidos):
                problemas.append(f"Cifra sin respaldo: {c} en «{texto[:80]}»")
        n = _norm(texto)
        for palabra in SENSACIONALISTAS:
            if palabra in n:
                problemas.append(f"Término no neutral «{palabra}» en «{texto[:80]}»")
        if es_cruce:
            for palabra in CAUSALES:
                if palabra in n:
                    problemas.append(f"Lenguaje causal «{palabra}» en un cruce de variables")
    return problemas
