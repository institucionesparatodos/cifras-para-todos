"""Descarga de datos de las fuentes oficiales. Sin IA: solo HTTP y parseo.

Fase 1: INE (Tempus3), REE (REData) y BCE (ECB Data Portal, SDMX).
Fase 2: AEMET OpenData (secreto AEMET_API_KEY) y e·sios (secreto ESIOS_TOKEN).
Fase 3: datos.gob.es (aviso semanal de datasets nuevos, desde n8n).

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


def _partes(nombre: str) -> list[str]:
    return [p.strip() for p in nombre.strip().rstrip(".").split(".") if p.strip()]


def _coincide(filtro: list[str], partes: list[str]) -> bool:
    """Cada elemento del filtro debe ser IGUAL a alguna parte del nombre de la serie (sin distinguir
    mayúsculas). Un elemento que acaba en '*' basta con que sea el comienzo de una parte.
    Coincidencia exacta a propósito: con 'contiene', «Total» también encajaba en «Total Nacional»
    y se colaban series de mujeres u hombres en lugar del total."""
    pl = [p.lower() for p in partes]
    for f in filtro:
        f = f.lower()
        if f.endswith("*"):
            if not any(p.startswith(f[:-1]) for p in pl):
                return False
        elif f not in pl:
            return False
    return True


def ine_tabla(tabla: int, nult: int | None = None, extra: str = "") -> list[dict]:
    q = f"?nult={nult}" if nult else "?"
    url = f"{INE_BASE}/DATOS_TABLA/{tabla}{q}{extra}"
    datos = json.loads(_get(url))
    if not isinstance(datos, list):                 # el INE devuelve un objeto con un mensaje si algo falla
        raise ValueError(f"Tabla {tabla}: respuesta inesperada del INE: {str(datos)[:300]}")
    return datos, url


def _muestra_nombres(datos: list[dict], n: int = 8) -> str:
    return " | ".join(s.get("Nombre", "?").strip() for s in datos[:n])


def ine_series_de_tabla(tabla: int, filtro_nombre: list[str], nult: int | None = 600,
                        id_base: str = "", unidad: str = "", decimales: int = 1,
                        dataset: str = "") -> list[Serie]:
    """Una Serie por cada serie de la tabla cuyo nombre contenga todos los textos de filtro_nombre."""
    datos, url = ine_tabla(tabla, nult)
    out = []
    for s in datos:
        nombre = s["Nombre"].strip().rstrip(".").strip()
        if not _coincide(filtro_nombre, _partes(nombre)):
            continue
        puntos = [(_periodo_ine(d), d["Valor"]) for d in s.get("Data", [])
                  if d.get("Valor") is not None and not d.get("Secreto")]
        if not puntos:
            continue
        puntos.sort(key=lambda x: x[0][1])          # el INE puede devolver los datos del más nuevo al más antiguo
        frec = puntos[-1][0][0]
        out.append(Serie(
            id=f"{id_base}.{s['COD']}".lower(), nombre=nombre, unidad=unidad, frecuencia=frec,
            periodos=[p[0][1] for p in puntos], valores=[float(v) for _, v in puntos],
            origen=Origen("INE", dataset or f"Tabla {tabla}", nombre, url, s["COD"], ahora_iso(),
                          "Licencia de uso del INE (cita obligatoria de la fuente)"),
            decimales=decimales))
    if not out:
        raise ValueError(f"Tabla {tabla}: ninguna serie contiene {filtro_nombre}. Ejemplos de nombres: {_muestra_nombres(datos)}")
    return out


def _clave(t: str) -> str:
    return "".join(c for c in t.lower() if c.isalnum())


_TERRITORIOS = None


def _territorio(partes: list[str]) -> str:
    """Busca en las partes del nombre de la serie un territorio conocido (provincias, CCAA, Total Nacional),
    sin depender de la posición. Si no encuentra ninguno, usa la última parte."""
    global _TERRITORIOS
    if _TERRITORIOS is None:
        cfg = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "provincias.json"), encoding="utf-8"))
        nombres = list(cfg["provincias"]) + cfg.get("ccaa_ine", []) + ["Total Nacional"]
        _TERRITORIOS = {_clave(n): n for n in nombres}
    for p in partes:
        if _clave(p) in ("nacional", "totalnacional"):
            return "Total Nacional"
        if _clave(p) in _TERRITORIOS:
            return _TERRITORIOS[_clave(p)]
    return partes[-1]


def ine_corte_territorial(tabla: int, filtro_nombre: list[str], nivel: str, id_: str, nombre: str,
                          unidad: str, total_contiene: str = "Total Nacional", decimales: int = 2,
                          dataset: str = "", nota: str = "") -> Corte:
    """Último periodo de una tabla territorial -> Corte. El territorio es el último trozo del nombre
    de la serie ("Tasa de paro de la población. Ambos sexos. Granada" -> "Granada")."""
    datos, url = ine_tabla(tabla, 1)
    valores, total, per = {}, None, None
    for s in datos:
        partes = _partes(s["Nombre"])
        if not _coincide(filtro_nombre, partes):
            continue
        d = max(s["Data"], key=lambda x: _periodo_ine(x)[1])
        if d.get("Valor") is None:
            continue
        per = _periodo_ine(d)
        terr = _territorio(partes)
        if total_contiene and total_contiene.lower() in terr.lower():
            if total is not None:
                raise ValueError(f"Tabla {tabla}: el filtro {filtro_nombre} deja varias series para el total nacional "
                                 f"(hay que afinarlo). Ejemplo: {s['Nombre']}")
            total = float(d["Valor"])
        elif terr in valores:
            raise ValueError(f"Tabla {tabla}: el filtro {filtro_nombre} deja varias series para «{terr}» "
                             f"(hay que afinarlo). Ejemplo: {s['Nombre']}")
        else:
            valores[terr] = float(d["Valor"])
    if per is None:
        raise ValueError(f"Tabla {tabla}: ninguna serie coincide con {filtro_nombre}. Ejemplos de nombres: {_muestra_nombres(datos)}")
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


def ultimo_periodo_completo(trunc: str, hoy: date | None = None) -> date:
    """Primer periodo que todavía NO está completo: hoy (day), el mes en curso (month) o el año en curso (year).
    Los datos de ese periodo y posteriores son parciales o previsiones y no se guardan."""
    hoy = hoy or date.today()
    return {"day": hoy, "month": hoy.replace(day=1), "year": hoy.replace(month=1, day=1)}[trunc]


def redata_series(categoria: str, widget: str, inicio: date, fin: date, trunc: str,
                  id_base: str, unidad: str, decimales: int = 0, porcentaje: bool = False) -> list[Serie]:
    """Una Serie por cada componente del widget (p. ej. Solar fotovoltaica, Eólica, Nuclear…).
    - porcentaje=True: guarda el peso de cada componente sobre el total (campo 'percentage' de REData, × 100).
    - Nunca guarda el periodo en curso (día de hoy, mes en curso), que REData da incompleto."""
    if trunc == "month":
        inicio = inicio.replace(day=1)                    # un mes pedido a medias daría un total parcial
    elif trunc == "year":
        inicio = inicio.replace(month=1, day=1)
    corte = ultimo_periodo_completo(trunc)
    tramos, a = [], inicio
    paso = timedelta(days=365) if trunc in ("day", "month") else timedelta(days=365 * 30)   # REData rechaza rangos largos
    while a <= fin:
        b = min(fin, a + paso - timedelta(days=1))
        if trunc == "month" and b < fin and (b + timedelta(days=1)).day != 1:
            b = b.replace(day=1) - timedelta(days=1)      # que cada tramo acabe a final de mes
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
                dia = v["datetime"][:10]
                if date.fromisoformat(dia) >= corte:
                    continue
                if porcentaje:
                    if v.get("percentage") is None:
                        continue
                    acc[dia] = round(float(v["percentage"]) * 100, 4)
                else:
                    acc[dia] = float(v["value"])
    out = []
    for titulo, vals in acumulado.items():
        if not vals:
            continue
        ps = sorted(vals)
        slug = "".join(c for c in titulo.lower().replace(" ", "_") if c.isalnum() or c == "_")
        out.append(Serie(
            id=f"{id_base}.{slug}", nombre=titulo, unidad=unidad,
            frecuencia={"day": "D", "month": "M", "year": "A"}[trunc],
            periodos=ps, valores=[vals[p] for p in ps],
            origen=Origen("REE (REData)", f"{categoria}/{widget}", titulo + (" (% del total)" if porcentaje else ""),
                          urls[-1], "", ahora_iso(),
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
# Días máximos entre el INICIO del último periodo y hoy (duración del periodo + retraso habitual de publicación)
RETRASO_MAXIMO_DIAS = {"D": 7, "M": 100, "T": 270, "A": 550}


def esta_congelada(serie: Serie, hoy: date | None = None) -> bool:
    hoy = hoy or date.today()
    ultimo = date.fromisoformat(serie.periodos[-1])
    return (hoy - ultimo).days > RETRASO_MAXIMO_DIAS.get(serie.frecuencia, 400)


def ine_buscar_tabla(operacion: str, contiene: str, operacion_nombre: str = "") -> list[int]:
    """Ids de las tablas de una operación del INE cuyo nombre contiene el texto, de la más nueva a la más antigua.
    La operación se busca por su código corto; si se da 'operacion_nombre' o el código falla, se busca en
    OPERACIONES_DISPONIBLES por nombre, código o código IOE."""
    tablas = None
    if not operacion_nombre:
        try:
            tablas = json.loads(_get(f"{INE_BASE}/TABLAS_OPERACION/{operacion}", reintentos=1))
        except RuntimeError:
            tablas = None
    if tablas is None:
        ops = json.loads(_get(f"{INE_BASE}/OPERACIONES_DISPONIBLES"))
        op = None
        if operacion_nombre:
            op = next((o for o in ops if operacion_nombre.lower() in str(o.get("Nombre", "")).lower()), None)
        if op is None:
            op = next((o for o in ops if operacion.upper() in (str(o.get("Codigo", "")).upper(), str(o.get("Cod_IOE", "")).upper())), None)
        if op is None:
            parecidas = [o.get("Nombre") for o in ops if (operacion_nombre or operacion).split()[0].lower() in str(o.get("Nombre", "")).lower()][:8]
            raise ValueError(f"INE: operación «{operacion_nombre or operacion}» no encontrada. Parecidas: {parecidas}")
        tablas = json.loads(_get(f"{INE_BASE}/TABLAS_OPERACION/{op['Id']}"))
    cand = [t for t in tablas if contiene.lower() in t["Nombre"].lower()]
    if not cand:
        palabra = contiene.split()[0].lower()
        parecidas = [f"{t['Id']}: {t['Nombre']}" for t in tablas if palabra in t["Nombre"].lower()][:10]
        raise ValueError(f"INE {operacion}: ninguna tabla contiene «{contiene}». Parecidas: {parecidas}")
    return [t["Id"] for t in sorted(cand, key=lambda t: t["Id"], reverse=True)]   # de la más nueva a la más antigua
