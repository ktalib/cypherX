import json
import os
import shutil
import socket
import struct
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.server import discovery as dsc
from app.server.events import EventBus
from app.server.services import ServiceManager

INFO = {"ip": "192.168.1.34", "gwId": "bf1234567890abcdefgh", "active": 2, "ability": 0, "mode": 0,
        "encrypt": True, "productKey": "keyabc123", "version": "3.3"}


def frame_55aa(payload, cmd=0x13):
    body = b"\x00\x00\x00\x00" + payload                      # return code + payload
    header = struct.pack(">IIII", 0x000055AA, 0, cmd, len(body) + 8)
    crc = zlib.crc32(header + body) & 0xFFFFFFFF
    return header + body + struct.pack(">II", crc, 0x0000AA55)


def ecb(data):
    pad = 16 - len(data) % 16
    e = Cipher(algorithms.AES(dsc.TUYA_UDP_KEY), modes.ECB()).encryptor()
    return e.update(data + bytes([pad]) * pad) + e.finalize()


def frame_6699(payload, cmd=0x13):
    iv = os.urandom(12)
    ct = AESGCM(dsc.TUYA_UDP_KEY).encrypt(iv, b"\x00\x00\x00\x00" + payload, None)
    header = struct.pack(">IHIII", 0x00006699, 0, 1, cmd, 12 + len(ct) + 4)
    aad_ct = AESGCM(dsc.TUYA_UDP_KEY).encrypt(iv, b"\x00\x00\x00\x00" + payload, header[4:])
    return header + iv + aad_ct + struct.pack(">I", 0x00009966)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestParsers(unittest.TestCase):
    def test_tuya_v31_plain(self):
        info = dsc.parse_tuya_packet(frame_55aa(json.dumps(dict(INFO, version="3.1")).encode()))
        self.assertEqual(info["gwId"], INFO["gwId"])
        self.assertEqual(info["version"], "3.1")

    def test_tuya_v33_encrypted(self):
        info = dsc.parse_tuya_packet(frame_55aa(ecb(json.dumps(INFO).encode())))
        self.assertEqual(info["ip"], "192.168.1.34")
        dev = dsc.tuya_device(info, "192.168.1.34")
        self.assertEqual(dev["id"], "tuya:bf1234567890abcdefgh")
        self.assertIn("local key", dev["control"])

    def test_tuya_v35_gcm(self):
        info = dsc.parse_tuya_packet(frame_6699(json.dumps(dict(INFO, version="3.5")).encode()))
        self.assertEqual(info["version"], "3.5")

    def test_unknown_encrypted_and_garbage(self):
        junk = frame_55aa(os.urandom(48))
        self.assertEqual(dsc.parse_tuya_packet(junk), {"encrypted": True})
        self.assertIsNone(dsc.parse_tuya_packet(b"hello"))
        self.assertEqual(dsc.tuya_device({"encrypted": True}, "192.168.1.9")["id"], "tuya:192.168.1.9")

    def test_kasa_cipher_and_reply(self):
        msg = '{"system":{"get_sysinfo":{}}}'
        self.assertEqual(dsc.kasa_decrypt(dsc.kasa_encrypt(msg)), msg)
        reply = dsc.kasa_encrypt(json.dumps({"system": {"get_sysinfo": {
            "alias": "Fridge plug", "model": "HS100(UK)", "type": "IOT.SMARTPLUGSWITCH",
            "mac": "50-C7-BF-00-11-22", "relay_state": 1, "deviceId": "80061234"}}}))
        dev = dsc.parse_kasa_reply(reply, "192.168.1.60")
        self.assertEqual((dev["name"], dev["kind"], dev["extra"]["on"]), ("Fridge plug", "plug", True))
        self.assertIsNone(dsc.parse_kasa_reply(b"\x01\x02", "x"))

    def test_http_probe_fingerprints(self):
        def shelly(url, timeout=1.5):
            if url.endswith("/shelly"):
                return {"type": "SHPLG-S", "mac": "A4CF12AABBCC", "auth": False}
            raise OSError
        dev = dsc.probe_http("192.168.1.70", get=shelly)
        self.assertEqual((dev["brand"], dev["kind"], dev["mac"]), ("Shelly", "plug", "A4:CF:12:AA:BB:CC"))

        def tasmota(url, timeout=1.5):
            if "cmnd=Status" in url:
                return {"Status": {"DeviceName": "Gosund SP1", "FriendlyName": ["TV socket"], "Power": 1}}
            raise OSError
        dev = dsc.probe_http("192.168.1.71", get=tasmota)
        self.assertEqual((dev["brand"], dev["name"]), ("Tasmota", "TV socket"))
        self.assertIsNone(dsc.probe_http("192.168.1.72", get=lambda u, timeout=1.5: (_ for _ in ()).throw(OSError())))


