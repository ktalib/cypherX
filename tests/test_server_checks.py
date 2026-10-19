import os
import shutil
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from app.services import server_checks as sc


class TestServerChecks(unittest.TestCase):
    def test_statuses_are_known(self):
        for fn in (sc.check_launch, sc.check_system, sc.check_storage):
            status, detail = fn()
            self.assertIn(status, (sc.OK, sc.WARN, sc.FAIL, sc.INFO))
            self.assertTrue(detail)

    def test_root(self):
        self.assertEqual(sc.check_root({"username": "admin", "role": "root"})[0], sc.OK)
        self.assertEqual(sc.check_root({"username": "mum", "role": "user"})[0], sc.FAIL)
        self.assertEqual(sc.check_root(None)[0], sc.FAIL)

    def test_database(self):
        d = tempfile.mkdtemp()
        try:
            db = Path(d) / "x.db"
            self.assertEqual(sc.check_database(db)[0], sc.FAIL)          # missing
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE a (x)")
            conn.commit()
            conn.close()
            status, detail = sc.check_database(db)
            self.assertEqual(status, sc.OK)
            self.assertIn("1 tables", detail)
            db.write_bytes(b"this is not a database at all" * 100)
            self.assertEqual(sc.check_database(db)[0], sc.FAIL)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_network_offline_is_a_warning_not_a_failure(self):
        with mock.patch.object(sc, "local_ip", return_value="192.168.1.20"), \
                mock.patch.object(socket, "create_connection", side_effect=OSError("down")):
            status, detail = sc.check_network()
        self.assertEqual(status, sc.WARN)
        self.assertIn("192.168.1.20", detail)
        with mock.patch.object(sc, "local_ip", return_value="127.0.0.1"):
            self.assertEqual(sc.check_network()[0], sc.WARN)

    def test_updates_and_services(self):
        status, detail = sc.check_updates("1.0.0")
        self.assertEqual(status, sc.INFO)                 # never claims "up to date" without a server
        self.assertIn("1.0.0", detail)
        status, detail = sc.check_services(2, 3, 1, True)
        self.assertEqual(status, sc.OK)
        self.assertIn("1/3 cameras live", detail)


if __name__ == "__main__":
    unittest.main()
