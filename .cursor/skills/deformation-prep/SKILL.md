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

1. **Archetype** — from `reports/structure.json` (`structure_analysis.py`) as confirmed in the plan (`../blender-director/references/motion-analysis.md`): `skinned` → steps 2–8; `rigid_parts` → separate rigid parts on pivots or bones (`rigid_rig.py` for vehicles, `hinge_rig.py` for lids/doors; cut fused parts only after the user agrees), then step 8 with hinge limits; `rigid_whole` → `rigid_rig.py kind=ball` or a single root, no skin; `chain_flex` → `chain_rig.py` (plant/spine) + step 7; `morph` → shape keys. A category preset only fills defaults. When bone heat fails (fused or self-intersecting meshes), `skin_weights.py` falls back to distance weights and reports it.
2. **Joint analysis** — place/confirm joint positions (existing rig, fitted metarig, or proposal), slice the mesh at each joint, score topology readiness (`references/joint-analysis.md`; `rig_fit.py` with fit/prune/trace/overrides from `references/category-rigs.md → Template Fitting`, `joint_analysis.py`). **User confirms joint placement.**
3. **Region strategy** — per region: skin, rigid part (weight 1.0 to one bone), or free chain (`references/region-strategy.md`).
4. **Deform mesh** — automatic quad base at the spec budget (`deform_mesh.py remesher`: `quadriflow` built in, `autoremesher` when the AutoRemesher extension is installed, `auto` = AutoRemesher with QuadriFlow fallback; spec `geometry.remesher`), then enforce joint loop rules (`references/joint-loop-rules.md`; `deform_mesh.py`); shrinkwrap to source. **Gate G4a (user approves wireframe per joint).**
5. **Surface** — UV with seams away from bend areas; bake normal/AO (and colour if UVs changed) from the source via `texture-workflow` (`bake_maps.py`).
6. **Rig** — fit and generate the template from `references/category-rigs.md` (`rig_fit.py`, `generate: true` after approval); add twist bones on long limbs; export deform bones only.
7. **Skin** — automatic weights on the clean deform mesh; rigid parts 1.0; weight transfer for accessories; limit to `budgets.max_influences` (web: 4), normalize, smooth, clean tiny weights (`skin_weights.py`). **Gate G4b.** Chubby bodies with short legs: add half-rotation helpers at the hips and shoulders before skinning (`helper_bones.py`) and pass `refine` to `skin_weights.py` (`references/limb-junctions.md`).
8. **ROM test** — generate the range-of-motion action, measure volume loss, stretch, intersections, twist collapse; contact sheet of worst poses (`references/rom-test.md`; `rom_test.py`). **Gate G4c (user approves).** Failing joints loop back to step 4, 6 or 7. Then check the skin under the real clips with `deform_check.py` (folds, flipped faces, collapsed edges per clip, clustered with their weights) — a walk moves four legs at once and creases where single-joint ROM does not.

Scripts live in `production/scripts/blender/` and expose `run(args) -> dict` (see `../blender-director/references/production-mode.md` §6).

## Technical Guidelines

| Problem | Fix |
|---------|-----|
| Elbow/knee collapses when bent | More loops at the joint (3 + supports), check weight gradient |
| Wrist/forearm "candy-wrapper" on twist | Twist bones splitting rotation; loops along the segment |
| Belly, armpit or groin folds/flips while walking (chubby body, short legs) | Half-rotation helpers at limb roots + `refine` (`helpers`, `helper_upper_share`, side split); measure with `deform_check.py` (`references/limb-junctions.md`) |
| Paws skew or slide off the leg after a weight change | A paw/toe weighted to a distant bone (e.g. a hip helper); G4b `far_weight_verts` shows it — refine must treat every bone below a limb as limb |
| Hard accessory bends with skin | Make it a rigid part weighted 1.0 to one bone |
| Wing/limb fused to body must open | Separate geometry and rebuild hidden surface + texture — ask the user first |
| Action pose (leap) as bind pose | Ask: rig as-is, re-pose to neutral (expect cleanup), or neutral asset from the user |
| Template far too long/short for a stylised body | `rig_fit.py` `fit: feet`, then `trace`/`overrides` (`references/category-rigs.md → Template Fitting`) |
| QuadriFlow "needs to be manifold" on a clean small mesh | Edges under 0.1 mm trip Blender's check; `deform_mesh.py` remeshes an enlarged copy automatically |
| QuadriFlow still fails, or claws/horns/teeth melt into blobs | `remesher: autoremesher` with `preserve_thin: true`, `island_detail: 10+`; intersecting shells → `weld_shells: true` (removes interior geometry) |
| AutoRemesher face count far below/above `target_faces` | Leave `adaptivity` unset so fitting can switch it (0 follows the target on blobby shapes, 1 on long thin ones); read `remesh.autoremesher.passes`, `settings`, `warnings` — thin features may set a density floor that a low budget cannot meet |
| `remesher: autoremesher` returns "extension not available" | `autoremesh.py mode=probe` → ask the user to install the zip it names (Blender 5.1+ vs `-blender42-` for 4.2–5.0), or rerun with `remesher: auto` |
| G4b fails "weights collapsed" (many DEF bones unweighted, head moves with a paw) | The rig does not overlap the mesh — check the generated rig against the mesh; never patch weights by hand first |
| Normal map shows the quad grid | Target was flat-shaded while baking; `deform_mesh.py` now shades smooth, re-bake normals |
| Blender and three.js poses differ by centimetres | B-Bone segments on DEF bones; flatten (default in `rig_fit.py`). Only one clip differs → that clip does not key `IK_FK` |
| Walking legs cross, knees flip, paws twist | Rigify IK on short legs; animate with `quadruped_walk_fk` (planar IK on FK controls) |
| Both paws skewed to the same side, even at rest | Rig generated facing another direction than -Y (Rigify paw helpers use world axes) or paw auto-tracking on; regenerate with current `rig_fit.py` and run the IK/FK rest check |

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
| Weld and cleanup before skinning | `../blender-modeler/references/mesh-cleanup.md` | Steps 4, 7 |
| Engine skeleton after rigging | `../rigging/references/game-ready-skeleton.md` | Step 6, before export |
| Motion measures under real clips | `../animation/references/motion-quality.md` | After step 8 |

## Knowledge Reference

deform mesh, joint analysis, edge loops, supporting loops, QuadriFlow, shrinkwrap, normal bake, Rigify metarig, DEF bones, twist bones, linear blend skinning, candy wrapper, automatic weights, weight transfer, robust weight transfer, max influences, normalize weights, rigid parts, hinge pivot, range of motion, ROM test, volume loss, self-intersection, gate G4a, gate G4b, gate G4c
