import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from app.services.cctv_service import CctvStore, MotionDetector, threshold_for

W, H = 64, 48


def frame(level=100, box=None, box_level=220):
    """Flat grey thumbnail, optionally with a bright box (x, y, w, h)."""
    px = bytearray([level]) * (W * H)
    if box:
        x0, y0, bw, bh = box
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                px[y * W + x] = box_level
    return bytes(px)


class TestMotionDetector(unittest.TestCase):
    def test_still_scene_is_quiet(self):
        d = MotionDetector(6)
        for _ in range(5):
            score, moving = d.feed(frame())
            self.assertFalse(moving)
            self.assertEqual(score, 0.0)

    def test_moving_object_triggers_after_confirmation(self):
        d = MotionDetector(6)
        d.feed(frame())
        _, first = d.feed(frame(box=(5, 5, 12, 12)))
        _, second = d.feed(frame(box=(20, 5, 12, 12)))
        self.assertFalse(first)          # one noisy sample isn't enough
        self.assertTrue(second)

    def test_global_brightness_change_is_ignored(self):
        d = MotionDetector(10)
        d.feed(frame(100))
        for level in (140, 180, 220):
            score, moving = d.feed(frame(level))
            self.assertFalse(moving)
            self.assertEqual(score, 0.0)

    def test_sensitivity_threshold_range(self):
        self.assertAlmostEqual(threshold_for(1), 0.20)
        self.assertAlmostEqual(threshold_for(10), 0.008)
        self.assertGreater(threshold_for(3), threshold_for(7))
        # small object: seen at high sensitivity, ignored at low
        lo, hi = MotionDetector(1), MotionDetector(10)
        for d in (lo, hi):
            d.feed(frame())
            d.feed(frame(box=(5, 5, 6, 6)))
        self.assertFalse(lo.feed(frame(box=(30, 20, 6, 6)))[1])
        self.assertTrue(hi.feed(frame(box=(30, 20, 6, 6)))[1])


class TestCctvStore(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cyberops_test_cctv_"))
        self.store = CctvStore(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cameras_persist(self):
        cam = self.store.add_camera("Gate", url="rtsp://admin:pw@192.168.1.50/stream1")
        self.store.add_camera("PC Camera", device_id="usb#1")
        self.store.update_camera(cam["id"], sensitivity=3)
        again = CctvStore(self.root)
        self.assertEqual([c["name"] for c in again.cameras], ["Gate", "PC Camera"])
        self.assertEqual(again.camera(cam["id"])["source"], "url")
        self.assertEqual(again.camera(cam["id"])["sensitivity"], 3)
        again.remove_camera(cam["id"])
        self.assertEqual(len(CctvStore(self.root).cameras), 1)

    def test_phone_camera_source(self):
        cam = self.store.add_camera("Gate", source="phone")
        self.assertEqual(CctvStore(self.root).camera(cam["id"])["source"], "phone")

    def test_phone_host_and_app_urls(self):
        from app.views.cctv import phone_host, PHONE_APPS
        self.assertEqual(phone_host(" 192.168.1.23 "), "192.168.1.23")
        self.assertEqual(phone_host("http://192.168.1.23:8080/video"), "192.168.1.23")
        self.assertEqual(phone_host("user:pw@phone.lan:4747"), "phone.lan")
        self.assertEqual(phone_host("192.168.1.23; rm -rf"), "")
        self.assertEqual(PHONE_APPS["IP Webcam (Android)"].format(host="10.0.0.9"), "http://10.0.0.9:8080/video")

    def test_events_and_paths(self):
        cam = self.store.add_camera("PC Camera", device_id="x")
        snap = self.store.snapshot_path(cam["id"])
        self.assertTrue(snap.parent.is_dir())
        self.store.add_event(cam["id"], "motion", score=0.05, snapshot=snap)
        again = CctvStore(self.root)
        self.assertEqual(again.events[0]["camera_name"], "PC Camera")
        self.assertEqual(len(again.events_since(time.time() - 60)), 1)

    def test_prune_removes_old_files_and_events(self):
        cam = self.store.add_camera("PC Camera", device_id="x")
        now = time.time()
        old = self.store.snapshot_path(cam["id"], ts=now - 30 * 86400)
        new = self.store.snapshot_path(cam["id"], ts=now)
        for p in (old, new):
            p.write_bytes(b"jpg")
        os.utime(old, (now - 30 * 86400, now - 30 * 86400))
        self.store.add_event(cam["id"], "motion", snapshot=old, ts=now - 30 * 86400)
        self.store.add_event(cam["id"], "motion", snapshot=new, ts=now)
        self.assertEqual(self.store.prune(days=14, now=now), 1)
        self.assertFalse(old.exists())
        self.assertFalse(old.parent.exists())     # empty day folder removed
        self.assertTrue(new.exists())
        self.assertEqual(len(self.store.events), 1)


if __name__ == "__main__":
    unittest.main()
