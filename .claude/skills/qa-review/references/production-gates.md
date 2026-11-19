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

| Gate | Metrics | Produced by |
|------|---------|-------------|
| G0 | import_ok, missing_images, components_raw/welded, boundary_edges_welded | `scripts/blender/intake.py` |
| G1 | required_fields_missing, strategy_conflicts | `scripts/validation/gates.py plan` |
| G2 | triangles, nonmanifold_edges, transforms_applied, silhouette_dev | `scripts/blender/mesh_metrics.py` |
| G3 | uv_overlap_ratio, maps_present, maps_empty, materials | `scripts/blender/mesh_metrics.py`, `bake_maps.py` |
| G4a | per-joint rings/tri_ratio/poles | `scripts/blender/joint_analysis.py` |
| G4b | unweighted_verts, max_influences, unnormalized_verts, rigid_parts_ok | `scripts/blender/skin_weights.py` (`mode: check`) |
| G4c | per-joint volume_loss, stretch_max, twist_collapse, self_intersections, rigid_gap, jitter | `scripts/blender/rom_test.py` |
| G5 | clips_missing, fps, loop_seam_delta, foot_slide, similarity (user) | `scripts/blender/anim_check.py` |
| G6 | validator_errors, validator_warnings, axis_ok, scale_ok | `scripts/node/validate_gltf.mjs` |
| G7 | bytes, draw_calls, triangles, texture_bytes_gpu, clips_play, max_vertex_dev | `scripts/validation/runtime_check.mjs` |
| G8 | input_checksums_ok, report_complete | `scripts/validation/gates.py final` |

## Review Rules

- Visual gates (G2 silhouette, G3 bake, G4a, G4c, G5) attach screenshots or sheets; no visual claim without an image.
- Never relax a threshold to make a gate pass; ask the user to change the spec instead and record it.
- Re-run the gate after every fix; keep previous gate JSON as `gate-<id>.<n>.json`.

The classic verdict (`qa-verdict-template.md`) is still written at G8, citing gate results.
