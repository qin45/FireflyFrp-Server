from __future__ import annotations

from .models import User


def user_public(user: User) -> dict:
    remaining = max(0, user.traffic_quota_bytes - user.traffic_used_bytes)
    return {
        "id": user.id,
        "username": user.username,
        "traffic_quota_bytes": user.traffic_quota_bytes,
        "traffic_used_bytes": user.traffic_used_bytes,
        "traffic_remaining_bytes": remaining,
        "rate_limit_mbps": user.rate_limit_mbps,
        "status": user.status,
        "created_at": user.created_at,
    }
