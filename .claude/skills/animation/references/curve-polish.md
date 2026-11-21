# Curve Polish — Graph Editor Moves Through the MCP

> `production/scripts/blender/anim_curves.py` — key tools an animator reaches for in the Graph Editor
> (tween, blend, push/pull, smooth, offset), run as script calls so an agent can polish a clip without
> the UI. Ideas from AnimAide (aresdevo/animaide), re-implemented; loop rules from blender-kiln.

## Contents
- When to reach for it
- Selection model
- Ops at a glance
- Recipes
- Rules

## When to reach for it

| Symptom (from `motion_qa.py`, `anim_check.py` or a preview) | Op |
|---|---|
| A knee or elbow pops for one frame, jitter on one bone | `smooth` on that limb's controls (2–3 iterations, `cyclic: true` for loops) |
| A breakdown key is too strong / too weak | `push_pull` on that key range (+ exaggerate, − flatten) |
| A key should sit between its neighbours (breakdown) | `tween` (`t` 0..1) |
| A pose must hold longer / settle | `blend_neighbor` towards the key it should hold to |
| Pose the whole clip a little lower / turned (hips too high, legs locked) | `offset` with `from_pose` or `delta`, `blend` frames of falloff |
| Ears, tail, antenna, hair move stiffly with the head/body | `overlap` (`follow`: delayed copy of the driver; `delay`: shift the chain's own motion) |
| Two clips meet with a pop at the loop | `match_cycle` (closing key = first key, quaternion signs fixed) |
| A generated / mocap clip does not loop | `loop_window` → a new `<action>_loop` action |
| Organic motion too mechanical | `wave` (`kind: noise`, small amplitude) on a secondary chain |
| Dense baked keys, heavy file | `clean` (tolerance in curve units) |
| A move is too early / late on one channel | `time_offset` (`shift` frames, cyclic wrap) |

## Selection model

- `object` + `action` (default: the active one). The action is assigned temporarily if needed; the
  previous assignment is restored.
- `bones` — fnmatch patterns (`["thigh_fk.*", "shin_fk.*"]`). Rigify: work on **controls** (`*_fk`,
  `*_ik`, `torso`, `tail.*`), never on `DEF-`/`MCH-` bones — those are driven by constraints.
- `channels` — `location`, `rotation`, `scale`, `props` (custom properties such as `IK_FK`).
- `frames: [f0, f1]` — the keys inside are the selection; the keys just outside are its neighbours.
  Without it, ops that need neighbours use the first/last key as bookends.
- `backup: true` (default) — the first edit copies the action to `<action>__bak`; `op: restore` puts it back.
- `ops: [...]` chains several ops in one call (one backup, one report).

Values are in the curve's units: radians for rotations, metres for locations. Quaternion keys are
re-normalised after every op.

## Ops at a glance

| Op | Parameters | Does |
|---|---|---|
| `tween` | `t` (0.5), `mode` flat/linear | Keys at a fraction between the neighbours |
| `blend_neighbor` | `factor` −1..1 | Towards left (<0) / right (>0) neighbour |
| `blend_frame` | `frame`, `factor` | Towards the value at a reference frame |
| `blend_default` | `factor` | Towards rest (0, scale 1, quaternion identity) |
| `push_pull` | `factor` | Exaggerate (+) / flatten (−, −1 = straight line) vs the line between neighbours |
| `smooth` | `iterations`, `factor`, `cyclic` | Neighbour averaging |
| `ease` | `shape` in/out/inout, `power` | Keys placed on an ease curve between the neighbours |
| `scale` | `factor`, `pivot` average/left/right/rest/number | Scale values around a pivot |
| `time_offset` | `shift`, `cyclic` | Value at x := value at x − shift |
| `wave` | `amplitude`, `period`, `phase`, `kind` sine/noise, `seed` | Add a wave |
| `offset` | `delta` or `from_pose`, `blend` | Anim-offset layer with smooth falloff (quaternions multiplied in) |
| `overlap` | `chain`, `lag`, `mode` follow/delay, `gain`, `falloff`, `cyclic`, `step` | Follow-through on a chain |
| `match_cycle` | `period`, `mode` first/average | Exact loop closing key |
| `loop_window` | `min_len`, `crossfade`, `root`, `out` | Best looping window → new action |
| `resample` | `step` | Re-key every `step` frames |
| `clean` | `tolerance` | Remove keys the curve does not need |
| `interpolation` | `interpolation`, `easing`, `handle_type` | Key interpolation / handles |
| `restore` | — | Back to `<action>__bak` |

## Recipes

**Knee pops in a generated walk** (measured on the project cat: 8 pops, jitter 10.3° → 0 pops, 5.7°):

```python
run({"object": RIG, "action": "AN_walk", "ops": [
    {"op": "smooth", "bones": ["thigh_fk.*", "shin_fk.*", "foot_fk.*"], "channels": ["rotation"],
     "iterations": 3, "factor": 0.6, "cyclic": True}]})
```

Then run `motion_qa.py` again. Reach still over 95 %? The legs are too long for the stride: lower the
hips in the generator (`quadruped_walk_fk`) rather than smoothing further.

**Ears trail the head** (kiln: the ears take where the head was 3 frames before, ×2):

```python
run({"object": RIG, "action": "AN_idle", "op": "overlap", "chain": ["head", "ear.L"], "lag": 3, "gain": 2.0})
run({"object": RIG, "action": "AN_idle", "op": "overlap", "chain": ["head", "ear.R"], "lag": 3, "gain": 2.0})
```

The driver's rotation is carried through both bones' rest orientations, so bones with different rolls
follow correctly. A tail: `chain: ["tail.004", "tail.003", "tail.002", "tail.001"]`, `lag: 2`,
`falloff: 0.85` — each link a little later and a little less.

**Spread a pose change over a range** (AnimAide's Anim Offset): pose the control by script at frame F,
then

```python
run({"object": RIG, "action": "AN_walk", "op": "offset", "bones": ["torso"], "from_pose": F,
     "frames": [1, 121], "blend": 0})
```

`frames` + `blend` limit it to part of the clip with a smooth falloff on each side.

**Make a clip loop** — mocap, retargeted or generated:

```python
run({"object": RIG, "action": "AN_run_raw", "op": "loop_window", "root": "torso", "min_len": 16})
# → AN_run_raw_loop, keyed every frame, key P == key 0, horizontal root drift removed
```

## Rules

1. **Work on controls, measure on deform bones.** Edits go to the bones that carry keys; `motion_qa.py`
   reads the `DEF-` bones and the skin.
2. **One fix, one measure.** Re-run `motion_qa.py` after each op chain; keep the report numbers in
   `PROJECT.md` (before → after).
3. **A loop closes with a key equal to the first** (kiln rule 5): glTF plays the closing key. After any
   edit on a cycle, finish with `match_cycle`.
4. **Signs before values** (kiln rule 4): for `delta` offsets, try a small value and look at which way
   the bone moves before committing a large one.
5. **Do not polish forever.** Two or three op chains per clip; if the measures do not move, the problem
   is upstream (stride, hip height, rig, weights).
