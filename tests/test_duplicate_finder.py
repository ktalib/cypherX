import os
import shutil
import tempfile
import unittest
from pathlib import Path
from app.services.disk_service import DiskService

class TestDuplicateFinder(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cyberops_test_dup_")
        self.root = Path(self.test_dir)

        # Create two identical files with different names
        (self.root / "original.txt").write_text("Hello CyberOps Security Telemetry Alpha")
        (self.root / "copy_of_original.txt").write_text("Hello CyberOps Security Telemetry Alpha")

        # Create a file with same length (39 bytes) but different content
        (self.root / "different.txt").write_text("Different content string with same len!")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sha256_detection(self):
        h1 = DiskService.compute_sha256(str(self.root / "original.txt"))
        h2 = DiskService.compute_sha256(str(self.root / "copy_of_original.txt"))
        h3 = DiskService.compute_sha256(str(self.root / "different.txt"))

        self.assertIsNotNone(h1)
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)

if __name__ == "__main__":
    unittest.main()
