"""
Web dashboard: a small HTTP server so phones on the home Wi-Fi can use the
smart home — http://<server-ip>:8080.

  • same accounts as the app (session cookie, 12 h), login rate-limited per address
  • JSON API backed by an `api` object (see app/server/home_api.py) that does the
    real work on the GUI thread
  • a single-page, phone-first UI in app/server/static/index.html
  • refuses to start while the admin account still has the default password

Standard library only (http.server) — nothing extra to install.
"""
import json
import os
import secrets
import socket
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from app.server.services import ThreadService

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SESSION_TTL = 12 * 3600
# public files (no secrets): the page itself and what "Add to Home screen" needs
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}
COOKIE = "cx_session"
MAX_BODY = 64 * 1024
LOGIN_TRIES, LOGIN_LOCK_S = 5, 60


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Sessions:
    def __init__(self):
        self._s = {}

    def create(self, user):
        token = secrets.token_urlsafe(32)
        self._s[token] = {"user": user, "expires": time.time() + SESSION_TTL}
        return token

    def get(self, token):
        s = self._s.get(token or "")
        if not s:
            return None
        if s["expires"] < time.time():
            self._s.pop(token, None)
            return None
        return s["user"]

    def drop(self, token):
        self._s.pop(token or "", None)

    def clear(self):
        n = len(self._s)
        self._s.clear()
        return n

    def count(self):
        now = time.time()
        return sum(1 for s in self._s.values() if s["expires"] >= now)


class LoginLimiter:
    def __init__(self):
        self._fails = {}

    def blocked(self, ip, now=None):
        now = time.time() if now is None else now
        n, until = self._fails.get(ip, (0, 0))
        return until > now

    def fail(self, ip, now=None):
        now = time.time() if now is None else now
        n, _ = self._fails.get(ip, (0, 0))
        n += 1
        self._fails[ip] = (0, now + LOGIN_LOCK_S) if n >= LOGIN_TRIES else (n, 0)

    def ok(self, ip):
        self._fails.pop(ip, None)


def lan_addresses():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


class WebApp:
    """Routing + auth, independent of the socket server (unit-testable)."""

    def __init__(self, auth, api, log=lambda *a, **k: None):
        self.auth = auth
        self.api = api
        self.log = log
        self.sessions = Sessions()
        self.limiter = LoginLimiter()
        self.requests = 0

    def handle(self, method, path, query, body, token, ip):
        """Returns (status, content_type, payload_bytes, set_cookie or None)."""
        self.requests += 1
        try:
            if method == "GET" and path in STATIC_FILES:
                name, ctype = STATIC_FILES[path]
                with open(os.path.join(STATIC_DIR, name), "rb") as f:
                    return 200, ctype, f.read(), None
            if path == "/api/login" and method == "POST":
                return self._login(body, ip)
            user = self.sessions.get(token)
            if path == "/api/logout":
                self.sessions.drop(token)
                return 200, "application/json", b'{"ok":true}', f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"
            if not path.startswith("/api/"):
                raise ApiError(404, "Not found")
            if user is None:
                raise ApiError(401, "Please sign in")
            result = self._route(method, path, query, body, user)
            if isinstance(result, tuple):          # (content_type, bytes)
                return 200, result[0], result[1], None
            return 200, "application/json", json.dumps(result).encode("utf-8"), None
        except ApiError as e:
            return e.status, "application/json", json.dumps({"error": str(e)}).encode(), None
        except TimeoutError as e:
            return 503, "application/json", json.dumps({"error": str(e)}).encode(), None
        except Exception as e:  # never leak a traceback to the browser
            self.log(f"Error on {method} {path}: {e}", "error")
            return 500, "application/json", b'{"error":"Server error"}', None

    def _login(self, body, ip):
        if self.limiter.blocked(ip):
            raise ApiError(429, f"Too many wrong tries. Wait {LOGIN_LOCK_S} s.")
        data = _json(body)
        user = self.auth.authenticate(str(data.get("username", "")), str(data.get("password", "")))
        if not user:
            self.limiter.fail(ip)
            self.log(f"Failed sign-in for '{data.get('username', '')}' from {ip}", "warn")
            raise ApiError(401, "Wrong user name or password")
        self.limiter.ok(ip)
        token = self.sessions.create(user)
        self.log(f"{user['username']} signed in from {ip}")
        cookie = f"{COOKIE}={token}; Max-Age={SESSION_TTL}; Path=/; HttpOnly; SameSite=Strict"
        return 200, "application/json", json.dumps({"user": user}).encode(), cookie

    def _route(self, method, path, query, body, user):
        parts = [p for p in path.split("/") if p][1:]       # drop "api"
        api = self.api
        if method == "GET":
            if parts == ["me"]:
                return {"user": user}
            if parts == ["status"]:
                return api.status(user)
            if parts == ["bills"]:
                return api.bills()
            if parts == ["groceries"]:
                return api.groceries()
            if parts == ["snapshot.jpg"]:
                data = api.snapshot_jpeg(query.get("cam", [None])[0])
                if not data:
                    raise ApiError(404, "No snapshot yet")
                return ("image/jpeg", data)
            if parts == ["server"]:
                _need_root(user)
                return api.server()
        if method == "POST":
            data = _json(body)
            who = user["username"]
            if len(parts) == 3 and parts[0] == "devices" and parts[2] == "toggle":
                return api.toggle(parts[1], who)
            if parts == ["alloff"]:
                return api.all_off(who)
            if parts == ["arm"]:
                return api.set_armed(bool(data.get("on")), who)
            if parts == ["meter", "reading"]:
                return api.add_reading(_number(data, "units", 0, 100000), who)
            if parts == ["meter", "token"]:
                return api.add_token(_number(data, "amount", 0, 10_000_000), _number(data, "units", 0.1, 100000), who)
            if len(parts) == 3 and parts[0] == "groceries" and parts[2] == "toggle":
                return api.toggle_grocery(int(parts[1]), who)
        raise ApiError(404, "Not found")


