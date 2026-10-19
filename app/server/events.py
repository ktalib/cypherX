"""
A tiny publish / subscribe bus for things worth telling the owner about
(motion, power cut, meter low, new device on the Wi-Fi, backup failed...).

Publishers call `bus.publish(kind, title, message, **data)` from the GUI thread;
subscribers (e.g. the Telegram bot) must not block — they queue the event for
their own thread.
"""
import time
import threading


class EventBus:
    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()
        self.recent = []          # last events, newest last (for status pages)

    def subscribe(self, fn):
        with self._lock:
            if fn not in self._subs:
                self._subs.append(fn)

    def unsubscribe(self, fn):
        with self._lock:
            if fn in self._subs:
                self._subs.remove(fn)

    def publish(self, kind, title, message, **data):
        event = {"ts": time.time(), "kind": kind, "title": title, "message": message, **data}
        with self._lock:
            self.recent = (self.recent + [event])[-100:]
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(event)
            except Exception:
                pass                # one broken subscriber must not stop the others
        return event


bus = EventBus()
