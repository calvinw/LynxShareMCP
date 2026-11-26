"""lynx-share-mcp: an MCP server that drives LYNX SHARE through its official Remote Control API (lynx-control/1).

Run with:
    python -m lynx_share_mcp        # stdio, started by an MCP client such as Claude Code or Codex
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from .remote import LynxError, RemoteClient

logging.basicConfig(level=os.environ.get("LYNX_MCP_LOG_LEVEL", "INFO").upper(), stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lynx_share_mcp")

client = RemoteClient()

# Used when LYNX_BIN is unset: a LYNX-SHARE clone next to this repo, built with CMake into build/. JUCE's build output
# is an app bundle on macOS and a plain executable on Linux.
_BUILD = Path(__file__).resolve().parents[3] / "LYNX-SHARE" / "build" / "LYNX_artefacts" / "Release"
DEFAULT_BIN = str(_BUILD / "LYNX.app/Contents/MacOS/LYNX" if sys.platform == "darwin" else _BUILD / "LYNX")

Unit = Literal["beats", "ticks"]
Ref = str | int  # an id from get_project_state, a name, or a 0-based index

# Every note field pattern.replace_notes requires, with LYNX's defaults (core/Song.h's Note).
NOTE_DEFAULTS: dict[str, Any] = {
    "start": 0, "length": 240, "channel": 0, "key": 60, "velocity": 0.78, "pan": 0.0, "muted": False,
    "finePitch": 0.0, "slide": False, "porta": False, "release": 0.5, "modX": 0.5, "modY": 0.5, "colour": 0,
    "group": 0, "chance": 1.0, "velocityRange": 0.0, "chanceGroup": 0, "chanceOne": False,
}
# LYNX SHARE 0.1.30+ requires each note's MPE curves; 0.1.29 rejects the field. Added only when the app wants it.
NO_EXPRESSION: dict[str, Any] = {"pitch": [], "timbre": [], "pressure": []}
CONTINUOUS = 2**31 - 1  # numSteps of a continuous parameter

INSTRUCTIONS = """\
Controls LYNX SHARE, an open-source FL Studio-style DAW, through its official Remote Control API.

How the project works:
- get_project_state lists channels, patterns, playlist clips and mixer tracks. Refer to a channel or pattern by its
  id (e.g. "0000010000000005"), its exact name, or its 0-based index. Ids stay the same when other things are added or
  deleted; indices shift. Mixer tracks are indices (0 = master), playlist tracks are 0-based indices.
- Positions and lengths are in beats (quarter notes) by default; pass unit="ticks" for raw ticks (ppq = 960 per
  beat). get_project_state reports ticks.
- Note keys are MIDI numbers: 60 = middle C. Velocity 0..1 (default 0.78), note pan -1..1 (0 = centre).
- To hear notes a channel needs an instrument from list_instruments: built-in ones (Synth, Kick, Snare, Hat, Clap,
  3x Osc, ...) or plugins such as "Serum 2".
- Plugin sounds (e.g. Serum 2) are shaped with plugin_params (search parameters by name) and set_plugin_params.
  Values are normalized 0..1; plugin_params shows what each value means (displayValue, e.g. "425 Hz"). Serum 2's
  Macro 1-8 are usually the most musical controls. A switch or menu parameter (steps > 1) snaps to its steps.
