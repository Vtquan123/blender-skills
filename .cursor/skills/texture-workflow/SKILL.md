---
name: texture-workflow
description: Production texture workflow for atlases, baking AO/curvature/normal/roughness maps, decals, and texture memory optimization. Use for game-ready texture pipelines in Blender via MCP.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.1.0"
  domain: blender
  role: specialist
  triggers: texture, bake, normal map, AO, curvature, roughness, metallic, height, atlas, decal, emission, transfer textures, rebake to new UVs
  related-skills: uv-workflow, materials, asset-optimization, deformation-prep, web-export
---

# Texture Workflow

Bake high-poly detail to efficient texture sets. Optimize memory. Engine-ready outputs.

## When to Use

- Baking sculpt detail to normal maps
- Creating texture atlases for modular kits
- PBR texture set generation
- Decal placement and blending
- Texture memory optimization

## Workflow

```
High/Low Poly Setup → Cage Setup → Bake Maps → Composite
    → Atlas Pack → Engine Format Export → Validation
```

## Standard PBR Texture Set

| Map | Format | Notes |
|-----|--------|-------|
| Base Color | sRGB PNG | No embedded AO |
| Normal | Linear PNG | OpenGL convention unless engine specifies |
| Roughness | Linear PNG | Single channel |
| Metallic | Linear PNG | Single channel |
| AO | Linear PNG | Multiply in shader, not base color |
| Height | Linear PNG | Optional parallax |
| Emission | sRGB PNG | Mask-based |
| ORM Packed | Linear PNG | R=AO, G=Roughness, B=Metallic (Unreal) |

Naming: `T_[Asset]_[Map]` per `../references/naming-conventions.md`

## Bake Setup

```
1. Low-poly mesh with UVs (active)
2. High-poly mesh (sculpt or detail) — selected
3. Cage extrusion: 0.01–0.05m (adjust per asset scale)
4. Ray distance: match cage
5. Bake margin: 16px minimum
6. Anti-aliasing: enabled
```

## Maps to Bake

| Map | Source | Priority |
|-----|--------|----------|
| Normal | High→Low | Required |
| AO | High or low (cavity) | Required |
| Curvature | High sculpt | Wear masks |
| Position | High | Optional (blending) |
| Thickness | Subsurface meshes | Characters |

## Source → New Mesh Transfer (Production Mode)

When geometry was decimated or rebuilt (`asset-optimization`, `deformation-prep`), the source's textures no longer match the new UVs. `production/scripts/blender/bake_maps.py` bakes from the untouched source onto the new mesh:

| Map | Bake type | Notes |
|-----|-----------|-------|
| Base colour | Emit pass of the source colour texture (avoids lighting in the bake) | sRGB |
| Normal | Selected-to-active normal, tangent space, OpenGL (+Y) for glTF | Combines source normal map detail + shape difference |
| ORM | AO from source geometry → R; source roughness → G; source metallic → B | glTF reads occlusion R, roughness G, metallic B |

Cage/extrusion from asset scale (≈ 1 % of the bbox diagonal as a start), margin ≥ 16 px, resolution from `budgets.textures.max_size`. Result checked at gate G3 (`mesh_metrics.py` with `gate: G3` and the bake result: non-empty maps, UV overlap, material count) plus a screenshot vs source.

- Shade the target **smooth** before baking normals; a flat-shaded cage bakes the quad grid into the normal map (`bake_maps.py` warns).
- Dense sources: bake one or two maps per MCP call; the last call (`use_existing: true`, default) packs ORM and builds the material from every map already in `textures/`. The first GPU bake of a session can exceed the MCP wait while kernels compile — poll for the PNGs instead of resending.

## Texture Atlas Strategy

Modular kits share one atlas:
```
1. All modules UV'd to shared 0–1 or UDIM space
2. Bake each module to atlas regions
3. Trim sheet areas for repeating detail
4. Single material references atlas
5. Document region map for artists
```

## Decals

- Decal mesh projected on surface
- Separate UV channel or atlas region
- Blend via alpha mask
- Limit decal overdraw in engine

## Memory Optimization

| Technique | Savings |
|-----------|---------|
| ORM packing | 3 textures → 1 |
| Shared atlas | N materials → 1 texture |
| Lower res on hidden surfaces | 50%+ memory |
| BC compression in engine | 4:1 or 6:1 |
| Trim sheets | Reuse detail across assets |

## Resolution Guidelines

See `../references/polycount-budgets.md` texture section.

## MCP Integration

1. Setup bake objects via MCP
2. Configure bake settings via MCP if supported
3. Export baked images via MCP
4. Assign baked textures to materials via MCP
5. Query texture count and resolution

## Validation Checklist

- [ ] Normal map correct orientation (test in engine)
- [ ] No UV seams visible in bake
- [ ] AO not baked into base color
- [ ] Consistent texel density in final textures
- [ ] Texture resolution within budget
- [ ] Files named per convention
- [ ] sRGB vs Linear correctly assigned

## Constraints

### MUST DO
- Bake high-poly detail before discarding sculpt
- Use cage for clean normal bakes
- Pack ORM for engine efficiency
- Test normal map orientation in target engine
- Document atlas regions for modular kits

### MUST NOT DO
- Bake without cage on complex shapes
- Embed AO in base color (PBR standard)
- Exceed texture budget without LOD justification
- Use inconsistent normal map conventions
- Skip margin in bake settings

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Bake troubleshooting | `references/bake-troubleshooting.md` | Bake artifacts |
| ORM packing | `references/orm-packing.md` | Unreal/Unity export |
