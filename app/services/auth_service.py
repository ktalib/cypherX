"""
Accounts for the CypherX server: who may sign in and what they may open.

Roles
  root   full access, including the Server (PC / OS) tools and user management
  user   Smart Home and Apps only

On first run a single root account is created: admin / admin. The login screen
and Settings keep reminding until that password is changed.

Passwords are stored as salted PBKDF2-SHA256 hashes in the app's SQLite
database (table `users`), never in plain text.
"""
import hashlib
import hmac
import os
from datetime import datetime

ROOT = "root"
USER = "user"
ROLES = (ROOT, USER)

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
ITERATIONS = 200_000


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


class AuthError(Exception):
    pass


class AuthService:
    def __init__(self, db):
        self.db = db
        with db._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            """)
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
                conn.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                             (DEFAULT_USERNAME, hash_password(DEFAULT_PASSWORD), ROOT, _now()))
            conn.commit()

    # ------------------------------------------------------------ queries --

    def users(self):
        with self.db._get_connection() as conn:
            rows = conn.execute("SELECT id, username, role, created_at, last_login FROM users "
                                "ORDER BY role = 'root' DESC, username").fetchall()
        return [dict(r) for r in rows]

    def _row(self, username):
        with self.db._get_connection() as conn:
            r = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        return dict(r) if r else None

    def uses_default_password(self, username=DEFAULT_USERNAME):
        r = self._row(username)
        return bool(r) and verify_password(DEFAULT_PASSWORD, r["password_hash"])

    # ------------------------------------------------------------- sign in --

    def authenticate(self, username, password):
        """Returns the user (id, username, role) or None."""
        r = self._row(username or "")
        if r is None:
            hash_password(password or "")       # same cost whether or not the name exists
            return None
        if not verify_password(password or "", r["password_hash"]):
            return None
        with self.db._get_connection() as conn:
            conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (_now(), r["id"]))
            conn.commit()
        return {"id": r["id"], "username": r["username"], "role": r["role"]}

    # ----------------------------------------------------------- changes --

    def change_password(self, username, old_password, new_password):
        if not self.authenticate(username, old_password):
            raise AuthError("The current password is wrong.")
        self._set_password(username, new_password)

    def reset_password(self, username, new_password):
        """Root setting another user's password."""
        if not self._row(username):
            raise AuthError("No such user.")
        self._set_password(username, new_password)

    def _set_password(self, username, new_password):
        if len(new_password) < 4:
            raise AuthError("Use at least 4 characters.")
        with self.db._get_connection() as conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                         (hash_password(new_password), username))
            conn.commit()

    def add_user(self, username, password, role=USER):
        username = (username or "").strip()
        if not username or any(c.isspace() for c in username):
            raise AuthError("User names can't be empty or contain spaces.")
        if role not in ROLES:
            raise AuthError("Unknown role.")
        if self._row(username):
            raise AuthError(f"'{username}' already exists.")
        if len(password) < 4:
            raise AuthError("Use at least 4 characters.")
        with self.db._get_connection() as conn:
            conn.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                         (username, hash_password(password), role, _now()))
            conn.commit()

    def remove_user(self, username):
        r = self._row(username)
        if not r:
            raise AuthError("No such user.")
        if r["role"] == ROOT and sum(1 for u in self.users() if u["role"] == ROOT) <= 1:
            raise AuthError("The last root account can't be removed.")
        with self.db._get_connection() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (r["id"],))
            conn.commit()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
