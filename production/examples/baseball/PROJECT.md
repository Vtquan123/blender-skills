# Project: baseball

> Read this file first, every session. It is the project's memory: what the model is, what the user wants and
> does not want, what was decided, what changed and why. Update it after every change (section 5) and whenever
> the user states a preference (section 3). Machine-readable details live in the files listed in section 7.

Created: 2026-11-20 · Source: `input/baseball.glb` (SHA-256 in `input/MANIFEST.json`, never modified)

## 1. Model

- What it is: a regulation baseball built procedurally to test the pipeline (`production/tests/make_test_assets.py`, asset `baseball`): white leather sphere, seam on the tennis-ball curve, 108 red chevron stitches; one object, two materials.
- Real size: Ø 73.2 mm (0.0732 m), modelled at real scale.
- Measured: 6,594 vertices, 1 part (stitches touch the sphere), 1 ground contact, no extremities, sphere score 0.95 (`reports/structure.json`).
- Motion type: `rigid_whole/round` (score 0.98) — measured; no question needed except the clip list.
- Rig: `rigid_rig.py kind=ball` — 3 bones: `root` (travel) → `squash` (contact-point scaling, volume kept) → `spin` (rolling). The mesh is parented to `spin`; no skinning.

## 2. Status

| Stage | State | Evidence |
|-------|-------|----------|
| Intake (G0) | pass | `reports/gate-G0.json`, `reports/input-spec.yaml` |
| Plan (G1) | approved in chat 2026-11-20 | `plan.yaml` |
| Rig (G4b) | n/a — rigid, no skin | `working/recipe.json` step `rig` |
| Animation (G5) | needs_review — similarity approved in chat | `reports/preview/baseball_drop_bounce.mp4` |
| Export / web (G6–G7) | pass — 0 errors; 65 KB; Blender↔three.js 0.71 mm; motion 1.83 m | `reports/gate-G6.json`, `reports/gate-G7.json` |

Latest checkpoint: `checkpoints/06_animation.blend` · Deliverables: `output/baseball.glb` (web, meshopt), `output/baseball.master.glb`

## 3. Constraints and preferences

- One clip only: the ball falls, bounces away with shrinking hops and rolls to a stop (user, 2026-11-20). Do not turn it into a loop.
- Physical plausibility over cartoon exaggeration: real gravity, baseball restitution ~0.55; squash stays subtle (≤ 18 %).
- Rebuild only through `working/recipe.json`; changes to the motion go into `working/clips.json`, not into repo code.
- Do not push the repo without the user asking.

## 4. Decisions

| Date | Question | Answer | By |
|------|----------|--------|----|
| 2026-11-20 | Motion type | rigid_whole / round | measured (score 0.98) |
| 2026-11-20 | Front / travel direction | +X | default (round object) |
| 2026-11-20 | Clips | drop_bounce | user |
| 2026-11-20 | Textures | WebP (no `ktx` CLI installed) | default |

## 5. Changelog

- **2026-11-20** — Replayed from `working/recipe.json` alone (intake → structure → rig → clip → export → samples, then optimize, G6, G7): identical impacts (0.43, 0.93, 1.20, 1.33, 1.40, 1.43 s) and travel 1.756 m; G7 0.71 mm.
- **2026-11-20** — Clip `drop_bounce` (`ball_throw`: drop 1.0 m, 1.2 m/s forward, restitution 0.55, friction 0.12, rolling decel 0.6 m/s², squash ≤ 18 %): 6 impacts, 1.76 m travel, 2.8 s. Preview with a follow camera and a close-up inset. Found and fixed in the repo: preview ground placed at the ball's current (mid-air) height → framing now from the rest pose; added `follow_bone`.
- **2026-11-20** — Project created from the procedural baseball.

## 6. Open issues

- Rolled stitches can dip ~1 mm below the ground (the ground is set from the leather at rest); invisible at normal distance.
- Checkpoints are ~109 MB because they were saved from a shared test session that also holds the calico cat; a dedicated Blender file per project keeps them small.

## 7. Files

| File | Holds |
|------|-------|
| `output-spec.yaml` | Web desktop, real size, WebP, clip `drop_bounce`, approvals G1 |
| `plan.yaml` | Archetype, stages, decisions |
| `working/recipe.json` | Rebuild steps (repo scripts + arguments) and the external web commands |
| `working/clips.json` | Clip parameters (`ball_throw`) |
| `reports/structure.json` | Structure analysis |
| `reports/recipe_run.json` | Last replay: steps, timings, values passed between steps |
| `reports/preview/baseball_drop_bounce.mp4` | Approved preview |
| `checkpoints/` | `01_intake.blend`, `06_animation.blend` |

Rebuild everything from the source: in Blender run `production/scripts/blender/run_recipe.py` with
`{"project_dir": "<this folder>"}`, then the three `external` commands it prints (optimize, G6, G7).
