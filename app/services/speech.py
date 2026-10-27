"""
Speech to text for the assistant, and the small pieces of audio handling around it.

Engines (chosen in Assistant settings):
  local   Whisper on this PC (faster-whisper) — free, offline, private.
          pip install faster-whisper ; the model (75–500 MB) downloads once on first use.
  groq    Groq's hosted Whisper — free tier, very fast; uses the Groq key from the AI settings.
  openai  OpenAI transcription — paid.

Audio comes in two shapes:
  • Pcm(bytes, rate): 16-bit mono samples from the PC microphone
  • bytes of a file: a phone recording (webm / ogg / mp4) or a Telegram voice note (ogg)

Segmenter turns a live microphone stream into utterances (speech between pauses),
which is what push-to-talk and the wake phrase listener both need. Pure Python.
"""
import io
import json
import math
import os
import threading
import urllib.error
import urllib.request
import uuid
import wave
from array import array
from collections import namedtuple

from app.services import vision_ai

Pcm = namedtuple("Pcm", "data rate")
RATE = 16000

ENGINES = {
    "local": {"title": "Offline on this PC (Whisper)", "tag": "free, private"},
    "groq": {"title": "Groq Whisper", "tag": "free tier, fastest", "url": "https://api.groq.com/openai/v1",
             "model": "whisper-large-v3-turbo", "key_from": "groq"},
    "openai": {"title": "OpenAI", "tag": "paid", "url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini-transcribe", "key_from": "openai"},
}
LOCAL_MODELS = {
    "tiny.en": "Tiny — fastest, least accurate (75 MB)",
    "base.en": "Base — recommended (145 MB)",
    "small.en": "Small — most accurate, slower (480 MB)",
    "small": "Small, any language (480 MB)",
}
MODEL_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cyberops"), "CyberOps", "whisper")
MAX_UPLOAD = 2 * 1024 * 1024


class SpeechError(Exception):
    pass


# ----------------------------------------------------------------- engines --

def local_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def stt_ready(settings, ai_settings):
    """(ok, why not) for the chosen engine."""
    eng = settings.get("stt") or "local"
    if eng == "local":
        if not local_available():
            return False, "Install the offline speech engine:  pip install faster-whisper"
        return True, ""
    e = ENGINES.get(eng)
    if e is None:
        return False, f"Unknown speech engine '{eng}'"
    key = _key(ai_settings, e["key_from"])
    if not key:
        return False, f"{e['title']} needs the {vision_ai.PROVIDERS[e['key_from']]['title']} API key " \
                      f"(get one at {vision_ai.PROVIDERS[e['key_from']]['signup']})."
    return True, ""


def _key(ai_settings, pid):
    try:
        return vision_ai.provider_config(ai_settings, pid).get("api_key", "")
    except vision_ai.VisionError:
        return ""


_models = {}
_model_lock = threading.Lock()


def _local_model(name, factory=None):
    with _model_lock:
        if name not in _models:
            if factory is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError:
                    raise SpeechError("Install the offline speech engine:  pip install faster-whisper")
                os.makedirs(MODEL_DIR, exist_ok=True)

                def factory(n):
                    return WhisperModel(n, device="cpu", compute_type="int8", download_root=MODEL_DIR)
            try:
                _models[name] = factory(name)
            except SpeechError:
                raise
            except Exception as e:
                raise SpeechError(f"Couldn't load the Whisper '{name}' model ({e}). The first use needs "
                                  f"internet to download it.")
        return _models[name]


def transcribe(audio, settings, ai_settings, prompt="", model_factory=None, post=None):
    """Pcm or file bytes → text ('' when nothing was said)."""
    eng = settings.get("stt") or "local"
    ok, why = stt_ready(settings, ai_settings) if model_factory is None else (True, "")
    if not ok:
        raise SpeechError(why)
    if eng == "local":
        return _transcribe_local(audio, settings.get("stt_model") or "base.en", prompt, settings, model_factory)
    e = ENGINES[eng]
    data, name, ctype = (pcm_to_wav(audio), "speech.wav", "audio/wav") if isinstance(audio, Pcm) else \
        (bytes(audio), *_file_name(audio))
    return _transcribe_cloud(e, _key(ai_settings, e["key_from"]), data, name, ctype, prompt,
                             settings.get("lang") or "en", post or _post_multipart)


