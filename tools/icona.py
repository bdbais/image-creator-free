# -*- coding: utf-8 -*-
"""Disegna l'icona di Image Creator Free e ne produce PNG, ICO e favicon.

Una foto "generata" (tramonto sulle colline) inclinata su uno sfondo indaco
con riflessi neon, e una scintilla nell'angolo: l'immagine che nasce dal
testo. Forme grandi e contrasti netti, perche' deve leggersi anche a 16 px.

    python tools/icona.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
S = 2048                      # si disegna grande e si riduce: bordi puliti


def gradiente(size, stops, angolo=135):
    """Gradiente lineare con piu' fermate, angolo in gradi (0 = da sinistra)."""
    w, h = size
    rad = math.radians(angolo)
    dx, dy = math.cos(rad), math.sin(rad)
    lin = Image.linear_gradient("L").resize((256, 256))
    # proiezione: calcolata a bassa risoluzione e ingrandita
    small = Image.new("RGB", (256, 256))
    px = small.load()
    for y in range(256):
        for x in range(256):
            t = ((x / 255 - 0.5) * dx + (y / 255 - 0.5) * dy) / (abs(dx) + abs(dy)) + 0.5
            t = min(1.0, max(0.0, t))
            for i in range(len(stops) - 1):
                p0, c0 = stops[i]
                p1, c1 = stops[i + 1]
                if p0 <= t <= p1:
                    k = (t - p0) / (p1 - p0) if p1 > p0 else 0
                    px[x, y] = tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3))
                    break
    del lin
    return small.resize((w, h), Image.BICUBIC)


def maschera_arrotondata(size, raggio):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), raggio, fill=255)
    return m


def scintilla(draw, cx, cy, r, colore, esponente=2.6):
    """Stella a quattro punte con i lati concavi (un'astroide ammorbidita)."""
    punti = []
    for i in range(720):
        a = 2 * math.pi * i / 720
        c, s = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** esponente, c)
        y = math.copysign(abs(s) ** esponente, s)
        punti.append((cx + r * x, cy + r * y))
    draw.polygon(punti, fill=colore)


def disegna() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Sfondo: indaco profondo -> viola -> blu elettrico, angoli morbidi.
    fondo = gradiente((S, S), [(0.0, (34, 18, 92)), (0.55, (76, 38, 170)),
                               (1.0, (22, 120, 235))], angolo=120)
    img.paste(fondo, (0, 0), maschera_arrotondata((S, S), int(S * 0.225)))

    # Alone neon dietro la foto.
    alone = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(alone).ellipse((S * .18, S * .20, S * .86, S * .88),
                                  fill=(255, 90, 200, 150))
    alone = alone.filter(ImageFilter.GaussianBlur(S * 0.09))
    img = Image.alpha_composite(img, ImageChops.multiply(
        alone, Image.new("RGBA", (S, S), (255, 255, 255, 255))))

    # La foto: cornice bianca e tramonto, disegnata dritta e poi ruotata.
    fw, fh = int(S * 0.60), int(S * 0.52)
    bordo = int(S * 0.035)
    foto = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    ImageDraw.Draw(foto).rounded_rectangle((0, 0, fw - 1, fh - 1), int(S * 0.05),
                                           fill=(255, 255, 255, 255))
    iw, ih = fw - 2 * bordo, fh - 2 * bordo
    cielo = gradiente((iw, ih), [(0.0, (255, 196, 92)), (0.45, (255, 110, 120)),
                                 (1.0, (150, 60, 200))], angolo=90)
    interno = cielo.convert("RGBA")
    d = ImageDraw.Draw(interno)
    # sole
    r = ih * 0.17
    d.ellipse((iw * 0.62 - r, ih * 0.40 - r, iw * 0.62 + r, ih * 0.40 + r),
              fill=(255, 244, 214, 255))
    # colline: due piani
    d.polygon([(0, ih * 0.78), (iw * 0.30, ih * 0.52), (iw * 0.55, ih * 0.74),
               (iw * 0.78, ih * 0.58), (iw, ih * 0.72), (iw, ih), (0, ih)],
              fill=(92, 40, 150, 255))
    d.polygon([(0, ih * 0.92), (iw * 0.40, ih * 0.70), (iw * 0.70, ih * 0.88),
               (iw, ih * 0.80), (iw, ih), (0, ih)], fill=(46, 22, 96, 255))
    foto.paste(interno, (bordo, bordo), maschera_arrotondata((iw, ih), int(S * 0.025)))

    ombra = Image.new("RGBA", (fw + 200, fh + 200), (0, 0, 0, 0))
    ImageDraw.Draw(ombra).rounded_rectangle((110, 140, 90 + fw, 120 + fh), int(S * 0.05),
                                            fill=(10, 0, 40, 140))
    ombra = ombra.filter(ImageFilter.GaussianBlur(S * 0.03))
    angolo = -8
    ombra = ombra.rotate(angolo, resample=Image.BICUBIC, expand=True)
    ruotata = foto.rotate(angolo, resample=Image.BICUBIC, expand=True)
    cx, cy = int(S * 0.47), int(S * 0.56)
    img.alpha_composite(ombra, (cx - ombra.width // 2, cy - ombra.height // 2))
    img.alpha_composite(ruotata, (cx - ruotata.width // 2, cy - ruotata.height // 2))

    # Scintille: la grande sull'angolo della foto, due piccole intorno.
    luce = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dl = ImageDraw.Draw(luce)
    scintilla(dl, S * 0.765, S * 0.255, S * 0.19, (255, 236, 150, 255))
    luce_blur = luce.filter(ImageFilter.GaussianBlur(S * 0.03))
    img = Image.alpha_composite(img, luce_blur)
    img = Image.alpha_composite(img, luce)
    top = ImageDraw.Draw(img)
    scintilla(top, S * 0.765, S * 0.255, S * 0.105, (255, 255, 255, 255))
    scintilla(top, S * 0.215, S * 0.235, S * 0.065, (255, 255, 255, 235))
    scintilla(top, S * 0.86, S * 0.60, S * 0.045, (180, 240, 255, 230))
    return img


def main():
    grande = disegna()
    png = grande.resize((1024, 1024), Image.LANCZOS)
    png.save(ROOT / "assets" / "ImageCreatorFree.png")
    png.resize((512, 512), Image.LANCZOS).save(ROOT / "site" / "public" / "img" / "icona.png")
    png.resize((180, 180), Image.LANCZOS).save(
        ROOT / "site" / "public" / "apple-touch-icon.png")
    formati = [(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    for dest in (ROOT / "assets" / "ImageCreatorFree.ico",
                 ROOT / "src" / "imagecreator" / "data" / "app.ico",
                 ROOT / "site" / "public" / "favicon.ico"):
        png.save(dest, sizes=formati)
    # Anteprima dei formati piccoli, per controllare che si legga.
    prova = Image.new("RGBA", (16 + 24 + 32 + 48 + 64 + 128 + 70, 140), (30, 30, 30, 255))
    x = 10
    for s in (16, 24, 32, 48, 64, 128):
        prova.alpha_composite(png.resize((s, s), Image.LANCZOS), (x, 6))
        x += s + 10
    prova.save(ROOT / "build" / "icona-prova.png")
    print("fatto")


if __name__ == "__main__":
    main()
