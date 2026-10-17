import os
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMessageBox, QSystemTrayIcon, QMenu, QApplication
)
from app.icons import get_icon
from app.config import (
    APP_NAME, APP_SUBTITLE, APP_VERSION, DEFAULT_METRICS_INTERVAL_MS
)
from app.widgets.status_bar import TopStatusBar
from app.widgets.right_panel import RightInfoPanel
from app.navigation import NavigationSidebar, MODULE_DEFINITIONS
from app.ui_polish import GlassBackdrop, polish_tables
from app.views.settings import get_pref
from app.services.system_service import SystemService
from app.services.network_service import NetworkService

from app.views.widget_screen import WidgetScreenView
from app.views.dashboard import DashboardView
from app.views.smart_home import SmartHomeView
from app.views.cctv import CctvView
from app.views.my_computer import MyComputerView
from app.views.disk_analyzer import DiskAnalyzerView
from app.views.disk_cleaner import DiskCleanerView
from app.views.folder_organizer import FolderOrganizerView
from app.views.file_explorer import FileExplorerView
from app.views.duplicate_finder import DuplicateFinderView
from app.views.large_file_finder import LargeFileFinderView
from app.views.process_manager import ProcessManagerView
from app.views.startup_manager import StartupManagerView
from app.views.system_monitor import SystemMonitorView
from app.views.network_monitor import NetworkMonitorView
from app.views.clock_calendar import ClockCalendarView
from app.views.notes_tasks import NotesTasksView
from app.views.app_launcher import ApplicationLauncherView
from app.views.automation_center import AutomationCenterView
from app.views.operation_history import OperationHistoryView
from app.views.settings import SettingsView

