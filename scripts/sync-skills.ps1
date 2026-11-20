# Mirror .claude/skills/ into .cursor/skills/ (Windows PowerShell).
# .claude/skills is the source of truth; files removed there are removed from the mirror.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
robocopy ".claude\skills" ".cursor\skills" /MIR /XF .DS_Store /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
Write-Host "Synced .claude\skills -> .cursor\skills"
