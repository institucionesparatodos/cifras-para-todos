"""Insight Engine: detectores estadísticos. Todo es código determinista, sin IA.

Cada detector devuelve Insights con:
- detector y formato propuesto (DATO, RÉCORD, RANKING, MAPA, COMPARACIÓN TEMPORAL, EXTREMOS,
  CURIOSIDAD, ¿SABÍAS QUE…?, HOY VS MEDIA HISTÓRICA, TOP / BOTTOM);
- intensidad (0-1): lo "sorprendente" que es estadísticamente;
- afirmaciones: TODAS las cifras que se pueden usar, con su trazabilidad y su tipo
  (DATO OFICIAL, CÁLCULO DERIVADO, COMPARACIÓN, ESTIMACIÓN);
- visual: tipo de gráfico y datos ya preparados por el código.
"""
from __future__ import annotations
import math
import statistics as st
from dataclasses import dataclass, field, asdict
from datetime import date

from .series import Serie, Corte, Afirmacion, origen_con_valor
from . import formato as fmt

ORDINAL_T = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto"}
VENTANAS_ANYOS = (5, 10, 20)


@dataclass
class Insight:
    id: str
    detector: str
    formato: str
    intensidad: float
    fuente_id: str                       # id de la serie o del corte
    titular_base: str                    # frase plana generada por código (la IA la reescribe)
    afirmaciones: list[Afirmacion]
    visual: dict
    contexto: dict = field(default_factory=dict)
    tema: str = ""                       # "empleo", "precios", "energía"…
    puntuacion: float = 0.0              # la calcula motor.puntuar()

    def to_dict(self):
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def etiqueta_periodo(iso: str, frec: str, larga: bool = False) -> str:
    a, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    if frec == "D":
        return fmt.fecha_larga(iso)
    if frec == "M":
        return f"{fmt.MESES[m - 1]} de {a}"
    if frec == "T":
        t = (m - 1) // 3 + 1
        return f"{ORDINAL_T[t]} trimestre de {a}" if larga else f"{t}T {a}"
    return str(a)


def periodos_por_anyo(frec: str) -> int:
    return {"D": 365, "M": 12, "T": 4, "A": 1}.get(frec, 1)


def af_dato(serie: Serie, i: int, aid: str, descripcion: str | None = None) -> Afirmacion:
    p, v = serie.periodos[i], serie.valores[i]
    return Afirmacion(
        id=aid, tipo="DATO OFICIAL", texto_valor=fmt.con_unidad(v, serie.unidad, serie.decimales),
        valor=v, unidad=serie.unidad, descripcion=descripcion or f"{serie.nombre} ({serie.territorio})",
        periodo=etiqueta_periodo(p, serie.frecuencia),
        origenes=[origen_con_valor(serie.origen, v, p, serie.territorio)])


def af_calculo(aid: str, tipo: str, valor: float, unidad: str, decimales: int, descripcion: str,
               periodo: str, calculo: str, origenes: list[dict], aproximado=False,
               texto_valor: str | None = None) -> Afirmacion:
    if texto_valor is None:
        if unidad == "puntos":
            texto_valor = fmt.puntos(valor, decimales)
        else:
            texto_valor = fmt.con_unidad(valor, unidad, decimales)
    return Afirmacion(id=aid, tipo=tipo, texto_valor=texto_valor, valor=valor, unidad=unidad,
                      descripcion=descripcion, periodo=periodo, origenes=origenes,
                      calculo=calculo, aproximado=aproximado)


