# Production Mode

> Reference for: blender-director
> Load when: an existing source asset must be turned into a deliverable defined by an Output Specification

Production Mode is the spec-driven pipeline for **existing assets**. It reuses the specialist skills of this pack, adds three skills (`asset-intake`, `deformation-prep`, `web-export`), and drives Blender only through the connected Blender MCP.

## 1. Inputs and Outputs

| Item | Who writes it | Where |
|------|---------------|-------|
| Source asset | User | `projects/<name>/input/` (read-only) |
| `input-spec.yaml` | `asset-intake` (measured) | `projects/<name>/reports/` |
| `output-spec.yaml` | User (from `production/templates/output-spec.yaml` + a preset) | `projects/<name>/` |
| `plan.yaml` | Director (this file's strategy table) | `projects/<name>/` |
| `state.json` | Every stage | `projects/<name>/` |
| Checkpoints | Every stage | `projects/<name>/checkpoints/NN_<stage>.blend` |
| Deliverables | Export stage | `projects/<name>/output/` |
| Reports | Gates | `projects/<name>/reports/` (`gate-G*.json`, `report.md`) |

Schemas: `../../references/production-spec.md`. Project scaffolding: `production/scripts/project_init.py`.

## 2. Execution Modes

| Mode | Runs | Stops for user |
|------|------|----------------|
| ANALYZE | Intake → G0, then `structure_analysis.py` → `reports/structure.json` | Only the questions the analysis generates (archetype, front, fused parts, hinge, clips) — `motion-analysis.md` §3 |
| PLAN | Strategy table → `plan.yaml` + production brief → G1 | **Always** (approve plan) |
| PREVIEW | All enabled stages at preview settings (low remesh density, 512 px bakes, no LOD) | Shows screenshots and preview clips (`production/scripts/blender/preview_render.py`: separate scene with copies of the rig, ground, lights, follow camera, repeated clip with root motion; render in chunks, encode with ffmpeg); nothing is delivered |
| PRODUCTION | Enabled stages from `geometry` to `animation` | At gates the spec lists in `acceptance.approve_at` |
| VALIDATE | Re-runs gates on the latest checkpoint | Only if a gate fails |
| EXPORT | Export → web/engine optimisation → G6–G8 → report | Final review |

## 3. Strategy Table (planner)

The planner enables stages from **intake facts × output spec**. It never enables a stage the spec does not need.

| Intake fact / spec field | Stage decision |
|--------------------------|----------------|
| `triangles` > `budgets.triangles` and asset static | `geometry.strategy: decimate` (+ bake normal from source) |
| `triangles` > budget and asset must deform | `geometry.strategy: retopo` via `deformation-prep` (joint loops), bake from source |
| Mesh split along UV seams (many components, many boundary edges) | Weld in intake before any analysis |
| Structure archetype (`reports/structure.json`, confirmed by the user when asked) | Rig and clips per `motion-analysis.md` §2: `skinned` → `deformation-prep` → `rigging` → `animation`; `rigid_whole`/`rigid_parts` → `rigid_rig.py` or `hinge_rig.py`, no skinning; `chain_flex` → `chain_rig.py` + skin; `morph` → shape keys |
| Category preset (`asset.category`) | Prior only: fills defaults the user has not set; when it disagrees with the structure, show both and ask |
| `deformation_hints.short_limbs_round_body` | `helper_bones.py` + `skin_weights.py refine` (deformation-prep `limb-junctions.md`) |
| Fused parts that must move separately (wheels, lid) | Ask before cutting (`rigid_rig.py split_wheels`); default keep fused |
| Clip `source.type: none` | Pause animation stage, send source request (`animation/references/reference-driven-motion.md`) |
| `lod.levels` not empty | `lod-pipeline` |
| `target.platform: web` | `web-export` |
| Engine target | Matching engine export skill |
| Pose not neutral (intake `pose_hint`) | Ask user: rig as-is, re-pose, or supply a neutral-pose asset |

## 4. Gates

| Gate | After | Automatic checks (script → JSON) | Default approval |
|------|-------|----------------------------------|------------------|
| G0 | Intake | File imports; no missing images; units, scale, orientation recorded; weld result | No |
| G1 | Plan | Required spec fields present; strategy consistent with category | **Yes** |
| G2 | Geometry | Triangles ≤ budget; non-manifold = 0; transforms applied; silhouette deviation vs source | Spec |
| G3 | Surface | UV overlap (unless intended); texel density; bake maps present and non-empty; material count | Spec |
| G4a | Deform mesh | Joint loop rules met per joint; budget; silhouette | **Yes** (creatures) |
| G4b | Rig + weights | No unweighted verts; ≤ max influences; normalized; rigid parts 1.0 to one bone; far weights ≤ 0.2 % | No |
| G4c | ROM test | Per-joint volume loss, stretch, intersections, twist collapse within spec thresholds | **Yes** (creatures) |
| G5 | Animation | All clips present; fps/frame range; loop seam delta; foot slide; skin folds over each clip (`deform_check.py`); similarity sheet vs source | Spec |
| G6 | Export | glTF-Validator 0 errors; axis/scale; clip names | No |
| G7 | Web | File size, draw calls, texture memory; headless three.js load + play every clip; Blender↔three.js vertex check (skinned and rigid meshes); every clip moves | No |
| G8 | Deliver | Report complete; `input/` checksums unchanged | User reads report |

Thresholds come from `output-spec.yaml → acceptance`. A missing threshold means "report the value, do not judge" — never invent one.

Gate runner: `production/scripts/validation/gates.py`. Each gate writes `reports/gate-<id>.json`:

```json
{"gate": "G2", "status": "pass|fail|needs_review", "metrics": {}, "thresholds": {}, "notes": [], "checkpoint": "checkpoints/03_geometry.blend"}
```

## 5. State and Resume

`state.json` (written by `production/scripts/blender/u3d_common.py`):

```json
{
  "project": "calico_cat",
  "mode": "PRODUCTION",
  "stages": {
    "intake":   {"status": "passed", "checkpoint": "checkpoints/01_intake.blend", "gate": "G0"},
    "geometry": {"status": "failed", "checkpoint": null, "gate": "G2", "error": "..."}
  },
  "last_good_checkpoint": "checkpoints/01_intake.blend"
}
```

Resume protocol:
1. Read `state.json`; find the first stage whose status is not `passed`.
2. Open `last_good_checkpoint` in Blender (via MCP) — never re-import the source.
3. Re-run that stage only; then its gate.
4. A stage that fails three times stops the run and reports the gate JSON to the user.

## 6. Running Scripts Through Blender MCP

Scripts in `production/scripts/blender/` are plain Python modules with a `run(args: dict) -> dict` function.

- **Repo cloned on the Blender machine (preferred):**
  ```python
  import runpy
  ns = runpy.run_path("/path/to/blender-skills/production/scripts/blender/intake.py")
  result = ns["run"]({"source": ".../input/model.glb", "project_dir": ".../projects/demo"})
  ```
  Send this through the MCP tool that executes Python in the connected Blender instance (official Blender MCP: `execute_blender_code`; the code must assign a dict to `result`).
- **No local clone:** send the script text followed by `result = run({...})` in one call.
- Long operations (remesh, bake): run one stage per call; save a checkpoint at the end of the call.
- After every call, verify scene state with the MCP's object/scene summary tools before marking the stage passed.

## 7. Approval Points (never skip)

- G1 plan approval.
- Any destructive step on data not yet checkpointed.
- Joint placement (start of `deformation-prep`) and G4a/G4c for creatures.
- Blocking questions from `reports/structure.json` (archetype, front, cutting fused parts, hinge) — answers go to `plan.yaml → decisions`.
- Animation source request when a clip has no source.
- Missing spec field that changes geometry, rig or budget.

## 8. Report

`reports/report.md` from `production/templates/report.md`: source summary, plan, stages run, gate table with values vs thresholds, screenshots, deliverable list with sizes, open issues. Never mark a stage "passed" in the report without its gate JSON.
