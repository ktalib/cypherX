"""
Telegram bot: alerts to your phone and simple commands, from anywhere.

Set-up (once):
  1. In Telegram, talk to @BotFather → /newbot → copy the token it gives you.
  2. Paste the token in Server → Services → Telegram bot → Settings, Save, Start.
  3. Press "Pair a chat", then send the bot the code it shows: /start 123456

Only paired chats can use the bot. Alerts (each can be switched off):
motion with the snapshot, power cut / power back, meter running low, a
service restarted by the watchdog, new device on the Wi-Fi, backup problems.

Commands: /status /devices /on <name> /off <name> /alloff /units /arm /disarm
/snapshot /help — and plain words or voice notes go to the assistant.

Uses the Telegram Bot API over HTTPS with the standard library (urllib).
"""
import json
import re
import queue
import random
import threading
import time
import urllib.error
import urllib.request
import uuid

from app.server.services import ThreadService

API = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 20
PAIR_TTL = 600
ALERT_KINDS = {"motion": "alert_motion", "power": "alert_power", "meter": "alert_meter", "fridge": "alert_fridge",
               "service": "alert_system", "network": "alert_system", "backup": "alert_system",
               "smart": "alert_system"}


class TelegramError(Exception):
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal          # e.g. a bad token: retrying won't help until it's fixed


def _http_raw(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        raise TelegramError(f"download failed: {getattr(e, 'reason', e)}")


def _http(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            desc = body.get("description", str(e))
        except Exception:
            desc = str(e)
        raise TelegramError(desc, fatal=e.code in (401, 404))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TelegramError(f"network: {getattr(e, 'reason', e)}")


class TelegramClient:
    def __init__(self, token, http=_http, raw=_http_raw):
        self.token = token
        self.http = http
        self.raw = raw

    def call(self, method, params=None, timeout=30):
        url = API.format(token=self.token, method=method)
        data = json.dumps(params or {}).encode("utf-8")
        res = self.http(url, data, {"Content-Type": "application/json"}, timeout)
        if not res.get("ok"):
            raise TelegramError(res.get("description", "Telegram said no"))
        return res.get("result")

    def get_me(self):
        return self.call("getMe")

    def get_updates(self, offset, timeout=POLL_TIMEOUT):
        return self.call("getUpdates", {"offset": offset, "timeout": timeout,
                                        "allowed_updates": ["message"]}, timeout=timeout + 10)

    def send_message(self, chat_id, text):
        return self.call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})

    def download(self, file_id):
        """A photo someone sent the bot, as bytes."""
        path = self.call("getFile", {"file_id": file_id}).get("file_path")
        if not path:
            raise TelegramError("Telegram didn't give the file")
        return self.raw(f"https://api.telegram.org/file/bot{self.token}/{path}")

    def send_photo(self, chat_id, jpeg, caption=""):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (("chat_id", str(chat_id)), ("caption", caption[:1000])):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="snapshot.jpg"\r\n'
                     f'Content-Type: image/jpeg\r\n\r\n'.encode() + jpeg + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        res = self.http(API.format(token=self.token, method="sendPhoto"), b"".join(parts),
                        {"Content-Type": f"multipart/form-data; boundary={boundary}"}, 60)
        if not res.get("ok"):
            raise TelegramError(res.get("description", "Telegram said no"))
        return res.get("result")


HELP = ("CYPHER-X home bot\n"
        "/status – power, grid, meter, security\n"
        "/devices – appliances and their state\n"
        "/on <name>, /off <name> – switch an appliance (e.g. /off tv)\n"
        "/alloff – everything off except the fridge\n"
        "/units – prepaid meter units and days left\n"
        "/arm, /disarm – CCTV alerts\n"
        "/snapshot – latest camera picture\n"
        "/fridge – what's in the fridge\n"
        "/took 2 eggs, /add 6 beer – update the fridge\n"
        "📷 Send a photo of the open fridge and I'll count what's inside\n"
        "🎙 Or just say it: send a voice note or plain words, e.g. “is there light?”, “turn off the TV”")


def _h(hours):
    if hours is None:
        return "—"
    if hours >= 48:
        return f"{hours / 24:.1f} days"
    m = int(round(hours * 60))
    return f"{m // 60}h {m % 60:02d}m"


def match_devices(devices, text):
    """Find appliances by what people actually type: the full name, part of it,
    the short id ("tv"), or the start of each word ("bed light" → Bedroom light)."""
    q = text.lower().strip()
    exact = [d for d in devices if d["name"].lower() == q or d["id"].lower() == q]
    if exact:
        return exact
    words = q.split()

    def hit(d):
        name, ident = d["name"].lower(), d["id"].lower().replace("_", " ")
        if q in name or q in ident:
            return True
        name_words = name.split() + ident.split()
        return all(any(w.startswith(qw) for w in name_words) for qw in words)
    return [d for d in devices if hit(d)]


