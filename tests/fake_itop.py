"""Small fake of the iTop REST endpoint (webservices/rest.php) for tests.

Answers `list_operations` (token check) and `core/get`, and records what it received,
so tests can check what actually reached iTop.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


@dataclass
class ReceivedRequest:
    auth_token: str | None
    query_params: dict[str, str]
    form: dict[str, str]
    operation: dict

    @property
    def name(self) -> str:
        return self.operation.get("operation", "")

    @property
    def oql(self) -> str | None:
        return self.operation.get("key") if self.name == "core/get" else None


@dataclass
class FakeITop:
    valid_tokens: set[str] = field(default_factory=set)
    person_name: str = "Max Muster"
    requests: list[ReceivedRequest] = field(default_factory=list)
    base_url: str = ""
    # (code, message) returned for core/get on non-Person classes, e.g. to simulate an OQL error
    core_get_error: tuple[int, str] | None = None
    # when set, every request gets this HTTP status (simulates a broken iTop)
    http_status: int | None = None

    def reset(self) -> None:
        self.valid_tokens.clear()
        self.requests.clear()
        self.core_get_error = None
        self.http_status = None

    def core_gets(self) -> list[ReceivedRequest]:
        return [r for r in self.requests if r.name == "core/get"]

    async def _rest(self, request: Request) -> JSONResponse:
        form = {k: str(v) for k, v in (await request.form()).items()}
        op = json.loads(form.get("json_data", "{}"))
        token = request.headers.get("auth-token")
        self.requests.append(ReceivedRequest(token, dict(request.query_params), form, op))

        if self.http_status is not None:
            return JSONResponse({"error": "broken"}, status_code=self.http_status)
        if token not in self.valid_tokens:
            return JSONResponse({"code": 1, "message": "Error: Invalid login"})
        if op.get("operation") == "list_operations":
            return JSONResponse({"code": 0, "message": "Operations: 1", "version": "1.3", "operations": []})
        if op.get("operation") == "core/get":
            cls = op.get("class") or "Ticket"
            if self.core_get_error and cls != "Person":
                code, message = self.core_get_error
                return JSONResponse({"code": code, "message": message, "objects": None})
            fields = {"friendlyname": self.person_name} if cls == "Person" else {"ref": "R-000001", "title": "Test"}
            return JSONResponse({"code": 0, "message": "Found: 1",
                                 "objects": {f"{cls}::1": {"code": 0, "message": "", "class": cls, "key": "1", "fields": fields}}})
        return JSONResponse({"code": 100, "message": "Unsupported operation"})

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/webservices/rest.php", self._rest, methods=["POST"])])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_in_thread(app, port: int) -> uvicorn.Server:
    """Start an ASGI app with uvicorn on 127.0.0.1:<port> in a daemon thread and wait until it is up."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"server on port {port} did not start")
        time.sleep(0.05)
    return server
