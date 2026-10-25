"""
Services — the server's background services: status, uptime, restarts, start /
stop / restart, start-automatically, settings, extra actions and live logs.
"""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QCheckBox,
    QFormLayout, QLineEdit, QSpinBox, QPlainTextEdit, QMessageBox
)

from app.icons import get_pixmap, get_icon
from app.server.services import RUNNING, STOPPED, FAILED, STARTING, fmt_uptime

GREEN, AMBER, RED, DIM, MUTED, TEXT, SOFT = "#22c55e", "#f59e0b", "#f43f5e", "#64748b", "#94a3b8", "#f8fafc", "#cbd5e1"
STATUS = {RUNNING: ("Running", GREEN), STARTING: ("Starting…", AMBER), FAILED: ("Failed", RED),
          STOPPED: ("Stopped", DIM)}


def _lbl(text="", color=TEXT, size=12, weight=500):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{weight};background:transparent;border:none;")
    return l


def _btn(text, icon=None, primary=False, danger=False):
    b = QPushButton(f" {text}" if icon else text)
    if icon:
        b.setIcon(get_icon(icon, "#04140a" if primary else "#e2e8f0", 13))
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(30)
    if primary:
        b.setStyleSheet(f"QPushButton{{background:{GREEN};color:#04140a;border:none;border-radius:15px;padding:4px 14px;"
                        "font-weight:800;}QPushButton:hover{background:#4ade80;}"
                        "QPushButton:disabled{background:#1f2937;color:#64748b;}")
    else:
        color = "#fda4af" if danger else "#e2e8f0"
        b.setStyleSheet(f"QPushButton{{background:rgba(255,255,255,0.07);color:{color};border:1px solid "
                        "rgba(255,255,255,0.14);border-radius:15px;padding:4px 14px;font-weight:600;}"
                        "QPushButton:hover{background:rgba(255,255,255,0.14);}"
                        "QPushButton:disabled{color:#475569;}")
    return b


class ServiceCard(QFrame):
    clicked = Signal(str)

    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.svc = svc
        self.setObjectName(f"svc_{svc.id}")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(12, 9, 12, 9)
        lo.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(get_pixmap(svc.icon, SOFT, 18))
        icon.setStyleSheet("background:transparent;border:none;")
        lo.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = _lbl(svc.title, TEXT, 12, 700)
        self.sub = _lbl("", MUTED, 10, 500)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        lo.addLayout(col, 1)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        lo.addWidget(self.dot)
        self.selected = False

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.svc.id)

    def sync(self, enabled):
        word, color = STATUS.get(self.svc.status, ("?", DIM))
        extra = f" · up {fmt_uptime(self.svc.uptime)}" if self.svc.status == RUNNING else \
            (" · auto-start on" if enabled and self.svc.status != FAILED else "")
        self.sub.setText(word + extra)
        self.dot.setStyleSheet(f"background:{color};border-radius:5px;")
        n = self.objectName()
        border = "rgba(34,197,94,0.55)" if self.selected else "rgba(255,255,255,0.10)"
        bg = "rgba(34,197,94,0.12)" if self.selected else "rgba(255,255,255,0.04)"
        self.setStyleSheet(f"QFrame#{n}{{background:{bg};border:1px solid {border};border-radius:12px;}}"
                           f"QFrame#{n}:hover{{border:1px solid rgba(34,197,94,0.45);}}")


