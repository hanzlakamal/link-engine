"""Users, roles, sessions, 2FA, login throttling and request hardening.

Roles (low -> high): client (read-only, own projects) < builder (works on assigned projects)
< manager (assigns, approves, configures all projects) < admin (everything + users).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import socket
import struct
import time
from urllib.parse import urlparse

from app.config import base_settings

ROLES = ["client", "builder", "manager", "admin"]
RANK = {r: i for i, r in enumerate(ROLES)}
SESSION_DAYS = 7


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 310_000).hex()
    return f"pbkdf2${salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 310_000).hex(), h)


def password_problem(pw: str) -> str:
    if len(pw) < 12:
        return "Password must be at least 12 characters."
    if pw.lower() in {"password1234", "admin1234567", "qwertyuiop12"} or len(set(pw)) < 6:
        return "Password is too easy to guess."
    return ""


# ---------------------------------------------------------------- sessions
def session_token(user, issued: int | None = None) -> str:
    """uid.issued.sig — tied to the password hash, so a password change logs out everywhere."""
    issued = issued or int(time.time())
    msg = f"{user.id}:{issued}:{user.password_hash[-16:]}"
    sig = hmac.new(base_settings().secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{user.id}.{issued}.{sig}"


def user_from_token(db, token: str | None):
    from app.models import User

    try:
        uid, issued, _ = (token or "").split(".")
        uid_i, issued_i = int(uid), int(issued)
    except ValueError:
        return None
    if time.time() - issued_i > SESSION_DAYS * 86400:
        return None
    u = db.get(User, uid_i)
    if u is None or not u.active or not hmac.compare_digest(session_token(u, issued_i), token):
        return None
    return u


# ---------------------------------------------------------------- 2FA (RFC 6238 TOTP)
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_now(secret: str, t: float | None = None, step: int = 30) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = struct.pack(">Q", int((t or time.time()) // step))
    h = hmac.new(key, counter, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def verify_totp(secret: str, code: str) -> bool:
    code = re.sub(r"\D", "", code or "")
    now = time.time()
    return len(code) == 6 and any(hmac.compare_digest(totp_now(secret, now + d * 30), code) for d in (-1, 0, 1))


def otpauth_uri(secret: str, email: str, issuer: str) -> str:
    from urllib.parse import quote

    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}"


# ---------------------------------------------------------------- login throttling
_fails: dict[str, list[float]] = {}
LOCK_WINDOW, MAX_PER_EMAIL, MAX_PER_IP = 15 * 60, 5, 20


def _recent(key: str) -> list[float]:
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < LOCK_WINDOW]
    return _fails[key]


def login_locked(email: str, ip: str) -> bool:
    return len(_recent(f"e:{email}")) >= MAX_PER_EMAIL or len(_recent(f"i:{ip}")) >= MAX_PER_IP


def login_failed(email: str, ip: str) -> None:
    for k in (f"e:{email}", f"i:{ip}"):
        _recent(k).append(time.time())


def login_ok(email: str) -> None:
    _fails.pop(f"e:{email}", None)


# ---------------------------------------------------------------- permissions
def at_least(user, role: str) -> bool:
    return user is not None and RANK.get(user.role, -1) >= RANK[role]


def can_see_project(user, project_id: int) -> bool:
    if at_least(user, "manager"):
        return True
    return any(m.project_id == project_id for m in user.memberships)


# (method, path regex) -> minimum role. First match wins. Unlisted GETs need "client".
RULES: list[tuple[str, str, str]] = [
    ("*", r"^/account", "client"),
    ("*", r"^/(settings|team|audit)", "admin"),
    ("POST", r"^/projects$", "manager"),
    ("POST", r"^/p/\d+/(settings|accounts|competitors|playbooks|jobs|import|pins)", "manager"),
    ("POST", r"^/p/\d+/(opportunities|content|tasks|articles|contacts|outreach|links)", "builder"),
    ("POST", r".*", "admin"),
]


def required_role(method: str, path: str) -> str:
    for m, rx, role in RULES:
        if (m == "*" or m == method) and re.search(rx, path):
            return role
    return "client"


def project_id_from_path(path: str) -> int | None:
    m = re.match(r"^/(?:p|api/projects)/(\d+)", path)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- request hardening
def same_origin(origin: str | None, referer: str | None, host: str) -> bool:
    """CSRF guard: browsers always send Origin on cross-site POSTs; it must match our host."""
    src = origin or referer
    if not src or src == "null":
        return origin is None and referer is None  # non-browser clients (no cookies cross-site)
    return (urlparse(src).netloc or "").lower() == host.lower()


SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; "
                                "base-uri 'none'; object-src 'none'"),
}


def assert_public_url(url: str) -> str:
    """SSRF guard for server-side fetches: https/http to public IPs only."""
    p = urlparse(url if "://" in url else "https://" + url)
    if p.scheme not in ("https", "http") or not p.hostname:
        raise ValueError("URL must be http(s) with a host")
    for info in socket.getaddrinfo(p.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"Refusing to fetch internal address ({p.hostname})")
    return url


def check_production_secrets() -> None:
    s = base_settings()
    if s.database_url.startswith("postgresql") and (s.secret_key in ("", "dev-only-change-me") or len(s.secret_key) < 32):
        raise RuntimeError("Refusing to start: set a strong SECRET_KEY (32+ chars) in production.")
