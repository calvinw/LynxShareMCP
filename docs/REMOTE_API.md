# How lynx-share-mcp uses LYNX SHARE's Remote Control API

LYNX SHARE's own reference is
[docs/REMOTE_CONTROL.md](https://github.com/Ka1-S/LYNX-SHARE/blob/main/docs/REMOTE_CONTROL.md) (`lynx-control/1`).
This page covers how this server uses it, and what we learned driving real projects through it.

## Connection

- **Turning it on.** Remote Control is off by default. Turn on **Settings › General › Remote control**, or start
  LYNX SHARE with `LYNX_CONTROL_ENABLED=1`, which is what `lynx_launch` does.
- **Discovery.** The app writes a private discovery record, `control/connection.json`, in its settings folder. The
  record holds a loopback port and a 64-hex-digit token. The server reads it from `$LYNX_CONTROL_DISCOVERY`, then
  `$LYNX_PROFILE_DIR/LYNX/control/connection.json`, then the platform default. It accepts the record only if it is a
  regular file (not a symlink), owned by this user, and not readable by group or others. It also checks that the
  record's `pid` is still running.
- **One request per connection.** Each request opens a new TCP connection and does the mutual HMAC-SHA-256
  handshake. It then sends one `{"op", "args"}` line and reads one result line, and the server closes the
  connection.
- **The token stays private.** It is never logged, passed on a command line, or shown to the model.

Code: [`src/lynx_share_mcp/remote.py`](../src/lynx_share_mcp/remote.py).

## Edits are guarded

- **Every edit carries the guard.** Each edit sends `expectedProjectId`, `expectedEpoch` and `expectedRevision`. A
  tool reads `session.inspect`, works out indices from it (channels and patterns are named by id, name or index),
  then sends the edit guarded by that same read. If the user changed the project in the window in between, LYNX
  refuses the edit with code `changed`, so nothing lands in the wrong place.
- **Lost answers are not retried.** If the answer to an edit is lost, the server reports the outcome as unknown
  (`uncertain`). The model must read the project again before doing anything else.
- **Stop before editing.** Stock LYNX refuses every edit while playing, including volume and mute, and
  `project.read` also needs playback stopped.

## Tools and the operations behind them

| Tool | Operations |
|---|---|
| `lynx_status`, `transport_status` | `status` |
| `get_project_state` | `session.inspect`, `playlist.inspect` |
| `get_notes` | `pattern.notes` (paged, 256 at a time) |
| `list_instruments` | `instrument.catalog` |
| `write_notes`, `clear_notes` | `pattern.notes`, then `pattern.replace_notes` with the whole pattern; every note needs all 19 fields, and the server fills in LYNX's defaults |
| `add_channel` | `instrument.catalog` (prefers VST3, then CLAP, then AU), `channel.create` |
| `set_channel` | `channel.set` (volume, pan, mute); `project.edit` for the name and mixer track |
| `delete_channel`, `delete_pattern` | `project.read` + `project.edit`, renumbering note channels and clip patterns/channels in the same transaction; refused for projects with automations, extra arrangements or grooves |
| `plugin_params` | `plugin.inspect` (paged) |
| `set_plugin_params` | `plugin.inspect`, `plugin.parameters_set` (each entry needs `expectedValue`) |
| `add_pattern`, `rename_pattern` | `pattern.create`, `pattern.set` |
| `place_pattern`, `delete_clip` | `playlist.edit` |
| `set_tempo`, `set_mixer_track` | `tempo.set`, `mixer.set` |
| `play`, `stop`, `pause` | `transport.play`, `transport.stop`, `transport.pause`* |
| `select` | `ui.select`*; on a stock build, `project.edit` of `/currentPattern` and `/mode` (an undo step) |
| `save_project`, `new_project` | `project.save`*, `project.new`* |
| `undo`, `redo` | `history.undo`, `history.redo` |
| `remote_call` | any operation; edits get a fresh guard. `project.read` and `project.edit` are not exposed raw |

\* These operations are not in stock LYNX SHARE. They are on the `remote-api-ui` branch of
[calvinw/LYNX-SHARE](https://github.com/calvinw/LYNX-SHARE/tree/remote-api-ui), documented in that branch's
`docs/REMOTE_CONTROL.md`. The server checks `api.describe` each time and, when they are missing, the tool says it
is unavailable.

## Plugin parameters (Serum 2)

- **Size.** `plugin.inspect` pages at most 256 parameters. Serum 2 exposes 2,622, and 2,048 of those are per-MIDI-CC
  mappings named `CCn ...`. `plugin_params` hides them unless `include_midi_cc` is set.
- **Values.** Values are normalized 0..1. `displayValue` and `label` give the meaning, e.g. `407 Hz`, `MG Low 12`,
  `On`, `1.00 s`.
- **Menus and switches must land exactly on a step.** Otherwise LYNX refuses the change with "Plugin state did not
  retain staged parameter changes". The VST3 reports `numSteps` (Filter 1 Type has 107). The AU reports every
  parameter as continuous, but the same grid works. `set_plugin_params` snaps to `numSteps`, and `add_channel`
  prefers the VST3.
- **AU and VST3 number their parameters differently** (off by one). Always look parameters up by name.
- **Presets rename the macros.** Serum 2's Macro 1–8 are the eight parameters after `Mod 64 Out`, but a preset
  replaces their names with its own labels (e.g. `LPF CUTOFF`, `HPF CUTOFF`, `REVERB`), so a search for "macro"
  can find nothing.
- **Serum 2's time and frequency scales**, measured:
  - Envelope times: about `32 s × value^5`, so 0.5 is 1.00 s.
  - Filter frequency: about `8 Hz × 2756^value`, so 0.5 is about 425 Hz.
- **Not visible through the API:** the modulation matrix (sources and destinations), wavetables and FX routing. A
  parameter's base value may not be what you hear when the preset modulates it.

## Known gaps

**Stock API:**
- Editing while playing.
- The built-in Synth's sound: `plugin.inspect` refuses native instruments.
- Loading samples.
- The undo history list.
- Several different edits as one undo step: only `project.edit` and `playlist.edit` batch.
- Setting a plugin parameter from text such as "800 Hz".

**This server:**
- `plugin_params` matches search words as substrings: "filter 1" also matches `Filter 2>BUS1`.
- Serum 2's renamed macros are not tagged "Macro N".
