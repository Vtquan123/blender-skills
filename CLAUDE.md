# Blender Skills Project

Blender Skills Pack for Cursor and Claude Code with Blender MCP integration.

## Project Structure

```
.claude-plugin/          # plugin.json + marketplace.json
.claude/skills/          # 94 specialist skills + shared references
.cursor/mcp.json         # Blender MCP (Cursor)
docs/BLENDER_MCP_SETUP.md
```

## Agent Instructions

1. For Blender asset tasks, read **blender-director** first for complex work
2. **If user attaches a reference image:** read `references/reference-image-match.md` and complete Reference Analysis before MCP execution
3. **Check Blender MCP** — if connected, execute via MCP; never narrate UI steps
4. Read MCP tool schemas before calling (see `references/mcp-tools.md`; official Blender MCP tool names, community mapping)
5. Follow universal pipeline in `references/asset-pipeline.md`
6. Validate before export using `references/validation-checklist.md`
7. For reference tasks, also run `references/visual-match-checklist.md`
8. Use naming conventions from `references/naming-conventions.md`
9. **Existing model + output spec:** use blender-director Production Mode (`blender-director/references/production-mode.md`); scripts live in `production/`

## MCP Setup

Blender must be running with a Blender MCP add-on server on `localhost:9876` — the official Blender Lab **MCP** add-on (Blender 5.1+, Online Access enabled) or the community `blender-mcp` add-on. See `docs/BLENDER_MCP_SETUP.md` and the verified capability map in `docs/BLENDER_MCP_CAPABILITIES.md`.

## Key Files

- `QUICKSTART.md` — Installation
- `SKILLS_GUIDE.md` — Decision trees and workflows
- `README.md` — Overview
