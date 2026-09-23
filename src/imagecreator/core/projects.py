"""Progetti: un insieme di parametri da cui si generano immagini, anche piu' volte.

Ogni progetto e' un file JSON in <dati>/progetti e ha una sua cartella dentro
quella delle immagini. Le immagini portano con se' i parametri con cui sono
nate, cosi' si possono cambiare quelli del progetto senza perdere la storia.
Clonare copia i parametri in un progetto nuovo e vuoto: si cambia qualcosa e
si rigenera, lasciando intatto l'originale.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config

# Parametri del modulo che un progetto ricorda.
PARAM_KEYS = ("prompt", "negative_prompt", "aspect", "quality", "steps",
              "true_cfg_scale", "seed", "batch", "refs")


def default_params() -> dict:
    return {"prompt": "", "negative_prompt": "", "aspect": "1:1", "quality": "standard",
            "steps": 0, "true_cfg_scale": 4.0, "seed": None, "batch": 1, "refs": []}


@dataclass
class Project:
    id: str
    name: str
    created: str
    updated: str
    params: dict = field(default_factory=default_params)
    images: list[dict] = field(default_factory=list)
    parent: str = ""             # id del progetto da cui e' stato clonato

    @property
    def cover(self) -> str:
        """L'ultima immagine ancora su disco, per la miniatura nell'elenco."""
        for entry in reversed(self.images):
            if Path(entry.get("path", "")).exists():
                return entry["path"]
        return ""


def folder() -> Path:
    d = config.data_dir() / "progetti"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file(project_id: str) -> Path:
    return folder() / ("%s.json" % project_id)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def slug(text: str, limit: int = 32) -> str:
    """Nome sicuro per una cartella: minuscolo, senza accenti, trattini."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:limit].strip("-") or "progetto"


def name_from_prompt(prompt: str, words: int = 6) -> str:
    parole = prompt.split()
    nome = " ".join(parole[:words])
    if len(parole) > words:
        nome += "..."
    return nome or "Progetto senza nome"


def _clean_params(params: dict) -> dict:
    out = default_params()
    for key in PARAM_KEYS:
        if key in params:
            out[key] = params[key]
    out["refs"] = [str(p) for p in (out.get("refs") or [])]
    return out


def create(name: str, params: dict | None = None, parent: str = "") -> Project:
    adesso = _now()
    base = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), slug(name))
    project_id, n = base, 2
    while _file(project_id).exists():
        project_id = "%s-%d" % (base, n)
        n += 1
    project = Project(id=project_id, name=name.strip() or "Progetto senza nome",
                      created=adesso, updated=adesso,
                      params=_clean_params(params or {}), parent=parent)
    save(project)
    return project


def save(project: Project) -> None:
    project.updated = _now()
    project.params = _clean_params(project.params)
    tmp = _file(project.id).with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(project), indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(_file(project.id))


def load(project_id: str) -> Project | None:
    try:
        raw = json.loads(_file(project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Project(id=raw.get("id", project_id), name=raw.get("name", project_id),
                   created=raw.get("created", ""), updated=raw.get("updated", ""),
                   params=_clean_params(raw.get("params", {})),
                   images=list(raw.get("images", [])), parent=raw.get("parent", ""))


def list_all() -> list[Project]:
    """Tutti i progetti, dal piu' recente."""
    out = []
    for path in folder().glob("*.json"):
        project = load(path.stem)
        if project is not None:
            out.append(project)
    out.sort(key=lambda p: p.updated, reverse=True)
    return out


def clone(project: Project, name: str = "", params: dict | None = None) -> Project:
    """Nuovo progetto con gli stessi parametri (o con quelli dati) e nessuna immagine."""
    nome = name.strip() or "%s (copia)" % project.name
    return create(nome, dict(params if params is not None else project.params),
                  parent=project.id)


def rename(project: Project, name: str) -> None:
    project.name = name.strip() or project.name
    save(project)


def delete(project: Project, with_images: bool = False) -> None:
    """Toglie il progetto dall'elenco; le immagini restano, se non si chiede altro."""
    if with_images:
        shutil.rmtree(output_dir(project), ignore_errors=True)
    _file(project.id).unlink(missing_ok=True)


def output_dir(project: Project, settings=None) -> Path:
    """La cartella delle immagini del progetto, dentro quella scelta dall'utente."""
    settings = settings or config.Settings.load()
    return settings.out_path() / project.id


def keep_refs(project: Project, settings=None) -> list[str]:
    """Copia nel progetto le immagini di riferimento che stanno altrove.

    Cosi' rigenerare funziona anche se gli originali vengono spostati.
    """
    dest = output_dir(project, settings) / "riferimenti"
    out = []
    for ref in project.params.get("refs") or []:
        src = Path(ref)
        if not src.exists():
            continue
        if dest in src.parents:
            out.append(str(src))
            continue
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / src.name
        n = 2
        while target.exists() and target.read_bytes() != src.read_bytes():
            target = dest / ("%s-%d%s" % (src.stem, n, src.suffix))
            n += 1
        if not target.exists():
            shutil.copy2(src, target)
        out.append(str(target))
    project.params["refs"] = out
    return out


def add_image(project: Project, entry: dict, params: dict) -> None:
    """Registra un'immagine con i parametri del modulo al momento del clic."""
    record = dict(entry)
    record["params"] = _clean_params(params)
    project.images.append(record)
    save(project)


def images_on_disk(project: Project) -> list[dict]:
    return [e for e in project.images if Path(e.get("path", "")).exists()]
