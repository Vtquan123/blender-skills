# Intake Metrics and Heuristics

> Reference for: asset-intake
> Load when: measuring a source asset or interpreting an input-spec

## Import Settings

| Format | Operator | Notes |
|--------|----------|-------|
| GLB / glTF | `bpy.ops.import_scene.gltf` | Splits vertices on UV seams and hard normals; always run the weld check |
| FBX | `bpy.ops.import_scene.fbx` | Check unit scale (cm vs m) and `global_scale` |
| OBJ | `bpy.ops.wm.obj_import` | No rig/animation; materials via MTL |
| USD | `bpy.ops.wm.usd_import` | Check meters-per-unit |
| STL / PLY | `bpy.ops.wm.stl_import` / `bpy.ops.wm.ply_import` | Usually no UV, no materials |
| .blend | `bpy.data.libraries.load` (append into temp scene) | Never open over the user's file |

Import into `bpy.data.scenes.new("INTAKE_<name>")` and switch the window to it; switch back and delete it at the end.

## UV-Seam Split (common with GLB)

Symptom: hundreds of components and tens of thousands of boundary edges on a mesh that looks closed.
Check on a bmesh copy:

```python
bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
# count components and boundary edges on bm; do not write back during intake
```

Observed on four Tripo-generated GLBs (≈1.9–2.0 M triangles each): one of them imported as 116 components with 38,137 boundary edges; after the weld all four were 1 component with ≤ 2 boundary edges. Intake records `issues: [split_on_uv_seams]`; the geometry stage welds for real (UVs are per-loop and survive the weld).

## Category Hint

| Signal | Suggests |
|--------|----------|
| Existing armature with many bones | creature / character |
| Name tokens (`cat`, `dog`, `parrot`, `book`, `chair`…) | matching preset |
| One welded component, organic curvature, ≥ 4 limb-like protrusions | quadruped / biped |
| Several rigid components with coplanar faces | articulated or static object |

Always confirm with the user; the category selects `production/presets/categories/<category>.yaml`.

## Orientation and Scale

- Forward axis guess: direction of the head/front feature from screenshots + bbox asymmetry; confirm visually.
- Real size: from the user or the category preset's `typical_size_m`; record the scale factor needed. Rigify assumes 1 unit = 1 metre.

## Pose Hint

| Observation | `pose_hint` |
|-------------|-------------|
| Limbs roughly vertical, feet on one plane, left/right symmetric | `neutral_standing` |
| Limbs extended forward/back, feet off ground plane | `action_pose` (e.g. leap) |
| Wings/limbs fused to body (no gap between limb and torso surface) | `fused_limbs` |

`action_pose` and `fused_limbs` must be raised to the user at G1 (options: rig as-is, re-pose, or supply another asset).

## Screenshots

Material preview, overlays off, framed on the object: front, side, 3/4. Use the MCP area-screenshot tool after setting the view via `execute_blender_code`.

## Gate G0 JSON

```json
{"gate": "G0", "status": "pass", "metrics": {"triangles": 1939832, "components_raw": 116, "components_welded": 1, "boundary_edges_welded": 0, "missing_images": 0}, "notes": ["split_on_uv_seams"]}
```

Fail G0 only when the file cannot be imported or images are missing; everything else is information for planning.
