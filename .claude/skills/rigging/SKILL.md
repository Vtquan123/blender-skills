---
name: rigging
description: Production rigging in Blender with armatures, IK/FK, constraints, weight painting, mechanical rigs, facial rigs, and drivers. Use before animation on deforming assets via MCP.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.2.0"
  domain: blender
  role: specialist
  triggers: rig, rigging, armature, bone, IK, FK, weight paint, constraint, facial rig, driver, Rigify, metarig, twist bone, rigid part, hinge
  related-skills: animation, character-artist, blender-modeler, deformation-prep, web-export
---

# Rigging

Functional rigs supporting intended motion. Clean deformation. Engine-compatible bone hierarchies.

## When to Use

- Character/creature deformation rigs
- Mechanical constraint rigs
- Facial expression rigs
- Prop rigs (doors, vehicles, weapons)
- Before any animation work

## Existing High-Detail Meshes (Production Mode)

Do not rig a scanned, sculpted or AI-generated mesh directly. Run `deformation-prep` first: joint analysis, region strategy (skin / rigid part / free chain), deform mesh with joint loops, then the rig and ROM test defined there. Category templates (Rigify Human, Wolf, Cat; custom bird; hinge rigs for objects) are in `../deformation-prep/references/category-rigs.md`.

For web targets: linear blend skinning, 4 influences per vertex, twist bones on long limbs, deform bones only in the export — see `../web-export/references/web-runtime-limits.md`.

## Workflow

```
Skeleton Design → Bone Placement → Hierarchy → Constraints/IK
    → Weight Painting → Deformation Test → Export Prep
```

## Armature Naming

Prefix: `ARM_[AssetName]`
Bones: `[side]_[region]_[name]` — e.g., `L_arm_upper`, `spine_01`, `jaw`

## Bone Hierarchy

```
ARM_Character
├── root
├── spine_01 → spine_02 → spine_03
│   ├── L_clavicle → L_arm_upper → L_arm_lower → L_hand
│   └── R_clavicle → R_arm_upper → R_arm_lower → R_hand
├── L_leg_upper → L_leg_lower → L_foot → L_toe
└── R_leg_upper → R_leg_lower → R_foot → R_toe
```

## IK vs FK

| Use IK | Use FK |
|--------|--------|
| Legs (ground contact) | Spine (flexible arc) |
| Arms (hand placement) | Shoulder overlap |
| Feet planting | Finger detail |
| Mechanical reach | Whip/tail motion |

Standard: IK legs, FK spine; switchable arms for game characters.

## Constraints

| Constraint | Use |
|------------|-----|
| IK | Limb positioning |
| Copy Rotation | Mechanical sync |
| Limit Rotation | Joint ranges |
| Stretch To | Tentacles, pistons |
| Child Of | Weapon attach/detach |
| Shrinkwrap | Ground contact (use carefully) |

## Weight Painting

```
1. Automatic weights as starting point only
2. Clean weights: normalize per vertex (max 4 influences)
3. Smooth problematic areas (shoulders, hips)
4. Test extreme poses: T-pose, arms up, crouch, jaw open
5. Gradient weights at joints — no hard 1.0/0.0 at bend center
```

## Mechanical Rigs

- Empty objects as control handles
- Constraints instead of weight painting
- Hinge limits match real joint ranges
- Parent hierarchy mirrors mechanical assembly

## Facial Rigs

| Approach | Use Case |
|----------|----------|
| Bone-based | Game characters |
| Shape keys | Cinematics, dialog |
| Hybrid | Hero game characters |

Minimum game facial: jaw open, blink L/R, brow up/down.

## Drivers

- Gear rotation sync
- Auto eyelid blink
- Weapon reload mechanism
- Procedural antenna/wire motion

## MCP Integration

1. Create armature via MCP
2. Parent mesh with automatic weights via MCP
3. Query bone count and hierarchy
4. Validate weight groups via MCP if supported
5. Export armature with mesh via export-pipeline
6. Before any engine export: `game_skeleton.py` audit (roots, B-Bones, scale, dead bones, density); `mode=export_rig` builds a deform-only skeleton with one root and baked clips (`references/game-ready-skeleton.md`)

## Deformation Test Poses

- T-pose / A-pose (bind pose)
- Arms fully raised
- Deep crouch
- Neck rotation extremes
- Jaw wide open (characters)

## Constraints

### MUST DO
- Rig after retopology complete
- Name bones consistently
- Limit bone influences to 4 per vertex (game engines)
- Test deformation at extremes before animation
- Document control scheme for animators

### MUST NOT DO
- Auto weights without cleanup (hero assets)
- Scale bones in bind pose
- Rig before topology validated
- Skip IK pole targets on limbs
- Mix multiple root bones without documentation (a Rigify rig exports 16 skeleton roots: ship the export rig)
- Ship B-Bones or scaled deform bones to an engine

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Humanoid rig | `references/humanoid-rig.md` | Characters |
| Mechanical rig | `references/mechanical-rig.md` | Props, vehicles |
| Existing mesh → animatable | `../deformation-prep/SKILL.md` | Source is a scan/sculpt/AI mesh |
| Category templates | `../deformation-prep/references/category-rigs.md` | Human, dog, cat, parrot, book, box, chair, table |
| ROM test | `../deformation-prep/references/rom-test.md` | Before animation |
| Game-ready skeleton (single hierarchy, root, baked clips) | `references/game-ready-skeleton.md` | Unity / Unreal / Godot / glTF export of a Rigify or custom rig |
| Weight problems pinned by the user (weights view, notes → vertex indices) | `../qa-review/references/review-notes.md` | Skin feedback on a spot |
