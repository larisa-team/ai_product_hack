"""Минимальный сервер Connect-протокола (unary, JSON) поверх FastAPI.

Зачем: фронт использует сгенерированный `protoc-gen-connect-es` клиент, бэкенд — те же
сообщения из `backend/gen`. gRPC-сервер и grpc-web прокси при этом не нужны.

Контракт Connect (unary):
  POST /{package}.{Service}/{Method}   Content-Type: application/json
  тело запроса  — сообщение Request  в proto3-JSON
  200           — сообщение Response в proto3-JSON
  ошибка        — HTTP-код по таблице + {"code": "...", "message": "..."}

Именно здесь возникает контроль контракта: `json_format.Parse(..., ignore_unknown_fields=False)`
роняет запрос с полем, которого нет в proto.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from google.protobuf import json_format
from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db

log = logging.getLogger(__name__)

# Коды Connect -> HTTP-статусы (connectrpc.com/docs/protocol#error-codes)
CODE_TO_HTTP: dict[str, int] = {
    "canceled": 499,
    "unknown": 500,
    "invalid_argument": 400,
    "deadline_exceeded": 504,
    "not_found": 404,
    "already_exists": 409,
    "permission_denied": 403,
    "resource_exhausted": 429,
    "failed_precondition": 412,
    "aborted": 409,
    "out_of_range": 400,
    "unimplemented": 501,
    "internal": 500,
    "unavailable": 503,
    "data_loss": 500,
    "unauthenticated": 401,
}


class ConnectError(Exception):
    """Ошибка, которую клиент Connect-ES увидит как ConnectError с тем же кодом."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def http_status(self) -> int:
        return CODE_TO_HTTP.get(self.code, 500)

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.http_status,
            content={"code": self.code, "message": self.message},
        )


Handler = Callable[[Any, AsyncSession], Awaitable[Message]]


@dataclass(frozen=True)
class Method:
    name: str
    request: type[Message]
    response: type[Message]
    handler: Handler


class Registry:
    """Реестр RPC: полное имя сервиса из proto -> методы."""

    def __init__(self) -> None:
        self._services: dict[str, dict[str, Method]] = {}

    def register(self, service_fqn: str, methods: list[Method]) -> None:
        self._services.setdefault(service_fqn, {}).update({m.name: m for m in methods})

    def lookup(self, service_fqn: str, method: str) -> Method:
        service = self._services.get(service_fqn)
        if service is None:
            raise ConnectError("unimplemented", f"unknown service: {service_fqn}")
        found = service.get(method)
        if found is None:
            raise ConnectError("unimplemented", f"unknown method: {service_fqn}/{method}")
        return found

    def describe(self) -> dict[str, list[str]]:
        return {svc: sorted(methods) for svc, methods in self._services.items()}


registry = Registry()
router = APIRouter()


@router.post("/{service_fqn}/{method}")
async def unary(
    service_fqn: str,
    method: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rpc = registry.lookup(service_fqn, method)

    raw = await request.body()
    try:
        # ignore_unknown_fields=False — расхождение с proto ловится здесь
        req = json_format.Parse(raw or b"{}", rpc.request(), ignore_unknown_fields=False)
    except json_format.ParseError as exc:
        raise ConnectError("invalid_argument", str(exc)) from exc

    resp = await rpc.handler(req, db)
    if not isinstance(resp, rpc.response):
        raise ConnectError(
            "internal",
            f"{service_fqn}/{method} вернул {type(resp).__name__}, ожидался {rpc.response.__name__}",
        )
    return JSONResponse(json_format.MessageToDict(resp))


async def connect_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ConnectError)
    if exc.http_status >= 500:
        log.error("connect %s: %s", exc.code, exc.message)
    return exc.to_response()


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("необработанная ошибка в RPC")
    return ConnectError("internal", str(exc)).to_response()
