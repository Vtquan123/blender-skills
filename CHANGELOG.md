# Changelog

All notable changes to the Blender Skills Pack.

Format: [Semantic Versioning](https://semver.org/) — `Major.Minor.Patch`

---

## [Unreleased]

### Added
- **AutoRemesher backend** — `production/scripts/blender/autoremesh.py` runs the core of the optional
  [AutoRemesher for Blender](https://github.com/jakeblakeley/autoremesher-blender) extension (`autoremesher_core`,
  MIT) in a subprocess of Blender's Python, so a native crash cannot take Blender or the MCP session down. Blocks
  until done (MCP-friendly, `timeout`), `mode: probe` reports whether this Blender can load it and which zip to
  install. Options: adaptivity, edge scaling, sharp edges, smooth normals, island detail, preserve thin features,
  hard surface, voxel `weld_shells`. Budget fitting: the core's count is approximate and shape-dependent
  (63k-tri inputs: Suzanne at adaptivity 1 plateaus far below the target, 32k → 3.6k quads; a thin tube at
  adaptivity 0 stays at 3–8k whatever the request). The script re-scales the request until faces land within
  ±20% (`fit_target`, `max_passes`), switches adaptivity 0 ↔ 1 when the count stops following the request,
  drops `preserve_thin` with a warning when still over budget (`budget_strict`), and caps all passes with
  `total_timeout`. Independent implementation — none of the extension's GPL-3.0 add-on code is
  included, and the extension is never bundled or downloaded by the scripts.
- `deform_mesh.py` `remesher: quadriflow | autoremesher | auto` (+ `autoremesher` options); `auto` falls back to
  QuadriFlow when the extension is missing or fails, and the result reports `remesh.used` / `remesh.fallback`.
  Output spec `geometry.remesher`.
- `production/tests/run_autoremesh_tests.py` — probe, error path, fallback (always run); sphere, deform mesh with
  a joint, weld shells (skipped without the extension).
- **Material Maker maps** — `production/scripts/blender/material_maker.py` runs the user-installed
  [Material Maker](https://github.com/RodZill4/material-maker) (MIT) command-line export on a `.ptex` graph (an
  example by name or the user's file). It overrides node parameters (`params`) and exposed controls (`controls`) in
  a copy of the graph, then builds a glTF-ready material the way `bake_maps.py` does: Principled BSDF, ORM split,
  glTF occlusion group, and tiling exported as `KHR_texture_transform`. Profiles: `GLTF/Plane` (albedo/ORM/normal/
  emission) and `Blender` (separate roughness/metal/occlusion EXR). Modes: probe, list, export, material
  (from maps on disk) and apply. Guide: `materials/references/material-maker.md`.
- `production/tests/run_material_maker_tests.py` — overrides, material + glTF export check, CLI contract against a
  stand-in executable (always run); real export (skipped without the app).
- **Video motion capture (MoCapAnything V2)** — `production/scripts/blender/mocap_capture.py` runs the
  user-installed [MoCapAnything V2](https://github.com/kehong-gong/MoCapAnything) (MIT) on a clip in its own
  Python environment (`production/scripts/motion/mocapanything_runner.py`, separate process; Blender never imports
  torch), imports the BVH and retargets it onto a project rig. Animals first: the demo data has 80 reference
  skeletons (cat, dog, horse, birds, reptiles, insects …); the video may show another animal than the rig.
  - Runner: one clip, trimmed / resampled / downscaled with ffmpeg first; device auto (CUDA, else Apple MPS,
    else CPU); upstream's hard-coded `.cuda()` calls redirected and DINOv2 run in float32 off CUDA; BVH written
    with the clip's real frame rate (upstream writes 30 fps regardless). Measured on an M1 Pro: 2 s clip at
    15 fps in 30 s on MPS / 66 s on CPU (same result to 1e-5); a 10 s 1080p clip in about 7 min on CPU.
  - Modes: probe, rigs, capture (`wait: false` + `status` for long runs), import, bones (both hierarchies and a
    suggested map), retarget, apply.
  - Retarget: world-space rotation change from rest per mapped bone, so names, rolls, scale and facing may
    differ (facing fitted automatically). Automatic bone map by role and side, chains resampled; on generated
    Rigify rigs only controls are targets (FK limbs, FK spine, neck, head, tail), `IK_FK` keyed to FK, and
    additive Copy Rotation chains (tail) corrected iteratively. `error_deg` reports how closely each bone follows.
    Rigify cat metarig from the demo cat clip: 61 bones, max error 0.04°.
- `production/tests/run_mocap_tests.py` — bone roles, auto map, retarget between synthetic armatures with
  different names/rolls/facing/scale (checked against world bone directions), frame offset, BVH import, status
  log, missing install (always run); a real 2 s capture (`{"real": True}`, skipped without the install).

### Changed
- `retopology`, `deformation-prep` (`joint-loop-rules.md`), `production-mode.md` and `docs/BLENDER_MCP_SETUP.md`
  document when to choose AutoRemesher over QuadriFlow and how to install it.
- `materials` skill and `docs/BLENDER_MCP_SETUP.md` document Material Maker (when to use it, install, limits).
- `animation`: new `references/video-mocap.md`; `reference-driven-motion.md` §5 now points to the optional capture
  path instead of "can be added later". `docs/BLENDER_MCP_SETUP.md` documents the MoCapAnything install.
- **Review viewer at visual gates** (`production-mode.md` §7a, `review-notes.md → Agent Self-Check`): before
  G4a, G4c, G5 and delivery the agent publishes the model, opens the local viewer and checks it itself (surface
  modes, weights per joint bone, clip frames at key poses and motion-QA marks, close-ups), records problems as
  `author: "agent"` notes, fixes and re-checks; then asks the user in the approval question whether to open the
  viewer for them. Standing answer kept in `PROJECT.md` §3 (template line added). The server is stopped when the
  gate closes. Found in the dog test run: the viewer was never opened, the user only saw screenshots.

---

## [1.6.0] — 2026-11-22

Rigging, animation and meshing efficiency. Methods studied in elithril/blender-kiln (MIT), aresdevo/animaide
(GPL-3) and Arminando/GameRig (GPL-2); everything here is an independent implementation — no GPL code is included.

### Added
- **`anim_curves.py`** — Graph Editor moves as MCP calls (AnimAide-style): tween, blend to neighbour / frame / rest,
  push-pull, smooth, ease, scale, time offset, wave/noise, anim offset with falloff mask (`delta` or `from_pose`),
  chain overlap (`follow`: delayed driver rotation carried through rest orientations; `delay`), `match_cycle`
  (closing key = first, quaternion signs fixed), `loop_window` (best looping window of a generated/mocap clip →
  new action, cross-faded, root drift removed), resample, clean, interpolation, backup/restore
  (`animation/references/curve-polish.md`)
- **`motion_qa.py`** — kiln's motion measures for G5 on any rig: limb reach vs rest length, knee/elbow pops,
  per-bone jitter, skin under the floor, standing foot pitch, loop seam ratio and closing key; limbs found by name
  (Rigify, Mixamo, kiln) (`animation/references/motion-quality.md`)
- **`game_skeleton.py`** — audit (deform roots, deform bones under ORG/MCH, B-Bones, stretch, deform scale in clips,
  >4 influences, unweighted, dead bones, kiln's verts-per-bone density) and `export_rig`: a deform-only armature with
  one root (following the control root), hierarchy rebuilt through ORG twins (Rigify's reversed tails handled),
  no B-Bones, location+rotation only, clips baked, meshes copied or retargeted, parity reported
  (`rigging/references/game-ready-skeleton.md`)
- **`mesh_cleanup.py`** — kiln's cleanup order with bmesh (weld, loose, degenerate, holes, normals, n-gons,
  transforms, guarded decimate, origin at base), before/after counts incl. duplicate vertices and components,
  decimate undone and relaxed (up to 2× target) when it opens the mesh, `protect_group`, print mode, tier budgets,
  T/A/I pose measure (`blender-modeler/references/mesh-cleanup.md`)
- **Review notes** — `production/review/viewer.html` + `production/scripts/review/serve.py` (stdlib, 127.0.0.1 only,
  non-localhost Host refused) + `review_notes.py` (`publish` with current/previous GLB and a frame manifest, `serve`,
  `stop`, `context`, `reply`, `view`). The user clicks the model to inspect a point (Blender rest/posed coordinates,
  object, interpolated skin weights, Blender frame) and pins notes; `context` turns each into vertex indices, region
  weights, nearest deform bones and a posed check; replies show under the note. Views: lit/clay/normals/weights per
  bone, wire, skeleton, floor, A/B side by side, motion_qa frames on the timeline. A reduced take on blender-kiln's
  Studio: no phone/AR sharing, no agent launched from the page (`qa-review/references/review-notes.md`)
- `production/tests/run_v16_tests.py` — procedural regression tests for the five scripts (throw-away scene)

### Measured
- Project cat, existing `AN_walk` (Rigify, 11.9 k vertices): `motion_qa` found hind legs at 98.6 % reach, 8 knee
  pops and 10.3° jitter (invisible on stills); `anim_curves smooth` → 96 %, 0 pops, 5.7°
- Same rig: glTF skin exported from the control rig had 16 root joints; from `game_skeleton` export rig 1 root,
  49 joints, parity 0.000 mm bone heads / 0.006 mm skin over both baked clips
- Review notes on the project cat: a click at walk frame 22 resolved to a vertex 1.3 mm away with a 1.3 mm posed
  check; the same click showed `DEF-ear.R` weighting 19 % of the neck
- Project dog (Tripo, 1.92 M triangles, 128 pieces, 20,758 doubled vertices): `mesh_cleanup` → 20 K triangles,
  1 piece, open edges 41,081 → 2, 65 s

### Changed
- `animation`, `rigging` (1.2.0), `blender-modeler` (1.1.0), `export-pipeline`, `deformation-prep`: new references
  and MCP steps; Production Mode G2/G5/G6 rows list the new checks
- References **188 → 193**

### Fixed (found while building the tests)
- Blender 5 creates F-curves only for an assigned action slot: `anim_curves` assigns temporarily and restores
- `EditBone.matrix` assignment flipped some rolls by ~180° when copying a rest pose; export rig copies head/tail
  and aligns roll to the source Z axis, and refuses a rest pose that differs (> 0.01° / mm)

---

## [1.5.0] — 2026-11-20

### Added
- **Any model, analysis first:** `production/scripts/blender/structure_analysis.py` measures parts, shape classes, ground contacts, a skeleton of protrusions, symmetry and wheels (separate or fused) without names or presets, scores motion archetypes (rigid_whole, rigid_parts, chain_flex, skinned, morph) and generates only the questions the measurement cannot settle (`blender-director/references/motion-analysis.md`)
- **New motion types:** `rigid_rig.py` (ball: roll/squash/spin; vehicle: body, wheels, steering, optional cut of fused wheels), `chain_rig.py` (plants, snakes, ropes along the measured skeleton), generators `ball_roll`, `ball_bounce`, `ball_throw` (drop/toss, bounces away, rolls to a stop), `vehicle_drive`, `wind_sway`
- `preview_render.py`: `follow_bone` for clips whose root travels (camera follows horizontally, ground grows with the travel), `checker_m`; framing taken from the rest pose
- Test asset: procedural baseball (regulation size, seam and 108 chevron stitches)
- **Project memory and rebuild:** every project gets `PROJECT.md` (model, status, the user's constraints and preferences, decisions, changelog, open issues — read first, updated after every change) and `working/recipe.json` (repo scripts + arguments that rebuild it); `production/scripts/blender/run_recipe.py` replays a recipe and logs `reports/recipe_run.json`. Tested by rebuilding the baseball project from its files alone (identical impacts and travel; G6 0 errors, G7 0.71 mm)
- `skin_weights.py`: distance-weight fallback when bone heat fails
- `production/tests/`: procedural test assets (ball, car as parts and fused, tree, chest, snake) with `run_structure_tests.py` and `run_rig_tests.py`

### Changed
- Category presets are priors: plans come from the structure analysis and the user's answers (`plan.yaml → decisions`); `output-spec.yaml asset.category` is optional
- `runtime_check.mjs` (G7) checks rigid (bone-parented) meshes, matches samples by mesh name and fails clips that do not move

---

## [1.4.0] — 2026-11-20

### Added
- **Production Mode** in `blender-director`: spec-driven conversion of an existing model into a deliverable — modes ANALYZE / PLAN / PREVIEW / PRODUCTION / VALIDATE / EXPORT, gates G0–G8, checkpoints and `state.json` resume (`blender-director/references/production-mode.md`, `references/production-spec.md`)
- **New skills:** `asset-intake` (import + measure → input spec, G0), `deformation-prep` (joint analysis, deform mesh with joint loops, rigid parts, template fitting, weights, ROM test — G4a–G4c), `web-export` (glTF-Transform, glTF-Validator, headless three.js check — G6–G7)
- **Reference-driven motion:** ask for a video/GIF/description when a clip has no source, imitate it with parametric generators (`animation/references/reference-driven-motion.md`)
- **`production/` toolkit:** spec templates, web presets (mobile/desktop/hero), category presets (human, dog, cat, parrot, book, box, chair, table), bird metarig, Blender scripts run through MCP (`intake`, `rig_fit`, `deform_mesh`, `joint_analysis`, `mesh_metrics`, `bake_maps`, `skin_weights`, `rom_test`, `hinge_rig`, `anim_check`, `export_glb`, `sample_vertices`), motion generators + frame extraction, Node tools (`optimize`, `validate_gltf`, `runtime_check`), gate runner and `project_init`
- `production/scripts/blender/preview_render.py` — preview clips of a rigged asset in a separate scene (copies, ground, lights, follow camera, root motion, chunked rendering)
- Reference-driven walk from a GIF (cat): `chain_curve` generator for slow tail/head layers with per-step oscillations; `quadruped_walk_fk` gains `cycles`, per-end lift and paw curl, and `swing_lift_peak` (lift early, reach forward low); `skin_weights.py` `transfers` move limb weight to body bones beyond a plane or inside a region; `preview_render.py` `background` / `ground_colors` to match a source backdrop
- Limb-junction skinning for chubby, short-legged characters: `helper_bones.py` (half-rotation helper deform bones at hips and shoulders), `skin_weights.py` `refine` (helper re-mapping, upper-segment share, side split, capsules), `deform_check.py` (folds, flipped faces and collapsed edges over real clips, clustered with their weights); `deformation-prep/references/limb-junctions.md`. Kitten walk: fold vertices 599 → 142, visible belly/chest creases removed
- `scripts/check_skills.py` (pack validator) and `scripts/sync-skills.sh` / `.ps1`
- `docs/PRODUCTION_MODE.md` — user guide (requirements, decisions, outputs, troubleshooting)
- `docs/BLENDER_MCP_CAPABILITIES.md` — MCP operations verified on Blender 5.3 plus an end-to-end run on a 1.9 M-triangle model

### Changed
- Skills and references use the **official Blender Lab MCP** tool names (`execute_blender_code`, `get_objects_summary`, `get_screenshot_of_area_as_image`, …) with a mapping for the community `blender-mcp` server; `docs/BLENDER_MCP_SETUP.md` rewritten for both
- `animation`, `rigging`, `retopology`, `texture-workflow`, `uv-workflow`, `qa-review`, `export-pipeline` extended for Production Mode (1.1.0)
- `bake_maps.py` picks the GPU automatically (Metal/CUDA/OptiX/HIP/oneAPI)
- Skill count **94 → 97**; references **175 → 188**

### Removed
- Plugin root `.mcp.json` (Windows-only `cmd /c uvx blender-mcp`, collided with the official add-on on port 9876); configure the MCP server in your client

### Fixed
- `dream-weirdcore-style` related skill `surreal-mood` → `dream-surreal-mood`
- QUICKSTART plugin install id (`blender-skills@blender-skills`)
- Front paws skewed to one side (user report): Rigify paw helpers assume a -Y-facing character; `rig_fit.py` now generates in that orientation and turns the rig back, and disables Rigify's paw auto-tracking (not neutral at rest) — IK and FK rest poses match the bind pose
- Walk on short legs (user report: crossing legs, twisted paws): new `quadruped_walk_fk` generator — planar two-bone IK on FK controls with body compensation; generators key `IK_FK` per clip (`ikfk`); `anim_check.py` takes `root_velocity` for in-place cycles; `export_glb.py` unhides objects so a hidden armature is not dropped
- `preview_render.py` cleared the copied rig's animation data and with it Rigify's drivers, so previews showed nearly static legs; it now keeps the drivers and refuses a copy whose drivers still point at the source rig
- `sample_vertices.py` resets the pose before each clip — a bone keyed only in an earlier clip kept that value in the Blender samples (15 mm false difference on the cat walk tail in G7)
- Skewed paws after limb-junction skinning (user report): `refine` counted toe bones as body and re-mapped paws to the hip helper; every deform descendant of a limb is now limb. G4b reports and fails on far weights (vertices weighted to distant bones)
- Found by the end-to-end test and fixed in the scripts: Rigify rig displaced from the mesh (metarig location not applied), twisted control rolls after fitting, "disjoint chain" Rigify errors after moving joints, QuadriFlow refusing small assets, faceted normal bakes, B-Bones breaking Blender↔three.js parity, empty extra glTF scene, missing tangents, work actions exported as clips, ROM test not moving IK limbs, G4b passing collapsed weights, G2/G3 gate files never written

---

## [1.3.0] — 2026-07-10

### Added
- Deep `references/` docs for production skills (prop, vehicle, hair, cloth, VFX, camera, compositing, physics, engine exports, LOD, collision, scene, QA, styles, vegetation, set-dressing, archviz, lookdev)
- **Extended art styles:** cartoon, comic-book, manga, pixel-art, hand-painted, painterly, stop-motion-craft, chibi, noir, minimalist, vector, retro-8bit, retro-16bit, hd-2d, frutiger-aero
- **Horror packs:** cosmic-eldritch, body-horror, analog-found-footage, liminal-space, folk-horror, mascot-puppet, dream-weirdcore, indie-horror-aesthetics
- **Worlds:** fantasy-worlds, sci-fi-punk-worlds, historical-worlds, apocalypse-worlds, biome-worlds
- **Moods:** cozy-wholesome, dark-gritty, dream-surreal, neon-retrofuturism, brutalist
- **Gameplay genre direction:** action-combat, shooter, rpg, survival, stealth, puzzle-platformer, metroidvania-roguelike, soulslike, strategy-sim, racing-sports, narrative-vn, card-party-idle, open-world-sandbox
- **character-archetypes**, **visual-console-eras**
- Subtype coverage map in `SKILLS_GUIDE.md` (genres/styles map into pack skills + refs)

### Changed
- Skill count **46 → 94**; references **~40 → 175**
- `blender-director` routing expanded for genre/style/world/mood packs

---

## [1.2.0] — 2026-07-10

### Added
- **Modeling:** `prop-artist`, `vehicle-artist`, `vegetation-artist`
- **Character / sim:** `hair-groom`, `cloth-sim`
- **Technical:** `vfx-fx`, `camera-cinematography`, `compositing`, `physics-sim`, `lookdev`
- **Pipeline:** `unity-export`, `unreal-export`, `godot-export`, `lod-pipeline`, `collision-proxy`, `scene-assembly`, `set-dressing`, `qa-review`, `archviz`
- **Styles:** `anime-style`, `voxel-style`, `isometric-style`, `psx-horror-style`
- Expanded `blender-director` routing tables and multi-skill workflows
- Updated `SKILLS_GUIDE.md` decision trees for new disciplines and engines

### Changed
- Skill count **23 → 46** (`version.json`, README, plugin metadata)
- `hard-surface` now defers dedicated vehicles to `vehicle-artist`
- `skill-routing.md` engine targets point at Unity/Unreal/Godot export skills

---

## [1.1.0] — 2026-07-05

### Added
- `references/reference-image-match.md` — Full photo/concept-art-to-Blender workflow
- `references/reference-analysis-template.md` — Mandatory pre-flight analysis form for reference tasks
- `references/visual-match-checklist.md` — Pass/fail validation vs reference image
- Reference image routing added to `blender-director` SKILL.md
- Screenshot comparison loop protocol in `mcp-integration.md`
- Visual match section in `validation-checklist.md`
- `docs/local_skill_development.md` — Guide for adding custom skills
- `CONTRIBUTING.md` — Contribution guidelines
- `CHANGELOG.md`, `LICENSE`, `.gitignore`, `version.json`, `ROADMAP.md`
- Reference image workflow added to `SKILLS_GUIDE.md`, `README.md`, `CLAUDE.md`

### Changed
- `blender-director` — Now detects attached reference images and routes to match workflow
- `asset-pipeline.md` — Reference collection phase now covers photo analysis
- `rendering` SKILL.md — AgX grading and EEVEE preview settings for animation playback documented
- `skill-routing.md` — Reference phase added to production phase table
- `QUICKSTART.md` — Reference task routing added to cheat sheet
- All SKILL.md frontmatter updated to follow Jeffallan schema (description formula, metadata fields)
- `plugin.json` / `marketplace.json` — Author field updated; keywords expanded

### Fixed
- White hull blowout: documented per-object light material pattern; shared structural material animation flagged as anti-pattern
- EEVEE playback blur: taa_samples + motion blur off pattern documented in rendering skill

---

## [1.0.0] — 2026-07-05

### Added
- 23 specialist skills: `blender-director`, `blender-modeler`, `hard-surface`, `environment-artist`, `character-artist`, `creature-artist`, `sculpting`, `retopology`, `uv-workflow`, `materials`, `texture-workflow`, `geometry-nodes`, `lighting`, `rendering`, `animation`, `rigging`, `procedural-modeling`, `asset-optimization`, `export-pipeline`, `horror-style`, `lowpoly-style`, `stylized-style`, `realistic-style`
- Shared references: `asset-pipeline.md`, `mcp-integration.md`, `mcp-tools.md`, `naming-conventions.md`, `polycount-budgets.md`, `validation-checklist.md`
- Blender MCP integration (`.cursor/mcp.json`, `.mcp.json`)
- `SKILLS_GUIDE.md` — Decision trees and workflow combinations
- `QUICKSTART.md` — Installation for Claude Code and Cursor
- `docs/BLENDER_MCP_SETUP.md` — Full MCP connection guide
- `CLAUDE.md` — Agent instructions
- `.claude-plugin/` — Claude Code plugin manifest
