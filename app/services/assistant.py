"""
The home assistant: understands what people say or type — "turn off the TV",
"is there light?", "how many eggs are left?", "disarm 4 8 1 5" — and does it
through the home API (the same one the phone dashboard and Telegram bot use).

  • Everyday commands are understood offline by a small rule-based parser, so
    they work instantly with no AI and no internet.
  • Anything the parser doesn't understand can go to an optional AI ("smart
    answers"): the same providers as the fridge photo AI, free ones included,
    sharing the same API keys. The AI may switch appliances, arm the cameras and
    update the fridge, but never disarm.
  • Disarming the cameras by voice needs a PIN, so nobody can shout it through
    a window. Wrong PINs lock voice disarm for a while.

Settings are one JSON value in the app database ("assistant").
"""
import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher, get_close_matches

from app.services import vision_ai

SETTING_KEY = "assistant"
DEFAULT_WAKE = "Hey Cypher"
PIN_TRIES, PIN_LOCK_S = 5, 600
MAX_TEXT = 300

# Text models for smart answers (the fridge AI's defaults are vision models)
AI_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "llama3.2:3b",
    "claude": "claude-opus-5-5",
    "openai": "gpt-4o-mini",
    "custom": "",
}
AI_ORDER = ("none", "gemini", "groq", "openrouter", "ollama", "claude", "openai", "custom")


class AssistantError(Exception):
    pass


# ----------------------------------------------------------------- settings --

def default_settings():
    return {"ai": "none", "models": {}, "stt": "local", "stt_model": "base.en", "speak": True,
            "voice": "", "rate": 0.0, "wake_on": False, "wake_phrase": DEFAULT_WAKE, "lang": "en-NG",
            "pin_hash": "", "pin_salt": ""}


def load_settings(db):
    s = default_settings()
    stored = db.get_setting(SETTING_KEY, None) if db is not None else None
    if isinstance(stored, dict):
        s.update({k: v for k, v in stored.items() if k in s})
    if not str(s.get("wake_phrase") or "").strip():
        s["wake_phrase"] = DEFAULT_WAKE
    return s


def save_settings(db, settings):
    db.set_setting(SETTING_KEY, settings)


def set_pin(settings, pin):
    """Store a PIN (4–8 digits) as a salted hash; an empty PIN removes it."""
    pin = re.sub(r"\D", "", str(pin or ""))
    if not pin:
        settings["pin_hash"] = settings["pin_salt"] = ""
        return settings
    if not 4 <= len(pin) <= 8:
        raise AssistantError("The PIN must be 4 to 8 digits")
    salt = secrets.token_hex(8)
    settings["pin_salt"] = salt
    settings["pin_hash"] = _pin_hash(pin, salt)
    return settings


def _pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


# ------------------------------------------------------------ text helpers --

NUMBER_WORDS = {
    "zero": 0, "oh": 0, "o": 0, "one": 1, "won": 1, "a": 1, "an": 1, "two": 2, "to": 2, "too": 2,
    "three": 3, "four": 4, "for": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ate": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
}
DIGIT_WORDS = {k: v for k, v in NUMBER_WORDS.items() if v <= 9 and k not in ("a", "an")}

FILLER = {
    "please", "pls", "plz", "can", "could", "would", "will", "you", "kindly", "abeg", "for", "me", "the", "a",
    "an", "my", "our", "in", "at", "of", "now", "right", "just", "help", "i", "want", "wanna", "to", "go",
    "ahead", "and", "hey", "ok", "okay", "so", "that", "this", "there", "it", "is", "are", "be", "do", "make",
    "sure", "quickly", "some", "its", "whats",
}
SYNONYMS = {
    "tv": ["television", "telly"], "television": ["tv"], "telly": ["tv", "television"],
    "ac": ["air", "aircon", "conditioner"], "aircon": ["ac", "air"], "fridge": ["refrigerator"],
    "refrigerator": ["fridge"], "bulb": ["light", "lamp"], "lamp": ["light", "bulb"], "lights": ["light"],
    "light": ["lamp", "bulb"], "dstv": ["decoder"], "gotv": ["decoder"], "decoder": ["dstv", "gotv"],
    "socket": ["plug"], "plug": ["socket"], "fan": ["fan"], "lounge": ["living"], "parlour": ["living"],
    "parlor": ["living"], "sitting": ["living"], "room": ["room"], "bedroom": ["bedroom"],
    "freezer": ["fridge"], "heater": ["water"], "pumping": ["pump"], "machine": ["machine"],
}


