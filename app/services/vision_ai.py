"""
Count what's in a fridge photo with an AI vision model — several providers,
free ones included, all optional:

  gemini      Google Gemini              free tier with a key from aistudio.google.com
  openrouter  OpenRouter                 free vision models (":free"), OpenAI-style API
  groq        Groq                       free tier, OpenAI-style API
  ollama      Ollama on this PC          free and offline; needs a vision model pulled
  claude      Claude (Anthropic)         paid, the most accurate; official `anthropic` SDK
  openai      OpenAI                     paid
  custom      any OpenAI-compatible server (LM Studio, vLLM, …)
  none        no AI — the photo is kept and you count by hand

Settings (provider, keys, models, a backup provider) are one JSON value in the
app database ("fridge_ai"). A free tier that hits its limit can fall back to the
backup provider. Standard library HTTP for everything except Claude.
"""
import base64
import json
import re
import urllib.error
import urllib.request

SETTING_KEY = "fridge_ai"
MAX_SIDE = 1600             # longer photo side sent to the AI: enough to count eggs, fewer tokens
MAX_COUNT = 500

PROVIDERS = {
    "gemini": {"title": "Google Gemini", "tag": "free tier", "kind": "gemini",
               "url": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash",
               "key": True, "signup": "https://aistudio.google.com/apikey"},
    "openrouter": {"title": "OpenRouter", "tag": "free models", "kind": "openai",
                   "url": "https://openrouter.ai/api/v1", "model": "google/gemma-3-27b-it:free",
                   "key": True, "signup": "https://openrouter.ai/keys"},
    "groq": {"title": "Groq", "tag": "free tier", "kind": "openai",
             "url": "https://api.groq.com/openai/v1", "model": "meta-llama/llama-4-scout-17b-16e-instruct",
             "key": True, "signup": "https://console.groq.com/keys"},
    "ollama": {"title": "Ollama on this PC", "tag": "free, offline", "kind": "ollama",
               "url": "http://localhost:11434", "model": "qwen2.5vl:7b",
               "key": False, "signup": "https://ollama.com/download"},
    "claude": {"title": "Claude (Anthropic)", "tag": "paid, most accurate", "kind": "anthropic",
               "url": "", "model": "claude-opus-5-5",
               "key": True, "signup": "https://console.anthropic.com/settings/keys"},
    "openai": {"title": "OpenAI", "tag": "paid", "kind": "openai",
               "url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
               "key": True, "signup": "https://platform.openai.com/api-keys"},
    "custom": {"title": "Other OpenAI-compatible server", "tag": "LM Studio, vLLM…", "kind": "openai",
               "url": "http://localhost:1234/v1", "model": "",
               "key": False, "signup": ""},
    "none": {"title": "No AI — count by hand", "tag": "", "kind": "none", "url": "", "model": "",
             "key": False, "signup": ""},
}
FREE = ("gemini", "openrouter", "groq", "ollama")

