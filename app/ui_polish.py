"""
App-wide visual polish shared by every page:
  • a dark base palette (no more white scroll-area / spin-box backgrounds under Fusion)
  • a blurred copy of the Home wallpaper painted behind all pages (liquid-glass look)
  • consistent table styling (no row-number column, taller rows, no grid)
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QPainter, QPixmap, QImage, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QTableWidget, QTableView, QAbstractItemView, QHeaderView, QScrollArea, QFrame
)


def apply_dark_palette(app):
    pal = QPalette()
    base = QColor(11, 17, 22)
    for role, color in [
        (QPalette.Window, base), (QPalette.WindowText, QColor(241, 245, 249)),
        (QPalette.Base, QColor(15, 22, 29)), (QPalette.AlternateBase, QColor(20, 28, 36)),
        (QPalette.Text, QColor(241, 245, 249)), (QPalette.Button, QColor(24, 32, 40)),
        (QPalette.ButtonText, QColor(241, 245, 249)), (QPalette.ToolTipBase, QColor(14, 20, 27)),
        (QPalette.ToolTipText, QColor(241, 245, 249)), (QPalette.Highlight, QColor(3, 105, 161)),
        (QPalette.HighlightedText, QColor(255, 255, 255)), (QPalette.PlaceholderText, QColor(100, 116, 139)),
        (QPalette.Link, QColor(56, 189, 248)), (QPalette.Light, QColor(40, 50, 60)),
        (QPalette.Midlight, QColor(32, 42, 52)), (QPalette.Mid, QColor(26, 34, 42)),
        (QPalette.Dark, QColor(8, 12, 16)), (QPalette.Shadow, QColor(0, 0, 0)),
    ]:
        pal.setColor(role, color)
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(100, 116, 139))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(100, 116, 139))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(100, 116, 139))
    app.setPalette(pal)


EXTRA_QSS = """
/* Slimmer default padding so buttons with a fixed height never clip their text */
QPushButton { padding: 3px 12px; }
/* Scroll areas are see-through so the glass backdrop shows */
QScrollArea, QScrollArea > QWidget#qt_scrollarea_viewport { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QStackedWidget { background: transparent; }

/* Buttons placed inside table cells */
QTableWidget QPushButton { padding: 0px 10px; font-size: 10px; font-weight: 700;
                           border-radius: 7px; min-height: 0px; }
QTableWidget { alternate-background-color: rgba(255,255,255,0.025); }
QTableWidget::item { padding: 0px 6px; border: none; }
QTableCornerButton::section { background: transparent; border: none; }
QHeaderView { background: transparent; }

