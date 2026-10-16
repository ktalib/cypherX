import os
import shutil
import tempfile
import unittest
from pathlib import Path
from app.services.cleanup_service import CleanupService
from app.services.disk_service import DiskService
from app.services.process_service import ProcessService

class TestCleanupSafety(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cyberops_test_safety_")
        self.root = Path(self.test_dir)
        (self.root / "cache.tmp").write_text("temporary data")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_analysis_is_read_only(self):
        # Run analysis
        res = CleanupService.analyze_target(self.test_dir, min_age_hours=0.0)
        self.assertEqual(len(res["candidates"]), 1)

        # File MUST still exist after analysis
        self.assertTrue((self.root / "cache.tmp").exists())

    def test_protected_directory_detection(self):
        self.assertTrue(DiskService.is_protected_path("C:\\Windows"))
        self.assertTrue(DiskService.is_protected_path("C:\\Windows\\System32"))
        self.assertTrue(DiskService.is_protected_path("C:\\Program Files"))

        # User scratch path should NOT be protected
        self.assertFalse(DiskService.is_protected_path(self.test_dir))

    def test_protected_process_guards(self):
        # Critical Windows processes must be protected
        self.assertTrue(ProcessService.is_protected_process("csrss.exe", 100))
        self.assertTrue(ProcessService.is_protected_process("svchost.exe", 200))
        self.assertTrue(ProcessService.is_protected_process("explorer.exe", 300))
        self.assertTrue(ProcessService.is_protected_process("System", 4))

        # Termination on PID 4 must be blocked
        kill_res = ProcessService.terminate_process(4)
        self.assertFalse(kill_res["success"])
        self.assertIn("critical Windows system component", kill_res["error"])

if __name__ == "__main__":
    unittest.main()
