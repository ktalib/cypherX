from PySide6.QtCore import QThread, Signal
from app.services.disk_service import DiskService

class FolderScanWorker(QThread):
    """Background worker for recursive folder size analysis."""

    progress = Signal(int, str)       # (file_count, current_filename)
    finished = Signal(dict)           # results dictionary
    error = Signal(str)

    def __init__(self, folder_path: str, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            results = DiskService.scan_folder(
                self.folder_path,
                progress_callback=lambda count, name: self.progress.emit(count, name),
                is_cancelled=lambda: self._is_cancelled
            )
            if not self._is_cancelled:
                self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class LargeFileWorker(QThread):
    """Background worker for finding heavy files above a threshold."""

    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, folder_path: str, min_size_bytes: int, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.min_size_bytes = min_size_bytes
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            results = DiskService.find_large_files(
                self.folder_path,
                min_size_bytes=self.min_size_bytes,
                progress_callback=lambda count, name: self.progress.emit(count, name),
                is_cancelled=lambda: self._is_cancelled
            )
            if not self._is_cancelled:
                self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
