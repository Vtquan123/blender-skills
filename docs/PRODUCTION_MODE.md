# Production Mode — User Guide

Turn a model you already have (detailed, AI-generated, sculpted or scanned) into a deliverable defined by an **output spec** — for example an optimised, animated GLB for a web page. The agent runs every step in Blender through MCP using the scripts in `production/`, measures each result, and stops at the points where a person has to decide.

Agent-side protocol: [`production-mode.md`](../.claude/skills/blender-director/references/production-mode.md) · spec schemas: [`production-spec.md`](../.claude/skills/references/production-spec.md) · routing: [`skill-routing.md`](../.claude/skills/blender-director/references/skill-routing.md)

## 1. Requirements

| Need | Notes |
|------|-------|
| Blender 5.1+ with a Blender MCP add-on | Official Blender Lab MCP add-on recommended ([setup](BLENDER_MCP_SETUP.md)) |
| This repository on the same machine as Blender | Blender runs the scripts from `production/scripts/` with `runpy` |
| Python 3.9+ with PyYAML | `project_init.py`, `gates.py` |
| Node 18+ | `cd production && npm install` once |
| Headless browser for the web check | `npx playwright install chromium`, or installed Google Chrome (`--chrome`) |
| Optional: KTX-Software `ktx` CLI | For KTX2 textures; otherwise set `compression.textures: webp` |

## 2. Start a Project

```bash
python3 production/scripts/project_init.py --workspace ~/3d-production --name calico_cat \
    --source ~/models/calicocat_3d.glb --preset web-desktop --category cat
```

