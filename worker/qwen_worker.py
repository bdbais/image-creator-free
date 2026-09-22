# -*- coding: utf-8 -*-
"""Processo di generazione per Image Creator Free.

Gira nell'ambiente Python separato creato dall'applicazione (torch + diffusers)
e parla con la GUI via JSON Lines: una richiesta per riga su stdin, eventi su
stdout. Il modello resta caricato tra una generazione e l'altra.

Comandi:  {"cmd":"load"} {"cmd":"generate", ...} {"cmd":"cancel"} {"cmd":"shutdown"}
Eventi:   hello, status, loaded, progress, image, done, error, bye
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from queue import Queue

MODEL_ID = os.environ.get("ICF_MODEL_ID", "Qwen/Qwen-Image-2.1")

_out_lock = threading.Lock()
_cancel = threading.Event()


def emit(event, **data):
    data["ev"] = event
    line = json.dumps(data, ensure_ascii=False)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


class Cancelled(Exception):
    pass


class Engine:
    def __init__(self):
        self.pipe = None
        self.memory_mode = "auto"
        self.device = "cpu"
        self.vram_gb = 0.0

    # ---------------------------------------------------------------- caricamento
    def probe(self):
        import torch
        info = {
            "torch": torch.__version__,
            "cuda": bool(torch.cuda.is_available()),
            "device_name": "",
            "vram_gb": 0.0,
        }
        if info["cuda"]:
            props = torch.cuda.get_device_properties(0)
            info["device_name"] = props.name
            info["vram_gb"] = round(props.total_memory / 1024 ** 3, 1)
        self.vram_gb = info["vram_gb"]
        return info

    def _resolve_mode(self, requested):
        if requested != "auto":
            return requested
        # Vedi la nota in core/config.py: il modulo piu' grande pesa 17,5 GB.
        if self.vram_gb >= 40:
            return "high"
        if self.vram_gb >= 20:
            return "balanced"
        return "low"

    def load(self, model_id=MODEL_ID, memory_mode="auto"):
        import torch

        if self.pipe is not None and memory_mode == self.memory_mode:
            emit("loaded", model=model_id, memory_mode=self.memory_mode,
                 device=self.device, cached=True)
            return

        info = self.probe()
        mode = self._resolve_mode(memory_mode)
        dtype = torch.bfloat16 if info["cuda"] else torch.float32

        emit("status", msg="Carico il modello (al primo avvio scarica circa 33 GB)...",
             stage="load", model=model_id, memory_mode=mode)

        pipe = self._from_pretrained(model_id, dtype)

        if not info["cuda"]:
            self.device = "cpu"
            emit("status", msg="Nessuna GPU NVIDIA: uso la CPU, sarà molto lento.", stage="load")
        elif mode == "high":
            pipe.to("cuda")
            self.device = "cuda"
        elif mode == "low":
            _try(getattr(pipe, "enable_sequential_cpu_offload", None))
            self.device = "cuda (offload sequenziale)"
        else:
            _try(getattr(pipe, "enable_model_cpu_offload", None))
            self.device = "cuda (offload dei moduli)"

        if mode != "high":
            for name in ("enable_vae_slicing", "enable_vae_tiling"):
                _try(getattr(pipe, name, None))
        _try(getattr(pipe, "enable_attention_slicing", None))

        self.pipe = pipe
        self.memory_mode = memory_mode
        emit("loaded", model=model_id, memory_mode=mode, device=self.device,
             vram_gb=info["vram_gb"], torch=info["torch"], cached=False)

    @staticmethod
    def _from_pretrained(model_id, dtype):
        """QwenImage21Pipeline se c'è, altrimenti la pipeline dichiarata dal modello."""
        errors = []
        try:
            from diffusers import QwenImage21Pipeline  # type: ignore
            return QwenImage21Pipeline.from_pretrained(model_id, torch_dtype=dtype)
        except Exception as exc:  # noqa: BLE001 - diffusers vecchio o classe assente
            errors.append("QwenImage21Pipeline: %s" % exc)
        from diffusers import DiffusionPipeline
        try:
            return DiffusionPipeline.from_pretrained(model_id, torch_dtype=dtype)
        except Exception as exc:  # noqa: BLE001
            errors.append("DiffusionPipeline: %s" % exc)
            raise RuntimeError(
                "Impossibile costruire la pipeline di %s.\n%s" % (model_id, "\n".join(errors)))

    # ---------------------------------------------------------------- generazione
    def generate(self, req):
        import torch
        from PIL import Image

        if self.pipe is None:
            self.load(req.get("model", MODEL_ID), req.get("memory_mode", "auto"))

        job = req.get("id", "job")
        steps = int(req.get("steps", 30))
        batch = max(1, int(req.get("batch", 1)))
        out_dir = req.get("out_dir") or os.getcwd()
        os.makedirs(out_dir, exist_ok=True)
        basename = req.get("basename") or time.strftime("%Y%m%d-%H%M%S")

        refs = []
        for path in req.get("images", []) or []:
            try:
                refs.append(Image.open(path).convert("RGB"))
            except OSError as exc:
                emit("error", id=job,
                     msg="Immagine di riferimento non leggibile: %s (%s)" % (path, exc))
                return

        seed = req.get("seed")
        if seed in (None, "", -1):
            seed = int.from_bytes(os.urandom(4), "little")
        seed = int(seed)

        for index in range(batch):
            if _cancel.is_set():
                break
            run_seed = seed + index
            device = "cuda" if torch.cuda.is_available() else "cpu"
            generator = torch.Generator(device=device).manual_seed(run_seed)

            kwargs = {
                "prompt": req.get("prompt", ""),
                "negative_prompt": req.get("negative_prompt") or " ",
                "num_inference_steps": steps,
                "true_cfg_scale": float(req.get("true_cfg_scale", 4.0)),
                "generator": generator,
                "num_images_per_prompt": 1,
            }
            if refs:
                kwargs["image"] = refs if len(refs) > 1 else refs[0]
            else:
                kwargs["width"] = int(req.get("width", 1024))
                kwargs["height"] = int(req.get("height", 1024))

            kwargs["callback_on_step_end"] = _make_callback(job, index, batch, steps)
            kwargs = _filter_kwargs(self.pipe, kwargs)

            started = time.time()
            emit("progress", id=job, index=index, batch=batch, step=0, total=steps,
                 msg="Generazione %d di %d" % (index + 1, batch))
            try:
                result = self.pipe(**kwargs)
            except Cancelled:
                emit("status", id=job, msg="Generazione annullata.", stage="cancelled")
                break
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                emit("error", id=job, kind="oom", msg=(
                    "VRAM esaurita. Riduci la risoluzione o scegli una modalità di memoria "
                    "più conservativa nelle impostazioni."))
                return
            except Exception as exc:  # noqa: BLE001 - riportiamo tutto alla GUI
                emit("error", id=job, msg=str(exc), trace=traceback.format_exc())
                return

            image = result.images[0]
            suffix = "" if batch == 1 else "-%d" % (index + 1)
            path = os.path.join(out_dir, "%s%s.png" % (basename, suffix))
            meta = {
                "prompt": req.get("prompt", ""),
                "negative_prompt": req.get("negative_prompt", ""),
                "seed": run_seed,
                "steps": steps,
                "true_cfg_scale": req.get("true_cfg_scale", 4.0),
                "model": req.get("model", MODEL_ID),
                "size": "%dx%d" % image.size,
                "references": len(refs),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _save_png(image, path, meta)
            emit("image", id=job, index=index, path=path, seed=run_seed,
                 elapsed=round(time.time() - started, 1), meta=meta)

        _cancel.clear()
        emit("done", id=job)


def _save_png(image, path, meta):
    """Salva conservando l'alpha (il modello genera anche RGBA) e i parametri."""
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", json.dumps(meta, ensure_ascii=False))
    info.add_text("Software", "Image Creator Free - Qwen-Image-2.1")
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    image.save(path, "PNG", pnginfo=info)


def _filter_kwargs(pipe, kwargs):
    """Tiene solo gli argomenti che questa versione della pipeline accetta."""
    import inspect

    try:
        sig = inspect.signature(type(pipe).__call__)
    except (TypeError, ValueError):
        return kwargs
    params = sig.parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    dropped = [k for k in kwargs if k not in params]
    if dropped:
        emit("status", stage="compat",
             msg="Parametri ignorati da questa pipeline: %s" % ", ".join(dropped))
    return dict((k, v) for k, v in kwargs.items() if k in params)


def _make_callback(job, index, batch, total):
    def callback(pipe, step, timestep, callback_kwargs):
        if _cancel.is_set():
            raise Cancelled()
        emit("progress", id=job, index=index, batch=batch, step=step + 1, total=total)
        return callback_kwargs
    return callback


def _try(fn):
    if fn is None:
        return False
    try:
        fn()
        return True
    except Exception:  # noqa: BLE001 - ottimizzazioni opzionali
        return False


def _incoming():
    """Comandi in arrivo, letti da un thread a parte.

    Durante una generazione il thread principale e' dentro la pipeline e non
    puo' leggere stdin: senza questo lettore separato, "annulla" arriverebbe
    solo a lavoro finito. Cancel e shutdown agiscono subito sui flag; gli altri
    comandi aspettano il loro turno in coda.
    """
    queue = Queue()

    def reader():
        # readline() esplicita: la GUI tiene stdin aperto per tutta la sessione
        # e i comandi devono essere consegnati uno alla volta, senza aspettare
        # che chi scrive chiuda il canale.
        while True:
            raw = sys.stdin.readline()
            if not raw:
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                req = json.loads(raw)
            except ValueError:
                emit("error", msg="Comando non valido: %s" % raw[:200])
                continue
            if req.get("cmd") == "cancel":
                _cancel.set()
                continue
            if req.get("cmd") == "shutdown":
                _cancel.set()   # una generazione in corso si ferma al passo successivo
            queue.put(req)
        queue.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    while True:
        req = queue.get()
        if req is None:
            return
        yield req


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    if os.environ.get("HF_HUB_ENABLE_HF_TRANSFER") == "1":
        try:
            import hf_transfer  # noqa: F401
        except ImportError:
            # Senza la libreria, huggingface_hub si rifiuterebbe di partire.
            os.environ.pop("HF_HUB_ENABLE_HF_TRANSFER", None)

    engine = Engine()
    emit("hello", pid=os.getpid(), python=sys.version.split()[0], model=MODEL_ID)

    for req in _incoming():
        cmd = req.get("cmd")
        try:
            if cmd == "load":
                engine.load(req.get("model", MODEL_ID), req.get("memory_mode", "auto"))
            elif cmd == "generate":
                _cancel.clear()
                engine.generate(req)
            elif cmd == "probe":
                emit("probe", **engine.probe())
            elif cmd == "shutdown":
                break
            else:
                emit("error", msg="Comando sconosciuto: %s" % cmd)
        except Cancelled:
            emit("status", msg="Annullato.", stage="cancelled")
        except Exception as exc:  # noqa: BLE001 - il worker non muore mai in silenzio
            emit("error", id=req.get("id"), msg=str(exc), trace=traceback.format_exc())

    emit("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
