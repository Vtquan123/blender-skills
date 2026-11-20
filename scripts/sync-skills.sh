#!/usr/bin/env bash
# Mirror .claude/skills/ into .cursor/skills/ (macOS / Linux).
# .claude/skills is the source of truth; files removed there are removed from the mirror.
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '.DS_Store' .claude/skills/ .cursor/skills/
else
  rm -rf .cursor/skills
  mkdir -p .cursor
  cp -R .claude/skills .cursor/skills
fi
echo "Synced .claude/skills -> .cursor/skills"
