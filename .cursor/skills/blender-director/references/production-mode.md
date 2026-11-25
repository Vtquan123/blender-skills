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
| PREVIEW | All enabled stages at preview settings (low remesh density, 512 px bakes, no LOD) | Shows screenshots and preview clips (`production/scripts/blender/preview_render.py`: separate scene with copies of the rig, ground, lights, follow camera, repeated clip with root motion; render in chunks, encode with ffmpeg) and the review viewer (`review_notes.py` publish/serve: the user pins notes on the model, `context` turns them into vertices, bones and frames — `../../qa-review/references/review-notes.md`); nothing is delivered |
| PRODUCTION | Enabled stages from `geometry` to `animation` | At gates the spec lists in `acceptance.approve_at`; before each visual gate the agent checks the model in the review viewer itself and offers it to the user (§7a) |
| VALIDATE | Re-runs gates on the latest checkpoint | Only if a gate fails |
| EXPORT | Export → web/engine optimisation → G6–G8 → report | Final review |

## 3. Strategy Table (planner)

The planner enables stages from **intake facts × output spec**. It never enables a stage the spec does not need.

| Intake fact / spec field | Stage decision |
|--------------------------|----------------|
| `triangles` > `budgets.triangles` and asset static | `geometry.strategy: decimate` (+ bake normal from source) |
| `triangles` > budget and asset must deform | `geometry.strategy: retopo` via `deformation-prep` (joint loops), bake from source; quad base from `geometry.remesher` (`quadriflow` / `autoremesher` / `auto` → `deform_mesh.py remesher`) |
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
| G2 | Geometry | Triangles ≤ budget; non-manifold = 0; transforms applied; no duplicate vertices; silhouette deviation vs source (cleanup: `mesh_cleanup.py`) | Spec |
| G3 | Surface | UV overlap (unless intended); texel density; bake maps present and non-empty; material count | Spec |
| G4a | Deform mesh | Joint loop rules met per joint; budget; silhouette | **Yes** (creatures) |
| G4b | Rig + weights | No unweighted verts; ≤ max influences; normalized; rigid parts 1.0 to one bone; far weights ≤ 0.2 % | No |
| G4c | ROM test | Per-joint volume loss, stretch, intersections, twist collapse within spec thresholds | **Yes** (creatures) |
| G5 | Animation | All clips present; fps/frame range; loop seam delta; foot slide; skin folds over each clip (`deform_check.py`); limb reach, joint pops, jitter, skin under floor, closing key (`motion_qa.py`; fixes with `anim_curves.py`); similarity sheet vs source | Spec |
| G6 | Export | glTF-Validator 0 errors; axis/scale; clip names; one skeleton root, no B-Bones, no deform scale (`game_skeleton.py` audit; engines: export rig) | No |
| G7 | Web | File size, draw calls, texture memory; headless three.js load + play every clip; Blender↔three.js vertex check (skinned and rigid meshes); every clip moves | No |
| G8 | Deliver | Report complete; `input/` checksums unchanged | User reads report |

Thresholds come from `output-spec.yaml → acceptance`. A missing threshold means "report the value, do not judge" — never invent one.

Gate runner: `production/scripts/validation/gates.py`. Each gate writes `reports/gate-<id>.json`:

```json
{"gate": "G2", "status": "pass|fail|needs_review", "metrics": {}, "thresholds": {}, "notes": [], "checkpoint": "checkpoints/03_geometry.blend"}
```

## 5. Project Memory, Recipe, State and Resume

**`PROJECT.md` — read first, every session.** Created by `project_init.py` from `production/templates/PROJECT.md`. Holds what the model is, status, the user's constraints and preferences, decisions, a changelog and open issues. Rules:
- Read it before any other project file or MCP call; it is the context a new session or another agent lacks.
- Never act against section 3 (constraints and preferences). If a new request conflicts with one, quote the constraint and ask.
- Record in section 3 every preference the user states in chat ("no face animation", "keep the approved walk", "do not push").
- After every change append a changelog entry: what the user asked or reported, the cause found, what changed (files, parameters, repo scripts), measured result before → after. Update sections 2 and 6.

**`working/recipe.json` — the rebuild.** The ordered steps (repo script + arguments) that turn `input/` into the deliverables; long arguments sit in `working/*.json` and are referenced (`args_file`, `args_key`). Values flow between steps with placeholders (`${project}`, `${scene_meshes}`, `${out.<step>.<key>}`). `production/scripts/blender/run_recipe.py` replays it in Blender (`from` / `to` / `only` / `dry_run`), writes `reports/recipe_run.json` and prints the external commands (optimize, G6, G7). Keep the recipe current as you work: a step that only exists in a chat cannot be rebuilt.
- Project specifics are data (recipe, argument files), never edits to repo scripts. Code needed by this model only goes to `working/scripts/` with a changelog note; anything reusable goes into the repo with a test.


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
0. Read `PROJECT.md` (constraints, open issues, last changelog entries, the standing review-viewer answer).
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
- Joint placement (start of `deformation-prep`) and G4a/G4c for creatures — with the review viewer offered (§7a).
- Blocking questions from `reports/structure.json` (archetype, front, cutting fused parts, hinge) — answers go to `plan.yaml → decisions`.
- Animation source request when a clip has no source.
- Missing spec field that changes geometry, rig or budget.

## 7a. Review Viewer at Visual Gates

Visual gates — G4a (deform mesh + joints), G4c (ROM / skin), G5 (each clip) and the final delivery — are judged
in the viewer the deliverable will run in (three.js), not only from Blender screenshots.
Tools: `review_notes.py` (`publish`, `serve`, `stop`, `context`, `reply`) — `../../qa-review/references/review-notes.md`.

1. **Agent self-check first (always, the user does not have to ask).** `publish` the current state (rig + skinned
   meshes, the clips of the gate), `serve`, open `http://127.0.0.1:8765/` in a browser on the Blender machine
   (the built-in browser or the user's Chrome reach the server; a cloud browser does not), and run the checks in
   `review-notes.md → Agent Self-Check`. Every problem found becomes a note with `author: "agent"`; fix it in
   Blender, `publish` again (current → previous, A/B view), re-check, `reply` with numbers. Present the gate only
   when no agent note is left open, or list the ones left open with the reason.
2. **Ask the user** in the same question that asks for the gate approval: "Open the review viewer to check it
   yourself?" (options: open it now / no, approve from the images). Skip the question when `PROJECT.md` §3 already
   holds the answer ("always open the viewer at visual gates" / "never"); record a standing answer there when the
   user gives one.
3. **Yes →** keep the server running, open the page for the user (built-in browser pane, or give the URL), set the
   clip and frame of interest, and wait. Read their pins with `context`; never guess a spot from a screenshot.
4. **When the gate is closed** (approved or sent back), `stop` the server unless the user is still using it, and
   say so. Record in the gate approval note whether the viewer was used (`--note "... viewer: agent + user"`).

The headless runtime check (G7, `runtime_check.mjs`) stays: it measures, the viewer is where people and the agent
look.

## 8. Report

`reports/report.md` from `production/templates/report.md`: source summary, plan, stages run, gate table with values vs thresholds, screenshots, deliverable list with sizes, open issues. Never mark a stage "passed" in the report without its gate JSON.
