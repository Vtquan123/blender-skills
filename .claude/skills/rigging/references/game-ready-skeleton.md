# Game-Ready Skeleton — One Hierarchy, One Root, No Scale

> `production/scripts/blender/game_skeleton.py`. The problem set is the one GameRig
> (Arminando/GameRig) solves inside Rigify; this is an independent, rig-agnostic implementation:
> audit any rig, then build a separate deform-only **export rig** that follows it and carries baked clips.

## Why a Rigify rig is not an engine skeleton

| Rigify output | Engine consequence |
|---|---|
| Deform bones under ORG/MCH bones (`DEF-thigh.L` → `ORG-pelvis.L`, `DEF-ear.L` → `ORG-ear.L`) | Measured on the project cat: the glTF skin had **16 root joints**; FBX deform-only re-parents unpredictably; Unreal refuses several roots |
| `DEF-spine` under the non-deform `root` | The real root never ships, root motion is lost or doubled |
| B-Bone segments on DEF bones | Blender bends them, no engine does (also breaks Blender↔three.js parity) |
| Stretch To / scaled deform bones | Engines handle joint scale differently (Unity/Unreal segment scale compensation); limbs swell |
| Hundreds of helper bones | Only the ~50 DEF bones matter; the rest is control machinery |

## Workflow

```
1. game_skeleton.py  mode=audit       → verdict: ready | export_rig | fix_first
2. (fix_first) weights / density      → skin_weights.py, prune bones, re-audit
3. game_skeleton.py  mode=export_rig  actions=["AN_*"] mesh_mode=copy
4. export_glb.py / FBX on the export rig + its meshes (clip_names renames "<clip>_game")
5. validate (G6/G7) on the exported file
```

The control rig stays as it is for animating. After a clip changes, re-run step 3 (it replaces the
export rig and its baked actions).

## What the audit checks

- **Roots**: deform bones whose nearest deform ancestor does not exist (should be exactly 1).
- **Non-deform parents**: deform bones hanging from ORG/MCH bones.
- **B-Bones**, **Stretch To / Maintain Volume** on deform bones.
- **Scale in clips**: deform-bone scale sampled over the given actions (> 2 % is a problem).
- **Weights**: vertices with > 4 deform influences, unweighted vertices, weights on non-deform bones,
  dead deform bones (move nothing).
- **Density** (kiln rule 26): one deform bone per ~20 vertices at most. A 160-bone Rigify human on a
  370-vertex figure left 107 bones influencing nothing and smeared the rest across 8–9 bones per vertex.

## What export_rig builds

- One armature `<rig>_game`: a `root` bone (following the control rig's own `root`, so root motion is
  kept) and every deform bone, renamed (`strip_def`: `DEF-thigh.L` → `thigh.L`; or a dict, e.g. to
  Mixamo/UE names), rest pose copied exactly (checked: < 0.01° / 0.01 mm).
- Hierarchy rebuilt from the rig: nearest deform ancestor, or the deform twin of an ORG ancestor
  (`DEF-thigh.L` → `ORG-pelvis.L` → `pelvis.L`); Rigify's reversed tail chains are handled (their ORG
  ancestors' twins are their own children, so the search climbs to the spine).
- No B-Bones, no constraints after baking, location + rotation only (`keep_scale` to keep scale).
- Clips baked per frame (linear keys, quaternion signs continuous) as `<clip>_game`.
- Meshes duplicated onto the export rig (`mesh_mode: copy`) with vertex groups renamed — the originals
  are untouched. `retarget` re-points the originals instead.
- **Parity** reported: bone heads and skin, control rig vs export rig, on sampled frames. Project cat:
  50 bones, 1 root, 0.000 mm bone heads, 0.006 mm skin; the exported GLB skeleton has 1 root joint.

## Rules

- Never hand-edit the export rig: it is generated. Change the control rig or the clips and rebuild.
- Bone names are the contract with the engine (retargeting, humanoid avatars, sockets): decide the
  `rename` map once per project and record it in `PROJECT.md`.
- Stretchy limbs: switch stretch off on the control rig before baking (Rigify `IK_Stretch` = 0) — the
  export rig drops scale, so a stretched limb would shorten the skin instead.
- Unity Humanoid / Unreal Mannequin retargeting need specific names and a T-/A-pose rest: rename to
  the target's names and check the rest pose before export (`unity-export`, `unreal-export`).
