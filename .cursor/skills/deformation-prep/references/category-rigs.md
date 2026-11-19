# Category Rigs

> Reference for: deformation-prep, animation, blender-director
> Load when: choosing a family, skeleton template, focus joints and default clips for a category

Each category has a preset in `production/presets/categories/<category>.yaml` with the same fields as the table. Add a category by adding a preset file; skills do not change.

## Families

| Family | Path |
|--------|------|
| `creature` | Full deformation-prep (steps 2–8) |
| `articulated_object` | Rigid parts + hinge pivots; ROM = hinge limits only |
| `static_object` | No rig; animation = object/node transforms |

## Shipped Categories

| Category | Family | Template | Focus joints | Default clips |
|----------|--------|----------|--------------|---------------|
| `human` | creature | Rigify Human (Basic Human if no face/fingers needed) | shoulders, elbows, wrists, hips, knees, fingers, neck, face | idle, walk, run, wave |
| `dog` | creature | Rigify Wolf | shoulders, front elbows, hips, hind hocks (digitigrade), neck, tail, ears | idle, walk, run, sit, tail_wag |
| `cat` | creature | Rigify Cat | as dog + flexible spine, long multi-segment tail | idle, walk, jump, sit |
| `parrot` | creature | Custom bird template (`production/rigs/bird_metarig.py`) — Rigify ships no bird metarig | wing shoulder/elbow/wrist, wing fold, neck, grasping toes, tail feathers | idle, head_tilt, flap, fly, perch_bob |
| `book` | articulated_object | Spine hinge + page bend chain | spine hinge, page edge | open, close, page_flip |
| `box` | articulated_object | One hinge per lid | lid hinge | open, close |
| `chair` | static_object (articulated if swivel/folding) | None, or pivots for swivel/fold | swivel axis, fold hinge | turntable, swivel, fold |
| `table` | static_object | None | — | turntable, appear |

Rigify metarigs shipped with Blender: Basic Human, Basic Quadruped, Human, Cat, Wolf, Horse, Shark. Rigify assumes 1 unit = 1 m, so normalise scale first.

## Creature Notes

- **Quadrupeds:** the hind "reverse knee" is the hock (ankle); apply hinge rules there, not human knee rules. Tail, ears and neck are chains.
- **Birds:** wing = shoulder (ball), elbow and wrist (hinges); feather cards ride wing/tail chains. Fused wings: see `region-strategy.md → Fused Parts`.
- **Fur/feathers for web:** bake surface detail to normal maps; silhouette cards with alpha are optional and count against the draw-call/overdraw budget.
- Export DEF (deform) bones only; control rig stays in the .blend.

## Articulated Objects

### Hinge detection

1. Split rigid parts (by welded components, material, or a user-drawn cut).
2. Candidate axis = the longest straight edge chain shared or nearest between the two parts, or the axis of a cylinder-like feature (hinge barrel, book spine).
3. Set the part's origin on that axis; align the local X axis with it.
4. Show the axis to the user when confidence < 0.8.

### Limits

Hinge limits come from the preset (e.g. lid 0–110°) or the spec; ROM test checks no interpenetration at the limit.

## Static Objects

No armature. Clips animate the root node (rotation for turntable, scale/translate for appear, simple bounce curves). glTF stores these as node transform animations without skinning.
