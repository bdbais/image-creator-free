"""Impostazioni: cartelle, gestione della memoria, modello."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..core import config, runtime


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(620)

        self.output_edit = QLineEdit(settings.output_dir)
        self.models_edit = QLineEdit(settings.models_dir)
        self.models_edit.setPlaceholderText("cache predefinita di Hugging Face")
        self.model_edit = QLineEdit(settings.model_id)

        self.memory_box = QComboBox()
        for key, label in config.MEMORY_MODES.items():
            self.memory_box.addItem(label, key)
        index = self.memory_box.findData(settings.memory_mode)
        self.memory_box.setCurrentIndex(max(0, index))

        self.torch_box = QComboBox()
        for key, label in (("auto", "Automatica"), ("cu124", "CUDA 12.4"),
                           ("cu121", "CUDA 12.1"), ("cpu", "Solo CPU")):
            self.torch_box.addItem(label, key)
        index = self.torch_box.findData(settings.torch_variant)
        self.torch_box.setCurrentIndex(max(0, index))

        form = QFormLayout()
        form.addRow("Cartella delle immagini", _with_browse(self.output_edit, self._pick_output))
        form.addRow("Cartella del modello", _with_browse(self.models_edit, self._pick_models))
        form.addRow("Modello", self.model_edit)
        form.addRow("Uso della memoria", self.memory_box)
        form.addRow("Versione di PyTorch", self.torch_box)

        info = runtime.installed_info()
        status = QLabel(
            "Runtime: %s · torch %s · diffusers %s\nModello scaricato: %s" % (
                "installato" if runtime.is_ready() else "assente",
                info.get("torch", "-"), info.get("diffusers", "-"),
                ("sì, %s GB" % runtime.model_size_on_disk(settings, settings.model_id))
                if runtime.model_is_downloaded(settings, settings.model_id) else "no"))
        status.setObjectName("muted")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Save).setText("Salva")
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")

        box = QVBoxLayout(self)
        box.setContentsMargins(20, 20, 20, 16)
        box.setSpacing(14)
        box.addLayout(form)
        box.addWidget(status)
        box.addWidget(buttons)

    def _pick_output(self):
        path = QFileDialog.getExistingDirectory(self, "Dove salvare le immagini",
                                                self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _pick_models(self):
        path = QFileDialog.getExistingDirectory(self, "Dove tenere i file del modello",
                                                self.models_edit.text())
        if path:
            self.models_edit.setText(path)

    def save(self):
        self.settings.output_dir = self.output_edit.text().strip() or str(
            config.default_output_dir())
        self.settings.models_dir = self.models_edit.text().strip()
        self.settings.model_id = self.model_edit.text().strip() or config.MODEL_ID
        self.settings.memory_mode = self.memory_box.currentData()
        self.settings.torch_variant = self.torch_box.currentData()
        Path(self.settings.output_dir).mkdir(parents=True, exist_ok=True)
        self.settings.save()
        self.accept()


def _with_browse(edit: QLineEdit, slot) -> QWidget:
    widget = QWidget()
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(edit, 1)
    button = QPushButton("Sfoglia...")
    button.clicked.connect(slot)
    row.addWidget(button)
    return widget