/* Inputs that had no dark style */
QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QDateTimeEdit {
    background-color: rgba(15, 23, 30, 0.85); border: 1px solid rgba(255,255,255,0.14);
    border-radius: 8px; color: #ffffff; padding: 4px 8px; min-height: 22px; }
QSpinBox:focus, QTimeEdit:focus { border: 1px solid #38bdf8; }
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {
    width: 16px; border: none; background: transparent; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.30); background: rgba(255,255,255,0.06); }
QCheckBox::indicator:checked { background: #0284c7; border: 1px solid #38bdf8; }
QToolTip { background: #0e151c; color: #f1f5f9; border: 1px solid rgba(255,255,255,0.15);
           border-radius: 6px; padding: 5px 8px; }
QComboBox QAbstractItemView { background: #111a22; color: #f1f5f9; border: 1px solid rgba(255,255,255,0.12);
                              selection-background-color: #0369a1; outline: none; }
QCalendarWidget QWidget { alternate-background-color: transparent; }

QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: rgba(255,255,255,0.06); color: #94a3b8; border: 1px solid rgba(255,255,255,0.08);
               padding: 6px 16px; margin-right: 6px; border-radius: 10px; font-size: 12px; font-weight: 600; }
QTabBar::tab:selected { background: rgba(56,189,248,0.22); color: #ffffff; border: 1px solid rgba(56,189,248,0.45); }
QTabBar::tab:hover:!selected { background: rgba(255,255,255,0.12); color: #e2e8f0; }
"""


def polish_tables(root: QWidget):
    """Uniform modern look for every table below `root` (QTableWidget and model-based QTableView)."""
    for t in root.findChildren(QTableView):
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(36)
        t.setShowGrid(False)
        t.setWordWrap(False)
        # Paths read best elided in the middle; everything else at the end
        t.setTextElideMode(Qt.ElideMiddle if t.property("elide_middle") else Qt.ElideRight)
        t.setAlternatingRowColors(True)
        t.setFrameShape(QFrame.NoFrame)
        if t.selectionBehavior() == QAbstractItemView.SelectItems:
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = t.horizontalHeader()
        hh.setHighlightSections(False)
        if not t.property("compact_columns"):    # tables with icon-sized columns opt out
            hh.setMinimumSectionSize(70)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for sa in root.findChildren(QScrollArea):
        sa.viewport().setAutoFillBackground(False)
        w = sa.widget()
        if w is not None:
            w.setAutoFillBackground(False)


class GlassBackdrop(QWidget):
    """Central widget that paints a blurred, darkened copy of the Home wallpaper."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._small = None        # tiny blurred source image
        self._cache = None        # scaled to widget size
        self._dim = 66            # percent darkness over the wallpaper

    def set_dim(self, percent: int):
        self._dim = max(0, min(100, int(percent)))
        self.update()

    def set_image(self, img: QImage):
        if img is None or img.isNull():
            return
        # Down-sample in two smooth passes = cheap, soft gaussian-like blur
        small = img.scaledToWidth(320, Qt.SmoothTransformation)
        small = small.scaledToWidth(48, Qt.SmoothTransformation)
        self._small = small
        self._cache = None
        self.update()

    def resizeEvent(self, event):
        self._cache = None
        super().resizeEvent(event)

    def _scaled(self):
        if self._cache is None and self._small is not None:
            w, h = self.width(), self.height()
            img = self._small.scaled(w // 4 + 1, h // 4 + 1, Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
            img = img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            pm = QPixmap.fromImage(img)
            self._cache = pm.copy((pm.width() - w) // 2, (pm.height() - h) // 2, w, h)
        return self._cache

    def paintEvent(self, event):
        p = QPainter(self)
        r = self.rect()
        pm = self._scaled()
        if pm is not None:
            p.drawPixmap(0, 0, pm)
            p.fillRect(r, QColor(6, 10, 14, int(self._dim * 2.55)))
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            g.setColorAt(0, QColor(14, 24, 34))
            g.setColorAt(1, QColor(6, 10, 14))
            p.fillRect(r, g)


# ---------------------------------------------------------------------------
#  Shared right-click menu for any table that lists files
# ---------------------------------------------------------------------------

def open_path(path):
    import os
    if path and os.path.exists(path):
        os.startfile(path)


def reveal_path(path):
    import os
    import subprocess
    if path and os.path.exists(path):
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')


def attach_file_menu(table, path_for_row, open_on_double_click=True):
    """Adds Open / Show in Explorer / Copy path to `table`; path_for_row(row) -> str | None."""
    from PySide6.QtGui import QCursor, QGuiApplication
    from app.widgets.home.common import make_menu, hicon

    def show(pos):
        item = table.itemAt(pos)
        if item is None:
            return
        path = path_for_row(item.row())
        if not path:
            return
        m = make_menu(table)
        m.addAction(hicon("eye", "#e2e8f0", 14), "Open", lambda: open_path(path))
        m.addAction(hicon("folder", "#e2e8f0", 14), "Show in Explorer", lambda: reveal_path(path))
        m.addAction(hicon("duplicate_finder", "#e2e8f0", 14), "Copy path",
                    lambda: QGuiApplication.clipboard().setText(path))
        m.exec(QCursor.pos())

    table.setContextMenuPolicy(Qt.CustomContextMenu)
    table.customContextMenuRequested.connect(show)
    if open_on_double_click:
        table.itemDoubleClicked.connect(lambda it: open_path(path_for_row(it.row())))
