# Blender MCP Tool Catalog

Reference for agents when a Blender MCP server is connected. The pack targets the **official Blender MCP server** (Blender Lab add-on `mcp`, Blender 5.1+). The community server `blender-mcp` (ahujasid) is still supported; see the mapping at the end.

**Always read the tool descriptors your client exposes before calling** — names and parameters can change between versions. Client UIs may prefix names (e.g. `Blender__execute_blender_code`).

Verified against add-on `mcp` 1.0.3 on Blender 5.3.0 (macOS, 2026-11-20). Live results: `docs/BLENDER_MCP_CAPABILITIES.md`.

## Official Server — Tools

### Interactive (running Blender with the add-on server on `localhost:9876`)

| Tool | Use for |
|------|---------|
| `execute_blender_code` | Run Python with full `bpy`. Assign a JSON-serialisable **dict** to `result` to return data (a non-dict is rejected). Main path for every operation. |
| `get_objects_summary` | Collection hierarchy + objects (name, type, parent, data, selection, visibility), active object, mode, camera |
| `get_object_detail_summary` | One object: transforms, parent/children, modifiers, constraints, materials, visibility, collections |
| `get_blendfile_summary_datablocks` | Data-block counts, active workspace, render engine |
| `get_blendfile_summary_path_info` | File path, saved/dirty state, age, backups — check **before** any step that opens or replaces the file |
| `get_blendfile_summary_missing_files` | Missing images/libraries/caches |
| `get_blendfile_summary_of_linked_libraries` | Linked library tree |
| `get_blendfile_summary_usage_guess` | Guessed use-cases of the file (0–100 scores) |
| `get_screenshot_of_area_as_image` | PNG of one area — `area_ui_type: "VIEW_3D"` is the viewport screenshot |
| `get_screenshot_of_window_as_image` | PNG of the whole Blender window |
| `get_screenshot_of_window_as_json` | Window layout, areas, active object, selection (cheap, no image) |
| `jump_to_view3d_object_by_name` / `jump_to_view3d_object_data_by_name` | Frame an object in the viewport before a screenshot |
| `jump_to_tab_by_name` / `jump_to_tab_by_space_type` | Switch workspace |
| `render_thumbnail_to_path` | Quick low-quality render to a file |
| `render_viewport_to_path` | Render the scene with current settings to a file |
| `get_python_api_docs` | API docs for an identifier (`bpy.ops.object.bake`, `bpy.types.*`) |
| `search_api_docs` / `search_manual_docs` | Full-text search of the bundled API reference / user manual |

### Background (`*_for_cli`)

`execute_blender_code_for_cli(blend_file, code)` and `get_blendfile_summary_*_for_cli(blend_file)` open a `.blend` in a separate `blender --background` process. The MCP server process must know the executable: set `BLENDER_PATH` (macOS: `/Applications/Blender.app/Contents/MacOS/Blender`) in that server's environment, otherwise the call fails with "Blender executable not found". Deferred responses are not supported in background mode. Use background mode for batch work that must not touch the user's open file.

## Agent Protocol

```
1. get_blendfile_summary_path_info  → is the open file unsaved/dirty? never discard user work
2. get_objects_summary              → real scene state, no assumptions
3. execute_blender_code             → one stage per call; return a dict in `result`
4. get_objects_summary / detail     → verify the stage changed what it should
5. jump_to_view3d_object_by_name + get_screenshot_of_area_as_image(VIEW_3D) → visual check
6. validation checklist / Production Mode gates before export
```

Work on existing assets in a **temporary scene** (or a copy file) so the user's scene is untouched; remove it afterwards (`production/scripts/blender/u3d_common.py → temp_scene`).

## Running Repository Scripts

Production scripts expose `run(args) -> dict`. With the repo on the same machine as Blender:

```python
import runpy
ns = runpy.run_path("<repo>/production/scripts/blender/intake.py")
result = ns["run"]({"source": "<project>/input/model.glb"})
```

Without a local clone, send `u3d_common.py` first (registers `sys.modules["u3d_common"]`), then the stage script text followed by `result = run({...})`.

## Common bpy Patterns

### Create Collection

```python
import bpy
col = bpy.data.collections.new("COL_Props")
bpy.context.scene.collection.children.link(col)
```

### Rename Object

```python
obj.name = "SM_Crate_01"
obj.data.name = "SM_Crate_01"
```

### Apply Transforms

```python
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
```

### Merge by Distance

```python
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.0001)
bpy.ops.object.mode_set(mode='OBJECT')
```

### Export (When No Export Tool)

```python
import bpy
bpy.ops.export_scene.fbx(
    filepath="//export/SM_Asset.fbx",   # '//' = relative to the .blend; use an absolute project path otherwise
    use_selection=True,
    apply_scale_options='FBX_SCALE_ALL',
    axis_forward='-Z',
    axis_up='Y',
    object_types={'MESH', 'ARMATURE'},
    bake_anim=False
)
```

Adjust axis settings per target engine — see `export-pipeline`. For GLB/web use `web-export` (`production/scripts/blender/export_glb.py`).

## Community Server Mapping (ahujasid `blender-mcp`)

| Purpose | Official server | Community server |
|---------|-----------------|------------------|
| Run Python | `execute_blender_code` (dict in `result`) | `execute_blender_code` |
| Scene overview | `get_objects_summary` | `get_scene_info` |
| Object details | `get_object_detail_summary` | `get_object_info` |
| Viewport screenshot | `get_screenshot_of_area_as_image` (`VIEW_3D`) | `get_viewport_screenshot` |
| Poly Haven / Hyper3D / Hunyuan3D | not available | available when enabled in the add-on |

Both servers listen on `localhost:9876` by default — run only one Blender add-on server at a time.

## Error Recovery

| Error | Action |
|-------|--------|
| Cannot connect to Blender at `localhost:9876` | Open Blender; enable the add-on; enable *Online Access* in Preferences → System (the official add-on refuses to start without it) |
| "Blender executable not found" on `*_for_cli` | Set `BLENDER_PATH` for the MCP server process |
| `result` must be a dict | Wrap the return value: `result = {"value": ...}` |
| Timeout on heavy work | Split into one stage per call; checkpoint between calls |
| Object not found | Re-query `get_objects_summary`; verify names |
| Code execution error | Read the traceback; fix; retry (max 3) |

Sources: Blender Lab MCP server (https://www.blender.org/lab/mcp-server/), tool list https://projects.blender.org/lab/blender_mcp, community server https://github.com/ahujasid/blender-mcp