def norm(text):
    t = str(text or "").lower().replace("’", "'")
    t = t.replace("n't", " not").replace("'re ", " are ").replace("'", "")     # what's → whats, it's → its
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def _sing(w):
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def parse_number(words):
    """First number in a word list: digits or words ('a', 'two', 'a dozen'). None if none."""
    joined = " ".join(words)
    if re.search(r"\bhalf (a )?dozen\b", joined):
        return 6
    for i, w in enumerate(words):
        if w.isdigit():
            return int(w)
        if w in NUMBER_WORDS and w not in ("to", "too", "for", "o", "oh", "won", "ate"):
            if w in ("a", "an") and i + 1 < len(words) and words[i + 1] == "dozen":
                return 12
            if w == "twenty" and i + 1 < len(words) and NUMBER_WORDS.get(words[i + 1], 99) < 10:
                return 20 + NUMBER_WORDS[words[i + 1]]
            return NUMBER_WORDS[w]
    return None


def spoken_digits(text):
    """'4 8 1 5', '4815', 'four eight one five' → '4815' (for the PIN)."""
    out = []
    for w in norm(text).split():
        if w.isdigit():
            out.append(w)
        elif w in DIGIT_WORDS:
            out.append(str(DIGIT_WORDS[w]))
    return "".join(out)


CALL_WORDS = {"hey", "hi", "ok", "okay", "yo", "hello", "oi"}


def _sounds(s):
    """Rough sound-alike spelling, so "cypher", "cipher" and "siphon" come out close."""
    s = s.replace("ph", "f").replace("ck", "k").replace("gh", "").replace("wh", "w")
    s = re.sub(r"c(?=[eiy])", "s", s).replace("c", "k").replace("y", "i").replace("z", "s").replace("q", "k")
    return re.sub(r"(.)\1+", r"\1", s)


def wake_match(text, phrase, threshold=0.72):
    """Does `text` start with the wake phrase (allowing for small mishearings)?
    Returns (matched, rest_of_text). Works for any phrase the user picks."""
    want = norm(phrase).split()
    words = norm(text).split()
    if not want or not words:
        return False, ""
    target = " ".join(want)
    key = "".join(x for x in want if x not in CALL_WORDS)
    best, best_end = 0.0, 0
    for start in range(0, min(3, len(words))):          # allow a stray "uh" / "okay" before it
        for n in (len(want) - 1, len(want), len(want) + 1):
            if n < 1 or start + n > len(words):
                continue
            got = " ".join(words[start:start + n])
            score = max(SequenceMatcher(None, got, target).ratio(),
                        SequenceMatcher(None, _sounds(got), _sounds(target)).ratio())
            if key and SequenceMatcher(None, _sounds("".join(x for x in got.split() if x not in CALL_WORDS)),
                                       _sounds(key)).ratio() < 0.66:
                continue                  # "hey there" is not "hey cypher": the name itself must sound alike
            if score > best:
                best, best_end = score, start + n
    if best >= threshold:
        return True, " ".join(words[best_end:])
    return False, ""


# ------------------------------------------------------------------ parser --

