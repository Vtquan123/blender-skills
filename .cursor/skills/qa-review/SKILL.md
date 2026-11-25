---
name: qa-review
description: Production QA gate for Blender assets using viewport screenshots, validation checklists, naming audits, and ship/no-ship verdicts via MCP.
license: MIT
metadata:
  author: https://github.com/arjun988
  version: "1.2.0"
  domain: blender
  role: specialist
  triggers: QA, quality assurance, review, validation, checklist, screenshot review, ship check, art review, quality gate, gate report
  related-skills: asset-optimization, export-pipeline, blender-director, lookdev, web-export, deformation-prep
---

# QA Review

Screenshot-backed review. Checklist gate. Explicit ship / no-ship.

## When to Use

- Before export or handoff
- After major modeling/lookdev milestones
- Reference-match final compare
- Periodic scene health checks
- Production Mode gates G0–G8 (automated metrics + approvals)

## Automated Gates (Production Mode)

Each stage ends with a gate that compares measured metrics with `output-spec.yaml → acceptance` and writes `reports/gate-<id>.json` (`pass` / `fail` / `needs_review`). Approval gates (G1, G4a, G4c by default) need an explicit user decision recorded in the JSON. Gate list, metrics and producers: `references/production-gates.md`.

## Workflow

```
Gather brief budgets → Screenshot key angles → Run checklists
  → List defects (severity) → Fix or reject → Re-verify → Verdict
```

## Required Screenshots

1. 3/4 hero angle
2. Ortho or profile if proportion-critical
3. Wireframe or poly overview (optional but useful)
4. Material/light beauty
5. Vs reference (if reference task)

Use the MCP viewport screenshot (`get_screenshot_of_area_as_image`, `VIEW_3D`) when connected; frame first with `jump_to_view3d_object_by_name`.

When the user reviews, prefer the review viewer over screenshots: `review_notes.py` publishes the model to a local three.js page where the user clicks and pins notes; each note comes back as Blender data (object, rest/posed point, vertex indices, skin weights, Blender frame, camera) — `references/review-notes.md`. At every visual gate (G4a, G4c, G5, delivery) the agent first checks the model in the viewer itself (surface modes, weights per joint bone, clip frames at key poses and motion-QA marks, close-ups) and records what it finds as `author: "agent"` notes, then asks the user whether to open the viewer for them (`../blender-director/references/production-mode.md` §7a).

## Checklists (load as needed)

- `../references/validation-checklist.md`
- `../references/visual-match-checklist.md` (reference tasks)
- `../references/naming-conventions.md`
- `../references/polycount-budgets.md`

## Defect Severity

| Level | Meaning |
|-------|---------|
| Blocker | Wrong scale, broken normals, fails budget badly |
| Major | Silhouette/readability issues, bad pivots |
| Minor | Naming, minor shading, small gaps |
| Note | Optional polish |

## Verdict Template

```markdown
## QA Verdict: [Asset]

**Result:** SHIP / SHIP WITH NOTES / NO-SHIP
**Budgets:** [tris/textures] vs target
**Screenshots:** [listed]
**Blockers:** ...
**Majors:** ...
**Minors:** ...
**Next actions:** ...
```

## Constraints

### MUST DO
- Give explicit verdict
- Attach or capture screenshots for visual claims
- Re-check after fixes before flipping to SHIP

### MUST NOT DO
- Rubber-stamp without screenshots on visual tasks
- Ignore budget overruns without approval

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|----------|
| Qa Verdict Template | `references/qa-verdict-template.md` | When needed |
| Screenshot Angles | `references/screenshot-angles.md` | When needed |
| Production Gates | `references/production-gates.md` | Production Mode stages |
| Review notes (local viewer, pinned notes → exact vertices, bones, frame) | `references/review-notes.md` | The user reviews a model or clip; feedback on a spot |
