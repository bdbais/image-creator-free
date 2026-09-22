"""Prima configurazione: requisiti, licenza del modello e installazione del runtime."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import config, runtime

LICENSE_TEXT = (
    "I pesi di Qwen-Image-2.1 sono distribuiti con la Qwen Research License: "
    "l'uso e' consentito per ricerca e valutazione, non per scopi commerciali. "
    "Questo programma e' open source (MIT) e non ridistribuisce il modello: lo "
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
            gpu_line = "Scheda video: %s, %s GB di VRAM - modalita' consigliata: %s" % (
                gpu["name"], gpu["vram_gb"], config.MEMORY_MODES[mode])
            self.settings.memory_mode = "auto"
        else:
            gpu_line = ("Nessuna GPU NVIDIA rilevata: il programma funzionera' sulla CPU, "
                        "con tempi nell'ordine delle decine di minuti per immagine.")
        gpu_label = QLabel(gpu_line)
        gpu_label.setWordWrap(True)
        grid.addWidget(gpu_label)

        disk = QLabel("Spazio libero su %s: %s GB (ne servono circa 36)" % (
            config.data_dir().drive or "disco", free))
        disk.setWordWrap(True)
        if free and free < 40:
            disk.setStyleSheet("color: #fbbf24;")
        grid.addWidget(disk)

        python = runtime.find_system_python()
        grid.addWidget(QLabel("Python di sistema: %s" % (
            python if python else "assente - ne scarico una copia dedicata")))
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
        later = QPushButton("Piu' tardi")
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
    def start_install(self):
        self.settings.accepted_license = True
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
            self.step_label.setText("Fatto: l'ambiente e' pronto.")
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
