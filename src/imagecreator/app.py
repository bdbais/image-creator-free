"""Avvio dell'applicazione."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .core import config, lancio, runtime
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

    righe = ["%s %s" % (APP_NAME, __version__),
             "eseguibile congelato: %s" % config.IS_FROZEN,
             "ambiente: %s" % config.runtime_dir(),
             "interprete: %s (esiste: %s)" % (config.runtime_python(),
                                              config.runtime_python().exists()),
             "interprete della finestra: %s" % lancio.runtime_pythonw(),
             "pronto: %s" % runtime.is_ready()]
    try:
        righe.append("verifica: " + json.dumps(runtime.verify(), ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - si raccoglie qualunque cosa
        righe.append("verifica fallita: %s: %s" % (type(exc).__name__, exc))
    # L'import che fa cadere i processi nati dall'eseguibile, provato come lo
    # fa davvero la finestra: in un processo aperto da Esplora risorse.
    if config.runtime_python().exists():
        righe.append("pipeline da explorer: %s" % lancio.prova_pipeline())

    testo = "\n".join(righe)
    try:
        (config.data_dir() / "diagnostica.txt").write_text(testo, encoding="utf-8")
    except OSError:
        pass
    print(testo)
    return 0


def _applicazione(argv: list[str]) -> QApplication:
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("bais.info")
    app.setWindowIcon(_icon())
    app.setStyleSheet(theme.stylesheet())
    return app


def prepara_ambiente(argv: list[str]) -> int:
    """Mostra solo la finestra di preparazione e poi esce.

    La finestra vera gira con il Python dell'ambiente appena installato: un
    eseguibile impacchettato non è un buon genitore per il processo che carica
    il modello.
    """
    app = _applicazione(argv)
    settings = config.Settings.load()
    if runtime.is_ready():
        runtime.remember_location()
        return 0
    dialog = SetupDialog(settings, None)
    dialog.setStyleSheet(app.styleSheet())
    dialog.exec()
    return 0 if runtime.is_ready() else 1


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
    if "--prepara" in argv:
        return prepara_ambiente(argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, __version__))
        return 0

    if config.IS_FROZEN and "--screenshot" not in argv:
        # L'eseguibile prepara l'ambiente e passa la mano: la finestra gira
        # con il Python dell'ambiente, in un processo che non discende da qui.
        esito = prepara_ambiente(argv)
        if esito != 0:
            return esito
        try:
            if lancio.avvia_finestra():
                return 0
        except OSError as exc:
            print("Avvio fuori dall'eseguibile fallito: %s" % exc, file=sys.stderr)
        # Ripiego: la finestra funziona, la generazione forse no.

    app = _applicazione(argv)

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

    if runtime.is_ready():
        runtime.remember_location()
    else:
        dialog = SetupDialog(settings, window)
        dialog.setStyleSheet(app.styleSheet())
        dialog.exec()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
