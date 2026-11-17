"""End to end: an MCP client calls this server over stdio, which drives a real LYNX SHARE (with its window) through
its Remote Control API, in a throwaway settings profile. Skipped unless LYNX_BIN names the app's binary.

    LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX .venv/bin/pytest -v   # macOS
    LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX .venv/bin/pytest -v                           # Linux
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

BIN = os.path.expanduser(os.environ.get("LYNX_BIN", ""))
pytestmark = pytest.mark.skipif(not BIN, reason="set LYNX_BIN to run against LYNX SHARE")


@pytest.fixture(scope="module")
def lynx_profile(tmp_path_factory):
    """LYNX SHARE running with Remote Control on, its settings and discovery record in a temporary profile."""
    profile = tmp_path_factory.mktemp("profile")
    # the plugins this user's LYNX already scanned (Serum 2), so the test profile needs no scan of its own
    real = Path.home() / ("Library/Application Support/LYNX" if sys.platform == "darwin" else ".config/LYNX")
    (profile / "LYNX").mkdir()
    for name in ("plugins.xml", "plugin-folders.txt"):
        if (real / name).is_file():
            shutil.copy(real / name, profile / "LYNX" / name)
    env = {**os.environ, "LYNX_PROFILE_DIR": str(profile), "LYNX_CONTROL_ENABLED": "1"}
    proc = subprocess.Popen([BIN], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record = Path(profile) / "LYNX/control/connection.json"
    deadline = time.time() + 60
    while time.time() < deadline and not record.exists():
        time.sleep(0.25)
    if not record.exists():
        proc.kill()
        pytest.fail("LYNX SHARE did not publish its Remote Control record")
    yield str(profile)
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_session(profile: str, body):
    params = StdioServerParameters(command=sys.executable, args=["-m", "lynx_share_mcp"],
                                   env={**os.environ, "LYNX_PROFILE_DIR": profile})

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


def test_build_a_beat_and_play_it(lynx_profile):
    async def body(call):
        status = await call("lynx_status")
        assert status["app_version"]
        assert (await call("lynx_launch"))["already"] is True

        await call("set_tempo", bpm=96)
        ch = (await call("add_channel", name="Bass", instrument="Synth"))["channel"]
        pat = (await call("add_pattern", name="Groove"))["pattern"]
        notes = [{"position": i, "length": 0.5, "key": k} for i, k in enumerate([36, 36, 43, 41])]
        assert (await call("write_notes", pattern=pat, channel=ch, notes=notes))["written"] == 4
        # by name, adding
        await call("write_notes", pattern="Groove", channel="Bass", replace=False,
                   notes=[{"position": 3.5, "length": 0.5, "key": 48, "velocity": 0.5}])

        got = await call("get_notes", pattern=pat)
        assert [(n["position"], n["length"], n["key"]) for n in got["notes"]] == \
            [(0, 0.5, 36), (1, 0.5, 36), (2, 0.5, 43), (3, 0.5, 41), (3.5, 0.5, 48)]

        clip = (await call("place_pattern", pattern=pat, position=0, track=1))["clip"]
        state = await call("get_project_state")
        assert state["bpm"] == 96
        assert any(c["clipId"] == clip and c["track"] == 1 for c in state["clips"])
        assert any(c["channelId"] == ch and c["name"] == "Bass" for c in state["channels"])

        await call("set_channel", channel=ch, name="Sub", volume=0.5, pan=-0.25)
        state = await call("get_project_state")
        sub = next(c for c in state["channels"] if c["channelId"] == ch)
        assert (sub["name"], round(sub["volume"], 3), round(sub["pan"], 3)) == ("Sub", 0.5, -0.25)

        await call("rename_pattern", pattern=pat, name="Verse")
        shown = await call("select", pattern="Verse", mode="pattern")
        assert shown["mode"] == "pattern"

        t = await call("play")
        assert t["state"] == "playing", t
        time.sleep(0.5)
        t = await call("transport_status")
        assert t["state"] == "playing" and t["position"] > 0, t
        with pytest.raises(RuntimeError, match="(?i)stop"):
            await call("set_tempo", bpm=100)
        assert (await call("stop"))["state"] == "stopped"

        await call("undo")  # the rename
        state = await call("get_project_state")
        assert any(p["patternId"] == pat and p["name"] == "Groove" for p in state["patterns"])
        await call("redo")

        await call("delete_clip", clip=clip)
        await call("delete_pattern", pattern=pat)
        await call("delete_channel", channel=ch)
        state = await call("get_project_state")
        assert not any(p["patternId"] == pat for p in state["patterns"])
        assert not any(c["channelId"] == ch for c in state["channels"])

    run_session(lynx_profile, body)


@pytest.mark.skipif(sys.platform != "darwin", reason="Serum 2 is installed on the Mac only")
def test_serum_parameters(lynx_profile):
    async def body(call):
        found = await call("list_instruments", query="Serum")
        assert any(i["name"] == "Serum 2" for i in found["instruments"])
        ch = (await call("add_channel", instrument="Serum 2", name="Serum"))["channel"]

        filt = await call("plugin_params", channel=ch, search="filter 1")
        names = {p["name"]: p for p in filt["parameters"]}
        assert {"Filter 1 On", "Filter 1 Type", "Filter 1 Freq"} <= set(names)
        assert names["Filter 1 Type"].get("steps", 0) > 2  # the VST3 reports its menu's steps
        assert (await call("plugin_params", channel=ch, search="macro"))["matched"] >= 8

        r = await call("set_plugin_params", channel=ch,
                       values={"Filter 1 On": 1, "Filter 1 Freq": 0.3, "Filter 1 Type": 0.1, "Macro 1": 0.7})
        got = {p["name"]: p for p in r["changed"]}
        assert got["Filter 1 On"]["display"] == "On"
        assert got["Macro 1"]["value"] == pytest.approx(0.7, abs=1e-4)
        steps = names["Filter 1 Type"]["steps"]
        assert got["Filter 1 Type"]["value"] == pytest.approx(round(0.1 * (steps - 1)) / (steps - 1), abs=1e-4)

        await call("undo")
        after = await call("plugin_params", channel=ch, search="macro 1")
        assert after["parameters"][0]["value"] == pytest.approx(0, abs=1e-4)

    run_session(lynx_profile, body)


def test_errors(lynx_profile):
    async def body(call):
        with pytest.raises(RuntimeError, match="pattern"):
            await call("get_notes", pattern="No Such Pattern")
        with pytest.raises(RuntimeError, match="channel"):
            await call("write_notes", pattern=0, notes=[{"position": 0, "key": 60}])
        with pytest.raises(RuntimeError, match="unknown instrument"):
            await call("add_channel", instrument="No Such Synth")
        with pytest.raises(RuntimeError, match="native|hosted"):
            await call("plugin_params", channel=0)  # the demo's Kick is a built-in instrument

    run_session(lynx_profile, body)


def test_ui_hooks_save_pause_select(lynx_profile, tmp_path):
    """The remote-api-ui additions: ui.select, transport.pause, play from a position, project.save, project.new."""
    async def body(call):
        try:
            await call("pause")
        except RuntimeError as e:
            if "cannot pause" in str(e):
                pytest.skip("this LYNX build has no ui.select/project.save additions")
            raise

        ch = (await call("add_channel", name="Keys", instrument="Synth"))["channel"]
        pat = (await call("add_pattern", name="Chords", bars=2))["pattern"]
        await call("write_notes", pattern=pat, channel=ch, notes=[{"position": 0, "length": 4, "key": k}
                                                                    for k in (60, 64, 67)])
        await call("add_pattern", name="Other")  # becomes current
        status = await call("lynx_status")
        shown = await call("select", pattern=pat, channel=ch, piano_roll=True)
        state = await call("get_project_state")
        assert state["currentPattern"] == next(p["index"] for p in state["patterns"] if p["patternId"] == pat)
        assert (await call("lynx_status"))["can_undo"] == status["can_undo"]  # select is not an edit

        t = await call("play", mode="pattern", pattern=pat, from_position=4)
        assert t["state"] == "playing" and t["mode"] == "pattern", t
        time.sleep(0.4)
        paused = await call("pause")
        assert paused["state"] == "stopped" and paused["position"] >= 4, paused
        time.sleep(0.3)
        assert (await call("transport_status"))["position"] == pytest.approx(paused["position"], abs=0.01)
        await call("stop")

        saved = await call("save_project", path=str(tmp_path / "ui.lynx"))
        assert os.path.getsize(saved["path"]) > 0
        assert (await call("save_project"))["path"] == saved["path"]  # its own file now

        await call("set_tempo", bpm=101)
        with pytest.raises(RuntimeError, match="unsaved"):
            await call("new_project")
        await call("save_project")
        fresh = await call("new_project")
        state = await call("get_project_state")
        assert not any(p["patternId"] == pat for p in state["patterns"]), fresh

    run_session(lynx_profile, body)