class TestBookAndService(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.book = dsc.SmartDeviceBook(self.d / "smart.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_book_link_rename_and_encrypted_fold(self):
        dev = dsc.tuya_device(INFO, "192.168.1.34")
        self.assertTrue(self.book.seen(dev))
        self.assertFalse(self.book.seen(dev))
        self.assertFalse(self.book.seen(dsc.tuya_device({"encrypted": True}, "192.168.1.34")))  # same device
        self.assertEqual(len(self.book.devices), 1)
        self.book.link(dev["id"], "fridge")
        self.book.rename(dev["id"], "Fridge plug")
        other = dict(dsc.tuya_device(dict(INFO, gwId="other"), "192.168.1.35"))
        self.book.seen(other)
        self.book.link(other["id"], "fridge")                     # one plug per appliance
        again = dsc.SmartDeviceBook(self.d / "smart.json")
        self.assertEqual(again.by_item("fridge"), other["id"])
        self.assertEqual(again.label(dev["id"]), "Fridge plug")
        self.assertTrue(again.online(dev["id"]))

    def test_concurrent_sightings_dont_break_saving(self):
        errors = []

        def spam(n):
            try:
                for i in range(30):
                    self.book.seen(dsc.tuya_device(dict(INFO, gwId=f"dev{n}-{i}"), "192.168.1.50"))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=spam, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(dsc.SmartDeviceBook(self.d / "smart.json").devices), 180)

    def test_service_hears_udp_broadcasts_and_kasa(self):
        bus, events = EventBus(), []
        bus.subscribe(events.append)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            tuya_port = probe.getsockname()[1]
        # a fake Kasa plug answering on a local port
        kasa = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        kasa.bind(("127.0.0.1", 0))
        kasa.settimeout(5)

        def kasa_plug():
            try:
                data, addr = kasa.recvfrom(2048)
                if json.loads(dsc.kasa_decrypt(data)) == {"system": {"get_sysinfo": {}}}:
                    kasa.sendto(dsc.kasa_encrypt(json.dumps({"system": {"get_sysinfo": {
                        "alias": "TV plug", "model": "HS103", "type": "IOT.SMARTPLUGSWITCH", "mac": "AA:BB:CC:00:00:01",
                        "relay_state": 0}}})), addr)
            except OSError:
                pass
        threading.Thread(target=kasa_plug, daemon=True).start()

        svc = dsc.DiscoveryService(bus, book=self.book, tuya_ports=(tuya_port,), kasa_port=kasa.getsockname()[1])
        svc._extra_kasa_targets = ("127.0.0.1",)
        m = ServiceManager()
        m.register(svc)
        svc.set_setting("mdns", False)
        svc.set_setting("http_probe", False)
        m.start("discovery")
        try:
            self.assertTrue(wait_for(lambda: svc.status == "running"))
            self.assertTrue(wait_for(lambda: any(d.get("brand") == "TP-Link Kasa" for d in self.book.devices.values())))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                tx.sendto(frame_55aa(ecb(json.dumps(INFO).encode())), ("127.0.0.1", tuya_port))
            self.assertTrue(wait_for(lambda: "tuya:bf1234567890abcdefgh" in self.book.devices))
            self.assertEqual({e["kind"] for e in events}, {"smart"})
            self.assertEqual(len(events), 2)
            self.assertIn("2 smart device(s) known", svc.info()[0])
        finally:
            m.stop_all()
            kasa.close()


if __name__ == "__main__":
    unittest.main()
