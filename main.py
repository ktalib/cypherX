import sys
import os
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QApplication
from app.config import APP_NAME, ORG_NAME, APP_VERSION
from app.theme import get_cyber_stylesheet
from app.main_window import MainWindow
from app.ui_polish import apply_dark_palette, EXTRA_QSS

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
    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
