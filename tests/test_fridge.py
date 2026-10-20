import json
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.services import vision_ai
from app.services.fridge_service import FridgeStore, norm, run_photo_check, summary_text, changes_text
from app.services.vision_ai import VisionError, parse_answer

DAY = 86400.0
T0 = 1_760_000_000.0


class TestFridgeStore(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cyberops_test_fridge_")
        self.store = FridgeStore(self.root)
        self.eggs = self.store.find("eggs")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_seeded_and_matching(self):
        self.assertEqual(norm("Fresh Eggs (crate)"), "fresh egg crate")
        self.assertEqual(norm("Tomatoes"), "tomato")
        self.assertEqual(self.store.find("Egg")["name"], "Eggs")
        self.assertEqual(self.store.find("Star lager")["name"], "Beer")
        self.assertIsNone(self.store.find("Butter"))
        self.assertEqual(len(FridgeStore(self.root).items()), 2)     # seeded once, persisted

    def test_bought_adds_packs_and_untick_removes(self):
        self.store.on_bought("Eggs (crate)", 2, ts=T0)
        self.assertEqual(self.store.item(self.eggs["id"], now=T0)["count"], 60)
        self.store.on_bought("Star 60cl", 6, ts=T0)
        self.assertEqual(self.store.find("beer")["count"], 6)
        self.store.on_bought("Eggs (crate)", -1, ts=T0)
        self.assertEqual(self.store.item(self.eggs["id"], now=T0)["count"], 30)
        self.assertIsNone(self.store.on_bought("Rice 50kg", 1, ts=T0))

    def test_rate_estimate_and_low_alert_once(self):
        eid = self.eggs["id"]
        self.store.set_count(eid, 30, "bought", ts=T0)
        self.store.set_count(eid, 24, "photo", ts=T0 + 3 * DAY)        # 2 a day
        v = self.store.item(eid, now=T0 + 3 * DAY)
        self.assertAlmostEqual(v["rate"], 2.0)
        self.assertAlmostEqual(v["days_left"], 12.0)
        later = T0 + 13 * DAY                                          # 10 days on: ≈ 4 left
        v = self.store.item(eid, now=later)
        self.assertAlmostEqual(v["estimate"], 4.0)
        self.assertTrue(v["low"])
        self.assertEqual([x["name"] for x in self.store.newly_low(now=later)], ["Eggs"])
        self.assertEqual(self.store.newly_low(now=later), [])          # only once…
        self.store.on_bought("eggs", 1, ts=later)                      # …until restocked
        self.assertFalse(self.store.item(eid, now=later)["low"])

    def test_purchases_are_not_negative_use(self):
        eid = self.eggs["id"]
        self.store.set_count(eid, 10, "photo", ts=T0)
        self.store.set_count(eid, 40, "bought", ts=T0 + DAY)
        self.store.set_count(eid, 36, "photo", ts=T0 + 2 * DAY)
        self.assertAlmostEqual(self.store.item(eid, now=T0 + 2 * DAY)["rate"], 2.0)

    def test_apply_check_and_manual_adjust(self):
        changes = self.store.apply_check([("eggs", 7), ("Malt", 3), ("Water", 0)], photo="p.jpg",
                                         provider="gemini", ts=T0)
        self.assertEqual([(c["name"], c["after"], c["new"]) for c in changes],
                         [("Eggs", 7, False), ("Malt", 3, True)])          # unseen item at 0 isn't added
        self.assertIn("Malt: 3 (new)", changes_text(changes))
        self.assertEqual(self.store.last_check()["provider"], "gemini")
        malt = self.store.find("malt")
        self.store.adjust(malt["id"], -2, ts=T0 + 60)
        self.assertEqual(self.store.find("malt")["count"], 1)
        self.assertIn("Malt 1", summary_text(self.store.items(now=T0 + 60)))
        with self.assertRaises(ValueError):
            self.store.add_item("eggs")


class TestParse(unittest.TestCase):
    def test_parse_variants(self):
        self.assertEqual(parse_answer('{"items":[{"name":"Eggs","count":7}],"note":""}'), ([("Eggs", 7)], ""))
        fenced = '```json\n{"items":[{"name":"Beer","count":"4"},{"name":"beer","count":2}],"note":"dark"}\n```'
        self.assertEqual(parse_answer(fenced), ([("Beer", 6)], "dark"))
        chatty = 'Sure! Here you go: {"items": [{"name": "Malt", "count": 2.0}, {"name": "", "count": 1}]} Hope it helps'
        self.assertEqual(parse_answer(chatty)[0], [("Malt", 2)])
        for bad in ("", "no idea", '{"items": "lots"}'):
            with self.assertRaises(VisionError):
                parse_answer(bad)


class FakeAI(BaseHTTPRequestHandler):
    """Answers like Gemini, OpenAI-style servers and Ollama, and records what it got."""
    seen = []
    answer = '{"items":[{"name":"Eggs","count":5},{"name":"Beer","count":3}],"note":"ok"}'
    status = 200

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAI.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if FakeAI.status != 200:
            self.send_response(FakeAI.status)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"quota exceeded"}}')
            return
        if ":generateContent" in self.path:
            out = {"candidates": [{"content": {"parts": [{"text": FakeAI.answer}]}}]}
        elif self.path.endswith("/chat/completions"):
            out = {"choices": [{"message": {"content": FakeAI.answer}}]}
        else:
            out = {"message": {"content": FakeAI.answer}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class TestProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeAI)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeAI.seen.clear()
        FakeAI.status = 200

    def settings(self, provider, fallback="", **cfgs):
        return {"provider": provider, "fallback": fallback, "providers": cfgs}

    def test_each_http_provider_shape(self):
        jpeg = b"\xff\xd8fake"
        for pid in ("gemini", "openrouter", "groq", "ollama", "openai", "custom"):
            s = self.settings(pid, **{pid: {"key": "k-123", "url": self.base, "model": "m1"}})
            res = vision_ai.count_items(s, jpeg, ["Eggs", "Beer"])
            self.assertEqual(res["items"], [("Eggs", 5), ("Beer", 3)], pid)
            path, headers, body = FakeAI.seen[-1]
            text = json.dumps(body)
            self.assertIn("Beer, Eggs", text, pid)                         # known names, to reuse
            self.assertIn("/9hmYWtl", text, pid)                         # the image went along, base64
            if pid == "gemini":
                self.assertEqual(path, "/models/m1:generateContent")
                self.assertEqual(headers.get("x-goog-api-key"), "k-123")
            elif pid == "ollama":
                self.assertEqual(path, "/api/chat")
                self.assertEqual(body["model"], "m1")
            else:
                self.assertEqual(path, "/chat/completions")
                self.assertEqual(headers.get("authorization"), "Bearer k-123")

    def test_key_required_and_fallback(self):
        ok, why = vision_ai.ready(self.settings("gemini"))
        self.assertFalse(ok)
        self.assertIn("aistudio.google.com", why)
        self.assertTrue(vision_ai.ready(self.settings("ollama"))[0])     # local: no key needed
        FakeAI.status = 429                                               # free tier used up …
        s = self.settings("groq", "ollama", groq={"key": "k", "url": self.base},
                          ollama={"url": self.base, "model": "llava"})
        with self.assertRaises(VisionError) as e:
            vision_ai.count_with(s, "groq", b"x")
        self.assertIn("limit", str(e.exception))
        FakeAI.status = 200
        calls = []
        real = vision_ai.CALLERS["openai"]

        def failing(*a, **k):
            calls.append("groq")
            raise VisionError("quota")
        vision_ai.CALLERS["openai"] = failing
        try:
            res = vision_ai.count_items(s, b"x", [])                      # … so the backup answers
        finally:
            vision_ai.CALLERS["openai"] = real
        self.assertEqual((calls, res["provider"]), (["groq"], "ollama"))
        self.assertIn("quota", res["errors"][0])

    def test_ollama_not_running(self):
        s = self.settings("ollama", ollama={"url": "http://127.0.0.1:9"})
        with self.assertRaises(VisionError) as e:
            vision_ai.count_items(s, b"x", [])
        self.assertIn("ollama pull", str(e.exception))

    def test_claude_uses_the_sdk(self):
        captured = {}

        class Err(Exception):
            pass

        class Messages:
            def create(self, **kw):
                captured.update(kw)
                block = types.SimpleNamespace(type="text", text='{"items":[{"name":"Eggs","count":9}],"note":""}')
                return types.SimpleNamespace(stop_reason="end_turn", content=[block])

        class Client:
            def __init__(self, **kw):
                captured["client"] = kw
                self.beta = types.SimpleNamespace(messages=Messages())

        fake = types.SimpleNamespace(Anthropic=Client, AuthenticationError=Err, PermissionDeniedError=Err,
                                     NotFoundError=Err, RateLimitError=Err, APIStatusError=Err,
                                     APIConnectionError=Err)
        old = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake
        try:
            res = vision_ai.count_items(self.settings("claude", claude={"key": "sk-ant-x"}), b"\xff\xd8", ["Eggs"])
        finally:
            if old is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = old
        self.assertEqual(res["items"], [("Eggs", 9)])
        self.assertEqual(captured["model"], "claude-opus-5-5")
        self.assertEqual(captured["client"]["api_key"], "sk-ant-x")
        self.assertEqual(captured["fallbacks"], "default")
        self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(captured["messages"][0]["content"][0]["source"]["media_type"], "image/jpeg")


