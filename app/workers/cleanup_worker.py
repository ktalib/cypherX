from typing import List
from PySide6.QtCore import QThread, Signal
from app.services.cleanup_service import CleanupService

class CleanupAnalyzeWorker(QThread):
    """Worker to safely analyze temporary files without deletion."""

    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, target_path: str, min_age_hours: float = 24.0, parent=None):
        super().__init__(parent)
        self.target_path = target_path
        self.min_age_hours = min_age_hours
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            results = CleanupService.analyze_target(
                self.target_path,
                min_age_hours=self.min_age_hours,
                progress_callback=lambda count, name: self.progress.emit(count, name),
                is_cancelled=lambda: self._is_cancelled
            )
            if not self._is_cancelled:
                self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class CleanupExecuteWorker(QThread):
    """Worker to perform safe file removal (Recycle Bin preference) on confirmed items."""

    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, files: List[str], use_recycle_bin: bool = True, parent=None):
        super().__init__(parent)
        self.files = files
        self.use_recycle_bin = use_recycle_bin
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            results = CleanupService.execute_cleanup(
                self.files,
                use_recycle_bin=self.use_recycle_bin,
                progress_callback=lambda count, name: self.progress.emit(count, name),
                is_cancelled=lambda: self._is_cancelled
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
