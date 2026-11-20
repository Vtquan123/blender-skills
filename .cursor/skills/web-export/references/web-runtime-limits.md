# Web Runtime Limits

> Reference for: web-export, deformation-prep, rigging, animation
> Load when: designing rigs, weights, materials or clips for browser delivery

| Topic | Limit / behaviour | Consequence for the asset |
|-------|-------------------|---------------------------|
| Skin influences | glTF stores 4 joints per `JOINTS_n/WEIGHTS_n` set; extra sets are allowed by the spec, but three.js reads only the first set (4 influences) | Limit to 4 in Blender, normalize; otherwise extra weights are dropped and fingers/head wobble |
| Skinning method | Linear blend skinning | Use twist bones and loops; no dual-quaternion assumptions |
| Drivers / constraints | Not exported | Bake to keyframes; corrective shapes need runtime code |
| Morph targets | Exported; cost memory per target | Use only when ROM test requires correctives or for faces |
| Materials | Metallic-roughness PBR, unlit, common KHR extensions | Bake procedural nodes to textures |
| Meshopt | three.js `GLTFLoader.setMeshoptDecoder` (r122+); Babylon.js 5+ built-in | Ship decoder setup in the snippet |
| KTX2 | `KTX2Loader` with transcoder path + `detectSupport(renderer)` | Ship loader setup in the snippet |
| Skinned mesh parent | Parent transforms do not affect a skinned mesh in glTF | Keep the armature at the root; apply transforms (validator warning `NODE_SKINNED_MESH_NON_ROOT` is expected and harmless) |
| B-Bones (bendy bones) | Not in glTF; runtimes deform with straight bones | Deform bones must have 1 segment (`rig_fit.py` flattens after Rigify generate). Rigify's 8–10 segment DEF bones made Blender differ from three.js by 15 mm on a 25 cm cat; 0.8–2.4 mm after flattening |
| Normal maps | Without exported tangents the runtime generates them (validator warning) | Export tangents (`export_glb.py` default) |
| Extra scenes / actions | Other scenes export as empty scenes (validator error); every action is exported as a clip | `export_glb.py` exports the active scene only and takes `clips: [...]` to drop work actions such as `AN_ROM` |

Budgets (triangles, bones, texture size, file size, draw calls) are **not** fixed here — they come from `output-spec.yaml`. Presets in `production/presets/web-*.yaml` give editable starting points.

Sources: three.js forum and glTF spec discussions summarised in the project proposal; verify against the three.js version the user ships.
