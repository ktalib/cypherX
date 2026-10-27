import io
import json
import time
import unittest
import wave
from array import array

from app.services import assistant as core, speech, vision_ai
from app.services.assistant import Assistant, parse, wake_match, match_devices, spoken_digits, parse_ai_reply


class FakeApi:
    def __init__(self):
        self.devices = [
            {"id": "tv", "name": "Television", "room": "Living Room", "watts": 100, "on": False, "kind": "tv"},
            {"id": "fan", "name": "Standing fan", "room": "Living Room", "watts": 55, "on": True, "kind": "fan"},
            {"id": "light_bed", "name": "Bedroom light", "room": "Bedroom", "watts": 15, "on": True, "kind": "light"},
            {"id": "light_k", "name": "Kitchen light", "room": "Kitchen", "watts": 15, "on": False, "kind": "light"},
            {"id": "fridge", "name": "Fridge", "room": "Kitchen", "watts": 150, "on": True, "kind": "fridge"}]
        self.armed = True
        self.calls = []
        self.fridge_items = {"eggs": {"id": "eggs", "name": "Eggs", "count": 11, "estimate": 11.0, "rate": 3.0,
                                      "days_left": 3.6, "low": False}}

    def status(self, user=None):
        return {"time": "Mon 19 Oct 09:00", "currency": "₦",
                "power": {"load_w": 235, "inverter_w": 3000, "battery_pct": 80, "runtime_h": 9.5, "per_hour": 53,
                          "source": "Grid"},
                "grid": {"watching": True, "off_since": time.time() - 5400, "cuts_24h_h": 1.5},
                "meter": {"units_left": 42.0, "days_left": 3.0, "kwh_per_day": 14.0, "price": 227},
                "security": {"armed": self.armed, "motion_today": 2},
                "weather": {"place": "Lagos", "temp": 29.4, "desc": "Partly cloudy", "high": 32, "solar": "good"},
                "devices": self.devices}

    def toggle(self, item_id, who):
        self.calls.append(("toggle", item_id, who))
        for d in self.devices:
            if d["id"] == item_id:
                d["on"] = not d["on"]

    def all_off(self, who):
        self.calls.append(("alloff", who))
        for d in self.devices:
            if d["kind"] != "fridge":
                d["on"] = False

    def set_armed(self, on, who):
        self.calls.append(("armed", on))
        self.armed = on

    def snapshot_jpeg(self, cam):
        return b"\xff\xd8jpeg"

    def snapshot_caption(self):
        return "Front door · live · 10:00"

    def fridge(self):
        return {"items": list(self.fridge_items.values())}

    def fridge_find(self, name):
        return self.fridge_items.get(name.lower().rstrip("s") + "s") or self.fridge_items.get(name.lower())

    def fridge_adjust(self, item_id, delta, who):
        v = self.fridge_items[item_id]
        v["count"] += delta
        v["estimate"] = v["count"]
        self.calls.append(("fridge", item_id, delta))
        return {"name": v["name"], "after": v["count"]}

    def fridge_add(self, name, count, who):
        self.fridge_items[name.lower()] = {"id": name.lower(), "name": name, "count": count, "estimate": count,
                                           "rate": None, "days_left": None, "low": False}
        return {"id": name.lower(), "name": name}


def make(settings=None, now=None):
    api = FakeApi()
    st = core.default_settings()
    st.update(settings or {})
    clock = (lambda: now[0]) if now else time.time
    return api, st, Assistant(api, lambda: st, clock=clock)


