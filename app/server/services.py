"""
Background services of the CYPHER-X server and the manager that runs them.

A service has a status (stopped / starting / running / failed), an uptime, a
restart count, its own log and optional settings. The manager starts the
services that are switched on, and its watchdog restarts a thread service that
died, waiting longer after each failure (5 s, 15 s, 60 s, then every 5 min).

Two kinds:
  ThreadService   runs in its own thread (web dashboard, Telegram bot, ...)
                  — subclasses implement run(stop_event) and may raise.
  ManagedService  wraps something that already lives in the app (cameras,
                  grid watch, automations, telemetry) through callables.

No Qt here: the main window drives watchdog() from a timer.
"""
import threading
import time
from collections import deque

STOPPED, STARTING, RUNNING, FAILED = "stopped", "starting", "running", "failed"
BACKOFF = (5, 15, 60, 300)
LOG_LINES = 400


class Service:
    id = "service"
    title = "Service"
    description = ""
    icon = "settings"
    default_enabled = False
    # (key, label, type, default, help)   type: "str" | "secret" | "int" | "bool"
    settings_schema = []

    def __init__(self):
        self.status = STOPPED
        self.started_at = None
        self.restarts = 0
        self.last_error = ""
        self.logs = deque(maxlen=LOG_LINES)
        self.manager = None

    # -- settings (stored by the manager) --
    def setting(self, key):
        default = next((s[3] for s in self.settings_schema if s[0] == key), None)
        if self.manager is None:
            return default
        return self.manager.get_setting(self.id, key, default)

    def set_setting(self, key, value):
        if self.manager is not None:
            self.manager.set_setting(self.id, key, value)

    # -- logging --
    def log(self, message, level="info"):
        self.logs.append((time.time(), level, message))
        if self.manager is not None:
            self.manager.on_log(self, level, message)

    # -- life cycle (override) --
    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def alive(self):
        return self.status == RUNNING

    def info(self):
        """A few short lines for the Services page."""
        return []

    def can_start(self):
        """(ok, reason) — e.g. a required setting is missing."""
        return True, ""

    def actions(self):
        """Extra buttons for the Services page: [(label, callable)]. A callable
        returns a short result message (or raises)."""
        return []

    def on_settings_changed(self):
        """Called after the settings form is saved."""

    @property
    def uptime(self):
        return time.time() - self.started_at if self.status == RUNNING and self.started_at else 0.0


class ThreadService(Service):
    """Runs run(stop_event) in a daemon thread. Returning or raising while not
    asked to stop counts as a crash; the watchdog restarts it."""

    def __init__(self):
        super().__init__()
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        ok, reason = self.can_start()
        if not ok:
            self.status = FAILED
            self.last_error = reason
            self.log(f"Can't start: {reason}", "error")
            return
        self._stop = threading.Event()
        self.status = STARTING
        self.last_error = ""
        self._thread = threading.Thread(target=self._main, name=f"svc-{self.id}", daemon=True)
        self._thread.start()

    def _main(self):
        stop = self._stop
        try:
            self.run(stop)
            if not stop.is_set():
                raise RuntimeError("stopped unexpectedly")
        except Exception as e:
            if not stop.is_set():
                self.status = FAILED
                self.last_error = str(e)
                self.log(f"Crashed: {e}", "error")
                return
        if stop.is_set():
            self.status = STOPPED

    def mark_running(self):
        """Call from run() once the service is actually serving."""
        self.status = RUNNING
        self.started_at = time.time()

    def stop(self):
        self._stop.set()
        self.on_stop()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self.status = STOPPED
        self.started_at = None

    def on_stop(self):
        """Override to unblock run() (close a socket, etc.)."""

    def alive(self):
        return self._thread is not None and self._thread.is_alive() and self.status in (STARTING, RUNNING)

    def run(self, stop_event):
        raise NotImplementedError


class ManagedService(Service):
    """Wraps an existing part of the app."""

    def __init__(self, sid, title, description, icon, start_fn, stop_fn, alive_fn,
                 info_fn=None, default_enabled=False):
        self._failed = False
        self._since = None
        super().__init__()
        self.id, self.title, self.description, self.icon = sid, title, description, icon
        self._start_fn, self._stop_fn, self._alive_fn = start_fn, stop_fn, alive_fn
        self._info_fn = info_fn
        self.default_enabled = default_enabled

    # Status follows the wrapped thing, so switching it elsewhere in the app
    # (e.g. the grid-watch checkbox on the Smart Home page) shows up here too.
    @property
    def status(self):
        if self._failed:
            return FAILED
        return RUNNING if self.alive() else STOPPED

    @status.setter
    def status(self, value):
        self._failed = value == FAILED

    @property
    def started_at(self):
        if self._failed or not self.alive():
            self._since = None
        elif self._since is None:
            self._since = time.time()
        return self._since

    @started_at.setter
    def started_at(self, value):
        self._since = value

    def start(self):
        try:
            self._start_fn()
        except Exception as e:
            self.status = FAILED
            self.last_error = str(e)
            self.log(f"Can't start: {e}", "error")
            return
        self._failed = False
        self.started_at = time.time()
        self.last_error = ""

    def stop(self):
        try:
            self._stop_fn()
        finally:
            self._failed = False
            self.started_at = None

    def alive(self):
        try:
            return bool(self._alive_fn())
        except Exception:
            return False

    def info(self):
        try:
            return list(self._info_fn()) if self._info_fn else []
        except Exception as e:
            return [f"Info unavailable: {e}"]


