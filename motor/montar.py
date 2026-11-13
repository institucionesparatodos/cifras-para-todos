"""Monta las diapositivas de un lote: une los gráficos del motor (cifras puestas por código) con los
textos que ha redactado Claude en n8n (ya verificados). Lo ejecuta la Action "render".

Entrada  datos/lotes/<lote>.json  (lo sube n8n):
  {"lote": "...", "resume_url": "...", "carruseles": [{"carrusel": <plan del motor>, "redaccion": {...},
    "diapositivas": [<plan de diapositivas>], "afirmaciones": [...]}, ...]}
Salida   docs/<lote>/lote.json   (lo lee render.py y, después, la rama de publicación de n8n)

Uso: python -m motor.montar datos/lotes/<lote>.json docs/<lote>
"""
from __future__ import annotations
import json
import os
import statistics as st
import sys

from . import formato as fmt

AQUI = os.path.dirname(os.path.abspath(__file__))

# Mapa de cuadrícula de comunidades autónomas: nombre del INE -> abreviatura, nombre corto y posición [columna, fila]
CCAA = {
    "Galicia": {"abr": "GAL", "corto": "Galicia", "pos": [0, 0]},
    "Asturias, Principado de": {"abr": "AST", "corto": "Asturias", "pos": [1, 0]},
    "Cantabria": {"abr": "CAN", "corto": "Cantabria", "pos": [2, 0]},
    "País Vasco": {"abr": "PV", "corto": "País Vasco", "pos": [3, 0]},
    "Navarra, Comunidad Foral de": {"abr": "NAV", "corto": "Navarra", "pos": [4, 0]},
    "Castilla y León": {"abr": "CYL", "corto": "Castilla y León", "pos": [1, 1]},
    "Rioja, La": {"abr": "RIO", "corto": "La Rioja", "pos": [3, 1]},
    "Aragón": {"abr": "ARA", "corto": "Aragón", "pos": [4, 1]},
    "Cataluña": {"abr": "CAT", "corto": "Cataluña", "pos": [5, 1]},
    "Extremadura": {"abr": "EXT", "corto": "Extremadura", "pos": [1, 2]},
    "Madrid, Comunidad de": {"abr": "MAD", "corto": "Madrid", "pos": [2, 2]},
    "Castilla - La Mancha": {"abr": "CLM", "corto": "Castilla-La Mancha", "pos": [3, 2]},
    "Comunitat Valenciana": {"abr": "VAL", "corto": "C. Valenciana", "pos": [4, 2]},
    "Balears, Illes": {"abr": "BAL", "corto": "Illes Balears", "pos": [5.6, 2.3]},
    "Andalucía": {"abr": "AND", "corto": "Andalucía", "pos": [2, 3]},
    "Murcia, Región de": {"abr": "MUR", "corto": "Murcia", "pos": [3, 3]},
    "Ceuta": {"abr": "CEU", "corto": "Ceuta", "pos": [1.6, 4.2]},
    "Melilla": {"abr": "MEL", "corto": "Melilla", "pos": [2.8, 4.2]},
    "Canarias": {"abr": "CNR", "corto": "Canarias", "pos": [0, 4.2]},
}
RECUADRO_CANARIAS = {"provincia": ["Santa Cruz de Tenerife", "Palmas, Las"], "ccaa": ["Canarias"]}


def _provincias() -> dict:
    with open(os.path.join(AQUI, "..", "config", "provincias.json"), encoding="utf-8") as f:
        return json.load(f)["provincias"]


def territorios(nivel: str) -> dict:
    return CCAA if nivel == "ccaa" else _provincias()


def corto(nombre: str, nivel: str) -> str:
    return territorios(nivel).get(nombre, {}).get("corto", nombre)


def cortes_bonitos(valores: list[float], k: int = 5) -> list[float]:
    qs = st.quantiles(valores, n=k)
    rango = max(valores) - min(valores)
    paso = 0.5 if rango < 10 else 1 if rango < 40 else 5 if rango < 200 else 10 ** (len(str(int(rango))) - 2)
    limites = sorted({round(q / paso) * paso for q in qs})
    return [min(valores)] + limites


def texto_valor(v: float, unidad: str, decimales: int) -> str:
    return fmt.con_unidad(v, unidad, decimales)


def partir(texto: str) -> tuple[str, str]:
    """'49.935.642 personas' -> ('49.935.642', 'personas'); '10,18 %' -> ('10,18 %', '')."""
    t = texto.replace("\u00a0", " ")
    num, _, resto = t.partition(" ")
    if resto in ("%", "€"):
        return texto, ""
    return num, resto


def mayuscula(t: str) -> str:
    return t[:1].upper() + t[1:]


def _limpia(desc: str) -> str:
    return desc.replace(" (España)", "")