class TestParse(unittest.TestCase):
    CASES = {
        "turn off the TV": {"do": "switch", "on": False, "target": "tv", "all": False},
        "please switch on the bedroom light for me": {"do": "switch", "on": True, "target": "bedroom light",
                                                      "all": False},
        "Put on the fan": {"do": "switch", "on": True, "target": "fan", "all": False},
        "switch the tv off": {"do": "switch", "on": False, "target": "tv", "all": False},
        "all off": {"do": "all_off"},
        "switch off everything": {"do": "all_off"},
        "is there light?": {"do": "grid"},
        "Has light come back": {"do": "grid"},
        "how many units are left": {"do": "units"},
        "how long will the battery last": {"do": "battery"},
        "how many eggs are left": {"do": "fridge_count", "item": "eggs"},
        "I took two eggs": {"do": "fridge_took", "n": 2, "item": "eggs"},
        "I bought 6 malt": {"do": "fridge_add", "n": 6, "item": "malt"},
        "arm the cameras": {"do": "arm"},
        "disarm four eight one five": {"do": "disarm", "pin": "4815"},
        "what's on": {"do": "status"},
        "what's the weather": {"do": "weather"},
        "show me the front door camera": {"do": "snapshot"},
        "how much power am I using": {"do": "load"},
    }

    def test_phrases(self):
        for text, want in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(parse(text), want)

    def test_all_lights_is_plural(self):
        self.assertEqual(parse("turn off all the lights"), {"do": "switch", "on": False, "target": "lights",
                                                            "all": True})

    def test_not_understood_and_negation(self):
        self.assertIsNone(parse("it's too hot in here"))
        self.assertIsNone(parse("don't switch off the fridge"))

    def test_disarm_is_never_a_switch(self):
        self.assertEqual(parse("turn off the alarm")["do"], "disarm")
        self.assertEqual(parse("switch off security 1234"), {"do": "disarm", "pin": "1234"})

    def test_spoken_digits(self):
        self.assertEqual(spoken_digits("4 8 1 5"), "4815")
        self.assertEqual(spoken_digits("four eight one five"), "4815")
        self.assertEqual(spoken_digits("4815"), "4815")


class TestWake(unittest.TestCase):
    def test_default_phrase(self):
        self.assertEqual(wake_match("Hey Cypher, turn off the TV", "Hey Cypher"), (True, "turn off the tv"))
        self.assertTrue(wake_match("hey cipher", "Hey Cypher")[0])
        self.assertTrue(wake_match("uh hey cypher what time is it", "Hey Cypher")[0])

    def test_other_words_dont_wake(self):
        for t in ("hey there", "hello", "hey simon", "okay so", ""):
            self.assertFalse(wake_match(t, "Hey Cypher")[0], t)

    def test_custom_phrase(self):
        self.assertEqual(wake_match("Jarvis lights off", "Jarvis"), (True, "lights off"))
        self.assertTrue(wake_match("ok house", "Okay House")[0])
        self.assertFalse(wake_match("Travis", "Jarvis")[0])
        self.assertFalse(wake_match("hey cypher", "Okay House")[0])


class TestMatchDevices(unittest.TestCase):
    def setUp(self):
        self.devs = FakeApi().devices

    def names(self, q):
        return [d["name"] for d in match_devices(self.devs, q)]

    def test_words_names_rooms_synonyms(self):
        self.assertEqual(self.names("tv"), ["Television"])
        self.assertEqual(self.names("telly"), ["Television"])
        self.assertEqual(self.names("light bedroom"), ["Bedroom light"])
        self.assertEqual(self.names("light in the kitchen"), ["Kitchen light"])
        self.assertEqual(self.names("lights"), ["Bedroom light", "Kitchen light"])
        self.assertEqual(self.names("refrigerator"), ["Fridge"])
        self.assertEqual(self.names("television"), ["Television"])
        self.assertEqual(self.names("microwave"), [])