class TestPhotoCheck(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cyberops_test_fridgecheck_")
        self.store = FridgeStore(self.root)
        from PySide6.QtGui import QImage, QColor
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        img = QImage(3000, 2000, QImage.Format_RGB32)
        img.fill(QColor("#ffffff"))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        self.png = bytes(ba)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_manual_mode_keeps_photo_resized(self):
        res = run_photo_check(self.store, self.png, {"provider": "none"})
        self.assertTrue(res["manual"])
        from PySide6.QtGui import QImage
        img = QImage(res["photo"])
        self.assertEqual(max(img.width(), img.height()), vision_ai.MAX_SIDE)
        self.assertEqual(self.store.last_check()["provider"], "none")

    def test_ai_failure_keeps_photo_and_says_why(self):
        s = {"provider": "gemini", "fallback": "", "providers": {}}
        with self.assertRaises(VisionError):
            run_photo_check(self.store, self.png, s)
        self.assertIn("Not counted", self.store.last_check()["note"])
        with self.assertRaises(VisionError):
            run_photo_check(self.store, b"not a picture", s)


if __name__ == "__main__":
    unittest.main()


class TestFridgeRemote(unittest.TestCase):
    """HomeApi's fridge methods (used by the web dashboard and Telegram) on a real store."""

    def setUp(self):
        from app.server.home_api import HomeApi
        from app.server.telegram import BotBrain
        self.root = tempfile.mkdtemp(prefix="cyberops_test_fridgeapi_")
        self.store = FridgeStore(self.root)
        self.api = HomeApi(types.SimpleNamespace(fridge=self.store), bridge=None)
        self.brain = BotBrain(self.api)
        self.store.set_count(self.store.find("eggs")["id"], 12)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_telegram_fridge_commands(self):
        self.assertIn("Eggs: 12", self.brain.handle("/fridge")[1])
        self.assertEqual(self.brain.handle("/took 2 eggs")[1], "Eggs: 10 left.")
        self.assertEqual(self.brain.handle("/took egg")[1], "Eggs: 9 left.")
        self.assertEqual(self.brain.handle("/add 6 star")[1], "Beer: 6 now.")             # grocery-style names match
        self.assertEqual(self.brain.handle("/add malt 3")[1], "Now tracking Malt: 3.")
        self.assertIn("isn't in the fridge list", self.brain.handle("/took 1 butter")[1])
        self.assertIn("e.g. /took 2 eggs", self.brain.handle("/took 2")[1])

    def test_web_routes(self):
        from app.server.web import WebApp

        class Auth:
            def authenticate(self, u, p):
                return {"id": 1, "username": u, "role": "user"} if p == "pw" else None

        app = WebApp(Auth(), self.api)
        _, _, _, cookie = app.handle("POST", "/api/login", {}, json.dumps({"username": "mum", "password": "pw"}).encode(),
                                     None, "1.1.1.1")
        tok = cookie.split(";")[0].split("=", 1)[1]

        def call(method, path, body=None, raw=None):
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
            st, ct, payload, _ = app.handle(method, path, {}, data, tok, "1.1.1.1")
            return st, (json.loads(payload) if ct == "application/json" else payload)

        st, f = call("GET", "/api/fridge")
        self.assertEqual(st, 200)
        eggs = next(v for v in f["items"] if v["name"] == "Eggs")
        self.assertEqual(eggs["count"], 12)
        self.assertIsNone(f["last"])
        self.assertEqual(call("POST", f"/api/fridge/{eggs['id']}/adjust", {"delta": -3})[1]["after"], 9)
        self.assertEqual(call("POST", f"/api/fridge/{eggs['id']}/set", {"count": 30})[1]["after"], 30)
        self.assertEqual(call("POST", "/api/fridge/nope/adjust", {"delta": 1})[0], 404)
        self.assertEqual(call("POST", f"/api/fridge/{eggs['id']}/set", {"count": -1})[0], 400)
        self.assertEqual(call("POST", "/api/fridge/add", {"name": "  Malt "})[1]["name"], "Malt")
        self.assertEqual(call("POST", "/api/fridge/add", {"name": "malt"})[0], 400)          # already tracked
        self.assertEqual(call("GET", "/api/fridge/photo.jpg")[0], 404)
        # a photo with no AI set up is saved for counting by hand; a broken picture is refused
        from app.database import Database
        old = vision_ai.load_settings(Database.get_instance())
        vision_ai.save_settings(Database.get_instance(), {"provider": "none", "fallback": "", "providers": {}})
        try:
            from PySide6.QtGui import QImage, QColor
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            img = QImage(64, 48, QImage.Format_RGB32)
            img.fill(QColor("#ffffff"))
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "JPG")
            st, res = call("POST", "/api/fridge/photo", raw=bytes(ba))
            self.assertEqual((st, res["manual"]), (200, True))
            st, jpeg = call("GET", "/api/fridge/photo.jpg")
            self.assertEqual((st, jpeg[:2]), (200, b"\xff\xd8"))
            self.assertEqual(call("POST", "/api/fridge/photo", raw=b"garbage")[0], 422)
            self.assertIn("No AI is set up", self.brain.photo(bytes(ba))[1])
        finally:
            vision_ai.save_settings(Database.get_instance(), old)


