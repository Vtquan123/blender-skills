# Changelog

All notable changes to the Blender Skills Pack.

Format: [Semantic Versioning](https://semver.org/) — `Major.Minor.Patch`

---

## [1.4.0] — 2026-11-20

### Added
- **Production Mode** in `blender-director`: spec-driven conversion of an existing model into a deliverable — modes ANALYZE / PLAN / PREVIEW / PRODUCTION / VALIDATE / EXPORT, gates G0–G8, checkpoints and `state.json` resume (`blender-director/references/production-mode.md`, `references/production-spec.md`)
- **New skills:** `asset-intake` (import + measure → input spec, G0), `deformation-prep` (joint analysis, deform mesh with joint loops, rigid parts, template fitting, weights, ROM test — G4a–G4c), `web-export` (glTF-Transform, glTF-Validator, headless three.js check — G6–G7)
- **Reference-driven motion:** ask for a video/GIF/description when a clip has no source, imitate it with parametric generators (`animation/references/reference-driven-motion.md`)
- **`production/` toolkit:** spec templates, web presets (mobile/desktop/hero), category presets (human, dog, cat, parrot, book, box, chair, table), bird metarig, Blender scripts run through MCP (`intake`, `rig_fit`, `deform_mesh`, `joint_analysis`, `mesh_metrics`, `bake_maps`, `skin_weights`, `rom_test`, `hinge_rig`, `anim_check`, `export_glb`, `sample_vertices`), motion generators + frame extraction, Node tools (`optimize`, `validate_gltf`, `runtime_check`), gate runner and `project_init`
- `production/scripts/blender/preview_render.py` — preview clips of a rigged asset in a separate scene (copies, ground, lights, follow camera, root motion, chunked rendering)
- `scripts/check_skills.py` (pack validator) and `scripts/sync-skills.sh` / `.ps1`
- `docs/PRODUCTION_MODE.md` — user guide (requirements, decisions, outputs, troubleshooting)
- `docs/BLENDER_MCP_CAPABILITIES.md` — MCP operations verified on Blender 5.3 plus an end-to-end run on a 1.9 M-triangle model

### Changed
- Skills and references use the **official Blender Lab MCP** tool names (`execute_blender_code`, `get_objects_summary`, `get_screenshot_of_area_as_image`, …) with a mapping for the community `blender-mcp` server; `docs/BLENDER_MCP_SETUP.md` rewritten for both
- `animation`, `rigging`, `retopology`, `texture-workflow`, `uv-workflow`, `qa-review`, `export-pipeline` extended for Production Mode (1.1.0)
- `bake_maps.py` picks the GPU automatically (Metal/CUDA/OptiX/HIP/oneAPI)
- Skill count **94 → 97**; references **175 → 188**

### Removed
- Plugin root `.mcp.json` (Windows-only `cmd /c uvx blender-mcp`, collided with the official add-on on port 9876); configure the MCP server in your client

### Fixed
- `dream-weirdcore-style` related skill `surreal-mood` → `dream-surreal-mood`
- QUICKSTART plugin install id (`blender-skills@blender-skills`)
- Walk on short legs (user report: crossing legs, twisted paws): new `quadruped_walk_fk` generator — planar two-bone IK on FK controls with body compensation; generators key `IK_FK` per clip (`ikfk`); `anim_check.py` takes `root_velocity` for in-place cycles; `export_glb.py` unhides objects so a hidden armature is not dropped
- Found by the end-to-end test and fixed in the scripts: Rigify rig displaced from the mesh (metarig location not applied), twisted control rolls after fitting, "disjoint chain" Rigify errors after moving joints, QuadriFlow refusing small assets, faceted normal bakes, B-Bones breaking Blender↔three.js parity, empty extra glTF scene, missing tangents, work actions exported as clips, ROM test not moving IK limbs, G4b passing collapsed weights, G2/G3 gate files never written

---

## [1.3.0] — 2026-07-10

### Added
- Deep `references/` docs for production skills (prop, vehicle, hair, cloth, VFX, camera, compositing, physics, engine exports, LOD, collision, scene, QA, styles, vegetation, set-dressing, archviz, lookdev)
- **Extended art styles:** cartoon, comic-book, manga, pixel-art, hand-painted, painterly, stop-motion-craft, chibi, noir, minimalist, vector, retro-8bit, retro-16bit, hd-2d, frutiger-aero
- **Horror packs:** cosmic-eldritch, body-horror, analog-found-footage, liminal-space, folk-horror, mascot-puppet, dream-weirdcore, indie-horror-aesthetics
- **Worlds:** fantasy-worlds, sci-fi-punk-worlds, historical-worlds, apocalypse-worlds, biome-worlds
- **Moods:** cozy-wholesome, dark-gritty, dream-surreal, neon-retrofuturism, brutalist
- **Gameplay genre direction:** action-combat, shooter, rpg, survival, stealth, puzzle-platformer, metroidvania-roguelike, soulslike, strategy-sim, racing-sports, narrative-vn, card-party-idle, open-world-sandbox
- **character-archetypes**, **visual-console-eras**
- Subtype coverage map in `SKILLS_GUIDE.md` (genres/styles map into pack skills + refs)

### Changed
- Skill count **46 → 94**; references **~40 → 175**
- `blender-director` routing expanded for genre/style/world/mood packs

---

## [1.2.0] — 2026-07-10

### Added
- **Modeling:** `prop-artist`, `vehicle-artist`, `vegetation-artist`
- **Character / sim:** `hair-groom`, `cloth-sim`
- **Technical:** `vfx-fx`, `camera-cinematography`, `compositing`, `physics-sim`, `lookdev`
- **Pipeline:** `unity-export`, `unreal-export`, `godot-export`, `lod-pipeline`, `collision-proxy`, `scene-assembly`, `set-dressing`, `qa-review`, `archviz`
- **Styles:** `anime-style`, `voxel-style`, `isometric-style`, `psx-horror-style`
- Expanded `blender-director` routing tables and multi-skill workflows
- Updated `SKILLS_GUIDE.md` decision trees for new disciplines and engines

### Changed
- Skill count **23 → 46** (`version.json`, README, plugin metadata)
- `hard-surface` now defers dedicated vehicles to `vehicle-artist`
- `skill-routing.md` engine targets point at Unity/Unreal/Godot export skills

---

## [1.1.0] — 2026-07-05

### Added
- `references/reference-image-match.md` — Full photo/concept-art-to-Blender workflow
- `references/reference-analysis-template.md` — Mandatory pre-flight analysis form for reference tasks
- `references/visual-match-checklist.md` — Pass/fail validation vs reference image
- Reference image routing added to `blender-director` SKILL.md
- Screenshot comparison loop protocol in `mcp-integration.md`
- Visual match section in `validation-checklist.md`
- `docs/local_skill_development.md` — Guide for adding custom skills
- `CONTRIBUTING.md` — Contribution guidelines
- `CHANGELOG.md`, `LICENSE`, `.gitignore`, `version.json`, `ROADMAP.md`
- Reference image workflow added to `SKILLS_GUIDE.md`, `README.md`, `CLAUDE.md`

### Changed
- `blender-director` — Now detects attached reference images and routes to match workflow
- `asset-pipeline.md` — Reference collection phase now covers photo analysis
- `rendering` SKILL.md — AgX grading and EEVEE preview settings for animation playback documented
- `skill-routing.md` — Reference phase added to production phase table
- `QUICKSTART.md` — Reference task routing added to cheat sheet
- All SKILL.md frontmatter updated to follow Jeffallan schema (description formula, metadata fields)
- `plugin.json` / `marketplace.json` — Author field updated; keywords expanded

### Fixed
- White hull blowout: documented per-object light material pattern; shared structural material animation flagged as anti-pattern
- EEVEE playback blur: taa_samples + motion blur off pattern documented in rendering skill

---

## [1.0.0] — 2026-07-05

### Added
- 23 specialist skills: `blender-director`, `blender-modeler`, `hard-surface`, `environment-artist`, `character-artist`, `creature-artist`, `sculpting`, `retopology`, `uv-workflow`, `materials`, `texture-workflow`, `geometry-nodes`, `lighting`, `rendering`, `animation`, `rigging`, `procedural-modeling`, `asset-optimization`, `export-pipeline`, `horror-style`, `lowpoly-style`, `stylized-style`, `realistic-style`
- Shared references: `asset-pipeline.md`, `mcp-integration.md`, `mcp-tools.md`, `naming-conventions.md`, `polycount-budgets.md`, `validation-checklist.md`
- Blender MCP integration (`.cursor/mcp.json`, `.mcp.json`)
- `SKILLS_GUIDE.md` — Decision trees and workflow combinations
- `QUICKSTART.md` — Installation for Claude Code and Cursor
- `docs/BLENDER_MCP_SETUP.md` — Full MCP connection guide
- `CLAUDE.md` — Agent instructions
- `.claude-plugin/` — Claude Code plugin manifest