class ServicesView(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.cards = {}
        self.current = None
        self._fields = {}
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    # ------------------------------------------------------------------ UI --

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)
        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        t = QLabel("SERVICES // BACKGROUND SERVICES")
        t.setObjectName("section-header")
        tb.addWidget(t)
        tb.addSpacing(12)
        self.summary = _lbl("", MUTED, 11, 600)
        tb.addWidget(self.summary)
        tb.addStretch()
        main.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QFrame()
        left.setObjectName("panel")
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(6)
        for svc in self.manager.all():
            card = ServiceCard(svc)
            card.clicked.connect(self.select)
            self.cards[svc.id] = card
            ll.addWidget(card)
        ll.addStretch()
        hint = _lbl("The watchdog restarts a service that crashes: after 5 s, 15 s, 60 s, then every 5 min.",
                    DIM, 10, 500)
        hint.setWordWrap(True)
        ll.addWidget(hint)
        body.addWidget(left)

        self.detail = QFrame()
        self.detail.setObjectName("panel")
        self.dl = QVBoxLayout(self.detail)
        self.dl.setContentsMargins(18, 14, 18, 14)
        self.dl.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        scroll.setWidget(self.detail)
        body.addWidget(scroll, 1)
        main.addLayout(body, 1)
        if self.manager.order:
            self.select(self.manager.order[0])

    def select(self, sid):
        self.current = sid
        for k, c in self.cards.items():
            c.selected = k == sid
        self._build_detail()
        self._tick()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _build_detail(self):
        self._clear(self.dl)
        svc = self.manager.get(self.current)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(get_pixmap(svc.icon, GREEN, 26))
        icon.setStyleSheet("background:transparent;")
        head.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(_lbl(svc.title, TEXT, 18, 600))
        desc = _lbl(svc.description, MUTED, 11, 500)
        desc.setWordWrap(True)
        col.addWidget(desc)
        head.addLayout(col, 1)
        self.status_chip = QLabel()
        head.addWidget(self.status_chip, 0, Qt.AlignTop)
        self.dl.addLayout(head)

        row = QHBoxLayout()
        self.start_btn = _btn("Start", "play", primary=True)
        self.stop_btn = _btn("Stop", "square", danger=True)
        self.restart_btn = _btn("Restart", "refresh")
        self.start_btn.clicked.connect(lambda: self._do(self.manager.start, svc.id))
        self.stop_btn.clicked.connect(lambda: self._do(self.manager.stop, svc.id))
        self.restart_btn.clicked.connect(lambda: self._do(self.manager.restart, svc.id))
        for b in (self.start_btn, self.stop_btn, self.restart_btn):
            row.addWidget(b)
        row.addStretch()
        self.dl.addLayout(row)
        self.auto = QCheckBox("Start automatically with CYPHER-X (and keep it running — watchdog)")
        self.auto.setChecked(self.manager.enabled(svc.id))
        self.auto.toggled.connect(lambda on: self.manager.set_enabled(svc.id, on))
        self.dl.addWidget(self.auto)

        self.error_lbl = _lbl("", RED, 11, 600)
        self.error_lbl.setWordWrap(True)
        self.dl.addWidget(self.error_lbl)
        self.meta = _lbl("", SOFT, 11, 500)
        self.dl.addWidget(self.meta)
        self.info_lbl = _lbl("", SOFT, 12, 500)
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.dl.addWidget(self.info_lbl)

        acts = svc.actions()
        if acts:
            arow = QHBoxLayout()
            for label, fn in acts:
                b = _btn(label)
                b.clicked.connect(lambda _=False, f=fn, l=label: self._action(l, f))
                arow.addWidget(b)
            arow.addStretch()
            self.dl.addLayout(arow)

        self._fields = {}
        if svc.settings_schema:
            self.dl.addWidget(_lbl("SETTINGS", "#4ade80", 10, 800))
            form = QFormLayout()
            form.setHorizontalSpacing(14)
            for key, label, kind, default, help_ in svc.settings_schema:
                value = svc.setting(key)
                if kind == "int":
                    w = QSpinBox()
                    w.setRange(1, 65535)
                    w.setValue(int(value or default or 0))
                elif kind == "bool":
                    w = QCheckBox()
                    w.setChecked(bool(value))
                else:
                    w = QLineEdit("" if value is None else str(value))
                    if kind == "secret":
                        w.setEchoMode(QLineEdit.Password)
                if help_:
                    w.setToolTip(help_)
                self._fields[key] = (kind, w)
                form.addRow(label, w)
            self.dl.addLayout(form)
            srow = QHBoxLayout()
            save = _btn("Save settings", "save")
            save.clicked.connect(self._save_settings)
            srow.addWidget(save)
            srow.addWidget(_lbl("Restart the service to apply.", DIM, 10, 500))
            srow.addStretch()
            self.dl.addLayout(srow)

        self.dl.addWidget(_lbl("LOG", "#4ade80", 10, 800))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(180)
        self.log_view.setStyleSheet("QPlainTextEdit{background:#03070a;color:#86efac;border:1px solid "
                                    "rgba(255,255,255,0.08);border-radius:10px;padding:6px;"
                                    "font-family:'Cascadia Mono','Consolas',monospace;font-size:11px;}")
        self.dl.addWidget(self.log_view, 1)
        self._log_count = None

    # -------------------------------------------------------------- actions --

    def _do(self, fn, sid):
        try:
            fn(sid)
        except Exception as e:
            QMessageBox.warning(self, "Services", str(e))
        self._tick()

    def _action(self, label, fn):
        try:
            msg = fn()
        except Exception as e:
            QMessageBox.warning(self, label, str(e))
            return
        if msg:
            QMessageBox.information(self, label, msg)
        self._build_detail()
        self._tick()

    def _save_settings(self):
        svc = self.manager.get(self.current)
        for key, (kind, w) in self._fields.items():
            if kind == "int":
                svc.set_setting(key, w.value())
            elif kind == "bool":
                svc.set_setting(key, w.isChecked())
            else:
                svc.set_setting(key, w.text().strip())
        svc.on_settings_changed()
        svc.log("Settings saved")
        self._tick()

    # -------------------------------------------------------------- refresh --

    def showEvent(self, e):
        super().showEvent(e)
        self._tick()

    def _tick(self):
        if not self.isVisible():
            return
        s = self.manager.summary()
        self.summary.setText(f"{s['running']} of {s['total']} running"
                             + (f"  ·  {s['failed']} failed" if s["failed"] else ""))
        for sid, card in self.cards.items():
            card.sync(self.manager.enabled(sid))
        svc = self.manager.get(self.current) if self.current else None
        if svc is None:
            return
        word, color = STATUS.get(svc.status, ("?", DIM))
        c = color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        self.status_chip.setText(word)
        self.status_chip.setStyleSheet(f"QLabel{{color:{TEXT};background:rgba({r},{g},{b},0.18);border:1px solid "
                                       f"rgba({r},{g},{b},0.5);border-radius:11px;padding:3px 12px;"
                                       "font-size:11px;font-weight:800;}")
        running = svc.status in (RUNNING, STARTING)
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(svc.status != STOPPED)
        self.restart_btn.setEnabled(svc.status != STOPPED)
        self.auto.blockSignals(True)
        self.auto.setChecked(self.manager.enabled(svc.id))
        self.auto.blockSignals(False)
        self.error_lbl.setText(f"Last error: {svc.last_error}" if svc.last_error else "")
        self.error_lbl.setVisible(bool(svc.last_error))
        meta = []
        if svc.status == RUNNING:
            meta.append(f"Up {fmt_uptime(svc.uptime)}")
        meta.append(f"{svc.restarts} restart{'s' if svc.restarts != 1 else ''}")
        self.meta.setText("  ·  ".join(meta))
        self.info_lbl.setText("\n".join(svc.info()))
        self.info_lbl.setVisible(bool(self.info_lbl.text()))
        last = svc.logs[-1][0] if svc.logs else 0
        if (len(svc.logs), last) != self._log_count:
            self._log_count = (len(svc.logs), last)
            lines = [f"{datetime.fromtimestamp(ts):%H:%M:%S}  {lvl.upper():5} {msg}"
                     for ts, lvl, msg in list(svc.logs)[-200:]]
            self.log_view.setPlainText("\n".join(lines))
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())


