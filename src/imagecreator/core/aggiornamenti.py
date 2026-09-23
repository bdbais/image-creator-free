"""Controllo delle versioni e aggiornamento automatico dalle release di GitHub.

La versione installata si confronta con l'ultima release pubblicata; se ce n'e'
una nuova si scarica l'installer e lo si fa partire in modo silenzioso, poi il
programma si riapre da solo. La versione portatile non si installa: si apre la
pagina di download.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from .. import APP_NAME, __version__
from . import config

REPO = "bdbais/image-creator-free"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
PAGE_LATEST = "https://github.com/%s/releases/latest" % REPO


def versione_tupla(testo: str) -> tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2); le parti non numeriche valgono 0."""
    parti = re.findall(r"\d+", testo or "")
    return tuple(int(p) for p in parti[:4]) or (0,)


def piu_nuova(candidata: str, attuale: str = __version__) -> bool:
    return versione_tupla(candidata) > versione_tupla(attuale)


def ultima_versione(timeout: float = 10.0) -> dict:
    """Legge l'ultima release. Solleva OSError/ValueError se la rete non risponde."""
    richiesta = urllib.request.Request(API_LATEST, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "%s/%s" % (APP_NAME.replace(" ", ""), __version__),
    })
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
        dati = json.loads(risposta.read().decode("utf-8"))
    setup = portatile = somme = ""
    for asset in dati.get("assets", []):
        nome = asset.get("name", "").lower()
        if nome.endswith("-setup.exe"):
            setup = asset.get("browser_download_url", "")
        elif nome.endswith("-portable.exe"):
            portatile = asset.get("browser_download_url", "")
        elif nome == "sha256sums.txt":
            somme = asset.get("browser_download_url", "")
    return {
        "version": (dati.get("tag_name") or "").lstrip("vV"),
        "notes": (dati.get("body") or "").strip(),
        "page": dati.get("html_url") or PAGE_LATEST,
        "setup_url": setup,
        "portable_url": portatile,
        "sha256_url": somme,
    }


def impronta_attesa(url_somme: str, nome_file: str, timeout: float = 20.0) -> str:
    """L'impronta SHA-256 di un file, dal SHA256SUMS.txt pubblicato con la release."""
    richiesta = urllib.request.Request(url_somme, headers={"User-Agent": "ImageCreatorFree"})
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
        testo = risposta.read().decode("utf-8", "replace")
    for riga in testo.splitlines():
        parti = riga.split()
        if (len(parti) == 2 and parti[1].lstrip("*").lower() == nome_file.lower()
                and re.fullmatch(r"[0-9a-fA-F]{64}", parti[0])):
            return parti[0].lower()
    return ""


def note_leggibili(testo: str) -> str:
    """Toglie gli a capo di impaginazione del changelog, tiene elenchi e paragrafi.

    Nel CHANGELOG.md le righe vanno a capo a 80 colonne: le continuazioni di una
    voce d'elenco (righe rientrate) si riuniscono alla voce.
    """
    righe = []
    for riga in testo.replace("\r\n", "\n").split("\n"):
        pulita = riga.strip()
        continua = (riga.startswith((" ", "\t")) and pulita
                    and not pulita.startswith(("- ", "* ", "#")) and righe and righe[-1])
        if continua:
            righe[-1] = righe[-1].rstrip() + " " + pulita
        else:
            righe.append(pulita)
    return "\n".join(righe).strip()


def changelog(versione: str = __version__) -> str:
    """Le novita' di una versione, prese da CHANGELOG.md."""
    for percorso in (config.app_dir() / "CHANGELOG.md",
                     config.app_dir().parent / "CHANGELOG.md"):
        try:
            testo = percorso.read_text(encoding="utf-8")
        except OSError:
            continue
        blocchi = re.split(r"(?m)^## ", testo)
        for blocco in blocchi[1:]:
            titolo, _, corpo = blocco.partition("\n")
            if versione_tupla(titolo.split(" ")[0]) == versione_tupla(versione):
                return corpo.strip()
    return ""


def cartella_installata() -> Path | None:
    """La cartella dell'installazione, se il programma e' stato installato.

    Fuori dall'eseguibile config.app_dir() e' {app}\\app; il disinstallatore
    di Inno Setup sta in {app}.
    """
    for candidata in (config.app_dir(), config.app_dir().parent):
        if list(candidata.glob("unins*.exe")) and (candidata / "ImageCreatorFree.cmd").exists():
            return candidata
    return None


def scarica(url: str, avanzamento: Callable[[int, int], None] | None = None,
            timeout: float = 60.0, sha256: str = "") -> Path:
    """Scarica l'installer in una cartella temporanea e ne restituisce il percorso.

    Con sha256 l'impronta del file deve coincidere, altrimenti il file viene
    cancellato: un installer corrotto o alterato non parte.
    """
    impronta = hashlib.sha256()
    dest = Path(tempfile.gettempdir()) / "ImageCreatorFree-Setup-nuovo.exe"
    richiesta = urllib.request.Request(url, headers={"User-Agent": "ImageCreatorFree"})
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta, \
            open(dest, "wb") as fh:
        totale = int(risposta.headers.get("Content-Length") or 0)
        letti = 0
        while True:
            blocco = risposta.read(1024 * 256)
            if not blocco:
                break
            fh.write(blocco)
            impronta.update(blocco)
            letti += len(blocco)
            if avanzamento:
                avanzamento(letti, totale)
    if totale and dest.stat().st_size != totale:
        raise OSError("Download incompleto: %d di %d byte" % (dest.stat().st_size, totale))
    if sha256 and impronta.hexdigest() != sha256.lower():
        dest.unlink(missing_ok=True)
        raise OSError("L'impronta SHA-256 del file scaricato non corrisponde a quella "
                      "pubblicata: aggiornamento annullato.")
    return dest


def installa_e_riavvia(setup: Path, cartella: Path) -> None:
    """Fa partire l'installer e poi riapre il programma, dopo che questo e' uscito.

    Il comando passa da Esplora risorse, cosi' sopravvive alla chiusura della
    finestra; il timeout lascia al programma il tempo di chiudersi.
    """
    from . import lancio

    lancio.apri_con_explorer([
        "timeout /t 3 /nobreak >nul",
        '"%s" /SILENT /SUPPRESSMSGBOXES /NORESTART /DIR="%s"'
        % (setup, cartella),
        # call, non start: start aprirebbe il lanciatore con cmd /K e la console resterebbe.
        'call "%s"' % (cartella / "ImageCreatorFree.cmd"),
    ], nome="aggiorna.cmd")
