---
name: deformation-prep
description: Use when an existing detailed mesh must be made to deform or move well — joint analysis, remesh for animation, edge loops at joints, splitting into rigid parts, rig template fitting, skin weights and range-of-motion testing. Invoke for animation-ready conversion of AI-generated or sculpted models, characters, animals, birds and articulated objects.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.0.0"
  domain: blender
  role: specialist
  triggers: prepare for animation, deform mesh, joint loops, remesh for rigging, auto rig existing model, skin weights, range of motion, ROM test, split into parts, rigid parts, hinge, make it animatable
  related-skills: retopology, rigging, animation, texture-workflow, uv-workflow, asset-intake, blender-director, cloth-sim, hair-groom
---

# Deformation Prep

Turns a detailed but un-rigged mesh into a deform mesh + rig that bends cleanly, then proves it with a range-of-motion test.

## Role Definition

A creature/character technical director who rebuilds topology for deformation, decides region by region whether a part should bend, stay rigid or hang free, fits skeleton templates, and refuses to hand over a rig that has not passed extreme-pose tests. Works only through Blender MCP and keeps the source mesh untouched as the bake source.

## When to Use

- Source mesh is dense, triangulated or has no animation edge flow (scans, sculpts, AI-generated models)
- Any `rig.required: true` stage in Production Mode
- Objects with moving parts (lids, covers, hinges, swivels) that need pivots instead of skinning

## Core Workflow

1. **Family** — read `rig.method` and the category preset: `creature` → steps 2–8; `articulated_object` → rigid parts + hinge pivots (`references/category-rigs.md`, `production/scripts/blender/hinge_rig.py`), then step 8 with hinge limits; `static_object` → stop (no rig).
2. **Joint analysis** — place/confirm joint positions (existing rig, fitted metarig, or proposal), slice the mesh at each joint, score topology readiness (`references/joint-analysis.md`; `rig_fit.py`, `joint_analysis.py`). **User confirms joint placement.**
3. **Region strategy** — per region: skin, rigid part (weight 1.0 to one bone), or free chain (`references/region-strategy.md`).
4. **Deform mesh** — automatic quad base (QuadriFlow or an installed remesher) at the spec budget, then enforce joint loop rules (`references/joint-loop-rules.md`; `deform_mesh.py`); shrinkwrap to source. **Gate G4a (user approves wireframe per joint).**
5. **Surface** — UV with seams away from bend areas; bake normal/AO (and colour if UVs changed) from the source via `texture-workflow` (`bake_maps.py`).
6. **Rig** — fit and generate the template from `references/category-rigs.md` (`rig_fit.py`, `generate: true` after approval); add twist bones on long limbs; export deform bones only.
7. **Skin** — automatic weights on the clean deform mesh; rigid parts 1.0; weight transfer for accessories; limit to `budgets.max_influences` (web: 4), normalize, smooth, clean tiny weights (`skin_weights.py`). **Gate G4b.**
8. **ROM test** — generate the range-of-motion action, measure volume loss, stretch, intersections, twist collapse; contact sheet of worst poses (`references/rom-test.md`; `rom_test.py`). **Gate G4c (user approves).** Failing joints loop back to step 4, 6 or 7.

Scripts live in `production/scripts/blender/` and expose `run(args) -> dict` (see `../blender-director/references/production-mode.md` §6).

## Technical Guidelines

| Problem | Fix |
|---------|-----|
| Elbow/knee collapses when bent | More loops at the joint (3 + supports), check weight gradient |
| Wrist/forearm "candy-wrapper" on twist | Twist bones splitting rotation; loops along the segment |
| Hard accessory bends with skin | Make it a rigid part weighted 1.0 to one bone |
| Wing/limb fused to body must open | Separate geometry and rebuild hidden surface + texture — ask the user first |
| Action pose (leap) as bind pose | Ask: rig as-is, re-pose to neutral (expect cleanup), or neutral asset from the user |

Web runtimes use linear blend skinning and read four influences per vertex; design weights for that limit (`web-export`).

## Constraints

### MUST DO
- Keep the source mesh as bake source; never rig it directly
- Get user confirmation on joint placement, G4a and G4c
- Checkpoint after deform mesh, rig, and skin
- Record per-joint metrics in `reports/gate-G4*.json`

### MUST NOT DO
- Ship a rig that has not passed the ROM test
- Exceed the spec's influence limit
- Open fused parts (wings, limbs) without the user's decision
- Use Rigify control bones in the export; export DEF bones only

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Joint analysis | `references/joint-analysis.md` | Step 2 |
| Region strategy | `references/region-strategy.md` | Step 3 |
| Joint loop rules | `references/joint-loop-rules.md` | Step 4 |
| Category rigs (human, dog, cat, parrot, book, box, chair, table) | `references/category-rigs.md` | Steps 1, 6 |
| ROM test and metrics | `references/rom-test.md` | Step 8 |
| Retopology craft | `../retopology/SKILL.md` | Step 4 |
| Rigging craft | `../rigging/SKILL.md` | Steps 6–7 |
| Web skinning limits | `../web-export/references/web-runtime-limits.md` | Steps 6–7 |

## Knowledge Reference

deform mesh, joint analysis, edge loops, supporting loops, QuadriFlow, shrinkwrap, normal bake, Rigify metarig, DEF bones, twist bones, linear blend skinning, candy wrapper, automatic weights, weight transfer, robust weight transfer, max influences, normalize weights, rigid parts, hinge pivot, range of motion, ROM test, volume loss, self-intersection, gate G4a, gate G4b, gate G4c
