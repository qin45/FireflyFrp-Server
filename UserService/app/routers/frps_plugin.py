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


def _authorize(secret: str, request: Request, settings: Settings) -> str:
    ip_text = _client_ip(request)
    if not settings.frps.plugin_path_secret or not hmac.compare_digest(
        secret, settings.frps.plugin_path_secret
    ):
        logger.warning(
            "frps plugin rejected: bad path secret from %s",
            ip_text or "unknown",
        )
        raise HTTPException(status_code=404, detail="not found")
    if not _is_trusted(ip_text, settings.frps.plugin_trusted_cidrs):
        logger.warning(
            "frps plugin rejected: untrusted source ip %s; trusted=%s",
            ip_text or "unknown",
            settings.frps.plugin_trusted_cidrs,
        )
        raise HTTPException(status_code=403, detail="source ip is not trusted")
    return ip_text


@router.get("/internal/frps/plugin/{secret}/health")
async def frps_plugin_health(
    secret: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Small probe for frps-side plugin address/secret/CIDR diagnostics."""
    ip_text = _authorize(secret, request, settings)
    return {"ok": True, "source": ip_text}


@router.post("/internal/frps/plugin/{secret}")
async def frps_plugin(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    ip_text = _authorize(secret, request, settings)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid JSON") from None

    op = request.query_params.get("op") or payload.get("op") or ""
    content = payload.get("content") or {}
    if op == "Ping":
        logger.debug("frps plugin op=%s source=%s", op, ip_text)
    else:
        logger.info("frps plugin op=%s source=%s", op, ip_text)
    if op not in SUPPORTED_OPS:
        return JSONResponse(
            {"reject": True, "reject_reason": f"unsupported op: {op}"}
        )

    try:
        result = await plugin_service.handle(db, settings, str(op), content)
        return JSONResponse(result)
    except PluginReject as exc:
        logger.info("frps plugin %s rejected: %s", op, exc.reason)
        return JSONResponse({"reject": True, "reject_reason": exc.reason})
    except Exception:  # noqa: BLE001 - fail closed
        logger.exception("frps plugin operation %s failed", op)
        return JSONResponse(
            {"reject": True, "reject_reason": "internal error"},
            status_code=500,
        )
