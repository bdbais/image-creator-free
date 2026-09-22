"""Dialogo con il processo di generazione (worker/qwen_worker.py) via QProcess."""
from __future__ import annotations

import json
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from . import config


class WorkerClient(QObject):
    """Avvia il worker, gli manda comandi JSON e ritrasmette gli eventi come segnali."""

    hello = Signal(dict)
    status = Signal(dict)
    loaded = Signal(dict)
    progress = Signal(dict)
    image = Signal(dict)
    done = Signal(dict)
    failed = Signal(dict)
    log = Signal(str)
    stopped = Signal(int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.proc: QProcess | None = None
        self._buffer = ""
        self.model_loaded = False
        self.busy = False

    # ------------------------------------------------------------------ processo
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self) -> bool:
        if self.is_running():
            return True
        python = config.runtime_python()
        script = config.worker_script()
        if not python.exists() or not script.exists():
            self.failed.emit({"msg": "Ambiente di generazione non installato."})
            return False

        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        for key, value in self.settings.env_for_worker().items():
            env.insert(key, value)
        env.insert("ICF_MODEL_ID", self.settings.model_id)
        proc.setProcessEnvironment(env)
        proc.setProgram(str(python))
        proc.setArguments(["-u", str(script)])
        proc.setWorkingDirectory(str(script.parent))
        proc.readyReadStandardOutput.connect(self._read_stdout)
        proc.readyReadStandardError.connect(self._read_stderr)
        proc.finished.connect(self._on_finished)
        proc.start()
        if not proc.waitForStarted(15000):
            self.failed.emit({"msg": "Non riesco ad avviare il processo di generazione."})
            return False
        self.proc = proc
        return True

    def stop(self) -> None:
        if not self.is_running():
            return
        self.send({"cmd": "shutdown"})
        assert self.proc is not None
        if not self.proc.waitForFinished(8000):
            self.proc.kill()
            self.proc.waitForFinished(3000)

    def _on_finished(self, code: int, _status) -> None:
        self.model_loaded = False
        self.busy = False
        self.proc = None
        self.stopped.emit(code)

    # ------------------------------------------------------------------ comandi
    def send(self, payload: dict) -> None:
        if not self.is_running():
            return
        assert self.proc is not None
        self.proc.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    def load_model(self) -> None:
        if not self.start():
            return
        self.send({"cmd": "load", "model": self.settings.model_id,
                   "memory_mode": self.settings.memory_mode})

    def generate(self, request: dict) -> str:
        if not self.start():
            return ""
        job = uuid.uuid4().hex[:8]
        request.update(cmd="generate", id=job, model=self.settings.model_id,
                       memory_mode=self.settings.memory_mode)
        self.busy = True
        self.send(request)
        return job

    def cancel(self) -> None:
        self.send({"cmd": "cancel"})

    # ------------------------------------------------------------------ lettura
    def _read_stdout(self) -> None:
        assert self.proc is not None
        self._buffer += bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if not line.startswith("{"):
                self.log.emit(line)
                continue
            try:
                event = json.loads(line)
            except ValueError:
                self.log.emit(line)
                continue
            self._dispatch(event)

    def _read_stderr(self) -> None:
        assert self.proc is not None
        text = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self.log.emit(line.rstrip())

    def _dispatch(self, event: dict) -> None:
        kind = event.get("ev")
        if kind == "hello":
            self.hello.emit(event)
        elif kind == "status":
            self.status.emit(event)
            if event.get("msg"):
                self.log.emit(event["msg"])
        elif kind == "loaded":
            self.model_loaded = True
            self.loaded.emit(event)
        elif kind == "progress":
            self.progress.emit(event)
        elif kind == "image":
            self.image.emit(event)
        elif kind == "done":
            self.busy = False
            self.done.emit(event)
        elif kind == "error":
            self.busy = False
            self.failed.emit(event)
            if event.get("trace"):
                self.log.emit(event["trace"])
        elif kind == "probe":
            self.log.emit("Runtime: " + json.dumps(event, ensure_ascii=False))
