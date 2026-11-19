# Production Brief: {{asset.name}}

**Source:** {{source.file}} — {{geometry.triangles_total}} tris, {{textures_summary}}
**Category / family:** {{asset.category}} / {{family}}
**Target:** {{target.platform}} ({{target.renderer}}), devices: {{target.devices}}
**Budgets:** tris {{budgets.triangles}} · bones {{budgets.max_bones}} · influences {{budgets.max_influences}} · textures {{budgets.textures.max_size}} {{budgets.textures.format}} · file {{budgets.file_size_mb}} MB
**Strategy:** {{strategy}}

## Stages
| Stage | Enabled | Skill | Gate | Notes |
|-------|---------|-------|------|-------|
{{stages_table}}

## Clips
| Clip | Loop | Source | Status |
|------|------|--------|--------|
{{clips_table}}

## Risks / open questions
{{open_questions}}

## Approval
- [ ] User approves this plan (G1)
