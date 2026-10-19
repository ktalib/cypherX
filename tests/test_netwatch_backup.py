import json
import shutil
import sqlite3
import tempfile
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from app.server.events import EventBus
from app.server.services import ServiceManager
from app.server import netwatch as nw
from app.server.backup import BackupManager, BackupService, backup_check

ARP_WINDOWS = """
Interface: 192.168.1.20 --- 0xb
  Internet Address      Physical Address      Type
  192.168.1.1           a4-2b-b0-11-22-33     dynamic
  192.168.1.34          24-0a-c4-aa-bb-cc     dynamic
  192.168.1.40          da-11-22-33-44-55     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""
IP_NEIGH = """192.168.1.1 dev wlan0 lladdr a4:2b:b0:11:22:33 REACHABLE
192.168.1.50 dev wlan0 lladdr b8:27:eb:01:02:03 STALE
192.168.1.77 dev wlan0  FAILED
"""


class TestNetwatch(unittest.TestCase):
    def test_parsers_and_vendors(self):
        arp = nw.parse_arp_windows(ARP_WINDOWS)
        self.assertEqual([ip for ip, _ in arp], ["192.168.1.1", "192.168.1.34", "192.168.1.40"])
        self.assertEqual(arp[1][1], "24:0A:C4:AA:BB:CC")
        self.assertEqual(nw.parse_ip_neigh(IP_NEIGH), [("192.168.1.1", "A4:2B:B0:11:22:33"),
                                                       ("192.168.1.50", "B8:27:EB:01:02:03")])
        self.assertIn("Espressif", nw.vendor_of("24:0A:C4:AA:BB:CC"))
        self.assertIn("Raspberry", nw.vendor_of("b8-27-eb-01-02-03"))
        self.assertIn("Private", nw.vendor_of("DA:11:22:33:44:55"))      # locally administered bit
        self.assertEqual(nw.vendor_of("A4:2B:B0:11:22:33"), "Unknown maker")
        self.assertEqual(len(nw.subnet_hosts("192.168.1.20")), 254)

    def test_scan_with_fakes(self):
        res = nw.scan(ping_fn=lambda ip: ip.endswith(".34"), arp_fn=lambda: nw.parse_arp_windows(ARP_WINDOWS),
                      name_fn=lambda ip: "plug" if ip.endswith(".34") else "", ip="192.168.1.20")
        self.assertEqual(res["answered"], 1)
        self.assertEqual([d["ip"] for d in res["devices"]], ["192.168.1.1", "192.168.1.34", "192.168.1.40"])
        self.assertEqual(res["devices"][1]["hostname"], "plug")

    def test_book_baseline_then_new_device_alert(self):
        d = tempfile.mkdtemp()
        try:
            book = nw.DeviceBook(Path(d) / "dev.json")
            bus, got = EventBus(), []
            bus.subscribe(got.append)
            results = [
                {"ip": "192.168.1.20", "devices": [
                    {"ip": "192.168.1.1", "mac": "A4:2B:B0:11:22:33", "hostname": "", "vendor": "Unknown maker"}]},
                {"ip": "192.168.1.20", "devices": [
                    {"ip": "192.168.1.1", "mac": "A4:2B:B0:11:22:33", "hostname": "", "vendor": "Unknown maker"},
                    {"ip": "192.168.1.66", "mac": "DA:00:00:00:00:01", "hostname": "", "vendor": "Private address"}]},
            ]
            svc = nw.NetWatchService(bus, book=book, scan_fn=lambda stop=None: results.pop(0))
            m = ServiceManager()
            m.register(svc)
            self.assertEqual(svc.scan_once(), [])                     # first scan = baseline, no alert
            self.assertEqual(book.label("A4:2B:B0:11:22:33"), "Router (likely)")
            self.assertTrue(book.devices["A4:2B:B0:11:22:33"]["trusted"])
            new = svc.scan_once()
            self.assertEqual([x["mac"] for x in new], ["DA:00:00:00:00:01"])
            self.assertEqual(got[-1]["kind"], "network")
            self.assertFalse(book.devices["DA:00:00:00:00:01"]["trusted"])
            book.rename("DA:00:00:00:00:01", "Mum's phone")
            again = nw.DeviceBook(Path(d) / "dev.json")
            self.assertEqual(again.label("DA:00:00:00:00:01"), "Mum's phone")
            self.assertTrue(again.online("DA:00:00:00:00:01"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestBackups(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.data = self.d / "data"
        (self.data / "cctv").mkdir(parents=True)
        self.db = self.data / "cyberops.db"
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE notes (t TEXT)")
        c.execute("INSERT INTO notes VALUES ('before')")
        c.commit()
        c.close()
        (self.data / "smart_home.json").write_text('{"v": 1}')
        (self.data / "cctv" / "cctv.json").write_text('{"cameras": []}')
        self.bm = BackupManager(self.data, self.db)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _notes(self):
        c = sqlite3.connect(self.db)
        try:
            return [r[0] for r in c.execute("SELECT t FROM notes")]
        finally:
            c.close()

    def test_create_restore_roundtrip(self):
        dest = self.d / "backups"
        path = self.bm.create(dest)
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        self.assertTrue({"cyberops.db", "smart_home.json", "cctv/cctv.json", "manifest.json"} <= names)
        # change things, then restore
        c = sqlite3.connect(self.db)
        c.execute("UPDATE notes SET t = 'after'")
        c.commit()
        c.close()
        (self.data / "smart_home.json").write_text('{"v": 2}')
        self.bm.restore(path)
        self.assertEqual(self._notes(), ["before"])
        self.assertEqual(json.loads((self.data / "smart_home.json").read_text()), {"v": 1})

    def test_rejects_foreign_or_unsafe_zips(self):
        bad = self.d / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("manifest.json", json.dumps({"app": "CYPHER-X", "files": ["../evil.txt"]}))
            z.writestr("../evil.txt", "x")
        with self.assertRaises(ValueError):
            self.bm.restore(bad)
        other = self.d / "other.zip"
        with zipfile.ZipFile(other, "w") as z:
            z.writestr("manifest.json", json.dumps({"app": "something else", "files": []}))
        with self.assertRaises(ValueError):
            self.bm.restore(other)

    def test_prune_keeps_newest_and_pre_restore(self):
        dest = self.d / "b"
        dest.mkdir()
        for i in range(5):
            p = dest / f"cypherx-backup-2026010{i}-000000.zip"
            p.write_bytes(b"x")
            t = time.time() - (5 - i) * 86400
            import os
            os.utime(p, (t, t))
        (dest / "cypherx-backup-20251231-000000-pre-restore.zip").write_bytes(b"x")
        self.assertEqual(self.bm.prune(dest, 2), 3)
        left = sorted(p.name for p in dest.iterdir())
        self.assertIn("cypherx-backup-20251231-000000-pre-restore.zip", left)
        self.assertEqual(len(left), 3)

    def test_service_schedule_and_boot_check(self):
        bus = EventBus()
        svc = BackupService(bus, manager_cls=lambda: self.bm)
        m = ServiceManager()
        m.register(svc)
        svc.set_setting("folder", str(self.d / "nightly"))
        self.assertTrue(svc.due())                                   # never backed up
        self.assertEqual(backup_check(svc)[0], "warn")
        svc.backup_now()
        self.assertFalse(svc.due())
        self.assertEqual(backup_check(svc)[0], "ok")
        tomorrow_3am = datetime.now().replace(hour=3, minute=0).timestamp() + 86400
        self.assertTrue(svc.due(now=tomorrow_3am))                   # past the next 02:30 slot


if __name__ == "__main__":
    unittest.main()
