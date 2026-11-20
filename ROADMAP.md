# Roadmap

Planned improvements for the Blender Skills Pack.

## Shipped in v1.5.0 — Any model: analysis, questions, new motion types

- [x] `structure_analysis.py`: archetypes from geometry with questions only where needed
- [x] Rigid rigs (ball, vehicle with steering, fused-wheel cut), chain rigs (plants, snakes), their generators
- [x] Limb-junction skinning (helper bones, refine, fold check), far-weight check, static-clip check in G7
- [x] Procedural test assets and regression runners in `production/tests/`

Next:
- [ ] Real AI-generated vehicles, plants and props through the full pipeline (test set beyond procedural assets)
- [ ] Hinged parts from the analysis straight into `hinge_rig.py` (hinge edge from the user's answer)
- [ ] Morph archetype (shape keys) generator and budget check
- [ ] Questions rendered with a coloured parts sheet

## Shipped in v1.4.0 — Production Mode

- [x] Spec-driven pipeline for existing assets (`blender-director` Production Mode, gates G0–G8)
- [x] `asset-intake`, `deformation-prep`, `web-export` + `production/` toolkit
- [x] Pack validator `scripts/check_skills.py` and `.cursor` sync scripts

Production Mode — next:
- [ ] End-to-end runs on dog, parrot (wing separation decision) and a non-neutral pose (leaping cat)
- [ ] KTX2 path verified with KTX-Software installed
- [ ] `rom_test.py`: twist_collapse, rigid_gap and jitter metrics (now judged visually)
- [ ] ROM contact sheet rendered by the script
- [ ] Optional UniRig template path; LOD stage in a Production Mode run
- [ ] CI job running `scripts/check_skills.py` and the headless `bpy` script tests

The "v1.4.0 — Character & Creature Pipeline" items below are still planned; their version number predates this release.

## v1.2.0 — Reference & Photogrammetry

- [ ] `references/photogrammetry-cleanup.md` — scan mesh cleanup workflow
- [ ] `references/reference-image-depth.md` — multi-angle reference triangulation
- [ ] `realistic-style` — scan-match material workflow (Quixel-style)
- [ ] Deeper `rendering` SKILL.md — Cycles denoiser presets per use-case

## v1.3.0 — Procedural Systems

- [ ] `geometry-nodes` — advanced scatter system reference
- [ ] `procedural-modeling` — terrain + road generation reference
- [ ] Blender 4.x geometry nodes API updates

## v1.4.0 — Character & Creature Pipeline

- [ ] `character-artist` — clothing simulation reference
- [ ] `retopology` — hair card topology reference
- [ ] `rigging` — shape key + driver reference for facial rigs
- [ ] `animation` — mocap cleanup workflow

## v1.5.0 — Engine Export Polish

- [ ] `export-pipeline` — Unreal 5 Nanite prep reference
- [ ] `export-pipeline` — Unity HDRP material mapping reference
- [ ] `asset-optimization` — automated LOD generation via Blender decimate modifier

## v2.0.0 — Multi-Agent Orchestration

- [ ] Parallel skill execution (Blender Director routes to multiple agents simultaneously)
- [ ] Blender + Substance Painter bridge (material handoff workflow)
- [ ] USD pipeline skill (OpenUSD for film/VFX)

## Backlog

- ~~Validation script for CI~~ — shipped as `scripts/check_skills.py` (CI wiring still open)
- GitHub Actions for SKILL.md schema lint on PRs
- Astro documentation site (mirroring Jeffallan pattern)
- Blender 4.x API compatibility matrix in `mcp-tools.md`
- `horror-style` — expanded Silent Hill / Bloober Team analysis reference
- `lowpoly-style` — PS1 dithering shader for Blender
