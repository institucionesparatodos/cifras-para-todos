"""Muestra completa: plan del motor (EPA real) + textos de prueba -> verificación -> lote -> JPEG.
En producción los textos los redacta Claude en n8n a partir de las afirmaciones; aquí van escritos a mano
para enseñar el resultado, y pasan por el mismo verificador."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor.carrusel import cortes_bonitos, provincias_cfg, afirmaciones_de, textos_de
from motor.detectores import af_calculo
from motor.verificar import verificar
from motor import formato as fmt
from dataclasses import asdict

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
plan = json.load(open(f"{R}/salida/plan_epa.json", encoding="utf-8"))
car = plan["carruseles"][0]
afs = afirmaciones_de(car)
A = {a["id"]: a for a in afs}
prov = provincias_cfg()
mapa = car["principal"]["visual"]
brecha = next(s for s in car["secundarios"] if s["detector"] == "brecha_grupos")
orig_total = A["t0"]["origenes"]

# Cifras auxiliares del pictograma: también son afirmaciones (CÁLCULO DERIVADO, aproximado)
extra = [asdict(af_calculo("p1", "CÁLCULO DERIVADO", 10, "", 0, "Personas en paro de cada 100 activas (redondeo)", "3T 2026",
                           "10,18 redondeado a entero", orig_total, aproximado=True)),
         asdict(af_calculo("p2", "CÁLCULO DERIVADO", 90, "", 0, "Personas con empleo de cada 100 activas (redondeo)", "3T 2026",
                           "100 − 10", orig_total, aproximado=True)),
         asdict(af_calculo("p3", "CÁLCULO DERIVADO", 100, "", 0, "Base del pictograma", "3T 2026", "base fija de 100 personas", orig_total))]
afs += extra

vals = mapa["valores"]
orden = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
corto = lambda t: prov[t]["corto"]
fila = lambda t, v: {"nombre": corto(t), "valor": v, "texto": fmt.pct(v, 2)}
FUENTE = "Fuente: INE (EPA), 3T 2026"

dias = [
 {"tipo": "portada", "oscura": True, "formato": "MAPA",
  "titulo": "De 4,63 % a 18,87 %: así cambia el paro según dónde vivas",
  "subtitulo": "Tasa de paro por provincias · tercer trimestre de 2026",
  "mini": [{"nombre": "Illes Balears", "valor": vals["Balears, Illes"], "texto": A["t52"]["texto_valor"] if A.get("t52",{}).get("valor")==vals["Balears, Illes"] else fmt.pct(vals["Balears, Illes"],2)},
           {"nombre": "España", "valor": A["t0"]["valor"], "texto": A["t0"]["texto_valor"], "destacar": True},
           {"nombre": "Melilla", "valor": vals["Melilla"], "texto": fmt.pct(vals["Melilla"], 2)}],
  "tipos": ["DATO OFICIAL"]},
 {"tipo": "contador", "titulo": "Tasa de paro en España",
  "cifra": A["t0"]["texto_valor"], "etiqueta": "Tercer trimestre de 2026",
  "pictograma": {"total": 100, "resaltadas": 10, "leyenda_si": "en paro", "leyenda_no": "con empleo"},
  "nota": "De cada <b>100</b> personas que trabajan o buscan empleo, unas <b>10</b> están en paro.",
  "tipos": ["DATO OFICIAL", "CÁLCULO DERIVADO"]},
 {"tipo": "mapa", "titulo": "El paro es más alto en el sur y en Ceuta y Melilla",
  "valores": vals, "provincias": prov, "unidad": "%", "cortes": cortes_bonitos(list(vals.values())),
  "nota": "Cada cuadrado es una provincia. Ceuta (CE) y Melilla (ML) son ciudades autónomas. Canarias, en el recuadro.",
  "tipos": ["DATO OFICIAL"]},
 {"tipo": "top_bottom", "titulo": "Dónde hay más y menos paro",
  "rotulo_arriba": "Más paro", "arriba": [fila(t, v) for t, v in orden[:5]],
  "rotulo_abajo": "Menos paro", "abajo": [fila(t, v) for t, v in orden[::-1][:5]],
  "referencia": A["t0"]["valor"], "rotulo_referencia": f"Media de España: {A['t0']['texto_valor']}",
  "tipos": ["DATO OFICIAL"]},
 {"tipo": "comparacion_grupos", "titulo": f"Las mujeres tienen más paro que los hombres en {A['b7']['texto_valor']} territorios",
  "bloques": [{"nombre": "España", "barras": [{"nombre": "Mujeres", "valor": A["b1"]["valor"], "texto": A["b1"]["texto_valor"]},
                                               {"nombre": "Hombres", "valor": A["b2"]["valor"], "texto": A["b2"]["texto_valor"]}],
               "diferencia": f"{A['b3']['texto_valor']} de diferencia"},
              {"nombre": "Melilla", "barras": [{"nombre": "Mujeres", "valor": A["b4"]["valor"], "texto": A["b4"]["texto_valor"]},
                                               {"nombre": "Hombres", "valor": A["b5"]["valor"], "texto": A["b5"]["texto_valor"]}],
               "diferencia": f"{A['b6']['texto_valor']} de diferencia"}],
  "nota": "Melilla tiene la mayor diferencia. La EPA es una encuesta: en territorios pequeños el margen de error es mayor.",
  "tipos": ["DATO OFICIAL", "COMPARACIÓN"]},
 {"tipo": "conclusion", "titulo": "En resumen",
  "puntos": [f"En España, la tasa de paro es del <b>{A['t0']['texto_valor']}</b>: unas 10 de cada 100 personas activas.",
             f"En Melilla es <b>{A['r1']['texto_valor']}</b> la de Illes Balears, la provincia con menos paro.",
             f"El paro de las mujeres supera al de los hombres en <b>{A['b3']['texto_valor']}</b>."],
  "tipos": ["DATO OFICIAL", "COMPARACIÓN"]},
 {"tipo": "fuente", "titulo": "Fuente y método", "sin_pie": True,
  "filas": [["Fuente", "Instituto Nacional de Estadística (INE)"],
            ["Estadística", "Encuesta de Población Activa (EPA), tabla 65349"],
            ["Periodo", "Tercer trimestre de 2026"],
            ["Qué se mide", "Tasa de paro: personas en paro entre personas activas (con empleo o buscándolo), por 100"],
            ["Cálculos", "Diferencias y cocientes hechos por Cifras para todos con los datos oficiales"],
            ["Aviso", "Es una encuesta: en provincias pequeñas, Ceuta y Melilla el margen de error es mayor"]],
  "leyenda_tipos": "<b>✓ DATO OFICIAL</b>: cifra publicada por la fuente.<br><b>= COMPARACIÓN o CÁLCULO DERIVADO</b>: operación hecha por nosotros con datos oficiales.<br><b>≈ ESTIMACIÓN</b>: valor aproximado."}
]

pie = ("La tasa de paro de España fue del 10,18 % en el tercer trimestre de 2026, según la EPA del INE. "
       "Pero cambia mucho según la provincia: va del 4,63 % de Illes Balears al 18,87 % de Melilla.\n\n"
       "📍 Las tasas más altas están en el sur y en Ceuta y Melilla.\n"
       "👩 Las mujeres tienen más paro que los hombres en 46 de 52 territorios.\n\n"
       "Fuente: INE, Encuesta de Población Activa (tabla 65349). Divulgación independiente, no oficial.")
lote = {"lote": "cifras-muestra-epa-3T2026", "marca_ejemplo": None, "carruseles": [{
    "titulo_publicacion": "El paro por provincias (3T 2026)", "fuente_corta": FUENTE,
    "pie_de_foto": pie, "hashtags": ["#CifrasParaTodos", "#EPA", "#Paro", "#Empleo", "#DatosAbiertos"],
    "alt": "Carrusel con la tasa de paro por provincias del tercer trimestre de 2026 según la EPA del INE.",
    "afirmaciones": afs, "diapositivas": dias}]}

import re
problemas = verificar([re.sub(r"<[^>]+>", "", t) for t in textos_de(lote)], afs)
print("Verificación:", "OK" if not problemas else problemas)
json.dump(lote, open(f"{R}/salida/lote_epa.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("cortes mapa:", dias[2]["cortes"])
