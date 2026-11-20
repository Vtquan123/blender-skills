# Motion Analysis: Any Model → How It Moves → What to Ask

> Reference for: blender-director (Production Mode ANALYZE → PLAN)
> Load when: deciding how an existing model should be rigged and animated — a creature, ball, vehicle, plant, furniture, prop or anything else — before writing `plan.yaml`

Categories do not scale: a model can be a toy car, a robot dog, a potted plant or a chest nobody has a preset for. The plan therefore comes from **measurements of the geometry**, checked against what the user wants. A category preset (`production/presets/categories/`) is only a prior: when it disagrees with the measurement, the measurement is shown to the user and they decide.

## 1. Measure

`production/scripts/blender/structure_analysis.py` (after intake, on the INTAKE scene or a `source` file; writes `reports/structure.json`). It uses no object names.

| Field | What it tells the planner |
|-------|---------------------------|
| `parts[]` | Separate shells or objects, each with a shape class (`sphere`, `disk` + axis + radius, `elongated`, `panel`, `blob`), share of the surface, which parts touch |
| `contacts[]` | Where the model meets the ground: four small (legs or wheels), one narrow (trunk, stem, pole), one large (base, box), many along a strip (snake, rope) |
| `skeleton.extremities[]` | Protrusions from the body core (limbs, head, tail, branches): length, radius, slenderness, direction, tip on the ground or not, path points. Box corners and lid rims are rejected by convex-hull concavity |
| `symmetry` | Mirror score across each horizontal axis (animals and vehicles are bilaterally symmetric) |
| `wheels[]` | Disks touching the ground — separate parts, or circles in the outermost side slab of a fused mesh |
| `forward` | Guess with confidence and basis (head vs tail, vehicle cabin, none for round objects) |
| `deformation_hints` | Leg length / height, `short_limbs_round_body` → helper bones and `refine` (deformation-prep) |
| `archetypes[]` | Scored candidates with reasons (below) |
| `questions[]` | What must be confirmed, with options and a recommendation |
| `suggested_clips` | Typical clips for the top archetype |

## 2. Archetypes → rig → clips → checks

| Archetype / subtype | Typical models | Rig (script) | Clips (generators.py) | Checks |
|---------------------|----------------|--------------|-----------------------|--------|
| `rigid_whole/round` | Ball, marble, fruit, planet | `rigid_rig.py kind=ball`: root → squash → spin, mesh on the spin bone | `ball_roll` (no slip, whole turns in loops), `ball_bounce` (squash/stretch, volume kept), `ball_throw` (drop or toss: falls, bounces away with restitution and friction, rolls to a stop) | Roll: contact point speed = root speed; bounce touches the ground; preview with `preview_render.py follow_bone: root` |
| `rigid_whole/prop` | Box, statue, bottle, toy, gadget | Object or one root bone | `turntable`, `bounce_in`, hover (`pose_keys`) | G6/G7 |
| `rigid_parts/vehicle` | Car, cart, train, tank, bike | `rigid_rig.py kind=vehicle`: root → body; steer → wheel bones | `vehicle_drive` (`speed`, `steer_deg`, `bob_m`, `lean_deg`, `in_place`) | Wheel spin vs speed (no skid), steering only on front wheels |
| `rigid_parts/hinged` | Chest, book, laptop, door, drawer | `hinge_rig.py` (pivot on the hinge edge the user names) | `hinge_open` | Limits; parts do not intersect at the limit |
| `chain_flex/plant` | Tree, flower, grass clump, cactus | `chain_rig.py mode=plant` + `skin_weights.py` | `wind_sway` (`amp_deg`, `sway_cycles`, `gust`) | `deform_check.py` (folds) |
| `chain_flex/body_chain` | Snake, worm, rope, tentacle, eel | `chain_rig.py mode=spine` + `skin_weights.py` | `wind_sway` with `axis: Z`, `phase_step` (travelling wave), `chain_curve` | `deform_check.py` |
| `skinned/quadruped`, `/biped`, `/multi_legged` | Animals, characters, robots with soft covers | `rig_fit.py` (Rigify template) or existing rig; `helper_bones.py` when `short_limbs_round_body`; `skin_weights.py refine` | `quadruped_walk_fk`, `biped_walk`, idle, `chain_curve` layers, reference-driven clips | G4b (incl. far weights), G4c ROM, `deform_check.py` over real clips, paw/foot rigidity |
| `morph/soft` | Slime, jelly, pillow, cartoon blob | Shape keys (glTF morph targets) | Squash / wobble keys | Morph count and size budget |

Mixed models combine rows: a vehicle with an antenna (chain on a rigid part), a creature carrying a rigid shield (rigid part parented to a bone), a tree with a swing (rigid part on a branch bone). Plan each part with its own row and say so in the plan.

## 3. When to ask (and when not)

Ask only when the answer changes what is built and the measurement does not settle it. `structure_analysis.py` already generates these; the director adds any that the output spec raises.

| Situation | Ask? | Default when unattended (say it in the plan) |
|-----------|------|------------------------------------------------|
| Top archetype score < 0.7 or margin < 0.2 | **Yes** — offer the top 2–3 with their reasons | Top candidate |
| Forward confidence < 0.8 for anything that travels or faces | **Yes** | Measured guess |
| Fused parts must move separately (wheels, lid, door in one AI mesh) | **Yes** — cutting changes geometry | Keep fused; animate only what moves as a whole |
| Hinge position (lid, door) | **Yes** — not visible in the geometry | Back edge |
| Steering, suspension, plant sway method, clip list | Yes, non-blocking, in one batch | Recommended option |
| Real size unknown and clips depend on speed/height | Yes (intake already asks) | Measured size, flagged |
| Short limbs on a round body, B-Bones, IK on stubby legs | **No** — measured; apply the fix and report it | — |
| Category name in the file ("car_final.glb") | **No** — never decide from names | — |

How to ask:
- One `AskUserQuestion` call with up to 4 questions; blocking ones first. Each question names the measurement behind it ("4 wheel-like circles touch the ground, fused into the body").
- Put the recommended option first with "(Recommended)".
- Record answers in `plan.yaml → decisions` (question id, answer, who, when) so a resumed run does not ask again.
- A rendered contact sheet (`intake_*.png`, or the structure parts coloured) helps the user answer; attach it when the question is about shape.
- If nobody can answer (scheduled run), take the default above, write it in `plan.yaml → open_questions` and in the report.

## 4. Plan from the answers

1. Archetype per part (section 2) → stages: geometry (only if budgets need it), surface, rig (script per row), animation (generators per clip), export.
2. Clip parameters scale with the measured size: ball speed in radii per second, vehicle speed from wheel radius, stride from leg length, sway amplitude from height. Never copy numbers from another model.
3. Checks per row (section 2) become plan acceptance items next to the spec thresholds.
4. Approval G1 as usual; the plan shows the measurement, the archetype, the decisions and their source (measured / user / default).

## 5. Tests

`production/tests/make_test_assets.py` builds a ball, a car (separate parts and fused), a tree, a chest with a lid and a snake; `run_structure_tests.py` checks the analysis (7/7 including the calico cat), `run_rig_tests.py` runs analysis → rig → clips → GLB for each. Add real models with `extra` and an expected archetype when a new kind of asset appears.
