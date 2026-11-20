"""Ejecución diaria (GitHub Action "analizar"):
1. descarga cada indicador del catálogo y lo fusiona con el histórico (datos/historico/);
2. avisa de series congeladas o caídas de una fuente (no paran el día);
3. pasa los detectores sobre lo que ha cambiado (novedades) y sobre todo el histórico (reserva);
4. puntúa, agrupa en carruseles y escribe datos/plan/<fecha>.json;
5. si existe RESUME_URL (la manda n8n al lanzar la Action), le envía el plan.
Uso: python -m motor.ejecutar"""
from __future__ import annotations
import json
import os
import sys
import time
import traceback
import urllib.request
from datetime import date, timedelta

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
        s.fecha_puntual = bool(cfg.get("fecha_puntual"))     # p. ej. población: "a 1 de octubre de 2026"
        series[cfg["id"]] = s
        limite = cfg.get("retraso_max_dias")                 # margen propio de un indicador (si lo tiene)
        congelada = ((date.today() - date.fromisoformat(s.periodos[-1])).days > limite) if limite else F.esta_congelada(s)
        if not cfg.get("solo_cambios") and congelada:
            avisos.append(f"⚠️ {s.nombre} ({s.origen.codigo}) no se actualiza desde {s.periodos[-1]}: ¿cambio de base o serie discontinuada?")
            return
        if cambios["revisados"] and s.frecuencia != "D":      # REE revisa a diario sus últimos días: no es noticia
            avisos.append(f"ℹ️ {s.nombre}: la fuente ha revisado {len(cambios['revisados'])} valores anteriores.")
        es_nuevo = bool(cambios["nuevos"])
        dets = D.det_records(s) + D.det_cambios(s) + D.det_tendencias(s) + D.det_hito(s)
        if "hoy_vs_media" in cfg.get("detectores_extra", []):
            dets += D.det_anomalia_estacional(s)
        omitir = set(cfg.get("omitir_detectores", []))     # p. ej. en series diarias, el cambio de un día a otro es ruido
        dets = [i for i in dets if i.detector not in omitir]
        for i in dets:
            i.tema = cfg.get("tema", "")
            puntuar(i, cfg.get("interes", 2), 1.0 if es_nuevo else 0.6, publicados)
            (novedades if es_nuevo else reserva).append(i)
        anyos_serie = (date.fromisoformat(s.periodos[-1]) - date.fromisoformat(s.periodos[0])).days / 365.25
        comparar = [] if s.frecuencia == "D" else D.det_comparacion_temporal(s, 20 if anyos_serie >= 20.5 else 10)
        for i in comparar:
            i.tema = cfg.get("tema", "")
            puntuar(i, cfg.get("interes", 2), 0.6, publicados)
            reserva.append(i)

    def leer_marca(cid, tipo):
        ruta = f"{R}/datos/historico/{cid}.{tipo}"
        return open(ruta).read().strip() if os.path.exists(ruta) else None

    def guardar_marca(cid, tipo, valor):
        os.makedirs(f"{R}/datos/historico", exist_ok=True)
        open(f"{R}/datos/historico/{cid}.{tipo}", "w").write(str(valor))

    def procesar_corte(cfg, tabla):
        ds = f"{cfg['operacion']} · tabla {tabla}"
        c = F.ine_corte_territorial(tabla, cfg["filtro"], cfg["nivel"], cfg["id"], cfg["nombre"], cfg["unidad"],
                                    decimales=cfg.get("decimales", 2), dataset=ds, nota=cfg.get("nota", ""))
        if len(c.valores) < 5:
            raise ValueError(f"tabla {tabla}: solo {len(c.valores)} territorios reconocidos ({list(c.valores)[:5]})")
        print(f"   tabla {tabla}: {len(c.valores)} territorios, periodo {c.periodo}, total {c.total}", flush=True)
        if (date.today() - date.fromisoformat(c.fecha)).days > cfg.get("retraso_max_dias", 270):
            raise ValueError(f"tabla {tabla}: el último dato es de {c.periodo}, demasiado antiguo")
        marca = f"{R}/datos/historico/{cfg['id']}.ultimo"
        es_nuevo = not os.path.exists(marca) or open(marca).read() != c.fecha
        ins = D.det_corte(c, prov)
        if cfg.get("detectores_corte"):              # p. ej. en población no tiene sentido «outlier» (las grandes son grandes)
            ins = [i for i in ins if i.detector in cfg["detectores_corte"]]
        if "brecha" in cfg:
            b = cfg["brecha"]
            ca = F.ine_corte_territorial(tabla, b["a"], cfg["nivel"], cfg["id"] + ".a", cfg["nombre"], cfg["unidad"], decimales=cfg.get("decimales", 2), dataset=ds)
            cb = F.ine_corte_territorial(tabla, b["b"], cfg["nivel"], cfg["id"] + ".b", cfg["nombre"], cfg["unidad"], decimales=cfg.get("decimales", 2), dataset=ds)
            ins += D.det_brecha(ca, cb, *b["etiquetas"], provincias_cfg=prov)
        for i in ins:
            i.tema = cfg.get("tema", "")
            puntuar(i, cfg.get("interes", 2), 1.0 if es_nuevo else 0.6, publicados)
            (novedades if es_nuevo else reserva).append(i)
        os.makedirs(os.path.dirname(marca), exist_ok=True)
        open(marca, "w").write(c.fecha)

    # --- INE ---
    for cfg in cat["ine"]:
        if cfg.get("activo") is False:
            continue
        t0 = time.time(); print(f"→ {cfg['id']}…", flush=True)
        try:
            recordada = leer_marca(cfg["id"], "tabla")
            if cfg.get("tabla"):
                candidatas = [cfg["tabla"]]
            elif recordada:
                candidatas = [int(recordada)]           # la tabla buena de ejecuciones anteriores (sin volver a buscar)
            else:
                candidatas = F.ine_buscar_tabla(cfg["operacion"], cfg["tabla_contiene"], cfg.get("operacion_nombre", ""))
            nult = 36 if recordada else 600             # la primera vez, histórico largo; después, solo lo reciente
            ultimo_error = None
            for tabla in candidatas[:4]:
                try:
                    if cfg["tipo"] == "corte":
                        procesar_corte(cfg, tabla)
                    else:
                        ss = F.ine_series_de_tabla(tabla, cfg["filtro"], nult, cfg["id"], cfg["unidad"], cfg.get("decimales", 1),
                                                   f"{cfg['operacion']} · tabla {tabla}")
                        if cfg["tipo"] == "serie":
                            ss = ss[:1]
                        print(f"   tabla {tabla}: {len(ss)} serie(s); «{ss[0].origen.indicador}» "
                              f"de {ss[0].periodos[0]} a {ss[0].periodos[-1]}", flush=True)
                        if all(F.esta_congelada(x) for x in ss) and tabla != candidatas[min(3, len(candidatas) - 1)]:
                            print(f"   tabla {tabla} sin datos recientes; pruebo la siguiente", flush=True)
                            continue
                        for x in ss:
                            if cfg["tipo"] == "serie":
                                x.nombre, x.id = cfg["nombre"], cfg["id"]
                            procesar_serie(x, cfg)
                    print(f"   ✓ tabla {tabla}", flush=True)
                    guardar_marca(cfg["id"], "tabla", tabla)
                    ultimo_error = None
                    break
                except Exception as e:            # probar la siguiente tabla candidata
                    ultimo_error = e
            if ultimo_error:
                raise ultimo_error
        except Exception as e:                       # una fuente caída no para el día
            avisos.append(f"❌ {cfg['id']}: {e}")
        print(f"   {time.time() - t0:.0f} s", flush=True)

    # --- REE (REData) ---
    for cfg in cat["redata"]:
        if cfg.get("activo") is False:
            continue
        t0 = time.time(); print(f"→ {cfg['id']}…", flush=True)
        try:
            ultima = leer_marca(cfg["id"], "hasta")
            desde = date.fromisoformat(cfg["desde"])
            if ultima:                                   # solo lo nuevo (con 60 días de margen por revisiones)
                desde = max(desde, date.fromisoformat(ultima) - timedelta(days=60))
            ss = F.redata_series(cfg["categoria"], cfg["widget"], desde, date.today(), cfg["trunc"], cfg["id"],
                                 cfg["unidad"], cfg.get("decimales", 0), porcentaje=bool(cfg.get("usar_porcentaje")))
            corte = F.ultimo_periodo_completo(cfg["trunc"]).isoformat()
            for s in ss:
                if cfg.get("componentes_interes") and s.nombre not in cfg["componentes_interes"]:
                    continue
                quitados = alm.borrar_desde(s.id, corte)   # limpia periodos incompletos guardados antes
                if quitados:
                    print(f"   {s.id}: quitados {quitados} periodo(s) incompleto(s) del histórico", flush=True)
                s.nombre = cfg.get("nombres", {}).get(s.nombre) or cfg.get("plantilla_nombre", "{}").format(s.nombre)
                procesar_serie(s, {**cfg, "id": s.id})
            guardar_marca(cfg["id"], "hasta", date.today().isoformat())
        except Exception as e:
            avisos.append(f"❌ {cfg['id']}: {e}")
        print(f"   {time.time() - t0:.0f} s", flush=True)

    # --- BCE ---
    for cfg in cat["bce"]:
        if cfg.get("activo") is False:
            continue
        t0 = time.time(); print(f"→ {cfg['id']}…", flush=True)
        try:
            previo = alm.leer(cfg["id"])
            inicio = "1999-01"
            if previo:
                inicio = (date.fromisoformat(max(previo)) - timedelta(days=730)).isoformat()[:7]
            s = F.bce_serie(cfg["flujo"], cfg["clave"], cfg["id"], cfg["nombre"], cfg["unidad"], cfg["frecuencia"],
                            inicio=inicio, decimales=cfg.get("decimales", 2))
            procesar_serie(s, cfg)
        except Exception as e:
            avisos.append(f"❌ {cfg['id']}: {e}")
        print(f"   {time.time() - t0:.0f} s", flush=True)

    # --- Cruces ---
    for cr in cat.get("cruces", []):
        if cr["a"] in series and cr["b"] in series:
            for i in D.det_cruce(series[cr["a"]], series[cr["b"]]):
                puntuar(i, 2, 0.6, publicados)
                reserva.append(i)

    plan = seleccionar(novedades, reserva, publicados)
    plan.update({"fecha": hoy, "avisos": avisos})
    os.makedirs(f"{R}/datos/plan", exist_ok=True)
    ruta = f"{R}/datos/plan/{hoy}.json"
    json.dump(plan, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\n=== AVISOS ===\n" + "\n".join(avisos), flush=True)
    print(f"Plan: {plan['tipo']} · {len(plan['carruseles'])} carrusel(es) · {len(avisos)} aviso(s) -> {ruta}")
    url = os.environ.get("RESUME_URL")
    if url:
        req = urllib.request.Request(url, data=json.dumps(plan, default=str).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60)


if __name__ == "__main__":
    sys.exit(main())
