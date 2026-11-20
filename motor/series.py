"""Estructuras de datos del motor y almacén del histórico.

Tres piezas:
- Serie: una variable a lo largo del tiempo (p. ej. tasa de paro nacional por trimestre).
- Corte: una variable en un mismo periodo para muchos territorios (p. ej. paro por provincias en 3T 2026).
- Afirmacion: cada cifra que puede acabar en una publicación, con su trazabilidad completa.
  Ninguna cifra llega a la IA ni a las imágenes si no viene de una Afirmacion.
"""
from __future__ import annotations
import csv
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

TIPOS = ("DATO OFICIAL", "CÁLCULO DERIVADO", "COMPARACIÓN", "ESTIMACIÓN")


@dataclass
class Origen:
    fuente: str            # "INE", "REE (REData)", "BCE", "AEMET"
    dataset: str           # operación/tabla/widget/dataflow, p. ej. "EPA · tabla 65349"
    indicador: str         # nombre original del indicador en la fuente
    url: str               # consulta exacta que devolvió el dato
    codigo: str = ""       # código de serie en la fuente (COD del INE, key SDMX del BCE…)
    descargado: str = ""   # marca de tiempo ISO de la descarga
    licencia: str = ""


@dataclass
class Serie:
    id: str                       # id interno, p. ej. "ine.epa.paro.total"
    nombre: str                   # nombre corto en llano
    unidad: str                   # "%", "personas", "GWh", "€"…
    frecuencia: str               # "D", "M", "T", "A"
    periodos: list[str]           # "2026-07-01" (inicio del periodo), ordenados
    valores: list[float]
    origen: Origen
    decimales: int = 1
    polaridad: int = 0            # +1 si subir es "bueno" en lenguaje común, −1 si es "malo", 0 neutro (solo para elegir verbos neutros, nunca valoraciones)
    territorio: str = "España"

    def ultimo(self):
        return self.periodos[-1], self.valores[-1]


@dataclass
class Corte:
    id: str
    nombre: str
    unidad: str
    periodo: str                  # etiqueta legible: "3T 2026"
    fecha: str                    # inicio del periodo ISO
    nivel: str                    # "provincia", "ccaa", "municipio", "estacion"
    valores: dict[str, float]     # territorio -> valor (nombres tal como vienen de la fuente)
    total: float | None           # valor nacional publicado por la fuente (no calculado)
    origen: Origen
    decimales: int = 2
    nota_metodologica: str = ""   # p. ej. error de muestreo de la EPA en provincias


@dataclass
class Afirmacion:
    """Ficha trazable de una cifra. Es lo único que la redacción puede usar."""
    id: str
    tipo: str                     # uno de TIPOS
    texto_valor: str              # cómo se escribe la cifra en la publicación ("10,18 %")
    valor: float                  # valor numérico mostrado
    unidad: str
    descripcion: str              # qué es, en llano ("Tasa de paro en España")
    periodo: str                  # "3T 2026"
    origenes: list[dict] = field(default_factory=list)   # Origen(es) + valor original de cada uno
    calculo: str = ""             # fórmula legible si es CÁLCULO DERIVADO o COMPARACIÓN
    aproximado: bool = False

    def __post_init__(self):
        assert self.tipo in TIPOS, self.tipo
        if self.tipo != "DATO OFICIAL":
            assert self.calculo, f"{self.id}: una cifra que no es DATO OFICIAL necesita 'calculo'"


def origen_con_valor(origen: Origen, valor_original: float, periodo: str, territorio: str = "") -> dict:
    d = asdict(origen)
    d.update({"valor_original": valor_original, "periodo_original": periodo, "territorio": territorio})
    return d


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Almacén: un CSV por serie en datos/historico/<id>.csv + metadatos JSON.
# Va dentro del repositorio para que GitHub guarde el histórico y cada cambio
# quede registrado (también sirve para detectar revisiones de datos ya publicados).
# ---------------------------------------------------------------------------
class Almacen:
    def __init__(self, carpeta: str):
        self.carpeta = carpeta
        os.makedirs(carpeta, exist_ok=True)

    def _ruta(self, sid: str, ext: str) -> str:
        return os.path.join(self.carpeta, f"{sid}.{ext}")

    def leer(self, sid: str) -> dict[str, float]:
        ruta = self._ruta(sid, "csv")
        if not os.path.exists(ruta):
            return {}
        with open(ruta, newline="", encoding="utf-8") as f:
            return {r["periodo"]: float(r["valor"]) for r in csv.DictReader(f)}

    def guardar(self, serie: Serie) -> dict:
        """Fusiona con lo guardado. Devuelve qué ha cambiado: periodos nuevos y revisiones."""
        previo = self.leer(serie.id)
        nuevos = [p for p in serie.periodos if p not in previo]
        revisados = [(p, previo[p], v) for p, v in zip(serie.periodos, serie.valores)
                     if p in previo and abs(previo[p] - v) > 1e-9]
        fusion = dict(previo)
        fusion.update(dict(zip(serie.periodos, serie.valores)))
        with open(self._ruta(serie.id, "csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["periodo", "valor"])
            for p in sorted(fusion):
                w.writerow([p, fusion[p]])
        meta = asdict(serie)
        meta.pop("periodos"); meta.pop("valores")
        meta["actualizado"] = ahora_iso()
        with open(self._ruta(serie.id, "json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return {"nuevos": nuevos, "revisados": revisados}

    def borrar_desde(self, sid: str, periodo: str) -> int:
        """Quita del histórico los periodos iguales o posteriores a 'periodo' (datos parciales guardados por error).
        Devuelve cuántos ha quitado."""
        datos = self.leer(sid)
        quitar = [p for p in datos if p >= periodo]
        if not quitar:
            return 0
        with open(self._ruta(sid, "csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["periodo", "valor"])
            for p in sorted(datos):
                if p < periodo:
                    w.writerow([p, datos[p]])
        return len(quitar)

    def serie_completa(self, serie: Serie) -> Serie:
        datos = self.leer(serie.id)
        datos.update(dict(zip(serie.periodos, serie.valores)))
        ps = sorted(datos)
        return Serie(**{**asdict(serie), "periodos": ps, "valores": [datos[p] for p in ps],
                        "origen": serie.origen})
