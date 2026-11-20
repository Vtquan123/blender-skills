# Reference-Driven Motion

> Reference for: animation, blender-director
> Load when: a clip must imitate a user-supplied video, GIF, image sequence or description

Goal: the clip **looks like** the source — timing, key poses, character of motion. It is not motion capture and does not copy every frame. No GPU, no mocap model, no body-model licence needed.

## 1. Source Request (when a clip has no source)

When `output-spec.yaml → animation.clips[].source.type` is `none`, pause the animation stage (other stages continue) and send the user:

```markdown
## Animation source needed: <clip>
- Purpose: <idle / walk / open lid …>, target length ~<s> s, loop: <yes/no>
- Accepted: video (MP4/MOV), GIF, image sequence, an existing motion file (FBX/BVH/GLB), or a written description
- Good source: one subject, whole body visible, static camera, good light;
  gaits filmed from the side with ≥ 2 full cycles; for loops, start and end look alike
- Only send material you have the right to use
```

Store the reply in `projects/<name>/input/motion/` and set `source.status: provided`.

If the source is unusable (subject occluded, camera shaking, too short), say exactly what is wrong and ask for another one instead of building a weak clip.

## 2. Read the Source → motion-brief.yaml

1. `production/scripts/motion/extract_frames.py` — ffmpeg to frames at native fps (GIF frame delays preserved), optional trim; builds `reports/<clip>_source_sheet.png` (grid of frames with timestamps).
2. Look at the sheet and write `motion-brief.yaml` (schema in `../../references/production-spec.md`): cycle length, key poses with times, amplitudes (stride, bounce, tail/ear angles, lid angle), rhythm (even, snappy, bouncy), loop points, tolerance.
3. Show the brief to the user; they may edit numbers.

## 3. Build with Motion Generators

`production/scripts/motion/generators.py` — parameterised generators driven by the brief:

| Family | Generators | Main parameters |
|--------|-----------|-----------------|
| Biped | `biped_walk`, `biped_idle` | cycle_s, stride, lift, arm_swing_deg, breath_deg, sway |
| Quadruped | `quadruped_walk` (lateral sequence), `quadruped_trot`, `tail_wag` | cycle_s, stride, lift, duty, phases, bounce, body_pitch_deg, head_bob_deg, amp_deg |
| Bird | `wing_flap`, `head_tilt`, `perch_bob` | flaps_per_cycle, amp_deg, tilt_deg, turn_deg, bob |
| Key poses | `pose_keys` — sit, jump, gestures and anything without a cyclic generator | `keys: [{t, bones: {name: {rot, loc}}}]` |
| Object | `hinge_open`, `turntable`, `bounce_in` | angle_deg, duration_s, easing, bounces |
| Secondary | `secondary` chains (follow-through on tail, ears, feathers, pages) | amp_deg, delay_frames, axis |

Generators key the **control** bones (IK feet for legs; FK chains for tail/neck). The glTF exporter samples the evaluated pose, so deform bones receive the motion (`bake_deform: true` bakes explicitly).

- **Layering:** `append: true` keys into an existing action, so one clip can combine generators (idle = `biped_idle` on chest/torso + `tail_wag` + `head_tilt`). Use different bones per layer.
- **Axes are the control's LOCAL axes.** Read them from the rig before keying (`(rig.matrix_world @ pose_bone.matrix).to_3x3()` columns). Rigify torso/chest/IK controls are world-aligned, so a rig facing +X uses `forward_axis: X`, `forward_negative: false`, `pitch_axis: Y`, `breath_axis: Y`; neck/head/tail controls bend around their X axis (lateral after `rig_fit.py` restores rolls).
- **Scale parameters to the asset:** stride and lift are metres — a 25 cm kitten walk used stride 0.03, lift 0.012, bounce 0.002.
- Rigify limbs must be in IK (`IK_FK = 0`, the default) for foot/hand IK keys to drive the legs.

## 4. Compare and Adjust

1. Render the model at the brief's key-pose times from the source's camera angle → `reports/<clip>_model_sheet.png`.
2. Build side-by-side sheet source ↔ model.
3. List differences (e.g. stride shorter, tail lags less) → adjust brief params → rebuild. Up to 3 automatic rounds.
4. The user approves similarity (gate G5 `similarity: approved`).

## 5. Optional: Precise Capture

For complex human motion that must match closely (dance, sport), a mocap path can be added later (monocular video mocap or a mocap service, then retarget). It needs a GPU or an external account and its own licence review; it is not part of the default pipeline.
