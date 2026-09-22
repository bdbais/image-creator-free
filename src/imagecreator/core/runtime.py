"""Preparazione dell'ambiente Python che esegue il modello.

La GUI è un eseguibile leggero: torch, diffusers e transformers vivono in un
ambiente separato sotto %LOCALAPPDATA%\\ImageCreatorFree\\runtime, creato al
primo avvio. Cosi' l'installer resta piccolo e un aggiornamento della GUI non
obbliga a riscaricare 3 GB di librerie.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from . import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Versione dello stack: cambiando questo numero il runtime viene rigenerato.
RUNTIME_VERSION = 3

EMBED_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

TORCH_INDEX = {
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cpu": "https://download.pytorch.org/whl/cpu",
}

BASE_PACKAGES = [
    "transformers>=5.17",
    "accelerate>=1.0",
    "safetensors",
    "pillow",
    "huggingface_hub>=0.30",
    "sentencepiece",
    "protobuf",
    "einops",
    "ftfy",
]

# La model card di Qwen-Image-2.1 chiede diffusers dal ramo di sviluppo:
# QwenImage21Pipeline non è ancora in una release su PyPI.
DIFFUSERS_SPEC = "git+https://github.com/huggingface/diffusers"

Log = Callable[[str], None]


class RuntimeError_(RuntimeError):
    """Errore di preparazione dell'ambiente, con messaggio già leggibile."""


def marker_path() -> Path:
    return config.runtime_dir() / "runtime.json"


def is_ready() -> bool:
    python = config.runtime_python()
    if not python.exists():
        return False
    try:
        data = json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("version") == RUNTIME_VERSION and data.get("ok") is True


def installed_info() -> dict:
    try:
        return json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def choose_torch_variant(requested: str = "auto") -> str:
    if requested in TORCH_INDEX:
        return requested
    gpu = config.detect_gpu()
    if not gpu["nvidia"]:
        return "cpu"
    return "cu124"


