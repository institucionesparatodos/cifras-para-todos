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
