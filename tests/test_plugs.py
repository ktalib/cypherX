import json
import shutil
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.server import plugs as pl
from app.server.discovery import SmartDeviceBook, kasa_encrypt, kasa_decrypt
from app.server.services import ServiceManager


class FakeTuyaDevice:
    def __init__(self, dev_id, ip, key):
        self.args = (dev_id, ip, key)
        self.on = False
        self.version = None

    def set_version(self, v):
        self.version = v

    def set_socketTimeout(self, t):
        pass

    def status(self):
        return {"dps": {"1": self.on, "18": 640, "19": 1462 if self.on else 0, "20": 2291}}

    def set_status(self, on, switch=1):
        self.on = on
        return {"dps": {"1": on}}


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestDrivers(unittest.TestCase):
    def test_tuya(self):
        dev = {"id": "tuya:bf123", "ip": "192.168.1.34", "local_key": "0123456789abcdef", "extra": {"version": "3.4"}}
        drv = pl.TuyaDriver(dev, factory=FakeTuyaDevice)
        self.assertEqual(drv.d.args, ("bf123", "192.168.1.34", "0123456789abcdef"))
        self.assertEqual(drv.d.version, 3.4)
        drv.set_on(True)
        r = drv.status()
        self.assertEqual((r["on"], r["power_w"], r["voltage"], r["current_a"]), (True, 146.2, 229.1, 0.64))
        with self.assertRaises(pl.PlugError):
            pl.TuyaDriver({"id": "tuya:x", "ip": "1.2.3.4"}, factory=FakeTuyaDevice)     # no key

    def test_shelly_gen1_and_gen2(self):
        calls = []

        def gen1(url, timeout=3):
            calls.append(url)
            return {"relays": [{"ison": True}], "meters": [{"power": 87.5}]} if url.endswith("/status") else {}
        d = pl.ShellyDriver({"ip": "10.0.0.5", "extra": {"gen": 1}}, get=gen1)
        self.assertEqual(d.status()["power_w"], 87.5)
        d.set_on(False)
        self.assertTrue(calls[-1].endswith("/relay/0?turn=off"))

        def gen2(url, timeout=3):
            calls.append(url)
            return {"output": False, "apower": 0, "voltage": 230.1, "aenergy": {"total": 1500}}
        d = pl.ShellyDriver({"ip": "10.0.0.6", "extra": {"gen": 2}}, get=gen2)
        r = d.status()
        self.assertEqual((r["on"], r["energy_kwh"]), (False, 1.5))
        d.set_on(True)
        self.assertIn("Switch.Set?id=0&on=true", calls[-1])

    def test_tasmota(self):
        def get(url, timeout=3):
            if "Status%2010" in url:
                return {"StatusSNS": {"ENERGY": {"Power": 41, "Voltage": 228, "Current": 0.18, "Total": 3.2}}}
            return {"POWER": "ON"}
        r = pl.TasmotaDriver({"ip": "10.0.0.7"}, get=get).status()
        self.assertEqual((r["on"], r["power_w"], r["energy_kwh"]), (True, 41, 3.2))

    def test_kasa_over_tcp(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        state = {"on": 0}

        def serve():
            for _ in range(3):
                try:
                    c, _a = srv.accept()
                except OSError:
                    return
                with c:
                    n = struct.unpack(">I", c.recv(4))[0]
                    req = json.loads(kasa_decrypt(c.recv(n)))
                    if "set_relay_state" in req.get("system", {}):
                        state["on"] = req["system"]["set_relay_state"]["state"]
                        resp = {"system": {"set_relay_state": {"err_code": 0}}}
                    elif "emeter" in req:
                        resp = {"emeter": {"get_realtime": {"power_mw": 152300, "voltage_mv": 230500}}}
                    else:
                        resp = {"system": {"get_sysinfo": {"relay_state": state["on"], "feature": "TIM:ENE"}}}
                    data = kasa_encrypt(json.dumps(resp))
                    c.sendall(struct.pack(">I", len(data)) + data)
        threading.Thread(target=serve, daemon=True).start()
        port = srv.getsockname()[1]
        d = pl.KasaDriver({"ip": "127.0.0.1"}, request=lambda ip, p: pl.kasa_request(ip, p, port=port))
        d.set_on(True)
        r = d.status()
        srv.close()
        self.assertEqual((r["on"], r["power_w"], r["voltage"]), (True, 152.3, 230.5))

    def test_can_control_and_key_import(self):
        self.assertFalse(pl.can_control({"protocol": "tuya"})[0])
        self.assertTrue(pl.can_control({"protocol": "shelly"})[0])
        self.assertFalse(pl.can_control({"protocol": "mdns"})[0])

        class Cloud:
            error = None

            def __init__(self, **kw):
                self.kw = kw

            def getdevices(self, verbose=False):
                return [{"id": "bf123", "key": "k" * 16, "name": "Fridge plug", "product_name": "Smart Plug"},
                        {"id": "nokey"}]
        keys = pl.fetch_tuya_keys("eu", "id", "secret", cloud_factory=Cloud)
        self.assertEqual(list(keys), ["bf123"])
        self.assertEqual(keys["bf123"]["name"], "Fridge plug")


class TestPlugService(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.book = SmartDeviceBook(self.d / "smart.json")
        self.book.seen({"id": "tuya:bf123", "protocol": "tuya", "brand": "Tuya", "kind": "plug", "ip": "192.168.1.34",
                        "extra": {"version": "3.3", "device_id": "bf123"}})
        self.book.link("tuya:bf123", "fridge")
        self.applied = []
        self.fake = {}

        def factory(dev):
            if dev["id"] not in self.fake:
                self.fake[dev["id"]] = pl.TuyaDriver(dev, factory=FakeTuyaDevice)
            return self.fake[dev["id"]]
        self.svc = pl.PlugService(self.book, lambda item, on, w: self.applied.append((item, on, w)),
                                  driver_factory=factory)
        self.m = ServiceManager()
        self.m.register(self.svc)

    def tearDown(self):
        self.m.stop_all()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_needs_key_then_switches_and_reads(self):
        self.assertFalse(self.svc.request("fridge", True))                    # no key yet: not controllable
        self.assertIn("needs its local key", self.svc.info()[0])
        self.book.devices["tuya:bf123"]["local_key"] = "0123456789abcdef"
        self.m.start("plugs")
        self.assertTrue(wait_for(lambda: self.applied and self.applied[-1] == ("fridge", False, 0.0)))
        self.assertTrue(self.svc.request("fridge", True))
        self.assertTrue(wait_for(lambda: self.applied[-1] == ("fridge", True, 146.2)))
        self.assertIn("ON · 146 W", self.svc.info()[0])
        self.assertFalse(self.svc.request("tv", True))                        # tv has no plug

    def test_unreachable_plug_is_reported_once(self):
        self.book.devices["tuya:bf123"]["local_key"] = "0123456789abcdef"

        def broken(dev):
            raise pl.PlugError("no answer from 192.168.1.34")
        self.svc.driver_factory = broken
        self.svc.poll_all()
        self.svc.poll_all()
        self.assertEqual(sum(1 for _t, lvl, m in self.svc.logs if "not answering" in m), 1)
        self.assertIn("not answering", self.svc.info()[0])


class TestModelHook(unittest.TestCase):
    def test_switch_hook_and_live_watts(self):
        from app.home3d import model as hm
        d = tempfile.mkdtemp()
        old = hm.HOME_FILE
        hm.HOME_FILE = Path(d) / "home.json"
        try:
            m = hm.HomeModel()
            calls = []
            m.switch_hook = lambda item, on: calls.append((item, on))
            base = m.load_w()
            m.set_on("tv", True)
            m.set_on("tv", True)                                  # no change: no second call
            self.assertEqual(calls, [("tv", True)])
            self.assertEqual(m.load_w(), base + 100)              # rated watts while no reading
            self.assertFalse(m.apply_reading("tv", on=True, watts=62.0))
            self.assertEqual(m.load_w(), base + 62)               # measured watts win
            self.assertEqual(calls, [("tv", True)])               # a reading never calls back
            m.live["tv"] = (62.0, time.time() - 999)              # stale reading -> rated again
            self.assertEqual(m.load_w(), base + 100)
            m.all_off()
            self.assertIn(("tv", False), calls)
        finally:
            hm.HOME_FILE = old
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
