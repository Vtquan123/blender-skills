# Material Maker Maps

> Reference for: materials, texture-workflow
> Load when: a tileable PBR material should come from a Material Maker `.ptex` graph, or procedural shading must survive a glTF/engine export

[Material Maker](https://github.com/RodZill4/material-maker) (MIT) is a node editor for procedural, tileable textures. `production/scripts/blender/material_maker.py` runs its command-line export and builds the Blender material. The app is installed by the user. Nothing of it is bundled here, and the agent never downloads it.

## When to Use

| Situation | Use |
|-----------|-----|
| Tileable surface (bricks, planks, tiles, rock, metal plates) for game/web | Material Maker → maps → UV material |
| Same surface with variations (row count, wear, hue) | One `.ptex`, several calls with `params` / `controls` |
| Unique, asset-specific detail (decals, baked AO from the high poly) | `texture-workflow` bake, not Material Maker |
| Blender-only render, no export | Shader-node procedurals are fine (`procedural-patterns.md`) |

## Workflow

1. **Probe:** `run({"mode": "probe"})` → `available`, `exe`, `examples`. If it is not available, give the user the install line from the result and continue with shader procedurals.
2. **Pick a graph:** an example name (`run({"mode": "list"})`, e.g. `bricks`, `wood`, `rock`, `tiles`, `rusted_metal`, `wooden_floor`) or a `.ptex` path from the user.
3. **Variations:**
   - `params` sets node parameters by node name, nested graphs included: `{"Perlin": {"scale_x": 8}}`.
   - `controls` sets the graph's exposed controls by label: `{"Hue": 0.1}`.
   - Unknown names fail the call and list what was not found. Never guess silently.
   - The source `.ptex` is never modified; a copy is exported.
4. **Export + material:**
   ```python
   run({"ptex": "bricks", "project_dir": proj, "size": 2048,
        "params": {"Perlin": {"scale_x": 6}}, "objects": ["SM_Wall_A"], "tiling": 2})
   ```
   - Maps go to `<project>/textures/material_maker/<name>/`.
   - The `GLTF/Plane` profile writes `albedo`, `orm` (R = AO, G = roughness, B = metallic), `normal` (OpenGL, like glTF and Blender) and `emission` when the graph has one.
   - The material `MAT_<name>` follows `bake_maps.py`: Principled BSDF, ORM split, `glTF Material Output` occlusion group, plus a Mapping node for tiling. The glTF exporter writes the tiling as `KHR_texture_transform`.
5. **No usable UVs:**
   - `projection: "box"` works for viewport and render only. glTF has no box mapping.
   - Before a game/web export, either unwrap (`uv-workflow`) or bake the box-mapped material to UVs with `bake_maps.py`.
6. **Validate:** look at the material in the target lighting (`lookdev`). Check the texture budget (`size`, KTX2 in `web-export`) and the material count budget.

## Profiles

| `target` | Files | Use |
|----------|-------|-----|
| `GLTF/Plane` (default) | `_albedo.png`, `_orm.png`, `_normal.png`, `_emission.png` | glTF / web / engines with ORM |
| `Blender` | `_albedo.png`, `_normal.png`, `_emission.png`, `_rough.exr`, `_metal.exr`, `_occlusion.exr`, `_displace.exr`, `_sss.exr` | Blender renders. Displacement and SSS maps are kept on disk, not wired |

Which files appear depends on the graph's Material node: a wood graph without emission writes no emission map. A black emission map is dropped from the material, so no empty emissive texture is exported.

## Operational Notes

- **Needs a desktop session:** Material Maker renders on the GPU through a window. No headless server, no SSH without a display. A failed export says so.
- **Timing (macOS Apple Silicon):**
  - The first export after launch takes about 30 s (shader warm-up). Later 512 px exports take about 2.3 s each.
  - One run exited with SIGTERM and wrote no maps. Re-run once before reporting a failure.
- **Already have maps:** `mode: "material"` with `maps_dir` and `name` builds the material from maps exported earlier, without the app.
- **Library materials:** materials downloaded from the Material Maker website keep their authors' licences. Ask the user before using a website material in a shipped asset.

## Constraints

### MUST DO
- Probe before use; report missing install with the result's install line
- Keep maps inside the project (`project_dir` or `out_dir`) — temp-folder maps are lost on reboot
- Bake or unwrap before export when `projection: "box"` was used

### MUST NOT DO
- Download or install Material Maker for the user
- Edit the user's `.ptex` in place
- Wire displacement into a game asset material (no glTF slot; use geometry or a parallax material in the engine)
