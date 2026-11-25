# Joint Loop Rules

> Reference for: deformation-prep, retopology
> Load when: building or checking the deform mesh (step 4, gate G4a)

These are the default rules shipped in category presets (`production/presets/categories/*.yaml → joint_rules`). The spec may override any value.

## Defaults

| Joint type | Rule | Reason |
|------------|------|--------|
| Hinge (elbow, knee, hock, wing elbow) | 3 loops in the bend band + 1 support loop each side, perpendicular to the bone | Keeps volume when folding |
| Ball (shoulder, hip, wing shoulder) | Radial loops around the socket; density ≥ 1.5× the limb | Rotates on several axes |
| Twist segment (forearm, upper arm, thigh) | Evenly spaced loops along the segment | Spreads twist across twist bones |
| Digit (fingers, toes, claws) | 2–3 loops per knuckle | Large angle in small area |
| Chain (neck, spine, tail, ear) | Evenly spaced loops, one per bone segment minimum | Smooth curve along chain |
| Face (only if facial animation) | Concentric loops around eyes and mouth | Open/close without tearing |
| Rigid part boundary | Border loop on each side of the cut | Clean edge, no shading artefacts |

## Building the Deform Mesh

1. Weld the source copy (see `asset-intake/references/intake-metrics.md`).
2. Automatic quad base at the triangle budget (`deform_mesh.py remesher`):
   - `quadriflow` (default) — Blender's built-in `bpy.ops.object.quadriflow_remesh`; needs a manifold mesh; supports X symmetry.
   - `autoremesher` — the AutoRemesher extension's core, run in a subprocess by `production/scripts/blender/autoremesh.py`. Curvature-adaptive quads, keeps thin features (`preserve_thin`) and small islands (`island_detail`), no manifold pre-check, can fuse intersecting shells (`weld_shells`). No symmetry. The user installs the extension; probe first (`autoremesh.py mode=probe`).
   - `auto` — AutoRemesher when available, QuadriFlow otherwise or when AutoRemesher fails; the result's `remesh.used` / `remesh.fallback` say which ran.
3. Measure each joint band (`joint-analysis.md` metrics). For bands below the rule:
   - add loops with loop cuts on rings that already cross the band, or
   - re-remesh the region with higher density (vertex-group density, or a local remesh + bridge), then re-measure.
4. Shrinkwrap (nearest surface point, small offset) back to the source so the silhouette matches.
5. Re-measure; write per-joint results to `reports/gate-G4a.json`.

Automatic remeshers produce even quads but do not place animation loops on their own, which is why step 3 exists.

## G4a Review Sheet

For each joint: wireframe close-up (front + side) with the bone overlay, rule vs measured rings. The user approves or marks joints to redo.
