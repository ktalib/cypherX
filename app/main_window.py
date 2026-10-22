import os
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMessageBox, QSystemTrayIcon, QMenu, QApplication, QFrame, QLabel, QPushButton
)
from app.icons import get_icon
from app.database import Database
from app.config import (
    APP_NAME, APP_SUBTITLE, APP_VERSION, DEFAULT_METRICS_INTERVAL_MS, DB_PATH
)
from app.widgets.status_bar import TopStatusBar
from app.widgets.right_panel import RightInfoPanel
from app.navigation import (
    NavigationSidebar, MODULE_DEFINITIONS, MODULES, module_allowed, module_mode, HOME_MODE, SERVER_MODE
)
from app.views.server_boot import ServerBootView
from app.views.services_view import ServicesView
from app.server.services import ServiceManager, ManagedService
from app.server.events import bus
from app.server.bridge import GuiBridge
from app.server.home_api import HomeApi
from app.server.web import WebService
from app.server.telegram import TelegramService
from app.server.netwatch import NetWatchService
from app.server.discovery import DiscoveryService
from app.server.plugs import PlugService
from app.views.smart_devices import SmartDevicesView
from app.server.backup import BackupService, backup_check
from app.views.lan_devices import LanDevicesView
from app.services import server_checks
from app.ui_polish import GlassBackdrop, polish_tables
from app.views.settings import get_pref
from app.services.system_service import SystemService
from app.services.network_service import NetworkService