def parse(text):
    """Text → an intent dict, or None when it isn't understood. No side effects."""
    t = norm(text)
    if not t:
        return {"do": "help"}
    w = t.split()
    ws = set(w)

    if t in ("thanks", "thank you", "thank you very much", "nice one", "good job", "well done"):
        return {"do": "thanks"}
    if re.fullmatch(r"(hi|hello|hey|good (morning|afternoon|evening))( \w+)?", t):
        return {"do": "hello"}
    if re.search(r"\bwhat can you do\b|\bhelp\b|\bcommands\b", t) and len(w) <= 6:
        return {"do": "help"}

    # security first: "disarm" must never be read as a plain switch
    if re.search(r"\b(disarm|unarm|dis arm)\b|\b(switch|turn) off (the )?(alarm|security|cctv|motion alerts?)\b"
                 r"|\b(alarm|security|cctv) off\b", t):
        return {"do": "disarm", "pin": spoken_digits(re.sub(r".*?\b(disarm|unarm|dis arm|off)\b", "", t, count=1))}
    if re.search(r"\barm\b|\b(switch|turn) on (the )?(alarm|security|cctv|motion alerts?)\b"
                 r"|\b(activate|enable) (the )?(alarm|security|cctv|cameras?)\b", t):
        return {"do": "arm"}

    # meter / grid / battery / load / weather / time — questions, not switches
    if re.search(r"\b(units?|meter|token|kwh)\b", t) and not re.search(r"\b(bought|buy|recharge|loaded)\b", t):
        return {"do": "units"}
    if re.search(r"\b(grid|nepa|phcn|mains|power cut|outage|blackout)\b|\bis there (light|power)\b"
                 r"|\bdo we have (light|power)\b|\b(light|power) (don|has|have)? ?(come|gone|go|back|been)\b"
                 r"|\bdid (light|power) (go|come)\b|\bwhen did (light|power)\b", t):
        return {"do": "grid"}
    if re.search(r"\b(battery|batteries|inverter|backup)\b|\bhow long (will|can|would) .*\blast\b", t):
        return {"do": "battery"}
    if re.search(r"\bhow much (power|electricity|energy|current)\b|\b(load|consumption|watts?|wattage)\b"
                 r"|\bhow much am i (using|spending)\b|\bcost\b", t):
        return {"do": "load"}
    if re.search(r"\b(weather|rain|raining|temperature|forecast|sunny|cloudy|solar)\b|\bhow hot\b", t):
        return {"do": "weather"}
    if re.search(r"\bwhat time\b|\btime is it\b|\bwhats (the )?(date|day)\b|\bwhat (is )?(the )?(date|day)\b|\btodays date\b", t):
        return {"do": "time"}
    if re.search(r"\b(snapshot|picture|photo)\b|\bshow\b.*\b(camera|cctv|door|gate|compound)\b"
                 r"|\bwho is (at|outside)\b", t):
        return {"do": "snapshot"}

    # fridge
    m = re.search(r"\b(took|take|taken|used|use|drank|drink|ate|eat|finished|removed|remove|cooked)\b(.*)", t)
    if m and not re.search(r"\b(off|on)\b", m.group(2)):
        n, item = _count_and_item(m.group(2))
        if item:
            return {"do": "fridge_took", "n": n, "item": item}
    m = re.search(r"\b(bought|buy|added|add|put|stocked|kept|keep)\b(.*)", t)
    if m and not re.match(r"\s*(it\s+)?(on|off)\b", m.group(2)) and not re.search(r"\b(appliance|device)\b", t):
        n, item = _count_and_item(m.group(2))
        if item:
            return {"do": "fridge_add", "n": n, "item": item}
    m = re.search(r"\bhow (many|much) (.+?)( (are|is|do|have|left|remain|remaining|in|we|i|still)\b.*)?$", t)
    if m:
        item = _strip_filler(m.group(2))
        if item and item not in ("thing", "things", "item", "items", "stuff"):
            return {"do": "fridge_count", "item": item}
    if re.search(r"\b(fridge|refrigerator|freezer)\b", t) and not re.search(r"\b(on|off)\b", t):
        return {"do": "fridge_list"}
    m = re.search(r"\b(?:any|is there|are there|do (?:we|i) (?:still )?have) (.+?)( left| remaining| in the fridge)?$", t)
    if m and m.group(1) not in ("light", "power") and not re.search(r"\b(on|off)\b", t):
        return {"do": "fridge_count", "item": _strip_filler(m.group(1))}

    # status
    if re.search(r"\b(status|report|summary)\b|\bwhat is (on|running|happening)\b|\bhows (the )?(house|home)\b"
                 r"|\bwhats (on|running|happening)\b|\bwhat (appliances|devices|things) are on\b"
                 r"|\bhow is (the )?(house|home)\b", t):
        return {"do": "status"}

    # switching
    state = None
    if re.search(r"\b(off|shut|kill|stop|cut)\b", t):
        state = False
    elif re.search(r"\bon\b|\bstart\b|\bopen\b", t):
        state = True
    if state is not None and re.search(r"\b(not|dont|never)\b", t):
        return None                     # "don't switch off the fridge": not a command to act on
    if state is not None:
        target = re.sub(r"\b(turn|switch|put|power|set|start|stop|shut|kill|cut|open|on|off|down|up|"
                        r"close|everything off|it)\b", " ", t)
        target = _strip_filler(target)
        if target in ("", "everything", "all", "all appliances", "all devices", "all thing", "every thing",
                      "everything in house", "all house", "house", "all of them"):
            return {"do": "all_off"} if state is False else {"do": "all_on"}
        everything = "all" in target.split() or "every" in target.split()
        plural = any(x.endswith("s") and _sing(x) != x for x in target.split())
        target = " ".join(x for x in target.split() if x not in ("all", "every"))
        return {"do": "switch", "on": state, "target": target, "all": everything or plural}
    return None


