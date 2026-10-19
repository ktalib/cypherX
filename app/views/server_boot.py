"""
Server boot screen — shown when root opens the Server console from the home
network. Runs the real start-up checks one by one (in a worker thread so the
animation never stutters), then hands over to the Server console.
"""
import time
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QPlainTextEdit, QProgressBar, QApplication
)

from app.icons import get_pixmap
from app.services import server_checks as sc

GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#f43f5e"
BLUE = "#38bdf8"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
DIM = "#64748b"

MIN_STEP_S = 0.45            # each step stays on screen at least this long
AUTO_ENTER_MS = 900          # pause on "Server online" before switching

STATUS_COLOR = {sc.OK: GREEN, sc.WARN: AMBER, sc.FAIL: RED, sc.INFO: BLUE}
STATUS_WORD = {sc.OK: "OK", sc.WARN: "WARN", sc.FAIL: "FAIL", sc.INFO: "INFO"}


class StepIcon(QWidget):
    """pending: dim ring · running: spinning arc · ok/warn/fail/info: filled badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.state = "pending"
        self.angle = 0

    def set_state(self, state):
        self.state = state
        self.update()

    def spin(self):
        if self.state == "running":
            self.angle = (self.angle + 24) % 360
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, 16, 16)
        if self.state == "pending":
            p.setPen(QPen(QColor(255, 255, 255, 50), 2))
            p.drawEllipse(r)
        elif self.state == "running":
            p.setPen(QPen(QColor(255, 255, 255, 30), 2))
            p.drawEllipse(r)
            p.setPen(QPen(QColor(BLUE), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, -self.angle * 16, 100 * 16)
        else:
            c = QColor(STATUS_COLOR.get(self.state, BLUE))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(r)
            p.setPen(QPen(QColor("#0b1220"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if self.state == sc.OK:
                p.drawPolyline([QPointF(7, 11.5), QPointF(10, 14.5), QPointF(15.5, 8)])
            elif self.state == sc.FAIL:
                p.drawLine(QPointF(8, 8), QPointF(14, 14))
                p.drawLine(QPointF(14, 8), QPointF(8, 14))
            else:                                   # warn "!" / info "i"
                top, bottom = (7, 12) if self.state == sc.WARN else (10, 15)
                dot = 15 if self.state == sc.WARN else 7
                p.drawLine(QPointF(11, top), QPointF(11, bottom))
                p.drawPoint(QPointF(11, dot))
        p.end()


class BootWorker(QThread):
    step_started = Signal(int)
    step_done = Signal(int, str, str)

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps            # [(label, callable)]
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for i, (_label, fn) in enumerate(self.steps):
            if self._stop:
                return
            self.step_started.emit(i)
            t0 = time.monotonic()
            try:
                status, detail = fn()
            except Exception as e:          # a broken check must never hang the boot
                status, detail = sc.FAIL, f"Check crashed: {e}"
            rest = MIN_STEP_S - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)
            if self._stop:
                return
            self.step_done.emit(i, status, detail)


class ServerBootView(QWidget):
    """Emits finished(results) when the server may open, cancelled() to go home."""

    finished = Signal(list)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.results = []
        self.rows = []
        self._build()
        self._spin = QTimer(self)
        self._spin.timeout.connect(self._tick)
        self._enter_timer = QTimer(self)
        self._enter_timer.setSingleShot(True)
        self._enter_timer.timeout.connect(self._enter)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)      # never leave the check thread running on exit

    # ------------------------------------------------------------------ UI --

    def _build(self):
        self.setObjectName("server_boot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#server_boot{background:qradialgradient(cx:0.5,cy:0.35,radius:0.9,"
                           "stop:0 rgba(14,40,32,0.96),stop:0.6 rgba(7,14,18,0.98),stop:1 #04080b);}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("boot_card")
        card.setMaximumWidth(760)
        card.setMinimumWidth(560)
        card.setStyleSheet("QFrame#boot_card{background:rgba(10,18,22,0.92);border:1px solid "
                           "rgba(34,197,94,0.35);border-radius:20px;}")
        row.addWidget(card, 4)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        lo = QVBoxLayout(card)
        lo.setContentsMargins(30, 26, 30, 24)
        lo.setSpacing(12)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(get_pixmap("hard_drive", GREEN, 30))
        icon.setStyleSheet("background:transparent;")
        head.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel("CYPHER-X SERVER")
        self.title.setStyleSheet(f"color:{TEXT};font-size:20px;font-weight:700;letter-spacing:3px;"
                                 "background:transparent;")
        self.subtitle = QLabel("Starting the server console…")
        self.subtitle.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.pct = QLabel("0%")
        self.pct.setStyleSheet(f"color:{GREEN};font-size:22px;font-weight:300;background:transparent;")
        head.addWidget(self.pct)
        lo.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet("QProgressBar{background:rgba(255,255,255,0.08);border:none;border-radius:3px;}"
                               f"QProgressBar::chunk{{background:{GREEN};border-radius:3px;}}")
        lo.addWidget(self.bar)

        self.steps_box = QVBoxLayout()
        self.steps_box.setSpacing(4)
        lo.addLayout(self.steps_box)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        self.log.setStyleSheet("QPlainTextEdit{background:#03070a;color:#86efac;border:1px solid "
                               "rgba(255,255,255,0.08);border-radius:10px;padding:6px;"
                               "font-family:'Cascadia Mono','Consolas',monospace;font-size:11px;}")
        lo.addWidget(self.log)

        btns = QHBoxLayout()
        self.cancel_btn = QPushButton("  Back to Home")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("QPushButton{background:rgba(255,255,255,0.07);color:#e2e8f0;border:1px solid "
                                      "rgba(255,255,255,0.14);border-radius:15px;padding:6px 14px;font-weight:600;}"
                                      "QPushButton:hover{background:rgba(255,255,255,0.14);}")
        self.cancel_btn.clicked.connect(self.cancel)
        self.enter_btn = QPushButton("Enter server  →")
        self.enter_btn.setCursor(Qt.PointingHandCursor)
        self.enter_btn.setStyleSheet(f"QPushButton{{background:{GREEN};color:#04140a;border:none;border-radius:15px;"
                                     "padding:6px 16px;font-weight:800;}QPushButton:hover{background:#4ade80;}"
                                     "QPushButton:disabled{background:#1f2937;color:#64748b;}")
        self.enter_btn.clicked.connect(self._enter)
        btns.addWidget(self.cancel_btn)
        btns.addStretch()
        btns.addWidget(self.enter_btn)
        lo.addLayout(btns)

    def _make_row(self, label):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(10)
        icon = StepIcon()
        name = QLabel(label)
        name.setStyleSheet(f"color:{DIM};font-size:13px;font-weight:600;background:transparent;")
        name.setMinimumWidth(190)
        detail = QLabel("")
        detail.setStyleSheet(f"color:{MUTED};font-size:11px;background:transparent;")
        detail.setWordWrap(True)
        h.addWidget(icon)
        h.addWidget(name)
        h.addWidget(detail, 1)
        self.steps_box.addWidget(w)
        return {"widget": w, "icon": icon, "name": name, "detail": detail}

    # ---------------------------------------------------------------- run --

    def start(self, steps):
        """steps: [(label, callable -> (status, detail))]"""
        self.stop()
        for r in self.rows:
            r["widget"].hide()
            r["widget"].deleteLater()
        self.rows = [self._make_row(label) for label, _fn in steps]
        self.results = []
        self.log.clear()
        self.bar.setRange(0, len(steps))
        self.bar.setValue(0)
        self.pct.setText("0%")
        self.subtitle.setText("Starting the server console…")
        self.pct.setStyleSheet(f"color:{GREEN};font-size:22px;font-weight:300;background:transparent;")
        self.enter_btn.setEnabled(False)
        self.enter_btn.setText("Enter server  →")
        self._log("boot sequence started")
        self.worker = BootWorker(steps, self)
        self.worker.step_started.connect(self._started)
        self.worker.step_done.connect(self._done)
        self.worker.finished.connect(self._all_done)
        self._spin.start(40)
        self.worker.start()

    def stop(self):
        self._enter_timer.stop()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        self._spin.stop()

    def cancel(self):
        self.stop()
        self.cancelled.emit()

    def _started(self, i):
        row = self.rows[i]
        row["icon"].set_state("running")
        row["name"].setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;background:transparent;")
        row["detail"].setText("…")
        self._log(f"{row['name'].text().lower()}…")

    def _done(self, i, status, detail):
        row = self.rows[i]
        row["icon"].set_state(status)
        row["detail"].setText(detail)
        row["detail"].setStyleSheet(f"color:{STATUS_COLOR[status] if status != sc.OK else MUTED};"
                                    "font-size:11px;background:transparent;")
        self.results.append((row["name"].text(), status, detail))
        self.bar.setValue(i + 1)
        self.pct.setText(f"{int((i + 1) / len(self.rows) * 100)}%")
        self._log(f"[{STATUS_WORD[status]:>4}] {detail}")

    def _all_done(self):
        self._spin.stop()
        if len(self.results) < len(self.rows):
            return                                  # cancelled part-way
        fails = [r for r in self.results if r[1] == sc.FAIL]
        warns = [r for r in self.results if r[1] == sc.WARN]
        if fails:
            self.subtitle.setText(f"{len(fails)} check{'s' if len(fails) != 1 else ''} failed — "
                                  "you can still enter, some tools may not work")
            self.pct.setStyleSheet(f"color:{RED};font-size:22px;font-weight:300;background:transparent;")
            self._log("boot finished with errors")
            self.enter_btn.setEnabled(not any(r[0] == "Verifying root access" for r in fails))
            return                                  # wait for the user
        self.subtitle.setText("Server online" + (f" · {len(warns)} warning{'s' if len(warns) != 1 else ''}"
                                                 if warns else ""))
        self._log("server online")
        self.enter_btn.setEnabled(True)
        self.enter_btn.setText("Entering…")
        self._enter_timer.start(AUTO_ENTER_MS)

    def _enter(self):
        self._enter_timer.stop()
        if not self.enter_btn.isEnabled():
            return
        self.stop()
        self.finished.emit(self.results)

    def _tick(self):
        for r in self.rows:
            r["icon"].spin()

    def _log(self, text):
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    @property
    def running(self):
        return self.worker is not None and self.worker.isRunning() or self._enter_timer.isActive()
