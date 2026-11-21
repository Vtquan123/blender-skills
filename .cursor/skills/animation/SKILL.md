---
name: animation
description: Game-ready animation in Blender including walk/run/idle cycles, combat, mechanical animation, camera animation, constraints, Graph Editor, and NLA workflows via MCP.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.2.0"
  domain: blender
  role: specialist
  triggers: animation, animate, walk cycle, run cycle, idle, combat, NLA, graph editor, keyframe, animate like this video, imitate GIF, motion brief, animation source
  related-skills: rigging, blender-modeler, export-pipeline, deformation-prep, web-export
---

# Animation

Game-ready motion with clean keyframes. Readable silhouettes in motion. Engine-compatible export.

## When to Use

- Character locomotion (walk, run, idle)
- Combat animations
- Mechanical/prop animation
- Camera animation
- Object animation with constraints
- Clips that imitate a user-supplied video/GIF/description (Production Mode)

## Reference-Driven Clips (Production Mode)

When a clip must look like a source the user provides, follow `references/reference-driven-motion.md`:
request the source if missing → frame sheet → `motion-brief.yaml` → parameterised generators → bake to deform bones → side-by-side compare → user approves (gate G5). The goal is a similar look and timing, not frame-exact capture.

For web delivery: one action per clip named as in the spec, bake constraints/IK to deform bones, then `web-export` resamples losslessly.

## Workflow

```
Reference → Blocking → Breakdown → Splining → Polish
    → Cycle Validation → NLA Strip → Export
```

## Locomotion Cycles

| Cycle | Key Poses | Frames (30fps) |
|-------|-----------|----------------|
| Walk | Contact, Down, Pass, Up × 2 | 24–32 |
| Run | Contact, Drive, Flight, Recovery | 16–24 |
| Idle | Breathe, weight shift, blink | 60–120 loop |

Naming: `AN_[Char]_[Action]_[Variant]`

## Animation Principles (Applied)

1. **Timing** — Weight through spacing
2. **Arcs** — Natural limb paths
3. **Overlap** — Secondary motion offset
4. **Anticipation** — Wind-up before action
5. **Exaggeration** — Style-dependent (see style skills)

## Mechanical Animation

- Use constraints over bone deformation
- Hinge: Limit Rotation constraint
- Pistons: Stretch-to or Copy Location
- Gears: Driver for synchronized rotation
- Doors: Empty pivot + rotation keyframes

## Graph Editor Workflow

```
1. Block stepped keys (Constant interpolation)
2. Splining: Bezier with auto handles
3. Ease: Weighted handles for acceleration
4. Cycle: Copy first/last frame; verify loop seam
5. Clean: Remove redundant keys
```

Through the MCP the same moves are script calls: `production/scripts/blender/anim_curves.py` — tween, blend to neighbour/frame/rest, push/pull, smooth, ease, scale, time offset, wave/noise, anim offset with falloff, chain overlap (follow-through), `match_cycle` (closing key = first key), `loop_window` (best looping window of a generated or mocap clip), clean, interpolation, backup/restore (`references/curve-polish.md`). Edit controls, then measure the clip with `motion_qa.py` (`references/motion-quality.md`).

## NLA for Game Export

```
1. Action created and named per convention
2. Push down to NLA strip
3. Strip set to Repeat for cycles
4. Single strip active for export
5. Scale: 1.0; no NLA time remapping unless intentional
```

## Camera Animation

- Smooth Bezier interpolation always
- Avoid sudden direction changes
- Match focal length to subject scale
- Camera shake: noise modifier on location (subtle)

## MCP Integration

1. Insert keyframes via MCP if supported
2. Query action names and frame ranges
3. Validate bone/object animation data exists pre-export
4. Set frame range via MCP
5. Export animation with rig via export-pipeline
6. Polish keys with `anim_curves.py`; measure every clip with `motion_qa.py` (reach, joint pops, jitter, skin under floor, seam, closing key) before showing it
7. Game engines: bake clips onto the export rig (`game_skeleton.py mode=export_rig`, `../rigging/references/game-ready-skeleton.md`)

## Game-Ready Requirements

- [ ] Root motion decision documented (in-place vs root motion)
- [ ] Loop seam invisible (walk/idle/run)
- [ ] No bone scale keyframes (engine issues)
- [ ] Animation length matches engine state machine
- [ ] Facial animation on separate action layer if needed
- [ ] Frame rate: 30fps default (confirm project spec)

## Constraints

### MUST DO
- Reference video for locomotion
- Block in stepped mode before splining
- Name actions `AN_` prefix
- Test cycle loop before export
- Match animation style to art direction

### MUST NOT DO
- Linear interpolation on organic motion
- Scale keyframes on rig bones
- Over-animate idle (subtle is better)
- Export without action assigned to NLA
- Skip root motion documentation

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Walk cycle breakdown | `references/walk-cycle.md` | Locomotion |
| Combat timing | `references/combat-animation.md` | Action games |
| Reference-driven motion (video/GIF/description) | `references/reference-driven-motion.md` | Clip must imitate a user source |
| Web runtime limits | `../web-export/references/web-runtime-limits.md` | Clips for browsers |
| Curve polish through the MCP (AnimAide-style ops) | `references/curve-polish.md` | Fixing pops, overlap, offsets, loops |
| Motion quality measures and fixes | `references/motion-quality.md` | Every clip before review (G5) |