def _strip_filler(s):
    return " ".join(x for x in norm(s).split() if x not in FILLER)


def _count_and_item(rest):
    words = norm(rest).split()
    n = parse_number(words)
    item = [x for x in words if not (x.isdigit() or x in NUMBER_WORDS or x in FILLER or
                                      x in ("from", "out", "into", "fridge", "inside", "more", "new",
                                            "bottle", "bottles", "can", "cans", "pack", "packs", "crate",
                                            "crates", "piece", "pieces", "dozen", "half", "today", "yesterday"))]
    return (n if n is not None else 1), " ".join(item)


def match_devices(devices, target):
    """Appliances that fit what was said: every word must fit the name, the
    room or the kind ("bedroom light", "light in the kitchen", "telly")."""
    q = [x for x in norm(target).split() if x not in FILLER]
    if not q:
        return []
    exact = [d for d in devices if norm(d["name"]) == " ".join(q) or d["id"].lower() == "_".join(q)]
    if exact:
        return exact

    def vocab(d):
        words = set(norm(d["name"]).split()) | set(d["id"].lower().replace("_", " ").split())
        words |= set(norm(d.get("room", "")).split()) | set(norm(d.get("kind") or "").split())
        return {_sing(x) for x in words}

    def fits(word, words):
        options = {_sing(word)} | {_sing(s) for s in SYNONYMS.get(word, [])} | {_sing(s) for s in
                                                                                SYNONYMS.get(_sing(word), [])}
        return any(any(v.startswith(o) or o.startswith(v) and len(v) >= 3 for v in words) for o in options)

    hits = [d for d in devices if all(fits(x, vocab(d)) for x in q)]
    if hits:
        return hits
    # a mishearing ("telivision", "fun" for "fan"): the closest word in every name
    allwords = sorted({x for d in devices for x in vocab(d)})
    fixed = []
    for x in q:
        close = get_close_matches(_sing(x), allwords, n=1, cutoff=0.75)
        fixed.append(close[0] if close else x)
    if fixed != q:
        return [d for d in devices if all(fits(x, vocab(d)) for x in fixed)]
    return []


def _hours(h):
    if h is None:
        return "unknown"
    if h >= 48:
        return f"{h / 24:.1f} days"
    m = int(round(h * 60))
    if m < 60:
        return f"{m} minutes"
    return f"{m // 60} hour{'s' if m // 60 != 1 else ''}" + (f" {m % 60} minutes" if m % 60 else "")


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


HELP = ("You can say things like: turn off the TV, switch on the bedroom light, all off, "
        "is there light, how many units are left, how long will the battery last, how many eggs are left, "
        "I took two eggs, arm the cameras, or what's the weather.")


# --------------------------------------------------------------- assistant --

