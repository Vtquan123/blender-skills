![Blender Skills](assets/Blender.png)

<div align="center">

# Blender Skills

**97 Specialized Skills for Blender Artists.**
**Transform Cursor, Claude Code, Kiro, and Codex into your Senior Technical Art team — not a tutorial bot.**

[![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)](version.json)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Skills](https://img.shields.io/badge/skills-97-orange.svg)](.claude/skills/)
[![Blender MCP](https://img.shields.io/badge/Blender_MCP-integrated-blueviolet.svg)](docs/BLENDER_MCP_SETUP.md)
[![Cursor](https://img.shields.io/badge/Cursor-skills-blue.svg)](https://cursor.com)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-black.svg)](https://docs.anthropic.com/en/docs/claude-code)
[![Kiro](https://img.shields.io/badge/Kiro-compatible-purple.svg)](https://kiro.dev)
[![Codex](https://img.shields.io/badge/Codex-compatible-green.svg)](https://openai.com/codex)
[![Website](https://img.shields.io/badge/website-blender--skills.vercel.app-orange.svg)](https://blender-skills.vercel.app/)

</div>

---

## Quick Start

> **Marketplace listing is currently under review by Anthropic.**
> Install directly from GitHub in the meantime.

Works with **Cursor**, **Claude Code**, **Kiro**, and **Codex** — same skill pack, Blender MCP execution.

**Claude Code**
```bash
git clone https://github.com/arjun988/blender-skills.git
cp -r blender-skills/.claude/skills /path/to/your/project/.claude/skills/
```

**Cursor (Windows)**
```powershell
git clone https://github.com/arjun988/blender-skills.git
Copy-Item -Recurse -Force "blender-skills\.claude\skills\*" ".cursor\skills\"
```

**Kiro**
```bash
# Copy skill folders into your Kiro skills directory, then restart Kiro
cp -r blender-skills/.claude/skills/* /path/to/kiro/skills/
```

**Codex**
```bash
# Mount or copy skills into your Codex skills path
cp -r blender-skills/.claude/skills/* /path/to/codex/skills/
# or: ln -s /path/to/blender-skills/.claude/skills /path/to/codex/skills/blender-skills
```

For all installation methods and first steps, see the **[Quick Start Guide](https://blender-skills.vercel.app/getting-started/)**.

**Full documentation:** [blender-skills.vercel.app](https://blender-skills.vercel.app/)

---

## Skills (97)

97 specialized skills across modeling, production, technical, pipeline, art styles, horror packs, worlds, moods, gameplay genre direction, and spec-driven production of existing assets (Production Mode).

See **[Skills Guide](SKILLS_GUIDE.md)** for the full list, subtype coverage map, decision trees, and workflow combinations.

### Usage Patterns

#### Orchestrated Execution

The **blender-director** skill analyzes your request and routes automatically:

```
# Hard Surface Asset
"Build a game-ready sci-fi rifle for Unreal Engine, 3k tris, realistic PBR"
→ blender-director → hard-surface → uv-workflow → materials → asset-optimization → export-pipeline

# Environment
"Create a modular horror corridor kit — narrow, flickering fluorescent, Silent Hill feel"
→ blender-director → horror-style → environment-artist → lighting → export-pipeline

# Character
"Retopologize this creature sculpt for game animation, 15k triangle budget"
→ blender-director → retopology → uv-workflow → texture-workflow → rigging
```

#### Existing Asset → Web (Production Mode)

Give an existing model and an output spec; the director plans the stages, runs repository scripts in Blender through MCP, and stops at gates for your approval:

```
"Turn input/calicocat_3d.glb into a web GLB for desktop with idle and walk"
→ blender-director (Production Mode) → asset-intake → deformation-prep (remesh, joint loops, Rigify, weights, ROM)
  → texture-workflow (bake from the source) → animation (motion generators, or your video/GIF as reference)
  → web-export (glTF-Transform, glTF-Validator, headless three.js check) → qa-review (report, gate G8)
```

Any model, not only the ones with a preset: the structure analysis measures parts, ground contacts, limbs or branches and wheels, proposes how the model moves (rolling ball, vehicle with wheels and steering, swaying plant, slithering body, skinned creature, hinged parts) and asks only what it cannot measure — the front, cutting fused wheels, a hinge, the clip list.

Details: [production-mode.md](.claude/skills/blender-director/references/production-mode.md) · [motion-analysis.md](.claude/skills/blender-director/references/motion-analysis.md) · toolkit in [`production/`](production/).

#### Reference Image Matching

Attach a photo or concept art and the agent matches it:

```
"Match this reference — industrial spaceship, analyze first then build in Blender"
→ blender-director → reference-image-match
  → Camera match → Geometry tiers → Materials → Lighting → Screenshot comparison loop
```

### Skill Categories

| Category | Skills |
|----------|--------|
| **Orchestration** | [blender-director](.claude/skills/blender-director/) |
| **Production Mode** | asset-intake, deformation-prep, web-export |
| **Modeling** | blender-modeler, hard-surface, prop-artist, vehicle-artist, environment-artist, vegetation-artist, character-artist, creature-artist, character-archetypes |
| **Production** | sculpting, retopology, uv-workflow, materials, texture-workflow, hair-groom, cloth-sim, lookdev |
| **Technical** | geometry-nodes, lighting, camera-cinematography, rendering, compositing, animation, rigging, vfx-fx, physics-sim |
| **Pipeline** | procedural-modeling, scene-assembly, set-dressing, asset-optimization, lod-pipeline, collision-proxy, export-pipeline, unity-export, unreal-export, godot-export, qa-review, archviz |
| **Core styles** | horror-style, psx-horror-style, lowpoly-style, anime-style, voxel-style, isometric-style, stylized-style, realistic-style |
| **Extended styles** | cartoon, comic-book, manga, pixel-art, hand-painted, painterly, stop-motion-craft, chibi, noir, minimalist, vector, retro-8bit, retro-16bit, hd-2d, frutiger-aero |
| **Horror packs** | cosmic-eldritch, body-horror, analog-found-footage, liminal-space, folk-horror, mascot-puppet, dream-weirdcore, indie-horror-aesthetics |
| **Worlds / moods** | fantasy-worlds, sci-fi-punk-worlds, historical-worlds, apocalypse-worlds, biome-worlds, cozy-wholesome, dark-gritty, dream-surreal, neon-retrofuturism, brutalist |
| **Genre direction** | action-combat, shooter, rpg, survival, stealth, puzzle-platformer, metroidvania-roguelike, soulslike, strategy-sim, racing-sports, narrative-vn, card-party-idle, open-world-sandbox |
| **Eras** | visual-console-eras |

Full paths and workflows: **[SKILLS_GUIDE.md](SKILLS_GUIDE.md)**.

---

## Blender MCP

Every skill executes **directly in Blender** via MCP — no UI walkthroughs, no manual steps.

```
Blender (running, MCP add-on on localhost:9876) ← MCP server ← Cursor / Claude Code / Claude Desktop / Kiro / Codex
```

**Recommended:** the official Blender Lab **MCP** add-on (Blender 5.1+, *Online Access* enabled in Preferences → System; set `BLENDER_PATH` for the background `*_for_cli` tools).
**Alternative:** the community [`blender-mcp`](https://github.com/ahujasid/blender-mcp) add-on (sidebar `N` → BlenderMCP → Connect). Both use port 9876 — run one at a time.

Full guide: **[docs/BLENDER_MCP_SETUP.md](docs/BLENDER_MCP_SETUP.md)** · verified tool list: **[docs/BLENDER_MCP_CAPABILITIES.md](docs/BLENDER_MCP_CAPABILITIES.md)**

| Config / Path | Client |
|---------------|--------|
| `.cursor/mcp.json` + `.cursor/skills/` | Cursor |
| Your MCP client config (see setup guide) + `.claude/skills/` | Claude Code / Claude Desktop |
| Kiro skills dir + Blender MCP | Kiro |
| Codex skills path + Blender MCP | Codex |

The plugin no longer ships a root `.mcp.json` (it only worked on Windows and clashed with the official add-on); configure the server once in your client instead.

---

## Workflow Pipelines

### Hero Hard Surface Prop
```
blender-director → hard-surface → uv-workflow → materials → asset-optimization → export-pipeline
```

### Game Character
```
blender-director → character-artist → sculpting → retopology
→ uv-workflow → texture-workflow → rigging → animation → export-pipeline
```

### Horror Environment
```
blender-director → horror-style → environment-artist → lighting
→ lowpoly-style → asset-optimization → export-pipeline
```

### Modular Kit
```
blender-director → environment-artist → geometry-nodes
→ uv-workflow → texture-workflow → asset-optimization → export-pipeline
```

### Existing Model → Animated Web GLB (Production Mode)
```
blender-director → asset-intake → deformation-prep → texture-workflow
→ animation → web-export → qa-review
  gates G0–G8, checkpoints, state.json resume; specs in production/templates/
```

### Reference Image Match
```
blender-director → reference-image-match.md
  → Reference Analysis → Camera match → Geometry tiers
  → Materials → Lighting → Screenshot compare loop
  → visual-match-checklist → validation-checklist
```

---

## Philosophy

Every skill in this pack:

- **Thinks before acting** — Plans the full pipeline before touching Blender
- **Executes via MCP** — Uses Blender MCP tools when connected, never narrates UI steps
- **Matches references** — Analyzes photo first, camera-matches, screenshot-compares in a loop
- **Follows production standards** — Naming conventions, polycount budgets, game-ready output
- **Validates before export** — Asset optimization and checklist gate on every delivery

---

## Project Structure

```
.claude-plugin/           # Claude Code plugin manifest
.claude/skills/           # 97 skills + 188 reference files
  ├── blender-director/
  ├── hard-surface/
  ├── prop-artist/
  ├── genre-shooter/
  ├── sci-fi-punk-worlds/
  ├── asset-intake/ deformation-prep/ web-export/   # Production Mode
  ├── ... (89 more skills)
  └── references/         # Asset pipeline, naming, MCP tools, checklists
.cursor/skills/           # Synced mirror for Cursor
.cursor/mcp.json          # Blender MCP config (Cursor)
production/               # Production Mode toolkit: spec templates, presets, rigs,
                          # Blender scripts (run via MCP), Node web tools, gate runner
scripts/                  # check_skills.py (pack validator), sync-skills.sh/.ps1
site/                     # Website (blender-skills.vercel.app)
docs/
  ├── BLENDER_MCP_SETUP.md
  ├── BLENDER_MCP_CAPABILITIES.md
  ├── PRODUCTION_MODE.md
  └── local_skill_development.md
```

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [QUICKSTART.md](QUICKSTART.md) | Installation and first steps |
| [SKILLS_GUIDE.md](SKILLS_GUIDE.md) | Skill index, decision trees, workflows |
| [docs/BLENDER_MCP_SETUP.md](docs/BLENDER_MCP_SETUP.md) | Blender MCP connection guide |
| [docs/PRODUCTION_MODE.md](docs/PRODUCTION_MODE.md) | User guide: existing model → spec'd deliverable (setup, decisions, outputs, troubleshooting) |
| [docs/BLENDER_MCP_CAPABILITIES.md](docs/BLENDER_MCP_CAPABILITIES.md) | Verified MCP tools and operations |
| [production-mode.md](.claude/skills/blender-director/references/production-mode.md) | Spec-driven pipeline for existing assets (modes, gates, resume) |
| [production-spec.md](.claude/skills/references/production-spec.md) | input-spec / output-spec / plan / motion-brief schemas |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to add skills and contribute |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [.claude/skills/references/](.claude/skills/references/) | Shared pipeline standards |

---

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for guidelines on adding skills, writing references, and submitting pull requests.

---

## Changelog

See **[CHANGELOG.md](CHANGELOG.md)** for full version history and release notes.

---

## License

MIT License — See [LICENSE](LICENSE) for details.

---

## Star History

<a href="https://star-history.com/#arjun988/blender-skills&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=arjun988/blender-skills&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=arjun988/blender-skills&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=arjun988/blender-skills&type=Date" />
  </picture>
</a>

---

## Support

- **Website:** [blender-skills.vercel.app](https://blender-skills.vercel.app/)
- **Issues:** [GitHub Issues](https://github.com/arjun988/blender-skills/issues)
- **Discussions:** [GitHub Discussions](https://github.com/arjun988/blender-skills/discussions)
- **Repository:** [github.com/arjun988/blender-skills](https://github.com/arjun988/blender-skills)

---

<div align="center">

**Built for Cursor, Claude Code, Kiro & Codex** | **Blender MCP** | **97 Skills** | **188 Reference Files**

Inspired by [jeffallan/claude-skills](https://github.com/Jeffallan/claude-skills)

</div>
