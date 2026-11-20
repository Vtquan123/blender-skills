"""Bone chains along the measured skeleton (structure_analysis.py): plants, snakes, ropes, tentacles, tails.

mode "plant":  the ground-touching extremity is the trunk (built from the ground up); every other extremity
               becomes a branch chain parented to the nearest trunk bone. Chains sway with generators.wind_sway.
mode "spine":  the two longest extremities are joined through the body core into one chain (snake, worm,
               rope, eel); animate with wind_sway (axis "Z", phase_step for a travelling wave) or chain_curve.
Bones are deform bones; skin the mesh afterwards with skin_weights.py (automatic weights), then deform_check.py.

args:
    structure      (dict | str)       structure_analysis result or reports/structure.json
    mode           (str, "plant")     "plant" | "spine"
    bone_length    (float, optional)  target bone length in metres (default 12 % of the model height / length)
    max_bones      (int, 6)           per chain
    name           (str, "RIG")
returns {"rig", "chains": [[bone, ...], ...]}; rig["u3d_chains"] stores the chains for the generators
"""
import importlib.util
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector


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


def _resample(pts, n):
    pts = np.asarray(pts, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.r_[0, np.cumsum(seg)]
    if cum[-1] <= 0:
        return pts[[0, -1]]
    t = np.linspace(0, cum[-1], n + 1)
    return np.array([np.interp(t, cum, pts[:, k]) for k in range(3)]).T


def _nbones(length, target, mx):
    return int(np.clip(round(length / max(target, 1e-6)), 1, mx))


def run(args: dict) -> dict:
    S = args.get("structure")
    if isinstance(S, str):
        S = json.load(open(S))
    mode = args.get("mode", "plant")
    ext = S["skeleton"]["extremities"]
    if not ext:
        return C.result_error("the structure has no extremities to build chains on")
    up = np.array(S["axes"]["up"], float)
    size = S["size"]
    target = float(args.get("bone_length") or 0.12 * max(size["height"], size["width_major"]))
    mx = int(args.get("max_bones", 6))
    chains_pts = []           # list of (points base→tip, parent_chain_index or None)
    if mode == "plant":
        trunk = [e for e in ext if e["touches_ground"]]
        if not trunk:
            return C.result_error("no ground-touching extremity (trunk) found; use mode spine or confirm with the user")
        t = max(trunk, key=lambda e: e["length"])
        tp = np.array(t["path"])                           # extremity paths run tip → base: ground → junction
        core = np.array(S["skeleton"]["root"])
        if np.linalg.norm(tp[-1] - core) > 1e-6:
            tp = np.vstack([tp, core])                      # continue to the crown core
        chains_pts.append((tp, None))
        for e in ext:
            if e is t:
                continue
            chains_pts.append((np.array(e["path"])[::-1], 0))      # base (junction) → tip
    elif mode == "spine":
        two = sorted(ext, key=lambda e: -e["length"])[:2]
        a = np.array(two[0]["path"]); b = np.array(two[1]["path"])[::-1] if len(two) > 1 else np.zeros((0, 3))
        core = np.array(S["skeleton"]["root"])
        pts = np.vstack([a, core[None], b]) if len(b) else np.vstack([a, core[None]])
        chains_pts.append((pts, None))
    else:
        return C.result_error(f"unknown mode {mode}")
    scene = bpy.context.scene
    name = args.get("name", "RIG")
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    scene.collection.objects.link(rig)
    for o in scene.objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    chains = []
    for ci, (pts, parent_ci) in enumerate(chains_pts):
        length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        n = _nbones(length, target, mx)
        q = _resample(pts, n)
        names = []
        prefix = "trunk" if (mode == "plant" and ci == 0) else ("spine" if mode == "spine" else f"branch{ci:02d}")
        for k in range(n):
            bn = f"{prefix}_{k + 1:02d}"
            b = eb.new(bn)
            b.head = Vector(q[k]); b.tail = Vector(q[k + 1])
            b.use_deform = True
            if k:
                b.parent = eb[names[-1]]; b.use_connect = True
            elif parent_ci is not None:
                # nearest bone of the parent chain to this chain's base
                base = Vector(q[0])
                best = min(chains[parent_ci], key=lambda nm: (eb[nm].head.lerp(eb[nm].tail, 0.5) - base).length)
                b.parent = eb[best]
            names.append(bn)
        chains.append(names)
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    rig["u3d_chains"] = json.dumps(chains)
    return C.result_ok(rig=rig.name, chains=chains)
