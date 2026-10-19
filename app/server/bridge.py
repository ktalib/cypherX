"""
Run a function on the GUI thread from a worker thread and wait for the result.

Qt widgets and models may only be touched from the GUI thread; the web server
and the Telegram bot run on their own threads, so every call into the app goes
through GuiBridge.call().
"""
import threading

from PySide6.QtCore import QObject, Signal, QThread, QCoreApplication


class _Job:
    __slots__ = ("fn", "done", "result", "error")

    def __init__(self, fn):
        self.fn = fn
        self.done = threading.Event()
        self.result = None
        self.error = None


class GuiBridge(QObject):
    _submit = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._submit.connect(self._run)       # queued: the bridge lives on the GUI thread

    def _run(self, job):
        try:
            job.result = job.fn()
        except Exception as e:
            job.error = e
        finally:
            job.done.set()

    def post(self, fn):
        """Run fn on the GUI thread later; don't wait (safe while the GUI thread waits for us)."""
        self._submit.emit(_Job(fn))

    def call(self, fn, timeout=8.0):
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() is self.thread():
            return fn()
        job = _Job(fn)
        self._submit.emit(job)
        if not job.done.wait(timeout):
            raise TimeoutError("The app didn't answer in time")
        if job.error is not None:
            raise job.error
        return job.result
