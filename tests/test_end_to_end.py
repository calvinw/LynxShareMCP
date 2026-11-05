"""End to end: an MCP client calls this server over stdio, which drives a real LYNX SHARE (with its window) on a
temporary socket. Skipped unless LYNX_BIN names the app's binary.

    LYNX_BIN=~/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX .venv/bin/pytest -v   # macOS
    LYNX_BIN=~/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX .venv/bin/pytest -v                           # Linux
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

BIN = os.path.expanduser(os.environ.get("LYNX_BIN", ""))
pytestmark = pytest.mark.skipif(not BIN, reason="set LYNX_BIN to run against LYNX SHARE")


@pytest.fixture(scope="module")
def lynx_socket(tmp_path_factory):
    path = f"/tmp/lynx-mcp-test-{os.getpid()}.sock"
    proc = subprocess.Popen([BIN, "--control", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(path)
            s.close()
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("LYNX SHARE did not start listening")
    yield path
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_session(sock: str, body):
    params = StdioServerParameters(command=sys.executable, args=["-m", "lynx_share_mcp"],
                                   env={**os.environ, "LYNX_SOCKET": sock})

    async def main():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
            await session.initialize()

            async def call(tool, /, **args):
                res = await session.call_tool(tool, args)
                text = res.content[0].text if res.content else "null"
                if res.is_error:
                    raise RuntimeError(f"{tool}: {text}")
                return json.loads(text)

            await body(call)

    anyio.run(main)


def test_build_a_beat_and_play_it(lynx_socket, tmp_path):
    async def body(call):
        status = await call("lynx_status")
        assert status["hello"]["app"] == "LYNX SHARE"
        assert (await call("lynx_launch"))["already"] is True

        start = (await call("get_history"))["position"]
        await call("set_tempo", bpm=96)
        ch = (await call("add_channel", name="Bass", instrument="synth"))["channel"]
        await call("set_synth", channel=ch, osc=[{"wave": "saw", "octave": -1}], cutoff=800, mono=True)
        pat = (await call("add_pattern", name="Groove"))["pattern"]
        notes = [{"position": i, "length": 0.5, "key": k} for i, k in enumerate([36, 36, 43, 41])]
        assert (await call("write_notes", pattern=pat, channel=ch, notes=notes))["written"] == 4

        got = await call("get_notes", pattern=pat)
        assert [(n["position"], n["length"], n["key"]) for n in got["notes"]] == [(0, 0.5, 36), (1, 0.5, 36), (2, 0.5, 43), (3, 0.5, 41)]
        assert all(n["channel"] == ch and n["velocity"] == 100 for n in got["notes"])

        clip = (await call("place_pattern", pattern=pat, position=0))["clip"]
        state = await call("get_project_state")
        assert state["bpm"] == 96
        assert any(c["id"] == clip and c["pattern"] == pat for c in state["clips"])

        # A failing apply changes nothing.
        before = await call("get_project_state")
        with pytest.raises(RuntimeError):
            await call("apply_commands", commands=[{"op": "add_pattern", "name": "Nope"},
                                                   {"op": "delete_pattern", "pattern": 999999999}])
        assert await call("get_project_state") == before

        t = await call("play", mode="pattern", pattern=pat)
        assert (t["state"], t["mode"]) == ("playing", "pattern")
        time.sleep(0.5)
        t = await call("transport_status")
        assert t["state"] == "playing" and t["position"] > 0, t
        assert (await call("stop"))["state"] == "stopped"

        # select changes the view, not the history.
        steps = (await call("get_history"))["position"]
        shown = await call("select", pattern=pat, channel=ch, piano_roll=True)
        assert (shown["current_pattern"], shown["selected_channel"]) == (pat, ch), shown
        assert (await call("get_history"))["position"] == steps

        # Undo all the edits back to where we started.
        for _ in range(steps - start):
            await call("undo")
        state = await call("get_project_state")
        assert not any(c["id"] == clip for c in state["clips"])
        assert not any(c["id"] == ch for c in state["channels"])
        await call("redo")

        saved = await call("save_project", path=str(tmp_path / "beat.lynx"))
        assert os.path.getsize(saved["path"]) > 0

    run_session(lynx_socket, body)


def test_plugins_and_errors(lynx_socket):
    async def body(call):
        plugins = await call("list_plugins", instruments_only=True)
        assert "synth" in plugins["builtin_instruments"]
        if sys.platform == "darwin":  # Serum 2 is installed on the Mac; Linux has no build of it
            assert any(p["name"] == "Serum 2" for p in plugins["plugins"]), [p["name"] for p in plugins["plugins"]]

        with pytest.raises(RuntimeError, match="pattern"):
            await call("get_notes", pattern=99999)
        with pytest.raises(RuntimeError, match="channel"):
            await call("write_notes", pattern=1, notes=[{"position": 0, "key": 60}])
        with pytest.raises(RuntimeError, match="unknown instrument"):
            await call("add_channel", instrument="No Such Synth")

    run_session(lynx_socket, body)
