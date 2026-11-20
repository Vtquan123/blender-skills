"""Rebuild a project from its recipe (working/recipe.json): the same repo scripts with the project's own arguments.

Every project keeps its specifics as data — the recipe and the argument files next to it — while the code stays
in the repo. This runner replays the recipe in the open Blender (through MCP), so a project can be rebuilt after a
source update or a fix in the repo, and a reviewer can see exactly what was run.

Recipe (schema 1):
    {"steps": [
        {"id": "intake", "script": "blender/intake.py",
         "args": {"source": "${project}/input/model.glb", "project_dir": "${project}", "keep_scene": true}},
        {"id": "rig", "script": "blender/rigid_rig.py", "scene": "${out.intake.scene}",
         "args": {"kind": "ball", "objects": "${scene_meshes}", "structure": "${project}/reports/structure.json"}},
        {"id": "walk", "script": "motion/generators.py", "args_file": "working/animation_calls.json", "args_key": 0},
        {"id": "export", "script": "blender/export_glb.py", "reset_pose": "${out.rig.rig}", "args": {...},
         "checkpoint": "checkpoints/06_animation.blend"}
     ],
     "external": [{"id": "optimize", "cmd": "node production/scripts/node/optimize.mjs --in ${project}/output/x.master.glb ..."}]}
step keys:
    id           unique name; results are kept as ${out.<id>.<key>} for later steps (and across runs in
                 reports/recipe_run.json)
    script       path relative to production/scripts (blender/…, motion/…)
    args         dict passed to run(args); args_file (+ args_key: list index or dict key) merges a file's content
    scene        make this scene current before the step (created empty if missing and "create_scene" is true)
    reset_pose   armature: clear its action and pose before the step (exports and samples start from rest)
    checkpoint   save a COPY of the .blend after the step (path relative to the project)
    skip         true to keep a step in the recipe without running it (documented manual or pre-recipe work)
Placeholders: ${project}, ${repo}, ${scene_meshes} (visible meshes of the current scene), ${out.<id>.<key>[.<key>]}.

args:
    project_dir  (str, required)
    from, to     (str, optional)   first / last step id to run (inclusive)
    only         (list, optional)  run just these step ids
    dry_run      (bool, False)     resolve and list the steps without running them
returns {"ok", "ran": [...], "failed": id | null, "external": [resolved commands]}; writes reports/recipe_run.json
"""
import copy
import importlib.util
import json
import os
import re
import runpy
import sys
import time

import bpy


def _load_common():
    here = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
    path = os.path.join(here, "u3d_common.py")
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location("u3d_common", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["u3d_common"] = mod
        spec.loader.exec_module(mod)
        return mod
    if "u3d_common" in sys.modules:
        return sys.modules["u3d_common"]
    raise ImportError("u3d_common.py not found")


C = _load_common()
SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__", "")) or "."))
REPO = os.path.dirname(os.path.dirname(SCRIPTS))
PH = re.compile(r"\$\{([^}]+)\}")
KEEP_KEYS = ("rig", "scene", "action", "frame_range", "chains", "parts", "out", "written", "gate", "helpers",
             "weight_method", "refine", "bones")


def _lookup(path, ctx):
    cur = ctx
    for k in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(k)]
        elif isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            raise KeyError(path)
    return cur


def _resolve(v, ctx):
    if isinstance(v, dict):
        return {k: _resolve(x, ctx) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve(x, ctx) for x in v]
    if not isinstance(v, str):
        return v
    whole = PH.fullmatch(v)
    if whole:                                   # "${...}" alone keeps the value's type (list, dict, number)
        key = whole.group(1)
        if key == "scene_meshes":
            return [o.name for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get()]
        return ctx[key] if key in ("project", "repo") else _lookup(key, ctx)
    return PH.sub(lambda m: str(ctx[m.group(1)] if m.group(1) in ("project", "repo") else _lookup(m.group(1), ctx)), v)


def _brief(res):
    if not isinstance(res, dict):
        return res
    out = {k: res[k] for k in ("ok", "error") if k in res}
    for k in KEEP_KEYS:
        if k in res:
            v = res[k]
            if k == "gate" and isinstance(v, dict):
                v = {"gate": v.get("gate"), "status": v.get("status")}
            out[k] = v
    return out


def run(args: dict) -> dict:
    proj = os.path.abspath(os.path.expanduser(args["project_dir"]))
    rpath = os.path.join(proj, "working", "recipe.json")
    if not os.path.exists(rpath):
        return C.result_error(f"no recipe at {rpath}")
    recipe = json.load(open(rpath))
    steps = recipe.get("steps", [])
    ids = [s["id"] for s in steps]
    lo = ids.index(args["from"]) if args.get("from") else 0
    hi = ids.index(args["to"]) if args.get("to") else len(ids) - 1
    only = set(args.get("only") or [])
    log_path = os.path.join(proj, "reports", "recipe_run.json")
    prev = json.load(open(log_path)) if os.path.exists(log_path) else {}
    ctx = {"project": proj, "repo": REPO, "out": dict(prev.get("out", {}))}
    ran, failed = [], None
    for i, st in enumerate(steps):
        if i < lo or i > hi or (only and st["id"] not in only) or st.get("skip"):
            continue
        t0 = time.time()
        try:
            if st.get("scene"):
                name = _resolve(st["scene"], ctx)
                sc = bpy.data.scenes.get(name)
                if sc is None and st.get("create_scene"):
                    sc = bpy.data.scenes.new(name)
                if sc is None:
                    raise RuntimeError(f"scene {name} not found")
                bpy.context.window.scene = sc
            a = copy.deepcopy(st.get("args", {}))
            if st.get("args_file"):
                data = json.load(open(os.path.join(proj, st["args_file"])))
                if "args_key" in st:
                    data = data[st["args_key"]]
                a = {**data, **a}
            a = _resolve(a, ctx)
            if args.get("dry_run"):
                ran.append({"id": st["id"], "script": st["script"], "args": a})
                continue
            if st.get("reset_pose"):
                rig = bpy.data.objects[_resolve(st["reset_pose"], ctx)]
                if rig.animation_data:
                    rig.animation_data.action = None
                for pb in rig.pose.bones:
                    pb.matrix_basis.identity()
                bpy.context.scene.frame_set(1)
            res = runpy.run_path(os.path.join(SCRIPTS, st["script"]))["run"](a)
            ok = bool(res.get("ok", True)) if isinstance(res, dict) else True
            ctx["out"][st["id"]] = _brief(res)
            if ok and st.get("checkpoint"):
                path = os.path.join(proj, st["checkpoint"])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
            ran.append({"id": st["id"], "ok": ok, "sec": round(time.time() - t0, 2),
                        **({"error": res.get("error")} if isinstance(res, dict) and not ok else {})})
            if not ok:
                failed = st["id"]
                break
        except Exception as e:                    # report, keep what ran
            ran.append({"id": st["id"], "ok": False, "error": f"{type(e).__name__}: {e}", "sec": round(time.time() - t0, 2)})
            failed = st["id"]
            break
    external = [{"id": e["id"], "cmd": _resolve(e["cmd"], ctx)} for e in recipe.get("external", [])]
    if not args.get("dry_run"):
        log = {"at": C.now_iso(), "ran": ran, "failed": failed, "out": ctx["out"], "external": external}
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        json.dump(log, open(log_path, "w"), indent=1, default=str)
    return C.result_ok(ran=ran, failed=failed, external=external) if not failed else \
        C.result_error(f"step {failed} failed", ran=ran, failed=failed, external=external)
