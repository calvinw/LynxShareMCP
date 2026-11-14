"""lynx-share-mcp: an MCP server that drives LYNX SHARE over its control socket.

Run with:
    python -m lynx_share_mcp        # stdio, started by an MCP client such as Claude Code or Codex
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from .client import LynxClient, LynxError, socket_path

logging.basicConfig(level=os.environ.get("LYNX_MCP_LOG_LEVEL", "INFO").upper(), stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lynx_share_mcp")

client = LynxClient()

# Used when LYNX_BIN is unset: a LYNX-SHARE clone next to this repo, built with CMake into build/. JUCE's build output
# is an app bundle on macOS and a plain executable on Linux.
_BUILD = Path(__file__).resolve().parents[3] / "LYNX-SHARE" / "build" / "LYNX_artefacts" / "Release"
DEFAULT_BIN = str(_BUILD / "LYNX.app/Contents/MacOS/LYNX" if sys.platform == "darwin" else _BUILD / "LYNX")
BUILTIN_INSTRUMENTS = ("synth", "kick", "snare", "hat", "clap", "sampler")

# The project file this server last opened or saved, so save_project can default to it.
_project_path: str | None = None

Unit = Literal["beats", "ticks"]

INSTRUCTIONS = """\
Controls LYNX SHARE, an open-source FL Studio-style DAW, directly over its control socket.

How the project works:
- Things have ids (channels, patterns, clips). Read them with get_project_state; ids stay the same when other things
  are added or deleted. Mixer tracks are referred to by index (0 = master), playlist tracks by 0-based index.
