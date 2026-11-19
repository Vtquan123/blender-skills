#!/usr/bin/env python3
"""Gate runner for Production Mode (plain Python 3.9+, outside Blender). Requires PyYAML (pip install pyyaml).

    python3 production/scripts/validation/gates.py plan    --project <projects/name>
    python3 production/scripts/validation/gates.py approve --project <dir> --gate G4a [--note "..."]
    python3 production/scripts/validation/gates.py summary --project <dir>
    python3 production/scripts/validation/gates.py final   --project <dir>

plan    → gate G1: checks output-spec.yaml for the fields the enabled stages need (never fills them in)
approve → records the user's approval on a needs_review gate (approved_by: user + timestamp)
summary → table of all gate files (used in the report)
final   → gate G8: input checksums unchanged (input/MANIFEST.json), every enabled stage has a passing or
          approved gate, report.md exists
Metric-producing scripts (Blender/Node) write the other gates themselves.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: python3 -m pip install pyyaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CATS = os.path.join(REPO, "production", "presets", "categories")


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get(d, dotted):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def write_gate(project, gate):
    path = os.path.join(project, "reports", f"gate-{gate['gate']}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):  # keep history
        n = len(glob.glob(path[:-5] + ".*.json")) + 1
        os.replace(path, path[:-5] + f".{n}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(gate, fh, indent=2, ensure_ascii=False)
    return path


def cmd_plan(a):
    spec = load_yaml(os.path.join(a.project, "output-spec.yaml"))
    missing, conflicts, notes = [], [], []
    for f in ("asset.name", "asset.category", "target.platform", "budgets.triangles", "budgets.textures.max_size"):
        if get(spec, f) in (None, ""):
            missing.append(f)
    cat = get(spec, "asset.category")
    family = None
    if cat:
        p = os.path.join(CATS, f"{cat}.yaml")
        if os.path.exists(p):
            family = load_yaml(p).get("family")
        else:
            conflicts.append(f"no preset production/presets/categories/{cat}.yaml (add one or pick another category)")
    clips = get(spec, "animation.clips") or []
    if family == "creature" or get(spec, "rig.required") is True:
        for f in ("budgets.max_bones", "budgets.max_influences", "asset.real_size_m"):
            if get(spec, f) in (None, ""):
                missing.append(f)
    if family == "static_object" and get(spec, "rig.required") is True:
        conflicts.append("rig.required true but category family is static_object")
    for c in clips:
        st = (c.get("source") or {}).get("type", "none")
        if st == "none":
            notes.append(f"clip '{c.get('name')}' has no source → source request will be sent at the animation stage")
    if get(spec, "target.platform") == "web" and (get(spec, "budgets.max_influences") or 4) > 4:
        conflicts.append("web target but budgets.max_influences > 4 (three.js reads 4)")
    gate = {"gate": "G1", "status": "fail" if (missing or conflicts) else "needs_review",
            "metrics": {"required_fields_missing": missing, "strategy_conflicts": conflicts, "family": family},
            "notes": notes + ["user approval required"], "at": datetime.now().astimezone().isoformat()}
    print(json.dumps({"written": write_gate(a.project, gate), **gate}, indent=2, ensure_ascii=False))


def cmd_approve(a):
    path = os.path.join(a.project, "reports", f"gate-{a.gate}.json")
    if not os.path.exists(path):
        sys.exit(f"{path} not found")
    gate = json.load(open(path, encoding="utf-8"))
    if gate.get("status") == "fail":
        sys.exit("cannot approve a failing gate; fix the stage or change the spec first")
    gate["approved_by"] = "user"
    gate["approved_at"] = datetime.now().astimezone().isoformat()
    if a.note:
        gate["approval_note"] = a.note
    json.dump(gate, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(gate, indent=2, ensure_ascii=False))


def gate_rows(project):
    rows = []
    for p in sorted(glob.glob(os.path.join(project, "reports", "gate-G*.json"))):
        if p.count(".") > 1:  # history files gate-G2.1.json
            continue
        g = json.load(open(p, encoding="utf-8"))
        ok = g.get("status") == "pass" or (g.get("status") == "needs_review" and g.get("approved_by"))
        rows.append({"gate": g.get("gate"), "status": g.get("status"), "approved": bool(g.get("approved_by")),
                     "ok": ok, "file": os.path.relpath(p, project)})
    return rows


def cmd_summary(a):
    rows = gate_rows(a.project)
    print("| Gate | Status | Approved | OK |\n|------|--------|----------|----|")
    for r in rows:
        print(f"| {r['gate']} | {r['status']} | {'yes' if r['approved'] else '-'} | {'yes' if r['ok'] else 'NO'} |")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_final(a):
    man_path = os.path.join(a.project, "input", "MANIFEST.json")
    changed = []
    if os.path.exists(man_path):
        man = json.load(open(man_path, encoding="utf-8"))
        for name, info in man.get("files", {}).items():
            p = os.path.join(a.project, "input", name)
            if not os.path.exists(p) or sha256(p) != info["sha256"]:
                changed.append(name)
    else:
        changed.append("MANIFEST.json missing")
    rows = gate_rows(a.project)
    not_ok = [r["gate"] for r in rows if r["gate"] != "G8" and not r["ok"]]
    report = os.path.exists(os.path.join(a.project, "reports", "report.md"))
    gate = {"gate": "G8", "status": "pass" if (not changed and not not_ok and report) else "fail",
            "metrics": {"input_checksums_ok": not changed, "changed_inputs": changed,
                        "gates_not_ok": not_ok, "report_complete": report, "gates": rows},
            "at": datetime.now().astimezone().isoformat()}
    print(json.dumps({"written": write_gate(a.project, gate), **gate}, indent=2, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "summary", "final"):
        s = sub.add_parser(name)
        s.add_argument("--project", required=True)
    s = sub.add_parser("approve")
    s.add_argument("--project", required=True)
    s.add_argument("--gate", required=True)
    s.add_argument("--note")
    a = ap.parse_args(argv)
    {"plan": cmd_plan, "approve": cmd_approve, "summary": cmd_summary, "final": cmd_final}[a.cmd](a)


if __name__ == "__main__":
    main()
