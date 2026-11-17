"""Dibuja el icono de Backtrack Acordes (diseño propio): pantalla de vídeo con un diagrama de
acorde, botón de play y una tira de línea de tiempo de acordes de colores.

Crea icon.png y, en macOS, «Backtrack Acordes.app/Contents/Resources/AppIcon.icns».
Uso:  .venv/bin/python make_icon.py
"""
import colorsys
import platform
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1024
BASE = Path(__file__).resolve().parent
FONT = BASE / "fuentes" / "DejaVuSerif-Bold.ttf"


def chord_rgb(root, minor=False):
    h = ((root * 30 + 20) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(h, 0.58 if minor else 0.66, 0.55)
    return int(r * 255), int(g * 255), int(b * 255)


def draw(size=S):
    W = size * 2
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    # fondo redondeado con degradado cálido
    bg = Image.new("RGB", (W, W))
    bd = ImageDraw.Draw(bg)
    for y in range(W):
        k = y / W
        bd.line((0, y, W, y), fill=(int(58 - 34 * k), int(38 - 24 * k), int(26 - 16 * k)))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle((W * .06, W * .06, W * .94, W * .94), radius=int(W * .2), fill=255)
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)
    gold, gold2, muted = (209, 157, 97), (232, 184, 120), (185, 166, 144)

    # pantalla
    sx0, sy0, sx1, sy1 = W * .14, W * .17, W * .86, W * .64
    sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((sx0, sy0 + W * .015, sx1, sy1 + W * .02), radius=int(W * .05), fill=(0, 0, 0, 160))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(W * .02)))
    d.rounded_rectangle((sx0, sy0, sx1, sy1), radius=int(W * .05), fill=(20, 14, 10), outline=gold, width=int(W * .012))

    # diagrama de acorde (La menor) a la izquierda de la pantalla
    gx0, gy0 = W * .20, W * .29
    gs, gfy = W * .042, W * .055
    for i in range(6):
        d.line((gx0 + i * gs, gy0, gx0 + i * gs, gy0 + 4 * gfy), fill=muted, width=int(W * .006))
    for j in range(5):
        d.line((gx0, gy0 + j * gfy, gx0 + 5 * gs, gy0 + j * gfy), fill=muted, width=int(W * (.016 if j == 0 else .005)))
    frets = (-1, 0, 2, 2, 1, 0)
    r = W * .02
    for i, f in enumerate(frets):
        cx = gx0 + i * gs
        if f > 0:
            cy = gy0 + (f - .5) * gfy
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=gold2)
    # nombre del acorde
    font = ImageFont.truetype(str(FONT), int(W * .14))
    d.text((W * .655, W * .40), "Am", font=font, fill=gold2, anchor="mm")
    # botón play
    px, py, pr = W * .74, W * .555, W * .045
    d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=gold)
    d.polygon([(px - pr * .35, py - pr * .5), (px - pr * .35, py + pr * .5), (px + pr * .55, py)], fill=(26, 18, 12))

    # tira de línea de tiempo con acordes de colores
    ty0, ty1 = W * .70, W * .82
    blocks = [(.14, .32, 9, True), (.32, .48, 7, False), (.48, .66, 5, False), (.66, .86, 4, False)]
    for a, b, root, minor in blocks:
        d.rounded_rectangle((W * a + W * .006, ty0, W * b - W * .006, ty1), radius=int(W * .022), fill=chord_rgb(root, minor))
    hx = W * .40
    d.rounded_rectangle((hx - W * .006, ty0 - W * .03, hx + W * .006, ty1 + W * .03), radius=int(W * .006), fill=(255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


def main():
    icon = draw()
    icon.save(BASE / "icon.png")
    print("icon.png creado")
    if platform.system() != "Darwin":
        return
    res = BASE / "Backtrack Acordes.app" / "Contents" / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        iset = Path(tmp) / "AppIcon.iconset"
        iset.mkdir()
        for s in (16, 32, 128, 256, 512):
            icon.resize((s, s), Image.LANCZOS).save(iset / f"icon_{s}x{s}.png")
            icon.resize((s * 2, s * 2), Image.LANCZOS).save(iset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iset), "-o", str(res / "AppIcon.icns")], check=True)
    print("AppIcon.icns creado")


if __name__ == "__main__":
    main()
