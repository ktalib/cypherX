"""
Talk to CYPHER-X on the PC: a floating assistant panel, push-to-talk (the mic
button in the top bar or Ctrl+Space), an optional wake phrase the user picks,
and spoken replies through the system voice (Qt Text-to-Speech: SAPI / WinRT
on Windows, nothing to install).

The heavy work (speech to text, the assistant, the home API) runs on a worker
thread; results come back to the GUI thread through Qt signals.
"""
import re
import threading

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QEvent, QRectF
from PySide6.QtGui import QPainter, QColor, QPixmap, QImage
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QWidget,
                               QScrollArea, QDialog, QComboBox, QCheckBox, QFormLayout, QDialogButtonBox,
                               QSlider, QMessageBox, QStackedWidget)

from app.database import Database
from app.icons import get_icon
from app.services import assistant as core, speech, vision_ai
from app.views.home_ui import (ACCENT, ACCENT_HI, ON_ACCENT, TEXT, SOFT, MUTED, DIM, GOOD, CRIT, Segmented,
                               apply_home_style)

WHO = "Voice (PC)"
LISTEN_TIMEOUT_MS = 7000
SUGGESTIONS = ("Is there light?", "What's on?", "Units left", "All off")
PANEL_BG = "#181614"


# --------------------------------------------------------------- microphone --

