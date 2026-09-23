"""Finestra principale: prompt, esempi ufficiali, parametri e galleria."""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction, QDesktopServices, QGuiApplication, QIcon, QImageReader, QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..core import config, history, presets as presets_mod, projects, runtime
from ..core.worker_client import WorkerClient
from . import aggiornamento
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
        self.seen_progress = False
        self.log_dialog = None
        self.project: projects.Project | None = None
        # Il lavoro in corso appartiene al progetto da cui e' partito, anche se
        # nel frattempo se ne apre un altro.
        self.job_project = ""
        self.job_params: dict = {}

        self.setWindowTitle("%s - Qwen-Image-2.1 in locale" % APP_NAME)
        self.resize(1360, 900)

        self._build_menu()
        self._build_ui()
        self._connect_worker()
        self._fill_projects(self.settings.current_project)
        self._update_generate_state()
        # Controllo della versione poco dopo l'avvio, senza bloccare la finestra.
        QTimer.singleShot(4000, self._check_update)

    # =================================================================== interfaccia
    def _build_menu(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        for label, shortcut, slot in (("Nuovo progetto...", "Ctrl+N", self.new_project),
                                      ("Duplica il progetto...", "Ctrl+D", self.clone_project),
                                      ("Rinomina il progetto...", "F2", self.rename_project),
                                      ("Elimina il progetto...", "", self.delete_project)):
            act = QAction(label, self)
            if shortcut:
                act.setShortcut(shortcut)
            act.triggered.connect(slot)
            file_menu.addAction(act)
        file_menu.addSeparator()
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
        act = QAction("Controlla gli aggiornamenti...", self)
        act.triggered.connect(self.show_about)
        help_menu.addAction(act)
        act = QAction("Informazioni e novità", self)
        act.triggered.connect(self.show_about)
        help_menu.addAction(act)

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.side_tabs = QTabWidget()
        self.side_tabs.addTab(self._projects_panel(), "Progetti")
        self.side_tabs.addTab(self._examples_panel(), "Esempi")
        splitter.addWidget(self.side_tabs)
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

    # ---------------------------------------------------------------- progetti
    def _projects_panel(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 6, 12)
        box.setSpacing(8)

        subtitle = QLabel("Ogni progetto ricorda prompt, parametri e immagini. "
                          "Duplicalo per provare varianti senza toccare l'originale.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        box.addWidget(subtitle)

        self.project_list = QListWidget()
        self.project_list.setIconSize(QSize(48, 48))
        self.project_list.itemSelectionChanged.connect(self._on_project_selected)
        self.project_list.itemDoubleClicked.connect(lambda *_: self.rename_project())
        box.addWidget(self.project_list, 1)

        row = QHBoxLayout()
        for label, tip, slot in (("Nuovo", "Ctrl+N", self.new_project),
                                 ("Duplica", "Stessi parametri in un progetto nuovo (Ctrl+D)",
                                  self.clone_project),
                                 ("Rinomina", "F2", self.rename_project),
                                 ("Elimina", "", self.delete_project)):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        box.addLayout(row)
        return panel

    def _fill_projects(self, select_id: str | None = None):
        """Ricostruisce l'elenco; la prima voce mostra tutte le immagini."""
        if select_id is None:
            select_id = self.project.id if self.project else ""
        self.project_list.blockSignals(True)
        self.project_list.clear()
        tutte = QListWidgetItem("Tutte le immagini")
        tutte.setData(Qt.UserRole, "")
        self.project_list.addItem(tutte)
        scelto = tutte
        for project in projects.list_all():
            item = QListWidgetItem(self._project_caption(project))
            item.setData(Qt.UserRole, project.id)
            item.setToolTip(project.params.get("prompt", "")[:300])
            icon = _thumbnail(project.cover, 96)
            if icon is not None:
                item.setIcon(icon)
            self.project_list.addItem(item)
            if project.id == select_id:
                scelto = item
        self.project_list.setCurrentItem(scelto)
        self.project_list.blockSignals(False)
        self._on_project_selected()

    @staticmethod
    def _project_caption(project: projects.Project) -> str:
        n = len(projects.images_on_disk(project))
        quando = project.updated[:16].replace("-", "/")
        return "%s\n%s · %s" % (project.name, "1 immagine" if n == 1
                                else "%d immagini" % n, quando)

    def _on_project_selected(self):
        items = self.project_list.selectedItems()
        if not items:
            return
        project_id = items[0].data(Qt.UserRole)
        if self.project and project_id == self.project.id:
            return
        self._store_form_in_project()
        self.project = projects.load(project_id) if project_id else None
        if self.project:
            self._apply_params(self.project.params)
        self.settings.current_project = self.project.id if self.project else ""
        self._update_project_label()
        self._fill_gallery()

    def _update_project_label(self):
        if self.project:
            origine = ""
            if self.project.parent:
                padre = projects.load(self.project.parent)
                if padre:
                    origine = " · copia di «%s»" % padre.name
            self.project_label.setText("Progetto: <b>%s</b>%s" % (
                _html(self.project.name), _html(origine)))
        else:
            self.project_label.setText(
                "Nessun progetto aperto: alla prima generazione ne creo uno.")

    def _form_params(self) -> dict:
        seed_text = self.seed_edit.text().strip()
        try:
            seed = int(seed_text) if seed_text else None
        except ValueError:
            seed = None
        return {
            "prompt": self.prompt_edit.toPlainText().strip(),
            "negative_prompt": self.negative_edit.text().strip(),
            "aspect": self.aspect_box.currentText(),
            "quality": self.quality_box.currentData() or "standard",
            "steps": self.steps_spin.value(),
            "true_cfg_scale": self.cfg_spin.value(),
            "seed": seed,
            "batch": self.batch_spin.value(),
            "refs": self.refs.paths(),
        }

    def _apply_params(self, params: dict):
        self.prompt_edit.setPlainText(params.get("prompt", ""))
        self.negative_edit.setText(params.get("negative_prompt", ""))
        if params.get("aspect") in config.ASPECT_RATIOS:
            self.aspect_box.setCurrentText(params["aspect"])
        index = self.quality_box.findData(params.get("quality"))
        if index >= 0:
            self.quality_box.setCurrentIndex(index)
        self.steps_spin.setValue(int(params.get("steps") or 0))
        self.cfg_spin.setValue(float(params.get("true_cfg_scale") or 4.0))
        seed = params.get("seed")
        self.seed_edit.setText("" if seed is None else str(seed))
        self.batch_spin.setValue(int(params.get("batch") or 1))
        self.refs.clear()
        self.refs.add_paths([p for p in params.get("refs") or [] if Path(p).exists()])

    def _store_form_in_project(self):
        """Il modulo appartiene al progetto aperto: le modifiche restano sue."""
        if self.project is None:
            return
        params = self._form_params()
        if params != self.project.params:
            self.project.params = params
            projects.save(self.project)

    def new_project(self):
        nome, ok = QInputDialog.getText(self, "Nuovo progetto", "Nome del progetto:")
        if not ok:
            return
        self._store_form_in_project()
        # Parte dal modulo vuoto, ma tiene formato, qualità e impostazioni avanzate.
        params = self._form_params()
        params.update(prompt="", negative_prompt="", seed=None, refs=[])
        project = projects.create(nome.strip() or "Progetto senza nome", params)
        self.project = None
        self._fill_projects(project.id)
        self.prompt_edit.setFocus()

    def clone_project(self):
        self._clone(None)

    def _clone(self, params: dict | None, nome: str = ""):
        """Copia il progetto aperto (o i parametri dati) in uno nuovo e lo apre."""
        if self.project is None and params is None:
            if not self._form_params()["prompt"]:
                self.status_label.setText("Apri un progetto da duplicare.")
                return
        self._store_form_in_project()
        base_name = self.project.name if self.project else \
            projects.name_from_prompt(self._form_params()["prompt"])
        nome, ok = QInputDialog.getText(
            self, "Duplica il progetto",
            "Nome della copia (i parametri si possono cambiare prima di generare):",
            text=nome or "%s (copia)" % base_name)
        if not ok:
            return
        sorgente = self.project or projects.Project(
            id="", name=base_name, created="", updated="", params=self._form_params())
        copia = projects.clone(sorgente, nome, params)
        self.project = None
        self._fill_projects(copia.id)
        self.tabs.setCurrentIndex(0)
        self.status_label.setText(
            "Copia creata: cambia i parametri che vuoi e premi Genera.")

    def rename_project(self):
        if self.project is None:
            return
        nome, ok = QInputDialog.getText(self, "Rinomina il progetto", "Nuovo nome:",
                                        text=self.project.name)
        if ok and nome.strip():
            self._store_form_in_project()
            projects.rename(self.project, nome)
            self._fill_projects(self.project.id)
            self._update_project_label()

    def delete_project(self):
        if self.project is None:
            return
        n = len(projects.images_on_disk(self.project))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Elimina il progetto")
        box.setText("Tolgo «%s» dall'elenco?" % self.project.name)
        cancella = None
        if n:
            box.setInformativeText(
                "Le immagini restano nella cartella del progetto, a meno che tu non "
                "scelga di cancellarle.")
            cancella = QCheckBox("Cancella anche %s" % (
                "l'immagine" if n == 1 else "le %d immagini" % n))
            box.setCheckBox(cancella)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes:
            return
        projects.delete(self.project, with_images=bool(cancella and cancella.isChecked()))
        self.project = None
        self.settings.current_project = ""
        self._fill_projects("")

    # ---------------------------------------------------------------- esempi
    def _examples_panel(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 6, 12)
        box.setSpacing(8)

        title = QLabel("Esempi")
        title.setObjectName("h1")
        box.addWidget(title)

        subtitle = QLabel("I prompt che hai gia' usato, restauro di foto, scene complesse "
                          "e gli esempi ufficiali di Qwen.")
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
        tutti = presets_mod.from_history() + self.presets
        for group, items in presets_mod.grouped(tutti).items():
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

        self.project_label = QLabel()
        self.project_label.setTextFormat(Qt.RichText)
        box.addWidget(self.project_label)

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
        if self.settings.aspect in config.ASPECT_RATIOS:
            self.aspect_box.setCurrentText(self.settings.aspect)
        self.aspect_box.currentTextChanged.connect(self._update_size_label)

        self.quality_box = QComboBox()
        for key, data in config.QUALITY.items():
            self.quality_box.addItem(data["label"], key)
        index = self.quality_box.findData(self.settings.quality)
        self.quality_box.setCurrentIndex(index if index >= 0 else 1)
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
        for label, slot in (("Apri la cartella", self._open_images_folder),
                            ("Copia il prompt", self.copy_prompt_of_selected),
                            ("Riusa i parametri", self.reuse_selected),
                            ("Nuovo progetto da questa immagine", self.clone_from_selected)):
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

        if not self._conferma_se_troppo_grande(width, height):
            return
        if not self.client.model_loaded and not self._conferma_memoria():
            return

        # Ogni generazione appartiene a un progetto: se non ce n'e' uno aperto,
        # nasce adesso con il nome preso dal prompt.
        params = self._form_params()
        nuovo = self.project is None
        if nuovo:
            self.project = projects.create(projects.name_from_prompt(prompt), params)
        else:
            self.project.params = params
        refs = projects.keep_refs(self.project, self.settings)
        params["refs"] = refs
        projects.save(self.project)
        if refs != self.refs.paths():
            self.refs.clear()
            self.refs.add_paths(refs)
        if nuovo:
            self.settings.current_project = self.project.id
            self._fill_projects(self.project.id)
            self._update_project_label()
            self._fill_gallery()

        self._save_form()
        request = {
            "prompt": prompt,
            "negative_prompt": params["negative_prompt"],
            "steps": steps,
            "true_cfg_scale": params["true_cfg_scale"],
            "seed": params["seed"],
            "batch": params["batch"],
            "images": refs,
            "width": width,
            "height": height,
            "out_dir": str(projects.output_dir(self.project, self.settings)),
            "basename": time.strftime("%Y%m%d-%H%M%S"),
        }
        self.job_project = self.project.id
        self.job_params = params
        self.pending = self.batch_spin.value()
        self.seen_progress = False
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

    def _conferma_se_troppo_grande(self, width: int, height: int) -> bool:
        """Chiede conferma quando la misura dice che la VRAM non basterà.

        Su una scheda da 12 GB 2048x2048 esaurisce la memoria dopo una
        ventina di minuti: meglio dirlo prima di farli aspettare.
        """
        gpu = config.detect_gpu()
        vram = gpu.get("vram_gb") or 0
        if not vram or self.settings.memory_mode not in ("auto", "low"):
            return True
        limite = 1536 if vram < 16 else 2048
        if max(width, height) <= limite:
            return True
        risposta = QMessageBox.question(
            self, "Risoluzione oltre la portata della scheda",
            "Con %s GB di VRAM una immagine %dx%d di solito finisce la memoria: "
            "sulla RTX 4070 provata durante lo sviluppo si ferma dopo una ventina "
            "di minuti.\n\nFino a %dx%d funziona.\n\nProvo lo stesso?"
            % (vram, width, height, limite, limite),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return risposta == QMessageBox.Yes

    def _memoria_per_il_modello(self) -> tuple[float, float]:
        """(GB che servono, GB liberi): il modello passa tutto dalla RAM."""
        serve = runtime.model_size_on_disk(self.settings, self.settings.model_id)
        return serve + 2 if serve else 0.0, config.free_memory_gb()

    def _testo_memoria(self, serve: float, libera: float) -> str:
        return (
            "Per caricare il modello servono circa %.0f GB di memoria (RAM più file "
            "di paging) e ora ne sono liberi %.0f GB.\n\nChiudi i programmi che ne "
            "usano molta (emulatori, macchine virtuali, browser con tante schede) "
            "oppure aumenta il file di paging di Windows su un disco con spazio "
            "libero." % (serve, libera))

    def _conferma_memoria(self) -> bool:
        """Se la memoria non basta il processo muore senza messaggi: lo si dice prima."""
        serve, libera = self._memoria_per_il_modello()
        if not serve or not libera or libera >= serve:
            return True
        risposta = QMessageBox.question(
            self, "Memoria insufficiente",
            self._testo_memoria(serve, libera) + "\n\nProvo lo stesso?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return risposta == QMessageBox.Yes

    def cancel(self):
        self.client.cancel()
        self.cancel_btn.setEnabled(False)
        self.generate_btn.setEnabled(True)
        self.bar.setVisible(False)
        self.status_label.setText(
            "Annullamento richiesto: se il modello si sta caricando, si ferma appena "
            "comincia a generare.")

    # ---------------------------------------------------------------- eventi
    def on_loaded(self, event: dict):
        self.model_state.setText("Modello pronto - %s" % event.get("device", ""))
        if not self.client.busy:
            self.status_label.setText("Modello caricato.")

    def on_progress(self, event: dict):
        self.seen_progress = True
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
        entry["project"] = self.job_project
        history.add(entry)
        self.pending = max(0, self.pending - 1)
        progetto = projects.load(self.job_project) if self.job_project else None
        if progetto is not None:
            params = dict(self.job_params, seed=entry.get("seed"))
            projects.add_image(progetto, entry, params)
            entry = progetto.images[-1]
            if self.project and self.project.id == progetto.id:
                self.project.images = progetto.images
        # In galleria solo se si sta guardando quel progetto (o tutte le immagini).
        if self.project is None or self.project.id == self.job_project:
            self._add_gallery_item(entry, select=True)
        self._refresh_project_item(self.job_project)

    def on_done(self, _event: dict):
        self.bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        elapsed = time.time() - self.job_started
        if _event.get("failed"):
            return          # il messaggio l'ha gia' scritto on_failed
        if _event.get("cancelled"):
            self.status_label.setText("Generazione annullata.")
        else:
            self.status_label.setText("Fatto in %d secondi." % int(elapsed))
            self._fill_examples()     # il prompt appena usato entra tra "I tuoi prompt"
        if not self.keep_box.isChecked():
            self.client.stop()

    def on_failed(self, event: dict):
        self.bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        message = event.get("msg", "Errore sconosciuto")
        if not self.client.model_loaded:
            self.model_state.setText("Modello non caricato")
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
        if match and not self.seen_progress:
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
        if code in (0xC0000005, -0x3FFFFFFB):
            # Accesso non valido in torch: in pratica, memoria finita durante il carico.
            serve, libera = self._memoria_per_il_modello()
            QMessageBox.warning(
                self, "La generazione si è interrotta",
                "Il processo di generazione si è chiuso all'improvviso "
                "(0xC0000005). Di solito succede quando la memoria non basta.\n\n"
                + (self._testo_memoria(serve, libera) if serve else ""))

    # =================================================================== galleria
    def _fill_gallery(self):
        """Le immagini del progetto aperto, oppure le ultime generate in assoluto."""
        self.gallery.clear()
        self.preview.clear()
        self.meta_label.setText("")
        if self.project is not None:
            entries = projects.images_on_disk(self.project)
            if not entries:
                self.preview.setText("Questo progetto non ha ancora immagini: premi Genera.")
        else:
            entries = list(reversed(history.load(60)))
            if not entries:
                self.preview.setText("Le immagini generate compaiono qui.")
        for entry in entries:
            self._add_gallery_item(entry, select=False)
        if self.gallery.count():
            self.gallery.setCurrentRow(self.gallery.count() - 1)

    def _refresh_project_item(self, project_id: str):
        """Aggiorna conteggio e miniatura di un progetto nell'elenco."""
        project = projects.load(project_id) if project_id else None
        if project is None:
            return
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item.data(Qt.UserRole) == project_id:
                item.setText(self._project_caption(project))
                icon = _thumbnail(project.cover, 96)
                if icon is not None:
                    item.setIcon(icon)
                return

    def _add_gallery_item(self, entry: dict, select: bool):
        path = entry.get("path", "")
        if not path or not Path(path).exists():
            return
        icon = _thumbnail(path, 208)
        if icon is None:
            return
        item = QListWidgetItem()
        item.setIcon(icon)
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

    def _params_of(self, entry: dict) -> dict:
        """I parametri con cui e' nata un'immagine, seed compreso.

        Le immagini dei progetti li hanno tutti; quelle piu' vecchie solo
        quello che il worker ha scritto nei metadati.
        """
        if entry.get("params"):
            params = dict(entry["params"])
        else:
            meta = entry.get("meta", {})
            params = self._form_params()
            params.update(prompt=meta.get("prompt", ""),
                          negative_prompt=meta.get("negative_prompt", ""),
                          steps=int(meta.get("steps") or 0), refs=[])
            if meta.get("true_cfg_scale"):
                params["true_cfg_scale"] = float(meta["true_cfg_scale"])
        params["seed"] = entry.get("seed", params.get("seed"))
        params["batch"] = 1
        return params

    def reuse_selected(self):
        entry = self._selected_entry()
        if not entry:
            return
        self._apply_params(self._params_of(entry))
        self.status_label.setText(
            "Parametri ripresi dall'immagine selezionata, seed compreso: cambia quello "
            "che vuoi e premi Genera.")

    def clone_from_selected(self):
        """Nuovo progetto che parte esattamente da questa immagine."""
        entry = self._selected_entry()
        if not entry:
            return
        params = self._params_of(entry)
        nome = "%s (variante)" % (self.project.name if self.project
                                  else projects.name_from_prompt(params["prompt"]))
        self._clone(params, nome)

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
            mode = config.MEMORY_MODES.get(self.settings.memory_mode,
                                           config.MEMORY_MODES["auto"])
            return "%s · %s GB · %s" % (gpu["name"], gpu["vram_gb"], mode)
        return "Nessuna GPU NVIDIA"

    def _save_form(self):
        self.settings.last_prompt = self.prompt_edit.toPlainText()
        self.settings.negative_prompt = self.negative_edit.text()
        self.settings.aspect = self.aspect_box.currentText()
        self.settings.quality = self.quality_box.currentData()
        self.settings.steps = self.steps_spin.value()
        self.settings.true_cfg_scale = self.cfg_spin.value()
        self.settings.keep_model_loaded = self.keep_box.isChecked()
        self.settings.current_project = self.project.id if self.project else ""
        self.settings.save()
        self._store_form_in_project()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec():
            self.gpu_label.setText(self._gpu_summary())
            if self.client.is_running():
                self.status_label.setText(
                    "Le nuove impostazioni valgono al prossimo caricamento del modello.")

    def show_about(self):
        dialog = aggiornamento.InfoDialog(self, SITE_URL, REPO_URL, MODEL_URL, DONATE_URL,
                                          self.settings.output_dir)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def _check_update(self):
        self._controllo = aggiornamento.ControlloVersione(self)
        self._controllo.trovata.connect(self._on_update_found)
        self._controllo.start()        # senza rete: nessun messaggio

    def _on_update_found(self, info: dict):
        from ..core import aggiornamenti
        if not aggiornamenti.piu_nuova(info.get("version", "")):
            return
        if self.client.busy:
            self.status_label.setText(
                "È disponibile la versione %s: Aiuto → Informazioni e novità." % info["version"])
            return
        aggiornamento.proponi(self, info)

    def _open_images_folder(self):
        """La cartella del progetto aperto, se ha gia' immagini; altrimenti quella generale."""
        if self.project is not None:
            cartella = projects.output_dir(self.project, self.settings)
            if cartella.exists():
                self._open_path(cartella)
                return
        self._open_path(self.settings.out_path())

    @staticmethod
    def _open_path(path: Path):
        path = Path(path)
        if path.is_file():
            # explorer vuole il percorso attaccato a /select, in un'unica stringa
            subprocess.Popen('explorer /select,"%s"' % path)
        else:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))  # noqa: S606 - apertura cartella su Windows

    def closeEvent(self, event):
        self._save_form()
        self.client.stop()
        super().closeEvent(event)


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _thumbnail(path: str, size: int) -> QIcon | None:
    """Miniatura letta gia' ridotta: le immagini sono da 2-3 megapixel."""
    if not path or not Path(path).exists():
        return None
    reader = QImageReader(path)
    original = reader.size()
    if original.isValid() and original.width() and original.height():
        scala = size / max(original.width(), original.height())
        reader.setScaledSize(QSize(max(1, int(original.width() * scala)),
                                   max(1, int(original.height() * scala))))
    image = reader.read()
    return None if image.isNull() else QIcon(QPixmap.fromImage(image))


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
