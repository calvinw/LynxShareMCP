# Changelog

## Unreleased

## 0.2.1 (2026-11-26)

- Fix: `write_notes` works with LYNX SHARE 0.1.30 and later, which require every note's `expression` (MPE
  curves). It is sent only to a LYNX that wants it, so 0.1.28 and 0.1.29 keep working.
- Docs: `docs/AGENT_SETUP.md`, step-by-step setup instructions for an AI agent (official LYNX SHARE release +
  this server), linked from the README.
- Docs: the README describes the official LYNX SHARE release only; the optional source build no longer points
  at a fork.

## 0.2.0 (2026-11-17)

Moves to LYNX SHARE's official Remote Control API (`lynx-control/1`, LYNX SHARE 0.1.28 and later). The
`control-socket` fork is no longer needed.

- New: `plugin_params` and `set_plugin_params` for plugin sounds such as Serum 2: search parameters by name, set
  several as one undo step, and snap menu values to their steps.
- New: `set_mixer_track`, `list_instruments` (built-ins and scanned plugins), `new_project`, and `remote_call`, which
  can run any API operation.
- Channels and patterns can be named by id, exact name or index.
- Edits are guarded by the project revision, so an edit planned before a change in the window is refused instead of
  applied in the wrong place.
- `save_project`, `new_project`, `pause`, `play(from_position=...)` and `select(channel, piano_roll)` need the
  `remote-api-ui` additions; on a stock build they say they are unavailable.
- Removed: `set_synth` (the API cannot reach the built-in Synth), `get_history`, `apply_commands`, `list_plugins`
  (now `list_instruments`), sample channels. Velocity is now 0..1 and note pan -1..1, as in the API.
- Works with an official LYNX SHARE release: `install.sh` also finds `/Applications/LYNX.app`, and the README installs
  from the release instead of building.
- End-to-end tests run in a throwaway LYNX profile.

## 0.1.0 (2026-11-14)

First release, for the `control-socket` branch of calvinw/LYNX-SHARE.
