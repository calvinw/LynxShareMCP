"""A client for LYNX SHARE's official Remote Control API (`lynx-control/1`, docs/REMOTE_CONTROL.md upstream).

The app publishes a private discovery record (port + token) when Remote Control is on: Settings > General > Remote
control, or LYNX_CONTROL_ENABLED=1 at launch. Each request is its own loopback TCP connection: a mutual HMAC-SHA-256
handshake, one `{"op", "args"}` line, one result line, then the server closes.

Edits are guarded by the project triple (projectId, controlEpoch, revision) the client last observed; `write` reads a
fresh `status` right before sending, so an edit is refused if the project changed in between. A write whose answer is
lost is never retried: its outcome is unknown.

Environment:
    LYNX_CONTROL_DISCOVERY   an absolute path to the discovery record (default: LYNX's settings folder)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import stat
import sys
import threading
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

PROTOCOL = "lynx-control/1"
MAX_FRAME = 1024 * 1024
HANDSHAKE_TIMEOUT = 3.0
OP_TIMEOUT = 70.0  # plugin parameter edits restore and verify the plugin's state; they can take a while


class LynxError(ToolError):
    """An error answer from LYNX SHARE (`code`: invalid, busy, changed, limit, failed, uncertain), or no connection
    (`code` None). A ToolError, so the MCP client sees its message."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def discovery_path() -> Path:
    if os.environ.get("LYNX_CONTROL_DISCOVERY"):
        return Path(os.environ["LYNX_CONTROL_DISCOVERY"])
    if os.environ.get("LYNX_PROFILE_DIR"):
        return Path(os.environ["LYNX_PROFILE_DIR"]) / "LYNX/control/connection.json"
    if sys.platform == "darwin":
        folder = Path.home() / "Library/Application Support/LYNX"
    elif os.name == "nt":
        folder = Path(os.environ.get("APPDATA", str(Path.home()))) / "LYNX"
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME", "") or Path.home() / ".config")
        folder = (config if config.is_absolute() else Path.home() / ".config") / "LYNX"
    return folder / "control/connection.json"


def _hex(value: Any, size: int) -> bool:
    return isinstance(value, str) and len(value) == size and all(c in "0123456789abcdef" for c in value)


