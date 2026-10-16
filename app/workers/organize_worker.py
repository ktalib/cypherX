from typing import List, Dict, Any
from PySide6.QtCore import QThread, Signal
from app.services.file_organizer_service import FileOrganizerService

class OrganizeWorker(QThread):
    """Background worker for executing planned file moves safely."""

    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, planned_moves: List[Dict[str, Any]], conflict_mode: str = "rename", parent=None):
        super().__init__(parent)
        self.planned_moves = planned_moves
        self.conflict_mode = conflict_mode
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            results = FileOrganizerService.execute_moves(
                self.planned_moves,
                conflict_mode=self.conflict_mode,
                progress_callback=lambda idx, name: self.progress.emit(idx, name),
                is_cancelled=lambda: self._is_cancelled
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
