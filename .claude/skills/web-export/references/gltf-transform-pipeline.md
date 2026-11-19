# glTF-Transform Pipeline

> Reference for: web-export
> Load when: optimising a master GLB for the web (step 3)

## Requirements

- Node.js 18+; `npm i -D @gltf-transform/cli @gltf-transform/core @gltf-transform/extensions @gltf-transform/functions meshoptimizer gltf-validator` (pinned in `production/package.json`; run `npm install` inside `production/`).
- KTX2 encoding needs KTX-Software (`ktx` CLI) on PATH. If it is missing, `optimize.mjs` stops and reports — it does not silently fall back to WebP.

## Order of Operations

Textures usually dominate file size and VRAM, so they are handled before geometry compression; geometry compression is always last.

```
dedup → prune → weld → resample (animation) → [simplify, only if spec allows]
  → texture resize (max_size) → texture compress (ktx2 | webp)
  → quantize/meshopt (or draco) → prune
```

`production/scripts/node/optimize.mjs` implements this order and reads every value from `output-spec.yaml`:

```bash
node production/scripts/node/optimize.mjs \
  --in projects/<name>/output/<name>.master.glb \
  --out projects/<name>/output/<name>.glb \
  --spec projects/<name>/output-spec.yaml \
  --report projects/<name>/reports/optimize.json
```

Equivalent CLI for a quick manual run (values from the spec):

```bash
npx gltf-transform optimize in.glb out.glb \
  --compress meshopt --texture-compress ktx2 --texture-size 2048 --simplify false
```

## Animation

- `resample` removes duplicate keyframes losslessly (default tolerance 1e-4); it does not change motion.
- Meshopt compresses animation and morph target data as well as meshes.
- Do not run Blender's "optimize animation size" and then a lossy resample with a large tolerance; compare poses (G7) if tolerance is raised.

## Simplify

Off unless `geometry.strategy` is `decimate` and the spec allows post-export simplification. For deforming meshes simplification must happen in Blender (`deformation-prep`), never here — it would break joint loops.

## Report (`reports/optimize.json`)

Bytes before/after, triangles, vertices, textures (size, format), animation channels and keyframes before/after, the exact command and package versions.
