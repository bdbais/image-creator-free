"""Finestra Informazioni (novita' e controllo versione) e aggiornamento automatico."""
from __future__ import annotations

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from .. import APP_NAME, MODEL_ID, __version__
from ..core import aggiornamenti, runtime


class ControlloVersione(QThread):
    """Chiede a GitHub l'ultima versione senza bloccare la finestra."""
    trovata = Signal(dict)
    fallito = Signal(str)

    def run(self):
        try:
            self.trovata.emit(aggiornamenti.ultima_versione())
        except (OSError, ValueError) as exc:
            self.fallito.emit(str(exc))


class Scaricatore(QThread):
    avanzamento = Signal(int, int)
    finito = Signal(str)
    fallito = Signal(str)

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info

    def run(self):
        try:
            # Come negli altri programmi: si installa solo un file verificato.
            atteso = ""
            if self.info.get("sha256_url"):
                nome = self.info["setup_url"].rsplit("/", 1)[-1]
                atteso = aggiornamenti.impronta_attesa(self.info["sha256_url"], nome)
            if not atteso:
                raise OSError("La release non pubblica l'impronta SHA-256 dell'installer.")
            percorso = aggiornamenti.scarica(
                self.info["setup_url"],
                lambda letti, totale: self.avanzamento.emit(letti, totale), sha256=atteso)
            self.finito.emit(str(percorso))
        except OSError as exc:
            self.fallito.emit(str(exc))


def aggiorna(parent, info: dict) -> None:
    """Scarica e installa la versione nuova; se il programma e' portatile apre la pagina."""
    cartella = aggiornamenti.cartella_installata()
    if cartella is None or not info.get("setup_url"):
        QDesktopServices.openUrl(QUrl(info.get("page") or aggiornamenti.PAGE_LATEST))
        return

    attesa = QProgressDialog("Scarico la versione %s..." % info["version"], "Annulla",
                             0, 100, parent)
    attesa.setWindowTitle("Aggiornamento")
    attesa.setMinimumDuration(0)
    attesa.setValue(0)
    lavoro = Scaricatore(info, parent)
    # Annullamento in un flag nostro: chiudere un QProgressDialog emette anche
    # canceled(), quindi wasCanceled() dopo close() risulta sempre vero e
    # l'aggiornamento scaricato non partiva mai.
    stato = {"annullato": False}

    def annulla():
        stato["annullato"] = True

    def chiudi_attesa():
        attesa.canceled.disconnect(annulla)
        attesa.close()

    def avanza(letti, totale):
        if totale:
            attesa.setValue(int(letti * 100 / totale))
            attesa.setLabelText("Scarico la versione %s... %.0f di %.0f MB" % (
                info["version"], letti / 2 ** 20, totale / 2 ** 20))

    def pronto(percorso):
        if stato["annullato"]:
            return
        chiudi_attesa()
        from pathlib import Path
        aggiornamenti.installa_e_riavvia(Path(percorso), cartella)
        # La finestra si chiude: l'installer parte appena e' uscita e poi la riapre.
        parent.window().close()

    def errore(messaggio):
        if stato["annullato"]:
            return
        chiudi_attesa()
        QMessageBox.warning(parent, "Aggiornamento non riuscito",
                            "Non riesco a scaricare l'aggiornamento:\n%s\n\n"
                            "Puoi scaricarlo a mano dalla pagina delle versioni." % messaggio)
        QDesktopServices.openUrl(QUrl(info.get("page") or aggiornamenti.PAGE_LATEST))

    lavoro.avanzamento.connect(avanza)
    lavoro.finito.connect(pronto)
    lavoro.fallito.connect(errore)
    # Niente terminate(): uccidere un thread a meta' download lascia il file
    # aperto. Se si annulla, il download finisce in silenzio e viene ignorato.
    attesa.canceled.connect(annulla)
    lavoro.start()


