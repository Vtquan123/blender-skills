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
| Quadruped | `quadruped_walk_fk` (lateral sequence, planar two-bone IK on FK controls — default for Rigify quadrupeds), `quadruped_walk` (IK controls), `quadruped_trot`, `tail_wag` | cycle_s, stride, lift, duty, phases, bounce, body_pitch_deg, head_bob_deg, paw_curl_deg, amp_deg; `quadruped_walk_fk` also: cycles, lift_front/lift_hind, paw_curl_front/paw_curl_hind, swing_lift_peak[_front/_hind] |
| Slow layers | `chain_curve` — envelope keys over the whole clip (tail up → lowered → up, head turns) plus per-step oscillations, keyed into one rotation per bone per frame | `keys: [{t, rot: {bone: [x, y, z] deg}}]`, `osc: [{bones, axis, amp_deg, cycles, phase, phase_step}]` |
| Bird | `wing_flap`, `head_tilt`, `perch_bob` | flaps_per_cycle, amp_deg, tilt_deg, turn_deg, bob |
| Key poses | `pose_keys` — sit, jump, gestures and anything without a cyclic generator | `keys: [{t, bones: {name: {rot, loc}}}]` |
| Object | `hinge_open`, `turntable`, `bounce_in` | angle_deg, duration_s, easing, bounces |
| Ball (`rigid_rig.py kind=ball`) | `ball_roll`, `ball_bounce` | speed, in_place, height, bounces, squash, stretch |
| Vehicle (`rigid_rig.py kind=vehicle`) | `vehicle_drive` | speed, steer_deg, bob_m, bob_hz, pitch_deg, lean_deg, in_place |
| Chains (`chain_rig.py`) | `wind_sway` — plants sway; with `axis: Z` and `phase_step` a travelling wave (snake, tentacle, flag) | amp_deg, sway_cycles, gust, taper, phase_step |
| Secondary | `secondary` chains (follow-through on tail, ears, feathers, pages) | amp_deg, delay_frames, axis |

Generators key the **control** bones (IK feet for legs; FK chains for tail/neck). The glTF exporter samples the evaluated pose, so deform bones receive the motion (`bake_deform: true` bakes explicitly).

- **Layering:** `append: true` keys into an existing action, so one clip can combine generators (idle = `biped_idle` on chest/torso + `tail_wag` + `head_tilt`). Use different bones per layer.
- **Axes are the control's LOCAL axes.** Read them from the rig before keying (`(rig.matrix_world @ pose_bone.matrix).to_3x3()` columns). Rigify torso/chest/IK controls are world-aligned, so a rig facing +X uses `forward_axis: X`, `forward_negative: false`, `pitch_axis: Y`, `breath_axis: Y`; neck/head/tail controls bend around their X axis (lateral after `rig_fit.py` restores rolls).
- **Scale parameters to the asset:** stride and lift are metres — a 25 cm kitten walk used stride 0.03, lift 0.012, bounce 0.002.
- **Short or stylised legs: use `quadruped_walk_fk`.** Rigify IK on nearly straight stubby legs picks a different bend plane per frame — knees flip, paws twist, front legs cross (seen on the chibi cat). The FK generator solves each leg in its sagittal plane, keeps the rest bend side, keeps paws level (plus a small swing curl), and compensates body bounce/pitch so planted paws neither sink nor slide.
- **Key the IK/FK switches in every clip** (`ikfk: {"upper_arm_parent.L": 0.0, ...}` on any generator; `quadruped_walk_fk` keys FK = 1 itself). An unkeyed clip inherits the value the previous clip left, so Blender and the exported GLB disagree (16.7 mm on the cat's idle until keyed).
- **Long clips with slow changes** (a tail that lowers and rises again over a few seconds, a head turning toward the camera): set `cycle_s` to the whole clip and `cycles` to the number of leg cycles in it (a 4 s clip with `cycles: 4` = 1 s steps), then layer `chain_curve` with `append: true` on the tail and head. Leave `head` out of the walk's bones when `chain_curve` keys it.
- **Tail chains in Rigify copy rotation down the chain:** a rotation on `tail.001` bends the whole tail. Lower or raise a tail with the first control only (−18° turned the cat's upright tail near horizontal), add small corrections further down.
- **Front-leg swing shape from a video:** cats lift the paw early with the wrist flexed, then reach forward low — `swing_lift_peak_front` 0.35–0.45 with `paw_curl_front` 25–40°; hind legs flex at the hock and curl the paw (`paw_curl_hind` ~35°, peak 0.5).
- **`scapula_share`** (4-bone legs `[shoulder, upper, lower, paw]`) only works when the shoulder control carries the limb. Rigify's `shoulder.L/R` does not (the arm follows the torso through `FK_limb_follow`), so leave it at 0 on Rigify rigs.
- **Root motion for previews:** an in-place cycle moves planted paws back at `stride / (duty × cycle_s)` m/s; move the root at that speed (preview scene or engine) and pass the same value to `anim_check.py` as `root_velocity` so foot slide is measured correctly. Use `contact_eps` well below the lift (0.002–0.003 m for a 25 cm animal): with 0.01 m the frames where a curling paw starts to lift count as contact and inflate foot slide (7.5 mm instead of 1.6 mm on the cat walk).

## 4. Compare and Adjust

Render the clip for review with `production/scripts/blender/preview_render.py` (mode `setup`, then `render` in chunks of ~60 frames; in-place cycles get `root_velocity`; `background` and `ground_colors` can match the source's backdrop), encode the frames to MP4 and put it next to the source video — e.g. `ffmpeg -i source.gif -i model.mp4 -filter_complex "[0:v]trim=start=<walk start>,setpts=PTS-STARTPTS,fps=30,scale=-2:540[a];[a][1:v]hstack"`. Rebuild the preview scene after every regeneration of the action (setup copies the rig and its action). Check close-ups of the feet as well: crossing legs or twisting paws do not show in a wide shot.


1. Render the model at the brief's key-pose times from the source's camera angle → `reports/<clip>_model_sheet.png`.
2. Build side-by-side sheet source ↔ model.
3. List differences (e.g. stride shorter, tail lags less) → adjust brief params → rebuild. Up to 3 automatic rounds.
4. The user approves similarity (gate G5 `similarity: approved`).

## 5. Optional: Precise Capture

For complex human motion that must match closely (dance, sport), a mocap path can be added later (monocular video mocap or a mocap service, then retarget). It needs a GPU or an external account and its own licence review; it is not part of the default pipeline.
