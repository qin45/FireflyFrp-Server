from __future__ import annotations

import hmac
import ipaddress
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_db
from ..deps import get_settings
from ..services import plugin_service
from ..services.plugin_service import PluginReject

logger = logging.getLogger(__name__)

router = APIRouter(tags=["frps-plugin"])

SUPPORTED_OPS = {"Login", "NewProxy", "Ping", "NewUserConn", "CloseProxy"}


def _client_ip(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host


def _is_trusted(ip_text: str, cidrs: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            logger.warning("invalid plugin_trusted_cidrs entry: %s", cidr)
    return False


@router.post("/internal/frps/plugin/{secret}")
async def frps_plugin(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if not settings.frps.plugin_path_secret or not hmac.compare_digest(
        secret, settings.frps.plugin_path_secret
    ):
        raise HTTPException(status_code=404, detail="not found")
    if not _is_trusted(_client_ip(request), settings.frps.plugin_trusted_cidrs):
        raise HTTPException(status_code=403, detail="source ip is not trusted")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid JSON") from None

    op = request.query_params.get("op") or payload.get("op") or ""
    content = payload.get("content") or {}
    if op not in SUPPORTED_OPS:
        return JSONResponse(
            {"reject": True, "reject_reason": f"unsupported op: {op}"}
        )

    try:
        result = await plugin_service.handle(db, settings, str(op), content)
        return JSONResponse(result)
    except PluginReject as exc:
        return JSONResponse({"reject": True, "reject_reason": exc.reason})
    except Exception:  # noqa: BLE001 - fail closed
        logger.exception("frps plugin operation %s failed", op)
        return JSONResponse(
            {"reject": True, "reject_reason": "internal error"},
            status_code=500,
        )
