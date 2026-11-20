# Production Spec Schemas

> Reference for: blender-director, asset-intake, deformation-prep, web-export, qa-review
> Load when: reading or writing input-spec, output-spec, plan, motion-brief or state files

Templates with every field live in `production/templates/`. This page explains the rules.

## General Rules

- **Measured vs declared.** `input-spec.yaml` is measured by `asset-intake`; nobody types values into it by hand. `output-spec.yaml` is declared by the user.
- **Unknown is explicit.** A value that could not be measured is the string `unknown`, never a guess and never omitted.
- **No hidden defaults.** A `null` in `output-spec.yaml` means "not decided". The director asks before a step that depends on it, or records it as "report only" for gates.
- **Units:** metres, degrees, seconds, pixels, megabytes (MB = 10^6 bytes).
- **Presets** (`production/presets/*.yaml`, `production/presets/categories/*.yaml`) are starting values the user copies into `output-spec.yaml`; skills never read a preset as if it were the spec.

## input-spec.yaml (measured)

| Field | Meaning |
|-------|---------|
| `source.file`, `source.format`, `source.bytes`, `source.sha256` | Original file identity (used by G8 to prove it was not changed) |
| `scene.objects[]` | name, type, parent, triangles, vertices, materials, uv_layers, shape_keys, vertex_groups, modifiers |
| `geometry.triangles_total`, `geometry.components_raw`, `geometry.components_welded` | Totals before/after seam weld |
| `geometry.boundary_edges_welded`, `geometry.nonmanifold_edges_welded` | Open/non-manifold edges after weld |
| `geometry.dimensions_m`, `geometry.bbox_min`, `geometry.bbox_max` | World-space size as imported |
| `geometry.quads_ratio` | Share of quads (0 for triangle soup) |
| `materials[]` | name, linked principled inputs, blend method |
| `textures[]` | name, width, height, colorspace, format |
| `rig.armatures[]`, `rig.bones_total` | Existing skeletons |
| `animation.actions[]` | Existing clips: name, frame range |
| `hints.category_guess`, `hints.forward_axis_guess`, `hints.up_axis_guess`, `hints.pose_hint`, `hints.generator_hint` | Heuristics, each with a `confidence` 0–1; user confirms at G0/G1 |
| `issues[]` | Measured problems (e.g. `split_on_uv_seams`, `missing_texture`, `scale_not_applied`) |

## output-spec.yaml (declared)

| Section | Key fields |
|---------|-----------|
| `asset` | `name`, `category` (matches a file in `presets/categories/`), `real_size_m` |
| `target` | `platform` (`web`, `unity`, `unreal`, `godot`, `generic`), `renderer`, `devices` |
| `budgets` | `triangles`, `max_bones`, `max_influences`, `textures.max_size`, `textures.format`, `materials`, `draw_calls`, `file_size_mb` |
| `geometry` | `strategy` (`auto`, `keep`, `decimate`, `remesh`, `retopo`), `preserve` |
| `surface` | `bake_maps` (`normal`, `ao`, `orm`, `basecolor`), `uv` (`keep`, `repack`, `new`) |
| `rig` | `required` (`auto`, `true`, `false`), `method` (`existing`, `rigify`, `custom_template`, `unirig`, `rigid_parts`, `none`), `template`, `rigid_parts` |
| `animation` | `fps`, `clips[]` → `name`, `loop`, `duration_s`, `root_motion`, `source` |
| `lod` | `levels[]` → `ratio` or `triangles`, `screen_size` |
| `compression` | `geometry` (`meshopt`, `draco`, `none`), `textures` (`ktx2`, `webp`, `none`) |
| `acceptance` | thresholds per gate (`G2.silhouette_max_dev`, `G4c.volume_loss_max`, `G7.file_size_mb_max`, …) and `approve_at` |

### Clip source

```yaml
source:
  type: none | video | gif | images | motion_file | text
  path: input/motion/walk.mp4     # for video/gif/images/motion_file
  trim: [start_s, end_s]          # optional
  description: "..."              # for text, or notes on other types
  status: requested | provided | briefed | built | approved
```

`type: none` makes the director pause the animation stage and send a source request (see `animation/references/reference-driven-motion.md`).

## plan.yaml (director)

```yaml
project: calico_cat
strategy: skinned/quadruped         # archetype from reports/structure.json (structure_analysis.py), confirmed by the user
structure: reports/structure.json
decisions:                          # answers to the analysis questions (never asked twice on resume)
  - {id: forward, answer: X, by: user, at: 2026-11-20T15:00}
  - {id: clips, answer: [idle, walk], by: user}
stages:
  - {id: intake,    enabled: true,  skill: asset-intake,     gate: G0}
  - {id: geometry,  enabled: true,  skill: deformation-prep, gate: G4a, params: {method: retopo}}
  - {id: surface,   enabled: true,  skill: texture-workflow, gate: G3}
  - {id: rig,       enabled: true,  skill: deformation-prep, gate: [G4b, G4c]}
  - {id: animation, enabled: true,  skill: animation,        gate: G5}
  - {id: lod,       enabled: false}
  - {id: export,    enabled: true,  skill: web-export,       gate: [G6, G7]}
approvals: [G1, G4a, G4c]
open_questions: []
```

## motion-brief.yaml (animation)

Written after reading a source; edited by the user; drives the motion generators.

```yaml
clip: walk
source: input/motion/walk.mp4
cycle_s: 0.9
loop: true
key_poses:
  - {t: 0.00, name: contact_L, notes: "left fore paw down"}
  - {t: 0.45, name: contact_R}
params: {stride: 0.6, bounce: 0.15, head_bob: 0.1, tail_sway_deg: 12}
tolerance: {cycle_s: 0.05, amplitude_ratio: 0.2}
```

## state.json

See `blender-director/references/production-mode.md` §5.
