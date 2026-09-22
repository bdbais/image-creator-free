"""Striscia delle immagini di riferimento (fino a dieci, come consente il modello)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

MAX_REFS = 10
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class ReferenceStrip(QWidget):
    changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(92, 92))
        self.list.setGridSize(QSize(104, 104))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setFixedHeight(122)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setToolTip("Trascina qui le immagini da usare come riferimento")

        self.hint = QLabel(
            "Trascina fino a %d immagini: il prompt può citarle come "
            "\"image 1\", \"image 2\"..." % MAX_REFS)
        self.hint.setObjectName("hint")

        add_btn = QPushButton("Aggiungi...")
        add_btn.clicked.connect(self.browse)
        rm_btn = QPushButton("Togli")
        rm_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("Svuota")
        clear_btn.clicked.connect(self.clear)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.hint, 1)
        buttons.addWidget(add_btn)
        buttons.addWidget(rm_btn)
        buttons.addWidget(clear_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addLayout(buttons)
        box.addWidget(self.list)

    # ------------------------------------------------------------------ dati
    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def count(self) -> int:
        return self.list.count()

    def add_paths(self, paths) -> None:
        for raw in paths:
            path = Path(str(raw))
            if path.suffix.lower() not in EXTENSIONS or not path.exists():
                continue
            if str(path) in self.paths() or self.list.count() >= MAX_REFS:
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            item = QListWidgetItem()
            item.setIcon(pixmap.scaled(184, 184, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            item.setToolTip(str(path))
            item.setData(Qt.UserRole, str(path))
            self.list.addItem(item)
        self._refresh()

    def browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Scegli le immagini di riferimento", "",
            "Immagini (*.png *.jpg *.jpeg *.webp *.bmp)")
        if files:
            self.add_paths(files)

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._refresh()

    def clear(self) -> None:
        self.list.clear()
        self._refresh()

    def _refresh(self) -> None:
        count = self.list.count()
        if count:
            self.hint.setText("%d immagini di riferimento su %d" % (count, MAX_REFS))
        else:
            self.hint.setText(
                "Trascina fino a %d immagini: il prompt può citarle come "
                "\"image 1\", \"image 2\"..." % MAX_REFS)
        self.changed.emit(count)

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.add_paths(paths)
        event.acceptProposedAction()
