# Quick Start

Get the Blender Skills Pack running in Cursor or Claude Code with Blender MCP.

## 1. Install Skills

### Claude Code (Plugin — Recommended)

From your project or globally:

```bash
/plugin marketplace add arjun988/blender-skills
/plugin install blender-skills@blender-skills
```

The part after `@` is the marketplace name from `.claude-plugin/marketplace.json` (`blender-skills`). To use a fork or a local clone, add that instead: `/plugin marketplace add <owner>/<repo>` or `/plugin marketplace add /path/to/blender-skills`. If an older version of the plugin is already installed, run `/plugin update blender-skills@blender-skills` (or uninstall and install again) so the new skills (`asset-intake`, `deformation-prep`, `web-export`) load.

Check the pack before installing: `python3 scripts/check_skills.py` (frontmatter, references, `.cursor` mirror).

### Claude Code (Manual)

Skills are at `.claude/skills/`. Copy to your project:

```bash
cp -r .claude/skills /path/to/your/project/.claude/skills/
```

### Cursor

Copy skills to Cursor's project skills folder:

```bash
# From repo root
bash scripts/sync-skills.sh          # macOS / Linux
pwsh scripts/sync-skills.ps1         # Windows
```

Or symlink if you prefer a single source of truth.

## 2. Connect Blender MCP

Full guide: [docs/BLENDER_MCP_SETUP.md](docs/BLENDER_MCP_SETUP.md)

**Quick version (official Blender Lab MCP add-on, recommended):**

1. Blender 5.1+ → install the **MCP** extension (Blender Lab) → Preferences → System → enable **Online Access** (the server will not start without it); it listens on `localhost:9876`
2. Register the MCP server in your client (Claude Desktop / Claude Code / Cursor) as described in the setup guide; set `BLENDER_PATH` if you want the background `*_for_cli` tools
3. Restart the client and test: *"List objects in the current Blender scene"*

**Community alternative:** [`blender-mcp`](https://github.com/ahujasid/blender-mcp) (uv + addon.py, sidebar → BlenderMCP → Connect). Same port — run only one of the two.

## 3. First Prompt

Start complex tasks with the director skill:

```
Plan and create a game-ready sci-fi crate for Unity — 1500 tris, realistic PBR, export to FBX
```

The agent should:
1. Activate **blender-director** → output production brief
2. Route to **hard-surface** + **realistic-style**
3. Execute via Blender MCP (not UI walkthroughs)
4. Validate with **asset-optimization** → **export-pipeline**

## 3b. Existing Model → Web (Production Mode)

```bash
cd production && npm install && npx playwright install chromium   # Node tools, once
python3 production/scripts/project_init.py --workspace ~/3d-production --name my_cat \
    --source /path/to/model.glb --preset web-desktop --category cat
```

Then ask: *"Run Production Mode on projects/my_cat"*. The director measures the asset (G0), asks for missing spec values and approval of the plan (G1), and stops at the approval gates in `output-spec.yaml → acceptance.approve_at`. Animation without a source: you will be asked for a video/GIF or a description. Optional: KTX-Software `ktx` CLI for KTX2 textures (otherwise set `compression.textures: webp`).

## 4. Skill Routing Cheat Sheet

| Task | Skills |
|------|--------|
| Any new asset | blender-director |
| Sci-fi prop / weapon | hard-surface |
| Modular environment | environment-artist + geometry-nodes |
| Character | character-artist → retopology → rigging |
| Horror scene | horror-style + lighting + lowpoly-style |
| Export to engine | asset-optimization → export-pipeline |
| Existing model → animated web GLB | blender-director (Production Mode) → asset-intake → deformation-prep → web-export |

Full decision trees: [SKILLS_GUIDE.md](SKILLS_GUIDE.md)

## 5. Verify Setup

- [ ] Skills visible in agent context (try mentioning "blender-director")
- [ ] Blender MCP connected (official add-on running / community add-on "Connected")
- [ ] Test: *"List objects in the current Blender scene"*
- [ ] Collections use `COL_` prefix, meshes use `SM_` prefix

## Documentation

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Overview |
| [SKILLS_GUIDE.md](SKILLS_GUIDE.md) | Skill index and workflows |
| [CLAUDE.md](CLAUDE.md) | Project instructions for agents |
| [docs/BLENDER_MCP_SETUP.md](docs/BLENDER_MCP_SETUP.md) | MCP connection guide |
| [docs/PRODUCTION_MODE.md](docs/PRODUCTION_MODE.md) | Existing model → web GLB with animation |

## Troubleshooting

**Skills not activating:** Ensure skills are in `.cursor/skills/` (Cursor) or `.claude/skills/` (Claude Code).

**MCP not connecting:** See [docs/BLENDER_MCP_SETUP.md](docs/BLENDER_MCP_SETUP.md) — usually Online Access is off (official add-on), uv not on PATH (community add-on), or both add-ons are fighting over port 9876.

**Agent describes UI instead of executing:** Remind it: *"Use Blender MCP tools"* — skills enforce MCP-first in `.claude/skills/references/mcp-integration.md`.