class MicListener(QObject):
    """The default microphone as 16 kHz mono 16-bit chunks, cut into utterances.
    mode "once": the first utterance, then stop. mode "wake": keep listening."""
    level = Signal(float)
    utterance = Signal(bytes)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.src = None
        self.dev = None
        self.mode = None
        self.paused = False
        self.seg = speech.Segmenter()
        self._fmt = None
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._give_up)

    @property
    def active(self):
        return self.src is not None

    def start(self, mode="once"):
        self.stop(quiet=True)
        try:
            from PySide6.QtMultimedia import QAudioSource, QAudioFormat, QMediaDevices
        except ImportError:
            self.failed.emit("Qt Multimedia is missing, so the microphone can't be used.")
            return False
        dev = QMediaDevices.defaultAudioInput()
        if dev.isNull():
            self.failed.emit("No microphone found. Plug one in, or check Windows privacy settings → Microphone.")
            return False
        fmt = QAudioFormat()
        fmt.setSampleRate(speech.RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if not dev.isFormatSupported(fmt):
            fmt = dev.preferredFormat()
        self._fmt = fmt
        self.mode = mode
        self.paused = False
        self.seg = speech.Segmenter(max_s=8.0 if mode == "once" else 6.0)
        self.src = QAudioSource(dev, fmt, self)
        self.dev = self.src.start()
        if self.dev is None:
            self.src = None
            self.failed.emit("The microphone couldn't be opened (is another app using it?).")
            return False
        self.dev.readyRead.connect(self._read)
        if mode == "once":
            self._deadline.start(LISTEN_TIMEOUT_MS)
        return True

    def stop(self, quiet=False):
        self._deadline.stop()
        if self.src is not None:
            try:
                self.src.stop()
            except RuntimeError:
                pass
            self.src.deleteLater()
            self.src = None
            self.dev = None
            if not quiet:
                self.stopped.emit()

    def _give_up(self):
        if self.mode == "once" and not self.seg.speaking:
            self.stop()
        elif self.mode == "once":
            self._deadline.start(3000)          # still talking: let the segmenter finish it

    def _read(self):
        if self.dev is None:
            return
        data = bytes(self.dev.readAll())
        if not data or self.paused:
            return
        data = _to_mono16k(data, self._fmt)
        self.level.emit(min(1.0, speech.level(data) * 12))
        out = self.seg.feed(data)
        if out:
            if self.mode == "once":
                self.stop(quiet=True)
            self.utterance.emit(out)
            if self.mode == "once":
                self.stopped.emit()


def _to_mono16k(data, fmt):
    """Whatever the sound card gives → 16 kHz mono int16."""
    from PySide6.QtMultimedia import QAudioFormat
    if fmt.sampleRate() == speech.RATE and fmt.channelCount() == 1 and fmt.sampleFormat() == QAudioFormat.Int16:
        return data
    try:
        import numpy as np
    except ImportError:
        return data if fmt.sampleFormat() == QAudioFormat.Int16 else b""
    kind = {QAudioFormat.Int16: np.int16, QAudioFormat.Int32: np.int32, QAudioFormat.Float: np.float32,
            QAudioFormat.UInt8: np.uint8}.get(fmt.sampleFormat(), np.int16)
    x = np.frombuffer(data[: len(data) // np.dtype(kind).itemsize * np.dtype(kind).itemsize], dtype=kind)
    x = x.astype(np.float32)
    if kind == np.int16:
        x /= 32768.0
    elif kind == np.int32:
        x /= 2147483648.0
    elif kind == np.uint8:
        x = (x - 128.0) / 128.0
    ch = max(1, fmt.channelCount())
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    if fmt.sampleRate() != speech.RATE and len(x):
        n = int(len(x) * speech.RATE / fmt.sampleRate())
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


# ------------------------------------------------------------- controller --

class VoiceController(QObject):
    """Push-to-talk, the wake phrase, typed questions and spoken replies."""
    state = Signal(str)            # idle | listening | thinking | speaking | wake
    heard = Signal(str)
    answered = Signal(object)      # reply dict from Assistant.ask
    note = Signal(str)             # a problem worth showing in the panel
    level = Signal(float)
    _done = Signal(object)         # from the worker thread

    def __init__(self, assistant, home_api, parent=None):
        super().__init__(parent)
        self.assistant = assistant
        self.api = home_api
        self.db = Database.get_instance()
        self.settings = core.load_settings(self.db)
        self.mic = MicListener(self)
        self.mic.level.connect(self.level)
        self.mic.utterance.connect(self._on_utterance)
        self.mic.failed.connect(self._mic_failed)
        self.mic.stopped.connect(self._mic_stopped)
        self.wake = MicListener(self)
        self.wake.utterance.connect(self._on_wake_utterance)
        self.wake.failed.connect(lambda m: self.note.emit(f"Wake phrase off: {m}"))
        self._busy = False
        self._done.connect(self._finish)
        self.tts = None
        self._state = "idle"
        self._vocab = ""
        self.reload()

    # -- settings
    def reload(self):
        self.settings = core.load_settings(self.db)
        self._setup_tts()
        self.set_wake(bool(self.settings.get("wake_on")))

    def ai_settings(self):
        return vision_ai.load_settings(self.db)

    def _setup_tts(self):
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
        except ImportError:
            self.tts = None
            return
        if self.tts is None:
            self.tts = QTextToSpeech(self)
            self.tts.stateChanged.connect(self._tts_state)
        want = self.settings.get("voice") or ""
        if want:
            for v in self.tts.availableVoices():
                if v.name() == want:
                    self.tts.setVoice(v)
                    break
        self.tts.setRate(max(-1.0, min(1.0, float(self.settings.get("rate") or 0))))

    def wake_ready(self):
        if (self.settings.get("stt") or "local") != "local":
            return False, "The wake phrase needs the offline speech engine (it listens all the time)."
        return speech.stt_ready(self.settings, self.ai_settings())

    def set_wake(self, on):
        if not on:
            self.wake.stop(quiet=True)
            self._set_state("idle" if self._state == "wake" else self._state)
            return
        ok, why = self.wake_ready()
        if not ok:
            self.note.emit(f"Wake phrase off: {why}")
            return
        if self.wake.start("wake"):
            self._set_state("wake")

    # -- entry points
    def listen(self):
        """Push-to-talk: one utterance."""
        if self._busy:
            return
        if self.mic.active:
            self.mic.stop()
            return
        ok, why = speech.stt_ready(self.settings, self.ai_settings())
        if not ok:
            self.note.emit(why)
            return
        self.stop_speaking()
        self.wake.paused = True
        if self.mic.start("once"):
            self._set_state("listening")

    def ask_text(self, text):
        text = " ".join(str(text or "").split())
        if not text or self._busy:
            return
        self.heard.emit(text)
        self._run(lambda: self.assistant.ask(text, WHO))

    def stop_speaking(self):
        if self.tts is not None:
            self.tts.stop()

    # -- pipeline
    def _vocabulary(self):
        try:
            names = [d["name"] for d in self.api.status()["devices"]]
        except Exception:
            names = []
        return speech.vocabulary_prompt(names, self.settings.get("wake_phrase") or "")

    def _on_utterance(self, pcm):
        self._set_state("thinking")
        self.wake.paused = True

        def work():
            text = speech.transcribe(speech.Pcm(pcm, speech.RATE), self.settings, self.ai_settings(),
                                     prompt=self._vocabulary())
            ok, rest = core.wake_match(text, self.settings.get("wake_phrase") or "")
            text = rest if ok and rest else text           # "hey cypher, lights off" said after pressing the mic
            if not text.strip():
                return {"say": "", "heard": "", "silent": True}
            self.heard.emit(text)
            return self.assistant.ask(text, WHO)
        self._run(work)

    def _on_wake_utterance(self, pcm):
        if self._busy or self.mic.active or self._state == "speaking":
            return
        self._busy = True
        phrase = self.settings.get("wake_phrase") or core.DEFAULT_WAKE

        def work():
            text = speech.transcribe(speech.Pcm(pcm, speech.RATE), self.settings, self.ai_settings(),
                                     prompt=f"{phrase}. " + self._vocab)
            ok, rest = core.wake_match(text, phrase)
            if not ok:
                return None
            if not rest.strip():
                return {"wake_only": True}
            self.heard.emit(rest)
            return self.assistant.ask(rest, WHO)
        threading.Thread(target=lambda: self._done.emit(self._safe(work)), daemon=True).start()

    def _run(self, fn):
        self._busy = True
        self._set_state("thinking")
        threading.Thread(target=lambda: self._done.emit(self._safe(fn)), daemon=True).start()

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except speech.SpeechError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Something went wrong: {e}"}

    def _finish(self, reply):
        self._busy = False
        self.wake.paused = False
        if reply is None:                                  # wake listener heard something else
            return
        if reply.get("wake_only"):
            self.answered.emit({"wake": True})
            self.listen()
            return
        if reply.get("error"):
            self.note.emit(reply["error"])
            self._set_state("wake" if self.wake.active else "idle")
            return
        if reply.get("silent"):
            self.note.emit("I didn't hear anything. Press the mic and speak.")
            self._set_state("wake" if self.wake.active else "idle")
            return
        self.answered.emit(reply)
        if self.settings.get("speak", True) and self.tts is not None and reply.get("say"):
            self.wake.paused = True                        # don't wake ourselves up
            self.tts.say(_speakable(reply["say"]))
            self._set_state("speaking")
        else:
            self._set_state("wake" if self.wake.active else "idle")

    def _tts_state(self, st):
        from PySide6.QtTextToSpeech import QTextToSpeech
        if st in (QTextToSpeech.State.Ready, QTextToSpeech.State.Error):
            QTimer.singleShot(400, self._after_speaking)    # the room echo dies down first

    def _after_speaking(self):
        self.wake.paused = False
        if self._state == "speaking":
            self._set_state("wake" if self.wake.active else "idle")

    def _mic_failed(self, msg):
        self.wake.paused = False
        self.note.emit(msg)
        self._set_state("wake" if self.wake.active else "idle")

    def _mic_stopped(self):
        if self._state == "listening" and not self._busy:
            self.wake.paused = False
            self._set_state("wake" if self.wake.active else "idle")

    def _set_state(self, s):
        if s == "wake":
            # refreshed now and then so Whisper knows newly added appliances
            threading.Thread(target=lambda: setattr(self, "_vocab", self._vocabulary()), daemon=True).start()
        self._state = s
        self.state.emit(s)


def _speakable(text):
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", text)
    return t.replace("₦", "naira ").replace("kWh", "units").replace(" W ", " watts ")


# ------------------------------------------------------------------ panel --

class LevelBars(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 18)
        self.value = 0.0
        self.on = False

    def set_level(self, v):
        self.value = self.value * 0.5 + v * 0.5
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shape = (0.45, 0.75, 1.0, 0.75, 0.45)
        for i, k in enumerate(shape):
            h = 4 + (self.height() - 4) * (min(1.0, self.value * k * 1.6) if self.on else 0.0)
            c = QColor(ACCENT if self.on else DIM)
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(i * 9 + 2, (self.height() - h) / 2, 5, h), 2.5, 2.5)


STATE_TEXT = {
    "idle": "Press the mic or Ctrl+Space",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking",
}


class AssistantPanel(QFrame):
    """The floating card on the main window."""

    def __init__(self, voice, host, parent):
        super().__init__(parent)
        self.voice = voice
        self.host = host                    # the main window: settings dialog parent
        self.setObjectName("assistant-panel")
        self.setFixedWidth(380)
        self.setStyleSheet(
            f"QLineEdit{{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.09);"
            f"border-radius:18px;padding:7px 14px;color:{TEXT};font-size:13px;}}"
            f"QLineEdit:focus{{border:1px solid {ACCENT};}}")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        orb = QLabel()
        orb.setFixedSize(34, 34)
        orb.setAlignment(Qt.AlignCenter)
        orb.setPixmap(get_icon("mic", ON_ACCENT, 16).pixmap(16, 16))
        orb.setStyleSheet(f"background:{ACCENT};border-radius:17px;")
        head.addWidget(orb)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Assistant")
        t.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:700;background:transparent;")
        self.state_lbl = QLabel()
        self.state_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;background:transparent;")
        titles.addWidget(t)
        titles.addWidget(self.state_lbl)
        head.addLayout(titles, 1)
        self.bars = LevelBars()
        head.addWidget(self.bars)
        for icon, tip, slot in (("settings", "Assistant settings", self.open_settings),
                                ("x", "Close (Esc)", self.hide)):
            b = QPushButton()
            b.setIcon(get_icon(icon, SOFT, 14))
            b.setToolTip(tip)
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:rgba(255,255,255,0.06);border:none;border-radius:15px;}"
                            "QPushButton:hover{background:rgba(255,255,255,0.14);}")
            b.clicked.connect(slot)
            head.addWidget(b)
        lo.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # solid, not transparent: a see-through viewport keeps stale pixels of the page underneath
        self.scroll.setStyleSheet(f"QScrollArea{{background:{PANEL_BG};border:none;}}")
        self.scroll.viewport().setStyleSheet(f"background:{PANEL_BG};")
        self.scroll.setMinimumHeight(170)
        self.scroll.setMaximumHeight(300)
        body = QWidget()
        body.setStyleSheet(f"background:{PANEL_BG};")
        self.log = QVBoxLayout(body)
        self.log.setContentsMargins(0, 0, 4, 0)
        self.log.setSpacing(8)
        self.log.addStretch(1)
        self.scroll.setWidget(body)
        lo.addWidget(self.scroll, 1)

        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        for s in SUGGESTIONS:
            c = QPushButton(s)
            c.setCursor(Qt.PointingHandCursor)
            c.setStyleSheet(f"QPushButton{{background:rgba(255,122,26,0.12);color:{ACCENT_HI};border:none;"
                            f"border-radius:12px;padding:4px 10px;font-size:11px;font-weight:700;}}"
                            f"QPushButton:hover{{background:rgba(255,122,26,0.22);}}")
            c.clicked.connect(lambda _=False, s=s: self.voice.ask_text(s))
            self.chips.addWidget(c)
        self.chips.addStretch(1)
        lo.addLayout(self.chips)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type, or press the mic and speak")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.mic_btn = QPushButton()
        self.mic_btn.setFixedSize(40, 40)
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setToolTip("Speak (Ctrl+Space)")
        self.mic_btn.clicked.connect(self._mic)
        row.addWidget(self.mic_btn)
        lo.addLayout(row)

        voice.state.connect(self._state)
        voice.heard.connect(lambda t: self._bubble(t, mine=True))
        voice.answered.connect(self._answer)
        voice.note.connect(lambda t: self._bubble(t, note=True))
        voice.level.connect(self.bars.set_level)
        self._state("wake" if voice.wake.active else "idle")
        self._bubble("Hi! Ask me to switch things, or about light, units, battery, the fridge or the weather.")
        parent.installEventFilter(self)
        self.hide()

    def paintEvent(self, _e):
        # painted by hand: a style-sheet background on a floating child isn't drawn on every platform
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(255, 255, 255, 26))
        p.setBrush(QColor(PANEL_BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)

    # -- placement
    def eventFilter(self, obj, e):
        if obj is self.parent() and e.type() == QEvent.Resize and self.isVisible():
            self._place()
        return False

    def _place(self):
        par = self.parent()
        self.adjustSize()
        h = min(self.sizeHint().height(), par.height() - 90)
        self.resize(self.width(), max(300, h))
        self.move(par.width() - self.width() - 22, par.height() - self.height() - 22)
        self.raise_()

    def popup(self, focus_input=False):
        self.show()
        self._place()
        if focus_input:
            self.input.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.voice.stop_speaking()
            self.hide()
            return
        super().keyPressEvent(e)

    # -- actions
    def _send(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.voice.ask_text(text)

    def _mic(self):
        self.voice.listen()

    def open_settings(self):
        dlg = AssistantSettingsDialog(self.voice, self.host)
        if dlg.exec():
            self.voice.reload()
            self._state(self.voice._state)

    # -- view
    def _state(self, s):
        listening = s == "listening"
        self.bars.on = listening
        self.bars.update()
        if s == "wake":
            phrase = self.voice.settings.get("wake_phrase") or core.DEFAULT_WAKE
            self.state_lbl.setText(f"Say “{phrase}”, or press the mic")
        else:
            self.state_lbl.setText(STATE_TEXT.get(s, ""))
        self.state_lbl.setStyleSheet(f"color:{ACCENT_HI if s in ('listening', 'speaking') else MUTED};"
                                     f"font-size:11px;font-weight:600;background:transparent;")
        self.mic_btn.setIcon(get_icon("square" if listening else "mic", ON_ACCENT, 16))
        self.mic_btn.setStyleSheet(
            f"QPushButton{{background:{CRIT if listening else ACCENT};border:none;border-radius:20px;}}"
            f"QPushButton:hover{{background:{ACCENT_HI};}}QPushButton:disabled{{background:rgba(255,122,26,0.35);}}")
        self.mic_btn.setEnabled(s != "thinking")
        if s == "listening" and not self.isVisible():
            self.popup()

    def _answer(self, reply):
        if reply.get("wake"):
            self.popup()
            return
        if reply.get("say"):
            self._bubble(reply["say"], did=reply.get("did") or [])
        if reply.get("photo"):
            self._picture(reply["photo"])

    def _bubble(self, text, mine=False, note=False, did=()):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setMaximumWidth(290)
        # a wrapped label asks for very little width; size it to the text, up to the bubble limit
        lbl.setMinimumWidth(min(290, lbl.fontMetrics().horizontalAdvance(text) + 30))
        if mine:
            lbl.setStyleSheet(f"background:{ACCENT};color:{ON_ACCENT};border-radius:14px;padding:7px 12px;"
                              f"font-size:12px;font-weight:600;")
        elif note:
            lbl.setStyleSheet(f"background:rgba(248,113,113,0.10);color:#fecaca;border-radius:14px;"
                              f"padding:7px 12px;font-size:12px;")
        else:
            lbl.setStyleSheet(f"background:rgba(255,255,255,0.06);color:{TEXT};border-radius:14px;"
                              f"padding:7px 12px;font-size:12px;")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if mine:
            row.addStretch(1)
        row.addWidget(lbl)
        if not mine:
            row.addStretch(1)
        self.log.insertLayout(self.log.count(), row)
        if did:
            tag = QLabel("  ·  ".join(did))
            tag.setStyleSheet(f"color:{GOOD};font-size:10px;font-weight:700;background:transparent;padding-left:6px;")
            self.log.insertWidget(self.log.count(), tag)
        self._trim()
        if self.isVisible():
            self._place()
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _picture(self, jpeg):
        img = QImage.fromData(jpeg)
        if img.isNull():
            return
        lbl = QLabel()
        lbl.setPixmap(QPixmap.fromImage(img).scaledToWidth(290, Qt.SmoothTransformation))
        lbl.setStyleSheet("border-radius:12px;background:transparent;")
        self.log.insertWidget(self.log.count(), lbl)
        self._trim()

    def _trim(self):
        while self.log.count() > 41:                       # stretch + 40 entries
            item = self.log.takeAt(1)
            w = item.widget() or None
            if w is not None:
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(0)
                    if sub.widget():
                        sub.widget().hide()
                        sub.widget().deleteLater()


# --------------------------------------------------------------- settings --

class AssistantSettingsDialog(QDialog):
    """Speech engine, smart answers (AI), voice, wake phrase and the voice PIN."""

    def __init__(self, voice, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.db = Database.get_instance()
        self.s = core.load_settings(self.db)
        self.ai = vision_ai.load_settings(self.db)
        self.setWindowTitle("Assistant settings")
        self.setMinimumWidth(540)
        apply_home_style(self)
        self.setStyleSheet(self.styleSheet() +
                           f"QSlider::groove:horizontal{{height:4px;background:rgba(255,255,255,0.10);border-radius:2px;}}"
                           f"QSlider::sub-page:horizontal{{background:{ACCENT};border-radius:2px;}}"
                           f"QSlider::handle:horizontal{{background:{TEXT};width:14px;margin:-6px 0;border-radius:7px;}}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)
        # four short tabs instead of one tall form, so it fits a 768-pixel-high screen
        self.tabs = Segmented([("hear", "mic", "Hearing"), ("ai", "zap", "Smart answers"),
                               ("voice", "volume", "Voice"), ("wake", "lock", "Wake + PIN")], height=32)
        outer.addWidget(self.tabs)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        pages = {}
        self.tabs.changed.connect(lambda k: self.pages.setCurrentWidget(pages[k]))
        state = {"lo": None}

        def page(key):
            w = QWidget()
            lo_ = QVBoxLayout(w)
            lo_.setContentsMargins(2, 6, 2, 2)
            lo_.setSpacing(10)
            pages[key] = w
            self.pages.addWidget(w)
            state["lo"] = lo_
            return lo_

        def section(title, hint=""):
            lo_ = state["lo"]
            h = QLabel(title)
            h.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:800;margin-top:4px;")
            lo_.addWidget(h)
            if hint:
                x = QLabel(hint)
                x.setWordWrap(True)
                x.setStyleSheet(f"color:{MUTED};font-size:11px;")
                lo_.addWidget(x)
            f = QFormLayout()
            f.setHorizontalSpacing(12)
            f.setVerticalSpacing(10)
            f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            lo_.addLayout(f)
            return f

        # -- hearing
        page("hear")
        f = section("Hearing you", "How speech becomes text. Offline is private and free; Groq is free and "
                                   "faster on slow PCs but sends the recording to Groq.")
        self.stt = QComboBox()
        for k, e in speech.ENGINES.items():
            self.stt.addItem(f"{e['title']} ({e['tag']})", k)
        self.stt.setCurrentIndex(max(0, self.stt.findData(self.s.get("stt") or "local")))
        f.addRow("Engine", self.stt)
        self.stt_model = QComboBox()
        for k, label in speech.LOCAL_MODELS.items():
            self.stt_model.addItem(label, k)
        self.stt_model.setCurrentIndex(max(0, self.stt_model.findData(self.s.get("stt_model") or "base.en")))
        f.addRow("Offline model", self.stt_model)
        self.stt_key = QLineEdit()
        self.stt_key.setEchoMode(QLineEdit.Password)
        f.addRow("API key", self.stt_key)
        self.lang = QComboBox()
        for code, label in (("en-NG", "English (Nigeria)"), ("en-GB", "English (UK)"), ("en-US", "English (US)")):
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(self.s.get("lang") or "en-NG")))
        f.addRow("Accent", self.lang)
        self.stt_info = QLabel()
        self.stt_info.setWordWrap(True)
        f.addRow("", self.stt_info)

        # -- smart answers
        page("ai")
        f = section("Smart answers (optional)",
                    "Everyday commands work offline without this. An AI answers anything else — "
                    "\"it's hot in here\", \"will the battery last the night?\". Keys are shared with the "
                    "fridge AI.")
        self.ai_pick = QComboBox()
        for pid in core.AI_ORDER:
            self.ai_pick.addItem("Off — built-in commands only" if pid == "none" else vision_ai.label(pid), pid)
        self.ai_pick.setCurrentIndex(max(0, self.ai_pick.findData(self.s.get("ai") or "none")))
        f.addRow("AI", self.ai_pick)
        self.ai_model = QLineEdit()
        f.addRow("Model", self.ai_model)
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.Password)
        f.addRow("API key", self.ai_key)

        # -- voice
        page("voice")
        f = section("Talking back", "Answers are read out with the Windows voices. More voices: Windows "
                                    "Settings → Time & language → Speech.")
        self.speak = QCheckBox("Speak the answers")
        self.speak.setChecked(bool(self.s.get("speak", True)))
        f.addRow("", self.speak)
        self.voice_pick = QComboBox()
        self.voice_pick.addItem("System default", "")
        tts = voice.tts
        if tts is not None:
            for v in tts.availableVoices():
                self.voice_pick.addItem(v.name(), v.name())
        self.voice_pick.setCurrentIndex(max(0, self.voice_pick.findData(self.s.get("voice") or "")))
        test = QPushButton("Test")
        test.clicked.connect(self._test_voice)
        vrow = QHBoxLayout()
        vrow.addWidget(self.voice_pick, 1)
        vrow.addWidget(test)
        f.addRow("Voice", vrow)
        self.rate = QSlider(Qt.Horizontal)
        self.rate.setRange(-5, 5)
        self.rate.setValue(int(round(float(self.s.get("rate") or 0) * 10)))
        f.addRow("Speed", self.rate)

        # -- wake phrase
        page("wake")
        f = section("Wake phrase", "Say the phrase to start talking without touching the PC — for example "
                                   "\"Hey Cypher, turn off the TV\". Pick any 2–3 words; unusual words work best "
                                   "(\"Hey Cypher\", \"Okay House\", \"Jarvis\"). Needs the offline engine, and "
                                   "uses a little CPU while it listens.")
        self.wake_on = QCheckBox("Listen for the wake phrase")
        self.wake_on.setChecked(bool(self.s.get("wake_on")))
        f.addRow("", self.wake_on)
        self.wake_phrase = QLineEdit(self.s.get("wake_phrase") or core.DEFAULT_WAKE)
        self.wake_phrase.setMaxLength(30)
        f.addRow("Phrase", self.wake_phrase)

        # -- PIN
        f = section("Voice PIN", "Needed to disarm the cameras by voice (\"disarm 4 8 1 5\"), so nobody can "
                                 "shout it through a window. 4–8 digits.")
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setMaxLength(8)
        self.pin.setPlaceholderText("PIN is set — type a new one to change it" if self.s.get("pin_hash")
                                    else "No PIN yet — voice can't disarm")
        clear = QPushButton("Remove PIN")
        clear.setEnabled(bool(self.s.get("pin_hash")))
        clear.clicked.connect(self._clear_pin)
        prow = QHBoxLayout()
        prow.addWidget(self.pin, 1)
        prow.addWidget(clear)
        f.addRow("PIN", prow)
        self._pin_cleared = False

        for w in pages.values():
            w.layout().addStretch(1)
        hint = QLabel("Ctrl+Space talks from anywhere in CYPHER-X. The phone dashboard has a mic button too, "
                      "and the Telegram bot understands voice notes.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{DIM};font-size:11px;")
        outer.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

        self.stt.currentIndexChanged.connect(self._sync)
        self.ai_pick.currentIndexChanged.connect(self._sync)
        self._sync()

    def _provider_key(self, pid):
        return ((self.ai.get("providers") or {}).get(pid) or {}).get("key", "")

    def _sync(self):
        eng = self.stt.currentData()
        local = eng == "local"
        self.stt_model.setEnabled(local)
        self.stt_key.setEnabled(not local)
        if not local:
            pid = speech.ENGINES[eng]["key_from"]
            self.stt_key.setText(self._provider_key(pid))
            self.stt_key.setPlaceholderText(f"{vision_ai.PROVIDERS[pid]['title']} key — "
                                            f"{vision_ai.PROVIDERS[pid]['signup']}")
            self.stt_info.setText("")
        else:
            self.stt_key.clear()
            self.stt_key.setPlaceholderText("Not needed offline")
            ok = speech.local_available()
            self.stt_info.setText("Ready. The model downloads once the first time you speak (needs internet)."
                                  if ok else "Not installed yet. In a terminal run:  pip install faster-whisper")
            self.stt_info.setStyleSheet(f"color:{GOOD if ok else '#fbbf24'};font-size:11px;")
        pid = self.ai_pick.currentData()
        on = pid != "none"
        self.ai_model.setEnabled(on)
        self.ai_model.setText(str((self.s.get("models") or {}).get(pid) or "") if on else "")
        self.ai_model.setPlaceholderText(core.AI_MODELS.get(pid, "") if on else "")
        needs_key = on and vision_ai.PROVIDERS.get(pid, {}).get("key")
        self.ai_key.setEnabled(bool(needs_key))
        self.ai_key.setText(self._provider_key(pid) if needs_key else "")
        self.ai_key.setPlaceholderText(f"Get one at {vision_ai.PROVIDERS[pid]['signup']}" if needs_key
                                       else "Not needed")

    def _clear_pin(self):
        self._pin_cleared = True
        self.pin.clear()
        self.pin.setPlaceholderText("PIN will be removed when you save")

    def _test_voice(self):
        tts = self.voice.tts
        if tts is None:
            QMessageBox.information(self, "Voice", "Text-to-speech isn't available on this PC.")
            return
        name = self.voice_pick.currentData()
        for v in tts.availableVoices():
            if v.name() == name:
                tts.setVoice(v)
        tts.setRate(self.rate.value() / 10)
        tts.say("Hello. The grid is on and the battery is at ninety percent.")

    def _save(self):
        s = self.s
        s["stt"] = self.stt.currentData()
        s["stt_model"] = self.stt_model.currentData()
        s["lang"] = self.lang.currentData()
        s["ai"] = self.ai_pick.currentData()
        models = dict(s.get("models") or {})
        if s["ai"] != "none":
            models[s["ai"]] = self.ai_model.text().strip()
        s["models"] = models
        s["speak"] = self.speak.isChecked()
        s["voice"] = self.voice_pick.currentData() or ""
        s["rate"] = self.rate.value() / 10
        phrase = " ".join(self.wake_phrase.text().split())
        if self.wake_on.isChecked() and len(core.norm(phrase)) < 3:
            QMessageBox.warning(self, "Wake phrase", "Type a wake phrase first, e.g. Hey Cypher.")
            return
        s["wake_phrase"] = phrase or core.DEFAULT_WAKE
        s["wake_on"] = self.wake_on.isChecked()
        try:
            if self.pin.text().strip():
                core.set_pin(s, self.pin.text())
            elif self._pin_cleared:
                core.set_pin(s, "")
        except core.AssistantError as e:
            QMessageBox.warning(self, "Voice PIN", str(e))
            return
        # shared API keys live with the fridge AI settings
        providers = dict(self.ai.get("providers") or {})
        for pid, field in ((speech.ENGINES.get(s["stt"], {}).get("key_from"), self.stt_key),
                           (s["ai"] if s["ai"] != "none" else None, self.ai_key)):
            if pid and field.isEnabled():
                mine = dict(providers.get(pid) or {})
                mine["key"] = field.text().strip()
                providers[pid] = mine
        self.ai["providers"] = providers
        vision_ai.save_settings(self.db, self.ai)
        core.save_settings(self.db, s)
        self.accept()