def proponi(parent, info: dict) -> None:
    """Chiede se aggiornare, mostrando le novita' della versione nuova."""
    installato = aggiornamenti.cartella_installata() is not None
    dialogo = QDialog(parent)
    dialogo.setWindowTitle("Nuova versione disponibile")
    box = QVBoxLayout(dialogo)
    box.addWidget(QLabel("<b>È disponibile %s %s</b> (hai la %s)." % (
        APP_NAME, info["version"], __version__)))
    if info.get("notes"):
        box.addWidget(QLabel("Novità:"))
        note = QTextBrowser()
        note.setOpenExternalLinks(True)
        note.setMarkdown(aggiornamenti.note_leggibili(info["notes"]))
        note.setFrameShape(QTextBrowser.NoFrame)
        box.addWidget(note, 1)
    riga = QHBoxLayout()
    riga.addStretch(1)
    dopo = QPushButton("Più tardi")
    dopo.clicked.connect(dialogo.reject)
    si = QPushButton("Aggiorna ora" if installato else "Scarica")
    si.setDefault(True)
    si.clicked.connect(dialogo.accept)
    riga.addWidget(dopo)
    riga.addWidget(si)
    box.addLayout(riga)
    if info.get("notes"):
        # Larga quanto serve alle righe, alta quanto il testo, entro lo schermo.
        larghezza = 640
        note.document().setTextWidth(larghezza - 40)
        altezza = int(note.document().size().height()) + 150
        schermo = dialogo.screen().availableGeometry() if dialogo.screen() else None
        massima = int(schermo.height() * 0.8) if schermo else 800
        dialogo.resize(larghezza, max(260, min(altezza, massima)))
    if dialogo.exec() == QDialog.Accepted:
        aggiorna(parent, info)


class InfoDialog(QDialog):
    """Versione, novita' di questa versione e controllo degli aggiornamenti."""

    def __init__(self, parent, site_url: str, repo_url: str, model_url: str,
                 donate_url: str, output_dir: str):
        super().__init__(parent)
        self.setWindowTitle("Informazioni")
        self.resize(620, 560)
        self.info: dict | None = None
        box = QVBoxLayout(self)

        dati = runtime.installed_info()
        testa = QLabel(
            "<h2>%s %s</h2>"
            "Interfaccia per <a href='%s'>%s</a> in locale.<br>"
            "Codice: MIT · <a href='%s'>GitHub</a> · <a href='%s'>sito</a><br>"
            "Pesi del modello: Qwen Research License (uso non commerciale).<br>"
            "Runtime: torch %s · diffusers %s<br>Immagini in: %s<br>"
            "<a href='%s'>Sostieni il progetto</a>" % (
                APP_NAME, __version__, model_url, MODEL_ID, repo_url, site_url,
                dati.get("torch", "-"), dati.get("diffusers", "-"), output_dir, donate_url))
        testa.setOpenExternalLinks(True)
        testa.setWordWrap(True)
        box.addWidget(testa)

        box.addWidget(QLabel("<b>Novità della versione %s</b>" % __version__))
        novita = QTextBrowser()
        novita.setOpenExternalLinks(True)
        novita.setMarkdown(aggiornamenti.changelog() or "Nessuna nota per questa versione.")
        box.addWidget(novita, 1)

        riga = QHBoxLayout()
        self.stato = QLabel("Controllo se c'è una versione nuova...")
        self.stato.setWordWrap(True)
        self.bottone = QPushButton("Controlla di nuovo")
        self.bottone.clicked.connect(self.controlla)
        chiudi = QPushButton("Chiudi")
        chiudi.clicked.connect(self.accept)
        riga.addWidget(self.stato, 1)
        riga.addWidget(self.bottone)
        riga.addWidget(chiudi)
        box.addLayout(riga)
        self.controlla()

    def controlla(self):
        if self.bottone.text() == "Aggiorna ora" and self.info:
            aggiorna(self, self.info)
            return
        self.stato.setText("Controllo se c'è una versione nuova...")
        self.bottone.setEnabled(False)
        self._lavoro = ControlloVersione(self)
        self._lavoro.trovata.connect(self._risultato)
        self._lavoro.fallito.connect(self._errore)
        self._lavoro.start()

    def _risultato(self, info: dict):
        self.bottone.setEnabled(True)
        if aggiornamenti.piu_nuova(info.get("version", "")):
            self.info = info
            self.stato.setText("È disponibile la versione <b>%s</b>." % info["version"])
            self.bottone.setText("Aggiorna ora"
                                 if aggiornamenti.cartella_installata() else "Scarica")
            if self.bottone.text() == "Scarica":
                self.bottone.clicked.disconnect()
                self.bottone.clicked.connect(
                    lambda: QDesktopServices.openUrl(QUrl(info["page"])))
        else:
            self.stato.setText("Hai l'ultima versione (%s)." % __version__)

    def _errore(self, messaggio: str):
        self.bottone.setEnabled(True)
        self.stato.setText("Non riesco a controllare la versione: %s" % messaggio[:120])
