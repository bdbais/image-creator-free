# -*- coding: utf-8 -*-
"""Punto di ingresso senza console (pythonw e PyInstaller)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))



def _mostra_errore() -> None:
    # Con pythonw non c'e' console: senza questo avviso un errore all'avvio
    # farebbe solo sparire la finestra.
    import ctypes
    import traceback
    testo = traceback.format_exc()[-1800:]
    ctypes.windll.user32.MessageBoxW(
        None, "Il programma non riesce a partire.\n\n" + testo,
        "Image Creator Free", 0x10)


if __name__ == "__main__":
    try:
        from imagecreator.app import main
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        _mostra_errore()
        sys.exit(1)
