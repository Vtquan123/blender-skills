# three.js Integration and Runtime Check

> Reference for: web-export, qa-review
> Load when: handing off a web GLB or running gate G7

## Loader Snippet (three.js)

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

const ktx2 = new KTX2Loader().setTranscoderPath('/basis/').detectSupport(renderer);
const loader = new GLTFLoader().setKTX2Loader(ktx2).setMeshoptDecoder(MeshoptDecoder);

const gltf = await loader.loadAsync('/models/asset.glb');
scene.add(gltf.scene);

const mixer = new THREE.AnimationMixer(gltf.scene);
const actions = Object.fromEntries(gltf.animations.map(c => [c.name, mixer.clipAction(c)]));
actions.idle?.play();
// switch smoothly: actions.idle.crossFadeTo(actions.walk.reset().play(), 0.3, false);
// per frame: mixer.update(clock.getDelta());
```

Add `DRACOLoader` only when the spec chose Draco. For React Three Fiber, `useGLTF` + `useAnimations` with the same decoders.

## Runtime Check (gate G7)

`production/scripts/validation/runtime_check.mjs` (Playwright + three.js, headless Chromium; uses Playwright's Chromium, or the installed Google Chrome automatically / via `--chrome <path>`):

1. Serve the GLB and a minimal page with the loader above.
2. Record: load time, `renderer.info.render.calls` (draw calls), triangles, textures and their GPU formats.
3. For each clip: play to sampled times (0, 25, 50, 75, 100 %), read world positions of a fixed vertex sample from each `SkinnedMesh` (`SkinnedMesh.applyBoneTransform` / `getVertexPosition`).
4. Compare with the same samples exported from Blender (`production/scripts/blender/sample_vertices.py`); report max deviation per clip.
5. Screenshot each clip at 50 % for the report.

A large deviation usually means dropped influences, wrong bind pose, unapplied scale, or a constraint that was not baked.

## Clip Naming

Use the clip names from the spec (`idle`, `walk`, …) so front-end code is stable across asset versions. Blender action names may carry the `AN_` prefix; `export_glb.py` strips it when the spec asks for plain names.
