"""Pruebas con series SINTÉTICAS (inventadas a propósito, solo para comprobar los detectores)."""
import math, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor.series import Serie, Origen
from motor import detectores as D
from motor.verificar import verificar
from motor.formato import num, pct, cifras_en_texto

O = Origen("PRUEBA", "sintético", "serie de prueba", "http://localhost", "", "", "")

def mensual(vals, desde=2000):
    ps = [f"{desde + i // 12}-{i % 12 + 1:02d}-01" for i in range(len(vals))]
    return Serie("prueba.s", "Serie de prueba", "GWh", "M", ps, vals, O, 0)

def test_formato():
    assert num(1234567.891, 2) == "1.234.567,89" and pct(10.18, 2) == "10,18\u00a0%"
    assert cifras_en_texto("De 4,63 % a 18,87 % y 1.234 personas") == [4.63, 18.87, 1234.0]

def test_record_historico():
    vals = [100 + math.sin(i) * 5 for i in range(240)] + [130]
    r = [i for i in D.det_records(mensual(vals)) if i.formato == "RÉCORD"]
    assert r and r[0].detector == "máximo_histórico"

def test_maximo_de_10_anyos():
    vals = [200] + [100 + (i % 7) for i in range(12 * 12)] + [150]
    r = D.det_records(mensual(vals))
    assert any(i.detector == "máximo_10_años" for i in r), [i.detector for i in r]

def test_sin_record_si_no_toca():
    vals = [100 + (i % 12) for i in range(120)]
    assert not [i for i in D.det_records(mensual(vals)) if i.detector.startswith("máximo")]

def test_cambio_brusco():
    random.seed(1)
    vals = [100 + random.gauss(0, 1) for _ in range(120)] + [115]
    assert any(i.detector == "cambio_periodo_anterior" for i in D.det_cambios(mensual(vals)))

def test_tendencia_y_giro():
    vals = [100 + (i % 3) for i in range(60)] + [100 + k for k in range(1, 9)]
    assert any(i.detector == "tendencia_sostenida" for i in D.det_tendencias(mensual(vals)))
    vals2 = vals + [vals[-1] - 3]
    assert any(i.detector == "cambio_tendencia" for i in D.det_tendencias(mensual(vals2)))

def test_hito():
    s = Serie("p", "Población", "personas", "A", [f"{2000+i}-01-01" for i in range(4)], [48.7e6, 49.3e6, 49.8e6, 50.1e6], O, 0)
    h = D.det_hito(s)
    assert h and "50.000.000" in h[0].titular_base

def test_cruce_no_causal():
    random.seed(2)
    a = [random.gauss(0, 1) for _ in range(60)]
    b = [x * 2 + random.gauss(0, 0.3) for x in a]
    sa, sb = mensual(a), mensual(b); sb.id = "otra"
    c = D.det_cruce(sa, sb)
    assert c and "misma dirección" in c[0].titular_base
    afs = [x.__dict__ for x in c[0].afirmaciones]
    assert verificar(["El calor provoca más consumo"], afs, es_cruce=True)

def test_verificador_detecta_cifra_inventada():
    afs = [{"valor": 10.18, "texto_valor": "10,18 %", "periodo": "3T 2026", "descripcion": ""}]
    assert not verificar(["La tasa de paro es del 10,18 % en el 3T 2026"], afs)
    assert verificar(["La tasa de paro es del 11,4 %"], afs)

def test_tendencia_con_ultimo_cambio_cero():
    vals = [100 + (i % 3) for i in range(60)] + [105, 105]
    D.det_tendencias(mensual(vals))   # no debe fallar

def test_filtro_exacto_y_total():
    from motor import fuentes as F
    p = F._partes("Total Nacional. Todas las edades. Mujeres. Población. Número.")
    assert not F._coincide(["Todas las edades", "Total"], p)          # antes «Total» encajaba en «Total Nacional»
    assert F._coincide(["Todas las edades", "Total"], F._partes("Granada. Todas las edades. Total. Población"))
    assert F._coincide(["Industria, construcción y servicios*"], F._partes("Total Nacional. Industria, construcción y servicios (excepto…). Coste"))
    assert F._territorio(F._partes("Nacional. General. Variación anual")) == "Total Nacional"
    assert F._territorio(F._partes("Tasa de paro de la población. Ambos sexos. Granada. Total")) == "Granada"