def _transcribe_local(audio, model_name, prompt, settings, factory):
    model = _local_model(model_name, factory)
    if isinstance(audio, Pcm):
        try:
            import numpy as np
        except ImportError:
            raise SpeechError("numpy is missing (it comes with faster-whisper)")
        samples = np.frombuffer(audio.data, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.rate != RATE:
            samples = _resample(samples, audio.rate, RATE)
        src = samples
    else:
        src = decode_file(audio)
    lang = None if model_name.endswith(".en") else ((settings.get("lang") or "en")[:2] or None)
    try:
        segments, _info = model.transcribe(src, language=lang, beam_size=1, initial_prompt=prompt or None,
                                           condition_on_previous_text=False, vad_filter=False)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        raise SpeechError(f"Whisper failed: {e}")


def decode_file(data):
    """A recording (ogg / webm / mp4 / wav…) → float32 samples at 16 kHz mono.
    Uses PyAV directly (it comes with faster-whisper), which works across PyAV versions."""
    try:
        import av
        import numpy as np
    except ImportError:
        raise SpeechError("Install the offline speech engine:  pip install faster-whisper")
    out = []
    try:
        with av.open(io.BytesIO(bytes(data)), mode="r") as container:
            stream = next((st for st in container.streams if st.type == "audio"), None)
            if stream is None:
                raise SpeechError("That recording has no sound in it")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
            for frame in container.decode(stream):
                for f in resampler.resample(frame) or []:
                    out.append(f.to_ndarray().reshape(-1))
            for f in resampler.resample(None) or []:
                out.append(f.to_ndarray().reshape(-1))
    except SpeechError:
        raise
    except Exception as e:
        raise SpeechError(f"That recording couldn't be read ({type(e).__name__})")
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0


def _resample(x, src, dst):
    import numpy as np
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _file_name(data):
    head = bytes(data[:12])
    if head.startswith(b"OggS"):
        return "speech.ogg", "audio/ogg"
    if head.startswith(b"RIFF"):
        return "speech.wav", "audio/wav"
    if head[4:8] == b"ftyp":
        return "speech.m4a", "audio/mp4"
    if head.startswith(b"ID3") or head[:2] == b"\xff\xfb":
        return "speech.mp3", "audio/mpeg"
    return "speech.webm", "audio/webm"


def _post_multipart(url, fields, file_field, timeout=60):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    name, ctype, data, headers = file_field
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                 f'Content-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
            detail = detail.get("message") if isinstance(detail, dict) else detail
        except Exception:
            detail = e.reason
        raise SpeechError(vision_ai._http_hint(e.code, str(detail)[:200]))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SpeechError(f"Can't reach the speech service: {getattr(e, 'reason', e)}")


def _transcribe_cloud(e, key, data, name, ctype, prompt, lang, post):
    if len(data) > MAX_UPLOAD * 4:
        raise SpeechError("That recording is too long")
    fields = {"model": e["model"], "response_format": "json", "language": lang[:2]}
    if prompt:
        fields["prompt"] = prompt[:400]
    res = post(e["url"] + "/audio/transcriptions", fields, (name, ctype, data, {"Authorization": f"Bearer {key}"}))
    return str(res.get("text") or "").strip()


def vocabulary_prompt(device_names, wake_phrase=""):
    """Whisper spells names better when it has seen them: give it the house's words."""
    names = ", ".join(sorted(set(device_names))[:40])
    lead = f"{wake_phrase}. " if wake_phrase else ""
    return f"{lead}Home commands: turn off the TV, switch on the light, all off, is there light, units, " \
           f"battery, fridge, eggs, disarm. Appliances: {names}."


# ------------------------------------------------------------------- audio --

def pcm_to_wav(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(pcm.rate)
        w.writeframes(pcm.data)
    return buf.getvalue()


def level(chunk):
    """RMS of 16-bit samples, 0..1."""
    a = array("h")
    a.frombytes(chunk[: len(chunk) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(s * s for s in a) / len(a)) / 32768.0


class Segmenter:
    """Cuts a live 16-bit mono stream into utterances.

    Speech starts when the level rises well above the room's background noise
    (learned as it listens) and ends after `silence_s` of quiet. A short pre-roll
    keeps the first syllable. feed() returns a finished utterance (bytes) or None.
    """

    def __init__(self, rate=RATE, silence_s=0.7, max_s=8.0, min_s=0.35, pre_s=0.3, min_level=0.012):
        self.rate = rate
        self.silence_s, self.max_s, self.min_s, self.pre_s = silence_s, max_s, min_s, pre_s
        self.min_level = min_level
        self.noise = min_level / 2
        self.reset()

    def reset(self):
        self.buf = bytearray()
        self.pre = bytearray()
        self.speaking = False
        self.quiet = 0.0
        self.voiced = 0.0

    @property
    def threshold(self):
        return max(self.min_level, self.noise * 3.0)

    def feed(self, chunk):
        secs = len(chunk) / 2 / self.rate
        lv = level(chunk)
        if not self.speaking:
            if lv > self.threshold:
                self.speaking = True
                self.buf = bytearray(self.pre) + bytearray(chunk)
                self.quiet, self.voiced = 0.0, secs
                return None
            self.noise = self.noise * 0.95 + lv * 0.05          # slow: the room's background
            self.pre += chunk
            keep = int(self.pre_s * self.rate) * 2
            if len(self.pre) > keep:
                del self.pre[:len(self.pre) - keep]
            return None
        self.buf += chunk
        if lv > self.threshold * 0.6:
            self.quiet = 0.0
            self.voiced += secs
        else:
            self.quiet += secs
        length = len(self.buf) / 2 / self.rate
        if self.quiet >= self.silence_s or length >= self.max_s:
            out, voiced = bytes(self.buf), self.voiced
            self.reset()
            return out if voiced >= self.min_s else None
        return None
