import json
import shutil
import ssl
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from app.server.web import WebApp, LoginLimiter, LOGIN_TRIES, MAX_FRAME, _Server, make_handler


class FakeAuth:
    def authenticate(self, u, p):
        if (u, p) == ("admin", "s3cret"):
            return {"id": 1, "username": "admin", "role": "root"}
        if (u, p) == ("mum", "1234"):
            return {"id": 2, "username": "mum", "role": "user"}
        return None

    def uses_default_password(self):
        return False


class FakeApi:
    def __init__(self):
        self.calls = []

    def status(self, user):
        return {"devices": [], "ok": True}

    def toggle(self, item_id, who):
        self.calls.append(("toggle", item_id, who))
        return {"id": item_id, "on": True}

    def add_reading(self, units, who):
        self.calls.append(("reading", units, who))
        return {"units_left": units}

    def server(self):
        return {"cpu": 1}

    def snapshot_jpeg(self, cam):
        return b"\xff\xd8jpeg"

    def phonecam_start(self, name, who):
        self.calls.append(("pc_start", name, who))
        return {"id": "cam_1", "name": name}

    def phonecam_frame(self, cam_id, jpeg):
        self.calls.append(("pc_frame", cam_id, len(jpeg)))
        return {"ok": True, "armed": False, "motion": False}

    def phonecam_stop(self, cam_id, who):
        self.calls.append(("pc_stop", cam_id, who))
        return {"ok": True}


def call(app, method, path, body=None, token=None, ip="192.168.1.5"):
    raw = json.dumps(body).encode() if body is not None else b""
    status, ctype, payload, cookie = app.handle(method, path, {}, raw, token, ip)
    data = json.loads(payload) if ctype == "application/json" else payload
    return status, data, cookie


def login(app, u="admin", p="s3cret"):
    status, data, cookie = call(app, "POST", "/api/login", {"username": u, "password": p})
    assert status == 200, data
    return cookie.split(";")[0].split("=", 1)[1]


