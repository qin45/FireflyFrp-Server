from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

USERNAME_PATTERN = r"^[A-Za-z0-9_-]{3,32}$"


class RegisterRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)


class TunnelCreateRequest(BaseModel):
    type: Literal["tcp", "udp", "http", "https"]
    name: str = Field(min_length=1, max_length=64)
    local_ip: str = Field(default="127.0.0.1", min_length=1, max_length=64)
    local_port: int = Field(ge=1, le=65535)


class TunnelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    local_ip: str | None = Field(default=None, min_length=1, max_length=64)
    local_port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "TunnelUpdateRequest":
        if not any(
            value is not None
            for value in (self.name, self.local_ip, self.local_port)
        ):
            raise ValueError("at least one field must be provided")
        return self


class TunnelTokenResponse(BaseModel):
    token: str
    frpc_config: str


class AdminUserPatch(BaseModel):
    remaining_traffic_bytes: int | None = Field(default=None, ge=0)
    traffic_quota_bytes: int | None = Field(default=None, ge=0)
    rate_limit_mbps: int | None = Field(default=None, ge=0)
    password: str | None = Field(default=None, min_length=8, max_length=72)
    status: Literal["active", "disabled", "exhausted"] | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "AdminUserPatch":
        if not any(
            value is not None
            for value in (
                self.remaining_traffic_bytes,
                self.traffic_quota_bytes,
                self.rate_limit_mbps,
                self.password,
                self.status,
            )
        ):
            raise ValueError("at least one field must be provided")
        return self


class UserPublic(BaseModel):
    id: int
    username: str
    traffic_quota_bytes: int
    traffic_used_bytes: int
    traffic_remaining_bytes: int
    rate_limit_mbps: int
    status: str
    created_at: datetime


class TunnelPublic(BaseModel):
    id: str
    name: str
    type: str
    local_ip: str
    local_port: int
    remote_port: int | None
    subdomain: str | None
    domain: str | None
    public_address: str | None
    status: str
    active: bool
    traffic_in_bytes: int
    traffic_out_bytes: int
    created_at: datetime


class UserInfoResponse(UserPublic):
    max_tunnels: int
    max_active_tunnels: int
    tunnels: list[TunnelPublic]


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserPublic


class TunnelCreateResponse(BaseModel):
    tunnel: TunnelPublic
    token: str
    frpc_config: str


class TunnelUpdateResponse(BaseModel):
    tunnel: TunnelPublic
    # Present only when the local endpoint changed and the token was rotated.
    token: str | None = None
    frpc_config: str | None = None


class PageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list
