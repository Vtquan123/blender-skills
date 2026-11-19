# Production Report: {{asset.name}}

Generated: {{timestamp}} · Blender {{blender_version}} · Repo commit {{repo_commit}}

## Source
- File: {{source.file}} ({{source.bytes}} bytes, sha256 {{source.sha256}}) — unchanged: {{input_checksums_ok}}
- Measured: {{geometry.triangles_total}} tris, {{geometry.components_welded}} component(s) after weld, textures {{textures_summary}}

## Plan
Strategy {{strategy}}; stages run: {{stages_run}}. Approved by {{plan.approved_by}} at {{plan.approved_at}}.

## Gates
| Gate | Status | Key metrics vs thresholds | Evidence |
|------|--------|---------------------------|----------|
{{gates_table}}

## Deliverables
| File | Bytes | Triangles | Draw calls | Texture memory | Clips |
|------|-------|-----------|------------|----------------|-------|
{{deliverables_table}}

Optimise command: `{{optimize_command}}`

## Open issues
{{open_issues}}
