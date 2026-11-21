# Review Notes — the User Points, Claude Gets Exact Data

> A local viewer where the user clicks the model and pins notes; each note is stored as Blender data
> (object, rest and posed coordinates, skin weights, clip and Blender frame, camera) that
> `production/scripts/blender/review_notes.py` turns into vertex indices, bones and a frame.
> Replaces "the left ear looks wrong" + a screenshot with a point Claude can act on.
> Idea from blender-kiln's Studio (MIT), reduced to the review loop: no phone/AR sharing, no agent
> launched from the page, no network access — the server binds 127.0.0.1 only.

## Files

| File | Role |
|---|---|
| `production/review/viewer.html` | three.js viewer (local `node_modules/three` when installed, else the CDN) |
| `production/scripts/review/serve.py` | stdlib server: `/project/…` read-only, `POST /api/note`, rejects non-localhost hosts |
| `production/scripts/blender/review_notes.py` | `publish`, `serve`, `stop`, `context`, `reply`, `view` |
| `<project>/review/current.glb`, `previous.glb` | what the viewer shows (A) and the version before (B, side by side) |
| `<project>/review/manifest.json` | fps and each clip's action + `frame_start` (frame mapping) |
| `<project>/review/notes.json` | the notes — commit them with the project |

## Loop

```
1. review_notes mode=publish  project_dir=projects/<name>  objects=[rig, mesh]  clips=[AN_*]
2. review_notes mode=serve    → http://127.0.0.1:8765/  (runs inside Blender; tell the user to open it)
3. the user clicks, reads the point panel, pins notes ("📍 Pin a note here", or a note on the whole model)
4. review_notes mode=context  → per open note: region vertex indices, nearest vertex (mm), Blender frame,
                                region weights, nearest deform bones, posed check (mm), warnings
5. fix in Blender (mark=true writes the region into vertex group REVIEW_<id> for the next script)
6. review_notes mode=publish  (current → previous: the viewer opens A/B side by side)
7. review_notes mode=reply    id=… text="what changed" measures={before/after}  → shown under the note
```

Standalone (without Blender running the server):
`python3 production/scripts/review/serve.py --project projects/<name>`.

## What a note holds

| Field | Meaning |
|---|---|
| `object` | Blender object name (original names, dots kept — `DEF-ear.R`, not three.js' sanitised names) |
| `rest_point` | Point on the **undeformed** mesh, Blender world (Z-up) — matches `mesh.vertices` whatever frame it was picked at |
| `posed_point` | Point as seen at that frame |
| `weights` | Skin weights interpolated at the point (top 4 bones); `parent_bone` for rigid parts |
| `clip`, `time_s`, `frame` | glTF clip, time, and the **Blender** frame (`frame_start + time × fps`) |
| `camera` | position, target, fov — `mode=view` puts the Blender viewport there |
| `category`, `text`, `status`, `replies` | the note itself; `scope: model` for notes on the whole model |

## Precision (measured)

- Project cat (Rigify, 11.9 k vertices, walk frame 22): nearest vertex 1.3 mm from the clicked point (a
  point inside a triangle), posed check 1.3 mm — coordinates and frame map exactly; region weights
  identical to the viewer's. The same click exposed `DEF-ear.R` weighting 19 % of the neck.
- Regression test (`run_v16_tests.py review_notes`): a note posted for vertex 50 at frame 12 resolves to
  vertex 50, 0.00 mm, frame 12.0, posed check 0.00 mm.

## Viewer controls

- Click = inspect (no note yet); orbit drags never pin. `n` pins at the inspected point.
- Modes: lit, clay, normals, **weights** (pick a bone; or a note's first bone after "Go").
- Wire, bones (skeleton lines), floor (at the model's lowest rest point), pins, hover readout.
- Timeline shows the Blender frame; red ticks = `reports/motion-qa.json` pops/jitter frames, orange =
  open notes. Space plays, ← → step one frame.

## Rules

- A `warnings` entry about distance means the mesh or rig changed after publishing: republish, ask the
  user to check the note again, never guess the spot.
- Reply on every note you act on, with numbers (before → after); the user resolves or reopens.
- The viewer is for the user's eye; Claude reads `notes.json` and `mode=context`, not screenshots.
