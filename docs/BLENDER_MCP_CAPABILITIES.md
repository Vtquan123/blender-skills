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

## End-to-End Run on a Real Asset (Phase 7)

`calicocat_3d.glb` (Tripo, 1,939,832 triangles, 0.25 m) → animated web GLB through the official MCP, every stage a repository script run with `runpy`. Spec = presets `web-desktop` + `cat` (test values), clips idle + walk.

| Stage | Result |
|-------|--------|
| Intake G0 | pass, 13.6 s |
| Rig fit (paw fit, prune 174 → 33 bones, traced tail, overrides) | joints inside the limbs; user approval pending |
| Deform mesh (QuadriFlow + joint loops) | 11,924 quads / 23,840 tris, manifold, 1 component, 27–35 s |
| G4a joint loops | all 20 joints meet their rule (needs_review) |
| G2 geometry | silhouette p95 0.21 mm; max 13 mm (whiskers lost) |
| UV + bake (basecolor, normal, roughness, metallic, AO, ORM, 2048 px, Metal GPU) | G3 needs_review; 5–20 s per call after the first (kernel compile > 80 s) |
| Rigify generate + weights G4b | 45 DEF bones, 4 influences, pass |
| ROM G4c | 10 joint tests recorded (needs_review) |
| Animation G5 | idle 4 s + walk 1 s (`quadruped_walk_fk`), seamless loops, foot slide 1.3 mm with root motion 0.05 m/s |
| Export + optimize | 12.9 MB master → 0.94 MB (meshopt + WebP) |
| G6 validator | 0 errors |
| G7 three.js (headless Chrome) | 1 draw call, 162 ms load, max vertex deviation idle 2.4 mm / walk 0.3 mm vs Blender |
| Preview render | EEVEE 1280×720, 180 frames in ≈ 110 s (3 MCP calls), PNG → MP4 with ffmpeg |
| G8 | input checksums unchanged; fails until the user approves G1/G4a/G4c and sets thresholds |

Problems found and fixed in the scripts during the run: Rigify rig displaced (unapplied metarig location), twisted control rolls, disjoint Rigify chains after moves, QuadriFlow rejecting sub-0.1 mm edges, faceted normal bake, B-Bones (15 mm Blender↔three.js deviation), empty extra glTF scene, missing tangents, ROM action exported as a clip, IK limbs not moving in the ROM test. See `CHANGELOG.md` 1.4.0.

| MCP behaviour | Handling |
|---------------|----------|
| `bpy.ops.screen.screenshot_area` from code writes a 1×1 PNG | Use `render.opengl` + `save_render` (`references/mcp-tools.md → Images and Long Calls`) |
| Calls over ~80 s time out on the client while Blender continues | Poll for output files; do not resend |
| Viewport screenshot can be one frame stale after `frame_set` | Redraw (`wm.redraw_timer`) before the screenshot |

## Not Yet Verified

| Item | Why |
|------|-----|
| KTX2 texture compression | KTX-Software `ktx` CLI not installed on the test machines (`optimize.mjs` stops with a clear message) |
| Draco output | Not exercised; meshopt is the default |
| Production Mode on dog, parrot (bird template + wing decision) and the leaping cat (non-neutral pose) | Only the calico cat ran end to end; parrot/leaping-cat decisions are open |
| Playwright's own Chromium on the user's machine | Download blocked in the test VM; G7 ran with installed Chrome (`--chrome`) |
| `*_for_cli` tools | Requires `BLENDER_PATH` |

## Re-running the Probe

Ask the agent: *"Run the Blender MCP capability probe from docs/BLENDER_MCP_CAPABILITIES.md in a temporary scene and update the table."* The probe must create a temporary scene, exercise each row, delete everything it created, and report the scene state afterwards.