class MainWindow(QMainWindow):
    """Master CyberOps Command Center Window coordinating all views, navigation, and telemetry."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} // {APP_SUBTITLE} [v{APP_VERSION}]")
        self.resize(1360, 860)
        self.setMinimumSize(1024, 640)

        self.net_service = NetworkService()
        self._immersive = False
        self._was_maximized = False
        self._right_was_visible = False
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_tray()
        self._setup_telemetry_loop()

    def _setup_ui(self):
        central_widget = GlassBackdrop(self)
        self.backdrop = central_widget
        self.setCentralWidget(central_widget)

        master_layout = QVBoxLayout(central_widget)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.setSpacing(0)

        # 1. Top Status Bar
        self.status_bar = TopStatusBar(self)
        master_layout.addWidget(self.status_bar)

        # 2. Main Center Body (Left Nav, Center Stack, Right Rail)
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Left Navigation Sidebar
        self.sidebar = NavigationSidebar(self)
        self.sidebar.module_selected.connect(self._on_navigation_change)
        body_layout.addWidget(self.sidebar)

        # Right Telemetry Rail
        self.right_panel = RightInfoPanel(self)

        # Center Stacked Widget
        self.stack = QStackedWidget(self)
        self._init_views()
        body_layout.addWidget(self.stack, stretch=1)
        body_layout.addWidget(self.right_panel)

        master_layout.addLayout(body_layout)

        # Every page sits on a blurred copy of the Home wallpaper
        self.view_widget_screen.wallpapers.image_ready.connect(self.backdrop.set_image)
        self.backdrop.set_dim(get_pref("pref_backdrop_dim"))
        polish_tables(self)
        if get_pref("pref_sidebar_collapsed"):
            self.sidebar.toggle_collapse()
        if get_pref("pref_home_fullscreen"):
            QTimer.singleShot(0, lambda: self.set_immersive(True))

    def _init_views(self):
        self.view_widget_screen = WidgetScreenView(self)
        self.view_widget_screen.navigate_to_module.connect(self.navigate_by_id)

        self.view_smart_home = SmartHomeView(self)
        self.view_cctv = CctvView(self)
        self.view_dashboard = DashboardView(self)
        self.view_dashboard.navigate_to_module.connect(self.navigate_by_id)

        self.view_my_computer = MyComputerView(self)
        self.view_disk_analyzer = DiskAnalyzerView(self)
        self.view_disk_cleaner = DiskCleanerView(self)
        self.view_folder_organizer = FolderOrganizerView(self)
        self.view_file_explorer = FileExplorerView(self)
        self.view_duplicate_finder = DuplicateFinderView(self)
        self.view_large_file_finder = LargeFileFinderView(self)
        self.view_process_manager = ProcessManagerView(self)
        self.view_startup_manager = StartupManagerView(self)
        self.view_system_monitor = SystemMonitorView(self)
        self.view_network_monitor = NetworkMonitorView(self)
        self.view_clock_calendar = ClockCalendarView(self)
        self.view_notes_tasks = NotesTasksView(self)
        self.view_app_launcher = ApplicationLauncherView(self)
        self.view_automation_center = AutomationCenterView(self)
        self.view_operation_history = OperationHistoryView(self)
        self.view_settings = SettingsView(self)

        # Map to stack in order of MODULE_DEFINITIONS
        self.view_map = {
            "widget_screen": self.view_widget_screen,
            "smart_home": self.view_smart_home,
            "cctv": self.view_cctv,
            "dashboard": self.view_dashboard,
            "my_computer": self.view_my_computer,
            "disk_analyzer": self.view_disk_analyzer,
            "disk_cleaner": self.view_disk_cleaner,
            "folder_organizer": self.view_folder_organizer,
            "file_explorer": self.view_file_explorer,
            "duplicate_finder": self.view_duplicate_finder,
            "large_file_finder": self.view_large_file_finder,
            "process_manager": self.view_process_manager,
            "startup_manager": self.view_startup_manager,
            "system_monitor": self.view_system_monitor,
            "network_monitor": self.view_network_monitor,
            "clock_calendar": self.view_clock_calendar,
            "notes_tasks": self.view_notes_tasks,
            "app_launcher": self.view_app_launcher,
            "automation_center": self.view_automation_center,
            "operation_history": self.view_operation_history,
            "settings": self.view_settings,
        }

        for item in MODULE_DEFINITIONS:
            mod_id = item[0]
            view = self.view_map.get(mod_id)
            if view:
                self.stack.addWidget(view)

        # By default start on Widget Screen and hide right panel for edge-to-edge view
        self.stack.setCurrentIndex(0)
        self.right_panel.setVisible(False)

    def _setup_tray(self):
        self._really_quit = False
        self._tray_hint_shown = False
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = get_icon("widgets", "#38bdf8", 64)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("Show CYPHER-X", self._show_from_tray)
        menu.addAction("Play / Pause Music", self.view_widget_screen.music.toggle_play)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_from_tray() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal() if not self._immersive else self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def notify(self, title: str, message: str):
        """Windows notification via the tray icon (falls back to the terminal log)."""
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 8000)

    def quit_app(self):
        self._really_quit = True
        self.close()

    def _setup_shortcuts(self):
        # Fullscreen toggle shortcut (F11)
        shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        shortcut_f11.activated.connect(self._toggle_fullscreen)

        # Esc exit fullscreen
        shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        shortcut_esc.activated.connect(self._exit_fullscreen)

    def _toggle_fullscreen(self):
        # The Home widget screen goes fully immersive; other modules just go full screen
        if self.stack.currentWidget() is self.view_widget_screen or self._immersive:
            self.toggle_immersive()
        elif self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()

    def _exit_fullscreen(self):
        if self._immersive:
            self.set_immersive(False)
        elif self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()

    def toggle_immersive(self):
        self.set_immersive(not self._immersive)

    def set_immersive(self, on: bool):
        """Full screen with all chrome hidden so the Home canvas fills the display."""
        if on == self._immersive:
            return
        self._immersive = on
        if on:
            self._was_maximized = self.isMaximized()
            self._right_was_visible = self.right_panel.isVisible()
            self.status_bar.setVisible(False)
            self.sidebar.setVisible(False)
            self.right_panel.setVisible(False)
            self.stack.setCurrentWidget(self.view_widget_screen)
            self.showFullScreen()
        else:
            self.status_bar.setVisible(True)
            self.sidebar.setVisible(True)
            self.right_panel.setVisible(self._right_was_visible
                                        and self.stack.currentWidget() is not self.view_widget_screen)
            self.showMaximized() if self._was_maximized else self.showNormal()
        self.view_widget_screen.on_immersive_changed(on)

    def _on_navigation_change(self, index: int, module_id: str):
        if index < self.stack.count():
            self.stack.setCurrentIndex(index)
            # Full edge-to-edge canvas for Widget Screen
            if module_id == "widget_screen":
                self.right_panel.setVisible(False)
            else:
                self.right_panel.setVisible(bool(get_pref("pref_right_panel")))

    def navigate_by_id(self, module_id: str):
        for idx, item in enumerate(MODULE_DEFINITIONS):
            if item[0] == module_id:
                self.sidebar._on_module_clicked(idx, module_id)
                break

    def _setup_telemetry_loop(self):
        # Immediate sample
        self._sample_telemetry()

        # Recurring timer
        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self._sample_telemetry)
        self.metrics_timer.start(int(get_pref("pref_rate") or DEFAULT_METRICS_INTERVAL_MS))

    def _sample_telemetry(self):
        try:
            cpu = SystemService.get_cpu_metrics()
            mem = SystemService.get_memory_metrics()
            disks = SystemService.get_disks_summary()
            rates = self.net_service.sample_bandwidth()
            uptime = SystemService.get_uptime_seconds()

            # Update Right Panel
            self.right_panel.update_telemetry(cpu, mem, disks, rates, uptime)

            # Update Dashboard
            self.view_dashboard.update_metrics(cpu, mem, disks, rates)

            # Update System Monitor
            self.view_system_monitor.update_telemetry(cpu, mem, disks, rates, uptime)

            # Update Network Monitor
            self.view_network_monitor.update_telemetry(rates)

        except Exception as e:
            pass

    def closeEvent(self, event):
        """Ensure all background threads and timers are cleanly stopped on window close."""
        if self.tray is not None and not self._really_quit and get_pref("pref_close_to_tray"):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.notify(APP_NAME, "Still running in the tray. Right-click the icon to quit.")
            return
        if self.tray is not None:
            self.tray.hide()
        if hasattr(self, "metrics_timer"):
            self.metrics_timer.stop()

        self.view_widget_screen.shutdown()

        # Stop active workers if running
        if hasattr(self.view_disk_analyzer, "worker") and self.view_disk_analyzer.worker:
            self.view_disk_analyzer.worker.cancel()

        if hasattr(self.view_disk_cleaner, "analyze_worker") and self.view_disk_cleaner.analyze_worker:
            self.view_disk_cleaner.analyze_worker.cancel()

        if hasattr(self.view_disk_cleaner, "exec_worker") and self.view_disk_cleaner.exec_worker:
            self.view_disk_cleaner.exec_worker.cancel()

        if hasattr(self.view_duplicate_finder, "worker") and self.view_duplicate_finder.worker:
            self.view_duplicate_finder.worker.cancel()

        event.accept()
        # Dialogs or the tray must not keep a closed app alive
        QApplication.instance().quit()
