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


def _settings_roundtrip() -> bool:
    try:
        settings = config.Settings.load()
        settings.save()
        return config.Settings.path().exists()
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
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