from app.views.widget_screen import WidgetScreenView
from app.views.dashboard import DashboardView
from app.views.smart_home import SmartHomeView
from app.views.cctv import CctvView
from app.views.fridge import FridgeView
from app.services.fridge_service import FridgeStore, summary_text
from app.services import budget_service
from app.views.smart_dashboard import SmartDashboardView
from app.views.bills import BillsView
from app.views.groceries import GroceriesView
from app.widgets.login_dialog import LoginDialog
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

    def __init__(self, user=None, auth=None):
        super().__init__()
        self.user = user or {"username": "admin", "role": "root"}
        self.auth = auth
        self._locked = False
        self._pending_server_page = "dashboard"
        self._last_home_page = "smart_dashboard"
        self.setWindowTitle(f"{APP_NAME} // {APP_SUBTITLE} [v{APP_VERSION}]")
        self.resize(1360, 860)
        self.setMinimumSize(1024, 640)

        self.net_service = NetworkService()
        self._immersive = False
        self._was_maximized = False
        self._right_was_visible = False
        self._setup_ui()
        self._apply_user()
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
        self.sidebar.lock_requested.connect(self.lock)
        self.sidebar.server_requested.connect(self.enter_server)
        self.sidebar.home_requested.connect(self.return_home)
        body_layout.addWidget(self.sidebar)

        # Right Telemetry Rail
        self.right_panel = RightInfoPanel(self)

        # Center Stacked Widget
        self.stack = QStackedWidget(self)
        self._init_views()
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        center.addWidget(self._build_server_banner())
        center.addWidget(self.stack, stretch=1)
        body_layout.addLayout(center, stretch=1)
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
        self.fridge = FridgeStore()
        budget_service.BOUGHT_HOOKS.append(lambda name, qty: self.fridge.on_bought(name, qty))
        self.view_fridge = FridgeView(self.fridge, self)
        self.view_smart_dashboard = SmartDashboardView(self.view_smart_home, self.view_cctv, self)
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
        self.view_bills = BillsView(self)
        self.view_groceries = GroceriesView(self)
        self.services = ServiceManager(Database.get_instance())
        self._register_services()
        self.view_services = ServicesView(self.services, self)
        self.view_lan_devices = LanDevicesView(self.services, self)
        self.view_smart_devices = SmartDevicesView(self.services, self.view_smart_home, self)

        # Smart Home pages and the Apps next to them share the warm home look (the Server console keeps its own)
        from app.views.home_ui import apply_home_style
        for v in (self.view_smart_home, self.view_smart_devices, self.view_cctv, self.view_fridge,
                  self.view_bills, self.view_groceries):
            apply_home_style(v)
        self.view_smart_home.view.use_warm_theme()

        # Map to stack in order of MODULE_DEFINITIONS
        self.view_map = {
            "widget_screen": self.view_widget_screen,
            "smart_dashboard": self.view_smart_dashboard,
            "smart_home": self.view_smart_home,
            "cctv": self.view_cctv,
            "fridge": self.view_fridge,
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
            "bills": self.view_bills,
            "services": self.view_services,
            "lan_devices": self.view_lan_devices,
            "smart_devices": self.view_smart_devices,
            "groceries": self.view_groceries,
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

        assert self.stack.count() == len(MODULE_DEFINITIONS), "every sidebar entry needs a page"

        # The server boot screen sits after the sidebar pages (it has no sidebar entry)
        self.view_server_boot = ServerBootView(self)
        self.view_server_boot.finished.connect(self._server_ready)
        self.view_server_boot.cancelled.connect(self.return_home)
        self.stack.addWidget(self.view_server_boot)

        # By default start on Widget Screen and hide right panel for edge-to-edge view
        self.navigate_by_id("widget_screen")
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
        menu.addAction("Lock", self.lock)
        menu.addAction("Play / Pause Music", self.view_widget_screen.music.toggle_play)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_from_tray() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_from_tray(self):
        if self._locked:
            return                       # the lock screen is already up
        self.showNormal() if not self._immersive else self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def notify(self, title: str, message: str):
        """Windows notification via the tray icon (falls back to the terminal log)."""
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 8000)

    def quit_app(self):
        self.view_server_boot.stop()
        self.services.stop_all()
        self._really_quit = True
        self.close()

    def _setup_shortcuts(self):
        # Fullscreen toggle shortcut (F11)
        shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        shortcut_f11.activated.connect(self._toggle_fullscreen)

        # Esc exit fullscreen
        shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        shortcut_esc.activated.connect(self._exit_fullscreen)

        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.lock)

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
        if not module_allowed(module_id, self.user.get("role")):
            return
        if self.view_server_boot.running:
            self.view_server_boot.stop()          # left the boot screen for another page
        if module_mode(module_id) == HOME_MODE:
            self._last_home_page = module_id
        if index < self.stack.count():
            self.stack.setCurrentIndex(index)
            # Full edge-to-edge canvas for Widget Screen
            # PC telemetry belongs to the server console; the home pages get the full width
            if module_id == "widget_screen" or module_mode(module_id) == HOME_MODE:
                self.right_panel.setVisible(False)
            else:
                self.right_panel.setVisible(bool(get_pref("pref_right_panel")))

    def navigate_by_id(self, module_id: str):
        if not module_allowed(module_id, self.user.get("role")):
            name = MODULES.get(module_id, (module_id,))[0]
            QMessageBox.information(self, "Root access needed",
                                    f"{name} is a Server tool. Sign in as a root user to open it.")
            return
        mode = module_mode(module_id)
        if mode == SERVER_MODE and self.sidebar.mode != SERVER_MODE:
            self.enter_server(module_id)          # server pages open through the boot screen
            return
        if mode == HOME_MODE and self.sidebar.mode == SERVER_MODE:
            self.server_banner.hide()
            self.sidebar.set_mode(HOME_MODE)
        for idx, item in enumerate(MODULE_DEFINITIONS):
            if item[0] == module_id:
                self.sidebar.expand_group_of(module_id)
                self.sidebar._on_module_clicked(idx, module_id)
                break

    # ------------------------------------------------------------ services --

    def _register_services(self):
        """Everything that runs in the background, under one manager and watchdog."""
        cctv, home = self.view_cctv, self.view_smart_home
        engine = self.view_automation_center.engine

        def cams_start():
            for f in cctv.feeds.values():
                cctv.start_camera(f, log=False)

        def cams_stop():
            for f in list(cctv.feeds.values()):
                if f.running:
                    cctv.stop_camera(f)

        def cams_info():
            live = sum(1 for f in cctv.feeds.values() if f.running)
            armed = "armed" if cctv.store.config.get("armed") else "disarmed"
            return [f"{live} of {len(cctv.feeds)} cameras live · {armed}",
                    f"{len(cctv.store.events)} events stored · files kept "
                    f"{cctv.store.config.get('retention_days', 14)} days"]

        def grid_info():
            e = home.energy
            out = e.open_outage()
            import time as _t
            return ["Grid OFF since " + _t.strftime("%H:%M", _t.localtime(out["start"])) if out else
                    ("Grid on" if e.grid_detect else "Not watching"),
                    f"{len(e.outages)} power cuts logged"]

        self.services.register(ManagedService(
            "telemetry", "Telemetry", "Samples CPU, RAM, disk and network for the monitors and side panel.",
            "activity", lambda: self.metrics_timer.start(), lambda: self.metrics_timer.stop(),
            lambda: hasattr(self, "metrics_timer") and self.metrics_timer.isActive(),
            lambda: [f"Every {self.metrics_timer.interval() / 1000:g} s"] if hasattr(self, "metrics_timer") else [],
            default_enabled=True))
        self.services.register(ManagedService(
            "grid_watch", "Grid watch", "Detects power cuts through the laptop charger (grid-only socket).",
            "zap", lambda: home.grid_detect.setChecked(True), lambda: home.grid_detect.setChecked(False),
            lambda: home.energy.grid_detect, grid_info, default_enabled=bool(home.energy.grid_detect)))
        self.services.register(ManagedService(
            "cameras", "Camera monitoring", "Runs every CCTV camera with motion detection.",
            "video", cams_start, cams_stop, lambda: any(f.running for f in cctv.feeds.values()),
            cams_info, default_enabled=False))
        self.services.register(ManagedService(
            "automations", "Automation scheduler", "Runs the Automation Center rules on schedule.",
            "automation", lambda: engine._timer.start(60_000), lambda: engine._timer.stop(),
            lambda: engine._timer.isActive(),
            lambda: [f"{sum(1 for v in engine.enabled.values() if v)} rules enabled"], default_enabled=True))

        # Remote access: everything goes through the GUI-thread bridge
        if self.auth is None:
            from app.services.auth_service import AuthService
            self.auth = AuthService(Database.get_instance())
        self.bridge = GuiBridge(self)
        self.home_api = HomeApi(self, self.bridge)
        self.services.register(WebService(self.auth, self.home_api))
        self.services.register(TelegramService(self.home_api, bus))
        netwatch = self.services.register(NetWatchService(bus))

        def mark_on_wifi_list(dev):
            # show what a device really is on the Wi-Fi Devices page
            for mac, d in netwatch.book.devices.items():
                if d.get("ip") == dev.get("ip"):
                    d["smart"] = f"{dev['brand']} {dev['kind']}"
        self.discovery = self.services.register(DiscoveryService(
            bus, ip_source=lambda: [d["ip"] for m, d in netwatch.book.devices.items()
                                    if netwatch.book.online(m) and d.get("ip")],
            on_found=mark_on_wifi_list))
        self.view_smart_home.smart_book = self.discovery.book

        # Smart plugs follow the appliances, and report real state + watts back
        # Two plugs can measure the inverter itself: grid side (power cuts, charging) and house side (load)
        from app.home3d.inverter import InverterMeter, ROLES as INVERTER_ROLES
        book = self.discovery.book
        self.inverter = InverterMeter(lambda: {d.get("linked_item") for d in list(book.devices.values())}
                                      & set(INVERTER_ROLES))
        self.view_smart_home.inverter = self.inverter
        self.view_smart_home.model.measured_load = self.inverter.load_w
        self.plugs = self.services.register(PlugService(
            self.discovery.book, lambda item, on, w: self.bridge.post(lambda: self._apply_plug(item, on, w)),
            on_role=lambda role, r, err: self.bridge.post(lambda: self._apply_inverter(role, r, err))))
        self.view_smart_home.model.switch_hook = lambda item, on: self.plugs.request(item, on)
        self.backup_service = self.services.register(
            BackupService(bus, extra_actions=[("Restore from a backup…", self._restore_backup)]))
        from app.server.fridgecam import FridgeCamService
        from app.services import vision_ai
        self.services.register(FridgeCamService(
            self.fridge, lambda: vision_ai.load_settings(Database.get_instance()), bus))
        from app.server.weather import WeatherService
        from app.widgets.home.common import load_setting
        self.weather = self.services.register(WeatherService(lambda: load_setting("weather_loc", None)))

    def _restore_backup(self):
        """Pick a backup, save the current state, restore, restart CYPHER-X."""
        import sys
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QFileDialog
        svc = self.backup_service
        path, _ = QFileDialog.getOpenFileName(self, "Restore from a backup", str(svc.folder()),
                                              "CYPHER-X backups (cypherx-backup-*.zip)")
        if not path:
            return None
        try:
            manifest = svc.bm.read_manifest(path)
        except Exception as e:
            raise RuntimeError(f"That file isn't a CYPHER-X backup ({e})")
        from datetime import datetime
        when = datetime.fromtimestamp(manifest["created"]).strftime("%a %d %b %Y %H:%M")
        if QMessageBox.question(self, "Restore backup",
                                f"Restore the backup from {when}?\n\nEverything changed since then is replaced. "
                                "The current state is saved first as a 'pre-restore' backup, and CYPHER-X "
                                "restarts.") != QMessageBox.Yes:
            return None
        svc.backup_now(tag="pre-restore")
        svc.bm.restore(path)
        Database.get_instance().log_operation("Backups", f"Restored backup from {when}", "Success")
        QProcess.startDetached(sys.executable, sys.argv)
        self.quit_app()
        QApplication.quit()
        return None

    def _apply_plug(self, item_id, on, watts):
        home = self.view_smart_home
        before = home.model.live_w(item_id)
        changed = home.model.apply_reading(item_id, on, watts)
        moved = watts is not None and (before is None or abs(before - watts) >= 3)
        if changed or moved:
            home.refresh()

    def _apply_inverter(self, role, reading, error):
        home = self.view_smart_home
        before = (self.inverter.grid_on(), round((self.inverter.load_w() or 0) / 5))
        self.inverter.update(role, reading, error)
        home._poll_grid()                         # a power cut shows up straight away, not at the next poll
        if (self.inverter.grid_on(), round((self.inverter.load_w() or 0) / 5)) != before:
            home.refresh()

    def _watchdog(self):
        for sid in self.services.watchdog():
            svc = self.services.get(sid)
            bus.publish("service", "Service restarted", f"{svc.title} crashed and was restarted by the watchdog")
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 200 == 1:                 # every ~10 min
            self._check_meter_low()
        if self._ticks % 20 == 2:                  # every ~1 min
            self._check_fridge_low()

    def _check_meter_low(self):
        """Once a day, warn when the prepaid meter has less than 2 days left."""
        from datetime import date
        e = self.view_smart_home.energy
        days = e.days_left()
        db = Database.get_instance()
        if days is None or days >= 2 or db.get_setting("meter_low_alerted", "") == date.today().isoformat():
            return
        db.set_setting("meter_low_alerted", date.today().isoformat())
        msg = f"About {days * 24:.0f} hours of units left ({e.units_left():.1f} kWh). Buy a token soon."
        self.notify("Prepaid meter low", msg)
        bus.publish("meter", "Prepaid meter low", msg)

    def _check_fridge_low(self):
        """Fridge items that just ran low: a notification, Telegram, and onto the shopping list."""
        low = self.fridge.newly_low()
        if not low:
            return
        added = self.add_to_shopping([v["name"] for v in low])
        text = summary_text(low) + (" — added to the shopping list" if added else "")
        self.notify("Fridge running low", text)
        bus.publish("fridge", "Fridge running low", text)

    def add_to_shopping(self, names):
        """Put names on the first shopping list unless they're already waiting there. Returns how many."""
        svc = self.view_groceries.svc
        lists = svc.lists()
        list_id = lists[0]["id"] if lists else svc.add_list("Shopping")
        waiting = {i["name"].lower() for i in svc.items(list_id) if not i["bought"]}
        added = 0
        for name in names:
            if not any(name.lower() in w for w in waiting):
                svc.add_item(list_id, name, 1)
                added += 1
        if added and self.view_groceries.isVisible():
            self.view_groceries.refresh()
        return added

    # -------------------------------------------------------------- server --

    def _build_server_banner(self):
        """Green strip shown above every page while the server console is open."""
        import socket
        bar = QFrame()
        bar.setObjectName("server_banner")
        bar.setStyleSheet("QFrame#server_banner{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                          "stop:0 rgba(34,197,94,0.22),stop:1 rgba(34,197,94,0.04));"
                          "border-bottom:1px solid rgba(34,197,94,0.35);}")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 6, 12, 6)
        dot = QLabel("●")
        dot.setStyleSheet("color:#22c55e;font-size:12px;background:transparent;")
        title = QLabel("SERVER CONSOLE")
        title.setStyleSheet("color:#dcfce7;font-size:11px;font-weight:800;letter-spacing:2px;background:transparent;")
        self.server_info = QLabel()
        self.server_info.setStyleSheet("color:#86efac;font-size:11px;background:transparent;")
        self._server_host = socket.gethostname()
        home = QPushButton("  Return to Home")
        home.setIcon(get_icon("home", "#1c0d02", 13))
        home.setCursor(Qt.PointingHandCursor)
        home.setStyleSheet("QPushButton{background:#ff7a1a;color:#1c0d02;border:none;border-radius:12px;"
                           "padding:4px 12px;font-size:11px;font-weight:800;}QPushButton:hover{background:#ffa25c;}")
        home.clicked.connect(lambda: self.return_home())
        lo.addWidget(dot)
        lo.addWidget(title)
        lo.addSpacing(10)
        lo.addWidget(self.server_info, 1)
        lo.addWidget(home)
        bar.hide()
        self.server_banner = bar
        return bar

    def enter_server(self, target="dashboard"):
        """Leave the home network: run the boot checks, then open the server console."""
        if self.user.get("role") != "root":
            QMessageBox.information(self, "Root access needed",
                                    "The server console is for root users. Sign in as root to open it.")
            return
        self._pending_server_page = target if isinstance(target, str) else "dashboard"
        if self._immersive:
            self.set_immersive(False)
        self.right_panel.setVisible(False)
        self.server_banner.hide()
        self.sidebar.setVisible(False)            # the boot screen stands on its own
        self.sidebar._set_active_button(-1)
        self.stack.setCurrentWidget(self.view_server_boot)
        self.view_server_boot.start(self._boot_steps())

    def _boot_steps(self):
        # The checks run on a worker thread: hand them plain data, not Qt objects.
        user = dict(self.user)
        return [
            ("Launching server", server_checks.check_launch),
            ("Verifying root access", lambda: server_checks.check_root(user)),
            ("Checking system health", server_checks.check_system),
            ("Checking network connection", server_checks.check_network),
            ("Connecting to database", lambda: server_checks.check_database(DB_PATH)),
            ("Checking storage", server_checks.check_storage),
            ("Checking for updates", lambda: server_checks.check_updates(APP_VERSION)),
            ("Checking backups", lambda: backup_check(self.backup_service)),
            ("Starting services", self._services_step),
        ]

    def _services_step(self):
        # runs on the boot worker thread: only reads plain attributes
        s = self.services.summary()
        detail = f"{s['running']} of {s['total']} services running"
        if s["failed"]:
            return server_checks.WARN, detail + " · failed: " + ", ".join(s["failed_titles"])
        return server_checks.OK, detail + " · watchdog on"

    def _server_ready(self, results):
        warns = sum(1 for r in results if r[1] in (server_checks.WARN, server_checks.FAIL))
        try:
            Database.get_instance().log_operation(
                "Server", f"Server console opened ({warns} warning{'s' if warns != 1 else ''})", "Success")
        except Exception:
            pass
        from datetime import datetime
        self.server_info.setText(f"{self._server_host}  ·  online since {datetime.now():%H:%M}"
                                 + (f"  ·  {warns} warning{'s' if warns != 1 else ''} at start-up" if warns else ""))
        self.sidebar.setVisible(True)
        self.sidebar.set_mode(SERVER_MODE)
        self.server_banner.show()
        self.navigate_by_id(self._pending_server_page)

    def return_home(self):
        """Back to the home network (Smart Home screens)."""
        self.view_server_boot.stop()
        self.server_banner.hide()
        self.sidebar.setVisible(not self._immersive)
        self.sidebar.set_mode(HOME_MODE)
        self.navigate_by_id(self._last_home_page or "smart_dashboard")

    # ------------------------------------------------------------ accounts --

    def _apply_user(self):
        self.sidebar.set_user(self.user)
        if hasattr(self.view_settings, "set_account"):
            self.view_settings.set_account(self.auth, self.user)
        if self.user.get("role") != "root" and (self.sidebar.mode == SERVER_MODE
                                                 or self.stack.currentWidget() is self.view_server_boot):
            self.return_home()

    def lock(self):
        """Hide everything behind the sign-in screen. Any account may unlock;
        the sidebar and pages follow the account that signs in."""
        if self.auth is None or self._locked:
            return
        self._locked = True
        was_full = self.isFullScreen()
        self.hide()
        while True:
            dlg = LoginDialog(self.auth, locked_user=self.user.get("username"))
            if dlg.exec() == LoginDialog.Accepted:
                break
            if QMessageBox.question(None, "Quit CYPHER-X?",
                                    "The server stays locked. Quit CYPHER-X instead?") == QMessageBox.Yes:
                self._locked = False
                self.quit_app()
                QApplication.quit()
                return
        self._locked = False
        if dlg.user["username"].lower() != self.user.get("username", "").lower():
            try:
                Database.get_instance().log_operation("Accounts", f"Signed in as {dlg.user['username']}",
                                                      "Success")
            except Exception:
                pass
        self.user = dlg.user
        self._apply_user()
        self.showFullScreen() if was_full else self.showNormal()
        self.raise_()
        self.activateWindow()

    def _start_services(self):
        self.services.start_enabled()
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.timeout.connect(self._watchdog)
        self._watchdog_timer.start(3000)
        self._watchdog()

    def _setup_telemetry_loop(self):
        # Immediate sample
        self._sample_telemetry()

        # Recurring timer
        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self._sample_telemetry)
        self.metrics_timer.start(int(get_pref("pref_rate") or DEFAULT_METRICS_INTERVAL_MS))
        QTimer.singleShot(1500, self._start_services)

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
