"""Avvio dell'applicazione."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .core import config, runtime
from .ui import theme
from .ui.main_window import MainWindow
from .ui.setup_dialog import SetupDialog


def _icon() -> QIcon:
    path = config.resource("data", "app.ico")
    if path.exists():
        return QIcon(str(path))
    alt = config.app_dir() / "assets" / "ImageCreatorFree.ico"
    return QIcon(str(alt)) if alt.exists() else QIcon()


def self_test() -> int:
    """Controllo rapido usato dalla pipeline di rilascio: nessuna finestra."""
    from .core import presets

    checks = []
    items = presets.load()
    checks.append(("esempi ufficiali", len(items) >= 30))
    checks.append(("worker presente", config.worker_script().exists()))
    checks.append(("impostazioni scrivibili", _settings_roundtrip()))
    checks.append(("risoluzioni valide", all(
        w % 64 == 0 and h % 64 == 0
        for aspect in config.ASPECT_RATIOS
        for quality in config.QUALITY
        for w, h in [config.resolution_for(aspect, quality)])))
    ok = all(result for _, result in checks)
    for name, result in checks:
        print("%-28s %s" % (name, "ok" if result else "FALLITO"))
    print("%s %s - self test %s" % (APP_NAME, __version__, "superato" if ok else "fallito"))
    return 0 if ok else 1


def check_runtime() -> int:
    """Diagnosi dell'ambiente di calcolo, scritta anche su file.

    Il programma gira senza console, quindi l'esito finisce in
    %LOCALAPPDATA%\\ImageCreatorFree\\diagnostica.txt: è la prima cosa da
    guardare quando la preparazione dice solo "verifica fallita".
    """
    import json
    import subprocess

    from .core import runtime as rt

    righe = ["%s %s" % (APP_NAME, __version__),
             "eseguibile congelato: %s" % config.IS_FROZEN,
             "interprete del runtime: %s" % config.runtime_python(),
             "esiste: %s" % config.runtime_python().exists(),
             "worker: %s" % config.worker_script()]
    prove = [
        ("avvio", "print('vivo')"),
        ("numpy", "import numpy;print(numpy.__version__)"),
        ("torch", "import torch;print(torch.__version__)"),
        ("cuda", "import torch;print(torch.cuda.is_available())"),
        ("transformers", "import transformers;print(transformers.__version__)"),
        ("diffusers", "import diffusers;print(diffusers.__version__)"),
        ("torch+diff", "import torch, diffusers;print('ok')"),
        ("torch+trans", "import torch, transformers;print('ok')"),
        ("trans+diff", "import transformers, diffusers;print('ok')"),
        ("tutti", "import torch, transformers, diffusers, hf_xet;print('ok')"),
        ("come worker", "import torch;import diffusers;"
                        "from diffusers import QwenImage21Pipeline;print('ok')"),
    ]
    # Ambiente passato ai figli: serve per capire quale variabile rompe l'import.
    try:
        import json as _json
        (config.data_dir() / "ambiente.json").write_text(
            _json.dumps({"clean_env": rt.clean_env(),
                         "os_environ": dict(__import__("os").environ)},
                        indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

    import os as _os
    minimale = {k: _os.environ[k] for k in
                ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                 "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")
                if k in _os.environ}
    minimale["PATH"] = _os.pathsep.join([
        _os.path.join(_os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32"),
        _os.environ.get("SYSTEMROOT", r"C:\Windows")])
    ambienti = [("ripulito", rt.clean_env()), ("ereditato", dict(_os.environ)),
                ("minimale", minimale)]
    frammento_critico = ("import torch;import diffusers;"
                         "from diffusers import QwenImage21Pipeline;print('ok')")
    con_thread = (
        "import threading;"
        "threading.stack_size(64*1024*1024);"
        "r=[];"
        "t=threading.Thread(target=lambda: r.append(__import__('diffusers').QwenImage21Pipeline));"
        "t.start();t.join();print('ok' if r else 'vuoto')"
    )
    try:
        esito = subprocess.run(
            [str(config.runtime_python()), "-c", con_thread],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, stdin=subprocess.DEVNULL, env=rt.clean_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        righe.append("import in thread con stack grande: codice %s  uscita %r  messaggi %r" % (
            esito.returncode, esito.stdout.strip()[:40], esito.stderr.strip()[-200:]))
    except Exception as exc:  # noqa: BLE001
        righe.append("import in thread fallito: %s" % exc)

    # Flag di creazione: qualcuno spezza l'eredità che fa morire il figlio?
    for nome_flag, valore in (("distaccato", 0x00000008),
                              ("nuovo gruppo", 0x00000200),
                              ("fuori dal job", 0x01000000),
                              ("distaccato+gruppo", 0x00000208)):
        uscita = config.data_dir() / ("prova_%s.txt" % valore)
        try:
            with open(uscita, "w", encoding="utf-8") as fh:
                esito = subprocess.run(
                    [str(config.runtime_python()), "-c", frammento_critico],
                    stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    timeout=300, env=rt.clean_env(), creationflags=valore)
            righe.append("flag %-18s codice %s  uscita %r" % (
                nome_flag, esito.returncode,
                uscita.read_text(encoding="utf-8", errors="replace").strip()[:60]))
        except Exception as exc:  # noqa: BLE001
            righe.append("flag %s fallito: %s" % (nome_flag, exc))

    # Il processo è dentro un Job Object con limiti? I figli lo ereditano.
    try:
        import ctypes as _c
        from ctypes import wintypes as _w

        class LIMITI(_c.Structure):
            _fields_ = [("PerProcessUserTimeLimit", _c.c_longlong),
                        ("PerJobUserTimeLimit", _c.c_longlong),
                        ("LimitFlags", _w.DWORD),
                        ("MinimumWorkingSetSize", _c.c_size_t),
                        ("MaximumWorkingSetSize", _c.c_size_t),
                        ("ActiveProcessLimit", _w.DWORD),
                        ("Affinity", _c.POINTER(_c.c_ulong)),
                        ("PriorityClass", _w.DWORD),
                        ("SchedulingClass", _w.DWORD)]

        class IO(_c.Structure):
            _fields_ = [("ReadOperationCount", _c.c_ulonglong),
                        ("WriteOperationCount", _c.c_ulonglong),
                        ("OtherOperationCount", _c.c_ulonglong),
                        ("ReadTransferCount", _c.c_ulonglong),
                        ("WriteTransferCount", _c.c_ulonglong),
                        ("OtherTransferCount", _c.c_ulonglong)]

        class ESTESI(_c.Structure):
            _fields_ = [("BasicLimitInformation", LIMITI), ("IoInfo", IO),
                        ("ProcessMemoryLimit", _c.c_size_t),
                        ("JobMemoryLimit", _c.c_size_t),
                        ("PeakProcessMemoryUsed", _c.c_size_t),
                        ("PeakJobMemoryUsed", _c.c_size_t)]

        k32 = _c.windll.kernel32
        dentro = _c.c_int(0)
        k32.IsProcessInJob(k32.GetCurrentProcess(), None, _c.byref(dentro))
        dati = ESTESI()
        letto = k32.QueryInformationJobObject(
            None, 9, _c.byref(dati), _c.sizeof(dati), None)   # ExtendedLimitInformation
        righe.append("dentro un job: %s | limiti letti: %s | flag: 0x%x | "
                     "memoria per processo: %s | memoria job: %s | processi max: %s" % (
                         bool(dentro.value), bool(letto),
                         dati.BasicLimitInformation.LimitFlags,
                         dati.ProcessMemoryLimit, dati.JobMemoryLimit,
                         dati.BasicLimitInformation.ActiveProcessLimit))
    except Exception as exc:  # noqa: BLE001
        righe.append("job non interrogabile: %s" % exc)

    # Doppio salto: l'exe lancia un python che lancia il motore.
    trampolino = (
        "import subprocess,sys;"
        "r=subprocess.run([sys.executable,'-c',"
        "\"from diffusers import QwenImage21Pipeline;print('ok')\"],"
        "capture_output=True,text=True);"
        "print('nipote:',r.returncode,r.stdout.strip()[:20])"
    )
    try:
        esito = subprocess.run(
            [str(config.runtime_python()), "-c", trampolino],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, stdin=subprocess.DEVNULL, env=rt.clean_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        righe.append("doppio salto: codice %s  uscita %r  messaggi %r" % (
            esito.returncode, esito.stdout.strip()[:60], esito.stderr.strip()[-200:]))
    except Exception as exc:  # noqa: BLE001
        righe.append("doppio salto fallito: %s" % exc)

    import ctypes as _ct
    righe.append("console allocata: %s, finestra: %s" % (
        config.ensure_hidden_console(), _ct.windll.kernel32.GetConsoleWindow()))

    # Console propria per il figlio, con la finestra nascosta.
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0                      # SW_HIDE
    uscita = config.data_dir() / "prova_console.txt"
    try:
        with open(uscita, "w", encoding="utf-8") as fh:
            esito = subprocess.run(
                [str(config.runtime_python()), "-c", frammento_critico],
                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                timeout=300, env=rt.clean_env(), startupinfo=info,
                creationflags=0x00000010)      # CREATE_NEW_CONSOLE
        righe.append("pipeline con console propria: codice %s, uscita %r" % (
            esito.returncode, uscita.read_text(encoding="utf-8", errors="replace").strip()[:80]))
    except Exception as exc:  # noqa: BLE001
        righe.append("pipeline con console propria fallita: %s" % exc)

    # Con faulthandler il figlio scrive dove è morto, anche su crash nativo.
    try:
        esito = subprocess.run(
            [str(config.runtime_python()), "-X", "faulthandler", "-c", frammento_critico],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, stdin=subprocess.DEVNULL, env=rt.clean_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        righe.append("faulthandler: codice %s\n%s" % (
            esito.returncode, (esito.stderr or "(nessun messaggio)")[-2500:]))
    except Exception as exc:  # noqa: BLE001
        righe.append("faulthandler fallito: %s" % exc)

    # Con un intermediario: il figlio non è più figlio diretto dell'eseguibile.
    for nome_via, comando in (
            ("cmd", ["cmd", "/c", str(config.runtime_python()), "-c", frammento_critico]),
            ("conhost", ["conhost.exe", "--headless", str(config.runtime_python()),
                         "-c", frammento_critico])):
        try:
            esito = subprocess.run(
                comando, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300, stdin=subprocess.DEVNULL,
                env=rt.clean_env(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            righe.append("pipeline via %-8s codice %s  uscita %r" % (
                nome_via, esito.returncode, esito.stdout.strip()[:60]))
        except Exception as exc:  # noqa: BLE001
            righe.append("pipeline via %s fallita: %s" % (nome_via, exc))

    for nome_amb, ambiente in ambienti:
        try:
            esito = subprocess.run(
                [str(config.runtime_python()), "-c", frammento_critico],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300, stdin=subprocess.DEVNULL, env=ambiente,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            righe.append("pipeline con ambiente %-10s codice %s  uscita %r  messaggi %r" % (
                nome_amb, esito.returncode, esito.stdout.strip()[:60],
                esito.stderr.strip()[-300:]))
        except Exception as exc:  # noqa: BLE001
            righe.append("pipeline con ambiente %s fallita: %s" % (nome_amb, exc))

    for nome, frammento in prove:
        for con_finestra in (False, True):
            flag = 0 if con_finestra else getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                esito = subprocess.run(
                    [str(config.runtime_python()), "-c", frammento],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=300, stdin=subprocess.DEVNULL, env=rt.clean_env(),
                    creationflags=flag)
                righe.append("%-13s %-12s codice %s  uscita %r  messaggi %r" % (
                    nome, "con console" if con_finestra else "senza console",
                    esito.returncode, esito.stdout.strip()[:80],
                    esito.stderr.strip()[-300:]))
            except Exception as exc:  # noqa: BLE001 - si raccoglie qualunque cosa
                righe.append("%-13s fallita: %s: %s" % (nome, type(exc).__name__, exc))

    try:
        righe.append("verifica: " + json.dumps(rt.verify(), ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        righe.append("verifica fallita: %s: %s" % (type(exc).__name__, exc))

    testo = "\n".join(righe)
    try:
        (config.data_dir() / "diagnostica.txt").write_text(testo, encoding="utf-8")
    except OSError:
        pass
    print(testo)
    return 0


def _settings_roundtrip() -> bool:
    try:
        settings = config.Settings.load()
        settings.save()
        return config.Settings.path().exists()
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    config.silence_crash_dialogs()
    config.ensure_hidden_console()
    if "--self-test" in argv:
        return self_test()
    if "--check-runtime" in argv:
        return check_runtime()
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("bais.info")
    app.setWindowIcon(_icon())
    app.setStyleSheet(theme.stylesheet())

    settings = config.Settings.load()
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

    window = MainWindow(settings)
    window.show()

    if "--screenshot" in argv:
        # Usato in sviluppo per controllare l'aspetto della finestra senza interagire.
        from PySide6.QtCore import QTimer

        target = argv[argv.index("--screenshot") + 1]

        def shoot():
            window.grab().save(target)
            app.quit()

        QTimer.singleShot(1200, shoot)
        return app.exec()

    if not runtime.is_ready():
        dialog = SetupDialog(settings, window)
        dialog.setStyleSheet(app.styleSheet())
        dialog.exec()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
