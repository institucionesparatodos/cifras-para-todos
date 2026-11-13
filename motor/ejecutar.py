"""Ejecución diaria (GitHub Action "analizar"):
1. descarga cada indicador del catálogo y lo fusiona con el histórico (datos/historico/);
2. avisa de series congeladas o caídas de una fuente (no paran el día);
3. pasa los detectores sobre lo que ha cambiado (novedades) y sobre todo el histórico (reserva);
4. puntúa, agrupa en carruseles y escribe datos/plan/<fecha>.json;
5. si existe RESUME_URL (la manda n8n al lanzar la Action), le envía el plan.
Uso: python -m motor.ejecutar [--sin-red ejemplos/]"""
from __future__ import annotations
import json
import os
import sys
import traceback
import urllib.request
from datetime import date

from . import fuentes as F
from . import detectores as D
from .motor import puntuar, seleccionar, cargar_publicados
from .series import Almacen

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def main():
    cat = json.load(open(f"{R}/config/indicadores.json", encoding="utf-8"))
    prov = json.load(open(f"{R}/config/provincias.json", encoding="utf-8"))["provincias"]
    alm = Almacen(f"{R}/datos/historico")
    publicados = cargar_publicados(f"{R}/datos/publicados.json")
    hoy = date.today().isoformat()
    novedades, reserva, avisos, series = [], [], [], {}

    def procesar_serie(s, cfg):
        cambios = alm.guardar(s)
        s = alm.serie_completa(s)
        series[cfg["id"]] = s
        if F.esta_congelada(s):
            avisos.append(f"⚠️ {s.nombre} ({s.origen.codigo}) no se actualiza desde {s.periodos[-1]}: ¿cambio de base o serie discontinuada?")
            return
        if cambios["revisados"]:
            avisos.append(f"ℹ️ {s.nombre}: la fuente ha revisado {len(cambios['revisados'])} valores anteriores.")
        es_nuevo = bool(cambios["nuevos"])
        dets = D.det_records(s) + D.det_cambios(s) + D.det_tendencias(s) + D.det_hito(s)
        if "hoy_vs_media" in cfg.get("detectores_extra", []):
            dets += D.det_anomalia_estacional(s)
        for i in dets:
            i.tema = cfg.get("tema", "")
            puntuar(i, cfg.get("interes", 2), 1.0 if es_nuevo else 0.6, publicados)
            (novedades if es_nuevo else reserva).append(i)
        for i in D.det_comparacion_temporal(s):
            i.tema = cfg.get("tema", "")
            puntuar(i, cfg.get("interes", 2), 0.6, publicados)
            reserva.append(i)

    # --- INE ---
    for cfg in cat["ine"]:
        try:
            tabla = cfg.get("tabla") or F.ine_buscar_tabla(cfg["operacion"], cfg["tabla_contiene"])
            if cfg["tipo"] == "corte":
                c = F.ine_corte_territorial(tabla, cfg["filtro"], cfg["nivel"], cfg["id"], cfg["nombre"], cfg["unidad"],
                                            decimales=cfg.get("decimales", 2), dataset=f"{cfg['operacion']} · tabla {tabla}",
                                            nota=cfg.get("nota", ""))
                marca = f"{R}/datos/historico/{cfg['id']}.ultimo"
                es_nuevo = not os.path.exists(marca) or open(marca).read() != c.fecha
                open(marca, "w").write(c.fecha)
                ins = D.det_corte(c, prov)
                if "brecha" in cfg:
                    b = cfg["brecha"]
                    ca = F.ine_corte_territorial(tabla, b["a"], cfg["nivel"], cfg["id"] + ".a", cfg["nombre"], cfg["unidad"], decimales=cfg.get("decimales", 2), dataset=f"{cfg['operacion']} · tabla {tabla}")
                    cb = F.ine_corte_territorial(tabla, b["b"], cfg["nivel"], cfg["id"] + ".b", cfg["nombre"], cfg["unidad"], decimales=cfg.get("decimales", 2), dataset=f"{cfg['operacion']} · tabla {tabla}")
                    ins += D.det_brecha(ca, cb, *b["etiquetas"], provincias_cfg=prov)
                for i in ins:
                    i.tema = cfg.get("tema", "")
                    puntuar(i, cfg.get("interes", 2), 1.0 if es_nuevo else 0.6, publicados)
                    (novedades if es_nuevo else reserva).append(i)
            else:
                for s in F.ine_series_de_tabla(tabla, cfg["filtro"], None, cfg["id"], cfg["unidad"], cfg.get("decimales", 1),
                                               f"{cfg['operacion']} · tabla {tabla}"):
                    s.nombre = cfg["nombre"] if cfg["tipo"] == "serie" else s.nombre
                    s.id = cfg["id"] if cfg["tipo"] == "serie" else s.id
                    procesar_serie(s, cfg)
                    if cfg["tipo"] == "serie":
                        break
        except Exception as e:                       # una fuente caída no para el día
            avisos.append(f"❌ {cfg['id']}: {e}")
            traceback.print_exc()

    # --- REE (REData) ---
    for cfg in cat["redata"]:
        try:
            ss = F.redata_series(cfg["categoria"], cfg["widget"], date.fromisoformat(cfg["desde"]), date.today(),
                                 cfg["trunc"], cfg["id"], cfg["unidad"])
            for s in ss:
                if cfg.get("componentes_interes") and s.nombre not in cfg["componentes_interes"]:
                    continue
                procesar_serie(s, {**cfg, "id": s.id})
        except Exception as e:
            avisos.append(f"❌ {cfg['id']}: {e}")

    # --- BCE ---
    for cfg in cat["bce"]:
        try:
            s = F.bce_serie(cfg["flujo"], cfg["clave"], cfg["id"], cfg["nombre"], cfg["unidad"], cfg["frecuencia"],
                            decimales=cfg.get("decimales", 2))
            procesar_serie(s, cfg)
        except Exception as e:
            avisos.append(f"❌ {cfg['id']}: {e}")

    # --- Cruces ---
    for cr in cat.get("cruces", []):
        if cr["a"] in series and cr["b"] in series:
            for i in D.det_cruce(series[cr["a"]], series[cr["b"]]):
                puntuar(i, 2, 0.6, publicados)
                reserva.append(i)

    plan = seleccionar(novedades, reserva)
    plan.update({"fecha": hoy, "avisos": avisos})
    os.makedirs(f"{R}/datos/plan", exist_ok=True)
    ruta = f"{R}/datos/plan/{hoy}.json"
    json.dump(plan, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"Plan: {plan['tipo']} · {len(plan['carruseles'])} carrusel(es) · {len(avisos)} aviso(s) -> {ruta}")
    url = os.environ.get("RESUME_URL")
    if url:
        req = urllib.request.Request(url, data=json.dumps(plan, default=str).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60)


if __name__ == "__main__":
    sys.exit(main())