class Assistant:
    """ask(text) → {"say": str, "heard": str, "photo": jpeg bytes or None, "did": [str]}.
    Thread-safe; the api does its own GUI-thread hops."""

    def __init__(self, api, settings_source, ai_settings_source=lambda: vision_ai.default_settings(),
                 clock=time.time):
        self.api = api
        self.settings = settings_source          # () -> assistant settings
        self.ai_settings = ai_settings_source    # () -> fridge AI settings (shared keys)
        self.clock = clock
        self._pin_fails = []
        self._pin_locked_until = 0
        self._lock = threading.Lock()
        self.last = None                          # last exchange, for the desktop panel

    def ask(self, text, who="assistant"):
        text = " ".join(str(text or "").split())[:MAX_TEXT]
        try:
            intent = parse(text)
            if intent is None:
                reply = self._smart(text, who)
            else:
                reply = self._do(intent, who)
        except Exception as e:                    # a failed action is still a spoken answer
            reply = {"say": f"Sorry, that didn't work: {e}"}
        reply.setdefault("photo", None)
        reply.setdefault("did", [])
        reply["heard"] = text
        self.last = reply
        return reply

    # ---- intents
    def _do(self, it, who):
        api, do = self.api, it["do"]
        if do == "help":
            return {"say": HELP}
        if do == "thanks":
            return {"say": "You're welcome."}
        if do == "hello":
            hour = datetime.now().hour
            part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
            return {"say": f"Good {part}. What should I do?"}
        if do == "time":
            now = datetime.now()
            return {"say": f"It's {now:%I:%M %p}".replace("s 0", "s ") + f", {now:%A} {now.day} {now:%B}."}
        if do in ("switch", "all_off", "all_on"):
            return self._switch(it, who)
        if do == "arm":
            if api.status()["security"]["armed"]:
                return {"say": "The cameras are already armed."}
            api.set_armed(True, who)
            return {"say": "Cameras armed. I'll alert you on motion.", "did": ["armed"]}
        if do == "disarm":
            return self._disarm(it.get("pin", ""), who)
        s = api.status() if do in ("status", "units", "grid", "battery", "load", "weather") else None
        if do == "status":
            return {"say": self._status_text(s)}
        if do == "units":
            m = s["meter"]
            if m["units_left"] is None:
                return {"say": "There's no meter reading yet. Type the units left on the meter in the app first."}
            extra = (f" That's about {_hours(m['days_left'] * 24)} at {m['kwh_per_day']:.1f} units a day."
                     if m["days_left"] else "")
            return {"say": f"{m['units_left']:.1f} units left on the meter.{extra}"}
        if do == "grid":
            g = s["grid"]
            if g["off_since"]:
                return {"say": f"No light. The grid has been off for {_hours((self.clock() - g['off_since']) / 3600)}."}
            if not g["watching"]:
                return {"say": "I'm not watching the grid yet. Turn on Grid watch in the app to track power cuts."}
            cuts = g.get("cuts_24h_h") or 0
            return {"say": "Yes, there's light. The grid is on." +
                    (f" It was off for {_hours(cuts)} in the last day." if cuts >= 0.05 else "")}
        if do == "battery":
            p = s["power"]
            run = (f" At the current load of {p['load_w']:,.0f} watts it would last {_hours(p['runtime_h'])}."
                   if p.get("runtime_h") else " Nothing is running, so there's no drain.")
            return {"say": f"The battery is at {p['battery_pct']:.0f} percent.{run}"}
        if do == "load":
            p = s["power"]
            on = [d["name"] for d in s["devices"] if d["on"]]
            top = sorted((d for d in s["devices"] if d["on"]), key=lambda d: -(d.get("live_w") or d["watts"]))[:2]
            biggest = f" The biggest are {_join(d['name'] for d in top)}." if len(on) > 2 else ""
            return {"say": f"The house is using {p['load_w']:,.0f} watts, about {s['currency']}{p['per_hour']:,.0f} "
                           f"an hour, with {len(on)} appliance{'s' if len(on) != 1 else ''} on.{biggest}"}
        if do == "weather":
            w = s.get("weather")
            if not w:
                return {"say": "I don't have the weather yet. Set your town on the Widget Screen weather card."}
            solar = f" Solar outlook today is {w['solar']}." if w.get("solar") else ""
            hi = f", high of {w['high']:.0f}" if w.get("high") is not None else ""
            return {"say": f"In {w['place']} it's {w['temp']:.0f} degrees and {str(w['desc']).lower()}{hi}.{solar}"}
        if do == "snapshot":
            jpeg = api.snapshot_jpeg(None)
            if not jpeg:
                return {"say": "There's no camera picture yet. Start a camera first."}
            cap = api.snapshot_caption() if hasattr(api, "snapshot_caption") else ""
            return {"say": f"Here's the latest picture{' from ' + cap.split(' · ')[0] if cap else ''}.", "photo": jpeg}
        if do.startswith("fridge"):
            return self._fridge(it, who)
        return {"say": "Sorry, I didn't get that."}

    def _switch(self, it, who):
        s = self.api.status()
        devices = s["devices"]
        if it["do"] == "all_off":
            if not any(d["on"] for d in devices if d.get("kind") != "fridge"):
                return {"say": "Everything is already off."}
            self.api.all_off(who)
            return {"say": "Done. Everything is off, except the fridge.", "did": ["all off"]}
        if it["do"] == "all_on":
            return {"say": "I won't switch everything on at once. Tell me which appliance."}
        want = it["on"]
        hits = match_devices(devices, it["target"])
        if not hits:
            return {"say": f"I couldn't find an appliance called {it['target'] or 'that'}."}
        if len(hits) > 1 and not it["all"] and sum(d["on"] != want for d in hits) == 1:
            hits = [d for d in hits if d["on"] != want]      # "turn off the light" when only one is on
        if len(hits) > 1 and not it["all"]:
            exact = [d for d in hits if norm(d["name"]).endswith(" ".join(norm(it["target"]).split()))]
            if len(exact) != 1:
                return {"say": f"Which one: {_join(d['name'] for d in hits[:5])}?"}
            hits = exact
        todo = [d for d in hits if d["on"] != want]
        if not todo:
            names = _join(d["name"] for d in hits)
            return {"say": f"{names} {'is' if len(hits) == 1 else 'are'} already {'on' if want else 'off'}."}
        for d in todo:
            self.api.toggle(d["id"], who)
        names = _join(d["name"] for d in todo)
        return {"say": f"{names} {'on' if want else 'off'}.", "did": [f"{d['name']} {'on' if want else 'off'}"
                                                                      for d in todo]}

    def _disarm(self, pin, who):
        st = self.settings()
        if not st.get("pin_hash"):
            return {"say": "For safety, disarming by voice needs a PIN. Set one in the assistant settings on the PC."}
        now = self.clock()
        with self._lock:
            if now < self._pin_locked_until:
                return {"say": f"Too many wrong PINs. Try again in {int((self._pin_locked_until - now) / 60) + 1} "
                               f"minutes, or disarm from the app."}
            if not pin:
                return {"say": "Say disarm and your PIN, for example: disarm 1 2 3 4."}
            if not secrets.compare_digest(_pin_hash(pin, st.get("pin_salt", "")), st["pin_hash"]):
                self._pin_fails = [t for t in self._pin_fails if now - t < PIN_LOCK_S] + [now]
                if len(self._pin_fails) >= PIN_TRIES:
                    self._pin_locked_until = now + PIN_LOCK_S
                    self._pin_fails = []
                return {"say": "That PIN is wrong."}
            self._pin_fails = []
        if not self.api.status()["security"]["armed"]:
            return {"say": "The cameras are already disarmed."}
        self.api.set_armed(False, who)
        return {"say": "Cameras disarmed.", "did": ["disarmed"]}

    def _fridge(self, it, who):
        api, do = self.api, it["do"]
        if do == "fridge_list":
            items = api.fridge()["items"]
            if not items:
                return {"say": "Nothing is tracked in the fridge yet."}
            parts = [f"{round(v['estimate'])} {v['name'].lower()}" for v in items]
            low = [v["name"].lower() for v in items if v["low"]]
            return {"say": f"In the fridge: {_join(parts)}." + (f" Running low on {_join(low)}." if low else "")}
        v = api.fridge_find(it["item"]) or api.fridge_find(_sing(it["item"]))
        if do == "fridge_count":
            if v is None:
                return {"say": f"I'm not tracking {it['item']} in the fridge."}
            n = round(v["estimate"])
            when = f" They'll run out in about {_hours(v['days_left'] * 24)}." if v.get("days_left") else ""
            return {"say": f"About {n} {v['name'].lower()} left.{when}" if v.get("rate") and
                    abs(v["estimate"] - v["count"]) >= 0.5 else f"{n} {v['name'].lower()} left.{when}"}
        if do == "fridge_took":
            if v is None:
                return {"say": f"I'm not tracking {it['item']} in the fridge."}
            r = api.fridge_adjust(v["id"], -it["n"], who)
            return {"say": f"Okay. {r['after']:g} {r['name'].lower()} left.", "did": [f"fridge {r['name']} -{it['n']}"]}
        if v is None:
            r = api.fridge_add(it["item"].capitalize(), it["n"], who)
            return {"say": f"Now tracking {r['name'].lower()}: {it['n']}.", "did": [f"fridge {r['name']} +{it['n']}"]}
        r = api.fridge_adjust(v["id"], it["n"], who)
        return {"say": f"Okay. {r['after']:g} {r['name'].lower()} now.", "did": [f"fridge {r['name']} +{it['n']}"]}

    def _status_text(self, s):
        p, g, m, sec = s["power"], s["grid"], s["meter"], s["security"]
        on = [d["name"] for d in s["devices"] if d["on"]]
        bits = [f"The house is using {p['load_w']:,.0f} watts."]
        bits.append(f"On: {_join(on)}." if on else "Nothing is on.")
        if g["off_since"]:
            bits.append(f"The grid is off, for {_hours((self.clock() - g['off_since']) / 3600)}.")
        elif g["watching"]:
            bits.append("The grid is on.")
        bits.append(f"Battery {p['battery_pct']:.0f} percent.")
        if m["units_left"] is not None:
            bits.append(f"{m['units_left']:.0f} units on the meter.")
        bits.append("Cameras armed." if sec["armed"] else "Cameras disarmed.")
        return " ".join(bits)

    # ---- smart answers
    def _smart(self, text, who):
        st = self.settings()
        pid = st.get("ai") or "none"
        if pid == "none":
            return {"say": "Sorry, I didn't understand that. " + HELP}
        try:
            answer = ask_ai(st, self.ai_settings(), pid, text, self._context())
        except vision_ai.VisionError as e:
            return {"say": f"I didn't understand that, and the AI couldn't help: {e}"}
        did = []
        status = None
        for a in answer["actions"][:6]:
            act = a.get("do")
            try:
                if act in ("on", "off"):
                    status = status or self.api.status()
                    dev = next((d for d in status["devices"] if d["id"] == a.get("target")), None)
                    if dev is None:
                        hits = match_devices(status["devices"], a.get("target", ""))
                        dev = hits[0] if len(hits) == 1 else None
                    if dev is not None and dev["on"] != (act == "on"):
                        self.api.toggle(dev["id"], who)
                        did.append(f"{dev['name']} {act}")
                elif act == "all_off":
                    self.api.all_off(who)
                    did.append("all off")
                elif act == "arm":
                    self.api.set_armed(True, who)
                    did.append("armed")
                elif act in ("took", "add"):
                    v = self.api.fridge_find(a.get("target", ""))
                    n = max(1, min(50, int(a.get("count") or 1)))
                    if v is not None:
                        self.api.fridge_adjust(v["id"], -n if act == "took" else n, who)
                        did.append(f"fridge {v['name']} {'-' if act == 'took' else '+'}{n}")
            except Exception:
                continue
        return {"say": answer["say"] or ("Done." if did else "Okay."), "did": did}

    def _context(self):
        s = self.api.status()
        p, g, m = s["power"], s["grid"], s["meter"]
        try:
            fridge = [{"name": v["name"], "count": round(v["estimate"]), "days_left": v["days_left"]}
                      for v in self.api.fridge()["items"]]
        except Exception:
            fridge = []
        w = s.get("weather") or {}
        return {
            "time": s["time"], "currency": s["currency"],
            "appliances": [{"id": d["id"], "name": d["name"], "room": d["room"], "on": d["on"],
                            "watts": d.get("live_w") or d["watts"]} for d in s["devices"]],
            "load_w": round(p["load_w"]), "inverter_w": p["inverter_w"], "battery_pct": p["battery_pct"],
            "battery_runtime_h": round(p["runtime_h"], 1) if p.get("runtime_h") else None,
            "cost_per_hour": round(p["per_hour"]), "power_source": p["source"],
            "grid_on": None if not g["watching"] else not g["off_since"],
            "meter_units_left": m["units_left"], "meter_days_left": m["days_left"],
            "cameras_armed": s["security"]["armed"], "fridge": fridge,
            "weather": {k: w.get(k) for k in ("place", "temp", "desc", "high", "low", "solar")} if w else None,
        }


