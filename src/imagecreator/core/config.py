"""Percorsi, impostazioni persistenti e rilevamento dell'ambiente."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import APP_NAME, MODEL_ID, VIDEO_MODEL_ID

IS_FROZEN = getattr(sys, "frozen", False)
NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def silence_crash_dialogs() -> None:
    """Evita i popup di Windows quando un sottoprocesso va in errore.

    La modalità di errore si eredita nei figli: senza questo, un crash del
    motore mostrerebbe all'utente una finestra di sistema incomprensibile al
    posto del messaggio dell'applicazione.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    except (AttributeError, OSError):
        pass


def ensure_hidden_console() -> bool:
    """Dà al processo una console valida ma invisibile.

    L'eseguibile è compilato senza console: i processi che lancia ereditano
    handle non validi e alcune librerie native (transformers, caricando i
    modelli Qwen) vanno in errore di memoria prima ancora di partire.
    Allocare una console e nasconderne subito la finestra risolve, senza che
    all'utente compaia nulla.
    """
    if not IS_FROZEN or os.name != "nt":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if kernel32.GetConsoleWindow() != 0:
            return False            # una console c'è già
        if not kernel32.AllocConsole():
            return False
        finestra = kernel32.GetConsoleWindow()
        if finestra:
            ctypes.windll.user32.ShowWindow(finestra, 0)   # SW_HIDE
        return True
    except (AttributeError, OSError):
        return False


def app_dir() -> Path:
    """Cartella che contiene l'eseguibile (build) o la radice del repo (sviluppo)."""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """Impostazioni, storico e registro.

    Di norma sotto %LOCALAPPDATA%; la variabile ICF_DATA_DIR permette di
    spostare tutto su un altro disco quando quello di sistema è pieno.
    """
    scelta = os.environ.get("ICF_DATA_DIR", "").strip()
    d = Path(scelta) if scelta else Path(
        os.environ.get("LOCALAPPDATA") or str(Path.home())) / "ImageCreatorFree"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runtime_dir() -> Path:
    """Ambiente Python separato con torch + diffusers, creato al primo avvio.

    Occupa circa 5 GB: su richiesta può stare su un altro disco, perche' il
    disco di sistema spesso non ha spazio. La scelta è nelle impostazioni e
    viene letta dal file senza costruire un oggetto Settings, per non creare
    dipendenze circolari.
    """
    try:
        raw = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        scelto = (raw.get("runtime_dir") or "").strip()
        if scelto:
            return Path(scelto)
    except (OSError, ValueError):
        pass
    return data_dir() / "runtime"


def runtime_python() -> Path:
    """L'interprete del runtime: venv (Scripts) o copia embeddable (radice)."""
    venv = runtime_dir() / "Scripts" / "python.exe"
    if venv.exists():
        return venv
    embedded = runtime_dir() / "python.exe"
    return embedded if embedded.exists() else venv


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
    except OSError as exc:
        if not target.exists():
            raise RuntimeError(
                "Non riesco a scrivere %s: %s" % (target, exc)) from exc
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


# Video con Wan2.2 TI2V-5B: 480p e 704p sono le misure della scheda del modello,
# 24 fotogrammi al secondo. I passi sono meno dei 50 consigliati: su una scheda
# da 12 GB ogni passo pesa, e la differenza di qualita' e' piccola.
VIDEO_QUALITY = {
    "draft": {"pixels": 832 * 480, "steps": 20},
    "standard": {"pixels": 832 * 480, "steps": 30},
    "high": {"pixels": 1280 * 704, "steps": 40},
}
VIDEO_FPS = 24


def video_resolution(aspect: str, quality: str) -> tuple[int, int]:
    """Stessa proporzione delle immagini, area fissata dalla qualita', lati multipli di 32."""
    w, h = ASPECT_RATIOS.get(aspect, ASPECT_RATIOS["16:9"])
    area = VIDEO_QUALITY.get(quality, VIDEO_QUALITY["standard"])["pixels"]
    ratio = w / h
    width = round((area * ratio) ** 0.5 / 32) * 32
    height = round((area / ratio) ** 0.5 / 32) * 32
    return max(256, width), max(256, height)


def video_frames(seconds: float) -> int:
    """Wan vuole 4k+1 fotogrammi."""
    frames = int(round(seconds * VIDEO_FPS))
    return max(5, frames // 4 * 4 + 1)


@dataclass
class Settings:
    model_id: str = MODEL_ID
    video_model_id: str = VIDEO_MODEL_ID
    runtime_dir: str = ""             # vuoto = dentro %LOCALAPPDATA%
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
    current_project: str = ""         # id del progetto aperto all'ultima chiusura

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
        """La cartella delle immagini, con ritorno alla predefinita se non si puo' usare."""
        for candidate in (Path(self.output_dir or default_output_dir()), default_output_dir()):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue
        return Path.home()

    def env_for_worker(self) -> dict:
        from . import runtime

        env = runtime.clean_env()
        if self.models_dir:
            # Solo la cache dei modelli: spostando HF_HOME si sposterebbe anche
            # il token di Hugging Face, e senza token il Hub limita la banda.
            env["HF_HUB_CACHE"] = self.models_dir
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        # Trasferimento ad alte prestazioni di Xet: i 33 GB del modello sono la
        # parte piu' lenta del primo avvio.
        env["HF_XET_HIGH_PERFORMANCE"] = "1"
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


def drive_media_type(path: Path) -> str:
    """"SSD", "HDD" o "" se non si riesce a stabilirlo.

    Il modello pesa 33 GB e viene riletto a ogni caricamento: su un disco
    meccanico il solo caricamento richiede ore, quindi vale la pena avvisare
    prima che l'utente scelga dove metterlo.
    """
    drive = str(Path(path).anchor).rstrip("\\/")
    if not drive:
        return ""
    script = (
        "$p = Get-Partition -DriveLetter %s -ErrorAction Stop;"
        "$d = Get-PhysicalDisk | Where-Object DeviceId -eq "
        "(Get-Disk -Number $p.DiskNumber).Number;"
        "Write-Output $d.MediaType" % drive[0]
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=25, creationflags=NO_WINDOW_FLAG)
    except (OSError, subprocess.SubprocessError):
        return ""
    value = (out.stdout or "").strip().upper()
    return value if value in ("SSD", "HDD") else ""


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

    candidati = []
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZC":
        drive = Path("%s:\\" % letter)
        if not drive.exists() or not is_fixed_drive(drive):
            continue
        free = free_disk_gb(drive)
        if free >= MODEL_SIZE_GB + 8:
            # A parita' di spazio un SSD vale molto di piu': il modello viene
            # riletto per intero a ogni caricamento.
            candidati.append((drive_media_type(drive) == "SSD", free, drive))
    if not candidati:
        return ""
    _, _, drive = max(candidati)
    return str(drive / "ImageCreatorFree" / "modelli")


def free_memory_gb() -> float:
    """Memoria che si può ancora impegnare (RAM + file di paging), in GB.

    Con lo scarico su CPU tutto il modello passa dalla RAM: se il sistema non
    ha abbastanza memoria impegnabile, torch non segnala l'errore ma il
    processo muore con 0xC0000005.
    """
    import ctypes

    class _Stato(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    try:
        stato = _Stato()
        stato.dwLength = ctypes.sizeof(stato)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stato)):
            return 0.0
        return round(stato.ullAvailPageFile / 1024 ** 3, 1)
    except (AttributeError, OSError):
        return 0.0


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
