"""Finestra principale: prompt, esempi ufficiali, parametri e galleria."""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, MODEL_ID, __version__
from ..core import config, history, presets as presets_mod, runtime
from ..core.worker_client import WorkerClient
from .refs import ReferenceStrip
from .settings_dialog import SettingsDialog
from .setup_dialog import SetupDialog

SITE_URL = "https://imagecreator.bais.info"
REPO_URL = "https://github.com/bdbais/image-creator-free"
DONATE_URL = "https://paypal.me/bellizia"
MODEL_URL = "https://huggingface.co/Qwen/Qwen-Image-2.1"


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.presets = presets_mod.load()
        self.client = WorkerClient(settings, self)
        self.current_job = ""
        self.job_started = 0.0
        self.pending = 0
        self.log_lines: deque[str] = deque(maxlen=3000)
        self.log_dialog = None

        self.setWindowTitle("%s - Qwen-Image-2.1 in locale" % APP_NAME)
        self.resize(1360, 900)

        self._build_menu()
        self._build_ui()
        self._connect_worker()
        self._load_history()
        self._update_generate_state()

    # =================================================================== interfaccia
    def _build_menu(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        act = QAction("Apri la cartella delle immagini", self)
        act.triggered.connect(lambda: self._open_path(self.settings.out_path()))
        file_menu.addAction(act)
        act = QAction("Impostazioni...", self)
        act.setShortcut("Ctrl+,")
        act.triggered.connect(self.open_settings)
        file_menu.addAction(act)
        file_menu.addSeparator()
        act = QAction("Esci", self)
        act.setShortcut("Ctrl+Q")
        act.triggered.connect(self.close)
        file_menu.addAction(act)

        model_menu = bar.addMenu("&Modello")
        self.act_load = QAction("Carica il modello in memoria", self)
        self.act_load.triggered.connect(self.load_model)
        model_menu.addAction(self.act_load)
        act = QAction("Chiudi il processo di generazione", self)
        act.triggered.connect(self.client.stop)
        model_menu.addAction(act)
        act = QAction("Mostra il registro", self)
        act.setShortcut("Ctrl+L")
        act.triggered.connect(self.show_log)
        model_menu.addAction(act)
        model_menu.addSeparator()
        act = QAction("Reinstalla l'ambiente di calcolo...", self)
        act.triggered.connect(self.run_setup)
        model_menu.addAction(act)

        help_menu = bar.addMenu("&Aiuto")
        for label, url in (("Sito del progetto", SITE_URL),
                           ("Codice sorgente su GitHub", REPO_URL),
                           ("Il modello su Hugging Face", MODEL_URL),
                           ("Offri un caffè", DONATE_URL)):
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            help_menu.addAction(act)
        help_menu.addSeparator()
        act = QAction("Informazioni", self)
        act.triggered.connect(self.show_about)
        help_menu.addAction(act)

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._examples_panel())
        splitter.addWidget(self._center_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 1030])
        self.setCentralWidget(splitter)

        self.status = self.statusBar()
        self.status_label = QLabel("Pronto")
        self.status.addWidget(self.status_label, 1)
        self.gpu_label = QLabel(self._gpu_summary())
        self.status.addPermanentWidget(self.gpu_label)

    # ---------------------------------------------------------------- esempi
    def _examples_panel(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 6, 12)
        box.setSpacing(8)

        title = QLabel("Esempi ufficiali")
        title.setObjectName("h1")
        box.addWidget(title)

        subtitle = QLabel("Prompt presi dalla scheda del modello e dalla demo di Qwen.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        box.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca tra gli esempi...")
        self.search.textChanged.connect(self._fill_examples)
        box.addWidget(self.search)

        self.example_list = QListWidget()
        self.example_list.itemSelectionChanged.connect(self._preview_example)
        self.example_list.itemDoubleClicked.connect(lambda *_: self.use_example())
        box.addWidget(self.example_list, 1)

        self.example_preview = QPlainTextEdit()
        self.example_preview.setReadOnly(True)
        self.example_preview.setFixedHeight(120)
        self.example_preview.setPlaceholderText("Seleziona un esempio per vederne il prompt.")
        box.addWidget(self.example_preview)

        use_btn = QPushButton("Usa questo prompt")
        use_btn.clicked.connect(self.use_example)
        box.addWidget(use_btn)

        self._fill_examples()
        return panel

    def _fill_examples(self):
        needle = self.search.text().strip().lower()
        self.example_list.clear()
        for group, items in presets_mod.grouped(self.presets).items():
            visible = [p for p in items
                       if not needle or needle in p.title_it.lower()
                       or needle in p.title_en.lower() or needle in p.prompt.lower()]
            if not visible:
                continue
            header = QListWidgetItem(group.upper())
            header.setFlags(Qt.NoItemFlags)
            self.example_list.addItem(header)
            for preset in visible:
                item = QListWidgetItem("  %s  ·  %s" % (preset.title_it, preset.badge))
                item.setData(Qt.UserRole, preset)
                item.setToolTip(preset.title_en)
                self.example_list.addItem(item)

    def _selected_preset(self):
        items = self.example_list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def _preview_example(self):
        preset = self._selected_preset()
        if preset:
            self.example_preview.setPlainText(preset.prompt)

    def use_example(self):
        preset = self._selected_preset()
        if not preset:
            return
        self.prompt_edit.setPlainText(preset.prompt)
        index = self.aspect_box.findText(preset.aspect)
        if index >= 0:
            self.aspect_box.setCurrentIndex(index)
        if preset.refs and self.refs.count() == 0:
            self.tabs.setCurrentIndex(1)
            self.status_label.setText(
                "Questo esempio lavora su %d immagini: aggiungile qui sotto." % preset.refs)
        self.prompt_edit.setFocus()

    # ---------------------------------------------------------------- centro
    def _center_panel(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(6, 12, 12, 12)
        box.setSpacing(10)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Descrivi l'immagine. Il modello scrive testo dentro l'immagine molto bene: "
            "metti tra virgolette le parole che devono comparire.")
        self.prompt_edit.setPlainText(self.settings.last_prompt)
        self.prompt_edit.setFixedHeight(120)
        box.addWidget(self.prompt_edit)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._params_tab(), "Parametri")
        self.tabs.addTab(self._refs_tab(), "Immagini di riferimento")
        self.tabs.addTab(self._advanced_tab(), "Avanzate")
        self.tabs.setFixedHeight(184)
        box.addWidget(self.tabs)

        box.addLayout(self._action_row())

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        box.addWidget(self.bar)

        box.addWidget(self._results_area(), 1)
        return panel

    def _params_tab(self) -> QWidget:
        page = QWidget()
        grid = QHBoxLayout(page)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setSpacing(18)
        grid.setAlignment(Qt.AlignTop)

        self.aspect_box = QComboBox()
        self.aspect_box.addItems(list(config.ASPECT_RATIOS))
        self.aspect_box.setCurrentText(self.settings.aspect)
        self.aspect_box.currentTextChanged.connect(self._update_size_label)

        self.quality_box = QComboBox()
        for key, data in config.QUALITY.items():
            self.quality_box.addItem(data["label"], key)
        self.quality_box.setCurrentIndex(
            max(0, list(config.QUALITY).index(self.settings.quality)))
        self.quality_box.currentIndexChanged.connect(self._update_size_label)

        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 8)
        self.batch_spin.setValue(1)

        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("casuale")
        self.seed_edit.setFixedWidth(120)

        grid.addLayout(_field("Formato", self.aspect_box))
        grid.addLayout(_field("Qualita'", self.quality_box))
        grid.addLayout(_field("Quante immagini", self.batch_spin))
        grid.addLayout(_field("Seed", self.seed_edit))

        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        self.size_label.setWordWrap(True)
        grid.addLayout(_field("Risoluzione", self.size_label), 1)
        self._update_size_label()
        return page

    def _refs_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 10, 14, 10)
        self.refs = ReferenceStrip()
        self.refs.changed.connect(lambda *_: self._update_generate_state())
        box.addWidget(self.refs)
        return page

    def _advanced_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(10)

        self.negative_edit = QLineEdit(self.settings.negative_prompt)
        self.negative_edit.setPlaceholderText("Cosa NON deve comparire (facoltativo)")

        row = QHBoxLayout()
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(0, 80)
        self.steps_spin.setValue(self.settings.steps)
        self.steps_spin.setSpecialValueText("automatico")

        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(1.0, 10.0)
        self.cfg_spin.setSingleStep(0.5)
        self.cfg_spin.setValue(self.settings.true_cfg_scale)

        self.keep_box = QCheckBox("Tieni il modello in memoria tra una generazione e l'altra")
        self.keep_box.setChecked(self.settings.keep_model_loaded)

        row.addLayout(_field("Passi di diffusione", self.steps_spin))
        row.addLayout(_field("Aderenza al prompt", self.cfg_spin))
        row.addWidget(self.keep_box, 1, Qt.AlignBottom)

        box.addLayout(_field("Prompt negativo", self.negative_edit))
        box.addLayout(row)
        return page

    def _action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.generate_btn = QPushButton("Genera")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setShortcut("Ctrl+Return")
        self.generate_btn.setToolTip("Ctrl+Invio")
        self.generate_btn.clicked.connect(self.generate)

        self.cancel_btn = QPushButton("Annulla")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)

        self.model_state = QLabel("Modello non caricato")
        self.model_state.setObjectName("muted")

        row.addWidget(self.generate_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.model_state, 1)
        return row

    def _results_area(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)

        self.preview = QLabel("Le immagini generate compaiono qui.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(260)
        self.preview.setObjectName("muted")
        box.addWidget(self.preview, 1)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("muted")
        self.meta_label.setWordWrap(True)
        box.addWidget(self.meta_label)

        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(104, 104))
        self.gallery.setGridSize(QSize(116, 116))
        self.gallery.setFixedHeight(136)
        self.gallery.setFlow(QListWidget.LeftToRight)
        self.gallery.setWrapping(False)
        self.gallery.setMovement(QListWidget.Static)
        self.gallery.itemSelectionChanged.connect(self._show_selected_image)
        self.gallery.itemDoubleClicked.connect(
            lambda item: self._open_path(Path(item.data(Qt.UserRole)["path"])))
        box.addWidget(self.gallery)

        actions = QHBoxLayout()
        for label, slot in (("Apri la cartella", lambda: self._open_path(self.settings.out_path())),
                            ("Copia il prompt", self.copy_prompt_of_selected),
                            ("Riusa i parametri", self.reuse_selected)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        actions.addStretch(1)
        donate = QPushButton("Offri un caffè")
        donate.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        actions.addWidget(donate)
        box.addLayout(actions)
        return frame

    # =================================================================== worker
    def _connect_worker(self):
        self.client.loaded.connect(self.on_loaded)
        self.client.progress.connect(self.on_progress)
        self.client.image.connect(self.on_image)
        self.client.done.connect(self.on_done)
        self.client.failed.connect(self.on_failed)
        self.client.status.connect(lambda e: self.status_label.setText(e.get("msg", "")))
        self.client.log.connect(self.on_log)
        self.client.stopped.connect(self.on_worker_stopped)

    def ensure_runtime(self) -> bool:
        if runtime.is_ready():
            return True
        dialog = SetupDialog(self.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()
        return runtime.is_ready()

    def run_setup(self):
        dialog = SetupDialog(self.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def load_model(self):
        if not self.ensure_runtime():
            return
        self.status_label.setText(
            "Carico il modello: al primo avvio scarica circa 33 GB da Hugging Face.")
        self.model_state.setText("Caricamento in corso...")
        self.client.load_model()

    def generate(self):
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            self.prompt_edit.setFocus()
            self.status_label.setText("Scrivi prima cosa vuoi generare.")
            return
        if not self.ensure_runtime():
            return

        quality = self.quality_box.currentData()
        steps = self.steps_spin.value() or config.QUALITY[quality]["steps"]
        width, height = config.resolution_for(self.aspect_box.currentText(), quality)
        refs = self.refs.paths()

        seed_text = self.seed_edit.text().strip()
        try:
            seed = int(seed_text) if seed_text else None
        except ValueError:
            seed = None

        self._save_form()
        request = {
            "prompt": prompt,
            "negative_prompt": self.negative_edit.text().strip(),
            "steps": steps,
            "true_cfg_scale": self.cfg_spin.value(),
            "seed": seed,
            "batch": self.batch_spin.value(),
            "images": refs,
            "width": width,
            "height": height,
            "out_dir": str(self.settings.out_path()),
            "basename": time.strftime("%Y%m%d-%H%M%S"),
        }
        self.pending = self.batch_spin.value()
        self.job_started = time.time()
        self.current_job = self.client.generate(request)
        if not self.current_job:
            return
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText(
            "In coda... il primo avvio richiede minuti per caricare il modello.")

    def cancel(self):
        self.client.cancel()
        self.status_label.setText("Annullamento richiesto: si ferma al passo successivo.")

    # ---------------------------------------------------------------- eventi
    def on_loaded(self, event: dict):
        self.model_state.setText("Modello pronto - %s" % event.get("device", ""))
        if not self.client.busy:
            self.status_label.setText("Modello caricato.")

    def on_progress(self, event: dict):
        total = int(event.get("total") or 0)
        step = int(event.get("step") or 0)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(step)
        index = int(event.get("index", 0)) + 1
        batch = int(event.get("batch", 1))
        suffix = "" if batch == 1 else " (immagine %d di %d)" % (index, batch)
        self.status_label.setText("Genero: passo %d di %d%s" % (step, total, suffix))

    def on_image(self, event: dict):
        entry = {
            "path": event.get("path", ""),
            "seed": event.get("seed"),
            "elapsed": event.get("elapsed"),
            "meta": event.get("meta", {}),
        }
        history.add(entry)
        self._add_gallery_item(entry, select=True)
        self.pending = max(0, self.pending - 1)

    def on_done(self, _event: dict):
        self.bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        elapsed = time.time() - self.job_started
        self.status_label.setText("Fatto in %d secondi." % int(elapsed))
        if not self.keep_box.isChecked():
            self.client.stop()

    def on_failed(self, event: dict):
        self.bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        message = event.get("msg", "Errore sconosciuto")
        self.status_label.setText("Errore: %s" % message.splitlines()[0][:160])
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("La generazione non è riuscita")
        box.setText(message[:800])
        if event.get("kind") == "oom":
            box.setInformativeText(
                "Suggerimento: scegli la qualità Bozza, riduci il numero di immagini "
                "oppure imposta una modalità di memoria più conservativa.")
        box.exec()

    def on_log(self, line: str):
        """Raccoglie l'output del processo e ne mostra l'avanzamento nella barra di stato.

        Il download del modello passa di qui come barra testuale di Hugging Face:
        senza questa riga, i primi 33 GB sarebbero muti.
        """
        self.log_lines.append(line)
        if self.log_dialog is not None and self.log_dialog.isVisible():
            self.log_view.appendPlainText(line)
        match = re.search(r"(\d{1,3})%\|", line)
        if match and not self.client.busy:
            name = line.split(":", 1)[0].strip()[:40]
            self.status_label.setText("Scarico il modello: %s%% %s" % (match.group(1), name))

    def show_log(self):
        from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout

        if self.log_dialog is None:
            self.log_dialog = QDialog(self)
            self.log_dialog.setWindowTitle("Registro")
            self.log_dialog.resize(900, 520)
            self.log_dialog.setStyleSheet(self.styleSheet())
            self.log_view = QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumBlockCount(5000)
            box = QVBoxLayout(self.log_dialog)
            box.addWidget(self.log_view)
        self.log_view.setPlainText("\n".join(self.log_lines))
        self.log_view.moveCursor(self.log_view.textCursor().End)
        self.log_dialog.show()
        self.log_dialog.raise_()

    def on_worker_stopped(self, code: int):
        self.model_state.setText("Modello non caricato")
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.bar.setVisible(False)
        if code not in (0, 62097):
            self.status_label.setText(
                "Il processo di generazione si è chiuso (codice %s)." % code)

    # =================================================================== galleria
    def _load_history(self):
        for entry in reversed(history.load(60)):
            self._add_gallery_item(entry, select=False)
        if self.gallery.count():
            self.gallery.setCurrentRow(self.gallery.count() - 1)

    def _add_gallery_item(self, entry: dict, select: bool):
        path = entry.get("path", "")
        if not path or not Path(path).exists():
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        item = QListWidgetItem()
        item.setIcon(pixmap.scaled(208, 208, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        item.setToolTip(entry.get("meta", {}).get("prompt", "")[:300])
        item.setData(Qt.UserRole, entry)
        self.gallery.addItem(item)
        if select:
            self.gallery.setCurrentItem(item)
            self.gallery.scrollToItem(item)

    def _show_selected_image(self):
        items = self.gallery.selectedItems()
        if not items:
            return
        entry = items[0].data(Qt.UserRole)
        pixmap = QPixmap(entry["path"])
        if pixmap.isNull():
            return
        area = self.preview.size()
        self.preview.setPixmap(pixmap.scaled(
            max(120, int(area.width() * 0.98)), max(120, int(area.height() * 0.98)),
            Qt.KeepAspectRatio, Qt.SmoothTransformation))
        meta = entry.get("meta", {})
        self.meta_label.setText("%s · seed %s · %s passi · %s s · %s" % (
            meta.get("size", "?"), entry.get("seed"), meta.get("steps", "?"),
            entry.get("elapsed", "?"), Path(entry["path"]).name))

    def _selected_entry(self) -> dict | None:
        items = self.gallery.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def copy_prompt_of_selected(self):
        entry = self._selected_entry()
        if not entry:
            return
        QGuiApplication.clipboard().setText(entry.get("meta", {}).get("prompt", ""))
        self.status_label.setText("Prompt copiato negli appunti.")

    def reuse_selected(self):
        entry = self._selected_entry()
        if not entry:
            return
        meta = entry.get("meta", {})
        self.prompt_edit.setPlainText(meta.get("prompt", ""))
        self.negative_edit.setText(meta.get("negative_prompt", ""))
        self.seed_edit.setText(str(entry.get("seed", "")))
        if meta.get("steps"):
            self.steps_spin.setValue(int(meta["steps"]))
        self.status_label.setText("Parametri ripresi dall'immagine selezionata.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show_selected_image()

    # =================================================================== varie
    def _update_size_label(self):
        quality = self.quality_box.currentData() or "standard"
        width, height = config.resolution_for(self.aspect_box.currentText(), quality)
        self.size_label.setText("%d x %d px" % (width, height))

    def _update_generate_state(self):
        self.generate_btn.setEnabled(not self.client.busy)

    def _gpu_summary(self) -> str:
        gpu = config.detect_gpu()
        if gpu["nvidia"]:
            return "%s · %s GB · %s" % (gpu["name"], gpu["vram_gb"],
                                        config.MEMORY_MODES[self.settings.memory_mode])
        return "Nessuna GPU NVIDIA"

    def _save_form(self):
        self.settings.last_prompt = self.prompt_edit.toPlainText()
        self.settings.negative_prompt = self.negative_edit.text()
        self.settings.aspect = self.aspect_box.currentText()
        self.settings.quality = self.quality_box.currentData()
        self.settings.steps = self.steps_spin.value()
        self.settings.true_cfg_scale = self.cfg_spin.value()
        self.settings.keep_model_loaded = self.keep_box.isChecked()
        self.settings.save()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec():
            self.gpu_label.setText(self._gpu_summary())
            if self.client.is_running():
                self.status_label.setText(
                    "Le nuove impostazioni valgono al prossimo caricamento del modello.")

    def show_about(self):
        info = runtime.installed_info()
        QMessageBox.about(
            self, "Informazioni",
            "<b>%s</b> %s<br><br>"
            "Interfaccia per <a href='%s'>%s</a> in locale.<br>"
            "Codice: MIT · <a href='%s'>GitHub</a><br>"
            "Pesi del modello: Qwen Research License (uso non commerciale).<br><br>"
            "Runtime: torch %s · diffusers %s<br>"
            "Immagini in: %s<br><br>"
            "<a href='%s'>Sostieni il progetto</a>" % (
                APP_NAME, __version__, MODEL_URL, MODEL_ID, REPO_URL,
                info.get("torch", "-"), info.get("diffusers", "-"),
                self.settings.output_dir, DONATE_URL))

    @staticmethod
    def _open_path(path: Path):
        path = Path(path)
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))  # noqa: S606 - apertura cartella su Windows

    def closeEvent(self, event):
        self._save_form()
        self.client.stop()
        super().closeEvent(event)


def _field(label: str, widget: QWidget, stretch: int = 0):
    """Etichetta sopra, campo sotto, il resto dello spazio in fondo."""
    box = QVBoxLayout()
    box.setSpacing(4)
    caption = QLabel(label)
    caption.setObjectName("muted")
    box.addWidget(caption, 0, Qt.AlignTop)
    box.addWidget(widget, 0, Qt.AlignTop)
    box.addStretch(1)
    return box
