from __future__ import annotations

import hashlib
import hmac
import secrets

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def rate_limit_bytes_per_second(mbps: int) -> int:
    if mbps <= 0:
        return 0
    return int(mbps * 1_000_000 / 8)


def format_frp_bandwidth(mbps: int) -> str:
    """Convert Mbps to frp's bandwidth-limit string (frp KB = 1024 bytes)."""
    bytes_per_second = rate_limit_bytes_per_second(mbps)
    if bytes_per_second <= 0:
        return ""
    return f"{bytes_per_second / 1024:.4f}KB"
