"""Avvio della finestra con il Python dell'ambiente, fuori dall'eseguibile.

Un processo che discende dall'eseguibile PyInstaller (figlio o nipote) muore
con 0xC0000005 quando importa la pipeline Qwen; lo stesso interprete lanciato
da Esplora risorse funziona. Per questo l'eseguibile non avvia la finestra da
se': scrive un piccolo .cmd e chiede a Esplora risorse di aprirlo, cosi' il
processo nasce figlio di explorer e non nostro.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config


def runtime_pythonw() -> Path | None:
    """L'interprete senza console dell'ambiente: venv (Scripts) o embeddable."""
    for candidato in (config.runtime_dir() / "Scripts" / "pythonw.exe",
                      config.runtime_dir() / "pythonw.exe"):
        if candidato.exists():
            return candidato
    return None


def script_finestra() -> Path:
    """Il punto di ingresso da far girare con il Python dell'ambiente.

    Con l'installer i sorgenti stanno gia' accanto all'eseguibile; la versione
    portatile li porta nel bundle e li copia in %LOCALAPPDATA% a ogni avvio,
    cosi' restano allineati all'eseguibile.
    """
    installato = config.app_dir() / "app" / "ImageCreatorFree.pyw"
    if installato.exists():
        return installato

    bundle = Path(getattr(sys, "_MEIPASS", config.app_dir()))
    dest = config.data_dir() / "app"
    shutil.rmtree(dest / "src", ignore_errors=True)
    shutil.copytree(bundle / "app" / "src", dest / "src", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(bundle / "app" / "ImageCreatorFree.pyw", dest / "ImageCreatorFree.pyw")
    # Fuori dall'eseguibile config.app_dir() e' questa cartella: il worker va qui.
    (dest / "worker").mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle / "data" / "qwen_worker.py", dest / "worker" / "qwen_worker.py")
    return dest / "ImageCreatorFree.pyw"


def apri_con_explorer(comandi: list[str], nome: str = "avvio.cmd") -> Path:
    """Scrive un .cmd con questi comandi e lo fa aprire a Esplora risorse.

    Il processo creato eredita l'ambiente di explorer, non il nostro: le
    variabili che servono vanno impostate nel file.
    """
    righe = ["@echo off",
             # explorer apre una console visibile: la riapriamo ridotta a icona.
             'if not "%~1"=="min" (start "" /min "%~f0" min & exit /b)',
             "chcp 65001 >nul"]
    scelta = os.environ.get("ICF_DATA_DIR", "").strip()
    if scelta:
        righe.append('set "ICF_DATA_DIR=%s"' % scelta)
    righe.append('set "PYTHONUTF8=1"')
    righe.extend(comandi)
    # "start" apre i .cmd con cmd /K: senza exit la console ridotta resterebbe aperta.
    righe.append("exit")
    cmd = config.data_dir() / nome
    cmd.write_bytes(("\r\n".join(righe) + "\r\n").encode("utf-8"))
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    subprocess.Popen([str(explorer), str(cmd)], close_fds=True)
    return cmd


def avvia_finestra() -> bool:
    """Lancia la finestra con pythonw dell'ambiente. False se l'ambiente manca."""
    pythonw = runtime_pythonw()
    if pythonw is None:
        return False
    apri_con_explorer(['start "" "%s" "%s"' % (pythonw, script_finestra())])
    return True


def esegui_da_explorer(argomenti: list[str], attesa: float = 600.0,
                       nome: str = "esegui") -> tuple[int | None, str]:
    """Esegue un comando in un processo nato da explorer e ne attende l'esito.

    Restituisce (codice di uscita, output unito); il codice e' None se il
    comando non finisce in tempo.
    """
    base = config.data_dir() / nome
    uscita = base.with_suffix(".out")
    codice = base.with_suffix(".codice")
    for vecchio in (uscita, codice):
        vecchio.unlink(missing_ok=True)
    comando = " ".join('"%s"' % a for a in argomenti)
    apri_con_explorer([
        '%s > "%s" 2>&1' % (comando, uscita),
        # Redirezione davanti: "echo 0> file" verrebbe letto come handle 0.
        '> "%s.tmp" echo %%errorlevel%%' % codice,
        'move /y "%s.tmp" "%s" >nul' % (codice, codice),
    ], nome=nome + ".cmd")
    limite = time.time() + attesa
    while time.time() < limite:
        if codice.exists():
            try:
                valore = int(codice.read_text(encoding="utf-8", errors="replace").strip())
            except ValueError:
                valore = -1
            testo = uscita.read_text(encoding="utf-8", errors="replace") \
                if uscita.exists() else ""
            return valore, testo
        time.sleep(0.3)
    return None, "nessuna risposta in %d secondi" % attesa


def prova_pipeline(attesa: float = 300.0) -> str:
    """Diagnostica: importa la pipeline Qwen in un processo nato da explorer."""
    script = config.data_dir() / "prova_pipeline.py"
    script.write_text("from diffusers import QwenImage21Pipeline\nprint('ok')\n",
                      encoding="utf-8")
    codice, testo = esegui_da_explorer(
        [str(config.runtime_python()), str(script)], attesa, nome="prova")
    return "codice %s, %s" % (codice, testo.strip()[-300:])
