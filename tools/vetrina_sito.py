# -*- coding: utf-8 -*-
"""Prepara le immagini della vetrina per il sito e riempie galleria, restauro e tempi.

Legge vetrina.json e restauro.json scritti dagli script di generazione, salva in
site/public/img/vetrina versioni WebP leggere (grande e miniatura) e sostituisce
i segnaposto <!--GALLERIA-->, <!--RESTAURO--> e <!--TEMPI--> in index.html.

    python tools/vetrina_sito.py V:\\ImageCreatorFree\\immagini\\vetrina
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "site" / "public"
DEST = PUBLIC / "img" / "vetrina"


def webp(src: Path, nome: str, lato: int, qualita: int = 82) -> str:
    im = Image.open(src)
    im.thumbnail((lato, lato), Image.LANCZOS)
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    DEST.mkdir(parents=True, exist_ok=True)
    dest = DEST / ("%s.webp" % nome)
    im.save(dest, "WEBP", quality=qualita, method=6)
    return "img/vetrina/%s" % dest.name


def durata(secondi: int) -> str:
    m, s = divmod(int(secondi), 60)
    return "%d min %02d s" % (m, s) if m else "%d s" % s


def main(cartella: Path):
    index = PUBLIC / "index.html"
    pagina = index.read_text(encoding="utf-8")

    voci = json.loads((cartella / "vetrina.json").read_text(encoding="utf-8"))
    figure, tempi = [], []
    for v in voci:
        if not v.get("path"):
            continue
        src = Path(v["path"])
        grande = webp(src, v["id"], 1400)
        mini = webp(src, v["id"] + "-mini", 640, 78)
        w, h = Image.open(src).size
        passi = 24
        figure.append(
            '        <figure>\n'
            '          <a class="img" href="%s"><img src="%s" alt="%s" width="%d" height="%d" loading="lazy"></a>\n'
            '          <figcaption><strong>%s</strong>\n'
            '            <div class="meta">%dx%d · %d passi · %s su RTX 4070</div>\n'
            '            <details><summary>Il prompt</summary><p>%s</p></details></figcaption>\n'
            '        </figure>' % (grande, mini, html.escape(v["title"]), w, h,
                                  html.escape(v["title"]), w, h, passi,
                                  durata(v["seconds"]), html.escape(v["prompt"])))
        tempi.append('        <tr><th>%s, %dx%d, %d passi</th><td>%s — %.1f s per passo</td></tr>' % (
            html.escape(v["title"]), w, h, passi, durata(v["seconds"]), v["seconds"] / passi))
    pagina = pagina.replace("<!--GALLERIA-->", "\n".join(figure))
    pagina = pagina.replace("<!--TEMPI-->", "\n".join(tempi[:2]))

    r_file = cartella / "restauro.json"
    if r_file.exists():
        r = json.loads(r_file.read_text(encoding="utf-8"))
        blocchi = []
        for chiave, titolo, testo in (
                ("rovinata", "Prima", "la stampa rovinata: graffi, piega, macchie, angolo strappato"),
                ("restaurata", "Dopo", "restaurata dal modello in %s" % durata(r["secondi"])),
                ("originale", "Riferimento", "il ritratto inventato da cui è partita la demo")):
            if not r.get(chiave):
                continue
            url = webp(Path(r[chiave]), "restauro-" + chiave, 900, 84)
            blocchi.append('        <figure><img src="%s" alt="%s" loading="lazy">'
                           '<figcaption><b>%s</b> — %s</figcaption></figure>'
                           % (url, html.escape(titolo + ": " + testo), titolo, testo))
        pagina = pagina.replace("<!--RESTAURO-->", "\n".join(blocchi))
    index.write_text(pagina, encoding="utf-8")
    print("galleria: %d immagini" % len(figure))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
