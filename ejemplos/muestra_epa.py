"""Ejecuta el motor sobre el corte real de la EPA (3T 2026) guardado en ejemplos/."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor.series import Corte, Origen
from motor.detectores import det_corte, det_brecha
from motor.motor import puntuar, seleccionar

base = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(base, "ine_epa_65349_3T2026.json"), encoding="utf-8"))
prov = json.load(open(os.path.join(base, "..", "config", "provincias.json"), encoding="utf-8"))["provincias"]
o = Origen("INE", "Encuesta de Población Activa (EPA) · tabla 65349", d["indicador"], d["url"], "", "2026-11-13T00:00:00+00:00",
           "Licencia de uso del INE (cita obligatoria de la fuente)")
cortes = {}
for sexo in ("Ambos sexos", "Hombres", "Mujeres"):
    v = dict(d["valores"][sexo]); total = v.pop("Total Nacional")
    cortes[sexo] = Corte(f"ine.epa.paro.provincias.{sexo[:3].lower()}", "Tasa de paro", "%", d["periodo"]["etiqueta"],
                         d["periodo"]["fecha_inicio"], "provincia", v, total, o, 2,
                         "La EPA es una encuesta: en provincias pequeñas el margen de error es mayor.")
ins = det_corte(cortes["Ambos sexos"], prov) + det_brecha(cortes["Mujeres"], cortes["Hombres"], "mujeres", "hombres", prov)
for i in ins:
    puntuar(i, interes=3, frescura=1.0, publicados=[])
plan = seleccionar(ins, [])
os.makedirs(os.path.join(base, "..", "salida"), exist_ok=True)
json.dump(plan, open(os.path.join(base, "..", "salida", "plan_epa.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
for i in sorted(ins, key=lambda x: -x.puntuacion):
    print(f"{i.puntuacion:5.3f}  {i.formato:22s} {i.detector:22s} {i.titular_base}")
print("\nPlan:", plan["tipo"], [ (c["formato"], [s["formato"] for s in c["secundarios"]]) for c in plan["carruseles"]])
