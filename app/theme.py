from app.config import (
    COLOR_BG_DARK, COLOR_PANEL_BG, COLOR_PANEL_ALT, COLOR_PANEL_HOVER,
    COLOR_BORDER_MUTED, COLOR_BORDER_FOCUS, COLOR_BORDER_ACCENT,
    COLOR_CYAN, COLOR_CYAN_DIM, COLOR_GREEN, COLOR_GREEN_DIM,
    COLOR_YELLOW, COLOR_RED, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY,
    COLOR_TEXT_MUTED, FONT_FAMILY_DISPLAY, FONT_FAMILY_MONO
)

def get_cyber_stylesheet() -> str:
    """Returns the Liquid Glass / macOS Sonoma styled QSS stylesheet."""
    return f"""
    /* MASTER APPLICATION CANVAS */
    QMainWindow, QDialog {{
        background-color: #0b1116;
        color: #f8fafc;
        font-family: {FONT_FAMILY_DISPLAY};
        font-size: 13px;
    }}

    QWidget {{
        color: #f8fafc;
        font-family: {FONT_FAMILY_DISPLAY};
        selection-background-color: #0284c7;
        selection-color: #ffffff;
    }}

    /* LIQUID GLASS PANELS & CARDS */
    QFrame#panel, QFrame.cyber-panel {{
        background-color: rgba(18, 26, 34, 0.75);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px;
    }}

    QFrame#panel:hover, QFrame.cyber-panel:hover {{
        border: 1px solid rgba(255, 255, 255, 0.20);
        background-color: rgba(22, 32, 42, 0.82);
    }}

    QFrame#header-bar {{
        background-color: rgba(12, 18, 24, 0.90);
        border-bottom: 1px solid rgba(255, 255, 255, 0.10);
    }}

    QFrame#sidebar {{
        background-color: rgba(10, 15, 20, 0.88);
        border-right: 1px solid rgba(255, 255, 255, 0.10);
    }}

    QFrame#right-rail {{
        background-color: rgba(10, 15, 20, 0.88);
        border-left: 1px solid rgba(255, 255, 255, 0.10);
    }}

    /* HEADINGS & LABELS */
    QLabel {{
        color: #f1f5f9;
        font-family: {FONT_FAMILY_DISPLAY};
    }}

    QLabel#section-header {{
        color: #38bdf8;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }}

    QLabel#panel-title {{
        color: #ffffff;
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.5px;
    }}

    QLabel#metric-val {{
        color: #ffffff;
        font-size: 24px;
        font-weight: 300;
        letter-spacing: -0.5px;
    }}

    QLabel#metric-lbl {{
        color: #94a3b8;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}

    QLabel#terminal-text {{
        font-family: {FONT_FAMILY_MONO};
        font-size: 11px;
        color: #38bdf8;
    }}

    /* BUTTONS */
    QPushButton {{
        background-color: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        color: #f1f5f9;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
    }}

    QPushButton:hover {{
        background-color: rgba(255, 255, 255, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.25);
        color: #ffffff;
    }}

    QPushButton:pressed {{
        background-color: rgba(255, 255, 255, 0.22);
        color: #ffffff;
    }}

    QPushButton:disabled {{
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.06);
        color: rgba(255, 255, 255, 0.3);
    }}

    /* PRIMARY ACCENT BUTTONS */
    QPushButton#action-btn-primary {{
        background-color: #0284c7;
        border: 1px solid #38bdf8;
        color: #ffffff;
        border-radius: 10px;
    }}

    QPushButton#action-btn-primary:hover {{
        background-color: #0369a1;
        border: 1px solid #7dd3fc;
    }}

    /* DANGER / DESTRUCTIVE BUTTON */
    QPushButton#danger-btn {{
        background-color: rgba(239, 68, 68, 0.25);
        border: 1px solid rgba(239, 68, 68, 0.50);
        color: #fca5a5;
        border-radius: 10px;
    }}

    QPushButton#danger-btn:hover {{
        background-color: rgba(239, 68, 68, 0.40);
        color: #ffffff;
    }}

    /* LINE EDITS & INPUTS */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: rgba(15, 23, 30, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        color: #ffffff;
        padding: 6px 10px;
        font-size: 12px;
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid #38bdf8;
        background-color: rgba(18, 28, 38, 0.95);
    }}

    /* TABLES & LISTS */
    QTableWidget, QTreeWidget, QListWidget {{
        background-color: rgba(15, 22, 28, 0.70);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 12px;
        color: #f1f5f9;
        gridline-color: rgba(255, 255, 255, 0.06);
        font-size: 12px;
    }}

    QHeaderView::section {{
        background-color: rgba(22, 32, 40, 0.90);
        color: #94a3b8;
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        font-weight: 600;
        font-size: 11px;
    }}

    QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
        background-color: rgba(56, 189, 248, 0.25);
        color: #ffffff;
    }}

    /* PROGRESS BARS */
    QProgressBar {{
        background-color: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 6px;
        text-align: center;
        color: #ffffff;
        font-size: 10px;
        font-weight: 600;
        height: 12px;
    }}

    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
        border-radius: 5px;
    }}

    /* COMBOBOX */
    QComboBox {{
        background-color: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        color: #ffffff;
        padding: 4px 10px;
        font-size: 12px;
        min-height: 24px;
    }}

    QComboBox:hover {{
        background-color: rgba(255, 255, 255, 0.14);
    }}

    QComboBox QAbstractItemView {{
        background-color: #0f172a;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 8px;
        color: #ffffff;
        selection-background-color: #0284c7;
    }}

    /* SCROLLBARS (macOS Minimalist Glass Pill) */
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}

    QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 0.18);
        min-height: 24px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: rgba(255, 255, 255, 0.32);
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 8px;
        margin: 0px;
    }}

    QScrollBar::handle:horizontal {{
        background: rgba(255, 255, 255, 0.18);
        min-width: 24px;
        border-radius: 4px;
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    """
