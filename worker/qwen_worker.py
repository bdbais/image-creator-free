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
VIDEO_MODEL_ID = os.environ.get("ICF_VIDEO_MODEL_ID", "Wan-AI/Wan2.2-TI2V-5B-Diffusers")
VIDEO_NEGATIVE = ("Bright tones, overexposed, static, blurred details, subtitles, worst "
                  "quality, low quality, deformed, disfigured, extra fingers, jpeg artifacts")

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
        # Il modello video vive al posto di quello per le immagini: tutti e due
        # insieme non stanno nella RAM di un PC normale.
        self.video_pipe = None
        self.video_model = ""
        self._video_prompts = {}

    def _free(self, which):
        import gc
        import torch

        if which == "image" and self.pipe is not None:
            self.pipe = None
        elif which == "video" and self.video_pipe is not None:
            self.video_pipe = None
        else:
            return
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

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

        self._free("video")
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

        if req.get("kind") == "video":
            return self.generate_video(req)
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
                emit("done", id=job, failed=True)
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
                emit("done", id=job, failed=True)
                return
            except Exception as exc:  # noqa: BLE001 - riportiamo tutto alla GUI
                emit("error", id=job, msg=str(exc), trace=traceback.format_exc())
                emit("done", id=job, failed=True)
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

        cancelled = _cancel.is_set()
        _cancel.clear()
        emit("done", id=job, cancelled=cancelled)

    # ---------------------------------------------------------------- video
    def load_video(self, model_id=VIDEO_MODEL_ID):
        """Wan2.2 TI2V-5B: un solo modello per testo->video e foto->video.

        Con meno di 24 GB di VRAM (misurato su una RTX 4070 da 12 GB):
        - il text encoder (UMT5-XXL, 11 GB) resta sulla CPU: portarlo sulla
          scheda, anche a gruppi, la riempie e da li' in poi il driver sposta
          memoria nella RAM di sistema, e ogni passo passa da 3 a 180 secondi;
        - il transformer sta tutto in VRAM con i pesi salvati in fp8 e il calcolo
          in bf16: 5 GB invece di 10, nessun trasferimento durante i passi;
        - il VAE sta sulla GPU in fp32, come consiglia la scheda del modello,
          con la decodifica a tessere. Picco misurato a 480p: 9,1 GB.
        """
        import torch

        if self.video_pipe is not None and self.video_model == model_id:
            emit("loaded", model=model_id, kind="video", device=self.device, cached=True)
            return
        self._free("image")
        info = self.probe()
        emit("status", stage="load", model=model_id,
             msg="Carico il modello video (al primo avvio scarica circa 34 GB)...")

        from diffusers import AutoModel, WanPipeline
        from transformers import UMT5EncoderModel

        # Dalla copia locale, se c'e': diffusers per i pesi divisi in piu' file
        # chiede comunque l'elenco al Hub, e senza rete il caricamento fallisce.
        richiesto = model_id
        model_id = _local_snapshot(model_id)
        text_encoder = UMT5EncoderModel.from_pretrained(
            model_id, subfolder="text_encoder", torch_dtype=torch.bfloat16)
        vae = AutoModel.from_pretrained(model_id, subfolder="vae", torch_dtype=torch.float32)
        transformer = AutoModel.from_pretrained(
            model_id, subfolder="transformer", torch_dtype=torch.bfloat16)

        if not info["cuda"]:
            pipe = WanPipeline.from_pretrained(model_id, vae=vae, transformer=transformer,
                                               text_encoder=text_encoder,
                                               torch_dtype=torch.float32)
            self.device = "cpu"
        elif info["vram_gb"] >= 24:
            pipe = WanPipeline.from_pretrained(model_id, vae=vae, transformer=transformer,
                                               text_encoder=text_encoder,
                                               torch_dtype=torch.bfloat16)
            pipe.to("cuda")
            self.device = "cuda"
        else:
            transformer.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn,
                                                 compute_dtype=torch.bfloat16)
            pipe = WanPipeline.from_pretrained(model_id, vae=vae, transformer=transformer,
                                               text_encoder=text_encoder,
                                               torch_dtype=torch.bfloat16)
            pipe.transformer.to("cuda")
            pipe.vae.to("cuda")
            self.device = "cuda (transformer fp8, testo su CPU)"
        _try(getattr(pipe.vae, "enable_tiling", None))
        self.video_pipe = pipe
        self.video_model = richiesto
        self._video_prompts = {}
        emit("loaded", model=richiesto, kind="video", device=self.device,
             vram_gb=info["vram_gb"], cached=False)

    def _encode_video_prompt(self, prompt, negative):
        """Codifica il prompt dove sta il text encoder e lo tiene per le clip successive."""
        import torch

        chiave = (prompt, negative)
        if chiave not in self._video_prompts:
            pipe = self.video_pipe
            dispositivo = next(pipe.text_encoder.parameters()).device
            with torch.no_grad():
                positivo, negativo = pipe.encode_prompt(
                    prompt=prompt, negative_prompt=negative,
                    do_classifier_free_guidance=True, device=dispositivo)
            if len(self._video_prompts) > 8:
                self._video_prompts.clear()
            self._video_prompts[chiave] = (positivo, negativo)
        positivo, negativo = self._video_prompts[chiave]
        dove = next(self.video_pipe.transformer.parameters()).device
        return positivo.to(dove), negativo.to(dove)

    def generate_video(self, req):
        import random

        import torch
        from PIL import Image

        model_id = req.get("video_model") or VIDEO_MODEL_ID
        self.load_video(model_id)
        job = req.get("id", "job")
        steps = int(req.get("steps") or 30)
        # Wan vuole lati multipli di 32 e 4k+1 fotogrammi: meglio correggere qui
        # che lasciare che la pipeline arrotondi in silenzio.
        width = max(256, int(req.get("width", 832)) // 32 * 32)
        height = max(256, int(req.get("height", 480)) // 32 * 32)
        frames = max(5, (int(req.get("num_frames", 73)) - 1) // 4 * 4 + 1)
        fps = int(req.get("fps", 24))
        seed = req.get("seed")
        run_seed = int(seed) if seed not in (None, "") else random.randint(0, 2 ** 32 - 1)
        out_dir = req.get("out_dir") or os.getcwd()
        os.makedirs(out_dir, exist_ok=True)
        basename = req.get("basename") or time.strftime("%Y%m%d-%H%M%S")

        emit("status", id=job, stage="text",
             msg="Leggo il prompt (sulla CPU, circa un minuto la prima volta)...")
        positivo, negativo = self._encode_video_prompt(
            req.get("prompt", ""), req.get("negative_prompt") or VIDEO_NEGATIVE)
        kwargs = {
            "prompt_embeds": positivo, "negative_prompt_embeds": negativo,
            "height": height, "width": width, "num_frames": frames,
            "num_inference_steps": steps,
            "guidance_scale": float(req.get("guidance_scale", 5.0)),
            "generator": torch.Generator("cpu").manual_seed(run_seed),
            "callback_on_step_end": _make_callback(job, 0, 1, steps),
        }
        pipe = self.video_pipe
        refs = [p for p in req.get("images", []) or [] if os.path.exists(p)]
        if refs:
            from diffusers import WanImageToVideoPipeline

            # Stessi pesi, altra pipeline: niente da ricaricare. La configurazione
            # va ripresa: con expand_timesteps (Wan2.2 TI2V) la foto diventa il
            # primo fotogramma latente; senza, la pipeline la prepara come Wan2.1
            # e il transformer riceve 100 canali invece di 48.
            base = self.video_pipe
            pipe = WanImageToVideoPipeline(
                **base.components,
                boundary_ratio=base.config.get("boundary_ratio"),
                expand_timesteps=bool(base.config.get("expand_timesteps", False)))
            kwargs["image"] = _fit(Image.open(refs[0]).convert("RGB"), width, height)

        started = time.time()
        emit("progress", id=job, index=0, batch=1, step=0, total=steps,
             msg="Video: %dx%d, %d fotogrammi" % (width, height, frames))
        try:
            result = pipe(**_filter_kwargs(pipe, kwargs))
        except Cancelled:
            emit("status", id=job, msg="Generazione annullata.", stage="cancelled")
            _cancel.clear()
            emit("done", id=job, cancelled=True)
            return
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            emit("error", id=job, kind="oom", msg=(
                "VRAM esaurita durante il video. Riduci risoluzione o durata."))
            emit("done", id=job, failed=True)
            return
        except Exception as exc:  # noqa: BLE001
            emit("error", id=job, msg=str(exc), trace=traceback.format_exc())
            emit("done", id=job, failed=True)
            return

        clip = result.frames[0]
        path = os.path.join(out_dir, basename + ".mp4")
        from diffusers.utils import export_to_video
        export_to_video(clip, path, fps=fps)
        meta = {
            "kind": "video",
            "prompt": req.get("prompt", ""),
            "negative_prompt": req.get("negative_prompt", ""),
            "seed": run_seed, "steps": steps,
            "guidance_scale": kwargs["guidance_scale"],
            "model": model_id,
            "size": "%dx%d" % (width, height),
            "frames": len(clip), "fps": fps,
            "seconds": round(len(clip) / float(fps), 1),
            "references": len(refs),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        # Il fotogramma centrale fa da copertina in galleria e porta i parametri.
        poster = os.path.join(out_dir, basename + ".png")
        _save_png(_to_pil(clip[len(clip) // 2]), poster, meta)
        emit("image", id=job, index=0, path=path, poster=poster, seed=run_seed,
             elapsed=round(time.time() - started, 1), meta=meta)
        emit("done", id=job, cancelled=False)


def _local_snapshot(model_id):
    """Il percorso della copia gia' scaricata; il nome del repo se non c'e'."""
    if os.path.isdir(model_id):
        return model_id
    try:
        from huggingface_hub import snapshot_download

        return snapshot_download(model_id, local_files_only=True)
    except Exception:  # noqa: BLE001 - non scaricato o incompleto: ci pensa from_pretrained
        return model_id


def _fit(image, width, height):
    """Ritaglia al centro e ridimensiona la foto di partenza alla misura del video."""
    from PIL import ImageOps

    return ImageOps.fit(image, (width, height))


def _to_pil(frame):
    from PIL import Image

    if isinstance(frame, Image.Image):
        return frame
    import numpy as np

    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 1) * 255).round().astype(np.uint8)
    return Image.fromarray(arr)


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


def _preload():
    """Carica torch e diffusers prima di mettere in piedi il thread lettore.

    Su Windows, se un altro thread e' fermo dentro readline() su stdin, il
    caricamento delle DLL di numpy e torch resta appeso a tempo indeterminato.
    Importare qui, da soli, costa qualche secondo e toglie di mezzo il problema.
    """
    versions = {}
    try:
        import torch
        versions["torch"] = torch.__version__
        versions["cuda"] = bool(torch.cuda.is_available())
    except Exception as exc:  # noqa: BLE001 - lo riferiamo, non moriamo qui
        versions["torch_error"] = str(exc)
    try:
        import diffusers
        versions["diffusers"] = diffusers.__version__
    except Exception as exc:  # noqa: BLE001
        versions["diffusers_error"] = str(exc)
    return versions


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
    emit("status", stage="boot", msg="Avvio il motore di generazione...")
    versions = _preload()
    engine = Engine()
    emit("hello", pid=os.getpid(), python=sys.version.split()[0], model=MODEL_ID, **versions)

    for req in _incoming():
        cmd = req.get("cmd")
        try:
            if cmd == "load" and req.get("kind") == "video":
                engine.load_video(req.get("video_model") or VIDEO_MODEL_ID)
            elif cmd == "load":
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
