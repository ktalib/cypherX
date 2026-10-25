"""Spotify Connect authorization and playback controls for the desktop app."""
import base64
import hashlib
import json
import secrets
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import (
    QHostAddress, QNetworkAccessManager, QNetworkReply, QNetworkRequest, QTcpServer
)
from PySide6.QtGui import QDesktopServices


API_URL = "https://api.spotify.com/v1"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing"


def normalize_spotify_uri(value):
    """Return a Spotify track, album, artist, or playlist URI, or None."""
    value = (value or "").strip()
    if value.startswith("spotify:"):
        parts = value.split(":")
        if len(parts) == 3 and parts[1] in {"track", "album", "artist", "playlist"} and parts[2]:
            return value
        return None
    url = QUrl(value)
    if url.scheme().lower() != "https" or url.host().lower() != "open.spotify.com":
        return None
    parts = [part for part in url.path().split("/") if part]
    types = {"track", "album", "artist", "playlist"}
    if parts and parts[0] not in types and len(parts) > 1:
        parts.pop(0)
    if len(parts) >= 2 and parts[0] in types:
        return f"spotify:{parts[0]}:{parts[1]}"
    return None


class SpotifyConnect(QObject):
    connected = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._server = None
        self._client_id = ""
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0
        self._verifier = ""
        self._state = ""
        self._redirect_uri = ""
        self._refreshing = False
        self._waiting = []
        self._auth_timeout = QTimer(self)
        self._auth_timeout.setSingleShot(True)
        self._auth_timeout.timeout.connect(self._cancel_auth)

    @property
    def is_connected(self):
        return bool(self._access_token)

    def authorize(self, client_id):
        client_id = (client_id or "").strip()
        if not client_id:
            self.error.emit("Enter a Spotify Client ID first.")
            return
        self._stop_server()
        self._auth_timeout.stop()
        self._client_id = client_id
        server = QTcpServer(self)
        if not server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            server.deleteLater()
            self.error.emit(f"Couldn't start the local Spotify sign-in callback: {server.errorString()}")
            return
        self._server = server
        server.newConnection.connect(self._on_callback_connection)
        port = server.serverPort()
        self._redirect_uri = f"http://127.0.0.1:{port}/callback"
        self._state = secrets.token_urlsafe(24)
        self._verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self._verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        query = urlencode({
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
            "state": self._state,
        })
        self._auth_timeout.start(180_000)
        if not QDesktopServices.openUrl(QUrl(f"{AUTHORIZE_URL}?{query}")):
            self._stop_server()
            self._auth_timeout.stop()
            self.error.emit("Couldn't open the Spotify sign-in page in your browser.")

    def _on_callback_connection(self):
        socket = self._server.nextPendingConnection() if self._server else None
        if socket is None:
            return
        buffer = bytearray()

        def receive_request():
            buffer.extend(bytes(socket.readAll()))
            if b"\r\n" in buffer:
                request_line = bytes(buffer).split(b"\r\n", 1)[0]
                self._handle_callback(socket, request_line)

        socket.readyRead.connect(receive_request)

    def _handle_callback(self, socket, request_line):
        if socket is None:
            return
        request_line = request_line.decode("latin-1", errors="replace").strip()
        request_parts = request_line.split(" ")
        target = request_parts[1] if len(request_parts) > 1 else ""
        callback_url = QUrl(f"http://127.0.0.1{target}")
        query = QUrlQuery(callback_url)
        state = query.queryItemValue("state")
        code = query.queryItemValue("code")
        error = query.queryItemValue("error")
        body = (b"Spotify sign-in complete. You can close this tab."
                if state == self._state and code
                else b"Spotify sign-in failed. Return to CYPHER-X and try again.")
        response = (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n"
                    b"Connection: close\r\nContent-Length: " + str(len(body)).encode("ascii")
                    + b"\r\n\r\n" + body)
        socket.write(response)
        socket.flush()
        socket.disconnectFromHost()
        self._stop_server()
        self._auth_timeout.stop()
        if state != self._state:
            self.error.emit("Spotify sign-in state check failed. Please try again.")
        elif error:
            self.error.emit(f"Spotify sign-in was declined: {error}")
        elif not code:
            self.error.emit("Spotify did not return an authorization code.")
        else:
            self._exchange_code(code)

    def _exchange_code(self, code):
        self._token_request({
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "code": code,
            "redirect_uri": self._redirect_uri,
            "code_verifier": self._verifier,
        }, self._accept_token)

    def _accept_token(self, data):
        if not data or not data.get("access_token"):
            return
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._expires_at = data.get("expires_in", 3600) + self._now()
        self.connected.emit()

    def _token_request(self, fields, callback):
        request = QNetworkRequest(QUrl(TOKEN_URL))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          "application/x-www-form-urlencoded")
        request.setTransferTimeout(20_000)
        reply = self._network.post(request, urlencode(fields).encode("utf-8"))

        def finished():
            payload = bytes(reply.readAll())
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            reply.deleteLater()
            try:
                data = json.loads(payload.decode("utf-8")) if payload else {}
            except (UnicodeDecodeError, ValueError):
                data = {}
            if reply.error() != QNetworkReply.NetworkError.NoError or not 200 <= (status or 0) < 300:
                detail = data.get("error_description") or data.get("error") or reply.errorString()
                self.error.emit(f"Spotify authorization failed: {detail}")
                callback(None)
                return
            callback(data)

        reply.finished.connect(finished)

    def _ensure_token(self, callback):
        if not self._access_token:
            callback(False)
            self.error.emit("Connect Spotify before using its playback controls.")
            return
        if self._expires_at - self._now() > 60:
            callback(True)
            return
        if not self._refresh_token:
            self._access_token = ""
            callback(False)
            self.error.emit("Spotify sign-in expired. Connect again.")
            return
        self._waiting.append(callback)
        if self._refreshing:
            return
        self._refreshing = True

        def refreshed(data):
            self._refreshing = False
            if data and data.get("access_token"):
                self._accept_token(data)
                waiting, self._waiting = self._waiting, []
                for done in waiting:
                    done(True)
            else:
                self._access_token = ""
                waiting, self._waiting = self._waiting, []
                for done in waiting:
                    done(False)

        self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
        }, refreshed)

    def _api(self, method, path, callback=None, body=None, retried=False):
        callback = callback or (lambda _data, _error: None)

        def send(ready):
            if not ready:
                callback(None, "Connect Spotify and try again.")
                return
            request = QNetworkRequest(QUrl(f"{API_URL}{path}"))
            request.setRawHeader(b"Authorization", f"Bearer {self._access_token}".encode("ascii"))
            request.setTransferTimeout(20_000)
            payload = b""
            if body is not None:
                request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
                payload = json.dumps(body).encode("utf-8")
            reply = self._network.sendCustomRequest(request, method.encode("ascii"), payload)

            def finished():
                raw = bytes(reply.readAll())
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                network_error = reply.error() != QNetworkReply.NetworkError.NoError
                error_text = reply.errorString()
                reply.deleteLater()
                if status == 401 and not retried and self._refresh_token:
                    self._expires_at = 0
                    self._ensure_token(lambda ok: self._api(
                        method, path, callback, body, retried=True
                    ) if ok else callback(None, "Spotify sign-in expired. Connect again."))
                    return
                try:
                    data = json.loads(raw.decode("utf-8")) if raw else None
                except (UnicodeDecodeError, ValueError):
                    data = None
                if network_error or status is None or not (200 <= status < 300 or status == 204):
                    message = error_text
                    if isinstance(data, dict):
                        detail = data.get("error")
                        if isinstance(detail, dict):
                            message = detail.get("message", message)
                    callback(None, f"Spotify request failed ({status or 'network error'}): {message}")
                    return
                callback(data, "")

            reply.finished.connect(finished)

        self._ensure_token(send)

    def play_uri(self, uri, callback=None):
        uri = normalize_spotify_uri(uri)
        if not uri:
            self.error.emit("Use a Spotify track, album, artist, or playlist link or URI.")
            if callback:
                callback(False)
            return
        kind = uri.split(":")[1]
        body = {"uris": [uri]} if kind == "track" else {"context_uri": uri}
        self._api("PUT", "/me/player/play", lambda _data, error: self._command_done(error, callback), body)

    def pause(self, callback=None):
        self._command("PUT", "/me/player/pause", callback)

    def resume(self, callback=None):
        self._command("PUT", "/me/player/play", callback)

    def next(self, callback=None):
        self._command("POST", "/me/player/next", callback)

    def previous(self, callback=None):
        self._command("POST", "/me/player/previous", callback)

    def seek(self, position_ms, callback=None):
        self._command("PUT", f"/me/player/seek?position_ms={max(0, int(position_ms))}", callback)

    def set_volume(self, volume, callback=None):
        self._command("PUT", f"/me/player/volume?volume_percent={max(0, min(100, int(volume)))}",
                      callback)

    def playback_state(self, callback):
        self._api("GET", "/me/player", lambda data, error: callback(data or {}, error))

    def _command(self, method, path, callback=None):
        self._api(method, path, lambda _data, error: self._command_done(error, callback))

    def _command_done(self, error, callback):
        if error:
            self.error.emit(error)
        if callback:
            callback(not error)

    def disconnect(self):
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0

    def _cancel_auth(self):
        self._stop_server()
        self.error.emit("Spotify sign-in timed out.")

    def _stop_server(self):
        if self._server:
            self._server.close()
            self._server.deleteLater()
            self._server = None

    @staticmethod
    def _now():
        from time import time
        return int(time())
