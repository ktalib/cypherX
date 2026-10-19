import threading
import time
import unittest
from app.server.services import (
    ServiceManager, ThreadService, ManagedService, RUNNING, STOPPED, FAILED, fmt_uptime
)
from app.server.events import EventBus


class Sleeper(ThreadService):
    id, title = "sleeper", "Sleeper"

    def __init__(self, crash_after=None):
        super().__init__()
        self.crash_after = crash_after
        self.runs = 0

    def run(self, stop):
        self.runs += 1
        self.mark_running()
        t0 = time.time()
        while not stop.wait(0.01):
            if self.crash_after is not None and time.time() - t0 > self.crash_after:
                raise ValueError("boom")


class NeedsToken(ThreadService):
    id, title = "needs", "Needs token"
    settings_schema = [("token", "Token", "secret", "", "")]

    def can_start(self):
        return (True, "") if self.setting("token") else (False, "no token set")

    def run(self, stop):
        self.mark_running()
        stop.wait()


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class TestServices(unittest.TestCase):
    def test_start_stop_and_enabled_flag(self):
        m = ServiceManager()
        s = m.register(Sleeper())
        self.assertFalse(m.enabled("sleeper"))
        m.start("sleeper")
        self.assertTrue(wait_for(lambda: s.status == RUNNING))
        self.assertTrue(m.enabled("sleeper"))
        self.assertGreaterEqual(s.uptime, 0)
        m.stop("sleeper")
        self.assertEqual(s.status, STOPPED)
        self.assertFalse(m.enabled("sleeper"))
        self.assertIn("Stopped", [line[2] for line in s.logs])

    def test_watchdog_restarts_with_backoff(self):
        m = ServiceManager()
        s = m.register(Sleeper(crash_after=0.05))
        m.start("sleeper")
        self.assertTrue(wait_for(lambda: s.status == FAILED))
        self.assertEqual(s.last_error, "boom")
        now = time.time()
        self.assertEqual(m.watchdog(now), [])              # schedules a retry in 5 s
        self.assertEqual(m.watchdog(now + 1), [])          # not yet
        self.assertEqual(m.watchdog(now + 6), ["sleeper"])  # restarted
        self.assertTrue(wait_for(lambda: s.runs == 2))
        self.assertEqual(s.restarts, 1)
        s.crash_after = None
        m.stop("sleeper")

    def test_disabled_service_is_not_restarted(self):
        m = ServiceManager()
        s = m.register(Sleeper(crash_after=0.0))
        m.start("sleeper")
        self.assertTrue(wait_for(lambda: s.status == FAILED))
        m.set_enabled("sleeper", False)
        self.assertEqual(m.watchdog(time.time() + 1000), [])

    def test_can_start_and_settings(self):
        m = ServiceManager()
        s = m.register(NeedsToken())
        m.start("needs")
        self.assertEqual(s.status, FAILED)
        self.assertEqual(s.last_error, "no token set")
        s.set_setting("token", "abc")
        m.restart("needs")
        self.assertTrue(wait_for(lambda: s.status == RUNNING))
        m.stop_all()

    def test_managed_service_and_summary(self):
        state = {"on": False}
        m = ServiceManager()
        svc = m.register(ManagedService("grid", "Grid watch", "", "zap",
                                        lambda: state.update(on=True), lambda: state.update(on=False),
                                        lambda: state["on"], lambda: ["watching"], default_enabled=True))
        m.start_enabled()
        self.assertTrue(state["on"])
        self.assertEqual(svc.status, RUNNING)
        self.assertEqual(svc.info(), ["watching"])
        self.assertEqual(m.summary()["running"], 1)
        m.stop("grid")
        self.assertFalse(state["on"])

    def test_event_bus_and_uptime_format(self):
        bus = EventBus()
        got = []
        bus.subscribe(got.append)
        bus.subscribe(lambda e: 1 / 0)                       # a broken subscriber is ignored
        bus.publish("motion", "Motion", "Front door", camera="cam1")
        self.assertEqual(got[0]["camera"], "cam1")
        self.assertEqual(fmt_uptime(59), "59s")
        self.assertEqual(fmt_uptime(3725), "1h 02m")
        self.assertEqual(fmt_uptime(90000), "1d 1h")


if __name__ == "__main__":
    unittest.main()
