# Project: {{name}}

> Read this file first, every session. It is the project's memory: what the model is, what the user wants and
> does not want, what was decided, what changed and why. Update it after every change (section 5) and whenever
> the user states a preference (section 3). Machine-readable details live in the files listed in section 7.

Created: {{created}} · Source: `input/{{source}}` (SHA-256 in `input/MANIFEST.json`, never modified)

## 1. Model

- What it is: _(one line, from the user and `reports/structure.json`)_
- Real size: _(longest dimension in metres; measured / confirmed by the user)_
- Measured: _(triangles, parts, contacts, limbs/branches/wheels — from `reports/input-spec.yaml`, `reports/structure.json`)_
- Motion type (archetype): _(e.g. `rigid_whole/round`, confirmed by the user on …)_
- Rig: _(template or builder, bone count, helpers)_

## 2. Status

| Stage | State | Evidence |
|-------|-------|----------|
| Intake (G0) | not started | |
| Plan (G1) | not started | |
| Rig / skin (G4) | not started | |
| Animation (G5) | not started | |
| Export / web (G6–G7) | not started | |

Latest checkpoint: _none_ · Deliverables: _none_

## 3. Constraints and preferences

Rules every step must respect. Ask the user before doing anything that conflicts with one; never drop one silently.

- _(e.g. "Do not animate the face", "The approved walk must not change when fixing the skin",
  "Paws point straight ahead", "Do not push without asking", budgets from `output-spec.yaml`)_

## 4. Decisions

| Date | Question | Answer | By (user / default / measured) |
|------|----------|--------|--------------------------------|

## 5. Changelog

Newest first. One entry per change: what the user asked or reported, the cause found, what changed (files,
parameters, scripts), measured result before → after.

- _{{created}}_ — Project created.

## 6. Open issues

- _(known limits, things to try next)_

## 7. Files

| File | Holds |
|------|-------|
| `output-spec.yaml` | Deliverable requirements (platform, budgets, clips, acceptance thresholds) |
| `plan.yaml` | Stages, archetype, decisions (machine-readable twin of sections 1 and 4) |
| `working/recipe.json` | Ordered steps (repo script + arguments) that rebuild the project; run with `run_recipe.py` |
| `working/*.json` | Arguments too long for the recipe (rig fitting, skinning, clip calls), referenced from the recipe |
| `reports/` | Measurements, gate results, `recipe_run.json` (last replay), `report.md` |
| `checkpoints/` | `.blend` after each stage |
| `state.json` | Stage status for resuming |

Rebuild everything from the source: run `production/scripts/blender/run_recipe.py` in Blender with
`{"project_dir": "<this folder>"}` (or `"from"` / `"to"` step ids), then the `external` commands it lists.
One-off code that only this model needs goes to `working/scripts/` with a note here — anything reusable belongs
in the repo with a test.
