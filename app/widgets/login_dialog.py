"""
Sign-in screen shown before the main window, and again when the server is locked.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame
)

from app.icons import get_pixmap, get_icon
from app.services.auth_service import DEFAULT_USERNAME, DEFAULT_PASSWORD

MAX_TRIES = 5
LOCKOUT_S = 30

_FIELD = ("QLineEdit{background:rgba(255,255,255,0.06);color:#f8fafc;border:1px solid "
          "rgba(255,255,255,0.14);border-radius:10px;padding:9px 12px;font-size:13px;}"
          "QLineEdit:focus{border:1px solid #38bdf8;background:rgba(56,189,248,0.08);}")


class LoginDialog(QDialog):
    def __init__(self, auth, locked_user=None, parent=None):
        super().__init__(parent)
        self.auth = auth
        self.user = None
        self._fails = 0
        self._wait = 0
        self.setWindowTitle("CYPHER-X — Sign in")
        self.setModal(True)
        self.setFixedSize(420, 450)
        self.setObjectName("login")
        self.setStyleSheet("QDialog#login{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                           "stop:0 #0b1622, stop:0.6 #101827, stop:1 #0c1f1c);}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 24)
        card = QFrame()
        card.setObjectName("login_card")
        card.setStyleSheet("QFrame#login_card{background:rgba(18,26,34,0.85);border:1px solid "
                           "rgba(255,255,255,0.12);border-radius:20px;}")
        outer.addWidget(card)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(28, 26, 28, 24)
        lo.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(get_pixmap("shield" if locked_user else "widgets", "#38bdf8", 36))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background:transparent;")
        lo.addWidget(logo)
        title = QLabel("Server locked" if locked_user else "CYPHER-X Server")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color:#f8fafc;font-size:20px;font-weight:600;background:transparent;")
        lo.addWidget(title)
        sub = QLabel("Sign in to continue" if locked_user else "Smart home control · sign in")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color:#94a3b8;font-size:12px;background:transparent;")
        lo.addWidget(sub)
        lo.addSpacing(10)

        self.username = QLineEdit(locked_user or "")
        self.username.setPlaceholderText("User name")
        self.username.setStyleSheet(_FIELD)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setStyleSheet(_FIELD)
        show = self.password.addAction(get_icon("eye", "#94a3b8", 16), QLineEdit.TrailingPosition)
        show.setToolTip("Show password")
        show.triggered.connect(lambda: self.password.setEchoMode(
            QLineEdit.Normal if self.password.echoMode() == QLineEdit.Password else QLineEdit.Password))
        lo.addWidget(self.username)
        lo.addWidget(self.password)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#fb7185;font-size:12px;font-weight:600;background:transparent;")
        self.error.hide()
        lo.addWidget(self.error)

        self.sign_in = QPushButton("Sign in")
        self.sign_in.setCursor(Qt.PointingHandCursor)
        self.sign_in.setMinimumHeight(40)
        self.sign_in.setDefault(True)
        self.sign_in.setStyleSheet("QPushButton{background:#38bdf8;color:#04131d;border:none;border-radius:10px;"
                                   "font-size:13px;font-weight:700;}QPushButton:hover{background:#7dd3fc;}"
                                   "QPushButton:disabled{background:#334155;color:#94a3b8;}")
        self.sign_in.clicked.connect(self._try)
        lo.addWidget(self.sign_in)
        lo.addStretch()

        if auth.uses_default_password():
            hint = QLabel(f"First sign-in: <b>{DEFAULT_USERNAME}</b> / <b>{DEFAULT_PASSWORD}</b>. "
                          "Change it in Settings → Accounts.")
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color:#fbbf24;font-size:11px;background:transparent;")
            lo.addWidget(hint)

        (self.password if locked_user else self.username).setFocus()
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._try)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._countdown)

    def _try(self):
        if self._wait:
            return
        user = self.auth.authenticate(self.username.text(), self.password.text())
        if user:
            self.user = user
            self.accept()
            return
        self._fails += 1
        self.password.clear()
        self.password.setFocus()
        if self._fails >= MAX_TRIES:
            self._fails = 0
            self._wait = LOCKOUT_S
            self.sign_in.setEnabled(False)
            self._timer.start(1000)
            self._countdown(initial=True)
        else:
            self._show_error(f"Wrong user name or password ({MAX_TRIES - self._fails} tries left).")

    def _countdown(self, initial=False):
        if not initial:
            self._wait -= 1
        if self._wait <= 0:
            self._timer.stop()
            self._wait = 0
            self.sign_in.setEnabled(True)
            self.error.hide()
            return
        self._show_error(f"Too many wrong tries. Try again in {self._wait} s.")

    def _show_error(self, text):
        self.error.setText(text)
        self.error.show()
