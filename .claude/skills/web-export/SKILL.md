---
name: web-export
description: Use when a Blender asset must be delivered for the web or a browser runtime. Invoke for three.js, React Three Fiber, Babylon.js, model-viewer, GLB for web, meshopt, Draco, KTX2, WebP textures, glTF-Transform, gltfpack, web performance budgets, animated GLB in the browser.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.0.0"
  domain: blender
  role: specialist
  triggers: web, three.js, threejs, react three fiber, R3F, babylon, model-viewer, GLB for web, browser 3D, meshopt, draco, KTX2, webp textures, gltf-transform, optimize glb
  related-skills: export-pipeline, asset-optimization, lod-pipeline, qa-review, animation, deformation-prep
---

# Web Export

Exports a master GLB from Blender, optimises it for browsers with glTF-Transform, and proves it loads and animates in a headless three.js page.

## Role Definition

A WebGL/WebGPU technical artist who ships 3D to product pages and web apps. Thinks in download size, decode time, VRAM and draw calls, and knows exactly which glTF features each web runtime reads.

## When to Use

- `target.platform: web` in an output spec
- "Make this GLB smaller / load faster / animate in three.js"
- Any animated GLB destined for a browser

## Core Workflow

1. **Pre-flight** — `asset-optimization` PASS; transforms applied; one armature; clips named; influences ≤ 4 (`references/web-runtime-limits.md`).
2. **Master export** — `production/scripts/blender/export_glb.py`: GLB, +Y up, no compression, animations as separate actions, deform bones only → `output/<name>.master.glb`. This file is the reproducible source for every web variant.
3. **Optimise** — `production/scripts/node/optimize.mjs` (glTF-Transform): dedup, prune, weld, resample animation, texture resize + KTX2/WebP, meshopt (or Draco per spec) → `output/<name>.glb` (`references/gltf-transform-pipeline.md`).
4. **Validate** — `production/scripts/node/validate_gltf.mjs` (Khronos glTF-Validator, 0 errors) → gate G6.
5. **Runtime check** — headless three.js page loads the GLB, plays every clip, records draw calls, triangles, texture memory, and compares sampled vertex positions with Blender → gate G7 (`references/threejs-integration.md`).
6. **Hand-off** — loader snippet for the user's framework, budgets table, report.

## Technical Guidelines

| Decision | Default | When to change |
|----------|---------|----------------|
| Geometry compression | Meshopt (`EXT_meshopt_compression`) — fast decode, also compresses animation | Draco when the spec wants the smallest bytes and accepts slower decode |
| Textures | KTX2: UASTC for normal/detail, ETC1S for colour/ORM | WebP when only download size matters (WebP still decodes to full RGBA in VRAM) |
| Texture size | From `budgets.textures.max_size` | Never upscale |
| Animation | Bake to deform bones at spec fps, then `resample` (lossless dedup) | Raise tolerance only with a G5/G7 comparison |
| Skinning | ≤ 4 influences, normalized | Never exceed: three.js reads one JOINTS/WEIGHTS set |
| Static objects | Node-transform clips, no skin | — |

Always pass the texture format explicitly to `gltf-transform optimize` (`--texture-compress ktx2|webp`); the `auto` default can re-encode PNG larger.

## Constraints

### MUST DO
- Keep `*.master.glb` and the exact optimise command in the report
- Run glTF-Validator and the headless runtime check before declaring done
- Report bytes, triangles, draw calls, texture memory against the spec

### MUST NOT DO
- Compress inside Blender and again in glTF-Transform
- Ship more than 4 influences per vertex or non-normalized weights
- Rely on Blender drivers or constraints at runtime (they do not export) — bake them

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| glTF-Transform pipeline | `references/gltf-transform-pipeline.md` | Step 3 |
| Web runtime limits | `references/web-runtime-limits.md` | Pre-flight, rigging |
| three.js integration + runtime check | `references/threejs-integration.md` | Steps 5–6 |
| Generic export settings | `../export-pipeline/SKILL.md` | Step 2 |

## Knowledge Reference

GLB, glTF 2.0, web, three.js, GLTFLoader, MeshoptDecoder, KTX2Loader, DRACOLoader, React Three Fiber, Babylon.js, model-viewer, glTF-Transform, gltfpack, meshopt, Draco, KTX2, Basis Universal, UASTC, ETC1S, WebP, quantization, resample, prune, dedup, glTF-Validator, AnimationMixer, crossFadeTo, draw calls, VRAM, gate G6, gate G7
