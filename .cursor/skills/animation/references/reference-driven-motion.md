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
| Biped | `biped_walk`, `biped_idle`, `arm_gesture` | cycle_s, stride, arm_swing, bounce |
| Quadruped | `quadruped_walk` (lateral sequence), `quadruped_trot`, `sit`, `tail_wag` | cycle_s, stride, leg phase offsets, spine_flex, head_bob, tail amplitude/frequency |
| Bird | `wing_flap`, `head_tilt`, `perch_bob` | flap_hz, wing_amplitude_deg, tilt_deg |
| Object | `hinge_open`, `turntable`, `bounce_in` | angle_deg, duration_s, easing, bounces |
| Secondary | `follow_through` on chains (tail, ears, feathers, pages) | delay_frames, damping |

Generators key the **control** bones (IK feet for legs), then bake to deform bones at the spec fps. Rigs without IK controls get FK keys directly.

## 4. Compare and Adjust

1. Render the model at the brief's key-pose times from the source's camera angle → `reports/<clip>_model_sheet.png`.
2. Build side-by-side sheet source ↔ model.
3. List differences (e.g. stride shorter, tail lags less) → adjust brief params → rebuild. Up to 3 automatic rounds.
4. The user approves similarity (gate G5 `similarity: approved`).

## 5. Optional: Precise Capture

For complex human motion that must match closely (dance, sport), a mocap path can be added later (monocular video mocap or a mocap service, then retarget). It needs a GPU or an external account and its own licence review; it is not part of the default pipeline.
