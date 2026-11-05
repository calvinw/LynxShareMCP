# LYNX SHARE MCP — Plan

An MCP server that lets Claude (Claude Code, Claude Desktop) drive **LYNX SHARE**, the open-source FL Studio-style DAW, while
it runs: read the project, write notes, build channels/patterns/playlist, play, undo, save.

## Where things stand (2026-11-04)

**Done: the app side (spike).** `~/develop/LYNX-SHARE`, branch `control-socket`, committed (cda122dc, rebased onto upstream 4f46c244 on 2026-11-05):

- `src/engine/ControlServer.{h,cpp}` — a Unix-socket JSON-RPC server, enabled with `--control /tmp/lynx.sock`.
  Requests run on the message thread; every `apply` is one `AudioEngine::editSong` step, so it undoes with Cmd+Z and is named
  in History automatically. `apply` is all-or-nothing (the ops run on a copy of the Song).
- Hooks: `src/Main.cpp` (`--control` flag, `startControlServer()`), `src/ui/MainComponent.h` (`selectPatternForControl`,
  `showPianoRollForControl`), `CMakeLists.txt`.
- Verified end to end with ad-hoc Python over the socket: a 40-bar, 5-section song with Serum 2 chords and bass, saved as
  `~/Documents/FirstProject.lynx`.

**Done (2026-11-05): Phase 1 code.** `src/lynx_share_mcp/` (26 tools), `tests/test_end_to_end.py` (2 tests, pass against the
real app), `install.sh`, README; registered in `~/.claude.json` (user scope) as `lynx-share`. Remaining for Phase 1:
the real-session check below (fresh Claude Code session, MCP tools only), and `git init` + first commit of this repo.
Protocol notes found while building: playlist tracks are 0-based; `save` needs a path (the MCP defaults it to the
project it launched); `transport` has `playing` (bool) and `position`, no paused state.

### Socket protocol (what the MCP talks to)

Newline-delimited JSON-RPC 2.0 over `/tmp/lynx.sock` (mode 0600), one client at a time — **the same framing and `apply`
shape as Lemon Studio**, so LemonStudioMCP's `client.py` works unchanged apart from names.

| Method | Params | Returns |
|---|---|---|
| `hello` | – | `{app, protocol, ppq}` |
| `state` | – | ppq, bpm, beats_per_bar, mode, current_pattern, selected_channel, channels[], patterns[], clips[], mixer[] |
| `notes` | `pattern` | `{pattern, notes[]}` |
| `plugins` | – | scanned VST3/AU/CLAP: `{name, manufacturer, format, instrument, id}` |
| `apply` | `commands[]`, `name` | `{results[]}` — one undo step, all or nothing |
| `play` | `mode` (song/pattern), `pattern`, `from` (ticks) | transport |
| `pause`, `stop`, `transport` | – | transport `{playing, position, mode, bpm, ppq}` |
| `select` | `pattern`, `channel`, `piano_roll` | state |
| `undo`, `redo` | – | `{position}` |
| `history` | – | `{steps[], position}` |
| `save` | `path` (required) | `{path}` |

`apply` ops: `add_channel {name, instrument | plugin, sample, track}`, `set_channel {channel, name, volume, pan, muted,
track}`, `delete_channel`, `set_synth {channel, osc[], attack, decay, sustain, release, cutoff, resonance, filter_type,
ladder, mono, porta, chorus, filter_env{}}`, `add_pattern {name}`, `delete_pattern`, `set_notes` / `add_notes {pattern,
notes[], channel}`, `add_clip {pattern, track, position, length}`, `delete_clip`, `set_tempo {bpm}`.

Conventions: ids are the entities' stable uids (64-bit, fit in a JSON number); positions/lengths in ticks (ppq 960);
note velocity and pan 0–128 on the wire (64 = centre), like Lemon; built-in instruments `synth kick snare hat clap
sampler`, anything else is looked up by plugin name (VST3 preferred).

## Phase 1 — the MCP server (≈ 1–2 h)

New repo `~/develop/LynxShareMCP`, forked from `~/develop/LemonStudioMCP` (Python, `mcp>=2.3`, hatchling, MIT for the MCP
code; the app itself is AGPL-3.0).

1. **Scaffold.** Copy `pyproject.toml`, `src/lemon_studio_mcp/{__init__,__main__,client,server}.py`, `tests/`, `install.sh`.
   Rename package `lynx_share_mcp`, script `lynx-share-mcp`, create `.venv`.
2. **Client (`client.py`).** Socket default `/tmp/lynx.sock`; env `LYNX_SOCKET`; `LynxError`; messages name LYNX and
   `lynx_launch`. No TCP/token (the app has none). Keep reconnect-once and the lock.
3. **Launch tools.**
   - `lynx_launch(project=None)`: runs `LYNX_BIN` (default
     `~/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX`) with `[project] --control <socket>` (**project first**: LYNX only opens `args[0]` when it is an absolute path),
     detached (`start_new_session=True`, output to a log file) so it survives the MCP process; waits up to 20 s for the
     socket; no-op if already listening.
   - `lynx_status()`: hello + transport, or "not running".
