# Joint Analysis

> Reference for: deformation-prep
> Load when: placing joints and scoring topology readiness (step 2)

## Joint Positions — Sources (in order)

1. **Existing armature** in the source → reuse; check bone roll and hierarchy.
2. **Template fit** — category template from `category-rigs.md`: add the metarig, scale to the model's real size, snap joints using cross-section centres (below).
3. **Proposal** for non-standard creatures — a learned skeleton predictor may propose bones; treat as a draft only.

Every source ends with **user confirmation** on a screenshot showing bones over the mesh (front + side, X-ray).

## Cross-Section Centring

For each bone: slice the welded source mesh with planes perpendicular to the bone at 5 positions (`bmesh.ops.bisect_plane` on a copy, or ray casts around the axis). The joint should sit at the centre of the slice loop nearest the bend; move it there and report the offset.

## Readiness Score per Joint

Measured on the **current** mesh (source before remesh, deform mesh after):

| Metric | How | Good |
|--------|-----|------|
| `rings` | Edge loops around the limb inside the band ±r (r = limb radius): count of band edges crossed by meridian half-planes through the bone axis, median of 8 angles (`u3d_common.count_rings`) | ≥ rule in `joint-loop-rules.md` |
| `tri_ratio` | Triangles / faces in the band | ≈ 0 for deform meshes |
| `poles` | Vertices with valence ≠ 4 in the band | Few; reported for the G4a review (automatic remeshes always have some), not gated |
| `density` | Average edge length in band vs limb radius | Rule-dependent |
| `rigid_crossing` | Faces of a rigid-part candidate inside the band | 0 (else split or move part) |

Raw AI/scan meshes are triangle soups: score is "not ready" everywhere — that is expected and is why step 4 rebuilds topology.

## Output — `reports/joint-report.json`

```json
{
  "template": "rigify_cat",
  "joints": [
    {"name": "front_leg.L.elbow", "pos": [0.04, -0.06, 0.05], "offset_from_centre_m": 0.003,
     "rings": 0, "tri_ratio": 1.0, "poles": 41, "strategy": "skin", "action": "retopo_band"}
  ],
  "screenshots": ["reports/joints_front.png", "reports/joints_side.png"]
}
```
