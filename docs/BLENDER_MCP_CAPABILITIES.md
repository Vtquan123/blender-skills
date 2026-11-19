# Blender MCP Capability Map

Which Blender operations the Universal 3D Production pipeline can drive through the **official Blender MCP server**, verified on a real session — not taken from documentation.

**Environment:** Blender 5.3.0 (macOS arm64), add-on `mcp` 1.0.3 (Blender Lab), Python 3.13.13, numpy 2.3.4, Cycles compute device METAL available.
**Date:** 2026-11-20. **Method:** probe operations in a temporary scene (`U3D_CAPABILITY_PROBE`), then delete it; repository scripts run from the local clone with `runpy`.

## Dedicated Tools

| Capability | Tool | Result |
|------------|------|--------|
| Scene inspection | `get_objects_summary` | ✅ collections, objects, active object, mode, camera |
| Object inspection | `get_object_detail_summary` | ✅ transforms, modifiers, constraints, materials, collections |
| File state | `get_blendfile_summary_path_info` | ✅ path, saved, dirty |
| Window layout | `get_screenshot_of_window_as_json` | ✅ areas, shading mode, selection |
| Viewport screenshot | `get_screenshot_of_area_as_image` (`VIEW_3D`) | ✅ PNG (used to review 4 source models) |
| API reference | `search_api_docs`, `get_python_api_docs` | ✅ e.g. full `bpy.ops.object.bake` signature |
| Background execution | `execute_blender_code_for_cli` | ⚠️ needs `BLENDER_PATH` in the MCP server environment (not set during the probe) |

## Operations via `execute_blender_code`

| Capability | Probe | Result |
|------------|-------|--------|
| File import | glTF, FBX, OBJ, USD, STL, PLY operators present; 4 GLB models (≈1.9–2.0 M triangles, 58–64 MB) imported in ≈3 s each | ✅ |
| Mesh statistics | triangles, components, boundary/non-manifold edges, weld check on a bmesh copy | ✅ |
| Geometry operations | Decimate modifier apply; QuadriFlow remesh (`FINISHED`, 288 faces) | ✅ |
| UV operations | `uv.smart_project` | ✅ |
| Material operations | Principled material create/assign | ✅ |
| Texture baking | Cycles AO bake to image (CPU by default; METAL available) | ✅ |
| Armature operations | Armature + bones in edit mode; `parent_set(ARMATURE_AUTO)` → 2 vertex groups | ✅ |
| Animation | Pose-bone keyframes; slotted action with slot assigned (`OBPROBE_rig`) | ✅ |
| GLB export | `export_scene.gltf` GLB with animation; options `export_meshopt_compression_enable`, `export_draco_mesh_compression_enable`, `export_anim_slide_to_zero` present | ✅ |
| Rigify | Add-on available (enabled on demand by `rig_fit.py`) | ✅ |
| Repository script | `production/scripts/blender/intake.py` via `runpy` on `calicocat_3d.glb`: 1,939,832 triangles, 149 raw → 1 welded component, G0 pass, temp scene removed, 13.3 s | ✅ |

## Headless Verification (CI-style)

The same Blender scripts were run end to end with the `bpy` 5.3.0 wheel (no UI) on synthetic assets: intake, joint analysis, deform mesh + joint-loop cuts, metrics, bake (basecolor/normal/roughness/metallic/AO + ORM pack), auto weights, ROM test, motion generator, anim check, GLB export, vertex sampling, Rigify generate (basic human, custom bird), hinge rig. Node tools (glTF-Transform 4.5.1, glTF-Validator 2.0.0-dev.3.10, three.js 0.187 in headless Chrome) passed G6/G7 with 1.4 mm max vertex deviation between Blender and three.js.

## Not Yet Verified

| Item | Why |
|------|-----|
| KTX2 texture compression | KTX-Software `ktx` CLI not installed on the test machines (`optimize.mjs` stops with a clear message) |
| Draco output | Not exercised; meshopt is the default |
| Full Production Mode on the 2 M-triangle models (remesh, bake, rig) | Next phase (integration test on representative assets) |
| `*_for_cli` tools | Requires `BLENDER_PATH` |

## Re-running the Probe

Ask the agent: *"Run the Blender MCP capability probe from docs/BLENDER_MCP_CAPABILITIES.md in a temporary scene and update the table."* The probe must create a temporary scene, exercise each row, delete everything it created, and report the scene state afterwards.
