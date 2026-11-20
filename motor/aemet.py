"""AEMET OpenData: temperatura y lluvia en las capitales de provincia. Sin IA: solo HTTP y parseo.

Cómo funciona la API: cada consulta devuelve primero un JSON con la URL "datos" y después hay que
descargar esa URL. La clave va en la cabecera api_key (secreto AEMET_API_KEY del repositorio).

Qué se descarga:
- Valores diarios de TODAS las estaciones de los últimos 14 días (una sola consulta). De ahí se elige
  una estación por provincia (la de la capital: observatorio o aeropuerto) y se guarda su serie diaria.
  Con ellas se calcula la temperatura media diaria de las capitales (CÁLCULO DERIVADO) para el cruce
  con la demanda eléctrica.
- Valores mensuales de cada estación elegida desde 1991, en tramos de 3 años (límite de la API).
  La primera carga se hace poco a poco, con un tiempo máximo por ejecución, y continúa al día siguiente.
"""
from __future__ import annotations
import json
import os
import time
import unicodedata
from datetime import date, timedelta

from .series import Serie, Origen, ahora_iso
from . import fuentes as F

AEMET_BASE = "https://opendata.aemet.es/opendata/api"
LICENCIA = "© AEMET. Información elaborada por la Agencia Estatal de Meteorología (reutilización con cita de la fuente)"
PAUSA_S = 1.3                     # AEMET limita las consultas por minuto
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

# Provincia (nombre del INE, como en config/provincias.json) -> nombre de la capital tal como suele
# aparecer en el nombre de la estación de AEMET.
CAPITALES = {
    "Coruña, A": "A CORUNA", "Lugo": "LUGO", "Asturias": "OVIEDO", "Cantabria": "SANTANDER",
    "Bizkaia": "BILBAO", "Gipuzkoa": "SAN SEBASTIAN", "Pontevedra": "PONTEVEDRA", "Ourense": "OURENSE",
    "León": "LEON", "Palencia": "PALENCIA", "Burgos": "BURGOS", "Araba/Álava": "VITORIA",
    "Navarra": "PAMPLONA", "Huesca": "HUESCA", "Lleida": "LLEIDA", "Girona": "GIRONA", "Zamora": "ZAMORA",
    "Valladolid": "VALLADOLID", "Segovia": "SEGOVIA", "Soria": "SORIA", "Rioja, La": "LOGRONO",
    "Zaragoza": "ZARAGOZA", "Tarragona": "TARRAGONA", "Barcelona": "BARCELONA", "Salamanca": "SALAMANCA",
    "Ávila": "AVILA", "Madrid": "MADRID", "Guadalajara": "GUADALAJARA", "Cuenca": "CUENCA",
    "Teruel": "TERUEL", "Castellón/Castelló": "CASTELLON", "Balears, Illes": "PALMA", "Cáceres": "CACERES",
    "Toledo": "TOLEDO", "Ciudad Real": "CIUDAD REAL", "Albacete": "ALBACETE", "Valencia/València": "VALENCIA",
    "Badajoz": "BADAJOZ", "Córdoba": "CORDOBA", "Jaén": "JAEN", "Murcia": "MURCIA",
    "Alicante/Alacant": "ALICANTE", "Huelva": "HUELVA", "Sevilla": "SEVILLA", "Málaga": "MALAGA",
    "Granada": "GRANADA", "Almería": "ALMERIA", "Cádiz": "CADIZ", "Ceuta": "CEUTA", "Melilla": "MELILLA",
    "Santa Cruz de Tenerife": "SANTA CRUZ DE TENERIFE", "Palmas, Las": "GRAN CANARIA",
}
# Cómo se nombra cada estación en los textos: la capital (o el lugar de la estación si no está en ella)
NOMBRE_CAPITAL = {
    "Coruña, A": "A Coruña", "Asturias": "Oviedo", "Cantabria": "Santander", "Bizkaia": "Bilbao",
    "Gipuzkoa": "San Sebastián", "Araba/Álava": "Vitoria", "Navarra": "Pamplona", "Rioja, La": "Logroño",
    "Castellón/Castelló": "Castellón", "Balears, Illes": "Palma", "Valencia/València": "Valencia",
    "Alicante/Alacant": "Alicante", "Santa Cruz de Tenerife": "Santa Cruz de Tenerife",
    "Palmas, Las": "Gran Canaria",
}
# Variantes con que AEMET escribe algunas provincias (ya normalizadas: sin tildes, en mayúsculas)
ALIAS_PROVINCIA = {
    "A CORUNA": "Coruña, A", "LA CORUNA": "Coruña, A", "CORUNA A": "Coruña, A", "ASTURIAS": "Asturias",
    "VIZCAYA": "Bizkaia", "BIZKAIA": "Bizkaia", "GUIPUZCOA": "Gipuzkoa", "GIPUZKOA": "Gipuzkoa",
    "ALAVA": "Araba/Álava", "ARABA ALAVA": "Araba/Álava", "ARABA/ALAVA": "Araba/Álava", "ARABA": "Araba/Álava",
    "LA RIOJA": "Rioja, La", "RIOJA LA": "Rioja, La", "ILLES BALEARS": "Balears, Illes", "BALEARES": "Balears, Illes",
    "BALEARS ILLES": "Balears, Illes", "LAS PALMAS": "Palmas, Las", "PALMAS LAS": "Palmas, Las",
    "STA CRUZ DE TENERIFE": "Santa Cruz de Tenerife", "SANTA CRUZ DE TENERIFE": "Santa Cruz de Tenerife",
    "S C DE TENERIFE": "Santa Cruz de Tenerife", "CASTELLON": "Castellón/Castelló", "CASTELLO": "Castellón/Castelló",
    "VALENCIA": "Valencia/València", "ALICANTE": "Alicante/Alacant", "ALACANT": "Alicante/Alacant",
    "GERONA": "Girona", "LERIDA": "Lleida", "ORENSE": "Ourense", "NAVARRA": "Navarra",
}


