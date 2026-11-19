# Range-of-Motion (ROM) Test

> Reference for: deformation-prep, qa-review
> Load when: validating a rig before animation (step 8, gate G4c)

## ROM Action

`production/scripts/blender/rom_test.py` creates action `AN_ROM` on the rig:

- One block of frames per joint; each block goes rest → limit A → rest → limit B → rest.
- Limits come from the category preset (`rom_limits`) or the spec; hinge joints bend one way only.
- Twist joints add ± twist blocks.
- Rigid-part hinges use their hinge limits.

## Metrics per Joint (on the evaluated, deformed mesh)

| Metric | Definition | Typical failure |
|--------|-----------|-----------------|
| `volume_loss` | max(0, 1 − cross-section area at limit / area at rest) on the joint bisector plane | Flattened joint |
| `pinch` | 1 − (closest band vertex to the posed joint centre at limit / same distance at rest) | Inner side collapsing into the bone (elbow/knee crease) |
| `stretch_max` | Max edge length ratio limit/rest in the band | Rubbery shoulders |
| `twist_collapse` | Min cross-section area ratio along a twisting segment | Candy-wrapper wrist |
| `self_intersections` | Overlapping face pairs (BVH tree overlap) in the band | Armpit/groin pinching |
| `rigid_gap` | Max distance between rigid part border and its neighbour at the limit | Gaps at hinges |
| `jitter` | Max per-vertex acceleration between consecutive frames | Weight noise |

Thresholds: `output-spec.yaml → acceptance.G4c`. With no threshold the value is reported and the user judges from the contact sheet.

## Contact Sheet

For each joint, render the worst frame (highest volume loss or intersections) from two angles at matching scale; save `reports/rom_<joint>.png` and a combined `reports/rom_sheet.png`. The user approves G4c from this sheet.

## Fix Loop

| Failing metric | Back to |
|----------------|---------|
| volume_loss, pinch, stretch | Step 4 (loops) or step 7 (weight gradient) |
| twist_collapse | Step 6 (twist bones) + step 4 (loops along segment) |
| self_intersections | Step 7 (weights), then limits |
| rigid_gap | Step 3 (overlap/gasket) or hinge pivot |
| jitter | Step 7 (smooth, clean small weights) |

Max three loops per joint before escalating to the user with the metrics.
