# Limb Junctions: Belly, Armpit and Groin Under a Walk

> Load when: skin folds, creases or flips where legs meet the body during a walk or run, typically on chubby, stylised or short-legged characters (kittens, puppies, chibi animals).

## Why automatic weights fold there

Bone heat gives the hip and shoulder region a gradient between body bones and the limb's upper segment. With linear blend skinning (the only skinning glTF runtimes support) a vertex weighted half to a body bone and half to a thigh swung 30° lands between two rigidly moved copies, so the skin collapses and buckles. On a round body the junction covers much of the belly and flank, and the ROM test (one joint at a time) does not show it: four legs moving in opposite phases do. Spreading the gradient by smoothing makes it worse (more skin shares the swing); cutting the limb influence with transfers moves the crease to the new border.

## Fix (glTF-safe)

1. **Half-rotation helpers** — `production/scripts/blender/helper_bones.py` adds `DEF-<limb>_half.L/R` at each limb root (thigh, upper arm): same head and roll as the limb bone, parented like it, Copy Rotation from the limb at influence 0.5. The exporter bakes the constraint, so the GLB plays it with plain skinning.
   ```python
   {"rig": RIG, "limbs": [{"bone": "DEF-thigh.L"}, {"bone": "DEF-thigh.R"}, {"bone": "DEF-upper_arm.L"}, {"bone": "DEF-upper_arm.R"}]}
   ```
   Knee/elbow helpers did not help on the kitten (more bones per vertex than the 4-influence limit keeps).
2. **Refine the weights** — `skin_weights.py` `refine`:
   | Option | Effect |
   |--------|--------|
   | `helpers: true` | Each junction vertex is re-mapped body → helper → limb by its limb share s: body `1−2s`, helper `1−|2s−1|`, limb `2s−1` |
   | `helper_upper_share` | Moves that share of the upper segment's own weight (thigh, upper arm) to the helper — on short legs the upper segment is mostly inside the body. 0.9 worked on the kitten; 1.0 leaves the thigh bones unweighted |
   | `side_margin`, `side_falloff` | A .L limb bone loses its weight past the midline (inner legs, groin) |
   | `capsule_scale` | Limb weight kept within a capsule around each bone — no effect when bone heat already stays inside |
   | `junction_iterations` | Extra smoothing on the junction only — made folds worse on the kitten; leave 0 |
3. **Measure** — `production/scripts/blender/deform_check.py` over every clip: `fold_verts` (vertices whose neighbouring triangles bend ≥ 60° sharper than at rest), `flipped_max`, `edge_min`, and clusters with their weights. Compare variants by these numbers, then confirm with close-up renders from both sides at the worst frames (the metric finds where; the render shows whether it reads as a crease).

## Measured on the calico kitten (25 cm, 12 k-vertex deform mesh, 4 s walk)

| Weights | Fold vertices | Worst frame | Flipped faces |
|---------|---------------|-------------|---------------|
| Bone heat + smoothing (before) | 599 | 345 | 19 |
| + chest/belly transfers, junction smoothing | 553–1029 | 300–482 | 16–29 |
| + hip/shoulder helpers | 310 | 149 | 15 |
| + helpers, `helper_upper_share` 0.9, side margin 0.002 | 143 | 53 | 6 |

Visible creases on chest, belly and flanks were gone; the remaining fold vertices sit on the inner legs at the groin (hidden from the side). Blender ↔ three.js stayed at 0.2 mm on the walk.

## Pitfall: bones below the limb counted as body

The first version classed limb bones by name prefix, so the toe bones (`DEF-f_toe`, `DEF-r_toe`) counted as body. Paw vertices weighted to a toe were then re-mapped to the hip helper (72 % of the paw), and the paws swung with the hip instead of the foot — visibly skewed paws while walking (user report). `refine` now treats every deform descendant of a limb bone as limb. G4b (`skin_weights.py` check) also counts **far weights**: vertices with ≥ 20 % weight on a bone more than 3× farther than their nearest deform bone (and > 8 % of the mesh size); a helper is measured against the upper segment it stands in for. More than 0.2 % of the vertices fails the gate (the simulated paw bug: 377 vertices; the fixed kitten: 10). After any weight change, also check the paws with a rigid fit of the lowest vertices per leg against rest (yaw/roll should stay near 0°).