def normaliza(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t)).encode("ascii", "ignore").decode().upper()
    return " ".join("".join(c if c.isalnum() or c == "/" else " " for c in t).split())


def provincia_ine(nombre_aemet: str, provincias_ine: list[str]) -> str | None:
    n = normaliza(nombre_aemet)
    if n in ALIAS_PROVINCIA:
        return ALIAS_PROVINCIA[n]
    for p in provincias_ine:
        if normaliza(p) == n or normaliza(p.split("/")[0]) == n:
            return p
    return None


def numero(v) -> float | None:
    """'23,4' -> 23.4; 'Ip' (precipitación inapreciable) -> 0.0; 'Acum', 'Varias', '' -> None.
    En los mensuales, '30.2(15)' -> 30.2 (el paréntesis es el día)."""
    if v is None:
        return None
    t = str(v).strip()
    if t.lower() == "ip":
        return 0.0
    t = t.split("(")[0].replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None


def llamar(ruta: str) -> tuple[list, str]:
    """Consulta en dos pasos. Devuelve ([] si AEMET dice que no hay datos, la URL de la consulta)."""
    clave = os.environ.get("AEMET_API_KEY")
    if not clave:
        raise RuntimeError("Falta AEMET_API_KEY")
    url = f"{AEMET_BASE}{ruta}"
    time.sleep(PAUSA_S)
    paso1 = json.loads(F._get(url, {"api_key": clave, "Accept": "application/json"}))
    estado = paso1.get("estado")
    if estado == 404:                                   # "No hay datos que satisfagan esos criterios"
        return [], url
    if estado != 200:
        raise RuntimeError(f"AEMET {ruta}: {estado} {paso1.get('descripcion')}")
    time.sleep(PAUSA_S)
    crudo = F._get(paso1["datos"])
    try:
        texto = crudo.decode("utf-8")
    except UnicodeDecodeError:
        texto = crudo.decode("latin-1")
    return json.loads(texto), url


def _f(d: date) -> str:
    return d.isoformat()


def diarios_todas(desde: date, hasta: date) -> tuple[list[dict], str]:
    return llamar(f"/valores/climatologicos/diarios/datos/fechaini/{_f(desde)}T00:00:00UTC"
                  f"/fechafin/{_f(hasta)}T23:59:59UTC/todasestaciones")


def mensuales(idema: str, anyo_ini: int, anyo_fin: int) -> tuple[list[dict], str]:
    return llamar(f"/valores/climatologicos/mensualesanuales/datos/anioini/{anyo_ini}/aniofin/{anyo_fin}/estacion/{idema}")


def elegir_estaciones(registros: list[dict], previas: dict, fijas: dict, provincias_ine: list[str]) -> dict:
    """Una estación por provincia: la elegida antes si sigue dando datos; si no, la mejor candidata
    de la capital (nombre de la capital + observatorio o aeropuerto). 'fijas' permite forzar una."""
    con_datos: dict[str, dict] = {}
    for r in registros:
        if numero(r.get("tmax")) is None:
            continue
        con_datos.setdefault(r["indicativo"], r)
    elegidas = {}
    for prov in provincias_ine:
        if prov in fijas and fijas[prov] in con_datos:
            r = con_datos[fijas[prov]]
            elegidas[prov] = {"indicativo": r["indicativo"], "nombre": r.get("nombre", ""), "altitud": r.get("altitud", "")}
            continue
        if prov in previas and previas[prov]["indicativo"] in con_datos:
            elegidas[prov] = previas[prov]
            continue
        capital = CAPITALES.get(prov, "")
        mejores = []
        for r in con_datos.values():
            if provincia_ine(r.get("provincia", ""), provincias_ine) != prov:
                continue
            nombre = normaliza(r.get("nombre", ""))
            puntos = 0
            if capital and capital in nombre:
                puntos += 3
            if "AEROPUERTO" in nombre:
                puntos += 2
            if "OBSERVATORIO" in nombre or "CMT" in nombre:
                puntos += 2
            if puntos:
                mejores.append((puntos, -len(nombre), r))
        if mejores:
            r = max(mejores, key=lambda x: (x[0], x[1]))[2]
            elegidas[prov] = {"indicativo": r["indicativo"], "nombre": r.get("nombre", ""), "altitud": r.get("altitud", "")}
    return elegidas


