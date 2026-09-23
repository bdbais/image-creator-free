"""Esempi di prompt: quelli ufficiali di Qwen-Image-2.1, i nostri e quelli gia' usati."""
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
    source: str        # "model-card", "demo-space", "image-creator-free" o "storico"
    group: str = ""    # gruppo esplicito; vuoto = deciso da modo e trasparenza

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


FILES = ("presets.json", "presets_extra.json")


def load() -> list[Preset]:
    out = []
    for name in FILES:
        path = config.resource("data", name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
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
                group=item.get("group", ""),
            ))
    return out


def from_history(limit: int = 40) -> list[Preset]:
    """I prompt gia' usati, dal piu' recente, senza doppioni.

    Vengono dai progetti (che ricordano anche formato e riferimenti) e dallo
    storico delle immagini, che copre anche quelle nate prima dei progetti.
    """
    from . import history, projects

    visti: set[str] = set()
    out: list[Preset] = []
    candidati = []
    for project in projects.list_all():
        candidati.append((project.updated, project.params))
        for image in project.images:
            if image.get("params"):
                candidati.append((image.get("meta", {}).get("created", ""), image["params"]))
    for entry in history.load(500):
        meta = entry.get("meta", {})
        candidati.append((meta.get("created", ""),
                          {"prompt": meta.get("prompt", ""),
                           "refs": [None] * int(meta.get("references") or 0)}))
    candidati.sort(key=lambda c: c[0] or "", reverse=True)
    for _, params in candidati:
        prompt = (params.get("prompt") or "").strip()
        chiave = " ".join(prompt.lower().split())
        if not prompt or chiave in visti:
            continue
        visti.add(chiave)
        refs = len(params.get("refs") or [])
        aspect = params.get("aspect") if params.get("aspect") in config.ASPECT_RATIOS else "1:1"
        out.append(Preset(id="storico-%d" % len(out), title_it=projects.name_from_prompt(prompt, 7),
                          title_en="", title_zh="", mode="edit" if refs else "t2i",
                          refs=refs, aspect=aspect, prompt=prompt, source="storico",
                          group=MY_PROMPTS))
        if len(out) >= limit:
            break
    return out


MY_PROMPTS = "I tuoi prompt"


def grouped(presets: list[Preset]) -> dict[str, list[Preset]]:
    groups: dict[str, list[Preset]] = {
        MY_PROMPTS: [],
        "Restauro foto": [],
        "Scene complesse": [],
        "Da testo": [],
        "Con trasparenza (RGBA)": [],
        "Modifica di immagini": [],
    }
    for p in presets:
        if p.group:
            groups.setdefault(p.group, []).append(p)
        elif p.mode == "edit":
            groups["Modifica di immagini"].append(p)
        elif p.is_rgba:
            groups["Con trasparenza (RGBA)"].append(p)
        else:
            groups["Da testo"].append(p)
    return {k: v for k, v in groups.items() if v}
