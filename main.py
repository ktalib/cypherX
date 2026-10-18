import sys
import os
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QApplication
from app.config import APP_NAME, ORG_NAME, APP_VERSION
from app.theme import get_cyber_stylesheet
from app.main_window import MainWindow
from app.ui_polish import apply_dark_palette, EXTRA_QSS
from app.database import Database
from app.services.auth_service import AuthService
from app.widgets.login_dialog import LoginDialog

def main():
    # High-DPI support
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_dark_palette(app)
    app.setStyleSheet(get_cyber_stylesheet() + EXTRA_QSS)

    # The window may hide to the system tray; quitting is handled explicitly
    app.setQuitOnLastWindowClosed(False)

    # Sign in first (first run: admin / admin, root access)
    auth = AuthService(Database.get_instance())
    login = LoginDialog(auth)
    if login.exec() != LoginDialog.Accepted:
        sys.exit(0)
    window = MainWindow(user=login.user, auth=auth)
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
