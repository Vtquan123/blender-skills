# Video Motion Capture (MoCapAnything V2)

> Reference for: animation, rigging, blender-director
> Load when: a clip must follow a video frame by frame (an animal's gait, a jump, a specific performance) and the generators in `reference-driven-motion.md` cannot match it closely enough

[MoCapAnything V2](https://github.com/kehong-gong/MoCapAnything) (MIT) predicts the joint rotations of a reference skeleton from a single video. It works for animals as well as people. `production/scripts/blender/mocap_capture.py` runs it, imports the BVH and retargets it onto a project rig.

The user installs it in its own folder with its own Python environment (≈ 3 GB with weights and demo data). Nothing of it is bundled here, and the agent never downloads it without asking.

## When to Use

| Situation | Use |
|-----------|-----|
| Gait, jump, turn of a real animal, matched closely | Capture → retarget |
| Stylised or looping cycle, approximate look is enough | Generators (`reference-driven-motion.md`) — faster, no install |
| Mechanical / object motion | Generators (`hinge_open`, `ball_throw`, `vehicle_drive`) |
| A person | Needs a human rig preprocessed for MoCapAnything first (see Limits) |

## Reference Skeletons ("rigs")

The model predicts motion for a skeleton it knows (`run({"mode": "rigs"})`). The demo data (`zoo1030`) has 80 animals: Cat, Dog, Puppy, Fox, Horse, Deer, Lion, Bear, Elephant, Rat, Chicken, Eagle, Parrot, Pigeon, Crocodile, Trex, Raptor, Spider, Scorpion, Crab and others. It has no human.

- Pick the rig closest to the target character's anatomy. The video may show another animal: for example, eagle footage on `Parrot`, or a kitten on `Cat`.
- The rig names use 3ds Max Biped style (`Bip01_L_Thigh`, `Bip01_R_HorseLink`, `BN_Tail_01`) and are in metres, Y-up.

## Workflow

1. **Probe:** `run({"mode": "probe"})` returns `available`, `rigs`, `torch`, `cuda` and `mps`. If it is not available, give the user the result's `install` line and stay on the generators.
2. **Source check:** the same rules as any motion source apply:
   - one subject, whole body visible, static camera;
   - side view for gaits;
   - at most ~20 s (the model keeps 301 frames at 15 fps).
   Trim with `start` / `duration`.
3. **Capture:**
   ```python
   run({"mode": "capture", "video": src, "rig": "Cat", "project_dir": proj,
        "start": 1.0, "duration": 4.0, "wait": False})
   ```
   - The capture runs in MoCapAnything's environment, in a separate process.
   - With `wait: False` the call returns at once. Poll `run({"mode": "status", "out_dir": ...})` until `state: done`.
   - Output goes to `<project>/working/mocap/<clip>/`: `<clip>_bvh.bvh` (rig skeleton, clip frame rate), `<clip>_rot6d.npy` and `<clip>_positions.npy`.
   - Optional: `preview: true` adds a skeleton comparison video. `export_glb: true` adds the rig's own skinned animal as GLB.
4. **Import:** `run({"mode": "import", "bvh": ..., "name": "cat_walk"})` creates armature `MC_<name>` in collection `MOCAP`. Keys are scaled to the scene frame rate.
5. **Map bones:**
   - `run({"mode": "bones", "source": "MC_cat_walk", "target": "<rig>"})` returns both hierarchies and `suggested_map` (`{target: source}`).
   - The suggestion matches by role and side: spine, neck, head, tail, thigh, shin, horselink, foot, toe, clavicle, upper arm, forearm, hand, wing, jaw, ear. Chains of different length (spine, tail, neck) are resampled.
   - Review it: on a Rigify rig it maps FK controls (`thigh_fk.L`, `tail`, `neck`, `head`). Helper bones (MCH/ORG/IK/tweak/root/torso) and constrained bones are never targets.
   - Edit or extend the map where the anatomy differs, for example a 4-bone animal leg mapped onto a 3-bone rig leg (leave the horselink out or map it onto the foot).
6. **Retarget:**
   ```python
   run({"mode": "retarget", "source": "MC_cat_walk", "target": "RIG_Cat", "bone_map": m,
        "action": "AN_Walk_mocap", "frame_start": 1})
   ```
   - Each mapped bone gets the source bone's world-space rotation change from rest, applied to its own rest orientation.
   - Bone names, rolls, scale and facing can all differ. The facing is fitted automatically (`yaw: "auto"`, or degrees).
   - Rigify `IK_FK` properties are keyed to FK (`ikfk`, default 1.0) when FK controls are mapped.
   - `error_deg` measures how far each target bone ended up from the source's rotation (mean, max, worst bones). It stays near 0 for free bones. A large value means locked axes, a constraint, or rest poses that differ.
7. **Clean up and check:**
   - Use the clip like any other: `anim_curves.py` (`smooth` against jitter, `loop_window` for a loop), then `motion_qa.py` (foot slide, joint pops, floor), then the preview against the source (`reference-driven-motion.md` §4).
   - The output is in place (no root trajectory). Add root motion with the preview `root_velocity`, or in the engine.

## Operational Notes

- **Speed:** the upstream code is written for CUDA; the runner redirects it to Apple's GPU (MPS) or the CPU. MPS gives the same result as the CPU (max difference 1e-5). Background removal and DINOv2 take most of the time, so trim the clip and keep `max_side` at 720. Measured on an M1 Pro, demo cat clip:
  - 2 s at 15 fps: 30 s on MPS, 66 s on CPU (about 20 s of that is model loading);
  - full 10 s 1080p clip: about 7 min on CPU.
- **Rotations vs positions:** the model predicts joint positions and joint rotations with two heads. The BVH carries the rotations. Their forward kinematics differs from the predicted positions by roughly 15–20 % of the skeleton size on the demo clip, and the body orientation can drift by up to about 15°. Check the retargeted clip against the source video before polishing.
- **Bone map rules:**
  - When one source bone feeds several target bones (a single `Finger0` onto four Rigify toes), only unconstrained target bones take it, and they follow it rigidly.
  - Additive Copy Rotation chains (the Rigify tail) are corrected iteratively.
  - Demo cat onto the Rigify cat metarig: 61 bones mapped, max error 0.04°.
- **Rest poses:** retargeting transfers rotation changes from rest. A source rig standing on four legs and a target in the same stance match well. A T-pose biped against an A-pose biped needs the arms mapped and checked (`error_deg`, a visual check) or the target's rest adjusted.
- **Proportions:** rotations are transferred, not positions. Short-legged targets can slide or hover; fix contacts with `motion_qa.py` and curve polish.
- **Delete the source armature** (`MC_*`) before export, or keep it in `MOCAP` excluded from the export collections.

## Limits

- **Humans and project characters as rigs:** MoCapAnything can preprocess a custom rigged FBX (base plus at least one motion) into a new reference skeleton (`examples/custom_rig`). That pipeline needs CUDA and Blender; it is not wrapped here. Run it on a CUDA machine, then point `data_dir` at its output.
- **Licences:**
  - The code and the released weights are MIT.
  - The background remover it downloads (briaai/RMBG-1.4) is **non-commercial**.
  - The zoo1030 characters come from Truebones Zoo (no redistribution).
  - Ask the user before a captured clip ships in a commercial product.

## Constraints

### MUST DO
- Probe first; tell the user what is missing instead of installing it
- Trim to the motion that matters before capture
- Review the bone map; report `error_deg.worst` to the user
- Run `motion_qa.py` on the retargeted clip

### MUST NOT DO
- Download MoCapAnything, its weights or data without the user's go-ahead (several GB, third-party licences)
- Retarget onto Rigify DEF/ORG/MCH bones (they are driven; keys there do nothing)
- Ship the `MC_*` source armature or the zoo meshes in a deliverable
