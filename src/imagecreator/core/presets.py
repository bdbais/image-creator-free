"""Gli esempi ufficiali di Qwen-Image-2.1 (model card + demo Hugging Face)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import config


@dataclass
class Preset:
    id: str
    title_it: str
    title_en: str
    title_zh: str
    mode: str          # "t2i" oppure "edit"
    refs: int          # immagini di riferimento richieste dall'esempio
    aspect: str
    prompt: str
    source: str        # "model-card" o "demo-space"

    @property
    def label(self) -> str:
        return self.title_it

    @property
    def badge(self) -> str:
        if self.mode == "t2i":
            return "testo"
        return "1 immagine" if self.refs == 1 else "%d immagini" % self.refs

    @property
    def is_rgba(self) -> bool:
        text = self.prompt.lower()
        return "rgba" in text or "transpar" in text or "alpha" in text


def load() -> list[Preset]:
    path = config.resource("data", "presets.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for item in raw.get("presets", []):
        out.append(Preset(
            id=item.get("id", ""),
            title_it=item.get("title_it") or item.get("title_en", ""),
            title_en=item.get("title_en", ""),
            title_zh=item.get("title_zh", ""),
            mode=item.get("mode", "t2i"),
            refs=int(item.get("refs", 0)),
            aspect=item.get("aspect", "1:1"),
            prompt=item.get("prompt", ""),
            source=item.get("source", ""),
        ))
    return out


def grouped(presets: list[Preset]) -> dict[str, list[Preset]]:
    groups: dict[str, list[Preset]] = {
        "Da testo": [],
        "Con trasparenza (RGBA)": [],
        "Modifica di immagini": [],
    }
    for p in presets:
        if p.mode == "edit":
            groups["Modifica di immagini"].append(p)
        elif p.is_rgba:
            groups["Con trasparenza (RGBA)"].append(p)
        else:
            groups["Da testo"].append(p)
    return {k: v for k, v in groups.items() if v}
