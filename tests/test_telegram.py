import os
import tempfile
import time
import unittest
from app.server.events import EventBus
from app.server.services import ServiceManager
from app.server.telegram import BotBrain, TelegramService, TelegramClient, TelegramError


class FakeApi:
    def __init__(self):
        self.devices = [{"id": "tv", "name": "Television", "room": "Living Room", "watts": 100, "on": False, "kind": "tv"},
                        {"id": "fan", "name": "Standing fan", "room": "Living Room", "watts": 55, "on": True, "kind": "fan"},
                        {"id": "light_bed", "name": "Bedroom light", "room": "Bedroom", "watts": 15, "on": False, "kind": "x"},
                        {"id": "light_k", "name": "Kitchen light", "room": "Kitchen", "watts": 15, "on": False, "kind": "x"}]
        self.armed = False
        self.calls = []

    def status(self, user=None):
        return {"time": "Mon 19 Oct 09:00", "currency": "₦",
                "power": {"load_w": 205, "inverter_w": 3000, "battery_pct": 80, "runtime_h": 9.5, "per_hour": 46},
                "grid": {"watching": True, "off_since": time.time() - 5400, "cuts_24h_h": 1.5},
                "meter": {"units_left": 42.0, "days_left": 3.0, "kwh_per_day": 14.0, "price": 227},
                "security": {"armed": self.armed, "motion_today": 2, "cameras": [], "latest": None},
                "devices": self.devices}

    def toggle(self, item_id, who):
        self.calls.append(("toggle", item_id, who))
        for d in self.devices:
            if d["id"] == item_id:
                d["on"] = not d["on"]

    def all_off(self, who):
        self.calls.append(("alloff", who))

    def set_armed(self, on, who):
        self.armed = on

    def snapshot_jpeg(self, cam):
        return b"\xff\xd8jpeg"

    def snapshot_caption(self):
        return "Front door · live"


class FakeClient:
    def __init__(self, token):
        self.token = token
        self.sent = []
        self.updates = []

    def get_me(self):
        if self.token == "bad":
            raise TelegramError("Unauthorized", fatal=True)
        return {"username": "cypherx_home_bot"}

    def get_updates(self, offset, timeout=20):
        time.sleep(0.02)
        out, self.updates = self.updates, []
        return out

    def send_message(self, chat_id, text):
        self.sent.append(("msg", chat_id, text))

    def send_photo(self, chat_id, jpeg, caption=""):
        self.sent.append(("photo", chat_id, caption))


def msg(chat_id, text, uid=[0]):
    uid[0] += 1
    return {"update_id": uid[0], "message": {"chat": {"id": chat_id, "first_name": f"user{chat_id}"}, "text": text}}


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class TestBotBrain(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.brain = BotBrain(self.api)

    def test_status_and_units(self):
        kind, text = self.brain.handle("/status")
        self.assertIn("Grid OFF for 1h 30m", text)
        self.assertIn("On: Standing fan", text)
        self.assertIn("42.0 kWh", self.brain.handle("/units")[1])

    def test_on_off_name_matching(self):
        self.assertIn("switched ON", self.brain.handle("/on tv")[1])
        self.assertEqual(self.api.calls[-1][:2], ("toggle", "tv"))
        self.assertIn("already on", self.brain.handle("/on television")[1])
        self.assertIn("Which one?", self.brain.handle("/on light")[1])          # two lights
        self.assertIn("No appliance", self.brain.handle("/off kettle")[1])
        self.assertIn("switched OFF", self.brain.handle("/off fan")[1])
        self.assertIn("Bedroom light switched ON", self.brain.handle("/on bed light")[1])

    def test_other_commands(self):
        self.assertEqual(self.brain.handle("/snapshot")[0], "photo")
        self.brain.handle("/arm@cypherx_home_bot")
        self.assertTrue(self.api.armed)
        self.assertIn("Unknown command", self.brain.handle("/dance")[1])


class TestTelegramService(unittest.TestCase):
    def setUp(self):
        self.api, self.bus = FakeApi(), EventBus()
        self.clients = []

        def factory(token):
            c = FakeClient(token)
            self.clients.append(c)
            return c
        self.m = ServiceManager()
        self.svc = self.m.register(TelegramService(self.api, self.bus, client_factory=factory))

    def tearDown(self):
        self.m.stop_all()

    def test_needs_token_and_bad_token_fails(self):
        self.m.start("telegram")
        self.assertEqual(self.svc.status, "failed")
        self.svc.set_setting("token", "bad")
        self.m.start("telegram")
        self.assertTrue(wait_for(lambda: self.svc.status == "failed"))
        self.assertIn("Unauthorized", self.svc.last_error)

    def test_pairing_commands_and_alerts(self):
        self.svc.set_setting("token", "good")
        self.m.start("telegram")
        self.assertTrue(wait_for(lambda: self.svc.status == "running"))
        client = self.clients[-1]
        # strangers are refused, and told only once
        client.updates = [msg(99, "/status"), msg(99, "/status")]
        self.assertTrue(wait_for(lambda: len(client.sent) == 1))
        self.assertIn("private", client.sent[0][2])
        # pairing with the code
        code = self.svc.actions()[0][1]().split("/start ")[1].strip()
        client.updates = [msg(7, "/start 000000" if code != "000000" else "/start 111111")]
        time.sleep(0.1)
        self.assertEqual(self.svc.chats(), [])
        client.updates = [msg(7, f"/start {code}")]
        self.assertTrue(wait_for(lambda: self.svc.chats() and self.svc.chats()[0]["id"] == 7))
        client.updates = [msg(7, "/off fan")]
        self.assertTrue(wait_for(lambda: any("switched OFF" in s[2] for s in client.sent)))
        # alerts from the bus, with the snapshot as a photo
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.write(fd, b"\xff\xd8jpeg")
        os.close(fd)
        try:
            self.bus.publish("motion", "Motion detected", "Front door", snapshot=path)
            self.bus.publish("power", "Power cut", "Grid is off")
            self.assertTrue(wait_for(lambda: self.svc.sent == 2))
            self.assertEqual([s[0] for s in client.sent[-2:]], ["photo", "msg"])
            # a switched-off alert type is not sent
            self.svc.set_setting("alert_power", False)
            self.bus.publish("power", "Grid restored", "back")
            time.sleep(0.2)
            self.assertEqual(self.svc.sent, 2)
        finally:
            os.remove(path)

    def test_client_builds_requests(self):
        seen = []

        def http(url, data, headers, timeout):
            seen.append((url, headers.get("Content-Type"), data))
            return {"ok": True, "result": {"username": "x"}}
        c = TelegramClient("123:ABC", http=http)
        c.get_me()
        c.send_photo(5, b"\xff\xd8", "hi")
        self.assertTrue(seen[0][0].endswith("/bot123:ABC/getMe"))
        self.assertIn("multipart/form-data", seen[1][1])
        self.assertIn(b'name="photo"', seen[1][2])
        with self.assertRaises(TelegramError):
            TelegramClient("t", http=lambda *a: {"ok": False, "description": "nope"}).get_me()


if __name__ == "__main__":
    unittest.main()
