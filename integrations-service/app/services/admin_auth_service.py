"""Single-admin auth: password check, signed session cookie, CSRF token, login throttling."""
import base64
import hashlib
import hmac
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from ..errors import ConfigError, TooManyAttempts

ITERATIONS = 600_000
MAX_FAILURES = 5
WINDOW_SECONDS = 300


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2:{ITERATIONS}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, digest_hex = stored.split(":")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class AdminSession:
    sid: str
    expires_at: float


class AdminAuthService:
    def __init__(self, password_hash: str, session_secret: str, ttl_seconds: int, clock=time.time):
        self._hash = password_hash
        self._secret = session_secret.encode()
        self._ttl = ttl_seconds
        self._clock = clock
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)

    @property
    def configured(self) -> bool:
        return bool(self._hash and self._secret)

    def _sign(self, data: str) -> str:
        return hmac.new(self._secret, data.encode(), hashlib.sha256).hexdigest()

    def check_throttle(self, client: str) -> None:
        q = self._failures[client]
        while q and self._clock() - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= MAX_FAILURES:
            raise TooManyAttempts("Too many failed logins; try again in a few minutes")

    def login(self, client: str, password: str) -> Optional[Tuple[str, str]]:
        """Returns (cookie_value, csrf) on success, None on a wrong password."""
        if not self.configured:
            raise ConfigError("ADMIN_PASSWORD_HASH / ADMIN_SESSION_SECRET are not set")
        self.check_throttle(client)
        if not verify_password(password, self._hash):
            self._failures[client].append(self._clock())
            return None
        self._failures.pop(client, None)
        payload = base64.urlsafe_b64encode(json.dumps(
            {"sid": os.urandom(8).hex(), "exp": self._clock() + self._ttl}).encode()).decode()
        cookie = f"{payload}.{self._sign(payload)}"
        return cookie, self.csrf_for(self.read(cookie))

    def read(self, cookie: Optional[str]) -> Optional[AdminSession]:
        if not cookie or "." not in cookie or not self.configured:
            return None
        payload, sig = cookie.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload.encode()))
            session = AdminSession(data["sid"], float(data["exp"]))
        except (ValueError, KeyError):
            return None
        return session if session.expires_at > self._clock() else None

    def csrf_for(self, session: Optional[AdminSession]) -> str:
        return self._sign("csrf:" + session.sid) if session else ""
