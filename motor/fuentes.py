"""Descarga de datos de las fuentes oficiales. Sin IA: solo HTTP y parseo.

Fase 1: INE (Tempus3), REE (REData) y BCE (ECB Data Portal, SDMX).
Fase 2: AEMET OpenData (necesita API key gratuita en el secreto AEMET_API_KEY).
Fase 3: datos.gob.es (descubrimiento de datasets) y e·sios (token personal de REE).

Cada función devuelve objetos Serie o Corte con su Origen (URL exacta incluida),
para que cualquier cifra pueda trazarse hasta la consulta que la produjo.
"""
from __future__ import annotations
import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .series import Serie, Corte, Origen, ahora_iso

UA = {"User-Agent": "cifras-para-todos/0.1 (divulgacion; contacto: institucionesparatodos@gmail.com)"}


def _get(url: str, headers: dict | None = None, reintentos: int = 3) -> bytes:
    h = dict(UA)
    h.update(headers or {})
    ultimo = None
    for i in range(reintentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return r.read()
        except Exception as e:          # noqa: BLE001 - se reintenta y se informa
            ultimo = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {ultimo}")


# ---------------------------------------------------------------------------
# INE · API Tempus3 (JSON). Doc: https://www.ine.es/dyngs/DAB/index.htm?cid=1099
#   DATOS_TABLA/{id}?nult=N  -> todas las series de una tabla, últimos N periodos
#   DATOS_SERIE/{cod}?nult=N -> una serie
# Lección: con el cambio a base 2025 del IPC (enero 2026) las series antiguas
# dejaron de actualizarse (IPC251852 termina en dic-2025). Por eso:
#   1) se trabaja por TABLA y se elige la serie por su nombre (filtro), no por código;
#   2) toda serie cuyo último dato sea más viejo de lo esperado se marca "congelada"
#      y se avisa por Telegram en vez de usarla.
# ---------------------------------------------------------------------------
INE_BASE = "https://servicios.ine.es/wstempus/js/ES"
PERIODO_INE = {**{m: ("M", m) for m in range(1, 13)},
               19: ("T", 1), 20: ("T", 2), 21: ("T", 3), 22: ("T", 4), 28: ("A", 1)}


def _periodo_ine(dato: dict) -> tuple[str, str, str]:
    """-> (frecuencia, fecha_inicio_iso, etiqueta)."""
    anyo, fk = dato["Anyo"], dato["FK_Periodo"]
    frec, n = PERIODO_INE.get(fk, ("?", 1))
    if frec == "M":
        return "M", f"{anyo}-{n:02d}-01", f"{n:02d}/{anyo}"
    if frec == "T":
        return "T", f"{anyo}-{3 * (n - 1) + 1:02d}-01", f"{n}T {anyo}"
    if frec == "A":
        return "A", f"{anyo}-01-01", str(anyo)
    # Periodos raros (semestres, semanas…): se usa la fecha que da el INE
    f = datetime.fromtimestamp(dato["Fecha"] / 1000, tz=timezone.utc) + timedelta(hours=2)
    return "?", f.date().isoformat(), f.date().isoformat()


def ine_tabla(tabla: int, nult: int | None = None, extra: str = "") -> list[dict]:
    q = f"?nult={nult}" if nult else "?"
    url = f"{INE_BASE}/DATOS_TABLA/{tabla}{q}{extra}"
    return json.loads(_get(url)), url


def ine_series_de_tabla(tabla: int, filtro_nombre: list[str], nult: int | None = None,
                        id_base: str = "", unidad: str = "", decimales: int = 1,
                        dataset: str = "") -> list[Serie]:
    """Una Serie por cada serie de la tabla cuyo nombre contenga todos los textos de filtro_nombre."""
    datos, url = ine_tabla(tabla, nult)
    out = []
    for s in datos:
        nombre = s["Nombre"].strip().rstrip(".").strip()
        if not all(f.lower() in nombre.lower() for f in filtro_nombre):
            continue
        puntos = [(_periodo_ine(d), d["Valor"]) for d in s.get("Data", [])
                  if d.get("Valor") is not None and not d.get("Secreto")]
        if not puntos:
            continue
        frec = puntos[-1][0][0]
        out.append(Serie(
            id=f"{id_base}.{s['COD']}".lower(), nombre=nombre, unidad=unidad, frecuencia=frec,
            periodos=[p[0][1] for p in puntos], valores=[float(v) for _, v in puntos],
            origen=Origen("INE", dataset or f"Tabla {tabla}", nombre, url, s["COD"], ahora_iso(),
                          "Licencia de uso del INE (cita obligatoria de la fuente)"),
            decimales=decimales))
    return out


def ine_corte_territorial(tabla: int, filtro_nombre: list[str], nivel: str, id_: str, nombre: str,
                          unidad: str, total_contiene: str = "Total Nacional", decimales: int = 2,
                          dataset: str = "", nota: str = "") -> Corte:
    """Último periodo de una tabla territorial -> Corte. El territorio es el último trozo del nombre
    de la serie ("Tasa de paro de la población. Ambos sexos. Granada" -> "Granada")."""
    datos, url = ine_tabla(tabla, 1)
    valores, total, per = {}, None, None
    for s in datos:
        partes = [p.strip() for p in s["Nombre"].strip().rstrip(".").split(".")]
        if not all(any(f.lower() == p.lower() or f.lower() in p.lower() for p in partes[:-1])
                   for f in filtro_nombre):
            continue
        d = s["Data"][-1]
        if d.get("Valor") is None:
            continue
        per = _periodo_ine(d)
        terr = partes[-1]
        if total_contiene and total_contiene.lower() in terr.lower():
            total = float(d["Valor"])
        else:
            valores[terr] = float(d["Valor"])
    if per is None:
        raise ValueError(f"Tabla {tabla}: ninguna serie coincide con {filtro_nombre}")
    return Corte(id=id_, nombre=nombre, unidad=unidad, periodo=per[2], fecha=per[1], nivel=nivel,
                 valores=valores, total=total,
                 origen=Origen("INE", dataset or f"Tabla {tabla}", nombre, url, "", ahora_iso(),
                               "Licencia de uso del INE (cita obligatoria de la fuente)"),
                 decimales=decimales, nota_metodologica=nota)


# ---------------------------------------------------------------------------
# REE · REData. Doc: https://www.ree.es/es/apidatos
#   /{lang}/datos/{categoria}/{widget}?start_date=…&end_date=…&time_trunc=day|month|year
#   [&geo_trunc=electric_system&geo_limit=peninsular|ccaa&geo_ids=…]
# Respuesta JSON:API: included[] -> {attributes: {title, values: [{value, percentage, datetime}]}}
# Límite práctico: rangos largos con time_trunc=day se piden por tramos de 1 año.
# ---------------------------------------------------------------------------
REDATA_BASE = "https://apidatos.ree.es/es/datos"


def redata(categoria: str, widget: str, inicio: date, fin: date, trunc: str = "day",
           geo: str = "") -> tuple[dict, str]:
    q = {"start_date": f"{inicio.isoformat()}T00:00", "end_date": f"{fin.isoformat()}T23:59",
         "time_trunc": trunc}
    url = f"{REDATA_BASE}/{categoria}/{widget}?{urllib.parse.urlencode(q)}{geo}"
    return json.loads(_get(url, {"Accept": "application/json", "Content-Type": "application/json"})), url


def redata_series(categoria: str, widget: str, inicio: date, fin: date, trunc: str,
                  id_base: str, unidad: str, decimales: int = 0) -> list[Serie]:
    """Una Serie por cada componente del widget (p. ej. Solar fotovoltaica, Eólica, Nuclear…)."""
    tramos, a = [], inicio
    paso = timedelta(days=365) if trunc == "day" else timedelta(days=365 * 30)
    while a <= fin:
        b = min(fin, a + paso - timedelta(days=1))
        tramos.append((a, b))
        a = b + timedelta(days=1)
    acumulado: dict[str, dict] = {}
    urls = []
    for a, b in tramos:
        js, url = redata(categoria, widget, a, b, trunc)
        urls.append(url)
        for inc in js.get("included", []):
            at = inc["attributes"]
            t = at["title"]
            acc = acumulado.setdefault(t, {})
            for v in at.get("values", []):
                acc[v["datetime"][:10]] = float(v["value"])
    out = []
    for titulo, vals in acumulado.items():
        ps = sorted(vals)
        slug = "".join(c for c in titulo.lower().replace(" ", "_") if c.isalnum() or c == "_")
        out.append(Serie(
            id=f"{id_base}.{slug}", nombre=titulo, unidad=unidad,
            frecuencia={"day": "D", "month": "M", "year": "A"}[trunc],
            periodos=ps, valores=[vals[p] for p in ps],
            origen=Origen("REE (REData)", f"{categoria}/{widget}", titulo, urls[-1], "", ahora_iso(),
                          "Datos de Red Eléctrica (REData), uso con cita de la fuente"),
            decimales=decimales))
    return out


# ---------------------------------------------------------------------------
# BCE · ECB Data Portal (SDMX REST). Doc: https://data.ecb.europa.eu/help/api/data
#   /service/data/{flujo}/{clave}?format=csvdata&startPeriod=…&lastNObservations=…&updatedAfter=…
# Sin clave de acceso.
# ---------------------------------------------------------------------------
BCE_BASE = "https://data-api.ecb.europa.eu/service/data"


def bce_serie(flujo: str, clave: str, id_: str, nombre: str, unidad: str, frecuencia: str,
              inicio: str = "1999-01", decimales: int = 2) -> Serie:
    url = f"{BCE_BASE}/{flujo}/{clave}?format=csvdata&detail=dataonly&startPeriod={inicio}"
    filas = list(csv.DictReader(io.StringIO(_get(url).decode("utf-8"))))
    ps, vs = [], []
    for f in filas:
        if f.get("OBS_VALUE") in ("", None, "NaN"):
            continue
        t = f["TIME_PERIOD"]
        if len(t) == 7:                       # 2026-09
            t = t + "-01"
        elif "-Q" in t:                       # 2026-Q3
            a, q = t.split("-Q")
            t = f"{a}-{3 * (int(q) - 1) + 1:02d}-01"
        elif len(t) == 4:
            t = t + "-01-01"
        ps.append(t)
        vs.append(float(f["OBS_VALUE"]))
    return Serie(id=id_, nombre=nombre, unidad=unidad, frecuencia=frecuencia, periodos=ps, valores=vs,
                 origen=Origen("BCE", f"ECB Data Portal · {flujo}", nombre, url, f"{flujo}.{clave}",
                               ahora_iso(), "Reutilización con cita de la fuente (BCE)"),
                 decimales=decimales)


# ---------------------------------------------------------------------------
# AEMET OpenData (fase 2). La API responde en dos pasos: primero un JSON con la
# URL "datos" y después hay que descargar esa URL. Clave en api_key (cabecera).
#   /api/observacion/convencional/todas                          (últimas 24 h, todas las estaciones)
#   /api/valores/climatologicos/diarios/datos/fechaini/…/fechafin/…/todasestaciones
#   /api/valores/climatologicos/normales/estacion/{idema}        (normales 1991-2020)
#   /api/valores/climatologicos/valoresextremos/parametro/{T|P|V}/estacion/{idema}
# ---------------------------------------------------------------------------
AEMET_BASE = "https://opendata.aemet.es/opendata/api"


def aemet(ruta: str) -> tuple[list, str]:
    clave = os.environ.get("AEMET_API_KEY")
    if not clave:
        raise RuntimeError("Falta AEMET_API_KEY (fase 2)")
    paso1 = json.loads(_get(f"{AEMET_BASE}{ruta}", {"api_key": clave}))
    if paso1.get("estado") != 200:
        raise RuntimeError(f"AEMET {ruta}: {paso1.get('descripcion')}")
    datos = _get(paso1["datos"]).decode("latin-1")
    return json.loads(datos), f"{AEMET_BASE}{ruta}"


# ---------------------------------------------------------------------------
# Comprobación de series congeladas (cambios de base, series discontinuadas…)
# ---------------------------------------------------------------------------
RETRASO_MAXIMO_DIAS = {"D": 7, "M": 75, "T": 160, "A": 500}


def esta_congelada(serie: Serie, hoy: date | None = None) -> bool:
    hoy = hoy or date.today()
    ultimo = date.fromisoformat(serie.periodos[-1])
    return (hoy - ultimo).days > RETRASO_MAXIMO_DIAS.get(serie.frecuencia, 400)


def ine_buscar_tabla(operacion: str, contiene: str) -> int:
    """Id de la tabla de una operación del INE cuyo nombre contiene el texto (la más reciente si hay varias)."""
    tablas = json.loads(_get(f"{INE_BASE}/TABLAS_OPERACION/{operacion}"))
    cand = [t for t in tablas if contiene.lower() in t["Nombre"].lower()]
    if not cand:
        raise ValueError(f"INE {operacion}: ninguna tabla contiene «{contiene}»")
    return max(cand, key=lambda t: t["Id"])["Id"]