4. **Tools kept from Lemon (re-pointed).** `get_project_state`, `get_notes`, `write_notes`, `clear_notes`, `add_channel`
   (takes `instrument` = built-in or plugin name), `set_channel`, `delete_channel`, `add_pattern`, `delete_pattern`,
   `place_pattern`, `delete_clip`, `set_tempo`, `play`, `pause`, `stop`, `transport_status`, `select`, `undo`, `redo`,
   `get_history`, `save_project`, `apply_commands`. Keep the beats ↔ ticks `unit` parameter.
5. **New tools.** `list_plugins` (from `plugins`), `set_synth` (built-in synth sound).
6. **Dropped for now** (no socket support yet; listed in Phase 2): `get_plugin_params`, `set_plugin_param`, `get_changes`,
   `load_sample`, `set_pattern`, `set_clip`, `add_mixer_track`, `set_mixer_track`, `route_mixer`, `set_eq`, `add_effect`,
   `set_effect`, `remove_effect`, `set_time_signature`, `set_project_settings`, `propose_commands`, `render_project`.
7. **Server instructions** (what Claude reads): ids and ticks; a channel needs an instrument to sound; one channel per
   pattern is a good layout; `select(..., piano_roll=True)` after writing notes; **chords with no bass under them need the
   root as the lowest note**; check bass notes against the chord in the same bar; don't save after every edit (save only
   when asked).
8. **Register** in `~/.claude.json` next to `lemon-studio`:
   ```json
   "lynx-share": {
     "type": "stdio",
     "command": "/Users/calvinw/develop/LynxShareMCP/.venv/bin/python",
     "args": ["-m", "lynx_share_mcp"],
     "env": { "LYNX_BIN": "/Users/calvinw/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX" }
   }
   ```
9. **Test.** Port `tests/test_end_to_end.py`: launch the app, build channels + a pattern + a clip, check notes round-trip,
   a failing `apply` changes nothing, play advances the position, 3× undo restores the song, `list_plugins` finds Serum 2.
   Then a real session: rebuild a small beat using only MCP tools.

**Done when:** a fresh Claude Code session can launch LYNX, load Serum 2, write a 4-bar beat and play it using only
`lynx-share` tools.

## Phase 2 — more of the app over the socket (C++, in priority order)

Each item is a new `apply` op or method in `ControlServer.cpp` plus its MCP tool.

1. **Plugin parameters and editor** — `params {channel | track+slot}` and `set_param`; `open_editor {channel}`
   (the window you'd get from clicking the channel). Needed to shape Serum without clicking.
2. **Plugin presets** — load a Serum `.SerumPreset` / VST3 preset into a channel (`PluginRef::state` or the plugin's
   preset API; see `src/ui/PluginPresetMenu.cpp`).
3. **Mixer and effects** — `set_track` (volume, pan, mute, name), `add_effect` / `set_effect` / `remove_effect` (built-in
   effects and plugins such as Serum 2 FX; `Song::mixer[t].effects`), routing (`Song::setRoute`).
4. **Pattern and clip edits** — `set_pattern` (name, colour, length), `set_clip` (move, resize, mute), `load_sample`.
5. **Render** — `render_project` via the headless CLI: `LYNX --export project.lynx out.wav`.
6. **Change events** — a `changes` method (or pushed notifications) so the MCP sees edits made in the window
   (`AudioEngine` is a `ChangeBroadcaster`; diff by `getSongStamp()`).
7. **Small fixes found in the spike** — `play` reports the position from before its `from` seek (the audio thread
   applies the seek a block later); `set_synth` exists in the build but has only been compiled, not exercised.
8. **Windows** — the socket is POSIX-only; use a named pipe or a localhost TCP port with a token (as Lemon does).

## Phase 3 — upkeep and upstream

- **Commit** the spike on `control-socket` (Co-Authored-By trailer) and keep it rebased: upstream ships alpha releases
  often (v0.1.23 on 2026-11-03), so rebase weekly; the change touches only 4 existing files.
- **Ask upstream** (github.com/Ka1-S/LYNX-SHARE): open an issue proposing a `--control` socket for local automation,
  linking a branch. If it's accepted there is no fork to maintain; if not, the fork stays small.
- **License**: the app is AGPL-3.0 — the fork's changes must stay open source if shared. The MCP server is a separate
  program talking over a socket, so it can stay MIT.

## Risks and open questions

- **Alpha app**: APIs inside LYNX (`editSong`, `Song` fields) may change between releases and break the C++ side.
- **Shared-copy edits**: `apply` replaces the whole Song with the edited copy. Fine for a single user; if Online Sessions
  are live at the same time it should go through the session's proposal path instead.
- **Undo merging**: `editSong` merges edits made while a mouse button is held, so an MCP edit during a drag joins that
  drag's undo step.
- **Launch lifetime**: an app started from inside a Claude session can close when the session ends — `lynx_launch` must
  detach it.
- **Open question**: separate repo (this plan) or a `--lynx` mode inside LemonStudioMCP? Separate is simpler while the
  two apps' tool sets differ; revisit if they converge.
