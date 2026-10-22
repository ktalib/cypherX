import shutil
import tempfile
import unittest
from pathlib import Path

import app.server.plugs as pl
from app.home3d.inverter import InverterMeter, INVERTER_IN, INVERTER_OUT, FRESH_S
from app.server.discovery import SmartDeviceBook
from app.server.plugs import reading

T = 1_000_000.0


def meter(*roles):
    return InverterMeter(lambda: set(roles))


class TestInverterMeter(unittest.TestCase):
    def test_grid_from_the_input_plug(self):
        m = meter(INVERTER_IN, INVERTER_OUT)
        self.assertIsNone(m.grid_on(T))                                         # nothing heard yet
        m.update(INVERTER_IN, reading(on=True, power_w=420, voltage=226), now=T)
        m.update(INVERTER_OUT, reading(on=True, power_w=300, voltage=230), now=T)
        self.assertTrue(m.grid_on(T))
        self.assertEqual(m.load_w(T), 300)
        self.assertEqual(m.charging_w(T), 120)
        # power cut: the grid-side plug goes silent, the house-side one keeps answering on the battery
        m.update(INVERTER_IN, error="no answer", now=T + 5)
        m.update(INVERTER_OUT, reading(on=True, power_w=310, voltage=229), now=T + 5)
        self.assertIs(m.grid_on(T + 6), False)
        self.assertIsNone(m.charging_w(T + 6))
        self.assertIn("Grid OFF", m.summary(T + 6)[0])
        # both silent: a Wi-Fi problem, not a power cut
        m.update(INVERTER_OUT, error="no answer", now=T + 10)
        self.assertIsNone(m.grid_on(T + 11))
        self.assertIsNone(m.load_w(T + 11))

    def test_low_voltage_and_stale_readings(self):
        m = meter(INVERTER_IN)
        m.update(INVERTER_IN, reading(on=True, power_w=0, voltage=12), now=T)    # plug alive, no mains
        self.assertIs(m.grid_on(T), False)
        m.update(INVERTER_IN, reading(on=True, power_w=50, voltage=180), now=T)  # low-voltage night still counts
        self.assertTrue(m.grid_on(T))
        self.assertIsNone(m.grid_on(T + FRESH_S + 1))                          # too old to trust
        m.update(INVERTER_IN, error="timeout", now=T + 100)                     # no OUT plug: silence = cut
        self.assertIs(m.grid_on(T + 101), False)

    def test_not_configured(self):
        m = meter()
        self.assertFalse(m.configured)
        m.update(INVERTER_IN, reading(on=True, voltage=230), now=T)
        self.assertIsNone(m.grid_on(T))                                         # no plug linked to the role
        self.assertEqual(m.summary(T), [])
        only_out = meter(INVERTER_OUT)
        only_out.update(INVERTER_OUT, reading(on=True, power_w=None), now=T)
        self.assertIsNone(only_out.load_w(T))
        self.assertIn("No plug on the inverter input", only_out.summary(T)[0])


class FakeDriver:
    def __init__(self, r=None, fail=False):
        self.r, self.fail, self.switched = r, fail, []

    def status(self):
        if self.fail:
            raise pl.PlugError("no answer")
        return self.r

    def set_on(self, on):
        self.switched.append(on)


class TestPlugRoles(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.book = SmartDeviceBook(self.d / "smart.json")
        for dev_id, role in (("shelly:in", INVERTER_IN), ("shelly:tv", "tv")):
            self.book.seen({"id": dev_id, "protocol": "shelly", "brand": "Shelly", "kind": "plug",
                            "ip": "192.168.1.5", "extra": {"gen": 1}})
            self.book.link(dev_id, role)
        self.drivers = {"shelly:in": FakeDriver(reading(on=True, power_w=410, voltage=228)),
                        "shelly:tv": FakeDriver(reading(on=True, power_w=95))}
        self.applied, self.roles = [], []
        self.svc = pl.PlugService(self.book, lambda *a: self.applied.append(a),
                                  driver_factory=lambda dev: self.drivers[dev["id"]],
                                  on_role=lambda *a: self.roles.append(a))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_role_plugs_are_read_not_applied_or_switched(self):
        self.svc.poll_all()
        self.assertEqual(self.applied, [("tv", True, 95)])
        self.assertEqual(self.roles[0][0], INVERTER_IN)
        self.assertEqual(self.roles[0][1]["voltage"], 228)
        self.assertFalse(self.svc.request(INVERTER_IN, False))               # never switched by the app
        self.svc._switch("shelly:in", False)
        self.assertEqual(self.drivers["shelly:in"].switched, [])
        self.drivers["shelly:in"].fail = True                                  # grid gone: plug silent
        self.svc.poll_all()
        self.assertEqual(self.roles[-1], (INVERTER_IN, None, "no answer"))


class TestMeasuredLoad(unittest.TestCase):
    def test_model_uses_the_measured_total(self):
        from app.home3d.model import HomeModel
        m = HomeModel.__new__(HomeModel)
        m.data, m.live, m.switch_hook, m.measured_load = {"rooms": [], "items": [], "power": {}}, {}, None, None
        m.devices = lambda room_id=None: [{"id": "tv", "device": {"watts": 100, "on": True}}]
        self.assertEqual(m.load_w(), 100)
        m.measured_load = lambda: 333.0
        self.assertEqual(m.load_w(), 333.0)
        self.assertEqual(m.load_w("living"), 100)                              # rooms still use the appliances
        m.measured_load = lambda: None                                          # plug silent: back to estimates
        self.assertEqual(m.load_w(), 100)


if __name__ == "__main__":
    unittest.main()
