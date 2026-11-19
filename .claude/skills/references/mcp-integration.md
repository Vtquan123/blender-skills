# Blender MCP Integration Rules

When Blender MCP is available, **execute operations through MCP** instead of describing manual UI steps.

**Setup:** See repo `docs/BLENDER_MCP_SETUP.md`. The pack targets the official Blender MCP server (Blender Lab add-on, Blender 5.1+); the community `blender-mcp` server also works (tool mapping in `mcp-tools.md`). Verified capabilities: `docs/BLENDER_MCP_CAPABILITIES.md`.

**Tool catalog:** See `mcp-tools.md` for tool names, the `result`-dict rule, background (`*_for_cli`) mode and bpy fallbacks.

## Priority Order

1. Check MCP tool descriptors before any Blender operation
2. Read tool schemas for required parameters
3. Execute via MCP tools
4. Validate results via MCP scene queries
5. Only fall back to UI instructions if MCP lacks the capability

## MCP-First Operations

| Task | MCP Approach |
|------|--------------|
| Create objects | Use MCP object creation tools |
| Modify geometry | Use MCP mesh/edit tools |
| Apply modifiers | Use MCP modifier tools |
| UV operations | Use MCP UV tools if supported |
| Materials | Create/assign materials via MCP |
| Collections | Organize scene hierarchy via MCP |
| Export | Use MCP export tools |
| Validation | Query scene stats via MCP |

## Execution Protocol

```
1. List available MCP tools for Blender server
2. Read schema for each tool before calling
3. If reference image attached → reference-analysis-template.md BEFORE step 4
4. Plan operation sequence (non-destructive first)
5. Execute step-by-step with validation between steps
6. viewport screenshot (`get_screenshot_of_area_as_image`, `VIEW_3D`) after camera, materials, lighting phases
7. Report object names, counts, and metrics after each phase
```

## Reference Image MCP Loop

When matching a photo:

| Step | MCP Tool |
|------|----------|
| Baseline | `get_screenshot_of_area_as_image` (`VIEW_3D`) |
| Audit scene | `execute_blender_code` (bounds, materials, collections) |
| Camera / geometry / materials / lights | `execute_blender_code` |
| Compare pass | `get_screenshot_of_area_as_image` (`VIEW_3D`) or `render_viewport_to_path` |
| Save | `execute_blender_code` → `bpy.ops.wm.save_mainfile` |

See `reference-image-match.md` for full workflow and anti-patterns.

## Production Mode Execution

- Check `get_blendfile_summary_path_info` first: if the open file is dirty, do not open/replace files — work in a temporary scene or ask the user.
- Run repository scripts with `runpy.run_path("<repo>/production/scripts/blender/<stage>.py")["run"](args)`; each returns a dict (assign it to `result`).
- One stage per call; verify with `get_objects_summary` and a viewport screenshot; write the gate JSON before moving on.
- Batch work that must not touch the user's session: `execute_blender_code_for_cli` with `BLENDER_PATH` set for the MCP server.

## Scene Organization via MCP

When creating assets, immediately establish:

```
Scene Root
├── COL_Reference
├── COL_Blockout
├── COL_HighPoly
├── COL_LowPoly
├── COL_Collision
├── COL_Lights
└── COL_Export
```

Naming prefixes: see `naming-conventions.md`

## Non-Destructive Defaults

- Create duplicates before destructive operations
- Keep backup collections hidden, not deleted
- Apply modifiers only at export phase unless required for downstream work
- Document modifier stack in planning output

## Validation Queries

After major phases, query via MCP:

- Object count and names
- Polygon/triangle counts per object
- Material count
- Collection membership
- Origin/pivot locations
- Transform application status

## Error Handling

If MCP call fails:
1. Read error message completely
2. Check if Blender is running and MCP connected
3. Verify object/mesh names match scene state
4. Retry with corrected parameters
5. Never silently skip failed operations

## Anti-Patterns

- ❌ "Press Tab to enter Edit Mode, then..."
- ❌ Long UI walkthroughs when MCP can execute
- ❌ Assuming scene state without querying
- ❌ Destructive apply without backup
- ❌ Export without validation pass

## Fallback Mode

When Blender MCP is unavailable:
- Provide concise planning and specifications
- Output Python `bpy` scripts the user can run
- Include validation checklist for manual verification
- Note which steps require MCP for full automation
