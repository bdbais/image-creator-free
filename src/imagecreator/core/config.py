"""Percorsi, impostazioni persistenti e rilevamento dell'ambiente."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import APP_NAME, MODEL_ID

IS_FROZEN = getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Cartella che contiene l'eseguibile (build) o la radice del repo (sviluppo)."""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "ImageCreatorFree"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runtime_dir() -> Path:
    """Ambiente Python separato con torch + diffusers, creato al primo avvio."""
    return data_dir() / "runtime"


def runtime_python() -> Path:
    return runtime_dir() / "Scripts" / "python.exe"


def worker_script() -> Path:
    """Il worker gira con il Python del runtime, quindi vive come file su disco.

    In sviluppo si usa il sorgente del repo; nell'eseguibile viene estratto una
    volta dal bundle in %LOCALAPPDATA%, così la versione portatile è un file solo.
    """
    if not IS_FROZEN:
        return app_dir() / "worker" / "qwen_worker.py"

    target = data_dir() / "worker" / "qwen_worker.py"
    source = resource("data", "qwen_worker.py")
    try:
        bundled = source.read_bytes()
        if not target.exists() or target.read_bytes() != bundled:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundled)
    except OSError:
        pass
    return target


def default_output_dir() -> Path:
    pics = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures"
    return (pics if pics.exists() else Path.home()) / "Image Creator Free"


def resource(*parts: str) -> Path:
    """File di dati (presets, icone): dentro il bundle PyInstaller o nel repo."""
    if IS_FROZEN and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / Path(*parts)
    return Path(__file__).resolve().parents[1] / Path(*parts)


ASPECT_RATIOS = {
    "1:1": (2048, 2048),
    "4:3": (2400, 1792),
    "3:4": (1792, 2400),
    "3:2": (2528, 1696),
    "2:3": (1696, 2528),
    "16:9": (2752, 1536),
    "9:16": (1536, 2752),
}

# Le dimensioni della model card sono pensate per schede da 24 GB e oltre.
# Su GPU più piccole la stessa proporzione viene scalata.
QUALITY = {
    "draft": {"label": "Bozza - veloce", "scale": 0.5, "steps": 20},
    "standard": {"label": "Standard", "scale": 0.75, "steps": 30},
    "high": {"label": "Alta - come la demo ufficiale", "scale": 1.0, "steps": 40},
}

MEMORY_MODES = {
    "auto": "Automatico (in base alla VRAM)",
    "high": "Tutto in VRAM (24 GB o più)",
    "balanced": "Offload dei moduli su CPU (12-16 GB)",
    "low": "Offload sequenziale (8-10 GB, lento)",
}


def resolution_for(aspect: str, quality: str) -> tuple[int, int]:
    w, h = ASPECT_RATIOS.get(aspect, ASPECT_RATIOS["1:1"])
    scale = QUALITY.get(quality, QUALITY["standard"])["scale"]
    # I modelli DiT vogliono lati multipli di 64.
    return (max(512, int(w * scale) // 64 * 64), max(512, int(h * scale) // 64 * 64))


@dataclass
class Settings:
    model_id: str = MODEL_ID
    models_dir: str = ""              # vuoto = cache Hugging Face predefinita
    output_dir: str = ""
    memory_mode: str = "auto"
    quality: str = "standard"
    aspect: str = "1:1"
    steps: int = 0                    # 0 = usa il valore della qualità scelta
    true_cfg_scale: float = 4.0
    negative_prompt: str = ""
    last_prompt: str = ""
    keep_model_loaded: bool = True
    setup_done: bool = False
    accepted_license: bool = False
    torch_variant: str = "auto"       # auto | cu124 | cu121 | cpu
    recent_seeds: list[int] = field(default_factory=list)

    @classmethod
    def path(cls) -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        for k, v in raw.items():
            if hasattr(s, k):
                setattr(s, k, v)
        if not s.output_dir:
            s.output_dir = str(default_output_dir())
        return s

    def save(self) -> None:
        try:
            self.path().write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def out_path(self) -> Path:
        p = Path(self.output_dir or default_output_dir())
        p.mkdir(parents=True, exist_ok=True)
        return p

    def env_for_worker(self) -> dict:
        env = dict(os.environ)
        if self.models_dir:
            env["HF_HOME"] = self.models_dir
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        # Download in parallelo: i 33 GB del modello sono la parte piu' lenta
        # del primo avvio. Il worker la disattiva da se' se la libreria manca.
        env["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
        return env


def detect_gpu() -> dict:
    """VRAM e nome GPU via nvidia-smi: serve prima che il runtime esista."""
    info = {"name": "", "vram_gb": 0.0, "nvidia": False}
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if out.returncode == 0 and out.stdout.strip():
            name, mem = out.stdout.strip().splitlines()[0].split(",")
            info.update(name=name.strip(), vram_gb=round(float(mem) / 1024, 1), nvidia=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return info


def suggest_memory_mode(vram_gb: float) -> str:
    if vram_gb >= 40:
        return "high"
    if vram_gb >= 20:
        return "balanced"
    return "low"


MODEL_SIZE_GB = 33.0


def is_fixed_drive(drive: Path) -> bool:
    """Solo dischi interni: niente chiavette, unita' di rete o dischi ottici."""
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(str(drive)) == 3  # DRIVE_FIXED
    except (AttributeError, OSError):
        return True


def default_hf_home() -> Path:
    home = os.environ.get("HF_HOME")
    return Path(home) if home else Path.home() / ".cache" / "huggingface"


def best_models_dir() -> str:
    """Dove proporre di tenere i 33 GB del modello.

    Se il disco della cache di Hugging Face non ha spazio a sufficienza cerca
    il disco fisso piu' capiente: sui portatili il disco di sistema e' spesso
    piccolo, e un download interrotto a meta' e' la delusione peggiore.
    """
    default = default_hf_home()
    if free_disk_gb(default) >= MODEL_SIZE_GB + 8:
        return ""

    best, best_free = "", 0.0
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZC":
        drive = Path("%s:\\" % letter)
        if not drive.exists() or not is_fixed_drive(drive):
            continue
        free = free_disk_gb(drive)
        if free > best_free:
            best, best_free = str(drive / "ImageCreatorFree" / "modelli"), free
    return best if best_free >= MODEL_SIZE_GB + 8 else ""


def free_disk_gb(path: Path) -> float:
    try:
        import shutil
        target = path
        while not target.exists() and target.parent != target:
            target = target.parent
        return round(shutil.disk_usage(str(target)).free / 1024 ** 3, 1)
    except OSError:
        return 0.0


APP_TITLE = APP_NAME
