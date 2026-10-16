import os
import shutil
import tempfile
import unittest
from pathlib import Path
from app.services.file_organizer_service import FileOrganizerService

class TestFileOrganizer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cyberops_test_organizer_")
        self.root = Path(self.test_dir)

        # Create dummy test files
        (self.root / "doc1.pdf").write_text("dummy pdf")
        (self.root / "img1.png").write_text("dummy png")
        (self.root / "code1.py").write_text("dummy python")
        (self.root / "archive1.zip").write_text("dummy zip")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_dry_run_simulation(self):
        plan = FileOrganizerService.preview_organization(self.test_dir, strategy="category")
        self.assertEqual(plan["total_files"], 4)
        self.assertEqual(plan["conflicts"], 0)
        self.assertEqual(len(plan["planned_moves"]), 4)

        # Verify original files were NOT moved during dry run
        self.assertTrue((self.root / "doc1.pdf").exists())
        self.assertTrue((self.root / "img1.png").exists())

    def test_execute_and_undo(self):
        plan = FileOrganizerService.preview_organization(self.test_dir, strategy="category")
        exec_res = FileOrganizerService.execute_moves(plan["planned_moves"], conflict_mode="rename")

        self.assertEqual(exec_res["executed_count"], 4)
        self.assertTrue((self.root / "Documents" / "doc1.pdf").exists())
        self.assertTrue((self.root / "Images" / "img1.png").exists())
        self.assertTrue((self.root / "Code" / "code1.py").exists())
        self.assertTrue((self.root / "Archives" / "archive1.zip").exists())

        # Test Undo
        undo_res = FileOrganizerService.undo_moves(exec_res["executed_moves"])
        self.assertEqual(undo_res["restored_count"], 4)

        # Verify files restored to root
        self.assertTrue((self.root / "doc1.pdf").exists())
        self.assertTrue((self.root / "img1.png").exists())
        self.assertTrue((self.root / "code1.py").exists())
        self.assertTrue((self.root / "archive1.zip").exists())

if __name__ == "__main__":
    unittest.main()
