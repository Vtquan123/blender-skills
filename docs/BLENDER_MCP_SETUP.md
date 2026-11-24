# Blender MCP Setup Guide

Connect a Blender MCP server to Claude Desktop, Claude Code, Cursor, Kiro or Codex so the Blender Skills Pack can execute operations directly in Blender.

Two servers work with this pack:

| | Official Blender MCP (recommended) | Community `blender-mcp` (ahujasid) |
|--|--|--|
| Maintainer | Blender Lab | Community |
| Blender | 5.1+ | 3.0+ |
| Blender side | Extension add-on **MCP** (`lab_blender_org.mcp`), auto-starts its socket server | `addon.py`, start with **Connect to Claude** |
| Socket | `localhost:9876` | `localhost:9876` |
| Extras | Background mode (`*_for_cli`), bundled API/manual search | Poly Haven, Sketchfab, Hyper3D, Hunyuan3D |
| Tool names | `get_objects_summary`, `get_screenshot_of_area_as_image`, … | `get_scene_info`, `get_viewport_screenshot`, … |

Both use port 9876 — **enable only one Blender add-on server at a time.** Skills use official tool names; the mapping is in `.claude/skills/references/mcp-tools.md`.

## Option A — Official Blender MCP Server

### 1. Blender add-on

1. Use Blender **5.1 or newer**.
2. Install the **MCP** add-on from the Blender Lab page: <https://www.blender.org/lab/mcp-server/> (it installs through Blender's extension system).
3. **Edit → Preferences → System → Network → enable Online Access.** The add-on refuses to start its socket server without it (it shows "Online access must be enabled in the system preferences").
4. The server auto-starts about a second after the add-on registers and listens on `localhost:9876`.

### 2. MCP client

Configure your client as described on the Blender Lab page (the client-side MCP server process is separate from the add-on). Recommended additions:

- Name the server `Blender`.
- Set `BLENDER_PATH` in the server's environment so background tools (`execute_blender_code_for_cli`, `get_blendfile_summary_*_for_cli`) can launch Blender:
  - macOS: `/Applications/Blender.app/Contents/MacOS/Blender`
  - Windows: `C:\Program Files\Blender Foundation\Blender 5.x\blender.exe`
  - Linux: path of the `blender` executable
- Restart the client after editing its config.

### 3. Background mode (optional)

The add-on can also serve MCP requests from a headless Blender:

```bash
blender --background file.blend --command blender_mcp --host localhost --port 9876
```

Deferred responses are not supported in background mode; every request must complete before returning.

## Option B — Community `blender-mcp` (ahujasid)

Use on Blender versions older than 5.1 or when you need Poly Haven / Sketchfab / Hyper3D / Hunyuan3D.

1. Install `uv` (<https://docs.astral.sh/uv/getting-started/installation/>). GUI clients do not inherit your shell `PATH`; use the absolute path to `uvx` if you see `spawn uvx ENOENT`.
2. In Blender install [`addon.py`](https://github.com/ahujasid/blender-mcp/raw/main/addon.py) (**Edit → Preferences → Add-ons → Install…**), enable **Interface: Blender MCP**.
3. 3D View sidebar (**N**) → **BlenderMCP** → **Connect to Claude**.
4. Client config:

macOS / Linux:

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": ["--python", "3.11", "blender-mcp"],
      "env": { "BLENDER_HOST": "localhost", "BLENDER_PORT": "9876", "DISABLE_TELEMETRY": "true" }
    }
  }
}
```

Windows:

```json
{
  "mcpServers": {
    "blender": {
      "command": "cmd",
      "args": ["/c", "uvx", "--python", "3.11", "blender-mcp"],
      "env": { "BLENDER_HOST": "localhost", "BLENDER_PORT": "9876", "DISABLE_TELEMETRY": "true" }
    }
  }
}
```

Claude Code CLI: `claude mcp add blender -- uvx --python 3.11 blender-mcp` (Windows: `claude mcp add blender -- cmd /c uvx --python 3.11 blender-mcp`).

`.cursor/mcp.json` in this repo contains the Windows variant for Cursor. The Claude Code plugin no longer ships an `.mcp.json`: configure the server you use in your client instead (the old bundled config only worked on Windows and collided with the official add-on's port).

| Variable | Default | Purpose |
|----------|---------|---------|
| `BLENDER_HOST` | `localhost` | Blender socket host |
| `BLENDER_PORT` | `9876` | Blender socket port |
| `DISABLE_TELEMETRY` | unset | `true` disables telemetry |
| `BLENDERMCP_SKETCHFAB_API_KEY` | — | Sketchfab downloads |
| `BLENDERMCP_HYPER3D_API_KEY` | — | Hyper3D generation |

## Verify the Connection

1. Ask: *"List the objects in the current Blender scene."* — the agent should call `get_objects_summary` (official) or `get_scene_info` (community).
2. Ask for a viewport screenshot.
3. For Production Mode, run the capability probe described in `docs/BLENDER_MCP_CAPABILITIES.md`.

## Optional Extension — AutoRemesher

Production Mode can build quad bases with [AutoRemesher for Blender](https://github.com/jakeblakeley/autoremesher-blender) instead of QuadriFlow (`deform_mesh.py remesher: autoremesher | auto`, spec `geometry.remesher`). Nothing else needs it.

1. Download the zip for your platform from the [releases page](https://github.com/jakeblakeley/autoremesher-blender/releases):
   - Blender **5.1+** → `autoremesher-<version>-<platform>.zip` (`macos_arm64`, `macos_x64`, `windows_x64`, `linux_x64`)
   - Blender **4.2 LTS–5.0** → `autoremesher-<version>-blender42-<platform>.zip`
2. **Edit → Preferences → Get Extensions → ▾ (top right) → Install from Disk…** → pick the zip. Keep it enabled.
3. Check from the agent: run `production/scripts/blender/autoremesh.py` with `{"mode": "probe"}` — `available: true` and a `core_dir`.

The skills only call the extension's compiled core (`autoremesher_core`, MIT) in a separate process; its add-on code (GPL-3.0) is not part of this pack. The extension's author reports testing on macOS Apple Silicon only so far — on other platforms, use `remesher: auto` so a failure falls back to QuadriFlow.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Cannot connect to Blender at `localhost:9876` | Blender not running, add-on disabled, or (official) Online Access off |
| `autoremesh.py` probe `available: false` | Extension not installed, or the zip does not match the Blender version (5.1+ vs `-blender42-`); reinstall the right zip |
| Two add-ons fighting over 9876 | Disable one of them |
| "Blender executable not found" on `*_for_cli` | Set `BLENDER_PATH` for the MCP server process |
| `result` must be a dict (official) | Return `result = {...}` from `execute_blender_code` |
| `spawn uvx ENOENT` (community) | Absolute path to `uvx` in the client config |
| First command times out | Retry; split heavy work into smaller calls |

## Security Note

`execute_blender_code` runs arbitrary Python in Blender with your user's permissions. **Save your `.blend` file before agent sessions.** Production Mode works in temporary scenes and never writes to a project's `input/` folder.

## Skills Integration

- `.claude/skills/references/mcp-integration.md` — agent protocol
- `.claude/skills/references/mcp-tools.md` — tool catalog and server mapping
- `docs/BLENDER_MCP_CAPABILITIES.md` — verified capability map

## Links

- [Blender Lab — MCP Server](https://www.blender.org/lab/mcp-server/)
- [Official MCP server source](https://projects.blender.org/lab/blender_mcp)
- [Community blender-mcp](https://github.com/ahujasid/blender-mcp)
- [uv installation](https://docs.astral.sh/uv/getting-started/installation/)