class BotBrain:
    """Turns a command into a reply using the home API. No network here (testable)."""

    def __init__(self, api):
        self.api = api

    def handle(self, text, who="telegram"):
        """Returns ("text", str) or ("photo", (jpeg_bytes, caption)) or ("text", error)."""
        parts = (text or "").strip().split(maxsplit=1)
        if not parts:
            return "text", HELP
        cmd = parts[0].split("@")[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        api = self.api
        if cmd in ("/start", "/help"):
            return "text", HELP
        if cmd == "/status":
            return "text", self.status_text(api.status())
        if cmd == "/devices":
            s = api.status()
            lines = [f"{'🟢' if d['on'] else '⚪'} {d['name']} ({d['room']}, {d['watts']:g} W)" for d in s["devices"]]
            return "text", "\n".join(lines) or "No appliances"
        if cmd in ("/on", "/off"):
            if not arg:
                return "text", f"Which one? e.g. {cmd} fan"
            s = api.status()
            want = cmd == "/on"
            matches = match_devices(s["devices"], arg)
            if not matches:
                return "text", f"No appliance called '{arg}'. Try /devices"
            if len(matches) > 1:
                return "text", "Which one? " + ", ".join(d["name"] for d in matches)
            d = matches[0]
            if d["on"] == want:
                return "text", f"{d['name']} is already {'on' if want else 'off'}."
            api.toggle(d["id"], who)
            return "text", f"{d['name']} switched {'ON' if want else 'OFF'}."
        if cmd == "/alloff":
            api.all_off(who)
            return "text", "Everything is off (fridge kept on)."
        if cmd == "/units":
            m = api.status()["meter"]
            if m["units_left"] is None:
                return "text", "No meter reading yet. Send one from the app or the web dashboard."
            extra = f"\n≈ {_h(m['days_left'] * 24)} left at {m['kwh_per_day']:.1f} kWh/day" if m["days_left"] else ""
            return "text", f"Meter: {m['units_left']:.1f} kWh left{extra}"
        if cmd in ("/arm", "/disarm"):
            api.set_armed(cmd == "/arm", who)
            return "text", "CCTV armed — you'll get motion alerts." if cmd == "/arm" else "CCTV disarmed."
        if cmd == "/snapshot":
            jpeg = api.snapshot_jpeg(None)
            if not jpeg:
                return "text", "No camera picture yet."
            caption = api.snapshot_caption() if hasattr(api, "snapshot_caption") else ""
            return "photo", (jpeg, caption or "Camera")
        if cmd == "/fridge":
            f = api.fridge()
            if not f["items"]:
                return "text", "Nothing tracked in the fridge yet. Send me a photo of it."
            lines = []
            for v in f["items"]:
                est = v["estimate"]
                n = f"≈{est:.0f}" if v["rate"] and abs(est - v["count"]) >= 0.5 else f"{v['count']}"
                when = f" · runs out in {_h(v['days_left'] * 24)}" if v["days_left"] is not None else ""
                lines.append(f"{'⚠️' if v['low'] else '•'} {v['name']}: {n}{when}")
            if f["last"]:
                lines.append(f"\nLast photo check {_h((time.time() - f['last']['ts']) / 3600)} ago")
            return "text", "\n".join(lines)
        if cmd in ("/took", "/add"):
            nums = re.findall(r"\b\d+\b", arg)
            n = int(nums[0]) if nums else 1
            name = " ".join(re.sub(r"\b\d+\b", " ", arg).split())
            if not name:
                return "text", f"What? e.g. {cmd} 2 eggs"
            v = api.fridge_find(name)
            if v is None:
                if cmd == "/took":
                    return "text", f"'{name}' isn't in the fridge list. Try /fridge"
                v = api.fridge_add(name.capitalize(), n, who)
                return "text", f"Now tracking {v['name']}: {n}."
            r = api.fridge_adjust(v["id"], -n if cmd == "/took" else n, who)
            return "text", f"{r['name']}: {r['after']} left." if cmd == "/took" else f"{r['name']}: {r['after']} now."
        if not cmd.startswith("/") and hasattr(api, "assistant_ask"):
            return self._reply(api.assistant_ask(text, who))     # plain words: "is there light?"
        return "text", "Unknown command.\n\n" + HELP

    def voice(self, audio, who="telegram"):
        """A voice note: transcribe it and let the assistant answer."""
        if not hasattr(self.api, "assistant_audio"):
            return "text", "Voice notes aren't supported here."
        try:
            reply = self.api.assistant_audio(audio, who)
        except Exception as e:
            return "text", f"Couldn't understand the voice note: {e}"
        heard = reply.get("heard") or ""
        return self._reply(reply, f"🎙 “{heard}”\n" if heard else "")

    @staticmethod
    def _reply(reply, lead=""):
        text = lead + (reply.get("say") or "")
        if reply.get("did"):
            text += "\n✅ " + ", ".join(reply["did"])
        if reply.get("photo"):
            return "photo", (reply["photo"], text[:1000])
        return "text", text

    def photo(self, jpeg, who="telegram"):
        """A photo sent to the bot: count the fridge."""
        try:
            res = self.api.fridge_check(jpeg, who)
        except Exception as e:
            return "text", f"Couldn't count that photo: {e}"
        if res["manual"]:
            return "text", "Photo saved. No AI is set up to count it — open CYPHER-X → Fridge → AI settings."
        extra = f"\n\nNote: {res['note']}" if res["note"] else ""
        return "text", f"🧊 Fridge ({res['provider']}):\n{res['text']}{extra}"

    @staticmethod
    def status_text(s):
        p, g, m, sec = s["power"], s["grid"], s["meter"], s["security"]
        cur = s["currency"]
        on = [d["name"] for d in s["devices"] if d["on"]]
        if g["off_since"]:
            grid = f"⚡ Grid OFF for {_h((time.time() - g['off_since']) / 3600)}"
        else:
            grid = "⚡ Grid on" if g["watching"] else "⚡ Grid not watched"
        lines = [
            f"🏠 {s['time']}",
            f"🔌 Load {p['load_w']:,.0f} W ({p['load_w'] / max(1, p['inverter_w']) * 100:.0f}% of inverter) · "
            f"{cur}{p['per_hour']:,.0f}/h",
            f"🔋 Battery {p['battery_pct']:.0f}%" + (f" · lasts {_h(p['runtime_h'])}" if p["runtime_h"] else ""),
            grid,
        ]
        if m["units_left"] is not None:
            lines.append(f"📟 Meter {m['units_left']:.1f} kWh" + (f" · ≈ {_h(m['days_left'] * 24)} left"
                                                                  if m["days_left"] else ""))
        lines.append(f"🛡 {'Armed' if sec['armed'] else 'Disarmed'} · {sec['motion_today']} motion today")
        lines.append("On: " + (", ".join(on) if on else "nothing"))
        return "\n".join(lines)


class TelegramService(ThreadService):
    id = "telegram"
    title = "Telegram bot"
    description = "Alerts to your phone (motion with photo, power cuts, meter low…) and commands like /status."
    icon = "bell"
    default_enabled = False
    settings_schema = [
        ("token", "Bot token", "secret", "", "From @BotFather in Telegram (/newbot)"),
        ("alert_motion", "Motion alerts (when armed)", "bool", True, ""),
        ("alert_power", "Power cut / back", "bool", True, ""),
        ("alert_meter", "Meter running low", "bool", True, ""),
        ("alert_fridge", "Fridge running low", "bool", True, ""),
        ("alert_system", "Server alerts", "bool", True, "Service restarts, new devices, backups"),
    ]

    def __init__(self, api, bus, client_factory=TelegramClient):
        super().__init__()
        self.api = api
        self.bus = bus
        self.brain = BotBrain(api)
        self.client_factory = client_factory
        self.client = None
        self.bot_name = ""
        self.outbox = queue.Queue()
        self.pair_code = None
        self.pair_until = 0
        self.sent = 0
        self._warned = set()

    # -- paired chats --
    def chats(self):
        return list(self.setting("chats") or [])

    def _add_chat(self, chat_id, name):
        chats = [c for c in self.chats() if c.get("id") != chat_id] + [{"id": chat_id, "name": name}]
        self.set_setting("chats", chats)

    def can_start(self):
        if not (self.setting("token") or "").strip():
            return False, "Paste the bot token from @BotFather in Settings, then Start."
        return True, ""

    # -- alerts in --
    def _on_event(self, event):
        key = ALERT_KINDS.get(event.get("kind"))
        if key and self.setting(key) is False:
            return
        if key is None or not self.chats() or self.status != "running":
            return
        self.outbox.put(event)

    def start(self):
        self.bus.subscribe(self._on_event)
        super().start()

    def stop(self):
        self.bus.unsubscribe(self._on_event)
        super().stop()

    # -- main loop --
    def run(self, stop):
        self.client = self.client_factory((self.setting("token") or "").strip())
        me = self.client.get_me()
        self.bot_name = me.get("username", "")
        self.mark_running()
        self.log(f"Connected as @{self.bot_name}")
        sender = threading.Thread(target=self._send_loop, args=(stop,), daemon=True)
        sender.start()
        offset, delay = None, 5
        while not stop.is_set():
            try:
                updates = self.client.get_updates(offset)
                delay = 5
            except TelegramError as e:
                if e.fatal:
                    raise
                self.log(f"Telegram unreachable ({e}); retrying in {delay} s", "warn")
                stop.wait(delay)
                delay = min(delay * 2, 120)
                continue
            for u in updates or []:
                offset = u["update_id"] + 1
                try:
                    self._handle_update(u)
                except Exception as e:
                    self.log(f"Couldn't handle a message: {e}", "error")

    def _send_loop(self, stop):
        while not stop.is_set():
            try:
                event = self.outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            text = f"{event['title']}\n{event['message']}"
            for chat in self.chats():
                try:
                    snap = event.get("snapshot")
                    if snap:
                        with open(snap, "rb") as f:
                            self.client.send_photo(chat["id"], f.read(), text)
                    else:
                        self.client.send_message(chat["id"], text)
                    self.sent += 1
                except (TelegramError, OSError) as e:
                    self.log(f"Alert not delivered to {chat.get('name')}: {e}", "warn")

    def _handle_update(self, u):
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id, text = chat.get("id"), (msg.get("text") or msg.get("caption") or "").strip()
        photo = msg.get("photo") or []
        doc = msg.get("document") or {}
        file_id = photo[-1].get("file_id") if photo else (
            doc.get("file_id") if str(doc.get("mime_type", "")).startswith("image/") else None)
        voice_id = (msg.get("voice") or msg.get("audio") or {}).get("file_id")
        if chat_id is None or not (text or file_id or voice_id):
            return
        name = chat.get("first_name") or chat.get("title") or chat.get("username") or str(chat_id)
        paired = any(c.get("id") == chat_id for c in self.chats())
        if not paired:
            parts = text.split()
            code = parts[1] if len(parts) > 1 and parts[0].split("@")[0] == "/start" else (parts[0] if parts else "")
            if self.pair_code and time.time() < self.pair_until and code == self.pair_code:
                self._add_chat(chat_id, name)
                self.pair_code = None
                self.log(f"Paired with {name}")
                self.client.send_message(chat_id, f"Paired with CYPHER-X ✅\n\n{HELP}")
            elif chat_id not in self._warned:
                self._warned.add(chat_id)
                self.log(f"Ignored a message from unpaired chat {name}", "warn")
                self.client.send_message(chat_id, "This bot is private. Pair it from CYPHER-X: "
                                                  "Server → Services → Telegram bot → Pair a chat.")
            return
        if voice_id:
            kind, payload = self.brain.voice(self.client.download(voice_id), who=f"Telegram: {name}")
            if kind == "photo":
                self.client.send_photo(chat_id, payload[0], payload[1])
            else:
                self.client.send_message(chat_id, payload)
            self.log(f"{name}: voice note")
            return
        if file_id:
            self.client.send_message(chat_id, "Counting what's in the photo… 🔎")
            kind, payload = self.brain.photo(self.client.download(file_id), who=f"Telegram: {name}")
            self.client.send_message(chat_id, payload)
            self.log(f"{name}: fridge photo")
            return
        kind, payload = self.brain.handle(text, who=f"Telegram: {name}")
        if kind == "photo":
            self.client.send_photo(chat_id, payload[0], payload[1])
        else:
            self.client.send_message(chat_id, payload)
        self.log(f"{name}: {text.split()[0]}")

    # -- Services page --
    def info(self):
        chats = self.chats()
        if not (self.setting("token") or "").strip():
            return ["Set-up: in Telegram open @BotFather → /newbot → copy the token → paste it below → "
                    "Save → Start → Pair a chat."]
        lines = [f"Bot: @{self.bot_name}" if self.bot_name else "Not connected yet",
                 "Paired chats: " + (", ".join(c.get("name", "?") for c in chats) if chats else "none — press Pair a chat"),
                 f"{self.sent} alert(s) sent this session"]
        if self.pair_code and time.time() < self.pair_until:
            lines.append(f"Pairing code: {self.pair_code} — send  /start {self.pair_code}  to "
                         f"@{self.bot_name or 'your bot'} within {int((self.pair_until - time.time()) / 60) + 1} min")
        return lines

    def actions(self):
        def pair():
            if self.status != "running":
                raise RuntimeError("Start the bot first.")
            self.pair_code = f"{random.SystemRandom().randint(0, 999999):06d}"
            self.pair_until = time.time() + PAIR_TTL
            return (f"Send this to @{self.bot_name} in Telegram within 10 minutes:\n\n"
                    f"/start {self.pair_code}")

        def test():
            if self.status != "running":
                raise RuntimeError("Start the bot first.")
            if not self.chats():
                raise RuntimeError("Pair a chat first.")
            self.outbox.put({"kind": "service", "title": "CYPHER-X", "message": "Test alert — the bot works ✅"})
            return "Test alert queued."

        def unpair():
            n = len(self.chats())
            self.set_setting("chats", [])
            return f"Removed {n} paired chat(s)."

        return [("Pair a chat", pair), ("Send test alert", test), ("Unpair all chats", unpair)]
