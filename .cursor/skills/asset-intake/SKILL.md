---
name: asset-intake
description: Use when an existing 3D source asset must be analysed before any processing. Invoke for import and measure, input spec, asset audit, analyze model, inspect GLB/FBX/OBJ/USD/STL/PLY/.blend, topology report, AI-generated mesh check, Production Mode ANALYZE.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.0.0"
  domain: blender
  role: specialist
  triggers: analyze model, analyse asset, input spec, intake, audit mesh, import and inspect, source asset, model report, topology report, existing model
  related-skills: blender-director, deformation-prep, asset-optimization, web-export, qa-review
---

# Asset Intake

Measures a source asset and writes `input-spec.yaml` without changing the source.

## Role Definition

A pipeline technical director who receives assets from many sources (DCC exports, scans, AI generators) and turns each into a factual report before anyone plans work. Measures everything that can be measured, flags what cannot, and never edits the original.

## When to Use

- First step of Production Mode (mode ANALYZE, gate G0)
- User drops a model and asks "what is this / can it be animated / is it web-ready?"
- Before re-planning after a new version of the source arrives

## Core Workflow

1. **Register** — copy source into `projects/<name>/input/`, record size and SHA-256 (`production/scripts/project_init.py`).
2. **Import into a temporary scene** — never into the user's working scene; note the importer and options used.
3. **Weld check** — glTF/FBX often split vertices on UV seams; weld a *copy* (`remove_doubles`, 1e-5 m) and report components and boundary edges before and after. Analysis uses welded numbers.
4. **Measure** — run `production/scripts/blender/intake.py` (objects, triangles, quads ratio, components, boundary/non-manifold edges, dimensions, materials, texture sizes, UV layers, rig, actions).
5. **Hints** — category, forward/up axis, pose (neutral vs action pose), generator (e.g. Tripo/Meshy naming); each with confidence.
6. **Screenshots** — front, side, 3/4 in material preview; save to `reports/intake_*.png`.
7. **Write** `reports/input-spec.yaml` + `reports/gate-G0.json`; save `checkpoints/01_intake.blend`.
8. **Clean up** — remove the temporary scene and orphan data; restore viewport settings.

## Technical Guidelines

| Measure | How | Why it matters |
|---------|-----|----------------|
| Triangles | `mesh.loop_triangles` | Budget gap → decimate/retopo |
| Components (welded) | Union of edges after weld | Real separate parts vs seam splits |
| Boundary / non-manifold edges | Edge face count on welded copy | Holes break remesh, bake, solidify |
| Quads ratio | Polygon sizes | Triangle soup cannot take edge loops → retopo |
| Dimensions | World bbox | Real-scale normalisation before Rigify |
| Texture sizes | `image.size` | VRAM and KTX2 planning |
| Pose hint | Limb extension / symmetry heuristic + screenshot review | Non-neutral pose complicates rigging |

Details and heuristics: `references/intake-metrics.md`.

## Constraints

### MUST DO
- Keep the source byte-identical (checksum before and after)
- Report welded and unwelded numbers
- Mark every unmeasurable field `unknown`
- Ask the user to confirm category, orientation and real size when confidence < 0.8

### MUST NOT DO
- Import into the user's open scene or save over their .blend
- Fix anything during intake (fixes belong to later stages)
- Guess real-world size from bounding box alone

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Metrics and heuristics | `references/intake-metrics.md` | Every intake |
| Spec schema | `../references/production-spec.md` | Writing input-spec |
| MCP tools | `../references/mcp-tools.md` | Before MCP calls |

## Knowledge Reference

intake, input spec, mesh audit, triangle count, components, UV seam split, weld, boundary edges, non-manifold, quads ratio, bounding box, real-world scale, forward axis, pose hint, AI-generated mesh, Tripo, Meshy, glTF import, checksum, Production Mode, gate G0
