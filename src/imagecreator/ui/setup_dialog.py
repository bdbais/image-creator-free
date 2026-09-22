"""Prima configurazione: requisiti, licenza del modello e installazione del runtime."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import config, runtime

LICENSE_TEXT = (
    "I pesi di Qwen-Image-2.1 sono distribuiti con la Qwen Research License: "
    "l'uso è consentito per ricerca e valutazione, non per scopi commerciali. "
    "Questo programma è open source (MIT) e non ridistribuisce il modello: lo "
    "scarica da Hugging Face sul tuo computer."
)


class InstallTask(QObject):
    line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, torch_variant: str):
        super().__init__()
        self.torch_variant = torch_variant
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            runtime.install(self.line.emit, self.torch_variant, lambda: self._stop)
        except Exception as exc:  # noqa: BLE001 - qualunque errore va mostrato all'utente
            self.finished.emit(False, str(exc))
            return
        self.finished.emit(True, "")


class SetupDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.thread: QThread | None = None
        self.task: InstallTask | None = None
        self.setWindowTitle("Preparazione di Image Creator Free")
        self.setMinimumSize(720, 560)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_intro())
        self.stack.addWidget(self._page_install())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.addWidget(self.stack)

    # ------------------------------------------------------------------ pagine
    def _page_intro(self) -> QWidget:
        gpu = config.detect_gpu()
        free = config.free_disk_gb(config.data_dir())
        page = QWidget()
        box = QVBoxLayout(page)
        box.setSpacing(12)

        title = QLabel("Manca un ultimo passo")
        title.setObjectName("h1")
        box.addWidget(title)

        intro = QLabel(
            "Image Creator Free genera le immagini sul tuo computer, senza account e "
            "senza inviare nulla in rete a parte il download del modello.\n\n"
            "Ora installo l'ambiente di calcolo (PyTorch e diffusers, circa 3 GB). "
            "Il modello Qwen-Image-2.1 (circa 33 GB) viene scaricato alla prima generazione."
        )
        intro.setWordWrap(True)
        box.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        grid = QVBoxLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.addWidget(QLabel("<b>Cosa ho trovato su questo computer</b>"))

        if gpu["nvidia"]:
            mode = config.suggest_memory_mode(gpu["vram_gb"])
            gpu_line = "Scheda video: %s, %s GB di VRAM - modalità consigliata: %s" % (
                gpu["name"], gpu["vram_gb"], config.MEMORY_MODES[mode])
            self.settings.memory_mode = "auto"
        else:
            gpu_line = ("Nessuna GPU NVIDIA rilevata: il programma funzionerà sulla CPU, "
                        "con tempi nell'ordine delle decine di minuti per immagine.")
        gpu_label = QLabel(gpu_line)
        gpu_label.setWordWrap(True)
        grid.addWidget(gpu_label)

        disk = QLabel("Spazio libero su %s: %s GB (l'ambiente di calcolo ne chiede 3)" % (
            config.data_dir().drive or "disco", free))
        disk.setWordWrap(True)
        if free and free < 8:
            disk.setStyleSheet("color: #fbbf24;")
        grid.addWidget(disk)

        python = runtime.find_system_python()
        grid.addWidget(QLabel("Python di sistema: %s" % (
            python if python else "assente - ne scarico una copia dedicata")))

        grid.addWidget(QLabel(""))
        grid.addWidget(QLabel("<b>Dove tenere il modello (circa 33 GB)</b>"))
        self.models_edit = QLineEdit(
            self.settings.models_dir or config.best_models_dir())
        self.models_edit.setPlaceholderText(str(config.default_hf_home()))
        self.models_edit.textChanged.connect(self._update_model_disk)
        browse = QPushButton("Sfoglia...")
        browse.clicked.connect(self._pick_models_dir)
        row = QHBoxLayout()
        row.addWidget(self.models_edit, 1)
        row.addWidget(browse)
        grid.addLayout(row)
        self.model_disk = QLabel("")
        self.model_disk.setWordWrap(True)
        grid.addWidget(self.model_disk)
        self._update_model_disk()
        box.addWidget(card)

        licence = QLabel(LICENSE_TEXT)
        licence.setWordWrap(True)
        licence.setObjectName("muted")
        box.addWidget(licence)

        self.accept_box = QCheckBox("Ho capito: uso il modello per ricerca e uso personale.")
        self.accept_box.toggled.connect(lambda v: self.start_btn.setEnabled(v))
        box.addWidget(self.accept_box)

        box.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        later = QPushButton("Più tardi")
        later.clicked.connect(self.reject)
        row.addWidget(later)
        self.start_btn = QPushButton("Installa ora")
        self.start_btn.setObjectName("primary")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_install)
        row.addWidget(self.start_btn)
        box.addLayout(row)
        return page

    def _page_install(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setSpacing(10)

        title = QLabel("Installazione in corso")
        title.setObjectName("h1")
        box.addWidget(title)

        self.step_label = QLabel("Preparo l'ambiente...")
        self.step_label.setObjectName("muted")
        box.addWidget(self.step_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        box.addWidget(self.bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        box.addWidget(self.log_view, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Annulla")
        self.cancel_btn.clicked.connect(self.cancel_install)
        row.addWidget(self.cancel_btn)
        self.close_btn = QPushButton("Inizia a creare")
        self.close_btn.setObjectName("primary")
        self.close_btn.setVisible(False)
        self.close_btn.clicked.connect(self.accept)
        row.addWidget(self.close_btn)
        box.addLayout(row)
        return page

    # ------------------------------------------------------------------ azioni
    def _pick_models_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Dove tenere i file del modello", self.models_edit.text())
        if path:
            self.models_edit.setText(path)

    def _update_model_disk(self):
        from pathlib import Path

        target = Path(self.models_edit.text().strip() or str(config.default_hf_home()))
        free = config.free_disk_gb(target)
        if free and free < config.MODEL_SIZE_GB + 3:
            self.model_disk.setText(
                "Su questo disco restano %s GB: non bastano per il modello. "
                "Scegline un altro." % free)
            self.model_disk.setStyleSheet("color: #f87171;")
        else:
            self.model_disk.setText("Spazio libero: %s GB" % free)
            self.model_disk.setStyleSheet("")

    def start_install(self):
        self.settings.accepted_license = True
        self.settings.models_dir = self.models_edit.text().strip()
        self.settings.save()
        self.stack.setCurrentIndex(1)

        self.task = InstallTask(self.settings.torch_variant)
        self.thread = QThread(self)
        self.task.moveToThread(self.thread)
        self.thread.started.connect(self.task.run)
        self.task.line.connect(self.append_line)
        self.task.finished.connect(self.on_finished)
        self.thread.start()

    def append_line(self, text: str):
        self.log_view.appendPlainText(text)
        lowered = text.lower()
        if "pytorch" in lowered and "installo" in lowered:
            self.step_label.setText("Scarico PyTorch (circa 2,5 GB)...")
        elif "transformers" in lowered and "installo" in lowered:
            self.step_label.setText("Installo transformers e accelerate...")
        elif "diffusers" in lowered and "installo" in lowered:
            self.step_label.setText("Installo diffusers...")

    def on_finished(self, ok: bool, error: str):
        if self.thread:
            self.thread.quit()
            self.thread.wait(5000)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if ok else 0)
        self.cancel_btn.setText("Chiudi")
        if ok:
            self.settings.setup_done = True
            self.settings.save()
            self.step_label.setText("Fatto: l'ambiente è pronto.")
            self.close_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
        else:
            self.step_label.setText("Installazione non riuscita.")
            self.step_label.setStyleSheet("color:#f87171;")
            self.log_view.appendPlainText("\n" + error)

    def cancel_install(self):
        if self.task and self.thread and self.thread.isRunning():
            self.task.stop()
            self.append_line("Interrompo al termine del passo in corso...")
            return
        self.reject()

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            self.task.stop() if self.task else None
            self.thread.quit()
            self.thread.wait(3000)
        super().closeEvent(event)
