"""Renderiza un lote (datos/<lote>.json) en JPEG de 1080 × 1350 con Playwright.
Uso: python -m render.render datos/<lote>.json salida/
Lo ejecuta la GitHub Action, igual que en el BOE. La API de Instagram solo acepta JPEG."""
import json
import os
import sys
from playwright.sync_api import sync_playwright

AQUI = os.path.dirname(os.path.abspath(__file__))


def renderizar(ruta_lote: str, carpeta: str) -> list[str]:
    lote = json.load(open(ruta_lote, encoding="utf-8"))
    os.makedirs(carpeta, exist_ok=True)
    hechas = []
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pag = nav.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        pag.goto("file://" + os.path.join(AQUI, "plantilla.html"))
        for ci, car in enumerate(lote["carruseles"], 1):
            total = len(car["diapositivas"])
            for i, s in enumerate(car["diapositivas"], 1):
                k = {"n": i, "total": total, "fuente_corta": car["fuente_corta"], "ejemplo": lote.get("marca_ejemplo")}
                pag.evaluate("([s,k]) => window.pintar(s,k)", [s, k])
                pag.wait_for_timeout(120)
                ruta = os.path.join(carpeta, f"c{ci}_{i:02d}.jpg")
                pag.screenshot(path=ruta, type="jpeg", quality=92)
                hechas.append(ruta)
        nav.close()
    return hechas


if __name__ == "__main__":
    print("\n".join(renderizar(sys.argv[1], sys.argv[2])))
