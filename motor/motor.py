"""Puntuación, selección y salida de candidatos para n8n.

puntuación = peso del detector × intensidad × interés del indicador × frescura × novedad

- peso del detector: lo que suele interesar más (récord histórico > hito > outlier > cambio…).
- interés del indicador: 1 (técnico) a 3 (le importa a todo el mundo: paro, precios, vivienda,
  luz, población, calor). Se fija en config/indicadores.json.
- frescura: 1 si el dato es de esta actualización; las piezas de reserva (atemporales) valen 0,6.
- novedad: penaliza repetir indicador o formato publicados en los últimos días (datos/publicados.json).
"""
from __future__ import annotations
import json
import os
from dataclasses import asdict
from datetime import date, timedelta

from .detectores import Insight

PESO_DETECTOR = {
    "máximo_histórico": 1.0, "mínimo_histórico": 1.0, "hito_redondo": 0.95,
    "máximo_20_años": 0.85, "mínimo_20_años": 0.85, "hoy_vs_media": 0.8,
    "outlier_territorial": 0.75, "brecha_grupos": 0.7, "reparto_territorial": 0.7,
    "máximo_10_años": 0.7, "mínimo_10_años": 0.7, "cruce_variables": 0.7,
    "cambio_interanual": 0.65, "cambio_tendencia": 0.65, "top_bottom": 0.6,
    "cambio_periodo_anterior": 0.55, "tendencia_sostenida": 0.55,
    "máximo_5_años": 0.5, "mínimo_5_años": 0.5, "comparacion_temporal": 0.5,
}
UMBRAL_NOTICIA = 0.45      # por debajo no se propone como novedad
MAX_DIA = 10               # carruseles de novedad propuestos al día (decisión de Jordi, 13/11/2026)
DIAS_NOVEDAD = 10          # ventana para penalizar repeticiones


def puntuar(ins: Insight, interes: float, frescura: float, publicados: list[dict]) -> float:
    peso = PESO_DETECTOR.get(ins.detector, 0.5)
    hoy = date.today()
    recientes = [p for p in publicados if date.fromisoformat(p["fecha"]) >= hoy - timedelta(days=DIAS_NOVEDAD)]
    novedad = 1.0
    if any(p["fuente_id"] == ins.fuente_id for p in recientes):
        novedad *= 0.4
    if any(p["formato"] == ins.formato for p in recientes[-3:]):
        novedad *= 0.8
    if any(p["id"] == ins.id for p in publicados):
        novedad = 0.0                                   # nunca dos veces el mismo insight
    ins.puntuacion = round(peso * ins.intensidad * (interes / 3) * frescura * novedad, 3)
    return ins.puntuacion


def _raiz(fuente_id: str) -> str:
    """Mismo origen de datos: quita los sufijos .a / .b de los cortes de brecha (mujeres/hombres…)."""
    f = fuente_id.split("|")[0]
    return f[:-2] if f.endswith((".a", ".b")) else f


def agrupar_en_carruseles(insights: list[Insight]) -> list[list[Insight]]:
    """Un carrusel = un insight principal + los secundarios de la misma fuente que aportan contexto
    (p. ej. MAPA principal + TOP/BOTTOM + brecha por sexo del mismo corte). Máximo 3 por carrusel."""
    usados, grupos = set(), []
    for ins in sorted(insights, key=lambda i: i.puntuacion, reverse=True):
        if ins.id in usados:
            continue
        raiz = _raiz(ins.fuente_id)
        grupo = [ins]
        usados.add(ins.id)
        for otro in sorted(insights, key=lambda i: i.puntuacion, reverse=True):
            if otro.id in usados or len(grupo) >= 3:
                continue
            if _raiz(otro.fuente_id) == raiz and otro.formato != ins.formato:
                grupo.append(otro)
                usados.add(otro.id)
        grupos.append(grupo)
    return grupos


def seleccionar(insights: list[Insight], reserva: list[Insight]) -> dict:
    """Devuelve el plan del día: novedades (máx MAX_DIA) o, si no hay, 1 pieza de reserva."""
    grupos = agrupar_en_carruseles(insights)
    novedades = [g for g in grupos if g[0].puntuacion >= UMBRAL_NOTICIA][:MAX_DIA]
    descartados = [{"id": g[0].id, "puntuacion": g[0].puntuacion, "titular_base": g[0].titular_base}
                   for g in grupos if g not in novedades][:10]
    plan = {"tipo": "novedad" if novedades else "reserva", "carruseles": [], "descartados": descartados}
    elegidos = novedades or agrupar_en_carruseles(reserva)[:1]
    for g in elegidos:
        plan["carruseles"].append({
            "principal": g[0].to_dict(), "secundarios": [x.to_dict() for x in g[1:]],
            "formato": g[0].formato, "puntuacion": g[0].puntuacion})
    return plan


def cargar_publicados(ruta: str) -> list[dict]:
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)
