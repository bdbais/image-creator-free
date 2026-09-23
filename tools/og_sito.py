# -*- coding: utf-8 -*-
"""Immagine di anteprima per i social (1200x630): icona, titolo e tre immagini generate."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H = 1200, 630


def font(dim, grassetto=True):
    for nome in (("segoeuib.ttf" if grassetto else "segoeui.ttf"), "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(nome, dim)
        except OSError:
            continue
    return ImageFont.load_default()


def main(cartella: Path):
    base = Image.new("RGB", (W, H), (12, 10, 36))
    alone = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(alone)
    d.ellipse((-200, -250, 700, 500), fill=(90, 50, 200))
    d.ellipse((650, 150, 1400, 800), fill=(200, 60, 140))
    base = Image.blend(base, alone.filter(ImageFilter.GaussianBlur(160)), 0.55)

    icona = Image.open(ROOT / "assets" / "ImageCreatorFree.png").resize((150, 150), Image.LANCZOS)
    base.paste(icona, (70, 80), icona)
    d = ImageDraw.Draw(base)
    d.text((70, 260), "Image Creator Free", font=font(64), fill=(239, 238, 255))
    d.text((72, 345), "Immagini generate sul tuo computer", font=font(34, False),
           fill=(200, 196, 240))
    d.text((72, 395), "Qwen-Image-2.1 · Windows · gratis e open source", font=font(26, False),
           fill=(170, 166, 216))
    d.text((72, 520), "imagecreator.bais.info", font=font(28), fill=(255, 232, 154))

    for nome, box, angolo in (("complessa-menu-lavagna.png", (330, 470), 7),
                              ("complessa-mercato-napoli.png", (470, 270), -5),
                              ("transparent-sticker-rgba.png", (250, 250), 4)):
        im = Image.open(cartella / nome).convert("RGBA")
        im.thumbnail(box, Image.LANCZOS)
        cornice = Image.new("RGBA", (im.width + 16, im.height + 16), (255, 255, 255, 255))
        cornice.alpha_composite(Image.new("RGBA", im.size, (40, 36, 80, 255)), (8, 8))
        cornice.alpha_composite(im, (8, 8))
        foto = cornice.rotate(angolo, resample=Image.BICUBIC, expand=True)
        pos = {"complessa-menu-lavagna.png": (930, 60),
               "complessa-mercato-napoli.png": (640, 300),
               "transparent-sticker-rgba.png": (700, 40)}[nome]
        base.paste(foto, pos, foto)
    out = ROOT / "site" / "public" / "img" / "og.jpg"
    base.save(out, quality=86)
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
