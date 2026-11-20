# Range-of-Motion (ROM) Test

> Reference for: deformation-prep, qa-review
> Load when: validating a rig before animation (step 8, gate G4c)

## ROM Action

`production/scripts/blender/rom_test.py` creates action `AN_ROM` on the rig:

- One block of frames per joint; each block goes rest → limit A → rest → limit B → rest.
- Limits come from the category preset (`rom_limits`) or the spec; hinge joints bend one way only.
- Twist joints add ± twist blocks.
- Rigid-part hinges use their hinge limits.
- Limits are rotations of the FK **control** from its rest pose. A joint that is already bent at rest (a stylised elbow at 59°) reaches rest + limit, so reduce preset limits for such assets instead of reading the extreme as a failure.
- The script switches every Rigify `IK_FK` property to FK (1.0) for the test and restores it (`fk: true`); without that, rotating `*_fk` controls does not move IK limbs.
- Sign check: positive X on Rigify limb FK controls flexes the joint (verified on the cat: elbow 59° → 171° at +130°). Confirm on new templates by measuring the angle between the two DEF bones.

## Metrics per Joint (on the evaluated, deformed mesh)

| Metric | Definition | Typical failure |
|--------|-----------|-----------------|
| `volume_loss` | max(0, 1 − cross-section area at limit / area at rest) on the joint bisector plane | Flattened joint |
| `pinch` | 1 − (closest band vertex to the posed joint centre at limit / same distance at rest) | Inner side collapsing into the bone (elbow/knee crease) |
| `stretch_max` | Max edge length ratio limit/rest in the band | Rubbery shoulders |
| `self_intersections` | Overlapping face pairs (BVH tree overlap) in the band | Armpit/groin pinching |
| `twist_collapse` * | Min cross-section area ratio along a twisting segment | Candy-wrapper wrist |
| `rigid_gap` * | Max distance between rigid part border and its neighbour at the limit | Gaps at hinges |
| `jitter` * | Max per-vertex acceleration between consecutive frames | Weight noise |

\* Not computed by `rom_test.py` yet: judge from the contact sheet (twist blocks show candy-wrapping; scrub for jitter).

Thresholds: `output-spec.yaml → acceptance.G4c` (`volume_loss_max`, `pinch_max`, `stretch_max`, `self_intersections_max`). With no threshold the value is reported and the user judges from the contact sheet. The measurement band can be wide where a joint sits inside the body (stubby legs), which raises `stretch_max`; always read it with the images.

## Contact Sheet

For each joint, render the worst frame (highest volume loss or intersections) from two angles at matching scale; save `reports/rom_<joint>.png` and a combined `reports/rom_sheet.png`. The user approves G4c from this sheet. Render with `bpy.ops.render.opengl(view_context=True)` + `save_render` (see `../../references/mcp-tools.md → Images`); set `IK_FK` to 1.0 while viewing `AN_ROM`.

## Fix Loop

| Failing metric | Back to |
|----------------|---------|
| volume_loss, pinch, stretch | Step 4 (loops) or step 7 (weight gradient) |
| twist_collapse | Step 6 (twist bones) + step 4 (loops along segment) |
| self_intersections | Step 7 (weights), then limits |
| rigid_gap | Step 3 (overlap/gasket) or hinge pivot |
| jitter | Step 7 (smooth, clean small weights) |

Max three loops per joint before escalating to the user with the metrics.