# ---------------------------------------------------------------------------
# Diapositivas de gráfico, a partir del "visual" de cada insight
# ---------------------------------------------------------------------------
def diapositiva_visual(ins: dict, txt: dict, afs: list[dict]) -> dict:
    v = ins["visual"]
    tipo = v["tipo"]
    tipos = sorted({a["tipo"] for a in ins["afirmaciones"]}, key=["DATO OFICIAL", "CÁLCULO DERIVADO", "COMPARACIÓN", "ESTIMACIÓN"].index)
    base = {"titulo": txt.get("titulo", ""), "nota": txt.get("nota", ""), "tipos": tipos}

    def periodo_de(iso):                 # etiqueta legible de un periodo usando las afirmaciones (respeta "a 1 de…")
        for a in afs:
            if a.get("fecha_dato") == iso:
                return a["periodo"].removeprefix("a ")
        return iso[:4]

    if tipo in ("lineas", "barras"):
        s = v["serie"]
        return {**base, "tipo": tipo, "serie": s,
                "ultimo_texto": texto_valor(s["valores"][-1], s["unidad"], s["decimales"]),
                "desde": v.get("destacar_desde")}
    if tipo == "comparacion":
        dec = v.get("decimales", 0)
        var = next((a for a in ins["afirmaciones"] if a["tipo"] != "DATO OFICIAL"), None)
        return {**base, "tipo": "comparacion",
                "antes": {"etiqueta": mayuscula(periodo_de(v["antes"]["periodo"])), "valor": v["antes"]["valor"],
                          "texto": partir(texto_valor(v["antes"]["valor"], v["unidad"], dec))[0]},
                "ahora": {"etiqueta": mayuscula(periodo_de(v["ahora"]["periodo"])), "valor": v["ahora"]["valor"],
                          "texto": partir(texto_valor(v["ahora"]["valor"], v["unidad"], dec))[0]},
                "unidad": partir(texto_valor(v["ahora"]["valor"], v["unidad"], dec))[1],
                "variacion": (("+" if var["valor"] > 0 else "") + var["texto_valor"]) if var else ""}
    if tipo == "mapa":
        terr = territorios(v["nivel"])
        celdas = [{"abr": terr[n]["abr"], "pos": terr[n]["pos"], "valor": val}
                  for n, val in v["valores"].items() if n in terr]
        recuadro = [terr[n]["pos"] for n in RECUADRO_CANARIAS.get(v["nivel"], []) if n in terr]
        return {**base, "tipo": "mapa", "celdas": celdas, "recuadro": recuadro, "unidad": v["unidad"],
                "decimales": v.get("decimales", 1), "cortes": cortes_bonitos(list(v["valores"].values())),
                "columnas": 11 if v["nivel"] != "ccaa" else 6.6}
    if tipo == "top_bottom":
        items = sorted(v["valores"].items(), key=lambda kv: kv[1], reverse=True)
        n = v.get("n", 5)
        fila = lambda t, x: {"nombre": corto(t, v["nivel"]), "valor": x, "texto": texto_valor(x, v["unidad"], v.get("decimales", 1))}
        return {**base, "tipo": "top_bottom",
                "arriba": [fila(t, x) for t, x in items[:n]], "abajo": [fila(t, x) for t, x in items[::-1][:n]],
                "rotulo_arriba": "Más alto", "rotulo_abajo": "Más bajo",
                "referencia": v.get("total"),
                "rotulo_referencia": f"España: {texto_valor(v['total'], v['unidad'], v.get('decimales', 1))}" if v.get("total") is not None else ""}
    if tipo == "ranking":
        items = sorted(v["valores"].items(), key=lambda kv: kv[1], reverse=True)
        top = items[:8]
        if v.get("destacar") and v["destacar"] not in dict(top):
            top = top[:7] + [(v["destacar"], v["valores"][v["destacar"]])]
        return {**base, "tipo": "ranking",
                "filas": [{"nombre": corto(t, v["nivel"]), "valor": x, "texto": texto_valor(x, v["unidad"], v.get("decimales", 1)),
                           "destacar": t == v.get("destacar")} for t, x in top]}
    if tipo == "comparacion_grupos":
        dec = v.get("decimales", 1)
        bloques = []
        if v.get("total") and v["total"][0] is not None:
            bloques.append({"nombre": "España", "barras": [
                {"nombre": v["a"].capitalize(), "valor": v["total"][0], "texto": texto_valor(v["total"][0], v["unidad"], dec)},
                {"nombre": v["b"].capitalize(), "valor": v["total"][1], "texto": texto_valor(v["total"][1], v["unidad"], dec)}]})
        t, va, vb = v["destacado"]
        bloques.append({"nombre": t, "barras": [
            {"nombre": v["a"].capitalize(), "valor": va, "texto": texto_valor(va, v["unidad"], dec)},
            {"nombre": v["b"].capitalize(), "valor": vb, "texto": texto_valor(vb, v["unidad"], dec)}]})
        for b in bloques:
            d = b["barras"][0]["valor"] - b["barras"][1]["valor"]
            b["diferencia"] = f"{fmt.puntos(d, dec) if v['unidad'] == '%' else texto_valor(abs(d), v['unidad'], dec)} de diferencia"
        return {**base, "tipo": "comparacion_grupos", "bloques": bloques}
    if tipo == "hoy_vs_media":
        dec = 1
        return {**base, "tipo": "hoy_vs_media",
                "hoy": {"valor": v["hoy"], "texto": texto_valor(v["hoy"], v["unidad"], dec)},
                "media": {"valor": v["media"], "texto": texto_valor(v["media"], v["unidad"], dec)}}
    if tipo == "doble_linea":
        return {**base, "tipo": "doble_linea", "a": v["a"], "b": v["b"]}
    if tipo == "contador":
        return {**base, "tipo": "contador", "cifra": texto_valor(v["valor"], v["unidad"], 0), "etiqueta": ""}
    return {**base, "tipo": "texto"}


