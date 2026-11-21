# Motion Quality — Measure Clips, Do Not Eyeball Them

> `production/scripts/blender/motion_qa.py` (gate G5, with `anim_check.py` and `deform_check.py`).
> The measures follow blender-kiln's animation rules — every one is a cycle that looked right on a
> contact sheet and wrong in motion.

## What is measured

| Measure | Target (default threshold) | Why |
|---|---|---|
| `reach_max` — limb start→end distance / rest chain length | ≤ 0.95 | A leg past ~95 % locks straight and reads as too long (kiln rule 3: rejected walk peaked at 101 %, approved one at 93 %) |
| `joint_pops` — knee/elbow bend spiking ≥ 8° against both neighbours | 0 | One-frame snaps read as trembling knees; no other measure flags them |
| `jitter_deg` — worst out-and-back turn of any deform bone across one frame | ≤ 8° | Popping keys, IK flips, constraint switches |
| `under_floor_mm` — deepest skin under the rest floor | ≤ 5 mm | Feet and bellies sinking into the ground |
| `standing_pitch_deg` — foot bone pitch off rest while standing | ≤ 5° (legs, not paws) | Tiptoeing in boots (kiln: 30° toes-down on a mascot) |
| `seam_ratio` — step across the loop / mean step | ≤ 1.2 | Visible hitch at the loop |
| `closing_key` — last frame equals the first | true | glTF plays to the last key; without it the step back is skipped (kiln rule 5) |

Limbs are found by name (Rigify `DEF-thigh/shin/foot`, `DEF-upper_arm/forearm/hand`; Mixamo `UpLeg/Leg/Foot`;
kiln names) or given in `limbs`. Twist segments (`.001`) are part of the chain.

## The loop

```
motion_qa.py  →  problems  →  fix (generator parameters, or anim_curves.py)  →  motion_qa.py
```

| Problem | First fix |
|---|---|
| Reach > 95 % | Shorter stride or lower hips in the generator; lower the hips no further than the legs need (kiln: 15 % read as stalking, 5–8 % held) |
| Joint pops | `anim_curves smooth` on the limb's FK/IK controls; if they persist, ease the reach (above) |
| Jitter on one bone | Look at its keys around the frame: a flipped quaternion sign, an IK pole switch, a stray key — `smooth` or `clean` |
| Skin under floor | Raise the root at those frames (`anim_curves offset` with `frames` + `blend`), or reduce squash |
| Standing pitch | Copy rotation of the foot to its rest orientation while planted (kiln rule 7: hold paws level) |
| Seam | `anim_curves match_cycle`; for generated/mocap clips `loop_window` |
| "nothing moves" | Wrong action slot, or DEF bones not following the controls (Rigify drivers lost on a copy) |

## Rules that come with it

1. **Drive a bone in its own rest frame.** A bone along the body has local Y forward, not up: convert
   world offsets with `(arm.matrix_world.to_3x3() @ bone.matrix_local.to_3x3()).inverted() @ offset`.
2. **Measure a rotation's sign before using it**: rotate +0.2 rad and watch which way a probe moves.
3. **Judge motion in motion and with numbers** — a contact sheet showed a jump as a body lying flat;
   the hip height said it rose 0.32 → 0.61 m.
4. Measured on the project cat (AN_walk, Rigify, 11.9 k vertices): reach 98.6 %, 8 knee pops, jitter
   10.3° — invisible on stills. After `smooth`: 96 %, 0 pops, 5.7°.
