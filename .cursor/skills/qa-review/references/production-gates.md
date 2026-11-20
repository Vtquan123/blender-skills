# Production Gates

> Reference for: qa-review, blender-director
> Load when: running or reviewing gates G0–G8 in Production Mode

Gates turn the QA checklist into measured, repeatable checks. Each gate writes `reports/gate-<id>.json`; the runner is `production/scripts/validation/gates.py`, which compares metrics (produced by the Blender/Node scripts) against `output-spec.yaml → acceptance`.

## Status Values

| Status | Meaning |
|--------|---------|
| `pass` | Every metric with a threshold is within it |
| `fail` | At least one metric breaks a threshold → stage is redone or escalated |
| `needs_review` | Metrics recorded, a human decision is required (approval gates, or metrics without thresholds) |

A stage is "done" only when its gate is `pass`, or `needs_review` and the user approved it (approval recorded in the gate JSON as `approved_by: user`, with a timestamp).

## Gate → Metrics → Producer

| Gate | Metrics written to `reports/gate-<id>.json` | Thresholds read from `output-spec.yaml` | Produced by |
|------|------------------------------------------------|----------------------------------------|-------------|
| G0 | import_ok, triangles, components_raw/welded, boundary_edges_welded, missing_images | — (issues listed in `input-spec.yaml`) | `production/scripts/blender/intake.py` |
| G1 | required_fields_missing, strategy_conflicts | required spec fields | `production/scripts/validation/gates.py plan` |
| G2 | triangles, nonmanifold_edges, transforms_applied, components, silhouette_max_ratio / p95_m / max_m | `budgets.triangles` → `triangles_max`, `acceptance.G2.silhouette_max_dev` (fraction of source bbox diagonal) | `production/scripts/blender/mesh_metrics.py` (`gate: G2`, with `source`) |
| G3 | uv_layers, uv_overlap_ratio, uv_coverage, materials, maps_present, maps_empty | `acceptance.G3.uv_overlap_max`, `budgets.materials` → `materials_max`; empty maps always fail | `production/scripts/blender/mesh_metrics.py` (`gate: G3`, with the `bake_maps.py` result as `bake`) |
| G4a | joints_checked, joints_failing (+ per-joint rings, tri_ratio, poles in `joint-report.json`) | joint rules from the category preset | `production/scripts/blender/joint_analysis.py` |
| G4b | unweighted_verts, max_influences_found, verts_over_max_influences, unnormalized_verts | `budgets.max_influences` | `production/scripts/blender/skin_weights.py` (`mode: check`) |
| G4c | per-joint volume_loss, pinch, stretch_max, self_intersections, worst_frame | `acceptance.G4c.*` | `production/scripts/blender/rom_test.py` |
| G5 | clips (duration, loop seam, foot slide), missing; similarity to source is a user decision | `acceptance.G5.*` | `production/scripts/blender/anim_check.py` |
| G6 | validator_errors, validator_warnings, extensions_used, animation_count, skin_count, total_triangles | `acceptance.G6.validator_errors_max` | `production/scripts/node/validate_gltf.mjs` |
| G7 | bytes, file_size_mb, draw_calls, triangles, textures, load_ms, clips, max_vertex_dev_m, rest_match_max_m, page_errors | `acceptance.G7.*` | `production/scripts/validation/runtime_check.mjs` |
| G8 | input_checksums_ok, report_complete, gates_not_ok | — | `production/scripts/validation/gates.py final` |

A threshold left `null` in the spec is never filled in by the agent: the metric is recorded and the gate is `needs_review`, so the user decides.

## Review Rules

- Visual gates (G2 silhouette, G3 bake, G4a, G4c, G5) attach screenshots or sheets; no visual claim without an image.
- Never relax a threshold to make a gate pass; ask the user to change the spec instead and record it.
- Re-run the gate after every fix; keep previous gate JSON as `gate-<id>.<n>.json`.

The classic verdict (`qa-verdict-template.md`) is still written at G8, citing gate results.