PROMPT = """This is a photo of the inside of a home fridge (or a shelf, tray or crate of food).
Count each kind of food or drink you can actually see.
- Count single units: each egg, each bottle, each can — not crates or packs.
- Use these names when they fit: {known}. Use short plain names for anything else (e.g. "Malt", "Water", "Tomatoes").
- If one of those named items is clearly not there, give it count 0. If you can't see that part of the fridge, leave it out.
- Don't guess hidden things.
Answer only with JSON, no other text:
{{"items": [{{"name": "Eggs", "count": 7}}], "note": "one short line about anything you weren't sure of, or empty"}}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["name", "count"], "additionalProperties": False}},
        "note": {"type": "string"},
    },
    "required": ["items", "note"],
    "additionalProperties": False,
}


class VisionError(Exception):
    pass


# ----------------------------------------------------------------- settings --

def default_settings():
    return {"provider": "none", "fallback": "", "providers": {}}


def load_settings(db):
    s = default_settings()
    stored = db.get_setting(SETTING_KEY, None) if db is not None else None
    if isinstance(stored, dict):
        s.update({k: v for k, v in stored.items() if k in s})
    return s


def save_settings(db, settings):
    db.set_setting(SETTING_KEY, settings)


def provider_config(settings, pid):
    """Defaults for pid overlaid with what the user saved (key, model, url)."""
    base = PROVIDERS.get(pid)
    if base is None:
        raise VisionError(f"Unknown AI provider '{pid}'")
    mine = (settings.get("providers") or {}).get(pid) or {}
    cfg = dict(base)
    for k in ("key", "model", "url"):
        v = (mine.get(k) or "").strip() if isinstance(mine.get(k), str) else ""
        if k == "key":
            cfg["api_key"] = v
        elif v:
            cfg[k] = v
    return cfg


def ready(settings, pid=None):
    """(ok, why not) — enough configured to try this provider?"""
    pid = pid or settings.get("provider") or "none"
    if pid == "none":
        return False, "No AI chosen — photos are saved and you count by hand."
    try:
        cfg = provider_config(settings, pid)
    except VisionError as e:
        return False, str(e)
    if cfg["key"] and not cfg["api_key"]:
        return False, f"{cfg['title']} needs an API key (get one at {cfg['signup']})."
    if not cfg["model"]:
        return False, f"Choose a model for {cfg['title']}."
    return True, ""


def label(pid):
    p = PROVIDERS.get(pid)
    if not p:
        return pid
    return f"{p['title']} ({p['tag']})" if p["tag"] else p["title"]


# ------------------------------------------------------------------- images --

def prepare_jpeg(data, max_side=MAX_SIDE):
    """Any image bytes → a JPEG no larger than max_side (keeps the original if Qt can't read it)."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage
    except ImportError:  # pragma: no cover
        return data
    img = QImage.fromData(data)
    if img.isNull():
        raise VisionError("That file isn't a picture I can read")
    if max(img.width(), img.height()) > max_side:
        img = img.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPG", 85)
    return bytes(ba)


# ------------------------------------------------------------------ parsing --

def parse_answer(text):
    """The model's reply → ([(name, count)], note). Tolerates ```json fences and extra words."""
    if not isinstance(text, str) or not text.strip():
        raise VisionError("The AI gave an empty answer")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        data = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise VisionError("The AI didn't answer with a list of items")
        try:
            data = json.loads(m.group(0))
        except ValueError:
            raise VisionError("The AI's answer wasn't valid JSON")
    if isinstance(data, list):
        data = {"items": data}
    rows = data.get("items") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise VisionError("The AI didn't answer with a list of items")
    merged = {}
    order = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = " ".join(str(r.get("name") or "").split())[:40]
        try:
            count = int(round(float(r.get("count"))))
        except (TypeError, ValueError):
            continue
        if not name or count < 0:
            continue
        key = name.lower()
        if key not in merged:
            order.append(key)
            merged[key] = [name, 0]
        merged[key][1] = min(MAX_COUNT, merged[key][1] + count)
    note = str(data.get("note") or "").strip()[:300] if isinstance(data, dict) else ""
    return [tuple(merged[k]) for k in order], note


# ---------------------------------------------------------------- providers --

def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace"))
            detail = detail.get("error", detail)
            if isinstance(detail, dict):
                detail = detail.get("message") or json.dumps(detail)[:200]
        except Exception:
            detail = e.reason
        raise VisionError(_http_hint(e.code, str(detail)[:300]))
    except urllib.error.URLError as e:
        raise VisionError(f"Can't reach {urllib.request.urlparse(url).netloc}: {e.reason}")
    except (OSError, ValueError) as e:
        raise VisionError(f"Request failed: {e}")


def _http_hint(code, detail):
    if code in (401, 403):
        return f"The API key was refused ({detail})"
    if code == 429:
        return f"Free limit or rate limit reached — try later, or set a backup provider ({detail})"
    if code == 404:
        return f"Model or address not found — check the model name ({detail})"
    return f"The AI service said {code}: {detail}"


def _gemini(cfg, b64, prompt, timeout):
    url = f"{cfg['url'].rstrip('/')}/models/{cfg['model']}:generateContent"
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                                    {"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0}}
    res = _post(url, body, {"x-goog-api-key": cfg["api_key"]}, timeout)
    try:
        parts = res["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        reason = (res.get("promptFeedback") or {}).get("blockReason") if isinstance(res, dict) else None
        raise VisionError(f"Gemini gave no answer{f' ({reason})' if reason else ''}")
    return "".join(p.get("text", "") for p in parts)


def _openai(cfg, b64, prompt, timeout):
    url = cfg["url"].rstrip("/") + "/chat/completions"
    headers = {"X-Title": "CYPHER-X"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = {"model": cfg["model"], "temperature": 0, "max_tokens": 1000,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
    res = _post(url, body, headers, timeout)
    try:
        content = res["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise VisionError("The AI gave no answer")
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content


def _ollama(cfg, b64, prompt, timeout):
    url = cfg["url"].rstrip("/") + "/api/chat"
    body = {"model": cfg["model"], "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, "images": [b64]}]}
    try:
        res = _post(url, body, {}, timeout)
    except VisionError as e:
        if "Can't reach" in str(e):
            raise VisionError(f"Ollama isn't running on this PC. Install it from ollama.com, then run "
                              f"'ollama pull {cfg['model']}'.")
        raise
    if res.get("error"):
        raise VisionError(f"Ollama: {res['error']}")
    return (res.get("message") or {}).get("content", "")


def _claude(cfg, b64, prompt, timeout):
    try:
        import anthropic
    except ImportError:
        raise VisionError("Install the Claude package first:  pip install anthropic")
    client = anthropic.Anthropic(api_key=cfg["api_key"], timeout=timeout, max_retries=1)
    try:
        resp = client.beta.messages.create(
            model=cfg["model"],
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                      # a policy decline is retried on Anthropic's default fallback
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt}]}],
        )
    except anthropic.AuthenticationError:
        raise VisionError("The Claude API key was refused")
    except anthropic.PermissionDeniedError:
        raise VisionError("This Claude API key can't use that model")
    except anthropic.NotFoundError:
        raise VisionError(f"Claude model '{cfg['model']}' not found")
    except anthropic.RateLimitError:
        raise VisionError("Claude rate limit reached — try again in a minute")
    except anthropic.APIStatusError as e:
        raise VisionError(f"Claude said {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise VisionError("Can't reach the Claude API — check the internet connection")
    if resp.stop_reason == "refusal":
        raise VisionError("Claude declined to read this photo")
    return "".join(b.text for b in resp.content if b.type == "text")


CALLERS = {"gemini": _gemini, "openai": _openai, "ollama": _ollama, "anthropic": _claude}


def count_with(settings, pid, jpeg, known_names=(), timeout=None):
    """One provider. Returns (items, note). jpeg should already be prepared."""
    ok, why = ready(settings, pid)
    if not ok:
        raise VisionError(why)
    cfg = provider_config(settings, pid)
    known = ", ".join(sorted(set(known_names))) or "(none yet)"
    prompt = PROMPT.format(known=known)
    b64 = base64.b64encode(jpeg).decode("ascii")
    timeout = timeout or (240 if cfg["kind"] == "ollama" else 90)
    text = CALLERS[cfg["kind"]](cfg, b64, prompt, timeout)
    return parse_answer(text)


def count_items(settings, jpeg, known_names=()):
    """The chosen provider, then the backup one if the first fails.
    Returns {"items", "note", "provider", "errors"}; raises VisionError if every one failed."""
    order = [settings.get("provider") or "none"]
    if settings.get("fallback") and settings["fallback"] not in order and settings["fallback"] != "none":
        order.append(settings["fallback"])
    errors = []
    for pid in order:
        if pid == "none":
            continue
        try:
            items, note = count_with(settings, pid, jpeg, known_names)
            return {"items": items, "note": note, "provider": pid, "errors": errors}
        except VisionError as e:
            errors.append(f"{PROVIDERS.get(pid, {}).get('title', pid)}: {e}")
    if not errors:
        raise VisionError("No AI chosen — count by hand, or pick an AI in Fridge → AI settings.")
    raise VisionError(" · ".join(errors))
