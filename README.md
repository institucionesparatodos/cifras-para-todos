# Cifras para todos (@cifrasparatodos)

Motor automático que busca datos sorprendentes en las estadísticas públicas de España (INE, Red Eléctrica, BCE; AEMET en fase 2) y genera carruseles de Instagram trazables, siguiendo la identidad de "INSTITUCIONES para todos". El diseño completo está en `DISENO.md`.

- `python -m pytest -q tests`: pruebas de los detectores y del verificador.
- `python ejemplos/muestra_epa.py && python ejemplos/lote_epa.py && python -m render.render salida/lote_epa.json salida/jpg`: muestra con datos reales de la EPA (3T 2026).
- `python -m motor.ejecutar`: ejecución diaria (en GitHub Actions, con acceso a las APIs).