- Positions and lengths are in beats (quarter notes) by default; pass unit="ticks" for raw ticks
  (get_project_state's `ppq` ticks per beat, and get_project_state itself is always in ticks).
- Note keys are MIDI numbers: 60 = middle C. Velocity 0-128 (default 100), note pan 0-128 (64 = centre).
- To hear notes a channel needs an instrument: a built-in one (synth, kick, snare, hat, clap, sampler) or an
  instrument plugin from list_plugins (e.g. "Serum 2"). Shape the built-in synth with set_synth.
- A good layout is one channel per pattern (e.g. a "Bass" pattern holding only the bass channel's notes), so the
  sections of a song are built by placing patterns in the playlist (place_pattern), stacked on different tracks.
- play(mode="pattern") loops the current pattern; play(mode="song") plays the playlist.
- The piano roll shows ONE channel in the CURRENT pattern. After writing notes the user should look at, call
  select(pattern=..., channel=..., piano_roll=True) so they are on screen. Use select, not play/stop, to change the
  current pattern.
- Every edit tool is one undo step; the user can undo it with Cmd+Z (Ctrl+Z on Linux). apply_commands runs several raw commands as one
  step, all or nothing.

Writing music:
- Chords with no bass under them need the root as the lowest note, or the harmony is misheard.
- Check each bass note against the chord sounding in the same bar (root, third or fifth unless it is a deliberate
  passing note).

Do not save after every edit: save_project only when the user asks.
If a call says LYNX SHARE is not listening, call lynx_launch.
"""


def _ppq() -> int:
    hello = client.hello or client.call("hello")
    return int(hello["ppq"])


def _to_ticks(v: float | None, unit: Unit, ppq: int) -> int | None:
    if v is None:
        return None
    return int(round(v * ppq)) if unit == "beats" else int(round(v))


def _from_ticks(t: float | None, unit: Unit, ppq: int) -> float | None:
    if t is None:
        return None
    return round(t / ppq, 6) if unit == "beats" else t


def _edit(name: str, *commands: dict[str, Any]) -> list[Any]:
    return client.apply([{k: v for k, v in c.items() if v is not None} for c in commands], name=name)


def _binary() -> str:
    return str(Path(os.environ.get("LYNX_BIN", DEFAULT_BIN)).expanduser())


def _transport(t: dict, unit: Unit) -> dict:
    t = dict(t)
    t["state"] = "playing" if t.pop("playing") else "stopped"
    t["position"] = _from_ticks(t["position"], unit, int(t["ppq"]))
    t["unit"] = unit
    return t


def build_app() -> MCPServer:
    mcp = MCPServer("lynx-share", instructions=INSTRUCTIONS)

    # ---- connection -----------------------------------------------------------------------------------------
    @mcp.tool()
    def lynx_launch(project: str | None = None) -> dict:
        """Start LYNX SHARE (with its window) listening on the control socket. Does nothing if it already is.

        project: a .lynx file to open (otherwise the demo song loads).
        """
        global _project_path
        if client.connected():
            return {"running": True, "already": True, "socket": client.path}
        exe = _binary()
        if not os.access(exe, os.X_OK):
            raise LynxError(f"LYNX SHARE's binary was not found at {exe}: build the control-socket branch of "
                            "github.com/calvinw/LYNX-SHARE and set LYNX_BIN to it (see the README)")
        args = [exe]
        if project:
            # LYNX opens only args[0], and only when it is an absolute path.
            p = Path(project).expanduser().resolve()
            if not p.is_file():
                raise LynxError(f"no such project file: {p}")
            args.append(str(p))
        path = socket_path()
        if len(os.fsencode(path)) > 103:  # sun_path holds 104 bytes on macOS (108 on Linux), including the NUL
            raise LynxError(f"the socket path is too long for a Unix socket ({len(path)} characters): {path}. "
                            "Set LYNX_SOCKET to a shorter path such as /tmp/lynx.sock")
        args += ["--control", path]
        log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "lynx-share-mcp-app.log"
        with open(log_path, "ab") as out:
            subprocess.Popen(args, stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.5)
            if client.connected():
                if project:
                    _project_path = args[1]
                return {"running": True, "socket": path, "project": _project_path, "log": str(log_path)}
        raise LynxError(f"LYNX SHARE did not start listening at {path} within 20 s; see {log_path}. "
                        "Official LYNX SHARE releases have no control socket: LYNX_BIN must be a build of the "
                        "control-socket branch of github.com/calvinw/LYNX-SHARE")

    @mcp.tool()
    def lynx_status() -> dict:
        """Whether LYNX SHARE is connected, the app and protocol version, and the transport."""
        transport = client.call("transport")
        return {"socket": client.path, "hello": client.hello, "project": _project_path,
                "transport": _transport(transport, "beats")}

    # ---- reading --------------------------------------------------------------------------------------------
    @mcp.tool()
    def get_project_state() -> dict:
        """The whole project: ppq, bpm, beats_per_bar, song/pattern mode, the current pattern, the selected channel,
        channels (id, name, instrument, mixer track, volume 0..1, pan -1..1, muted), patterns (id, name, length,
        note count), the playlist's clips (id, pattern, track, position, length) and mixer tracks.
        Positions and lengths here are raw ticks."""
        return client.call("state")

    @mcp.tool()
    def get_notes(pattern: int, unit: Unit = "beats") -> dict:
        """The notes of pattern `pattern` (an id): channel id, position, length, key, velocity, pan, muted."""
        ppq = _ppq()
        r = client.call("notes", pattern=pattern)
        for n in r["notes"]:
            n["position"] = _from_ticks(n["position"], unit, ppq)
            n["length"] = _from_ticks(n["length"], unit, ppq)
        r["unit"] = unit
        return r

    @mcp.tool()
    def list_plugins(instruments_only: bool = False) -> dict:
        """The scanned plugins (VST3/AU/CLAP): name, manufacturer, format, whether it is an instrument. add_channel
        takes an instrument's name. The built-in instruments are listed too."""
        r = client.call("plugins")
        plugins = [p for p in r["plugins"] if p["instrument"] or not instruments_only]
        return {"builtin_instruments": list(BUILTIN_INSTRUMENTS), "plugins": plugins}

    @mcp.tool()
    def get_history() -> dict:
        """The undo history: each step's name, and `position` (how many steps are done; the rest are undone)."""
        return client.call("history")

    # ---- notes ----------------------------------------------------------------------------------------------
    @mcp.tool()
    def write_notes(pattern: int, notes: list[dict], channel: int | None = None, replace: bool = True,
                    unit: Unit = "beats", name: str = "Write notes") -> dict:
        """Write notes into pattern `pattern` (an id).

        notes: [{"channel": id, "position": 0, "length": 0.5, "key": 60, "velocity": 100, "pan": 64}, ...];
        position/length in `unit` (beats by default). `channel` fills in notes that leave theirs out.
        replace=True: these become the notes of `channel` in the pattern (or all of its notes when channel is None);
        replace=False: they are added to what is there.
        """
        ppq = _ppq()
        out = []
        for n in notes:
            n = dict(n)
            if "channel" not in n:
                if channel is None:
                    raise LynxError("each note needs a `channel`, or give `channel` for all of them")
                n["channel"] = channel
            n["position"] = _to_ticks(n.get("position", 0), unit, ppq)
            if "length" in n:
                n["length"] = _to_ticks(n["length"], unit, ppq)
            out.append(n)
        if replace:
            cmd = {"op": "set_notes", "pattern": pattern, "notes": out, "channel": channel}
        else:
            cmd = {"op": "add_notes", "pattern": pattern, "notes": out}
        _edit(name, cmd)
        return {"pattern": pattern, "written": len(out), "replaced": replace}

    @mcp.tool()
    def clear_notes(pattern: int, channel: int | None = None) -> dict:
        """Remove the notes of `channel` from pattern `pattern` (or all of its notes when channel is None)."""
        _edit("Clear notes", {"op": "set_notes", "pattern": pattern, "notes": [], "channel": channel})
        return {"pattern": pattern, "cleared": True}

    # ---- channels -------------------------------------------------------------------------------------------
    @mcp.tool()
    def add_channel(name: str | None = None, instrument: str | None = None, sample: str | None = None,
                    mixer_track: int | None = None) -> dict:
        """Add a channel played by `instrument`: a built-in one (synth, kick, snare, hat, clap, sampler) or an
        instrument plugin's name from list_plugins (e.g. "Serum 2"); default synth. `sample`: an audio file to play
        in a sampler instead. mixer_track: a mixer track index to route it to (default: a new or free insert).
        Returns its id."""
        r = _edit("Add channel", {"op": "add_channel", "name": name, "instrument": instrument,
                                  "sample": str(Path(sample).expanduser()) if sample else None, "track": mixer_track})
        return {"channel": r[0]["id"], "index": r[0]["index"]}

    @mcp.tool()
    def set_channel(channel: int, name: str | None = None, volume: float | None = None, pan: float | None = None,
                    muted: bool | None = None, mixer_track: int | None = None) -> dict:
        """Change channel `channel` (an id): volume 0..1, pan -1..1, muted, mixer_track (an index). Only the
        fields given change."""
        _edit("Set channel", {"op": "set_channel", "channel": channel, "name": name, "volume": volume, "pan": pan,
                              "muted": muted, "track": mixer_track})
        return {"channel": channel}

    @mcp.tool()
    def set_synth(channel: int, osc: list[dict] | None = None, attack: float | None = None,
                  decay: float | None = None, sustain: float | None = None, release: float | None = None,
                  cutoff: float | None = None, resonance: float | None = None, key_track: float | None = None,
                  filter_type: Literal["lowpass", "bandpass", "highpass", "bandstop"] | None = None,
                  ladder: bool | None = None, mono: bool | None = None, porta: bool | None = None,
                  porta_beats: float | None = None, chorus: int | None = None,
                  filter_env: dict | None = None) -> dict:
        """Shape the sound of a channel whose instrument is the built-in "synth". Fields left out stay as they are.

        osc: up to 3 oscillators, [{"wave": "sine|triangle|saw|square|noise", "octave": -3..3, "semitones": -11..11,
        "detune": -100..100 cents, "level": 0..1, "pan": -1..1}, ...] (oscillator 1 first).
        attack/decay/release in seconds (0..10), sustain 0..1. cutoff in Hz (20..20000), resonance 0..1,
        key_track 0..2. ladder: the ladder filter. mono / porta (glide) / porta_beats (glide time, 0..4 beats).
        chorus 0..3. filter_env: {"amount": octaves -10..10, "attack", "hold", "decay", "release" (s), "sustain" 0..1}.
        """
        _edit("Synth", {"op": "set_synth", "channel": channel, "osc": osc, "attack": attack, "decay": decay,
                        "sustain": sustain, "release": release, "cutoff": cutoff, "resonance": resonance,
                        "key_track": key_track, "filter_type": filter_type, "ladder": ladder, "mono": mono,
                        "porta": porta, "porta_beats": porta_beats, "chorus": chorus, "filter_env": filter_env})
        return {"channel": channel}

    @mcp.tool()
    def delete_channel(channel: int) -> dict:
        """Delete channel `channel` (an id), with its notes."""
        _edit("Delete channel", {"op": "delete_channel", "channel": channel})
        return {"deleted": channel}

    # ---- patterns and playlist ------------------------------------------------------------------------------
    @mcp.tool()
    def add_pattern(name: str | None = None) -> dict:
        """Add a pattern. Returns its id."""
        r = _edit("Add pattern", {"op": "add_pattern", "name": name})
        return {"pattern": r[0]["id"], "index": r[0]["index"]}

    @mcp.tool()
    def delete_pattern(pattern: int) -> dict:
        """Delete pattern `pattern` (an id) and its playlist clips."""
        _edit("Delete pattern", {"op": "delete_pattern", "pattern": pattern})
        return {"deleted": pattern}

    @mcp.tool()
    def rename_pattern(pattern: int, name: str) -> dict:
        """Rename pattern `pattern` (an id) to `name`."""
        _edit("Rename pattern", {"op": "set_pattern", "pattern": pattern, "name": name})
        return {"pattern": pattern, "name": name}

    @mcp.tool()
    def place_pattern(pattern: int, position: float, track: int = 0, length: float | None = None,
                      unit: Unit = "beats") -> dict:
        """Place pattern `pattern` (an id) in the playlist on track `track` (0-based) at `position`. length defaults
        to the pattern's own length. Returns the clip id."""
        ppq = _ppq()
        r = _edit("Place pattern", {"op": "add_clip", "pattern": pattern, "track": track,
                                    "position": _to_ticks(position, unit, ppq), "length": _to_ticks(length, unit, ppq)})
        return {"clip": r[0]["id"]}

    @mcp.tool()
    def delete_clip(clip: int) -> dict:
        """Remove playlist clip `clip` (an id)."""
        _edit("Delete clip", {"op": "delete_clip", "clip": clip})
        return {"deleted": clip}

    # ---- project settings -----------------------------------------------------------------------------------
    @mcp.tool()
    def set_tempo(bpm: float) -> dict:
        """Set the tempo (10..999 BPM)."""
        _edit("Tempo", {"op": "set_tempo", "bpm": bpm})
        return {"bpm": bpm}

    # ---- transport ------------------------------------------------------------------------------------------
    @mcp.tool()
    def play(mode: Literal["pattern", "song"] | None = None, pattern: int | None = None,
             from_position: float | None = None, unit: Unit = "beats") -> dict:
        """Start playback.

        mode: "pattern" loops the current pattern, "song" plays the playlist (default: the app's current mode).
        pattern: make this pattern (an id) the current one. from_position: where to start.
        """
        ppq = _ppq()
        t = client.call("play", mode=mode, pattern=pattern, **{"from": _to_ticks(from_position, unit, ppq)})
        return _transport(t, unit)

    @mcp.tool()
    def pause(unit: Unit = "beats") -> dict:
        """Stop playback but keep the playhead where it is (play resumes from there)."""
        return _transport(client.call("pause"), unit)

    @mcp.tool()
    def stop(unit: Unit = "beats") -> dict:
        """Stop playback."""
        return _transport(client.call("stop"), unit)

    @mcp.tool()
    def transport_status(unit: Unit = "beats") -> dict:
        """Playing or stopped; pattern or song mode; the playhead position; the tempo."""
        return _transport(client.call("transport"), unit)

    @mcp.tool()
    def select(pattern: int | None = None, channel: int | None = None, piano_roll: bool | None = None) -> dict:
        """Change what the user sees, not the music: make `pattern` (an id) the current pattern, select `channel`
        (an id) in the channel rack, and with piano_roll=True open the piano roll on them. No undo step. Use it after
        writing notes so the user sees them."""
        s = client.call("select", pattern=pattern, channel=channel, piano_roll=piano_roll)
        return {"current_pattern": s["current_pattern"], "selected_channel": s["selected_channel"],
                "piano_roll": bool(piano_roll)}

    # ---- undo, save, raw commands ---------------------------------------------------------------------------
    @mcp.tool()
    def undo() -> dict:
        """Undo the last step (anyone's: this client's or the user's)."""
        return client.call("undo")

    @mcp.tool()
    def redo() -> dict:
        """Redo the last undone step."""
        return client.call("redo")

    @mcp.tool()
    def save_project(path: str | None = None) -> dict:
        """Save the project as a .lynx file at `path` (default: the file lynx_launch opened or this tool last saved).
        Only when the user asks."""
        global _project_path
        target = str(Path(path).expanduser().resolve()) if path else _project_path
        if not target:
            raise LynxError("give a `path` to save to (.lynx): this session has not opened or saved a project file")
        r = client.call("save", path=target)
        _project_path = r["path"]
        return r

    @mcp.tool()
    def apply_commands(commands: list[dict], name: str = "Edit") -> dict:
        """Run raw control-socket commands as ONE undo step, all or nothing. Positions and lengths here are raw
        ticks; note velocity and pan 0..128. Each command is {"op": ..., fields...}. Ops: add_channel {name,
        instrument, sample, track}, set_channel {channel, name, volume, pan, muted, track}, delete_channel {channel},
        set_synth {channel, ...}, add_pattern {name}, set_pattern {pattern, name},
        delete_pattern {pattern}, set_notes / add_notes {pattern,
        notes[], channel}, add_clip {pattern, track, position, length}, delete_clip {clip}, set_tempo {bpm}.
        Returns each command's result (new things' ids)."""
        return {"results": client.apply(commands, name=name)}

    return mcp


def main() -> None:
    build_app().run()


if __name__ == "__main__":
    main()
