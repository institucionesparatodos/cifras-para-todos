"""e·sios (Red Eléctrica): precio de la electricidad. Sin IA: solo HTTP y parseo.

API: https://api.esios.ree.es/indicators/{id}?start_date&end_date&time_trunc&time_agg&geo_ids[]
Necesita un token personal (se pide a consultasios@ree.es) en el secreto ESIOS_TOKEN del repositorio.
Indicadores usados:
- 1001: PVPC 2.0TD, término de energía activa (precio de la tarifa regulada para hogares), €/MWh.
- 600: precio del mercado diario (mercado mayorista), €/MWh.
Los precios del mercado diario se fijan el día anterior: el día de hoy ya es un dato completo.
"""
from __future__ import annotations
import json
import os
import urllib.parse
from datetime import date, timedelta

from .series import Serie, Origen, ahora_iso
from . import fuentes as F

ESIOS_BASE = "https://api.esios.ree.es/indicators"
LICENCIA = "Datos de Red Eléctrica (e·sios), uso con cita de la fuente"


def consulta(indicador: int, inicio: date, fin: date, trunc: str, geo_id: int | None) -> tuple[dict, str]:
    token = os.environ.get("ESIOS_TOKEN")
    if not token:
        raise RuntimeError("Falta ESIOS_TOKEN")
    q = [("start_date", f"{inicio.isoformat()}T00:00"), ("end_date", f"{fin.isoformat()}T23:59"),
         ("time_trunc", trunc), ("time_agg", "average")]
    if geo_id is not None:
        q.append(("geo_ids[]", str(geo_id)))
    url = f"{ESIOS_BASE}/{indicador}?{urllib.parse.urlencode(q)}"
    js = json.loads(F._get(url, {"Accept": "application/json; application/vnd.esios-api-v1+json",
                                 "Content-Type": "application/json", "x-api-key": token}))
    return js, url


def serie(cfg: dict, inicio: date, hoy: date | None = None) -> Serie | None:
    """Serie diaria o mensual (media) de un indicador. No guarda el mes en curso ni días futuros.
    Devuelve None si en ese intervalo no hay nada que pedir (p. ej. el mes pasado ya estaba guardado)."""
    hoy = hoy or date.today()
    trunc = cfg.get("trunc", "day")
    if trunc == "month":
        inicio = inicio.replace(day=1)
        corte = hoy.replace(day=1)                         # el mes en curso está incompleto
    else:
        corte = hoy + timedelta(days=1)                    # hoy sí (precio fijado ayer); mañana no
    vals, urls, a = {}, [], inicio
    while a < corte:
        b = min(corte - timedelta(days=1), a + timedelta(days=364))
        js, url = consulta(cfg["indicador"], a, b, trunc, cfg.get("geo_id"))
        urls.append(url)
        for v in js.get("indicator", {}).get("values", []):
            if cfg.get("geo_id") is not None and v.get("geo_id") not in (None, cfg["geo_id"]):
                continue
            dia = str(v.get("datetime", ""))[:10]
            if not dia or date.fromisoformat(dia) >= corte or v.get("value") is None:
                continue
            vals[dia if trunc != "month" else dia[:8] + "01"] = round(float(v["value"]), 4)
        a = b + timedelta(days=1)
    if not vals:
        if a == inicio:                                    # no había ningún periodo completo que pedir
            return None
        raise ValueError(f"e·sios {cfg['indicador']}: sin datos entre {inicio} y {corte}")
    ps = sorted(vals)
    nombre_ind = cfg.get("nombre_fuente", f"Indicador {cfg['indicador']}")
    return Serie(id=cfg["id"], nombre=cfg["nombre"], unidad=cfg.get("unidad", "€/MWh"),
                 frecuencia="M" if trunc == "month" else "D", periodos=ps, valores=[vals[p] for p in ps],
                 origen=Origen("REE (e·sios)", f"e·sios · indicador {cfg['indicador']}", nombre_ind, urls[-1],
                               str(cfg["indicador"]), ahora_iso(), LICENCIA),
                 decimales=cfg.get("decimales", 2))
