#!/usr/bin/env python3
"""Create a Production Mode project workspace (runs with plain Python 3.9+, outside Blender).

    python3 production/scripts/project_init.py --workspace ~/3d-production-workspace \
        --name calico_cat --source /path/to/calicocat_3d.glb [--preset web-desktop] [--category cat]

Creates projects/<name>/{input,working,output,textures,reports,checkpoints}, COPIES the source into
input/ (the original is never moved or modified), records its SHA-256, and writes:
  output-spec.yaml   (template, with preset/category values merged when given and PyYAML is available)
  plan.yaml          (template)
  state.json         (empty stage table)
Existing projects are never overwritten; re-running only fills in missing files.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TPL = os.path.join(REPO, "production", "templates")
PRESETS = os.path.join(REPO, "production", "presets")
SUBDIRS = ("input", "working", "output", "textures", "reports", "checkpoints", os.path.join("input", "motion"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def deep_merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--preset", help="web-mobile | web-desktop | web-hero (file in production/presets)")
    ap.add_argument("--category", help="file in production/presets/categories")
    a = ap.parse_args(argv)

    src = os.path.abspath(os.path.expanduser(a.source))
    if not os.path.isfile(src):
        sys.exit(f"source not found: {src}")
    proj = os.path.join(os.path.abspath(os.path.expanduser(a.workspace)), "projects", a.name)
    for d in SUBDIRS:
        os.makedirs(os.path.join(proj, d), exist_ok=True)

    dst = os.path.join(proj, "input", os.path.basename(src))
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
    src_hash, dst_hash = sha256(src), sha256(dst)
    if src_hash != dst_hash:
        sys.exit(f"input/{os.path.basename(src)} exists but differs from the source; refusing to continue")

    manifest_path = os.path.join(proj, "input", "MANIFEST.json")
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"files": {}}
    manifest["files"][os.path.basename(dst)] = {"sha256": dst_hash, "bytes": os.path.getsize(dst),
                                                "copied_from": src, "copied_at": datetime.now().isoformat()}
    json.dump(manifest, open(manifest_path, "w"), indent=2)

    spec_path = os.path.join(proj, "output-spec.yaml")
    if not os.path.exists(spec_path):
        text = open(os.path.join(TPL, "output-spec.yaml")).read()
        merged_note = ""
        if a.preset or a.category:
            try:
                import yaml  # optional
                spec = yaml.safe_load(text)
                if a.preset:
                    p = yaml.safe_load(open(os.path.join(PRESETS, f"{a.preset}.yaml")))
                    p.pop("preset", None)
                    deep_merge(spec, p)
                if a.category:
                    spec["asset"]["category"] = a.category
                spec["asset"]["name"] = a.name
                text = ("# Output Specification for %s — generated from template + preset %s; edit freely.\n"
                        % (a.name, a.preset or "-")) + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
            except ImportError:
                merged_note = "PyYAML not installed: template copied unchanged; copy preset values by hand"
        open(spec_path, "w").write(text)
        if merged_note:
            print(merged_note)

    plan_path = os.path.join(proj, "plan.yaml")
    if not os.path.exists(plan_path):
        shutil.copy2(os.path.join(TPL, "plan.yaml"), plan_path)

    state_path = os.path.join(proj, "state.json")
    if not os.path.exists(state_path):
        json.dump({"schema": 1, "project": a.name, "mode": "ANALYZE", "stages": {},
                   "last_good_checkpoint": None, "created_at": datetime.now().isoformat()},
                  open(state_path, "w"), indent=2)

    print(json.dumps({"ok": True, "project_dir": proj, "input": dst, "sha256": dst_hash}, indent=2))


if __name__ == "__main__":
    main()