def sigmoide(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def mad_z(valores: list[float]) -> list[float]:
    """z robusto (mediana y MAD): no se deja engañar por los propios outliers."""
    med = st.median(valores)
    mad = st.median([abs(v - med) for v in valores]) or 1e-9
    return [(v - med) / (1.4826 * mad) for v in valores]


# ---------------------------------------------------------------------------
# 1-3. Máximos / mínimos históricos y de 5, 10, 20 años
# ---------------------------------------------------------------------------
def det_records(s: Serie) -> list[Insight]:
    if len(s.valores) < 8:
        return []
    out = []
    p_ult, v_ult = s.ultimo()
    anterior = s.valores[:-1]
    for signo, nombre in ((1, "máximo"), (-1, "mínimo")):
        # Último periodo anterior en el que el valor fue igual o "más extremo"
        idx_previo = None
        for i in range(len(anterior) - 1, -1, -1):
            if signo * anterior[i] >= signo * v_ult:
                idx_previo = i
                break
        if idx_previo == len(anterior) - 1:
            continue                                   # el anterior ya era igual o más extremo
        inicio_serie = s.periodos[0]
        if idx_previo is None:
            anyos = (date.fromisoformat(p_ult) - date.fromisoformat(inicio_serie)).days / 365.25
            alcance, desde = "histórico", inicio_serie
            intensidad = min(1.0, 0.6 + anyos / 50)
            formato = "RÉCORD"
        else:
            anyos = (date.fromisoformat(p_ult) - date.fromisoformat(s.periodos[idx_previo])).days / 365.25
            ventana = max([w for w in VENTANAS_ANYOS if anyos >= w], default=None)
            if ventana is None:
                continue
            alcance, desde = f"{ventana} años", s.periodos[idx_previo]
            intensidad = {5: 0.35, 10: 0.5, 20: 0.7}[ventana]
            formato = "DATO"
        afs = [af_dato(s, -1, "a1")]
        if idx_previo is not None:
            afs.append(af_dato(s, idx_previo, "a2", f"{s.nombre}: último valor igual o más {'alto' if signo > 0 else 'bajo'}"))
        texto_desde = (f"desde que hay registros ({etiqueta_periodo(inicio_serie, s.frecuencia)})"
                       if idx_previo is None else f"desde {etiqueta_periodo(desde, s.frecuencia, True)}")
        out.append(Insight(
            id=f"{s.id}.{nombre}.{p_ult}", detector=f"{nombre}_{alcance.replace(' ', '_')}",
            formato=formato, intensidad=intensidad, fuente_id=s.id,
            titular_base=f"{s.nombre}: {afs[0].texto_valor} en {etiqueta_periodo(p_ult, s.frecuencia, True)}, "
                         f"el valor más {'alto' if signo > 0 else 'bajo'} {texto_desde}.",
            afirmaciones=afs,
            visual={"tipo": "lineas", "serie": _tramo(s, 20), "destacar": p_ult},
            contexto={"alcance": alcance, "desde": desde}))
    return out


def _tramo(s: Serie, anyos: int) -> dict:
    n = periodos_por_anyo(s.frecuencia) * anyos
    return {"periodos": s.periodos[-n:], "valores": s.valores[-n:], "unidad": s.unidad,
            "decimales": s.decimales, "frecuencia": s.frecuencia}


# ---------------------------------------------------------------------------
# 4-5. Cambio respecto al periodo anterior e interanual (comparado con su propia volatilidad)
# ---------------------------------------------------------------------------
def det_cambios(s: Serie, z_min: float = 2.0) -> list[Insight]:
    out = []
    k = periodos_por_anyo(s.frecuencia)
    for nombre, lag in (("periodo_anterior", 1), ("interanual", k)):
        if len(s.valores) < lag + 12:
            continue
        difs = [s.valores[i] - s.valores[i - lag] for i in range(lag, len(s.valores))]
        historial, ultimo = difs[:-1][-60:], difs[-1]
        sd = st.pstdev(historial) or 1e-9
        z = (ultimo - st.mean(historial)) / sd
        if abs(z) < z_min:
            continue
        v0, v1 = s.valores[-1 - lag], s.valores[-1]
        relativo = s.unidad not in ("%", "puntos", "°C", "€/MWh") and v0 != 0
        if relativo:
            var = (v1 - v0) / abs(v0) * 100
            af_var = af_calculo("a3", "CÁLCULO DERIVADO", var, "%", 1, f"Variación {nombre.replace('_', ' ')}",
                                etiqueta_periodo(s.periodos[-1], s.frecuencia),
                                f"({fmt.num(v1, s.decimales)} − {fmt.num(v0, s.decimales)}) / {fmt.num(v0, s.decimales)} × 100",
                                [origen_con_valor(s.origen, v1, s.periodos[-1]), origen_con_valor(s.origen, v0, s.periodos[-1 - lag])])
        else:
            var = v1 - v0
            af_var = af_calculo("a3", "CÁLCULO DERIVADO", var, "puntos" if s.unidad == "%" else s.unidad, s.decimales,
                                f"Diferencia {nombre.replace('_', ' ')}", etiqueta_periodo(s.periodos[-1], s.frecuencia),
                                f"{fmt.num(v1, s.decimales)} − {fmt.num(v0, s.decimales)}",
                                [origen_con_valor(s.origen, v1, s.periodos[-1]), origen_con_valor(s.origen, v0, s.periodos[-1 - lag])])
        out.append(Insight(
            id=f"{s.id}.{nombre}.{s.periodos[-1]}", detector=f"cambio_{nombre}", formato="DATO",
            intensidad=min(1.0, sigmoide(abs(z) - 2.5)), fuente_id=s.id,
            titular_base=f"{s.nombre} {'sube' if var > 0 else 'baja'} {af_var.texto_valor} "
                         f"({'respecto al periodo anterior' if lag == 1 else 'en un año'}).",
            afirmaciones=[af_dato(s, -1, "a1"), af_dato(s, -1 - lag, "a2"), af_var],
            visual={"tipo": "barras" if s.frecuencia in ("M", "T") else "lineas", "serie": _tramo(s, 5),
                    "destacar": s.periodos[-1]},
            contexto={"z": round(z, 2), "lag": lag}))
    return out


# ---------------------------------------------------------------------------
# 6-7. Tendencias sostenidas y cambios de tendencia
# ---------------------------------------------------------------------------
RACHA_MIN = {"D": 10, "M": 6, "T": 4, "A": 4}


def det_tendencias(s: Serie) -> list[Insight]:
    if len(s.valores) < 10:
        return []
    difs = [b - a for a, b in zip(s.valores, s.valores[1:])]
    signo = lambda x: (x > 0) - (x < 0)
    ult = signo(difs[-1])
    racha = 0
    for d in reversed(difs):
        if signo(d) == ult and ult != 0:
            racha += 1
        else:
            break
    out = []
    minimo = RACHA_MIN.get(s.frecuencia, 4)
    if racha >= minimo:
        i0 = -1 - racha
        out.append(Insight(
            id=f"{s.id}.racha.{s.periodos[-1]}", detector="tendencia_sostenida", formato="DATO",
            intensidad=min(1.0, 0.3 + 0.07 * (racha - minimo)), fuente_id=s.id,
            titular_base=f"{s.nombre} lleva {racha} periodos seguidos {'subiendo' if ult > 0 else 'bajando'}.",
            afirmaciones=[af_dato(s, -1, "a1"), af_dato(s, i0, "a2"),
                          af_calculo("a3", "CÁLCULO DERIVADO", racha, "periodos", 0, "Periodos consecutivos en la misma dirección",
                                     etiqueta_periodo(s.periodos[-1], s.frecuencia), "recuento de variaciones consecutivas del mismo signo",
                                     [origen_con_valor(s.origen, s.valores[-1], s.periodos[-1])])],
            visual={"tipo": "lineas", "serie": _tramo(s, 5), "destacar_desde": s.periodos[i0]}))
    # Cambio de tendencia: la racha anterior era larga y en sentido contrario
    if racha <= 2 and len(difs) > racha + minimo:
        previo = difs[:-racha]
        sp = signo(previo[-1])
        r2 = 0
        for d in reversed(previo):
            if signo(d) == sp and sp != 0:
                r2 += 1
            else:
                break
        if r2 >= minimo and sp == -ult:
            out.append(Insight(
                id=f"{s.id}.giro.{s.periodos[-1]}", detector="cambio_tendencia", formato="DATO",
                intensidad=min(1.0, 0.35 + 0.05 * (r2 - minimo)), fuente_id=s.id,
                titular_base=f"{s.nombre} {'vuelve a subir' if ult > 0 else 'vuelve a bajar'} tras {r2} periodos "
                             f"{'bajando' if ult > 0 else 'subiendo'}.",
                afirmaciones=[af_dato(s, -1, "a1"), af_dato(s, -1 - racha, "a2")],
                visual={"tipo": "lineas", "serie": _tramo(s, 5), "destacar": s.periodos[-1]},
                contexto={"racha_previa": r2}))
    return out


# ---------------------------------------------------------------------------
# Hitos redondos ("supera por primera vez los 50 millones")
# ---------------------------------------------------------------------------
def det_hito(s: Serie) -> list[Insight]:
    if len(s.valores) < 3:
        return []
    v0, v1 = max(s.valores[:-1]), s.valores[-1]
    if v1 <= v0 or v1 <= 0:
        return []
    paso = 10 ** int(math.floor(math.log10(v1)))     # 49,6 M -> 10 M; usamos 1/2 y 1/10 del orden
    for escalon in (paso, paso / 2, paso / 10):
        umbral = math.floor(v1 / escalon) * escalon
        if v0 < umbral <= v1 and umbral > 0:
            return [Insight(
                id=f"{s.id}.hito.{s.periodos[-1]}", detector="hito_redondo", formato="DATO",
                intensidad={paso: 0.95, paso / 2: 0.75, paso / 10: 0.45}[escalon], fuente_id=s.id,
                titular_base=f"{s.nombre} supera por primera vez {fmt.con_unidad(umbral, s.unidad, 0)}.",
                afirmaciones=[af_dato(s, -1, "a1"),
                              af_calculo("a2", "COMPARACIÓN", umbral, s.unidad, 0, "Umbral redondo superado por primera vez",
                                         etiqueta_periodo(s.periodos[-1], s.frecuencia),
                                         f"máximo anterior {fmt.num(v0, s.decimales)} < {fmt.num(umbral, 0)} ≤ {fmt.num(v1, s.decimales)}",
                                         [origen_con_valor(s.origen, v1, s.periodos[-1])])],
                visual={"tipo": "contador", "valor": v1, "unidad": s.unidad, "serie": _tramo(s, 20)})]
    return []


# ---------------------------------------------------------------------------
# 9 (AEMET, demanda). Hoy frente a la media histórica del mismo momento del año
# ---------------------------------------------------------------------------
def det_anomalia_estacional(s: Serie, anyos_ref: int = 30, ventana_dias: int = 7, z_min: float = 1.8,
                            normal_oficial: float | None = None, origen_normal: dict | None = None) -> list[Insight]:
    """Si la fuente publica un valor normal oficial (p. ej. normales 1991-2020 de AEMET) se usa ese
    (ESTIMACIÓN no; es DATO OFICIAL de la fuente). Si no, se calcula la media de los mismos días de
    años anteriores y se marca como CÁLCULO DERIVADO."""
    p_ult, v_ult = s.ultimo()
    d_ult = date.fromisoformat(p_ult)
    refs = []
    for p, v in zip(s.periodos[:-1], s.valores[:-1]):
        d = date.fromisoformat(p)
        if d.year < d_ult.year and d_ult.year - d.year <= anyos_ref:
            if s.frecuencia == "D":
                dd = abs((d.replace(year=2001) - d_ult.replace(year=2001)).days)
                if min(dd, 365 - dd) <= ventana_dias:
                    refs.append(v)
            elif d.month == d_ult.month:
                refs.append(v)
    if len(refs) < 10 and normal_oficial is None:
        return []
    media = normal_oficial if normal_oficial is not None else st.mean(refs)
    sd = st.pstdev(refs) if len(refs) >= 10 else None
    z = (v_ult - media) / sd if sd else None
    if z is not None and abs(z) < z_min:
        return []
    dif = v_ult - media
    af_media = (Afirmacion("a2", "DATO OFICIAL", fmt.con_unidad(media, s.unidad, s.decimales), media, s.unidad,
                           "Valor normal publicado por la fuente", "periodo de referencia oficial",
                           [origen_normal or {}])
                if normal_oficial is not None else
                af_calculo("a2", "CÁLCULO DERIVADO", media, s.unidad, s.decimales,
                           f"Media de las mismas fechas en los {len(refs)} registros de los últimos {anyos_ref} años",
                           etiqueta_periodo(p_ult, s.frecuencia), "media aritmética de los valores de referencia",
                           [origen_con_valor(s.origen, v_ult, p_ult, s.territorio)]))
    return [Insight(
        id=f"{s.id}.anomalia.{p_ult}", detector="hoy_vs_media", formato="HOY VS MEDIA HISTÓRICA",
        intensidad=min(1.0, sigmoide(abs(z or 3) - 2)), fuente_id=s.id,
        titular_base=f"{s.territorio}: {fmt.con_unidad(abs(dif), s.unidad, s.decimales)} "
                     f"{'por encima' if dif > 0 else 'por debajo'} de lo habitual para esta fecha.",
        afirmaciones=[af_dato(s, -1, "a1"), af_media,
                      af_calculo("a3", "COMPARACIÓN", dif, s.unidad, s.decimales, "Diferencia con lo habitual",
                                 etiqueta_periodo(p_ult, s.frecuencia), f"{fmt.num(v_ult, s.decimales)} − {fmt.num(media, s.decimales)}",
                                 [origen_con_valor(s.origen, v_ult, p_ult, s.territorio)])],
        visual={"tipo": "hoy_vs_media", "hoy": v_ult, "media": media, "unidad": s.unidad,
                "banda": [media - (sd or 0), media + (sd or 0)]},
        contexto={"z": z and round(z, 2), "n_ref": len(refs)})]


# ---------------------------------------------------------------------------
# 5 (formato). Comparación temporal: hoy frente a hace 20 años (pieza atemporal de reserva)
# ---------------------------------------------------------------------------
def det_comparacion_temporal(s: Serie, anyos: int = 20) -> list[Insight]:
    k = periodos_por_anyo(s.frecuencia) * anyos
    if len(s.valores) <= k:
        return []
    v0, v1 = s.valores[-1 - k], s.valores[-1]
    if v0 == 0:
        return []
    var = (v1 - v0) / abs(v0) * 100
    return [Insight(
        id=f"{s.id}.hace{anyos}.{s.periodos[-1]}", detector="comparacion_temporal", formato="COMPARACIÓN TEMPORAL",
        intensidad=min(1.0, abs(var) / 100), fuente_id=s.id,
        titular_base=f"{s.nombre}: {etiqueta_periodo(s.periodos[-1 - k], s.frecuencia)} frente a {etiqueta_periodo(s.periodos[-1], s.frecuencia)}.",
        afirmaciones=[af_dato(s, -1, "a1"), af_dato(s, -1 - k, "a2"),
                      af_calculo("a3", "CÁLCULO DERIVADO", var, "%", 0, f"Variación en {anyos} años",
                                 etiqueta_periodo(s.periodos[-1], s.frecuencia),
                                 f"({fmt.num(v1, s.decimales)} − {fmt.num(v0, s.decimales)}) / {fmt.num(v0, s.decimales)} × 100",
                                 [origen_con_valor(s.origen, v1, s.periodos[-1]), origen_con_valor(s.origen, v0, s.periodos[-1 - k])])],
        visual={"tipo": "comparacion", "antes": {"periodo": s.periodos[-1 - k], "valor": v0},
                "ahora": {"periodo": s.periodos[-1], "valor": v1}, "unidad": s.unidad})]


# ---------------------------------------------------------------------------
# 8-13. Cortes territoriales: rankings, mapa, top/bottom, outliers, distancia a la media
# ---------------------------------------------------------------------------
def det_corte(c: Corte, provincias_cfg: dict | None = None) -> list[Insight]:
    items = sorted(c.valores.items(), key=lambda kv: kv[1], reverse=True)
    n = len(items)
    if n < 5:
        return []
    vals = [v for _, v in items]
    out = []
    ref = c.total if c.total is not None else None
    corto = (lambda t: provincias_cfg.get(t, {}).get("corto", t)) if provincias_cfg else (lambda t: t)

    def af_terr(aid, terr, v):
        return Afirmacion(aid, "DATO OFICIAL", fmt.con_unidad(v, c.unidad, c.decimales), v, c.unidad,
                          f"{c.nombre} · {corto(terr)}", c.periodo,
                          [origen_con_valor(c.origen, v, c.fecha, terr)])

    afs = []
    if ref is not None:
        afs.append(Afirmacion("t0", "DATO OFICIAL", fmt.con_unidad(ref, c.unidad, c.decimales), ref, c.unidad,
                              f"{c.nombre} · total nacional", c.periodo,
                              [origen_con_valor(c.origen, ref, c.fecha, "Total Nacional")]))
    for i, (t, v) in enumerate(items):
        afs.append(af_terr(f"t{i + 1}", t, v))
    (t_max, v_max), (t_min, v_min) = items[0], items[-1]
    ratio = v_max / v_min if v_min > 0 else None
    if ratio:
        afs.append(af_calculo("r1", "COMPARACIÓN", ratio, "veces", 1, f"{corto(t_max)} frente a {corto(t_min)}",
                              c.periodo, f"{fmt.num(v_max, c.decimales)} / {fmt.num(v_min, c.decimales)}",
                              [origen_con_valor(c.origen, v_max, c.fecha, t_max), origen_con_valor(c.origen, v_min, c.fecha, t_min)],
                              texto_valor=f"{fmt.num(ratio, 1)} veces"))
    afs.append(af_calculo("r2", "COMPARACIÓN", v_max - v_min, "puntos" if c.unidad == "%" else c.unidad, c.decimales,
                          f"Distancia entre {corto(t_max)} y {corto(t_min)}", c.periodo,
                          f"{fmt.num(v_max, c.decimales)} − {fmt.num(v_min, c.decimales)}",
                          [origen_con_valor(c.origen, v_max, c.fecha, t_max), origen_con_valor(c.origen, v_min, c.fecha, t_min)]))
    dispersion = (v_max - v_min) / (abs(st.median(vals)) or 1)
    base = {"nivel": c.nivel, "valores": c.valores, "total": ref, "unidad": c.unidad, "decimales": c.decimales}
    # MAPA: muchos territorios y diferencias amplias
    if n >= 15:
        out.append(Insight(
            id=f"{c.id}.mapa.{c.fecha}", detector="reparto_territorial", formato="MAPA",
            intensidad=min(1.0, 0.3 + dispersion / 2), fuente_id=c.id,
            titular_base=f"{c.nombre} por {c.nivel}s: de {fmt.con_unidad(v_min, c.unidad, c.decimales)} en {corto(t_min)} "
                         f"a {fmt.con_unidad(v_max, c.unidad, c.decimales)} en {corto(t_max)}.",
            afirmaciones=afs, visual={"tipo": "mapa", **base}, contexto={"dispersion": round(dispersion, 2)}))
    # TOP / BOTTOM
    out.append(Insight(
        id=f"{c.id}.topbottom.{c.fecha}", detector="top_bottom", formato="TOP / BOTTOM",
        intensidad=min(1.0, 0.25 + dispersion / 2), fuente_id=c.id,
        titular_base=f"Las 5 {c.nivel}s con más y con menos {c.nombre.lower()}.",
        afirmaciones=afs, visual={"tipo": "top_bottom", "n": 5, **base}))
    # Outliers (z robusto)
    zs = dict(zip([t for t, _ in items], mad_z(vals)))
    raros = [(t, z) for t, z in zs.items() if abs(z) >= 3]
    for t, z in raros:
        v = c.valores[t]
        out.append(Insight(
            id=f"{c.id}.outlier.{t}.{c.fecha}", detector="outlier_territorial", formato="¿SABÍAS QUE…?",
            intensidad=min(1.0, sigmoide(abs(z) - 3) + 0.3), fuente_id=c.id,
            titular_base=f"{corto(t)} se sale de lo habitual: {fmt.con_unidad(v, c.unidad, c.decimales)}"
                         + (f" frente a {fmt.con_unidad(ref, c.unidad, c.decimales)} en el conjunto de España." if ref is not None else "."),
            afirmaciones=afs, visual={"tipo": "ranking", "destacar": t, **base}, contexto={"z_robusto": round(z, 2)}))
    return out


def det_brecha(a: Corte, b: Corte, etiqueta_a: str, etiqueta_b: str, provincias_cfg: dict | None = None,
               minimo_puntos: float = 5.0) -> list[Insight]:
    """Dos cortes del mismo indicador para dos grupos (p. ej. mujeres y hombres)."""
    comunes = [t for t in a.valores if t in b.valores]
    if not comunes:
        return []
    corto = (lambda t: provincias_cfg.get(t, {}).get("corto", t)) if provincias_cfg else (lambda t: t)
    brechas = sorted(((t, a.valores[t] - b.valores[t]) for t in comunes), key=lambda x: x[1], reverse=True)
    t_max, d_max = brechas[0]
    afs = []
    if a.total is not None and b.total is not None:
        afs += [Afirmacion("b1", "DATO OFICIAL", fmt.con_unidad(a.total, a.unidad, a.decimales), a.total, a.unidad,
                           f"{a.nombre} · {etiqueta_a} · total nacional", a.periodo, [origen_con_valor(a.origen, a.total, a.fecha, "Total Nacional")]),
                Afirmacion("b2", "DATO OFICIAL", fmt.con_unidad(b.total, b.unidad, b.decimales), b.total, b.unidad,
                           f"{b.nombre} · {etiqueta_b} · total nacional", b.periodo, [origen_con_valor(b.origen, b.total, b.fecha, "Total Nacional")]),
                af_calculo("b3", "COMPARACIÓN", a.total - b.total, "puntos", 2, f"Diferencia {etiqueta_a} − {etiqueta_b} (España)",
                           a.periodo, f"{fmt.num(a.total, 2)} − {fmt.num(b.total, 2)}",
                           [origen_con_valor(a.origen, a.total, a.fecha, "Total Nacional"), origen_con_valor(b.origen, b.total, b.fecha, "Total Nacional")])]
    afs += [Afirmacion("b4", "DATO OFICIAL", fmt.con_unidad(a.valores[t_max], a.unidad, a.decimales), a.valores[t_max], a.unidad,
                       f"{a.nombre} · {etiqueta_a} · {corto(t_max)}", a.periodo, [origen_con_valor(a.origen, a.valores[t_max], a.fecha, t_max)]),
            Afirmacion("b5", "DATO OFICIAL", fmt.con_unidad(b.valores[t_max], b.unidad, b.decimales), b.valores[t_max], b.unidad,
                       f"{b.nombre} · {etiqueta_b} · {corto(t_max)}", b.periodo, [origen_con_valor(b.origen, b.valores[t_max], b.fecha, t_max)]),
            af_calculo("b6", "COMPARACIÓN", d_max, "puntos", 2, f"Diferencia {etiqueta_a} − {etiqueta_b} en {corto(t_max)}",
                       a.periodo, f"{fmt.num(a.valores[t_max], 2)} − {fmt.num(b.valores[t_max], 2)}",
                       [origen_con_valor(a.origen, a.valores[t_max], a.fecha, t_max), origen_con_valor(b.origen, b.valores[t_max], b.fecha, t_max)])]
    n_mayor = sum(1 for _, d in brechas if d > 0)
    afs.append(af_calculo("b7", "CÁLCULO DERIVADO", n_mayor, "territorios", 0,
                          f"Territorios donde {etiqueta_a} supera a {etiqueta_b}", a.periodo,
                          "recuento de territorios con diferencia positiva",
                          [origen_con_valor(a.origen, 0, a.fecha, "todos")], texto_valor=f"{n_mayor} de {len(brechas)}"))
    if abs(d_max) < minimo_puntos:
        return []
    return [Insight(
        id=f"{a.id}.brecha.{a.fecha}", detector="brecha_grupos", formato="CURIOSIDAD",
        intensidad=min(1.0, 0.3 + abs(d_max) / 30), fuente_id=a.id,
        titular_base=f"{a.nombre}: {etiqueta_a} frente a {etiqueta_b}. La mayor diferencia está en {corto(t_max)}.",
        afirmaciones=afs,
        visual={"tipo": "comparacion_grupos", "a": etiqueta_a, "b": etiqueta_b,
                "total": [a.total, b.total], "destacado": [corto(t_max), a.valores[t_max], b.valores[t_max]],
                "unidad": a.unidad, "decimales": a.decimales})]


# ---------------------------------------------------------------------------
# 15. Cruces entre fuentes: relación estadística, nunca causalidad
# ---------------------------------------------------------------------------
def spearman(x: list[float], y: list[float]) -> float:
    def rangos(v):
        orden = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[orden[j + 1]] == v[orden[i]]:
                j += 1
            for k in range(i, j + 1):
                r[orden[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rangos(x), rangos(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) or 1e-9
    return num / den


def det_cruce(a: Serie, b: Serie, n_min: int = 24, rho_min: float = 0.6) -> list[Insight]:
    comunes = sorted(set(a.periodos) & set(b.periodos))
    if len(comunes) < n_min:
        return []
    va = dict(zip(a.periodos, a.valores)); vb = dict(zip(b.periodos, b.valores))
    x = [va[p] for p in comunes]; y = [vb[p] for p in comunes]
    # Se trabaja con variaciones (diferencias) para no confundir dos tendencias de fondo con una relación
    dx = [q - p for p, q in zip(x, x[1:])]; dy = [q - p for p, q in zip(y, y[1:])]
    rho = spearman(dx, dy)
    n = len(dx)
    t = rho * math.sqrt((n - 2) / max(1e-9, 1 - rho ** 2))
    if abs(rho) < rho_min or abs(t) < 2.6:                 # ~p<0,01 para n≥24
        return []
    return [Insight(
        id=f"cruce.{a.id}.{b.id}.{comunes[-1]}", detector="cruce_variables", formato="CURIOSIDAD",
        intensidad=min(1.0, abs(rho)), fuente_id=f"{a.id}|{b.id}",
        titular_base=f"{a.nombre} y {b.nombre} se mueven {'en la misma dirección' if rho > 0 else 'en direcciones opuestas'} "
                     f"durante el mismo periodo.",
        afirmaciones=[af_calculo("c1", "CÁLCULO DERIVADO", rho, "", 2, "Correlación de Spearman entre las variaciones",
                                 f"{comunes[0]} – {comunes[-1]}", f"Spearman sobre {n} variaciones consecutivas",
                                 [origen_con_valor(a.origen, x[-1], comunes[-1]), origen_con_valor(b.origen, y[-1], comunes[-1])])],
        visual={"tipo": "doble_linea", "a": {"nombre": a.nombre, "periodos": comunes, "valores": x, "unidad": a.unidad},
                "b": {"nombre": b.nombre, "periodos": comunes, "valores": y, "unidad": b.unidad}},
        contexto={"rho": round(rho, 3), "n": n, "aviso": "Relación estadística. No implica que una variable cause la otra."})]