def _need_root(user):
    if user.get("role") != "root":
        raise ApiError(403, "Root access needed")


def _json(body):
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "Bad JSON")
    if not isinstance(data, dict):
        raise ApiError(400, "Bad JSON")
    return data


def _number(data, key, lo, hi):
    try:
        v = float(data.get(key))
    except (TypeError, ValueError):
        raise ApiError(400, f"'{key}' must be a number")
    if not lo <= v <= hi:
        raise ApiError(400, f"'{key}' must be between {lo:g} and {hi:g}")
    return v


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CYPHER-X"
        sys_version = ""

        def _serve(self, method):
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            body = self.rfile.read(length) if length else b""
            if method == "POST" and body and "application/json" not in (self.headers.get("Content-Type") or ""):
                status, ctype, payload, cookie = 415, "application/json", b'{"error":"Use JSON"}', None
            else:
                token = None
                if self.headers.get("Cookie"):
                    c = SimpleCookie(self.headers["Cookie"])
                    if COOKIE in c:
                        token = c[COOKIE].value
                status, ctype, payload, cookie = app.handle(method, url.path, parse_qs(url.query), body,
                                                            token, self.client_address[0])
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def log_message(self, fmt, *args):     # quiet; errors go to the service log
            pass

    return Handler


class WebService(ThreadService):
    id = "web"
    title = "Web dashboard"
    description = "Use the smart home from any phone or laptop on your Wi-Fi, with your CYPHER-X account."
    icon = "network_monitor"
    default_enabled = False
    settings_schema = [("port", "Port", "int", 8080, "Open http://<this PC's IP>:<port> on your phone")]

    def __init__(self, auth, api):
        super().__init__()
        self.auth = auth
        self.app = WebApp(auth, api, log=self.log)
        self._httpd = None

    def can_start(self):
        if self.auth.uses_default_password():
            return False, ("Change the admin password first (Settings → Accounts). The dashboard is "
                           "reachable from every device on your Wi-Fi.")
        return True, ""

    def run(self, stop):
        port = int(self.setting("port") or 8080)
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(self.app))
        except OSError as e:
            raise RuntimeError(f"Port {port} is busy or blocked ({e.strerror or e})")
        self._httpd.daemon_threads = True
        self.mark_running()
        urls = ", ".join(f"http://{ip}:{port}" for ip in lan_addresses()) or f"http://localhost:{port}"
        self.log(f"Serving on {urls}")
        self._httpd.serve_forever(poll_interval=0.5)
        self._httpd.server_close()

    def on_stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None

    def urls(self):
        port = int(self.setting("port") or 8080)
        return [f"http://{ip}:{port}" for ip in lan_addresses()] or [f"http://localhost:{port}"]

    def info(self):
        lines = ["Open on your phone: " + "  ·  ".join(self.urls())]
        lines.append(f"{self.app.sessions.count()} signed-in session(s) · {self.app.requests} requests served")
        if self.auth.uses_default_password():
            lines.append("Blocked until the admin password is changed.")
        lines.append("Windows may ask to allow CYPHER-X through the firewall the first time — allow Private networks.")
        return lines

    def actions(self):
        def sign_out_all():
            return f"Signed out {self.app.sessions.clear()} session(s)."
        return [("Sign out all web sessions", sign_out_all)]