VARIABLES_DIARIAS = {"tmax": ("Temperatura máxima", "°C", 1), "tmin": ("Temperatura mínima", "°C", 1),
                     "tmed": ("Temperatura media", "°C", 1), "prec": ("Lluvia", "l/m²", 1)}


def series_diarias(registros: list[dict], estaciones: dict, corto: dict, url: str) -> list[Serie]:
    """Serie diaria de cada variable en cada estación elegida (solo se guarda; no se detecta nada con
    ella hasta que haya años de histórico)."""
    por_id = {e["indicativo"]: prov for prov, e in estaciones.items()}
    datos: dict[tuple[str, str], dict] = {}
    for r in registros:
        prov = por_id.get(r.get("indicativo"))
        if not prov:
            continue
        for var in VARIABLES_DIARIAS:
            v = numero(r.get(var))
            if v is not None:
                datos.setdefault((prov, var), {})[r["fecha"][:10]] = v
    out = []
    for (prov, var), vals in datos.items():
        nombre, unidad, dec = VARIABLES_DIARIAS[var]
        e = estaciones[prov]
        ps = sorted(vals)
        out.append(Serie(id=f"aemet.dia.{var}.{e['indicativo']}", nombre=f"{nombre} en {corto.get(prov, prov)}",
                         unidad=unidad, frecuencia="D", periodos=ps, valores=[vals[p] for p in ps],
                         origen=Origen("AEMET", "Valores climatológicos diarios", f"{var} · {e['nombre']}", url,
                                       e["indicativo"], ahora_iso(), LICENCIA),
                         decimales=dec, territorio=corto.get(prov, prov)))
    return out


def media_nacional_diaria(series_tmed: list[Serie], minimo: int = 40) -> tuple[list[str], list[float]]:
    """Media de la temperatura media diaria de las capitales (solo días con al menos 'minimo' estaciones)."""
    por_dia: dict[str, list[float]] = {}
    for s in series_tmed:
        for p, v in zip(s.periodos, s.valores):
            por_dia.setdefault(p, []).append(v)
    dias = sorted(p for p, vs in por_dia.items() if len(vs) >= minimo)
    return dias, [round(sum(por_dia[p]) / len(por_dia[p]), 2) for p in dias]


VARIABLES_MENSUALES = {"tm_mes": ("Temperatura media", "°C", 1), "p_mes": ("Lluvia", "l/m²", 1)}


def leer_mensuales(registros: list[dict]) -> dict[str, dict[str, float]]:
    """{'tm_mes': {'2025-10-01': 18.3, …}, 'p_mes': {…}}. Se ignora el resumen anual (mes 13)."""
    out: dict[str, dict[str, float]] = {v: {} for v in VARIABLES_MENSUALES}
    for r in registros:
        f = str(r.get("fecha", ""))
        try:
            a, m = f.split("-")[:2]
            a, m = int(a), int(m)
        except ValueError:
            continue
        if not 1 <= m <= 12:
            continue
        for var in VARIABLES_MENSUALES:
            v = numero(r.get(var))
            if v is not None:
                out[var][f"{a}-{m:02d}-01"] = v
    return out


def serie_mensual(var: str, idema: str, nombre_estacion: str, territorio: str, vals: dict, url: str) -> Serie:
    nombre, unidad, dec = VARIABLES_MENSUALES[var]
    ps = sorted(vals)
    return Serie(id=f"aemet.mes.{var}.{idema}", nombre=f"{nombre} del mes en {territorio}", unidad=unidad,
                 frecuencia="M", periodos=ps, valores=[vals[p] for p in ps],
                 origen=Origen("AEMET", "Valores climatológicos mensuales", f"{var} · {nombre_estacion}", url,
                               idema, ahora_iso(), LICENCIA),
                 decimales=dec, territorio=territorio)


def mismo_mes(s: Serie) -> Serie:
    """Solo los valores del mismo mes que el último dato, año a año: 'el octubre más cálido desde…'."""
    mes = int(s.periodos[-1][5:7])
    pares = [(p, v) for p, v in zip(s.periodos, s.valores) if int(p[5:7]) == mes]
    nombre_var = VARIABLES_MENSUALES[s.id.split(".")[2]][0]
    return Serie(id=f"{s.id}.m{mes:02d}", nombre=f"{nombre_var} de {MESES[mes - 1]} en {s.territorio}",
                 unidad=s.unidad, frecuencia="A", periodos=[p for p, _ in pares], valores=[v for _, v in pares],
                 origen=s.origen, decimales=s.decimales, territorio=s.territorio)