class TestAssistant(unittest.TestCase):
    def test_switch_and_already(self):
        api, st, a = make()
        r = a.ask("turn on the TV", "me")
        self.assertEqual(r["say"], "Television on.")
        self.assertIn(("toggle", "tv", "me"), api.calls)
        self.assertIn("already on", a.ask("switch on the telly")["say"])

    def test_ambiguous_asks_unless_only_one_needs_it(self):
        api, st, a = make()
        r = a.ask("turn off the light")                  # only the bedroom light is on
        self.assertEqual(r["say"], "Bedroom light off.")
        api.devices[2]["on"] = api.devices[3]["on"] = True
        self.assertTrue(a.ask("turn off the light")["say"].startswith("Which one"))
        r = a.ask("turn off all the lights")
        self.assertEqual(r["say"], "Bedroom light and Kitchen light off.")

    def test_all_off_keeps_fridge(self):
        api, st, a = make()
        self.assertIn("except the fridge", a.ask("everything off")["say"])
        self.assertIn(("alloff", "assistant"), api.calls)
        self.assertIn("won't switch everything on", a.ask("turn everything on")["say"])

    def test_questions(self):
        api, st, a = make()
        self.assertIn("No light", a.ask("is there light")["say"])
        self.assertIn("1 hour 30 minutes", a.ask("is there light")["say"])
        self.assertIn("42.0 units", a.ask("how many units left")["say"])
        self.assertIn("80 percent", a.ask("battery")["say"])
        self.assertIn("Lagos", a.ask("weather")["say"])
        self.assertIn("235 watts", a.ask("what's on")["say"])
        r = a.ask("show me the camera")
        self.assertEqual(r["photo"], b"\xff\xd8jpeg")
        self.assertIn("Front door", r["say"])

    def test_fridge(self):
        api, st, a = make()
        self.assertIn("11 eggs", a.ask("how many eggs are left")["say"])
        self.assertIn("9 eggs left", a.ask("I took two eggs")["say"])
        self.assertIn("15 eggs", a.ask("I bought half a dozen eggs")["say"])
        self.assertIn("tracking malt: 6", a.ask("I bought 6 malt")["say"])
        self.assertIn("not tracking", a.ask("how many yams are left")["say"])

    def test_disarm_needs_pin(self):
        now = [1000.0]
        api, st, a = make(now=now)
        self.assertIn("needs a PIN", a.ask("disarm")["say"])
        core.set_pin(st, "4815")
        self.assertIn("Say disarm and your PIN", a.ask("disarm")["say"])
        self.assertEqual(a.ask("disarm 1 2 3 4")["say"], "That PIN is wrong.")
        self.assertTrue(api.armed)
        self.assertEqual(a.ask("disarm four eight one five")["say"], "Cameras disarmed.")
        self.assertFalse(api.armed)

    def test_pin_lockout(self):
        now = [1000.0]
        api, st, a = make(now=now)
        core.set_pin(st, "4815")
        for _ in range(core.PIN_TRIES):
            a.ask("disarm 0000")
        self.assertIn("Too many wrong PINs", a.ask("disarm 4815")["say"])
        self.assertTrue(api.armed)
        now[0] += core.PIN_LOCK_S + 1
        self.assertEqual(a.ask("disarm 4815")["say"], "Cameras disarmed.")

    def test_set_pin_rules(self):
        st = core.default_settings()
        with self.assertRaises(core.AssistantError):
            core.set_pin(st, "12")
        core.set_pin(st, "1234")
        self.assertTrue(st["pin_hash"] and "1234" not in st["pin_hash"])
        core.set_pin(st, "")
        self.assertEqual(st["pin_hash"], "")

    def test_not_understood_without_ai(self):
        api, st, a = make()
        r = a.ask("it's too hot in here")
        self.assertIn("didn't understand", r["say"])
        self.assertEqual(api.calls, [])

    def test_smart_answer_acts_but_never_disarms(self):
        api, st, a = make({"ai": "gemini"})
        seen = {}

        def fake_ask(settings, ai_settings, pid, text, context, timeout=None):
            seen["context"] = context
            return {"say": "I've switched on the TV for you.",
                    "actions": [{"do": "on", "target": "tv"}, {"do": "disarm", "target": ""},
                                {"do": "took", "target": "eggs", "count": 2}]}
        old = core.ask_ai
        core.ask_ai = fake_ask
        try:
            r = a.ask("I want to watch the news")
        finally:
            core.ask_ai = old
        self.assertEqual(r["say"], "I've switched on the TV for you.")
        self.assertEqual(r["did"], ["Television on", "fridge Eggs -2"])
        self.assertTrue(api.armed)
        self.assertEqual({d["id"] for d in seen["context"]["appliances"]}, {"tv", "fan", "light_bed", "light_k",
                                                                            "fridge"})

    def test_ai_errors_are_spoken(self):
        api, st, a = make({"ai": "gemini"})
        r = a.ask("it's too hot")          # no key saved
        self.assertIn("needs an API key", r["say"])

    def test_parse_ai_reply(self):
        self.assertEqual(parse_ai_reply('```json\n{"say": "Hi", "actions": []}\n```'), {"say": "Hi", "actions": []})
        self.assertEqual(parse_ai_reply("Sure, the fan is on."), {"say": "Sure, the fan is on.", "actions": []})
        self.assertEqual(parse_ai_reply('{"say": "ok", "actions": ["bad", {"do": "on", "target": "tv"}]}')["actions"],
                         [{"do": "on", "target": "tv"}])

    def test_ai_config_shares_keys(self):
        ai = vision_ai.default_settings()
        ai["providers"] = {"groq": {"key": "gsk_x", "model": "a-vision-model"}}
        st = core.default_settings()
        cfg = core.ai_config(st, ai, "groq")
        self.assertEqual(cfg["api_key"], "gsk_x")
        self.assertEqual(cfg["model"], core.AI_MODELS["groq"])          # text model, not the fridge's vision one
        st["models"] = {"groq": "my-model"}
        self.assertEqual(core.ai_config(st, ai, "groq")["model"], "my-model")
        self.assertTrue(core.ai_ready(st, ai, "groq")[0])


