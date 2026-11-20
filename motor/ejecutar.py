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
from . import aemet as A
from . import esios as E
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

    def procesar_serie(s, cfg, guardar=True, es_nuevo=None):
        """Guarda la serie (si guardar) y pasa los detectores. Con guardar=False (series derivadas que no se
        guardan, como 'los octubres de cada año'), es_nuevo lo decide quien llama."""
        if guardar:
            cambios = alm.guardar(s)
            s = alm.serie_completa(s)
        else:
            cambios = {"nuevos": [s.periodos[-1]] if es_nuevo else [], "revisados": []}
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
        if cfg.get("solo_detectores"):                      # lista cerrada de detectores para esa serie
            dets = [i for i in dets if any(i.detector.startswith(d) for d in cfg["solo_detectores"])]
        for i in dets:
            i.tema = cfg.get("tema", "")
            puntuar(i, cfg.get("interes", 2), 1.0 if es_nuevo else 0.6, publicados)
            (novedades if es_nuevo else reserva).append(i)
        anyos_serie = (date.fromisoformat(s.periodos[-1]) - date.fromisoformat(s.periodos[0])).days / 365.25
        comparar = ([] if s.frecuencia == "D" or cfg.get("sin_comparacion")
                    else D.det_comparacion_temporal(s, 20 if anyos_serie >= 20.5 else 10))
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

    def procesar_aemet(cfg):
        corto = {k: A.NOMBRE_CAPITAL.get(k, v.get("corto", k)) for k, v in prov.items()}   # se nombra la capital
        provincias = list(prov)
        ruta_est = f"{R}/datos/historico/aemet.estaciones.json"
        previas = json.load(open(ruta_est, encoding="utf-8")) if os.path.exists(ruta_est) else {}
        # 1) Diarios de todas las estaciones (últimos 14 días; AEMET publica con unos días de retraso)
        hoy_d = date.today()
        registros, url = A.diarios_todas(hoy_d - timedelta(days=14), hoy_d - timedelta(days=1))
        estaciones = A.elegir_estaciones(registros, previas, cfg.get("estaciones_fijas", {}), provincias)
        cambios_est = [p for p in estaciones if previas.get(p, {}).get("indicativo") != estaciones[p]["indicativo"]]
        json.dump(estaciones, open(ruta_est, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"   {len(registros)} registros diarios; {len(estaciones)} provincias con estación", flush=True)
        for p in cambios_est:
            print(f"   estación de {corto.get(p, p)}: {estaciones[p]['indicativo']} · {estaciones[p]['nombre']}", flush=True)
        sin = [corto.get(p, p) for p in provincias if p not in estaciones]
        if sin:
            avisos.append(f"ℹ️ AEMET: sin estación elegida en {', '.join(sin)} (se puede fijar en 'estaciones_fijas').")
        diarias = A.series_diarias(registros, estaciones, corto, url)
        tmed = []
        for s in diarias:
            alm.guardar(s)
            if ".tmed." in s.id:
                tmed.append(alm.serie_completa(s))
        dias, medias = A.media_nacional_diaria(tmed, minimo=int(0.75 * len(estaciones)))
        if dias:
            nac = A.Serie(id="aemet.temperatura.media", nombre="Temperatura media de las capitales de provincia",
                          unidad="°C", frecuencia="D", periodos=dias, valores=medias,
                          origen=A.Origen("AEMET", "Valores climatológicos diarios (media de las capitales, cálculo propio)",
                                          "Media de tmed de las estaciones de las capitales", url, "", A.ahora_iso(), A.LICENCIA),
                          decimales=1)
            alm.guardar(nac)
            series["aemet.temperatura.media"] = alm.serie_completa(nac)
        # 2) Mensuales por estación: carga del histórico poco a poco y, después, solo el mes que falta
        anyo_desde = int(cfg.get("desde_mensual", 1991))
        presupuesto = time.time() + cfg.get("presupuesto_s", 540)
        completas = 0
        for prov_n, e in estaciones.items():
            idema, terr = e["indicativo"], corto.get(prov_n, prov_n)
            hecho = leer_marca(f"aemet.mes.{idema}", "hecho")        # último año cargado
            anyo_actual = hoy_d.year
            if hecho is None or int(hecho) < anyo_actual - 1:
                inicio = anyo_desde if hecho is None else int(hecho) + 1
                while inicio <= anyo_actual - 1 and time.time() < presupuesto:
                    fin = min(inicio + 2, anyo_actual - 1)
                    regs, url_m = A.mensuales(idema, inicio, fin)
                    for var, vals in A.leer_mensuales(regs).items():
                        if vals:
                            alm.guardar(A.serie_mensual(var, idema, e["nombre"], terr, vals, url_m))
                    guardar_marca(f"aemet.mes.{idema}", "hecho", fin)
                    inicio = fin + 1
                if inicio <= anyo_actual - 1:
                    continue                                  # sigue mañana
            # Año en curso: solo si falta el mes pasado
            mes_pasado = (hoy_d.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()
            previo = alm.leer(f"aemet.mes.tm_mes.{idema}")
            nuevo = False
            if mes_pasado not in previo and hoy_d.day >= 3 and time.time() < presupuesto:
                regs, url_m = A.mensuales(idema, int(mes_pasado[:4]), int(mes_pasado[:4]))
                for var, vals in A.leer_mensuales(regs).items():
                    if vals:
                        alm.guardar(A.serie_mensual(var, idema, e["nombre"], terr, vals, url_m))
                nuevo = mes_pasado in alm.leer(f"aemet.mes.tm_mes.{idema}")
            completas += 1
            # 3) Detectores (solo con el histórico completo)
            for var in A.VARIABLES_MENSUALES:
                datos = alm.leer(f"aemet.mes.{var}.{idema}")
                if len(datos) < 120:
                    continue
                ps = sorted(datos)
                s = A.serie_mensual(var, idema, e["nombre"], terr, {p: datos[p] for p in ps}, "")
                s.origen = A.Origen(**{**json.load(open(f"{R}/datos/historico/{s.id}.json", encoding="utf-8"))["origen"]})
                base = {"id": s.id, "tema": "tiempo", "interes": cfg.get("interes", 3), "sin_comparacion": True}
                procesar_serie(s, {**base, "solo_detectores": ["hoy_vs_media"], "detectores_extra": ["hoy_vs_media"]},
                               guardar=False, es_nuevo=nuevo)
                mm = A.mismo_mes(s)
                procesar_serie(mm, {**base, "id": mm.id, "solo_detectores": ["máximo", "mínimo"]},
                               guardar=False, es_nuevo=nuevo)
        if completas < len(estaciones):
            avisos.append(f"ℹ️ AEMET: cargando el histórico mensual ({completas} de {len(estaciones)} estaciones completas).")

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

    # --- REE (e·sios): precio de la luz ---
    if cat.get("esios") and not os.environ.get("ESIOS_TOKEN"):
        print("→ e·sios: falta el secreto ESIOS_TOKEN; se omite hasta que exista", flush=True)
    for cfg in (cat.get("esios", []) if os.environ.get("ESIOS_TOKEN") else []):
        if cfg.get("activo") is False:
            continue
        t0 = time.time(); print(f"→ {cfg['id']}…", flush=True)
        try:
            ultima = leer_marca(cfg["id"], "hasta")
            desde = date.fromisoformat(cfg["desde"])
            if ultima:                                   # solo lo nuevo (con margen por revisiones)
                margen = 62 if cfg.get("trunc") == "month" else 15
                desde = max(desde, date.fromisoformat(ultima) - timedelta(days=margen))
            s = E.serie(cfg, desde)
            if s is None:
                print("   nada nuevo que pedir", flush=True)
                guardar_marca(cfg["id"], "hasta", date.today().isoformat())
                continue
            if cfg.get("trunc") == "month":
                alm.borrar_desde(s.id, date.today().replace(day=1).isoformat())
            print(f"   {len(s.periodos)} valores de {s.periodos[0]} a {s.periodos[-1]}", flush=True)
            procesar_serie(s, cfg)
            guardar_marca(cfg["id"], "hasta", date.today().isoformat())
        except Exception as e:
            avisos.append(f"❌ {cfg['id']}: {e}")
        print(f"   {time.time() - t0:.0f} s", flush=True)

    # --- AEMET: temperatura y lluvia en las capitales de provincia ---
    cfg_a = cat.get("aemet")
    if cfg_a and cfg_a.get("activo") is not False and not os.environ.get("AEMET_API_KEY"):
        print("→ AEMET: falta el secreto AEMET_API_KEY; se omite hasta que exista", flush=True)
    elif cfg_a and cfg_a.get("activo") is not False:
        t0 = time.time(); print("→ aemet…", flush=True)
        try:
            procesar_aemet(cfg_a)
        except Exception as e:
            avisos.append(f"❌ aemet: {e}")
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
