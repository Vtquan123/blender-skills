# Mesh Cleanup — Safe Order, Measured Before and After

> `production/scripts/blender/mesh_cleanup.py`. Order and guards from blender-kiln's cleanup and
> topology rules; works on a copy (`<name>_clean`) unless `in_place: true`.

## Order

```
weld (0.1 mm) → loose → degenerate → [holes] → normals → [n-gons] → transforms → [decimate] → origin at base
```

Each step reports what it changed; `before` / `after` give verts, tris, quads, n-gons, open and
non-manifold edges, loose geometry, degenerate faces, **duplicate vertices** and connected components.

## Guards

| Guard | Why |
|---|---|
| **Weld before skinning** — `duplicate_verts` must be 0 | Each copy of a split vertex gets its own weights and the skin opens at every joint (kiln rule 26) |
| **Decimate is undone when it opens the mesh** — open / non-manifold edges compared per try; the next try decimates less (×1.25 … ×2 the target) | Thin parts (wires, handles, straps) break first; silhouette scores do not see the holes |
| **`protect_group`** keeps a vertex group at full detail | Faces, hands, thin rims |
| **Print models skip weld and decimate** (`print: true`) | A 0.1 mm merge broke a closed printable model while its own count read 0 |
| **Budget is reported, never enforced** | Tiers are soft: up to 2× the top is fine when the triangles go where they show; past 2× propose a reduction, the user decides |

## Budgets (triangles, soft)

| Tier | Hero / character | Prop | Background |
|---|---|---|---|
| lightweight | 3–8 K | 0.3–1.5 K | 50–300 |
| balanced | 8–20 K | 1.5–5 K | 0.3–1.5 K |
| detailed | 20–80 K | 5–15 K | 1.5–5 K |

## AI-generated meshes

Measured on the project dog (Tripo, 1.92 M triangles, 128 pieces, 20,758 doubled vertices along UV
seams): weld + degenerate + normals + guarded collapse → 20 K triangles, 1 piece, open edges 41,081 → 2,
in 65 s. A creature that will deform still goes through `deformation-prep` (QuadriFlow + joint loops):
a decimated triangle soup is a bake source or a static LOD, not an animation mesh.

## Before rigging

`measure_pose: true` reports the arm angle from two sections along the arm (robust to big heads):
within ±15° T-pose, −15…−45° A-pose, below −45° I-pose (arms touching the torso — convert first).
Wingspan ≈ height on a true T-pose.

## Rules

- Never decimate thin parts with the body; rebuild them as curves with a round bevel.
- After any decimate, compare open/non-manifold counts with before **and look at a close render of every
  thin part**.
- More passes at gentle ratios beat one aggressive pass (`passes`, default 2).
- Keep the source: the high-poly is the bake source for normals and AO.
