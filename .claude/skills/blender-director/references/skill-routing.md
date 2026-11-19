# Skill Routing Reference

Extended routing tables for the Blender Director.

## By Engine Target

| Engine | Export Skill | Notes |
|--------|--------------|-------|
| Unity | unity-export | GLB/GLTF modern; FBX for humanoid/legacy |
| Unreal | unreal-export | FBX; UCX collision; verify cm scale |
| Godot | godot-export | GLTF/GLB preferred |
| Web (three.js, R3F, Babylon.js, model-viewer) | web-export | GLB + meshopt + KTX2/WebP; ≤ 4 skin influences |
| Generic / multi | export-pipeline | Confirm axis and scale; then engine skill if known |

## Production Mode (Existing Asset → Deliverable)

| Stage | Lead Skill | Supporting | Gate |
|-------|------------|-----------|------|
| Intake / analysis | asset-intake | blender-director | G0 |
| Plan | blender-director (`production-mode.md`) | asset-intake report | G1 |
| Geometry (static) | asset-optimization | retopology, blender-modeler | G2 |
| Geometry (deforming) | deformation-prep | retopology | G4a |
| UV + bake | uv-workflow + texture-workflow | materials | G3 |
| Rig + skin | deformation-prep → rigging | animation | G4b, G4c |
| Animation | animation (`reference-driven-motion.md`) | deformation-prep | G5 |
| LOD | lod-pipeline | asset-optimization | G2 per level |
| Web delivery | web-export | export-pipeline | G6, G7 |
| Engine delivery | unity-export / unreal-export / godot-export | export-pipeline | G6 |
| Final QA + report | qa-review (`production-gates.md`) | blender-director | G8 |

Category presets (`production/presets/categories/*.yaml`) decide the family:
`creature` → full deformation path · `articulated_object` → rigid parts + hinges · `static_object` → no rig.

## By Production Phase

| Phase | Lead Skill | Validators |
|-------|------------|------------|
| Reference analysis | blender-director + reference-image-match | reference-analysis-template |
| Genre / style / world lock | matching genre/style/world/mood skill | production brief |
| Blockout | blender-modeler / discipline skill | blender-director |
| Detail pass | discipline skill | asset-optimization |
| UV pass | uv-workflow | texture-workflow |
| Look dev | lookdev + materials | style skill, qa-review |
| Camera / shot | camera-cinematography | rendering |
| FX / sim | vfx-fx / physics-sim / cloth-sim | compositing |
| Reference compare | rendering + lighting | visual-match-checklist |
| Scene layout | scene-assembly + set-dressing | qa-review |
| Performance | asset-optimization + lod-pipeline | collision-proxy |
| Delivery | unity-export / unreal-export / godot-export / web-export / export-pipeline | qa-review + validation-checklist |

## Style + Discipline Matrix (core)

|  | Hard Surface | Prop | Vehicle | Environment | Character | Creature |
|--|-------------|------|---------|-------------|-----------|----------|
| Horror | + horror-style | + horror-style | + horror-style | + horror-style | + horror-style | + horror-style |
| PSX Horror | + psx-horror-style | + psx-horror-style | + psx-horror-style | + psx-horror-style | + psx-horror-style | + psx-horror-style |
| Lowpoly | + lowpoly-style | + lowpoly-style | + lowpoly-style | + lowpoly-style | + lowpoly-style | + lowpoly-style |
| Anime | + anime-style | + anime-style | + anime-style | + anime-style | + anime-style | + anime-style |
| Voxel | + voxel-style | + voxel-style | + voxel-style | + voxel-style | + voxel-style | + voxel-style |
| Isometric | + isometric-style | + isometric-style | + isometric-style | + isometric-style | + isometric-style | + isometric-style |
| Stylized | + stylized-style | + stylized-style | + stylized-style | + stylized-style | + stylized-style | + stylized-style |
| Realistic | + realistic-style | + realistic-style | + realistic-style | + realistic-style | + realistic-style | + realistic-style |

Add world/mood/genre packs on top (e.g. `sci-fi-punk-worlds` + `neon-retrofuturism` + `genre-shooter`).

## Pack Routers (load references inside)

| Pack | Examples covered in refs |
|------|--------------------------|
| sci-fi-punk-worlds | hard sci-fi, space, cyber/steam/diesel/atom/solar/bio/clockpunk |
| fantasy-worlds | medieval, high/dark/urban fantasy |
| historical-worlds | western, pirate, samurai, viking, ancients, victorian, military |
| apocalypse-worlds | wasteland, zombie, dystopia/utopia, alien invasion |
| biome-worlds | underwater, desert, arctic, jungle, underground, floating islands |
| indie-horror-aesthetics | Silent Hill, Fear to Fathom, Puppet Combo, corporate, cabin/hospital/forest |
| character-archetypes | fantasy races, horror bodies, sci-fi bodies, role kits |
| visual-console-eras | PS1–PS5, CRT, VHS, DOS, arcade, film grain |
| painterly-style | watercolor, oil |
| stop-motion-craft-style | claymation, paper craft |
| genre-rpg | JRPG, CRPG, ARPG, MMORPG |
| genre-shooter | FPS, TPS, BR, extraction |
| genre-strategy-sim | RTS, TBS, TD, MOBA, city/colony/life/farming sim |

## Parallel vs Sequential

**Sequential (default):** Genre/style lock → Modeling → UV → Materials → Lookdev → Export

**Parallel allowed:**
- Material prototyping while UVs in progress (separate collections)
- Lighting setup while optimization runs on duplicate collection
- Collision proxies while LOD1+ generates
- Mood/world reference gathering during blockout

**Never parallel:**
- Retopology before sculpt complete
- Export before validation / qa-review
- Rigging before final topology locked
- Engine export before LOD/collision plan when required