- A good layout is one channel per pattern (e.g. a "Bass" pattern holding only the bass channel's notes), so the
  sections of a song are built by placing patterns in the playlist (place_pattern), stacked on different tracks.
- Every edit tool is one undo step; the user can undo it with Cmd+Z (Ctrl+Z on Linux).

Limits of this API:
- Edits are refused while LYNX is playing: call stop first.
- An edit is refused when the project changed since it was read (code "changed"): read again and redo the plan.
- An "uncertain" error means the edit may have happened: read the project before doing anything else.
- A stock LYNX SHARE release cannot save, pause, play from a position, select a channel or open the piano roll
  through this API (those tools then say so; ask the user). Builds of calvinw/LYNX-SHARE's remote-api-ui branch can.
- The piano roll shows ONE channel in the CURRENT pattern. After writing notes the user should look at, call
  select(pattern=..., channel=..., piano_roll=True).
- Do not save after every edit: save_project only when the user asks.

Writing music:
- Chords with no bass under them need the root as the lowest note, or the harmony is misheard.
- Check each bass note against the chord sounding in the same bar (root, third or fifth unless it is a deliberate
  passing note).

If a call says Remote Control is not on, call lynx_launch (or ask the user to turn on Settings > General >
Remote control).
"""


# ---- helpers ----------------------------------------------------------------------------------------------------
def _to_ticks(v: float | None, unit: Unit, ppq: int) -> int | None:
    if v is None:
        return None
    return int(round(v * ppq)) if unit == "beats" else int(round(v))


def _from_ticks(t: float | None, unit: Unit, ppq: int) -> float | None:
    if t is None:
        return None
    return round(t / ppq, 6) if unit == "beats" else t


def _binary() -> str:
    return str(Path(os.environ.get("LYNX_BIN", DEFAULT_BIN)).expanduser())


_ops: dict[str, set[str]] = {}


def _operations() -> set[str]:
    """api.describe's operations, per running app (its controlEpoch)."""
    d = client.call("api.describe")
    key = d["controlEpoch"]
    if key not in _ops:
        _ops.clear()
        _ops[key] = set(d["operations"])
    return _ops[key]


def _session() -> dict[str, Any]:
    return client.call("session.inspect")


def _find(rows: list[dict], ref: Ref, id_key: str, what: str) -> dict:
    """The row of `rows` that `ref` names: an id, an exact (then case-insensitive) name, or an index."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit() and len(ref) < 6):
        i = int(ref)
        if 0 <= i < len(rows):
            return rows[i]
        raise LynxError(f"no {what} at index {i} (there are {len(rows)})", "invalid")
    for match in (lambda r: r.get(id_key) == ref, lambda r: r.get("name") == ref,
                  lambda r: str(r.get("name", "")).lower() == str(ref).lower()):
        found = [r for r in rows if match(r)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise LynxError(f"{len(found)} {what}s are named {ref!r}; use an id", "invalid")
    names = ", ".join(repr(r.get("name")) for r in rows[:40])
    raise LynxError(f"no {what} {ref!r}; there are: {names}", "invalid")


def _channel(s: dict, ref: Ref) -> dict:
    return _find(s["channels"], ref, "channelId", "channel")


def _pattern(s: dict, ref: Ref) -> dict:
    return _find(s["patterns"], ref, "patternId", "pattern")


def _all_notes(index: int) -> list[dict]:
    notes: list[dict] = []
    offset = 0
    while True:
        page = client.call("pattern.notes", {"index": index, "offset": offset, "limit": 256})
        notes += page["notes"]
        if "nextOffset" not in page:
            return notes
        offset = page["nextOffset"]


def _instrument(name: str) -> dict:
    """The catalog entry named `name` (exact, then case-insensitive; a VST3 is preferred over an AU since it reports
    its parameters' steps)."""
    cat = client.call("instrument.catalog", {"query": name, "limit": 256})["instruments"]
    for match in (lambda i: i["name"] == name, lambda i: i["name"].lower() == name.lower()):
        found = [i for i in cat if match(i) and i.get("available", True)]
        if found:
            order = {"VST3": 0, "CLAP": 1, "AudioUnit": 2}
            return sorted(found, key=lambda i: order.get(i.get("format", ""), 3))[0]
    if cat:
        raise LynxError(f"unknown instrument {name!r}; did you mean one of: "
                        + ", ".join(sorted({i['name'] for i in cat})[:20]), "invalid")
    raise LynxError(f"unknown instrument {name!r}; see list_instruments", "invalid")


def _plugin_target(s: dict, channel: Ref) -> dict:
    ch = _channel(s, channel)
    return {"kind": "instrument", "channelIndex": ch["index"]}


def _all_params(target: dict) -> tuple[dict, list[dict]]:
    first = client.call("plugin.inspect", {"target": target, "offset": 0, "limit": 256})
    params = list(first["parameters"])
    offset = first.get("nextOffset")
    while offset is not None:
        page = client.call("plugin.inspect", {"target": target, "offset": offset, "limit": 256})
        params += page["parameters"]
        offset = page.get("nextOffset")
    return first, params


def _param_row(p: dict) -> dict:
    row = {"index": p["index"], "name": p["name"], "value": round(p["value"], 5),
           "display": (p.get("displayValue") or "").strip() + (f" {p['label']}" if p.get("label") else "")}
    steps = p.get("numSteps", CONTINUOUS)
    if 1 < steps < CONTINUOUS:
        row["steps"] = steps
    if p.get("readOnly"):
        row["read_only"] = True
    return row


def _snap(value: float, steps: int) -> float:
    if 1 < steps < CONTINUOUS:
        return round(value * (steps - 1)) / (steps - 1)
    return value


def _transport(s: dict, unit: Unit) -> dict:
    ppq = int(s.get("ppq", 960))
    return {"state": "playing" if s["playing"] else "stopped", "mode": "song" if s["songMode"] else "pattern",
            "position": _from_ticks(s["positionTicks"], unit, ppq), "unit": unit, "bpm": s["bpm"],
            "current_pattern": s.get("currentPattern"), "recording": s.get("recording", False)}


def _remap_delete(doc: dict, kind: Literal["channel", "pattern"], index: int) -> list[dict]:
    """JSON Patch ops that delete channel/pattern `index` from the native document and renumber what refers to the
    ones after it: notes' channels, and playlist clips (pattern clips' patterns, audio clips' channels). Refuses
    documents with references this does not know how to renumber."""
    unknown = [k for k in ("automations", "arrangements", "grooves") if doc.get(k)]
    if unknown:
        raise LynxError(f"deleting a {kind} is not supported yet in projects with {', '.join(unknown)}; "
                        "delete it in LYNX SHARE's window", "invalid")
    ops: list[dict] = []
    clips = doc.get("playlist", [])
    kept = []
    for c in clips:
        is_pattern, source = (c[5] == 0 if len(c) > 5 else True), (c[6] if len(c) > 6 else -1)
        if kind == "pattern" and is_pattern:
            if c[0] == index:
                continue
            if c[0] > index:
                c = [c[0] - 1, *c[1:]]
        if kind == "channel" and len(c) > 6 and c[5] == 1:
            if source == index:
                continue
            if source > index:
                c = [*c[:6], source - 1, *c[7:]]
        kept.append(c)
    if kept != clips:
        ops.append({"op": "replace", "path": "/playlist", "value": kept})
    if kind == "channel":
        for pi, p in enumerate(doc.get("patterns", [])):
            notes = p.get("notes", [])
            new = [[*n[:2], n[2] - 1 if n[2] > index else n[2], *n[3:]] for n in notes if n[2] != index]
            if new != notes:
                ops.append({"op": "replace", "path": f"/patterns/{pi}/notes", "value": new})
        ops.append({"op": "remove", "path": f"/channels/{index}"})
    else:
        ops.append({"op": "remove", "path": f"/patterns/{index}"})
        cur = doc.get("currentPattern", 0)
        if cur > index or cur == len(doc["patterns"]) - 1:
            ops.append({"op": "replace", "path": "/currentPattern", "value": max(0, cur - 1)})
    if len(ops) > 128:
        raise LynxError(f"this delete needs {len(ops)} document changes (the limit is 128)", "limit")
    return ops


# ---- the server -------------------------------------------------------------------------------------------------
def build_app() -> MCPServer:
    mcp = MCPServer("lynx-share", instructions=INSTRUCTIONS)

    # ---- connection -----------------------------------------------------------------------------------------
    @mcp.tool()
    def lynx_launch(project: str | None = None) -> dict:
        """Start LYNX SHARE (with its window) with Remote Control on. Does nothing if it is already reachable.

        project: a .lynx file to open (otherwise the demo song loads).
        """
        if client.connected():
            return {"running": True, "already": True}
        exe = _binary()
        if not os.access(exe, os.X_OK):
            raise LynxError(f"LYNX SHARE's binary was not found at {exe}; set LYNX_BIN to it (see the README)")
        args = [exe]
        if project:
            p = Path(project).expanduser().resolve()  # LYNX opens only its first argument, and only an absolute path
            if not p.is_file():
                raise LynxError(f"no such project file: {p}")
            args.append(str(p))
        log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "lynx-share-mcp-app.log"
        env = {**os.environ, "LYNX_CONTROL_ENABLED": "1"}
        with open(log_path, "ab") as out:
            subprocess.Popen(args, stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True, env=env)
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(0.5)
            if client.connected():
                return {"running": True, "project": args[1] if project else None, "log": str(log_path)}
        raise LynxError(f"LYNX SHARE did not turn on Remote Control within 30 s; see {log_path}. If LYNX SHARE was "
                        "already open, turn on Settings > General > Remote control there instead.")

    @mcp.tool()
    def lynx_status() -> dict:
        """Whether LYNX SHARE is reachable; its version, the open project, the transport and undo availability."""
        s = client.call("status")
        return {"app_version": s["appVersion"], "project": s["project"], "transport": _transport(s, "beats"),
                "can_undo": s["canUndo"], "can_redo": s["canRedo"], "revision": s["revision"],
                "channels": s["channelCount"], "patterns": s["patternCount"]}

    # ---- reading --------------------------------------------------------------------------------------------
    @mcp.tool()
    def get_project_state() -> dict:
        """The whole project: ppq, bpm, meter, song/pattern mode, the current pattern, channels (channelId, name,
        instrument, mixer track, volume 0..1, pan -1..1, muted), patterns (patternId, name, length, note count),
        playlist clips (clipId, kind, pattern index, track, start, length) and mixer tracks. Positions and lengths
        here are raw ticks."""
        s = _session()
        pl = client.call("playlist.inspect", {"limit": 250})
        clips = [{k: c[k] for k in ("clipId", "kind", "pattern", "channel", "track", "start", "length", "offset",
                                    "muted")} for c in pl["clips"]]
        return {"ppq": s["ppq"], "bpm": s["bpm"], "beatsPerBar": s["beatsPerBar"], "beatUnit": s["beatUnit"],
                "barTicks": s["barTicks"], "mode": "song" if s["songMode"] else "pattern",
                "currentPattern": s["currentPattern"], "playing": s["playing"], "project": s["project"],
                "channels": s["channels"], "patterns": s["patterns"], "clips": clips,
                "clipsTotal": pl["totalClips"], "playlistTracks": len(pl["tracks"]), "mixer": s["mixer"]}

    @mcp.tool()
    def get_notes(pattern: Ref, unit: Unit = "beats", channel: Ref | None = None) -> dict:
        """The notes of `pattern` (id, name or index): channel index, position, length, key, velocity 0..1, pan
        -1..1, muted (and LYNX's other note fields). channel: only that channel's notes."""
        s = _session()
        p = _pattern(s, pattern)
        notes = _all_notes(p["index"])
        if channel is not None:
            ci = _channel(s, channel)["index"]
            notes = [n for n in notes if n["channel"] == ci]
        out = []
        for n in notes:
            n = dict(n)
            n["position"] = _from_ticks(n.pop("start"), unit, s["ppq"])
            n["length"] = _from_ticks(n["length"], unit, s["ppq"])
            out.append(n)
        return {"pattern": p["patternId"], "name": p["name"], "notes": out, "unit": unit}

    @mcp.tool()
    def list_instruments(query: str | None = None) -> dict:
        """The instruments a channel can use: LYNX's built-in ones (Synth, Kick, Snare, Hat, Clap, 3x Osc, ...) and
        scanned plugins (VST3/AU/CLAP, e.g. Serum 2). add_channel takes a name from here. query: filter by name."""
        found, offset = [], 0
        while True:
            page = client.call("instrument.catalog", {"query": query, "offset": offset, "limit": 256})
            found += page["instruments"]
            offset += len(page["instruments"])
            if not page["instruments"] or offset >= page["count"]:
                break
        return {"instruments": [{"name": i["name"], "type": i["type"], "format": i.get("format"),
                                 "manufacturer": i.get("manufacturer"), "available": i.get("available", True)}
                                for i in found]}

    # ---- notes ----------------------------------------------------------------------------------------------
    @mcp.tool()
    def write_notes(pattern: Ref, notes: list[dict], channel: Ref | None = None, replace: bool = True,
                    unit: Unit = "beats") -> dict:
        """Write notes into `pattern`.

        notes: [{"position": 0, "length": 0.5, "key": 60, "velocity": 0.8, "pan": 0, "channel": ...}, ...];
        position/length in `unit` (beats by default). `channel` (id, name or index) fills in notes that leave theirs
        out. replace=True: these become the notes of `channel` in the pattern (or all of its notes when channel is
        None); replace=False: they are added to what is there. Other LYNX note fields (muted, slide, porta,
        finePitch, chance, ...) may be given too.
        """
        s = _session()
        p = _pattern(s, pattern)
        ci = _channel(s, channel)["index"] if channel is not None else None
        new = []
        for n in notes:
            n = dict(n)
            if "channel" in n:
                n["channel"] = _channel(s, n["channel"])["index"]
            elif ci is None:
                raise LynxError("each note needs a `channel`, or give `channel` for all of them", "invalid")
            else:
                n["channel"] = ci
            n["start"] = _to_ticks(n.pop("position", 0), unit, s["ppq"])
            n["length"] = _to_ticks(n["length"], unit, s["ppq"]) if "length" in n else s["ppq"] // 4
            unknown = set(n) - set(NOTE_DEFAULTS) - {"expression"}
            if unknown:
                raise LynxError(f"unknown note fields: {sorted(unknown)}", "invalid")
            new.append({**NOTE_DEFAULTS, **n})
        old = _all_notes(p["index"])
        if replace:
            kept = [] if ci is None else [x for x in old if x["channel"] != ci]
        else:
            kept = old
        notes_out = kept + new
        if any("expression" in x for x in old):
            notes_out = [{"expression": NO_EXPRESSION, **x} for x in notes_out]
        try:
            r = client.write("pattern.replace_notes", {"index": p["index"], "notes": notes_out}, observed=s)
        except LynxError as e:
            if "expression" not in str(e) or all("expression" in x for x in notes_out):
                raise
            # A refused edit changed nothing: send again with every note's expression (newer LYNX).
            notes_out = [{"expression": NO_EXPRESSION, **x} for x in notes_out]
            r = client.write("pattern.replace_notes", {"index": p["index"], "notes": notes_out}, observed=s)
        return {"pattern": p["patternId"], "written": len(new), "replaced": replace, "total_notes": r["noteCount"]}

    @mcp.tool()
    def clear_notes(pattern: Ref, channel: Ref | None = None) -> dict:
        """Remove the notes of `channel` from `pattern` (or all of its notes when channel is None)."""
        s = _session()
        p = _pattern(s, pattern)
        kept = []
        if channel is not None:
            ci = _channel(s, channel)["index"]
            kept = [n for n in _all_notes(p["index"]) if n["channel"] != ci]
        client.write("pattern.replace_notes", {"index": p["index"], "notes": kept}, observed=s)
        return {"pattern": p["patternId"], "cleared": True, "remaining": len(kept)}

    # ---- channels -------------------------------------------------------------------------------------------
    @mcp.tool()
    def add_channel(instrument: str = "Synth", name: str | None = None, mixer_track: int | None = None) -> dict:
        """Add a channel played by `instrument`, a name from list_instruments (e.g. "Synth", "Kick", "Serum 2").
        mixer_track: a mixer track index to route it to (default: a new or free insert). Returns its id."""
        inst = _instrument(instrument)
        r = client.write("channel.create", {"instrumentId": inst["instrumentId"], "name": name,
                                            "mixerIndex": mixer_track})
        s = _session()
        ch = s["channels"][r["channelIndex"]]
        return {"channel": ch["channelId"], "index": ch["index"], "name": ch["name"], "instrument": inst["name"],
                "format": inst.get("format"), "mixer_track": r.get("mixerIndex")}

    @mcp.tool()
    def set_channel(channel: Ref, name: str | None = None, volume: float | None = None, pan: float | None = None,
                    muted: bool | None = None, mixer_track: int | None = None) -> dict:
        """Change `channel` (id, name or index): volume 0..1, pan -1..1, muted, name, mixer_track (an index). Only
        the fields given change (a rename or re-route is its own undo step)."""
        s = _session()
        ch = _channel(s, channel)
        if volume is not None or pan is not None or muted is not None:
            client.write("channel.set", {"index": ch["index"], "volume": volume, "pan": pan, "muted": muted},
                         observed=s)
        if name is not None or mixer_track is not None:
            doc, snap = client.read_project()
            patch = []
            if name is not None:
                patch.append({"op": "replace", "path": f"/channels/{ch['index']}/name", "value": name})
            if mixer_track is not None:
                patch.append({"op": "replace", "path": f"/channels/{ch['index']}/mixer", "value": mixer_track})
            client.edit_project(patch, snap)
        return {"channel": ch["channelId"]}

    @mcp.tool()
    def delete_channel(channel: Ref) -> dict:
        """Delete `channel` (id, name or index) with its notes and audio clips."""
        s = _session()
        ch = _channel(s, channel)
        doc, snap = client.read_project()
        if doc["channels"][ch["index"]].get("uid") != ch["channelId"]:
            raise LynxError("the project changed while reading it; try again", "changed")
        client.edit_project(_remap_delete(doc, "channel", ch["index"]), snap)
        return {"deleted": ch["channelId"], "name": ch["name"]}

    # ---- plugin sounds --------------------------------------------------------------------------------------
    @mcp.tool()
    def plugin_params(channel: Ref, search: str | None = None, include_midi_cc: bool = False,
                      limit: int = 80) -> dict:
        """The parameters of `channel`'s plugin instrument (e.g. Serum 2): index, name, value (normalized 0..1),
        display (what it means, e.g. "425" Hz, "MG Low 12", "On"), steps (for switches/menus).

        search: words that must all appear in the name, case-insensitive (e.g. "filter 1", "env 1", "macro",
        "A uni"); a | separates alternatives ("cutoff|freq"). Serum 2 has ~2600 parameters, most of them per-MIDI-CC
        mappings that include_midi_cc=False hides."""
        s = _session()
        info, params = _all_params(_plugin_target(s, channel))
        if not include_midi_cc:
            params = [p for p in params if not re.match(r"CC\d+ ", p["name"])]
        if search:
            alts = [a.lower().split() for a in search.split("|")]
            params = [p for p in params if any(all(w in p["name"].lower() for w in words) for words in alts)]
        rows = [_param_row(p) for p in params]
        return {"plugin": info["name"], "plugin_id": info.get("pluginId"), "parameter_count": info["parameterCount"],
                "matched": len(rows), "parameters": rows[:limit],
                **({"truncated": True} if len(rows) > limit else {})}

    @mcp.tool()
    def set_plugin_params(channel: Ref, values: dict[str, float]) -> dict:
        """Set parameters of `channel`'s plugin instrument as ONE undo step. values: {parameter name or index:
        normalized value 0..1}, e.g. {"Filter 1 On": 1, "Filter 1 Freq": 0.3, "Macro 1": 0.7}. A parameter with
        steps snaps to the nearest one. Returns each parameter's new display value. Refused while playing."""
        s = _session()
        target = _plugin_target(s, channel)
        info, params = _all_params(target)
        by_name: dict[str, list[dict]] = {}
        for p in params:
            by_name.setdefault(p["name"].lower(), []).append(p)
        changes = []
        for key, value in values.items():
            if isinstance(key, int) or str(key).isdigit():
                i = int(key)
                if not 0 <= i < len(params):
                    raise LynxError(f"no parameter index {i} (there are {len(params)})", "invalid")
                p = params[i]
            else:
                found = by_name.get(str(key).lower(), [])
                if len(found) != 1:
                    near = [q["name"] for q in params if str(key).lower() in q["name"].lower()][:12]
                    raise LynxError(f"{'no' if not found else 'more than one'} parameter named {key!r}"
                                    + (f"; similar: {near}" if near else "; use plugin_params to search"), "invalid")
                p = found[0]
            if p.get("readOnly"):
                raise LynxError(f"{p['name']!r} is read-only", "invalid")
            if not 0 <= float(value) <= 1:
                raise LynxError(f"{p['name']!r}: values are normalized 0..1 (got {value})", "invalid")
            changes.append((p, _snap(float(value), p.get("numSteps", CONTINUOUS))))
        client.write("plugin.parameters_set", {"target": target, "parameters": [
            {"index": p["index"], "value": v, "expectedValue": p["value"]} for p, v in changes]}, observed=s)
        after = []
        for p, _ in changes:
            q = client.call("plugin.inspect", {"target": target, "offset": p["index"], "limit": 1})["parameters"][0]
            after.append(_param_row(q))
        return {"plugin": info["name"], "changed": after}

    # ---- patterns and playlist ------------------------------------------------------------------------------
    @mcp.tool()
    def add_pattern(name: str | None = None, bars: int | None = None) -> dict:
        """Add a pattern (it becomes the current one). bars: a fixed length in bars (default: follows its notes).
        Returns its id."""
        s = client.call("status")
        r = client.write("pattern.create", {"name": name, "lengthTicks": bars * s["barTicks"] if bars else None},
                         observed=s)
        return {"pattern": r["patternId"], "index": r["index"], "name": r["name"]}

    @mcp.tool()
    def rename_pattern(pattern: Ref, name: str) -> dict:
        """Rename `pattern` (id, name or index) to `name`."""
        s = _session()
        p = _pattern(s, pattern)
        client.write("pattern.set", {"index": p["index"], "name": name}, observed=s)
        return {"pattern": p["patternId"], "name": name}

    @mcp.tool()
    def delete_pattern(pattern: Ref) -> dict:
        """Delete `pattern` (id, name or index) and its playlist clips."""
        s = _session()
        p = _pattern(s, pattern)
        doc, snap = client.read_project()
        if doc["patterns"][p["index"]].get("uid") != p["patternId"]:
            raise LynxError("the project changed while reading it; try again", "changed")
        client.edit_project(_remap_delete(doc, "pattern", p["index"]), snap)
        return {"deleted": p["patternId"], "name": p["name"]}

    @mcp.tool()
    def place_pattern(pattern: Ref, position: float, track: int = 0, length: float | None = None,
                      unit: Unit = "beats") -> dict:
        """Place `pattern` (id, name or index) in the playlist on track `track` (0-based) at `position`. length
        defaults to the pattern's own length. Returns the clip id."""
        s = _session()
        p = _pattern(s, pattern)
        ticks = _to_ticks(length, unit, s["ppq"]) if length is not None else p["effectiveLengthTicks"]
        r = client.write("playlist.edit", {"edits": [{"action": "add", "kind": "pattern", "pattern": p["index"],
                                                      "track": track, "start": _to_ticks(position, unit, s["ppq"]),
                                                      "length": ticks}]}, observed=s)
        return {"clip": r["createdClipIds"][0]}

    @mcp.tool()
    def delete_clip(clip: str) -> dict:
        """Remove playlist clip `clip` (a clipId from get_project_state)."""
        client.write("playlist.edit", {"edits": [{"action": "remove", "clipId": clip}]})
        return {"deleted": clip}

    # ---- project settings -----------------------------------------------------------------------------------
    @mcp.tool()
    def set_tempo(bpm: float) -> dict:
        """Set the tempo (BPM)."""
        r = client.write("tempo.set", {"bpm": bpm})
        return {"bpm": r["bpm"]}

    @mcp.tool()
    def set_mixer_track(track: int, volume: float | None = None, pan: float | None = None,
                        muted: bool | None = None, solo: bool | None = None) -> dict:
        """Change mixer track `track` (0 = master): volume 0..1, pan -1..1, muted, solo."""
        client.write("mixer.set", {"index": track, "volume": volume, "pan": pan, "muted": muted, "solo": solo})
        return {"track": track}

    # ---- transport ------------------------------------------------------------------------------------------
    def _extended() -> bool:
        """Whether this LYNX has the ui.select / project.save / transport.pause additions (calvinw/LYNX-SHARE's
        remote-api-ui branch); a stock release does not."""
        return "ui.select" in _operations()

    def _need(op: str, what: str) -> None:
        if op not in _operations():
            raise LynxError(f"this LYNX SHARE cannot {what} through Remote Control (no {op} operation); "
                            "ask the user to do it in the window", "invalid")

    def _show(mode: str | None, pattern: Ref | None) -> None:
        """Make `mode`/`pattern` current. A stock LYNX can only do it as a document edit (an undo step, stopped)."""
        if mode is None and pattern is None:
            return
        s = _session()
        patch = []
        if pattern is not None:
            p = _pattern(s, pattern)
            if p["index"] != s["currentPattern"]:
                patch.append({"op": "replace", "path": "/currentPattern", "value": p["index"]})
        if mode is not None and (mode == "song") != s["songMode"]:
            patch.append({"op": "replace", "path": "/mode", "value": mode})
        if patch:
            if s["playing"]:
                raise LynxError("stop playback before changing the mode or the current pattern", "busy")
            _, snap = client.read_project()
            client.edit_project(patch, snap)

    @mcp.tool()
    def play(mode: Literal["pattern", "song"] | None = None, pattern: Ref | None = None,
             from_position: float | None = None, unit: Unit = "beats") -> dict:
        """Start playback. mode: "pattern" loops the current pattern, "song" plays the playlist (default: as it is).
        pattern: make it the current pattern first. from_position: where to start (default: the playhead, e.g.
        where pause left it)."""
        if _extended():
            s = _session()
            args: dict[str, Any] = {"mode": mode}
            if pattern is not None:
                args["pattern"] = _pattern(s, pattern)["index"]
            if from_position is not None:
                args["fromTicks"] = _to_ticks(from_position, unit, s["ppq"])
            client.write("transport.play", args, observed=s)
        else:
            if from_position is not None:
                _need("transport.pause", "start playback from a given position")
            _show(mode, pattern)
            client.write("transport.play")
        return _transport(client.call("status"), unit)

    @mcp.tool()
    def pause(unit: Unit = "beats") -> dict:
        """Stop playback but keep the playhead where it is (play resumes from there)."""
        _need("transport.pause", "pause")
        client.call("transport.pause")
        return _transport(client.call("status"), unit)

    @mcp.tool()
    def stop(unit: Unit = "beats") -> dict:
        """Stop playback."""
        client.call("transport.stop")
        return _transport(client.call("status"), unit)

    @mcp.tool()
    def transport_status(unit: Unit = "beats") -> dict:
        """Playing or stopped; pattern or song mode; the playhead position; the tempo; the current pattern."""
        return _transport(client.call("status"), unit)

    @mcp.tool()
    def select(pattern: Ref | None = None, channel: Ref | None = None, piano_roll: bool = False,
               mode: Literal["pattern", "song"] | None = None) -> dict:
        """Change what the user sees, not the music: make `pattern` the current pattern, select `channel` in the
        channel rack, and with piano_roll=True open the piano roll on them; mode switches pattern/song mode. Use it
        after writing notes so the user sees them. No undo step (except `mode`)."""
        if _extended():
            s = _session()
            args: dict[str, Any] = {}
            if pattern is not None:
                args["pattern"] = _pattern(s, pattern)["index"]
            if channel is not None:
                args["channel"] = _channel(s, channel)["index"]
            if piano_roll:
                args["pianoRoll"] = True
            if args:
                client.call("ui.select", args)
            _show(mode, None)
        else:
            if channel is not None or piano_roll:
                _need("ui.select", "select a channel or open the piano roll")
            _show(mode, pattern)
        return _transport(client.call("status"), "beats")

    # ---- the project file -----------------------------------------------------------------------------------
    @mcp.tool()
    def save_project(path: str | None = None) -> dict:
        """Save the project like File > Save: to its own file, or to `path` (a .lynx file; also for a project that
        has no file yet). Only when the user asks."""
        _need("project.save", "save")
        target = str(Path(path).expanduser().resolve()) if path else None
        return {"path": client.call("project.save", {"path": target}, write=True)["path"]}

    @mcp.tool()
    def new_project(path: str | None = None) -> dict:
        """Start a fresh default project (File > New), saved to `path` when given. Refused while the open project
        has unsaved changes, so nothing is lost: save first (only if the user wants that)."""
        _need("project.new", "start a new project")
        target = str(Path(path).expanduser().resolve()) if path else None
        r = client.call("project.new", {"path": target}, write=True)
        return {"path": r["path"] or None}

    # ---- undo and raw access --------------------------------------------------------------------------------
    @mcp.tool()
    def undo() -> dict:
        """Undo the last step (anyone's: this client's or the user's). Needs playback stopped."""
        r = client.write("history.undo")
        return {"changed": r["changed"], "can_undo": r["canUndo"], "can_redo": r["canRedo"]}

    @mcp.tool()
    def redo() -> dict:
        """Redo the last undone step. Needs playback stopped."""
        r = client.write("history.redo")
        return {"changed": r["changed"], "can_undo": r["canUndo"], "can_redo": r["canRedo"]}

    @mcp.tool()
    def remote_call(op: str, args: dict | None = None) -> dict:
        """Call any Remote Control operation directly (api.describe lists them; see LYNX SHARE's
        docs/REMOTE_CONTROL.md), e.g. effect.catalog, effect.load, playlist.edit, instrument.replace. The project
        guard (expectedProjectId/Epoch/Revision) is filled in from a fresh status for edits. Raw units: ticks,
        indices, normalized values."""
        read_only = {"api.describe", "status", "changes", "session.inspect", "device.state", "pattern.notes",
                     "plugin.inspect", "effect.catalog", "instrument.catalog", "playlist.inspect", "transport.stop"}
        if op == "project.read" or op == "project.edit":
            raise LynxError("use the other tools; whole-document reads and edits are not exposed raw", "invalid")
        return client.call(op, args) if op in read_only else client.write(op, args)

    return mcp


def main() -> None:
    build_app().run()


if __name__ == "__main__":
    main()
