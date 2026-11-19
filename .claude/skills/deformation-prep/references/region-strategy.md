# Region Strategy

> Reference for: deformation-prep
> Load when: deciding how each region of the model moves (step 3)

## Decision

```
For each region (from joint-report + intake components):
Does the surface bend or stretch when the joint moves?
├── NO  → RIGID PART: separate object/vertex set, weight 1.0 to one bone (or parent to bone)
│         examples: armour plates, helmet, collar tag, book cover board, box lid, chair seat
└── YES → Does it hang or swing freely (follows inertia, not a joint)?
          ├── YES → FREE CHAIN: own bone chain (or baked sim → bones/shape keys via cloth-sim)
          │         examples: cape, long hair, tail feathers, ear tips, page curl
          └── NO  → SKIN: deform mesh with joint loops + weights
                    examples: torso, limbs, neck, tail base
```

All three live under **one armature** and export as one GLB with one animation mixer.

## Seams Between Rigid Parts

- Overlap the parts slightly at the joint or add a collar/gasket ring so no gap opens at the joint limit.
- Put the pivot exactly on the hinge axis (see `category-rigs.md` → hinge detection).
- Test the joint at its full limit in the ROM test; no visible gap and no interpenetration.

## Fused Parts

AI-generated and sculpted models often fuse limbs, wings or accessories into the body surface.

| Required motion | Approach |
|-----------------|----------|
| Small (flutter, lift a few degrees, sway) | Keep fused; skin with bones; limit range so hidden surface never shows |
| Large (wing spread, arm raise away from body) | Separate the part, rebuild the hidden body surface, extend/paint texture — needs user approval and review |

Record the choice per region in `plan.yaml → stages.rig.params.regions`.