class TestFridgeCam(unittest.TestCase):
    def test_counts_when_the_light_comes_on_and_alerts_if_left_open(self):
        import app.server.fridgecam as fc
        from app.server.events import EventBus
        from app.server.services import ServiceManager
        levels = [10, 10, 200, 200, 200, 200, 10, 10, 200, 200] + [200] * 400
        clock = {"t": 1000.0}
        events, checks = [], []

        def fetch(url, timeout=6):
            clock["t"] += 30                           # every picture is "30 s later"
            return b"\xff\xd8" + bytes([levels.pop(0) if levels else 200])

        def check(store, jpeg, settings, source):
            checks.append(source)
            return {"manual": False, "changes": [{"name": "Eggs", "before": 9, "after": 7, "new": False}]}

        bus = EventBus()
        bus.subscribe(events.append)
        old = (fc.POLL_S, fc.SETTLE_S)
        fc.POLL_S, fc.SETTLE_S = 0.001, 0.001
        m = ServiceManager()
        svc = m.register(fc.FridgeCamService(None, lambda: {}, bus, fetch=fetch, measure=lambda j: j[2],
                                             check=check, clock=lambda: clock["t"]))
        try:
            m.start("fridge_cam")
            self.assertEqual(svc.status, "failed")            # no address yet
            svc.set_setting("url", "http://cam/capture")
            svc.set_setting("gap_min", 5)
            svc.set_setting("open_alert_s", 120)
            m.start("fridge_cam")
            end = time.time() + 3
            while time.time() < end and len(levels) > 300:
                time.sleep(0.01)
        finally:
            m.stop_all()
            fc.POLL_S, fc.SETTLE_S = old
        self.assertEqual(checks, ["camera"])                  # 2nd opening was within 5 min: not counted
        self.assertEqual(svc.opens, 2)
        self.assertIn("Eggs: 7", svc.last_result)
        self.assertIn(("fridge", "Fridge door open"), [(e["kind"], e["title"]) for e in events])