class TestWeb(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.app = WebApp(FakeAuth(), self.api)

    def test_index_and_auth_required(self):
        status, page, _ = call(self.app, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"CYPHER-X", page)
        self.assertEqual(call(self.app, "GET", "/api/status")[0], 401)
        self.assertEqual(call(self.app, "GET", "/api/status", token="forged")[0], 401)

    def test_login_session_and_cookie_flags(self):
        status, data, cookie = call(self.app, "POST", "/api/login", {"username": "admin", "password": "s3cret"})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        token = cookie.split(";")[0].split("=", 1)[1]
        self.assertEqual(call(self.app, "GET", "/api/status", token=token)[1]["ok"], True)
        call(self.app, "GET", "/api/logout", token=token)
        self.assertEqual(call(self.app, "GET", "/api/status", token=token)[0], 401)

    def test_actions_and_validation(self):
        token = login(self.app)
        self.assertEqual(call(self.app, "POST", "/api/devices/tv/toggle", {}, token)[0], 200)
        self.assertEqual(self.api.calls[-1], ("toggle", "tv", "admin"))
        self.assertEqual(call(self.app, "POST", "/api/meter/reading", {"units": "abc"}, token)[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/meter/reading", {"units": -5}, token)[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/meter/reading", {"units": 42.5}, token)[0], 200)
        status, data, _ = call(self.app, "GET", "/api/snapshot.jpg", token=token)
        self.assertEqual((status, data[:2]), (200, b"\xff\xd8"))
        self.assertEqual(call(self.app, "GET", "/api/nope", token=token)[0], 404)

    def test_server_page_is_root_only(self):
        self.assertEqual(call(self.app, "GET", "/api/server", token=login(self.app))[0], 200)
        self.assertEqual(call(self.app, "GET", "/api/server", token=login(self.app, "mum", "1234"))[0], 403)

    def test_login_rate_limit(self):
        for _ in range(LOGIN_TRIES):
            self.assertEqual(call(self.app, "POST", "/api/login", {"username": "admin", "password": "x"})[0], 401)
        self.assertEqual(call(self.app, "POST", "/api/login", {"username": "admin", "password": "s3cret"})[0], 429)
        # another address is not blocked
        self.assertEqual(call(self.app, "POST", "/api/login", {"username": "admin", "password": "s3cret"},
                              ip="192.168.1.9")[0], 200)
        lim = LoginLimiter()
        for _ in range(LOGIN_TRIES):
            lim.fail("a", now=0)
        self.assertTrue(lim.blocked("a", now=1))
        self.assertFalse(lim.blocked("a", now=1000))


    def test_phone_camera_routes(self):
        token = login(self.app, "mum", "1234")              # any signed-in user may add a phone camera
        self.assertEqual(call(self.app, "GET", "/api/phonecam", token=token)[1], {"https_port": 0})
        self.app.https_port = 8443
        self.assertEqual(call(self.app, "GET", "/api/phonecam", token=token)[1]["https_port"], 8443)
        self.assertEqual(call(self.app, "POST", "/api/phonecam/start", {"name": "  Front \n  gate " + "x" * 80}, token)[1]["id"],
                         "cam_1")
        self.assertEqual(self.api.calls[-1][1], ("Front gate " + "x" * 80)[:40])
        call(self.app, "POST", "/api/phonecam/start", {}, token)
        self.assertEqual(self.api.calls[-1][1], "Phone camera")
        jpeg = b"\xff\xd8" + bytes(range(256)) * 4                  # binary: must not be parsed as JSON
        status, _, _, _ = self.app.handle("POST", "/api/phonecam/cam_1/frame", {}, jpeg, token, "1.2.3.4")
        self.assertEqual(status, 200)
        self.assertEqual(self.api.calls[-1], ("pc_frame", "cam_1", len(jpeg)))
        self.assertEqual(self.app.handle("POST", "/api/phonecam/cam_1/frame", {}, b"", token, "1.2.3.4")[0], 400)
        self.assertEqual(self.app.handle("POST", "/api/phonecam/cam_1/frame", {}, jpeg, None, "1.2.3.4")[0], 401)
        self.assertEqual(call(self.app, "POST", "/api/phonecam/cam_1/stop", {}, token)[0], 200)
        self.assertEqual(self.api.calls[-1], ("pc_stop", "cam_1", "mum"))


class TestHttps(unittest.TestCase):
    """The real socket server over TLS with a certificate made by app.server.tls."""

    @classmethod
    def setUpClass(cls):
        from app.server.tls import ensure_certificate, server_context
        cls.dir = tempfile.mkdtemp(prefix="cyberops_test_tls_")
        cls.cert, key = ensure_certificate([], folder=cls.dir)
        cls.api = FakeApi()
        cls.app = WebApp(FakeAuth(), cls.api)
        cls.srv = _Server(("127.0.0.1", 0), make_handler(cls.app))
        cls.srv.socket = server_context(cls.cert, key).wrap_socket(cls.srv.socket, server_side=True,
                                                                     do_handshake_on_connect=False)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"https://127.0.0.1:{cls.srv.server_address[1]}"
        cls.ctx = ssl.create_default_context(cafile=cls.cert)     # trust our own certificate, verify normally

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def req(self, path, data=None, ctype=None, token=None):
        r = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        if ctype:
            r.add_header("Content-Type", ctype)
        if token:
            r.add_header("Cookie", f"cx_session={token}")
        try:
            with urllib.request.urlopen(r, context=self.ctx, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError:            # refused before the upload finished (sent 413, then closed)
            return 413, b""

    def test_page_and_frame_upload_over_tls(self):
        self.assertEqual(self.req("/")[0], 200)
        token = login(self.app)
        jpeg = b"\xff\xd8" + b"\0" * 200_000                 # bigger than a JSON body may be
        self.assertEqual(self.req("/api/phonecam/cam_1/frame", jpeg, "image/jpeg", token)[0], 200)
        self.assertEqual(self.api.calls[-1], ("pc_frame", "cam_1", len(jpeg)))
        self.assertEqual(self.req("/api/phonecam/cam_1/frame", jpeg, "application/json", token)[0], 415)
        self.assertEqual(self.req("/api/meter/reading", jpeg, "application/json", token)[0], 413)
        self.assertEqual(self.req("/api/phonecam/cam_1/frame", b"\0" * (MAX_FRAME + 1), "image/jpeg", token)[0], 413)


class TestCertificate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cyberops_test_cert_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reused_until_the_address_changes(self):
        from app.server.tls import ensure_certificate
        def read(path):
            with open(path, "rb") as f:
                return f.read()
        cert, _ = ensure_certificate(["192.168.1.20"], folder=self.dir)
        first = read(cert)
        ensure_certificate(["192.168.1.20"], folder=self.dir)
        self.assertEqual(read(cert), first)
        ensure_certificate(["192.168.1.31"], folder=self.dir)     # PC got a new address → new certificate
        self.assertNotEqual(read(cert), first)


if __name__ == "__main__":
    unittest.main()