# ---------------------------------------------------------------------------
def montar_carrusel(item: dict) -> dict:
    c, red, plan, afs = item["carrusel"], item["redaccion"], item["diapositivas"], item["afirmaciones"]
    insights = [c["principal"], *c.get("secundarios", [])]
    textos = {int(d["n"]): d for d in red.get("diapositivas", [])}
    a0 = c["principal"]["afirmaciones"][0]
    o0 = (a0.get("origenes") or [{}])[0]
    fuente = o0.get("fuente", "")
    operacion = o0.get("dataset", "").split(" · ")[0]
    fuente_corta = f"Fuente: {fuente}" + (f" ({operacion})" if operacion and operacion != fuente else "") + f", {a0['periodo'].removeprefix('a ')}"

    diapos = []
    k_visual = 0
    for d in plan:
        n, tipo = int(d["n"]), d["tipo"]
        txt = textos.get(n, {})
        if tipo == "portada":
            diapos.append({"tipo": "portada", "oscura": True, "formato": c["formato"],
                           "titulo": red["portada"]["titulo"], "subtitulo": red["portada"].get("subtitulo", ""), "sin_pie": True})
        elif tipo == "contador":
            cifra, unidad = partir(a0["texto_valor"])
            diapos.append({"tipo": "contador", "titulo": txt.get("titulo", ""), "cifra": cifra, "unidad": unidad,
                           "etiqueta": f"{_limpia(a0['descripcion'])} · {a0['periodo'].removeprefix('a ')}",
                           "nota": txt.get("nota", ""), "tipos": [a0["tipo"]]})
        elif tipo == "conclusion":
            diapos.append({"tipo": "conclusion", "titulo": "En resumen", "puntos": red.get("resumen", []),
                           "tipos": sorted({a["tipo"] for a in afs})})
        elif tipo == "fuente":
            datasets = sorted({a["dataset"] for a in afs if a.get("dataset")})
            hay_calculos = any(a["tipo"] != "DATO OFICIAL" for a in afs)
            filas = [["Fuente", {"INE": "Instituto Nacional de Estadística (INE)", "BCE": "Banco Central Europeo (BCE)",
                                 "REE (REData)": "Red Eléctrica (REData)"}.get(fuente, fuente)],
                     ["Estadística", ", ".join(datasets) or operacion],
                     ["Dato", mayuscula(a0["periodo"].removeprefix("a "))],
                     ["Qué se mide", red.get("que_se_mide", "")]]
            if hay_calculos:
                filas.append(["Cálculos", "Diferencias, variaciones y recuentos hechos por Cifras para todos con los datos oficiales"])
            diapos.append({"tipo": "fuente", "titulo": "Fuente y método", "sin_pie": True, "filas": filas,
                           "leyenda_tipos": "<b>✓ DATO OFICIAL</b>: cifra publicada por la fuente.<br>"
                                            "<b>= COMPARACIÓN o CÁLCULO DERIVADO</b>: operación hecha por nosotros con datos oficiales.<br>"
                                            "<b>≈ ESTIMACIÓN</b>: valor aproximado."})
        else:
            ins = insights[k_visual] if k_visual < len(insights) else insights[-1]
            k_visual += 1
            diapos.append(diapositiva_visual(ins, txt, afs))

    return {"titulo_publicacion": red.get("titulo_publicacion", ""), "fuente_corta": fuente_corta,
            "pie_de_foto": red.get("pie_de_foto", ""), "hashtags": red.get("hashtags", []), "alt": red.get("alt", ""),
            "insight_id": c["principal"]["id"], "fuente_id": c["principal"]["fuente_id"], "formato": c["formato"],
            "diapositivas": diapos}


def montar_lote(ruta_entrada: str, carpeta_salida: str) -> str:
    entrada = json.load(open(ruta_entrada, encoding="utf-8"))
    lote = {"lote": entrada["lote"], "resume_url": entrada.get("resume_url", ""),
            "carruseles": [montar_carrusel(it) for it in entrada["carruseles"]]}
    os.makedirs(carpeta_salida, exist_ok=True)
    ruta = os.path.join(carpeta_salida, "lote.json")
    json.dump(lote, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return ruta


if __name__ == "__main__":
    print(montar_lote(sys.argv[1], sys.argv[2]))
