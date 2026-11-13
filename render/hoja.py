"""Hoja de vista previa (todas las diapositivas en una imagen) para la revisión por Telegram."""
import glob, os, sys
from PIL import Image

def hoja(carpeta: str):
    for pref in sorted({os.path.basename(p).split("_")[0] for p in glob.glob(f"{carpeta}/c*_*.jpg")}):
        fs = sorted(f for f in glob.glob(f"{carpeta}/{pref}_*.jpg") if not f.endswith("_hoja.jpg"))
        ims = [Image.open(f).resize((360, 450)) for f in fs]
        cols = 4; filas = (len(ims) + cols - 1) // cols
        h = Image.new("RGB", (cols * 370 + 10, filas * 460 + 10), "white")
        for k, im in enumerate(ims):
            h.paste(im, (10 + (k % cols) * 370, 10 + (k // cols) * 460))
        h.save(f"{carpeta}/{pref}_hoja.jpg", quality=85)

if __name__ == "__main__":
    hoja(sys.argv[1])