class ServiceManager:
    def __init__(self, store=None):
        """store: object with get_setting(key, default) / set_setting(key, value)
        (the app Database), or None to keep settings in memory (tests)."""
        self.store = store
        self._mem = {}
        self.services = {}
        self.order = []
        self._retry_at = {}
        self._fails = {}
        self.log_lines = deque(maxlen=1000)       # all services together

    # -- settings --
    def get_setting(self, sid, key, default=None):
        k = f"svc.{sid}.{key}"
        if self.store is None:
            return self._mem.get(k, default)
        value = self.store.get_setting(k, None)
        return default if value is None else value

    def set_setting(self, sid, key, value):
        k = f"svc.{sid}.{key}"
        if self.store is None:
            self._mem[k] = value
        else:
            self.store.set_setting(k, value)

    def enabled(self, sid):
        svc = self.services[sid]
        return bool(self.get_setting(sid, "enabled", svc.default_enabled))

    def set_enabled(self, sid, on):
        self.set_setting(sid, "enabled", bool(on))

    def on_log(self, svc, level, message):
        self.log_lines.append((time.time(), svc.id, level, message))

    # -- registry --
    def register(self, svc):
        svc.manager = self
        self.services[svc.id] = svc
        self.order.append(svc.id)
        _ = svc.started_at          # a wrapped service may already be running: note since when
        return svc

    def get(self, sid):
        return self.services.get(sid)

    def all(self):
        return [self.services[s] for s in self.order]

    # -- control --
    def start(self, sid, user=True):
        svc = self.services[sid]
        if user:
            self.set_enabled(sid, True)
            self._fails[sid] = 0
            self._retry_at.pop(sid, None)
        svc.log("Starting")
        svc.start()
        if svc.status == RUNNING:
            svc.log("Running")

    def stop(self, sid, user=True):
        svc = self.services[sid]
        if user:
            self.set_enabled(sid, False)
        self._retry_at.pop(sid, None)
        if svc.status != STOPPED:
            svc.log("Stopping")
            svc.stop()
            svc.log("Stopped")

    def restart(self, sid):
        svc = self.services[sid]
        svc.log("Restarting")
        if svc.status != STOPPED:
            svc.stop()
        svc.restarts += 1
        self.start(sid)

    def start_enabled(self):
        for sid in self.order:
            if self.enabled(sid) and self.services[sid].status != RUNNING:
                self.start(sid, user=False)

    def stop_all(self):
        for sid in reversed(self.order):
            svc = self.services[sid]
            if svc.status != STOPPED:
                try:
                    svc.stop()
                except Exception:
                    pass

    # -- watchdog --
    def watchdog(self, now=None):
        """Restart thread services that should run but died. Returns the ids restarted."""
        now = now or time.time()
        restarted = []
        for sid in self.order:
            svc = self.services[sid]
            if isinstance(svc, ManagedService):
                _ = svc.started_at  # notices starts / stops made elsewhere in the app
                continue
            if not isinstance(svc, ThreadService) or not self.enabled(sid):
                continue
            if svc.status in (RUNNING, STARTING) and not svc.alive():
                svc.status = FAILED
                svc.last_error = svc.last_error or "stopped responding"
            if svc.status != FAILED:
                self._fails[sid] = 0
                continue
            due = self._retry_at.get(sid)
            if due is None:
                n = self._fails.get(sid, 0)
                delay = BACKOFF[min(n, len(BACKOFF) - 1)]
                self._retry_at[sid] = now + delay
                svc.log(f"Watchdog: restarting in {delay} s ({svc.last_error})", "warn")
                continue
            if now >= due:
                self._retry_at.pop(sid, None)
                self._fails[sid] = self._fails.get(sid, 0) + 1
                svc.restarts += 1
                svc.log("Watchdog: restarting", "warn")
                svc.start()
                restarted.append(sid)
        return restarted

    def summary(self):
        running = [s for s in self.all() if s.status == RUNNING]
        failed = [s for s in self.all() if s.status == FAILED]
        return {"total": len(self.order), "running": len(running), "failed": len(failed),
                "failed_titles": [s.title for s in failed]}


def fmt_uptime(seconds):
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 86400}d {s % 86400 // 3600}h"