def tone(seconds, amp, rate=16000):
    import math
    a = array("h", (int(amp * 32767 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(int(seconds * rate))))
    return a.tobytes()


class TestSpeech(unittest.TestCase):
    def test_segmenter_cuts_utterances(self):
        seg = speech.Segmenter()
        chunk = 1600 * 2                                   # 100 ms
        stream = tone(1.0, 0.002) + tone(1.2, 0.3) + tone(1.0, 0.002)
        outs = [seg.feed(stream[i:i + chunk]) for i in range(0, len(stream), chunk)]
        got = [o for o in outs if o]
        self.assertEqual(len(got), 1)
        self.assertGreater(len(got[0]) / 2 / 16000, 1.2)   # the speech plus pre-roll

    def test_segmenter_ignores_quiet_and_clicks(self):
        seg = speech.Segmenter()
        chunk = 3200
        stream = tone(2.0, 0.002) + tone(0.1, 0.4) + tone(1.5, 0.002)
        self.assertFalse([o for o in (seg.feed(stream[i:i + chunk]) for i in range(0, len(stream), chunk)) if o])

    def test_wav_and_sniffing(self):
        wav = speech.pcm_to_wav(speech.Pcm(tone(0.2, 0.1), 16000))
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual((w.getnchannels(), w.getframerate()), (1, 16000))
        self.assertEqual(speech._file_name(wav)[1], "audio/wav")
        self.assertEqual(speech._file_name(b"OggS\x00\x02")[1], "audio/ogg")
        self.assertEqual(speech._file_name(b"\x00\x00\x00\x18ftypmp42")[1], "audio/mp4")
        self.assertEqual(speech._file_name(b"\x1aE\xdf\xa3")[1], "audio/webm")

    def test_local_engine_with_a_stand_in_model(self):
        class Seg:
            def __init__(self, t):
                self.text = t

        class Model:
            def transcribe(self, audio, **kw):
                Model.seen = (audio, kw)
                return iter([Seg(" Turn off"), Seg(" the TV.")]), None
        speech._models.pop("tiny.en", None)
        st = core.default_settings()
        st["stt_model"] = "tiny.en"
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")
        text = speech.transcribe(speech.Pcm(tone(0.5, 0.2), 16000), st, vision_ai.default_settings(),
                                 prompt="Hey Cypher", model_factory=lambda n: Model())
        self.assertEqual(text, "Turn off the TV.")
        audio, kw = Model.seen
        self.assertEqual(len(audio), 8000)
        self.assertEqual(kw["initial_prompt"], "Hey Cypher")
        self.assertIsNone(kw["language"])                  # English-only model: no language hint
        speech._models.pop("tiny.en", None)

    def test_cloud_engine(self):
        st = core.default_settings()
        st["stt"] = "groq"
        ai = vision_ai.default_settings()
        self.assertFalse(speech.stt_ready(st, ai)[0])
        ai["providers"] = {"groq": {"key": "gsk_123"}}
        self.assertTrue(speech.stt_ready(st, ai)[0])
        sent = {}

        def post(url, fields, file_field):
            sent.update(url=url, fields=fields, file=file_field)
            return {"text": " is there light? "}
        text = speech.transcribe(b"OggS voice note", st, ai, prompt="Television", post=post)
        self.assertEqual(text, "is there light?")
        self.assertTrue(sent["url"].endswith("/audio/transcriptions"))
        self.assertEqual(sent["fields"]["model"], "whisper-large-v3-turbo")
        self.assertEqual(sent["fields"]["language"], "en")
        name, ctype, data, headers = sent["file"]
        self.assertEqual((name, ctype, headers["Authorization"]), ("speech.ogg", "audio/ogg", "Bearer gsk_123"))
        speech.transcribe(speech.Pcm(tone(0.1, 0.1), 16000), st, ai, post=post)
        self.assertEqual(sent["file"][1], "audio/wav")

    def test_vocabulary_prompt(self):
        p = speech.vocabulary_prompt(["Television", "Standing fan"], "Okay House")
        self.assertTrue(p.startswith("Okay House."))
        self.assertIn("Standing fan", p)


class TestWebAndTelegram(unittest.TestCase):
    def test_web_routes(self):
        from app.server.web import WebApp, upload_type

        class Api:
            def assistant_ask(self, text, who):
                return {"heard": text, "say": "Television off.", "did": ["Television off"], "photo": b"\xff\xd8"}

            def assistant_audio(self, data, who):
                return {"heard": "units", "say": "42 units.", "did": [], "photo": None}

            def assistant_info(self):
                return {"stt_ready": True}

        class Auth:
            def authenticate(self, u, p):
                return {"username": "admin", "role": "root"}
        app = WebApp(Auth(), Api())
        tok = app.sessions.create({"username": "admin", "role": "root"})
        st, _, body, _ = app.handle("POST", "/api/assistant", {}, json.dumps({"text": "tv off"}).encode(), tok, "x")
        out = json.loads(body)
        self.assertEqual((st, out["say"], out["did"]), (200, "Television off.", ["Television off"]))
        self.assertTrue(out["image"].startswith("/api/snapshot.jpg"))
        self.assertNotIn("photo", out)
        st, _, body, _ = app.handle("POST", "/api/assistant/audio", {}, b"OggS...", tok, "x")
        self.assertEqual(json.loads(body)["say"], "42 units.")
        self.assertEqual(app.handle("POST", "/api/assistant", {}, b"{}", tok, "x")[0], 400)
        self.assertEqual(app.handle("POST", "/api/assistant/audio", {}, b"", tok, "x")[0], 400)
        self.assertEqual(app.handle("POST", "/api/assistant", {}, b'{"text":"x"}', None, "x")[0], 401)
        self.assertEqual(upload_type("POST", "/api/assistant/audio"), "audio/")
        self.assertIsNone(upload_type("POST", "/api/assistant"))
        self.assertEqual(upload_type("POST", "/api/fridge/photo"), "image/jpeg")

    def test_telegram_plain_words_and_voice(self):
        from app.server.telegram import BotBrain

        class Api:
            def assistant_ask(self, text, who):
                return {"heard": text, "say": f"heard {text}", "did": [], "photo": None}

            def assistant_audio(self, data, who):
                return {"heard": "lights off", "say": "Bedroom light off.", "did": ["Bedroom light off"],
                        "photo": None}
        brain = BotBrain(Api())
        self.assertEqual(brain.handle("is there light?"), ("text", "heard is there light?"))
        self.assertIn("Unknown command", brain.handle("/dance")[1])
        kind, text = brain.voice(b"OggS")
        self.assertEqual(kind, "text")
        self.assertIn("“lights off”", text)
        self.assertIn("✅ Bedroom light off", text)


if __name__ == "__main__":
    unittest.main()
