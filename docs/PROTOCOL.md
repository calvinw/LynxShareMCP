# LYNX SHARE control socket protocol

What `lynx-share-mcp` talks to. The socket is added to LYNX SHARE by the `control-socket` branch of
[calvinw/LYNX-SHARE](https://github.com/calvinw/LYNX-SHARE) (`src/engine/ControlServer.{h,cpp}`); official LYNX SHARE
releases do not have it.

## Transport

- Start the app with `LYNX [/abs/path/project.lynx] --control /tmp/lynx.sock`. The project must be the **first**
  argument and an absolute path; after `--control` it is ignored and the demo song loads.
- A Unix domain socket (mode 0600, so only your user can connect), one client at a time. macOS and Linux only.
- Newline-delimited JSON-RPC 2.0: one request per line, one response per line.
- Requests run on the app's message thread. Every `apply` is one undo step (`AudioEngine::editSong`), so it shows in
  the app's History and undoes with Cmd/Ctrl+Z. `apply` is all or nothing: the ops run on a copy of the song, which
  replaces the live one only if every op succeeds.

## Methods

| Method | Params | Returns |
|---|---|---|
| `hello` | – | `{app, protocol, ppq}` |
| `state` | – | ppq, bpm, beats_per_bar, mode, current_pattern, selected_channel, channels[], patterns[], clips[], mixer[] |
| `notes` | `pattern` | `{pattern, notes[]}` |
| `plugins` | – | scanned VST3/AU/CLAP plugins: `{name, manufacturer, format, instrument, id}` |
| `apply` | `commands[]`, `name` | `{results[]}`: one undo step, all or nothing |
| `play` | `mode` (`song`/`pattern`), `pattern`, `from` (ticks) | transport |
| `pause`, `stop`, `transport` | – | transport `{playing, position, mode, bpm, ppq}` |
| `select` | `pattern`, `channel`, `piano_roll` | state |
| `undo`, `redo` | – | `{position}` |
| `history` | – | `{steps[], position}` |
| `save` | `path` (required) | `{path}` |

## `apply` ops

Each command is an object with `op` plus its fields:

| Op | Fields |
|---|---|
| `add_channel` | `name`, `instrument` (built-in) or `plugin` (name), `sample`, `track` |
| `set_channel` | `channel`, `name`, `volume`, `pan`, `muted`, `track` |
| `delete_channel` | `channel` |
| `set_synth` | `channel`, `osc[]`, `attack`, `decay`, `sustain`, `release`, `cutoff`, `resonance`, `filter_type`, `ladder`, `mono`, `porta`, `chorus`, `filter_env{}` |
| `add_pattern` | `name` |
| `set_pattern` | `pattern`, `name` |
| `delete_pattern` | `pattern` |
| `set_notes`, `add_notes` | `pattern`, `notes[]`, `channel` (`set_notes` first clears that channel's notes in the pattern, or all its notes when no `channel` is given) |
| `add_clip` | `pattern`, `track`, `position`, `length` |
| `delete_clip` | `clip` |
| `set_tempo` | `bpm` |

## Conventions

- Ids are the items' stable 64-bit uids (they fit in a JSON number) and do not change when other items are added or
  deleted. Playlist tracks are 0-based indexes; mixer tracks are indexes with 0 = master.
- Positions and lengths are in ticks (`ppq` from `hello`, 960 today). The MCP converts to beats by default.
- Note velocity and pan are 0–128 on the wire (64 = centre).
- Built-in instruments: `synth`, `kick`, `snare`, `hat`, `clap`, `sampler`. Any other instrument name is looked up
  among the scanned plugins, preferring VST3.

## Known issues

- `apply` returns `id: 0` for items it adds when the same batch also deletes channels or patterns.
- History labels come from the app (a batch shows as e.g. "Add pattern"); the `name` param is ignored.
- `play` with `from` reports the position from before the seek; read `transport` a moment later.
- An edit made while a mouse button is held in the window merges into that drag's undo step.

## Not yet available

Plugin parameters and editors, plugin presets, mixer effects and routing, clip moves and resizes, sample loading,
rendering, a feed of changes made in the window, and Windows support (the socket is POSIX-only).
