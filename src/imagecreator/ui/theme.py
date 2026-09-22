"""Palette e foglio di stile, coerenti con il sito del progetto."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

LIGHT = {
    "bg": "#ffffff", "bg_soft": "#f5f7fa", "bg_card": "#ffffff",
    "fg": "#12181f", "fg_muted": "#5b6773", "border": "#e2e8f0",
    "brand": "#0a6ed1", "brand_fg": "#ffffff",
    "good": "#1b7f4b", "warn": "#b26b00", "bad": "#b3261e",
    "field": "#ffffff",
}

DARK = {
    "bg": "#0d1117", "bg_soft": "#131a23", "bg_card": "#161d27",
    "fg": "#e6edf3", "fg_muted": "#9aa7b4", "border": "#252e3a",
    "brand": "#4c9aff", "brand_fg": "#06121f",
    "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171",
    "field": "#0f1620",
}


def is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        try:
            return scheme() == Qt.ColorScheme.Dark
        except (AttributeError, TypeError):
            pass
    return True


def palette() -> dict:
    return DARK if is_dark() else LIGHT


def stylesheet(c: dict | None = None) -> str:
    c = c or palette()
    return """
    QWidget {{ background: {bg}; color: {fg};
               font-family: "Segoe UI", system-ui, sans-serif; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: {bg}; }}
    QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
    QLabel#muted, QLabel#hint {{ color: {fg_muted}; }}
    QLabel#badge {{ color: {fg_muted}; border: 1px solid {border};
                    border-radius: 8px; padding: 1px 6px; }}

    QFrame#card {{ background: {bg_card}; border: 1px solid {border}; border-radius: 14px; }}
    QFrame#sep {{ background: {border}; max-height: 1px; border: none; }}

    QPlainTextEdit, QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{
        background: {field}; border: 1px solid {border}; border-radius: 10px;
        padding: 6px 8px; selection-background-color: {brand}; selection-color: {brand_fg};
    }}
    QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
    QDoubleSpinBox:focus {{ border: 1px solid {brand}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {bg_card}; border: 1px solid {border};
        selection-background-color: {brand}; selection-color: {brand_fg}; }}

    QPushButton {{ background: {bg_soft}; border: 1px solid {border}; border-radius: 10px;
                   padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {brand}; }}
    QPushButton:disabled {{ color: {fg_muted}; border-color: {border}; }}
    QPushButton#primary {{ background: {brand}; color: {brand_fg}; border: none;
                           font-weight: 600; padding: 10px 18px; }}
    QPushButton#primary:disabled {{ background: {bg_soft}; color: {fg_muted}; }}
    QPushButton#danger {{ color: {bad}; }}
    QPushButton#link {{ background: transparent; border: none; color: {brand};
                        text-align: left; padding: 2px; }}

    QProgressBar {{ background: {bg_soft}; border: 1px solid {border}; border-radius: 8px;
                    height: 10px; text-align: center; color: {fg_muted}; }}
    QProgressBar::chunk {{ background: {brand}; border-radius: 7px; }}

    QTabWidget::pane {{ border: 1px solid {border}; border-radius: 12px; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {fg_muted}; padding: 8px 14px;
                    border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {fg}; border-bottom: 2px solid {brand}; }}

    QListWidget {{ padding: 4px; }}
    QListWidget::item {{ border-radius: 8px; padding: 6px; }}
    QListWidget::item:selected {{ background: {brand}; color: {brand_fg}; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {fg_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 30px; }}

    QGroupBox {{ border: 1px solid {border}; border-radius: 12px; margin-top: 14px;
                 padding-top: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px;
                        color: {fg_muted}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {brand}; width: 14px; margin: -6px 0;
                                  border-radius: 7px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border};
                            border-radius: 4px; background: {field}; }}
    QCheckBox::indicator:checked {{ background: {brand}; border-color: {brand}; }}
    QToolTip {{ background: {bg_card}; color: {fg}; border: 1px solid {border};
                padding: 6px; border-radius: 8px; }}
    QStatusBar {{ background: {bg_soft}; color: {fg_muted}; }}
    QSplitter::handle {{ background: {border}; }}
    """.format(**c)