def test_redata_sin_periodo_en_curso_y_porcentaje():
    """REData da el día de hoy y el mes en curso incompletos: no se guardan. Con porcentaje, el peso × 100."""
    from datetime import date, timedelta
    from motor import fuentes as F
    hoy = date.today()
    pedidos = []

    def falso(categoria, widget, a, b, trunc="day", geo=""):
        pedidos.append((a, b))
        dias = [hoy - timedelta(days=1), hoy]
        meses = [(hoy.replace(day=1) - timedelta(days=1)).replace(day=1), hoy.replace(day=1)]
        fechas = dias if trunc == "day" else meses
        return {"included": [{"attributes": {"title": "Solar fotovoltaica", "values": [
            {"value": 100.0, "percentage": 0.25, "datetime": f.isoformat() + "T00:00:00.000+01:00"} for f in fechas]}}]}, "http://x"

    original = F.redata
    F.redata = falso
    try:
        d = F.redata_series("generacion", "w", hoy - timedelta(days=3), hoy, "day", "ree.x", "MWh")
        assert d[0].periodos == [(hoy - timedelta(days=1)).isoformat()]
        m = F.redata_series("generacion", "w", hoy - timedelta(days=50), hoy, "month", "ree.y", "%", porcentaje=True)
        assert hoy.replace(day=1).isoformat() not in m[0].periodos and m[0].valores == [25.0]
        assert all(a.day == 1 for a, b in pedidos[1:])             # los meses se piden enteros
    finally:
        F.redata = original


def test_reserva_rota_entre_fuentes_y_tope_por_fuente():
    from motor.detectores import Insight
    from motor import motor as M

    def ins(fid, p, n):
        i = Insight(id=f"{fid}.{n}", detector="máximo_histórico", formato=f"F{n}", intensidad=1, fuente_id=fid,
                    titular_base="x", afirmaciones=[], visual={}, contexto={})
        i.puntuacion = p
        return i
    reserva = [ins("ine.a", 0.4, 1), ins("ree.b", 0.2, 2)]
    publicados = [{"fuente_id": "ine.z", "fecha": "2026-11-17", "id": "q", "formato": "MAPA"}]
    plan = M.seleccionar([], reserva, publicados)
    assert plan["carruseles"][0]["principal"]["fuente_id"] == "ree.b"     # REE nunca ha salido: le toca
    novedades = [ins(f"ine.s{k}", 0.9, k) for k in range(6)] + [ins("bce.t", 0.5, 9)]
    plan = M.seleccionar(novedades, [], [])
    fuentes = [c["principal"]["fuente_id"].split(".")[0] for c in plan["carruseles"]]
    assert fuentes.count("ine") == M.MAX_POR_FUENTE and "bce" in fuentes


def test_aemet_lectura_y_estaciones():
    from motor import aemet as A
    assert A.numero("23,4") == 23.4 and A.numero("Ip") == 0.0 and A.numero("Acum") is None
    assert A.numero("30.2(15)") == 30.2
    provs = ["Coruña, A", "Madrid", "Palmas, Las", "Balears, Illes"]
    assert A.provincia_ine("A CORUÑA", provs) == "Coruña, A"
    assert A.provincia_ine("ILLES BALEARS", provs) == "Balears, Illes"
    regs = [{"indicativo": "1", "nombre": "MADRID, RETIRO", "provincia": "MADRID", "tmax": "20,1"},
            {"indicativo": "2", "nombre": "MADRID AEROPUERTO", "provincia": "MADRID", "tmax": "21,0"},
            {"indicativo": "3", "nombre": "ALCALA", "provincia": "MADRID", "tmax": "19,0"},
            {"indicativo": "4", "nombre": "MADRID CUATRO VIENTOS", "provincia": "MADRID"}]
    e = A.elegir_estaciones(regs, {}, {}, provs)
    assert e["Madrid"]["indicativo"] == "2"                                  # capital + aeropuerto
    assert A.elegir_estaciones(regs, {}, {"Madrid": "1"}, provs)["Madrid"]["indicativo"] == "1"
    m = A.leer_mensuales([{"fecha": "2025-10", "tm_mes": "18.3", "p_mes": "40.1"}, {"fecha": "2025-13", "tm_mes": "16"}])
    assert m["tm_mes"] == {"2025-10-01": 18.3}


def test_aemet_mismo_mes():
    from motor import aemet as A
    vals = {f"{a}-{m:02d}-01": float(m + (a - 2000) / 10) for a in range(2000, 2026) for m in range(1, 13)}
    s = A.serie_mensual("tm_mes", "3195", "MADRID, RETIRO", "Madrid", vals, "u")
    mm = A.mismo_mes(s)
    assert mm.frecuencia == "A" and all(p[5:7] == "12" for p in mm.periodos) and "diciembre" in mm.nombre
    assert any(i.detector == "máximo_histórico" for i in D.det_records(mm))