# --------------------------------------------------------------------- python base
def find_system_python() -> Path | None:
    """Un Python 3.10-3.13 già presente, se c'è: evita di scaricarne un altro."""
    candidates: list[str] = []
    try:
        out = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=15,
                             creationflags=NO_WINDOW)
        for line in out.stdout.splitlines():
            m = re.search(r"3\.(1[0-3])[^\s]*\s+(.+?python\.exe)", line, re.IGNORECASE)
            if m:
                candidates.append(m.group(2).strip())
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    if not config.IS_FROZEN:
        candidates.append(sys.executable)

    for path in candidates:
        p = Path(path.strip().strip('"'))
        if not p.exists():
            continue
        try:
            out = subprocess.run([str(p), "-c",
                                  "import sys;print('%d.%d' % sys.version_info[:2])"],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        version = out.stdout.strip()
        if re.fullmatch(r"3\.(10|11|12|13)", version):
            return p
    return None


def _download(url: str, dest: Path, log: Log) -> None:
    log("Scarico %s" % url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(dest, "wb") as fh:
        shutil.copyfileobj(response, fh)


def _bootstrap_embedded(log: Log) -> Path:
    """Nessun Python di sistema: scarica quello embeddable di python.org."""
    target = config.runtime_dir()
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / "python-embed.zip"
    _download(EMBED_URL, zip_path, log)
    log("Estraggo Python...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    zip_path.unlink(missing_ok=True)

    for pth in target.glob("python*._pth"):
        text = pth.read_text(encoding="utf-8")
        if "#import site" in text:
            pth.write_text(text.replace("#import site", "import site"), encoding="utf-8")
        elif "import site" not in text:
            pth.write_text(text.rstrip() + "\nimport site\n", encoding="utf-8")

    get_pip = target / "get-pip.py"
    _download(GET_PIP_URL, get_pip, log)
    python = target / "python.exe"
    _run([str(python), str(get_pip), "--no-warn-script-location"], log)
    get_pip.unlink(missing_ok=True)

    scripts = target / "Scripts"
    scripts.mkdir(exist_ok=True)
    shim = scripts / "python.exe"
    if not shim.exists():
        try:
            shim.hardlink_to(python)
        except (OSError, AttributeError):
            shutil.copy2(python, shim)
    return shim


def _run(cmd: list[str], log: Log, env: dict | None = None) -> None:
    log("> " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
        env=env or os.environ.copy(),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError_("Comando fallito (codice %s):\n%s" % (proc.returncode, " ".join(cmd)))


def install(log: Log, torch_variant: str = "auto",
            should_stop: Callable[[], bool] | None = None) -> dict:
    """Crea l'ambiente e installa lo stack. Solleva RuntimeError_ se fallisce."""
    variant = choose_torch_variant(torch_variant)
    runtime = config.runtime_dir()
    python = config.runtime_python()

    def stop_requested() -> bool:
        return bool(should_stop and should_stop())

    if not python.exists():
        base = find_system_python()
        if base is not None:
            log("Uso Python già installato: %s" % base)
            log("Creo l'ambiente in %s" % runtime)
            _run([str(base), "-m", "venv", str(runtime)], log)
        else:
            log("Nessun Python adatto sul sistema: ne scarico una copia dedicata.")
            _bootstrap_embedded(log)

    if not python.exists():
        raise RuntimeError_("Ambiente non creato: %s non esiste." % python)

    if stop_requested():
        raise RuntimeError_("Installazione interrotta.")

    _run([str(python), "-m", "pip", "install", "--upgrade", "pip", "wheel",
          "--no-warn-script-location"], log)

    log("")
    log("Installo PyTorch (%s). Sono circa 2,5 GB, ci vuole qualche minuto." % variant)
    _run([str(python), "-m", "pip", "install", "torch", "torchvision",
          "--index-url", TORCH_INDEX[variant], "--no-warn-script-location"], log)

    if stop_requested():
        raise RuntimeError_("Installazione interrotta.")

    log("")
    log("Installo transformers, accelerate e le altre librerie.")
    _run([str(python), "-m", "pip", "install", *BASE_PACKAGES,
          "--no-warn-script-location"], log)

    log("")
    log("Installo diffusers (versione di sviluppo, richiesta da Qwen-Image-2.1).")
    try:
        _run([str(python), "-m", "pip", "install", DIFFUSERS_SPEC,
              "--no-warn-script-location"], log)
    except RuntimeError_:
        log("Installazione da GitHub fallita (serve git?): provo la versione su PyPI.")
        _run([str(python), "-m", "pip", "install", "--upgrade", "diffusers",
              "--no-warn-script-location"], log)

    info = verify(log)
    info.update(version=RUNTIME_VERSION, ok=True, torch_variant=variant)
    marker_path().write_text(json.dumps(info, indent=2), encoding="utf-8")
    log("")
    log("Ambiente pronto.")
    return info


def verify(log: Log | None = None) -> dict:
    """Interroga il runtime: versioni, CUDA, presenza della pipeline Qwen."""
    python = config.runtime_python()
    code = (
        "import json,sys\n"
        "info={'python':sys.version.split()[0]}\n"
        "try:\n"
        "    import torch;info['torch']=torch.__version__;info['cuda']=torch.cuda.is_available()\n"
        "    info['gpu']=torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''\n"
        "except Exception as e: info['torch_error']=str(e)\n"
        "try:\n"
        "    import diffusers;info['diffusers']=diffusers.__version__\n"
        "    info['qwen_pipeline']=hasattr(diffusers,'QwenImage21Pipeline')\n"
        "except Exception as e: info['diffusers_error']=str(e)\n"
        "try:\n"
        "    import transformers;info['transformers']=transformers.__version__\n"
        "except Exception as e: info['transformers_error']=str(e)\n"
        "print(json.dumps(info))\n"
    )
    try:
        out = subprocess.run([str(python), "-c", code], capture_output=True, text=True,
                             timeout=300, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError_("Il runtime non risponde: %s" % exc)
    line = (out.stdout or "").strip().splitlines()
    if not line:
        raise RuntimeError_("Verifica fallita:\n%s" % (out.stderr or "")[-2000:])
    info = json.loads(line[-1])
    if log:
        log("Python %s | torch %s | CUDA %s | diffusers %s" % (
            info.get("python"), info.get("torch", "?"), info.get("cuda"),
            info.get("diffusers", "?")))
        if info.get("diffusers") and not info.get("qwen_pipeline"):
            log("Attenzione: questa diffusers non espone QwenImage21Pipeline; "
                "l'app userà la pipeline dichiarata dal modello.")
    return info


def model_cache_dir(settings) -> Path:
    home = settings.models_dir or os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(home) / "hub"


def model_is_downloaded(settings, model_id: str) -> bool:
    folder = "models--" + model_id.replace("/", "--")
    root = model_cache_dir(settings) / folder / "snapshots"
    if not root.is_dir():
        return False
    for snapshot in root.iterdir():
        if any(p.suffix == ".safetensors" for p in snapshot.rglob("*.safetensors")):
            return True
    return False


def model_size_on_disk(settings, model_id: str) -> float:
    folder = "models--" + model_id.replace("/", "--")
    root = model_cache_dir(settings) / folder
    if not root.is_dir():
        return 0.0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return round(total / 1024 ** 3, 1)


def uninstall_runtime() -> None:
    shutil.rmtree(config.runtime_dir(), ignore_errors=True)


def iter_lines(text: str) -> Iterable[str]:
    for line in text.splitlines():
        if line.strip():
            yield line
