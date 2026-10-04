"""Striscia delle immagini di riferimento (fino a dieci, come consente il modello)."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core import config

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
            "Trascina o incolla (Ctrl+V) fino a %d immagini: il prompt può citarle come "
            "\"image 1\", \"image 2\"..." % MAX_REFS)
        self.hint.setObjectName("hint")

        add_btn = QPushButton("Aggiungi...")
        add_btn.clicked.connect(self.browse)
        paste_btn = QPushButton("Incolla")
        paste_btn.setToolTip("Ctrl+V: un'immagine copiata, uno screenshot o dei file copiati")
        paste_btn.clicked.connect(self.paste_from_clipboard)
        rm_btn = QPushButton("Togli")
        rm_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("Svuota")
        clear_btn.clicked.connect(self.clear)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.hint, 1)
        buttons.addWidget(add_btn)
        buttons.addWidget(paste_btn)
        buttons.addWidget(rm_btn)
        buttons.addWidget(clear_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addLayout(buttons)
        box.addWidget(self.list)

        # Ctrl+V lo gestisce la finestra principale: una seconda scorciatoia uguale
        # qui la renderebbe ambigua e nessuna delle due scatterebbe.
        copia = QShortcut(QKeySequence.Copy, self.list)
        copia.setContext(Qt.WidgetShortcut)
        copia.activated.connect(self.copy_selected)
        togli = QShortcut(QKeySequence.Delete, self.list)
        togli.setContext(Qt.WidgetShortcut)
        togli.activated.connect(self.remove_selected)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)

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

    # ------------------------------------------------------------------ appunti
    def paste_from_clipboard(self) -> int:
        """Aggiunge quello che c'e' negli appunti; restituisce quante immagini.

        File copiati in Esplora risorse, un'immagine copiata (browser, Paint,
        Strumento di cattura) o un percorso scritto come testo.
        """
        prima = self.count()
        self.add_paths(clipboard_image_paths())
        aggiunte = self.count() - prima
        if not aggiunte:
            self.hint.setText("Negli appunti non c'è un'immagine da incollare.")
        return aggiunte

    def copy_selected(self) -> None:
        items = self.list.selectedItems()
        if items:
            copy_image_to_clipboard(items[0].data(Qt.UserRole))

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        item = self.list.itemAt(pos)
        if item is not None:
            if not item.isSelected():
                self.list.setCurrentItem(item)
            menu.addAction("Copia l'immagine", self.copy_selected)
            menu.addAction("Togli", self.remove_selected)
            menu.addSeparator()
        menu.addAction("Incolla", self.paste_from_clipboard)
        menu.exec(self.list.viewport().mapToGlobal(pos))

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
                "Trascina o incolla (Ctrl+V) fino a %d immagini: il prompt può citarle come "
                "\"image 1\", \"image 2\"..." % MAX_REFS)
        self.changed.emit(count)

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event):
        # Dal browser arriva spesso l'immagine stessa, con un indirizzo web.
        self.add_paths(mime_image_paths(event.mimeData()))
        event.acceptProposedAction()


def mime_image_paths(mime) -> list[str]:
    """Percorsi di immagini da un QMimeData: file locali, immagine in memoria o testo."""
    paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
    paths = [p for p in paths if Path(p).suffix.lower() in EXTENSIONS]
    if paths:
        return paths
    if mime.hasImage():
        image = QImage(mime.imageData())
        if not image.isNull():
            return [save_pasted_image(image)]
    if mime.hasText():
        testo = [r.strip().strip('"') for r in mime.text().splitlines() if r.strip()]
        return [r for r in testo if Path(r).suffix.lower() in EXTENSIONS and Path(r).exists()]
    return []


def clipboard_image_paths() -> list[str]:
    return mime_image_paths(QGuiApplication.clipboard().mimeData())


def save_pasted_image(image: QImage) -> str:
    """Le immagini incollate diventano file: i riferimenti sono sempre percorsi."""
    cartella = config.data_dir() / "appunti"
    cartella.mkdir(parents=True, exist_ok=True)
    base = cartella / ("incollata-%s" % time.strftime("%Y%m%d-%H%M%S"))
    path, n = base.with_suffix(".png"), 2
    while path.exists():
        path = cartella / ("%s-%d.png" % (base.name, n))
        n += 1
    image.save(str(path), "PNG")
    return str(path)


def copy_image_to_clipboard(path: str) -> bool:
    image = QImage(str(path))
    if image.isNull():
        return False
    QGuiApplication.clipboard().setImage(image)
    return True