This creates `projects/calico_cat/` with `input/` (a **copy** of your model plus `MANIFEST.json` checksums — the original is never touched), `output-spec.yaml`, `plan.yaml`, `state.json`, **`PROJECT.md`** (the project's memory), **`working/recipe.json`** (the rebuild steps) and empty `textures/ reports/ checkpoints/ output/`.

`PROJECT.md` is read by the agent first in every session: what the model is, the status, **your constraints and preferences** (write your own there — "no face animation", "keep the approved walk"), decisions, a changelog of every change (your feedback, cause, fix, numbers before → after) and open issues. `working/recipe.json` lists the repo scripts and arguments that rebuild the project from `input/`; your model's specifics are data in `working/`, the code stays shared.

Edit `output-spec.yaml` (or let the agent ask you): target devices, triangle/texture/file-size budgets, the clips you want, and acceptance thresholds. **A value left `null` is never invented** — the agent asks, or reports the measurement and leaves the decision to you.

Then ask the agent: *"Run Production Mode on ~/3d-production/projects/calico_cat"*.

## 3. What Happens

```
ANALYZE   asset-intake          import + measure → reports/input-spec.yaml           G0
          structure analysis    parts, ground contacts, limbs/branches, wheels →
                                how it can move + questions → reports/structure.json      ← you answer only what is unclear
PLAN      blender-director      strategy from facts × answers × spec → plan.yaml    G1  ← you approve
PRODUCE   deformation-prep      fit skeleton template, deform mesh with joint loops  G4a ← you approve joints
          texture-workflow      new UVs, bake colour/normal/ORM from the original    G2, G3
          deformation-prep      generate rig, skin weights, range-of-motion test     G4b, G4c ← you approve
          animation             clips from generators or your reference video        G5
EXPORT    web-export            master GLB → glTF-Transform → validator → three.js   G6, G7
DELIVER   qa-review             reports/report.md, input checksums                   G8
```

Strategy from the **geometry**, not from a category list (`production/scripts/blender/structure_analysis.py`; details in `.claude/skills/blender-director/references/motion-analysis.md`):

| Measured archetype | Examples | Rig | Clips |
|--------------------|----------|-----|-------|
| rigid_whole | ball, fruit, box, statue | Bones for roll/squash, or one root; no skinning | roll, bounce, turntable, hover |
| rigid_parts | car, cart, chest, laptop, door | Rigid parts on bones or hinge pivots; fused wheels/lids cut out only if you agree | drive, turn, open, close |
| chain_flex | tree, flower, snake, rope, tentacle | Bone chains along the measured branches/body + skin | wind sway, slither |
| skinned | cat, dog, human, bird | Rigify template fitted to the mesh, deform mesh with joint loops, helper bones on short round limbs | walk, idle, imitated clips |
| morph | slime, cushion | Shape keys | squash, wobble |

Category presets (`production/presets/categories/`) are only starting values; when the measurement disagrees, you are shown both.

## 4. Your Decisions

| When | You are asked |
|------|---------------|
| After analysis | Only what the measurement cannot settle: how it should move (when two archetypes score close), which end is the front, whether to cut fused parts (wheels, lid) so they can move, where a hinge is, which clips — each question shows the measurement and a recommended answer; answers are kept in `plan.yaml → decisions` |
| G1 | Approve the plan (stages, budgets, clips) |
| Joint placement / G4a | Approve the skeleton and the wireframe at each joint (`reports/img/G4a_*.png`) |
| G4c | Approve the range-of-motion results (`reports/rom.json`, contact sheet) |
| A clip has no source | Provide a video, GIF, image sequence or a short description; the motion is imitated, not motion-captured |
| Fused parts (wings in the body), action poses | Choose: keep, separate/re-pose (extra cleanup), or provide another asset |
| Missing spec values that change geometry, rig or budget | Give the value |

Record an approval: `python3 production/scripts/validation/gates.py approve --project <dir> --gate G4a --note "ok"`. Summary: `gates.py summary --project <dir>`.

## 5. Outputs

| File | What |
|------|------|
| `output/<name>.master.glb` | Uncompressed export — the reproducible source for any web variant |
| `output/<name>.glb` | Web file (meshopt + KTX2/WebP), what you ship |
| `reports/report.md` | Gates with values vs thresholds, deliverables, open issues |
| `reports/gate-*.json` | Machine-readable gate results |
| `reports/runtime/*.png` | Frames from the headless three.js check |
| `reports/preview/*.mp4` | Preview clips rendered in Blender (`preview_render.py`) |
| `checkpoints/NN_stage.blend` | Resume points; the run continues from the last good one |
| `PROJECT.md` | Project memory: model, status, constraints, decisions, changelog, open issues |
| `working/recipe.json`, `working/*.json` | Rebuild steps and their arguments; replay with `run_recipe.py` |
| `reports/recipe_run.json` | Last replay: steps, timings, values passed between steps |

Example (test run, calico cat): 58 MB / 1.94 M triangles → 0.94 MB / 23.8 k triangles, 45 deform bones, idle + walk, 1 draw call, 2.4 mm max difference between Blender and three.js.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Agent cannot reach Blender | Blender closed, add-on not running, Online Access off, or two add-ons on port 9876 ([setup](BLENDER_MCP_SETUP.md)) |
| A long step "times out" | The MCP client stopped waiting (~80 s) but Blender continues (first GPU bake compiles kernels). Wait for the output files; do not run it twice |
| G1 fails | A required spec field is missing (e.g. `asset.real_size_m` for creatures) |
| G4a fails on a joint | The joint sits outside the limb or the mesh lacks loops there; move the joint (`rig_fit.py` overrides) and rebuild the deform mesh |
| G4b fails "weights collapsed" | The rig does not overlap the mesh; regenerate the rig (the metarig transform must be applied) |
| Head or ears move with a leg | Same as above; never fix this by painting weights first |
| Normal map shows a grid | Deform mesh was flat-shaded while baking; shade smooth and re-bake normals |
| Large Blender ↔ three.js difference in G7 | B-Bones on deform bones; flatten them (default in `rig_fit.py`) |
| G6 "Entity cannot be empty" | Extra scenes exported; `export_glb.py` exports the active scene only |
| `optimize.mjs` exits 3 | KTX2 requested but `ktx` is not installed; install KTX-Software or use WebP |
| G7 cannot start a browser | Run `npx playwright install chromium` in `production/`, or pass `--chrome` to use installed Chrome |
| Wrong clip list in the GLB | Pass `clips: [...]` to `export_glb.py`; work actions such as `AN_ROM` are excluded |
| GLB has no animation / no skin | The armature was not exported; `export_glb.py` now unhides objects and errors if it cannot select them |
| Walking legs cross, knees flip, paws twist | Rigify IK on short legs; use `quadruped_walk_fk` |
| Both paws skewed to one side | Rig generated off the -Y convention or paw auto-tracking on; regenerate with current `rig_fit.py` (rest pose must not move in IK or FK) |
| One clip differs between Blender and three.js | That clip does not key `IK_FK`; pass `ikfk` to the generator |

## 7. Limits

- Animation from video is **imitation** with parametric generators and key poses, compared side by side — not motion capture.
- Thin strands (whiskers, hair wisps) do not survive the deform-mesh remesh; keep them as texture or separate rigid cards.
- Template limits for stylised proportions (chibi, cartoon) need review: preset ROM limits are written for realistic anatomy.
- KTX2 output, the parrot wing workflow and non-neutral poses have not yet been run end to end (see `ROADMAP.md`).
- Structure analysis is tested on procedural assets (ball, car as parts and fused, tree, chest, snake) and the calico cat; real vehicles and plants from AI generators may need the questions more often. Fused wheels are cut along measured circles: the cut faces are filled flat and may need touching up.