def _read_record(path: Path) -> dict[str, Any]:
    """The discovery record, checked the way docs/REMOTE_CONTROL.md asks: a regular file (not a symlink) owned by this
    user and readable only by them."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise LynxError(f"LYNX SHARE's Remote Control is not on (no {path}). Turn on Settings > General > Remote "
                        "control in LYNX SHARE, or call lynx_launch.") from None
    if not stat.S_ISREG(st.st_mode):
        raise LynxError(f"{path} is not a regular file; refusing it")
    if os.name != "nt" and (st.st_uid != os.getuid() or st.st_mode & 0o077):
        raise LynxError(f"{path} is not private to this user; refusing it")
    try:
        record = json.loads(path.read_bytes())
    except ValueError as e:
        raise LynxError(f"cannot read {path}: {e}") from e
    if not (isinstance(record, dict) and record.get("protocol") == PROTOCOL and record.get("host") == "127.0.0.1"
            and type(record.get("port")) is int and 0 < record["port"] < 65536 and _hex(record.get("token"), 64)):
        raise LynxError(f"{path} is not a {PROTOCOL} record")
    return record


def _pid_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


class RemoteClient:
    def __init__(self, path: Path | None = None):
        self.path = path or discovery_path()
        self._lock = threading.Lock()

    # ---- connection -------------------------------------------------------------------------------------------
    def record(self) -> dict[str, Any]:
        record = _read_record(self.path)
        if not _pid_alive(record.get("pid")):
            raise LynxError(f"LYNX SHARE is not running (its Remote Control record at {self.path} is stale). "
                            "Start it, or call lynx_launch.")
        return record

    def connected(self) -> bool:
        try:
            self.call("status")
            return True
        except LynxError as e:
            return e.code is not None

    def _exchange(self, record: dict[str, Any], op: str, args: dict[str, Any], write: bool) -> dict[str, Any]:
        token = record["token"]
        nonce = secrets.token_hex(16)

        def proof(role: str, server: str) -> str:
            msg = f"{PROTOCOL}\n{role}\n{nonce}\n{server}".encode("ascii")
            return hmac.new(token.encode("ascii"), msg, hashlib.sha256).hexdigest()

        def send(conn: socket.socket, value: Any, limit: int) -> None:
            data = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(data) > limit:
                raise LynxError(f"the request is too large ({len(data)} bytes; the limit is {limit})", "limit")
            conn.sendall(data + b"\n")

        def frame(stream: Any, limit: int) -> dict[str, Any]:
            data = stream.readline(limit + 2)
            if not data.endswith(b"\n"):
                raise ConnectionError("LYNX SHARE closed the connection or sent an oversized frame")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ConnectionError("LYNX SHARE sent a frame that is not an object")
            return value

        try:
            conn = socket.create_connection(("127.0.0.1", record["port"]), timeout=HANDSHAKE_TIMEOUT)
        except OSError as e:
            raise LynxError(f"LYNX SHARE is not answering on its Remote Control port ({e}). Is it still running "
                            "with Remote control on?") from e
        with conn, conn.makefile("rb") as stream:
            try:
                send(conn, {"type": "hello", "protocol": PROTOCOL, "nonce": nonce}, 1024)
                challenge = frame(stream, 1024)
                server = challenge.get("nonce")
                if not (challenge.get("type") == "challenge" and _hex(server, 32) and isinstance(challenge.get("proof"), str)
                        and hmac.compare_digest(challenge["proof"], proof("server", server))):
                    raise LynxError("LYNX SHARE's Remote Control proof did not verify; not sending anything")
                send(conn, {"type": "auth", "proof": proof("client", server)}, 1024)
                if frame(stream, 1024).get("type") != "ready":
                    raise LynxError("LYNX SHARE refused this client's authentication")
            except (OSError, ValueError) as e:
                raise LynxError(f"Remote Control handshake failed: {e}") from e
            conn.settimeout(OP_TIMEOUT)
            try:
                send(conn, {"op": op, "args": args}, MAX_FRAME)
                return frame(stream, MAX_FRAME)
            except (OSError, ValueError) as e:
                if write:
                    raise LynxError(f"{op}: the answer was lost ({e}); the edit may or may not have happened. "
                                    "Read the project before doing anything else; do not repeat it blindly.",
                                    "uncertain") from e
                raise LynxError(f"{op}: {e}") from e

    def call(self, op: str, args: dict[str, Any] | None = None, *, write: bool = False) -> dict[str, Any]:
        args = {k: v for k, v in (args or {}).items() if v is not None}
        with self._lock:
            response = self._exchange(self.record(), op, args, write)
        if response.get("ok") is not True:
            message = str(response.get("error", "operation failed"))
            code = response.get("code")
            if response.get("uncertain") is True:
                message += " (The edit may have happened: read the project before doing anything else.)"
            raise LynxError(f"{op}: {message}", code if isinstance(code, str) else "failed")
        return response["result"]

    # ---- guarded edits ----------------------------------------------------------------------------------------
    @staticmethod
    def guard(observed: dict[str, Any]) -> dict[str, Any]:
        return {"expectedProjectId": observed["projectId"], "expectedEpoch": observed["controlEpoch"],
                "expectedRevision": observed["revision"]}

    def write(self, op: str, args: dict[str, Any] | None = None, observed: dict[str, Any] | None = None) -> dict[str, Any]:
        """A guarded edit: bound to `observed` (a result holding the project triple, e.g. the session.inspect the
        edit was planned from) or else to a fresh status."""
        observed = observed or self.call("status")
        return self.call(op, {**(args or {}), **self.guard(observed)}, write=True)

    # ---- the whole project document ---------------------------------------------------------------------------
    def read_project(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """(document, snapshot): the complete native project and the fence project.edit needs."""
        import base64

        request: dict[str, Any] = {"limit": 65536}
        chunks: list[bytes] = []
        while True:
            page = self.call("project.read", request)
            chunks.append(base64.b64decode(page["data"], validate=True))
            if "nextOffset" not in page:
                break
            request = {"snapshotId": page["snapshotId"], "expectedDocumentHash": page["documentHash"],
                       "offset": page["nextOffset"], "limit": 65536}
        data = b"".join(chunks)
        if len(data) != page["totalBytes"] or hashlib.sha256(data).hexdigest() != page["documentHash"]:
            raise LynxError("project.read: the pages did not add up to the document; read again")
        snapshot = {k: page[k] for k in ("snapshotId", "documentHash", "projectId", "controlEpoch", "revision")}
        return json.loads(data), snapshot

    def edit_project(self, patch: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
        """One project.edit transaction (JSON Patch, 1-128 ops) against the document `snapshot` came from."""
        return self.call("project.edit", {"patch": patch, "snapshotId": snapshot["snapshotId"],
                                          "expectedDocumentHash": snapshot["documentHash"], **self.guard(snapshot)},
                         write=True)