# --------------------------------------------------------------- smart AI --

AI_PROMPT = """You are CYPHER-X, the voice assistant of a home in Nigeria. You can see the home's live state
and you can act on it. Reply in one or two short, friendly spoken sentences (no lists, no markdown, no emojis).
Allowed actions: "on"/"off" an appliance (target = its id), "all_off", "arm" the cameras,
"took"/"add" a fridge item (target = item name, count). You cannot disarm the cameras; tell the user to say
"disarm" with their PIN. Only act when the user asks for it or clearly implies it ("it's hot" → the fan on).
Answer only with JSON: {"say": "...", "actions": [{"do": "off", "target": "tv", "count": 1}]}"""

AI_SCHEMA = {
    "type": "object",
    "properties": {
        "say": {"type": "string"},
        "actions": {"type": "array", "items": {
            "type": "object",
            "properties": {"do": {"type": "string", "enum": ["on", "off", "all_off", "arm", "took", "add"]},
                           "target": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["do", "target", "count"], "additionalProperties": False}},
    },
    "required": ["say", "actions"],
    "additionalProperties": False,
}


def ai_config(settings, ai_settings, pid):
    """The provider with the shared key (from the fridge AI settings) and the assistant's own model."""
    cfg = vision_ai.provider_config(ai_settings, pid)
    cfg["model"] = (str((settings.get("models") or {}).get(pid) or "").strip() or AI_MODELS.get(pid) or cfg["model"])
    return cfg


def ai_ready(settings, ai_settings, pid=None):
    pid = pid or settings.get("ai") or "none"
    if pid == "none":
        return False, "Off — only the built-in commands are understood."
    try:
        cfg = ai_config(settings, ai_settings, pid)
    except vision_ai.VisionError as e:
        return False, str(e)
    if cfg["key"] and not cfg["api_key"]:
        return False, f"{cfg['title']} needs an API key (get one at {cfg['signup']})."
    if not cfg["model"]:
        return False, f"Choose a model for {cfg['title']}."
    return True, ""


def parse_ai_reply(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.I)
    try:
        data = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return {"say": t[:400], "actions": []}       # plain words are still an answer
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return {"say": t[:400], "actions": []}
    if not isinstance(data, dict):
        return {"say": "", "actions": []}
    actions = [a for a in (data.get("actions") or []) if isinstance(a, dict)]
    return {"say": str(data.get("say") or "").strip()[:600], "actions": actions}


def ask_ai(settings, ai_settings, pid, text, context, timeout=None):
    ok, why = ai_ready(settings, ai_settings, pid)
    if not ok:
        raise vision_ai.VisionError(why)
    cfg = ai_config(settings, ai_settings, pid)
    user = f"Home right now:\n{json.dumps(context, separators=(',', ':'))}\n\nThe user said: \"{text}\""
    timeout = timeout or (120 if cfg["kind"] == "ollama" else 40)
    return parse_ai_reply(_CALLERS[cfg["kind"]](cfg, user, timeout))


def _gemini_text(cfg, user, timeout):
    url = f"{cfg['url'].rstrip('/')}/models/{cfg['model']}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": AI_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.3}}
    res = vision_ai._post(url, body, {"x-goog-api-key": cfg["api_key"]}, timeout)
    try:
        return "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise vision_ai.VisionError("Gemini gave no answer")


