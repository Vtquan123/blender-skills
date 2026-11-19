# Production QA Checklist

Tick only with evidence (gate JSON or screenshot). Gate details: `.claude/skills/qa-review/references/production-gates.md`.

## G0 Intake
- [ ] Source imported in a temporary scene; checksum recorded
- [ ] Weld check done; components/boundary edges recorded
- [ ] Category, orientation, real size confirmed by user

## G1 Plan
- [ ] Every required spec field set or explicitly "report only"
- [ ] Only needed stages enabled
- [ ] User approved

## G2 Geometry / G3 Surface
- [ ] Triangles within budget; no non-manifold; transforms applied
- [ ] Silhouette compared with source (screenshot)
- [ ] UVs without unintended overlap; maps baked, non-empty, no visible seams

## G4 Deformation (creatures / articulated objects)
- [ ] G4a joint loops per rule — user approved wireframe sheet
- [ ] G4b no unweighted vertices; ≤ max influences; normalized; rigid parts 1.0
- [ ] G4c ROM sheet — user approved

## G5 Animation
- [ ] All clips present with spec names, fps, ranges
- [ ] Loops seamless; no foot slide beyond threshold
- [ ] Similarity to source approved (reference-driven clips)

## G6–G7 Export / Web
- [ ] glTF-Validator: 0 errors
- [ ] Size, draw calls, texture memory within budget
- [ ] three.js headless: loads, every clip plays, vertex deviation within threshold

## G8 Deliver
- [ ] Source checksum unchanged
- [ ] Report complete with commands and versions
