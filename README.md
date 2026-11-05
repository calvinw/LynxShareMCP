# lynx-share-mcp

An MCP server that lets Claude drive [LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE), the open-source FL Studio-style
DAW, while it runs: read the project, add channels (built-in instruments or plugins such as Serum 2), write notes,
build patterns and the playlist, play, undo and save.

It talks to the app over a local Unix socket (`--control /tmp/lynx.sock`), which is **not in upstream LYNX SHARE yet**:
build the `control-socket` branch of `~/develop/LYNX-SHARE` (`cmake --build build --target LYNX`).

## Install

```sh
./install.sh [path/to/LYNX]   # creates .venv and registers `lynx-share` with Claude Code (user scope)
```

Then ask Claude to call `lynx_launch` (optionally with a `.lynx` project), or start the app yourself — the project
must come first:

```sh
LYNX /abs/path/song.lynx --control /tmp/lynx.sock
```

Environment: `LYNX_SOCKET` (default `/tmp/lynx.sock`), `LYNX_BIN` (the app binary for `lynx_launch`).

## Tools

`lynx_launch`, `lynx_status`, `get_project_state`, `get_notes`, `list_plugins`, `get_history`, `write_notes`,
`clear_notes`, `add_channel`, `set_channel`, `set_synth`, `delete_channel`, `add_pattern`, `delete_pattern`,
`place_pattern`, `delete_clip`, `set_tempo`, `play`, `pause`, `stop`, `transport_status`, `select`, `undo`, `redo`,
`save_project`, `apply_commands`.

Positions are in beats by default (`unit="ticks"` for raw ticks). Every edit is one undo step in the app.
See `PLAN.md` for the socket protocol and what comes next.

## Test

```sh
LYNX_BIN=~/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX .venv/bin/pytest -v
```

The test opens a LYNX window on a temporary socket and closes it at the end.

## License

MIT (this server). LYNX SHARE itself is AGPL-3.0.
