"""Construye el lote de diapositivas a partir del plan del motor (cifras y gráficos, hechos por código)
y de los textos que redacta la IA (titulares y frases, sin cifras propias).

La IA nunca escribe números en los datos de los gráficos: los valores de barras, mapas y contadores
salen de las afirmaciones. En los textos sí puede citar cifras, pero el verificador exige que cada
una coincida con una afirmación del carrusel.
"""
from __future__ import annotations
import json
import os
import statistics as st

from . import formato as fmt

AQUI = os.path.dirname(os.path.abspath(__file__))


def cortes_bonitos(valores: list[float], k: int = 5) -> list[float]:
    """Límites de tramos por cuantiles, redondeados a números 'redondos' (enteros o múltiplos de 5, 10…)."""
    qs = st.quantiles(valores, n=k)
    rango = max(valores) - min(valores)
    paso = 1 if rango < 40 else 5 if rango < 200 else 10 ** (len(str(int(rango))) - 2)
    limites = sorted({round(q / paso) * paso for q in qs})
    return [0] + limites


def provincias_cfg() -> dict:
    with open(os.path.join(AQUI, "..", "config", "provincias.json"), encoding="utf-8") as f:
        return json.load(f)["provincias"]


def afirmaciones_de(car: dict) -> list[dict]:
    vistos, out = set(), []
    for ins in [car["principal"], *car["secundarios"]]:
        for a in ins["afirmaciones"]:
            clave = (a["id"], a["texto_valor"])
            if clave not in vistos:
                vistos.add(clave)
                out.append(a)
    return out


def textos_de(lote: dict) -> list[str]:
    """Todos los textos redactados (para pasarlos al verificador)."""
    out = []
    for car in lote["carruseles"]:
        out += [car["titulo_publicacion"], car["pie_de_foto"]]
        for s in car["diapositivas"]:
            for k in ("titulo", "subtitulo", "nota", "etiqueta"):
                if s.get(k):
                    out.append(s[k])
            out += s.get("puntos", [])
    return out
