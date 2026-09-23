# -*- mode: python ; coding: utf-8 -*-
"""Build dell'eseguibile Windows: un solo file, senza finestra di console.

torch e diffusers NON entrano qui: vivono nel runtime separato che l'app
installa al primo avvio (src/imagecreator/core/runtime.py).
"""

block_cipher = None

datas = [
    ("src/imagecreator/data/presets.json", "data"),
    ("src/imagecreator/data/presets_extra.json", "data"),
    ("src/imagecreator", "app/src/imagecreator"),
    ("ImageCreatorFree.pyw", "app"),
    ("src/imagecreator/data/app.ico", "data"),
    ("worker/qwen_worker.py", "data"),
    ("LICENSE", "."),
    ("NOTICE", "."),
]

a = Analysis(
    ["ImageCreatorFree.pyw"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "torch", "diffusers", "transformers", "numpy", "scipy",
        "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtQuick", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ImageCreatorFree",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/ImageCreatorFree.ico",
    version="build/version_info.txt",
)