def _openai_text(cfg, user, timeout):
    headers = {"X-Title": "CYPHER-X"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = {"model": cfg["model"], "temperature": 0.3, "max_tokens": 500,
            "messages": [{"role": "system", "content": AI_PROMPT}, {"role": "user", "content": user}]}
    res = vision_ai._post(cfg["url"].rstrip("/") + "/chat/completions", body, headers, timeout)
    try:
        return res["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise vision_ai.VisionError("The AI gave no answer")


def _ollama_text(cfg, user, timeout):
    body = {"model": cfg["model"], "stream": False, "format": "json", "options": {"temperature": 0.3},
            "messages": [{"role": "system", "content": AI_PROMPT}, {"role": "user", "content": user}]}
    try:
        res = vision_ai._post(cfg["url"].rstrip("/") + "/api/chat", body, {}, timeout)
    except vision_ai.VisionError as e:
        if "Can't reach" in str(e):
            raise vision_ai.VisionError(f"Ollama isn't running on this PC. Install it from ollama.com, then run "
                                        f"'ollama pull {cfg['model']}'.")
        raise
    if res.get("error"):
        raise vision_ai.VisionError(f"Ollama: {res['error']}")
    return (res.get("message") or {}).get("content", "")


def _claude_text(cfg, user, timeout):
    try:
        import anthropic
    except ImportError:
        raise vision_ai.VisionError("Install the Claude package first:  pip install anthropic")
    client = anthropic.Anthropic(api_key=cfg["api_key"], timeout=timeout, max_retries=1)
    try:
        resp = client.beta.messages.create(
            model=cfg["model"],
            max_tokens=2000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                      # a policy decline is retried on Anthropic's default fallback
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": AI_SCHEMA}},
            system=AI_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        raise vision_ai.VisionError("The Claude API key was refused")
    except anthropic.PermissionDeniedError:
        raise vision_ai.VisionError("This Claude API key can't use that model")
    except anthropic.NotFoundError:
        raise vision_ai.VisionError(f"Claude model '{cfg['model']}' not found")
    except anthropic.RateLimitError:
        raise vision_ai.VisionError("Claude rate limit reached — try again in a minute")
    except anthropic.APIStatusError as e:
        raise vision_ai.VisionError(f"Claude said {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise vision_ai.VisionError("Can't reach the Claude API — check the internet connection")
    if resp.stop_reason == "refusal":
        raise vision_ai.VisionError("Claude declined to answer that")
    return "".join(b.text for b in resp.content if b.type == "text")


_CALLERS = {"gemini": _gemini_text, "openai": _openai_text, "ollama": _ollama_text, "anthropic": _claude_text}
