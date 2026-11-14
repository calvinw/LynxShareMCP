"""A JSON-RPC 2.0 client for LYNX SHARE's control socket.

LYNX SHARE listens on a local Unix socket when started with `--control <socket>` (only builds of the
`control-socket` branch of github.com/calvinw/LYNX-SHARE; see src/engine/ControlServer.cpp there). One request per line, one answer per line, one client at a time.

Where it connects, from the environment:
    LYNX_SOCKET   the Unix socket path (default /tmp/lynx.sock).
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import threading
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_SOCKET = "/tmp/lynx.sock"
TIMEOUT = 15.0


class LynxError(ToolError):
    """An error answer from LYNX SHARE (`code` is JSON-RPC's), or no connection (`code` None). A ToolError, so the MCP
    client sees its message (other exceptions reach it only as "Error executing tool")."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def socket_path() -> str:
    return os.environ.get("LYNX_SOCKET", DEFAULT_SOCKET)


class LynxClient:
    def __init__(self, path: str | None = None):
        self.path = path or socket_path()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._file = None
        self.hello: dict[str, Any] | None = None

    # ---- connection -------------------------------------------------------------------------------------------
    def _connect(self) -> None:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(TIMEOUT)
            s.connect(self.path)
        except OSError as e:
            raise LynxError(
                f"LYNX SHARE is not listening at {self.path} ({e.strerror or e}). Start it with "
                f"`LYNX --control {self.path}` or use the lynx_launch tool."
            ) from e
        self._sock, self._file = s, s.makefile("rw", encoding="utf-8", newline="\n")
        self.hello = self._rpc("hello", {})

    def close(self) -> None:
        for x in (self._file, self._sock):
            try:
                if x is not None:
                    x.close()
            except OSError:
                pass
        self._sock = self._file = None
        self.hello = None

    def connected(self) -> bool:
        try:
            self.call("transport")
            return True
        except LynxError as e:
            return e.code is not None

    # ---- requests ---------------------------------------------------------------------------------------------
    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        assert self._file is not None
        req = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        self._file.write(json.dumps(req) + "\n")
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise ConnectionResetError("LYNX SHARE closed the connection")
        resp = json.loads(line)
        if "error" in resp:
            err = resp["error"]
            raise LynxError(err.get("message", "error"), err.get("code"))
        return resp.get("result")

    def call(self, method: str, **params: Any) -> Any:
        """Calls `method`; reconnects once if the app was restarted since the last call."""
        params = {k: v for k, v in params.items() if v is not None}
        with self._lock:
            for attempt in (0, 1):
                try:
                    if self._file is None:
                        self._connect()
                    return self._rpc(method, params)
                except (OSError, ValueError) as e:
                    self.close()
                    if attempt == 1:
                        raise LynxError(f"lost the connection to LYNX SHARE at {self.path}: {e}") from e
        raise AssertionError("unreachable")

    def apply(self, commands: list[dict[str, Any]], name: str | None = None) -> list[Any]:
        """Applies `commands` as one undo step (all or nothing); returns each command's result."""
        return self.call("apply", commands=commands, name=name)["results"]
