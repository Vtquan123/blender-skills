#!/usr/bin/env python3
"""Validate the Blender Skills pack.

Checks every skill under .claude/skills/:
  * frontmatter parses and has the required fields (CONTRIBUTING.md schema)
  * `name` matches the folder name
  * every `related-skills` entry is an existing skill
  * every referenced file path (references/*.md, ../other/references/*.md,
    docs/*, production/*) resolves
  * .cursor/skills/ is an exact mirror of .claude/skills/ (unless --no-mirror)

Usage:
  python3 scripts/check_skills.py            # from the repo root
  python3 scripts/check_skills.py --json     # machine-readable report
  python3 scripts/check_skills.py --sections # also report missing schema sections
Exit code 0 = no errors (warnings allowed), 1 = errors found.
Needs Python 3.8+. PyYAML is used when installed, otherwise a small
built-in frontmatter parser handles the flat schema used by this pack.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILLS = os.path.join(ROOT, ".claude", "skills")
MIRROR = os.path.join(ROOT, ".cursor", "skills")
SHARED = "references"  # shared reference folder inside .claude/skills/

REQUIRED_TOP = ("name", "description", "license", "metadata")
REQUIRED_META = ("author", "version", "domain", "role", "triggers", "related-skills")
RECOMMENDED_SECTIONS = ("Role Definition", "When to Use", "Core Workflow", "Constraints")

# Paths written in backticks or markdown links that look like repo files.
PATH_RE = re.compile(
    r"(?:`|\]\()"
    r"((?:\.\./|\./)*(?:[\w.-]+/)*(?:references|docs|production|scripts|\.claude|\.cursor)/[^`)\s]*?"
    r"\.(?:md|py|mjs|js|json|yaml|yml|ps1|sh))"
    r"(?:`|\)|#)"
)
ROOT_PREFIXES = ("docs/", "production/", "scripts/", ".claude/", ".cursor/", ".claude-plugin/")


def parse_frontmatter(text: str):
    if not text.startswith("---"):
        return None, "missing frontmatter"
    end = text.find("\n---", 3)
    if end < 0:
        return None, "unterminated frontmatter"
    block = text[3:end].strip("\n")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block)
        if not isinstance(data, dict):
            return None, "frontmatter is not a mapping"
        return data, None
    except ImportError:
        pass
    except Exception as exc:  # yaml error
        return None, f"frontmatter YAML error: {exc}"
    data: dict = {}
    current = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        val = val.strip().strip('"').strip("'")
        if indent == 0:
            if key in data:
                return None, f"duplicate key '{key}'"
            data[key] = val if val else {}
            current = key if not val else None
        elif current is not None:
            if key in data[current]:
                return None, f"duplicate key '{current}.{key}'"
            data[current][key] = val
    return data, None


def split_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def resolve(ref: str, file_dir: str, skill_dir: str) -> bool:
    if any(ch in ref for ch in "*?{<") or "NN_" in ref or "<" in ref:
        return True  # glob or template placeholder
    ref = ref.split("#")[0]
    candidates = [
        os.path.join(file_dir, ref),
        os.path.join(skill_dir, ref),
        os.path.join(SKILLS, ref),
        os.path.join(SKILLS, SHARED, os.path.basename(ref)) if ref.startswith("references/") else None,
    ]
    if ref.startswith(ROOT_PREFIXES):
        candidates.append(os.path.join(ROOT, ref))
    return any(c and os.path.exists(os.path.normpath(c)) for c in candidates)


def check_refs(path: str, skill_dir: str, errors: list, rel: str):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    # skip fenced code blocks: paths there are examples, not links
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for ref in sorted(set(PATH_RE.findall(text))):
        if not resolve(ref, os.path.dirname(path), skill_dir):
            errors.append(f"{rel}: unresolved path `{ref}`")


def tree_hashes(base: str) -> dict:
    out = {}
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if name == ".DS_Store":
                continue
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, base)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print a JSON report")
    ap.add_argument("--no-mirror", action="store_true", help="skip the .cursor/skills mirror check")
    ap.add_argument("--sections", action="store_true",
                    help="also warn when a skill lacks the CONTRIBUTING.md sections (Role Definition, When to Use, ...)")
    args = ap.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    skills = sorted(
        d for d in os.listdir(SKILLS)
        if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md"))
    )
    skill_set = set(skills)
    ref_files = 0

    for name in skills:
        sdir = os.path.join(SKILLS, name)
        smd = os.path.join(sdir, "SKILL.md")
        with open(smd, encoding="utf-8") as fh:
            text = fh.read()
        fm, err = parse_frontmatter(text)
        if err:
            errors.append(f"{name}/SKILL.md: {err}")
            continue
        for key in REQUIRED_TOP:
            if key not in fm:
                errors.append(f"{name}/SKILL.md: missing '{key}'")
        meta = fm.get("metadata") or {}
        if not isinstance(meta, dict):
            errors.append(f"{name}/SKILL.md: 'metadata' is not a mapping")
            meta = {}
        for key in REQUIRED_META:
            if key not in meta:
                errors.append(f"{name}/SKILL.md: missing 'metadata.{key}'")
        if fm.get("name") != name:
            errors.append(f"{name}/SKILL.md: name '{fm.get('name')}' does not match folder")
        if len(str(fm.get("description", ""))) > 1024:
            errors.append(f"{name}/SKILL.md: description longer than 1024 characters")
        for rel in split_list(meta.get("related-skills")):
            if rel not in skill_set:
                errors.append(f"{name}/SKILL.md: related skill '{rel}' does not exist")
        for section in (RECOMMENDED_SECTIONS if args.sections else ()):
            if not re.search(rf"^#+\s+{re.escape(section)}", text, flags=re.M):
                warnings.append(f"{name}/SKILL.md: no '{section}' section")
        check_refs(smd, sdir, errors, f"{name}/SKILL.md")
        rdir = os.path.join(sdir, "references")
        if os.path.isdir(rdir):
            for fname in sorted(os.listdir(rdir)):
                if fname.endswith(".md"):
                    ref_files += 1
                    check_refs(os.path.join(rdir, fname), sdir, errors, f"{name}/references/{fname}")

    shared_dir = os.path.join(SKILLS, SHARED)
    shared_files = 0
    if os.path.isdir(shared_dir):
        for fname in sorted(os.listdir(shared_dir)):
            if fname.endswith(".md"):
                shared_files += 1
                check_refs(os.path.join(shared_dir, fname), shared_dir, errors, f"references/{fname}")

    mirror = None
    if not args.no_mirror and os.path.isdir(MIRROR):
        a, b = tree_hashes(SKILLS), tree_hashes(MIRROR)
        missing = sorted(set(a) - set(b))
        extra = sorted(set(b) - set(a))
        differ = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        mirror = {"missing": missing, "extra": extra, "differ": differ}
        for k in missing:
            errors.append(f".cursor/skills: missing {k} (run scripts/sync-skills)")
        for k in differ:
            errors.append(f".cursor/skills: {k} differs from .claude/skills (run scripts/sync-skills)")
        for k in extra:
            warnings.append(f".cursor/skills: extra file {k} not in .claude/skills")

    report = {
        "skills": len(skills),
        "skill_reference_files": ref_files,
        "shared_reference_files": shared_files,
        "errors": errors,
        "warnings": warnings,
        "mirror": mirror,
        "ok": not errors,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"skills: {len(skills)}  skill references: {ref_files}  shared references: {shared_files}")
        for w in warnings:
            print(f"WARN  {w}")
        for e in errors:
            print(f"ERROR {e}")
        print("OK" if not errors else f"{len(errors)} error(s)")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
