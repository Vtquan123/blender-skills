"""Skin quality under real clips: folds, flipped faces and collapsed edges (deformation-prep, gate G5 helper).

The ROM test bends one joint at a time; a walk moves four legs against a round body at once, and that is where
automatic weights crease (belly, groin, armpit). This samples the deformed mesh over each clip and measures:
  crease      increase in bend between neighbouring triangles vs rest, 1 - cos(Δ) per shared edge
              (0 = unchanged, 1 = 90° sharper, 2 = folded flat onto itself)
  fold_verts  vertices whose worst crease exceeds `crease_limit` (default 0.5 ≈ 60° sharper than at rest)
  flipped     triangles whose normal turns more than 120° away from the average normal of their neighbours
  edge_min    smallest edge-length ratio pose/rest (collapsed skin)
Clusters (2 cm grid) of fold vertices are listed with their mean bone weights and worst frames, so the fix can be
aimed (refine / transfers in skin_weights.py). Optionally stores a "fold" vertex group (0..1) for weight-paint view.

args:
    rig          (str, required)
    mesh         (str, required)
    clips        (list[str], required)   actions to sample
    step         (int, 2)                frame step
    crease_limit (float, 0.5)
    ikfk         (dict, optional)        {"upper_arm_parent.L": 0.0, ...} rest values restored after the check
    store_group  (bool, False)           write vertex group "fold" (not deforming; delete before export)
    thresholds   (dict, optional)        {"fold_verts_max": .., "flipped_max": .., "edge_min": ..}
    project_dir  (str, optional)         write reports/deform-check.json
"""
import importlib.util
import os
import sys
from collections import defaultdict

import bpy
import numpy as np


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


def _topology(me):
    me.calc_loop_triangles()
    T = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", T)
    T = T.reshape(-1, 3)
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    tri = np.tile(np.arange(len(T)), 3)
    key = np.sort(e, 1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    k, t = key[order], tri[order]
    same = np.all(k[1:] == k[:-1], axis=1)
    pairs = np.stack([t[:-1][same], t[1:][same], k[:-1][same][:, 0], k[:-1][same][:, 1]], 1)
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    return T, pairs, ev.reshape(-1, 2)


def _normals(co, T):
    n = np.cross(co[T[:, 1]] - co[T[:, 0]], co[T[:, 2]] - co[T[:, 0]])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def _reset(rig, ikfk):
    rig.animation_data.action = None
    for pb in rig.pose.bones:
        pb.matrix_basis.identity()
    for n, v in (ikfk or {}).items():
        if n in rig.pose.bones:
            rig.pose.bones[n]["IK_FK"] = v


def run(args: dict) -> dict:
    rig = bpy.data.objects.get(args.get("rig", ""))
    mesh = bpy.data.objects.get(args.get("mesh", ""))
    if rig is None or mesh is None:
        return C.result_error("rig and mesh required")
    sc = bpy.context.scene
    me = mesh.data
    ikfk = args.get("ikfk")
    lim = float(args.get("crease_limit", 0.5))
    step = max(1, int(args.get("step", 2)))
    T, pairs, ev = _topology(me)
    nv = len(me.vertices)
    ad = rig.animation_data or rig.animation_data_create()
    prev = ad.action, sc.frame_current
    _reset(rig, ikfk)
    sc.frame_set(sc.frame_current)
    rest = C.evaluated_vertex_positions(mesh)
    nr = _normals(rest, T)
    dr = np.einsum("ij,ij->i", nr[pairs[:, 0]], nr[pairs[:, 1]])
    l0 = np.maximum(np.linalg.norm(rest[ev[:, 0]] - rest[ev[:, 1]], axis=1), 1e-9)
    score = np.zeros(nv)
    worst_f = np.zeros(nv, dtype=int)
    clips = {}
    for name in args.get("clips", []):
        act = bpy.data.actions.get(name)
        if act is None:
            continue
        _reset(rig, ikfk)
        ad.action = act
        if hasattr(ad, "action_slot") and len(getattr(act, "slots", [])):
            ad.action_slot = act.slots[0]
        f0, f1 = (int(x) for x in act.frame_range)
        c = {"fold_verts_frame_max": 0, "crease_max": 0.0, "flipped_max": 0, "edge_min": 1.0}
        for f in range(f0, f1 + 1, step):
            sc.frame_set(f)
            co = C.evaluated_vertex_positions(mesh)
            n = _normals(co, T)
            crease = np.clip(dr - np.einsum("ij,ij->i", n[pairs[:, 0]], n[pairs[:, 1]]), 0, None)
            vs = np.zeros(nv)
            np.maximum.at(vs, pairs[:, 2], crease)
            np.maximum.at(vs, pairs[:, 3], crease)
            upd = vs > score
            score[upd] = vs[upd]
            worst_f[upd] = f
            # flipped: triangle normal vs mean of neighbour normals
            acc = np.zeros_like(n)
            np.add.at(acc, pairs[:, 0], n[pairs[:, 1]])
            np.add.at(acc, pairs[:, 1], n[pairs[:, 0]])
            acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
            flipped = int((np.einsum("ij,ij->i", n, acc) < -0.5).sum())
            r = np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1) / l0
            c["fold_verts_frame_max"] = max(c["fold_verts_frame_max"], int((vs > lim).sum()))
            c["crease_max"] = max(c["crease_max"], round(float(crease.max()), 3))
            c["flipped_max"] = max(c["flipped_max"], flipped)
            c["edge_min"] = min(c["edge_min"], round(float(r.min()), 3))
        clips[name] = c
    _reset(rig, ikfk)
    ad.action = prev[0]
    sc.frame_set(prev[1])

    bad = np.where(score > lim)[0]
    names = {g.index: g.name for g in mesh.vertex_groups}
    cl = defaultdict(list)
    for vi in bad:
        cl[tuple((rest[vi] // 0.02).astype(int))].append(vi)
    clusters = []
    for _, vs in sorted(cl.items(), key=lambda x: -len(x[1]))[:10]:
        w = defaultdict(float)
        for vi in vs:
            for g in me.vertices[vi].groups:
                w[names[g.group]] += g.weight / len(vs)
        clusters.append({"verts": len(vs), "centre": [round(float(x), 3) for x in rest[vs].mean(0)],
                         "frames": sorted({int(worst_f[v]) for v in vs})[:6],
                         "weights": sorted(((a, round(b, 2)) for a, b in w.items()), key=lambda x: -x[1])[:5]})
    if args.get("store_group"):
        g = mesh.vertex_groups.get("fold") or mesh.vertex_groups.new(name="fold")
        g.remove(list(range(nv)))
        for vi in np.where(score > 0.05)[0]:
            g.add([int(vi)], float(min(score[vi] / 2.0, 1.0)), "REPLACE")
    metrics = {"fold_verts": int(len(bad)), "crease_limit": lim, "clips": clips, "clusters": clusters}
    th = args.get("thresholds") or {}
    failing = []
    if "fold_verts_max" in th and metrics["fold_verts"] > th["fold_verts_max"]:
        failing.append("fold_verts")
    for nm, c in clips.items():
        if "flipped_max" in th and c["flipped_max"] > th["flipped_max"]:
            failing.append(f"{nm}.flipped")
        if "edge_min" in th and c["edge_min"] < th["edge_min"]:
            failing.append(f"{nm}.edge_min")
    status = "fail" if failing else ("pass" if th else "needs_review")
    out = {"status": status, "metrics": metrics, "failing": failing, "thresholds": th}
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", "deform-check.json"), out)
    return C.result_ok(**out)
