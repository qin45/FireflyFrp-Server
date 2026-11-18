from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow

# SQLite only auto-increments INTEGER PRIMARY KEY, so use a smaller variant there.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    traffic_quota_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    traffic_used_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    rate_limit_mbps: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class Tunnel(Base):
    __tablename__ = "tunnels"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    local_ip: Mapped[str] = mapped_column(
        String(64), nullable=False, default="127.0.0.1"
    )
    local_port: Mapped[int] = mapped_column(Integer, nullable=False)
    remote_port: Mapped[int | None] = mapped_column(
        Integer, nullable=True, unique=True, index=True
    )
    subdomain: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    domain: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="inactive"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PortReservation(Base):
    __tablename__ = "port_reservations"

    remote_port: Mapped[int] = mapped_column(Integer, primary_key=True)
    tunnel_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("tunnels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class TunnelSession(Base):
    __tablename__ = "tunnel_sessions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tunnel_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("tunnels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    proxy_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True
    )
    last_today_in: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_today_out: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    traffic_in_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    traffic_out_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sample_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


Index(
    "ix_tunnel_sessions_tunnel_status", TunnelSession.tunnel_id, TunnelSession.status
)
Index("ix_tunnel_sessions_user_status", TunnelSession.user_id, TunnelSession.status)
