import json
import unittest
from app.server.web import WebApp, LoginLimiter, LOGIN_TRIES


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


if __name__ == "__main__":
    unittest.main()
