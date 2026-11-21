"""Opt-in API authentication boundary and request telemetry for deployments.

By default the API is local-first, not a multi-tenant service. Required mode
protects ALL data routes with a single operator key. Individual project RBAC
and public hosting require a separate identity provider and authorization.
"""
import hmac
import logging
import os
import time
from ipaddress import ip_address
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

_LOGGER=logging.getLogger("geofathom.access")


def _loopback(host):
    if host in ("testclient","localhost"):
        return True
    try:
        return ip_address(host).is_loopback
    except (ValueError,TypeError):
        return False


def _authorized(request,mode):
    if request.method=="OPTIONS" or request.url.path=="/health":
        return None
    if mode=="local":
        if request.client and _loopback(request.client.host):
            return None
        return JSONResponse(status_code=403,content={
            "detail":"Remote access is disabled. Enable required authentication."})
    if mode!="required":
        return JSONResponse(status_code=503,content={
            "detail":"Invalid API authentication configuration."})
    expected=os.getenv("GEOFATHOM_API_TOKEN","")
    if len(expected)<32:
        return JSONResponse(status_code=503,content={
            "detail":"Required API authentication is not configured."})
    token=request.headers.get("X-GeoFathom-API-Key","")
    if not token:
        auth=request.headers.get("authorization","")
        if auth.startswith("Bearer "):
            token=auth[7:]
    if token and hmac.compare_digest(token.encode(),expected.encode()):
        return None
    from .access import authenticate,permits
    principal=authenticate(token)
    if principal:
        request.state.principal=principal
        if permits(principal,request.method,request.url.path):
            return None
        return JSONResponse(status_code=403,content={"detail":"Project permission denied."})
    if principal is None:
        return JSONResponse(status_code=401,content={
            "detail":"Valid API credentials are required."},
            headers={"WWW-Authenticate":"Bearer"})
    return None


class APIBoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        started=time.perf_counter()
        request_id=str(uuid4())
        response=None
        try:
            mode=os.getenv("GEOFATHOM_AUTH_MODE","local").lower()
            rejected=await run_in_threadpool(_authorized,request,mode)
            response=rejected if rejected is not None else await call_next(request)
            return response
        finally:
            elapsed=round((time.perf_counter()-started)*1000,2)
            if response is not None:
                response.headers["X-Request-ID"]=request_id
                response.headers["X-Process-Time-ms"]=str(elapsed)
                response.headers["Cache-Control"]=(
                    response.headers.get("Cache-Control","no-store"))
            _LOGGER.info(
                "http request_id=%s method=%s route=%s status=%s elapsed_ms=%.2f",
                request_id,request.method,request.url.path,
                response.status_code if response is not None else 500,elapsed)
