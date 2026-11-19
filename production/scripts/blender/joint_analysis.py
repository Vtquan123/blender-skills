"""Joint analysis (deformation-prep step 2, gate G4a): score topology readiness around each joint.

Works on any mesh + armature in rest pose. Metrics are ESTIMATES meant for ranking and gating,
always reviewed with wireframe screenshots.

args:
    mesh        (str, required)   mesh object to analyse (source or deform mesh)
    armature    (str, required)   armature whose bone heads mark joints (metarig or generated rig)
    joints      (list[str])       bone names whose HEAD is a joint; default: every bone with a parent
    rules       (dict)            {bone_name: {"type": "hinge", "loops": 3, "supports": 1}, ...}
                                  (agent maps category preset joint_rules onto bone names)
    band_scale  (float, 1.0)      band half-width = band_scale * limb radius
    project_dir (str, optional)   write reports/joint-report.json and gate-G4a.json

per joint: position, limb_radius_m, band_halfwidth_m, rings, tri_ratio, poles, verts_in_band, rule, ok
"""
import importlib.util
import os
import sys

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


def mesh_arrays(ob):
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    mw = np.array(ob.matrix_world)
    co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    sizes = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_total", sizes)
    pverts = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", pverts)
    starts = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_start", starts)
    valence = np.bincount(ev.ravel(), minlength=len(co))
    cnt = C.edge_face_counts(me)
    boundary_v = np.zeros(len(co), dtype=bool)
    boundary_v[ev.reshape(-1, 2)[cnt == 1].ravel()] = True
    return co, ev.reshape(-1, 2), sizes, pverts, starts, valence, boundary_v


def bone_frame(arm, bone_name):
    b = arm.data.bones[bone_name]
    mw = arm.matrix_world
    head = np.array(mw @ b.head_local)
    tail = np.array(mw @ b.tail_local)
    d = tail - head
    d /= np.linalg.norm(d) or 1.0
    if b.parent:
        ph, pt = np.array(mw @ b.parent.head_local), np.array(mw @ b.parent.tail_local)
        pd = pt - ph
        pd /= np.linalg.norm(pd) or 1.0
        axis = d + pd
        axis = axis / (np.linalg.norm(axis) or 1.0)
    else:
        axis = d
    return head, axis


def limb_radius(co, head, axis, diag):
    rel = co - head
    t = rel @ axis
    radial = np.linalg.norm(rel - np.outer(t, axis), axis=1)
    slab = np.abs(t) < 0.01 * diag
    near = slab & (np.linalg.norm(rel, axis=1) < 0.25 * diag)
    if near.sum() < 3:
        return float(np.percentile(np.linalg.norm(rel, axis=1), 1)) or 0.01 * diag
    r = radial[near]
    rmin = r.min()
    # keep the cluster nearest the axis (the limb), not the torso behind it
    cluster = r[r < rmin * 3 + 0.01 * diag]
    return float(np.median(cluster))


def analyse_joint(arrays, head, axis, r, band_scale):
    co, edges, sizes, pverts, starts, valence, boundary_v = arrays
    rel = co - head
    t = rel @ axis
    radial = np.linalg.norm(rel - np.outer(t, axis), axis=1)
    hw = max(band_scale * r, 1e-5)
    inband = (np.abs(t) <= hw) & (radial <= 2.0 * r)
    n = int(inband.sum())
    if n == 0:
        return {"verts_in_band": 0}
    e_in = inband[edges[:, 0]] & inband[edges[:, 1]]
    ev = co[edges[e_in, 1]] - co[edges[e_in, 0]]
    lens = np.linalg.norm(ev, axis=1)
    lens[lens == 0] = 1e-9
    axial = np.abs(ev @ axis) / lens > 0.7
    step = float(np.median(np.abs(ev[axial] @ axis))) if axial.any() else 0.0
    rings = C.count_rings(co, edges, head, axis, hw, r)["rings"]
    # faces touching the band
    face_in = np.add.reduceat(inband[pverts].astype(np.int64), starts) > 0
    tri_ratio = float((sizes[face_in] == 3).mean()) if face_in.any() else 0.0
    poles = int(((valence != 4) & inband & ~boundary_v).sum())
    return {"verts_in_band": n, "band_halfwidth_m": round(hw, 5), "axial_edge_step_m": round(step, 5),
            "rings": rings, "tri_ratio": round(tri_ratio, 3), "poles": poles}


def run(args: dict) -> dict:
    mesh = bpy.data.objects.get(args.get("mesh", ""))
    arm = bpy.data.objects.get(args.get("armature", ""))
    if mesh is None or arm is None:
        return C.result_error("mesh and armature required")
    arrays = mesh_arrays(mesh)
    mn, mx = C.world_bbox([mesh])
    diag = float(np.linalg.norm(np.array(mx) - np.array(mn)))
    joints = args.get("joints") or [b.name for b in arm.data.bones if b.parent]
    rules = args.get("rules", {})
    band_scale = float(args.get("band_scale", 1.0))
    report = []
    for jn in joints:
        if jn not in arm.data.bones:
            report.append({"joint": jn, "error": "bone not found"})
            continue
        head, axis = bone_frame(arm, jn)
        r = limb_radius(arrays[0], head, axis, diag)
        m = analyse_joint(arrays, head, axis, r, band_scale)
        rule = rules.get(jn)
        ok = None
        if rule and "rings" in m:
            need = int(rule.get("loops", 0))
            ok = m["rings"] >= need and m["tri_ratio"] <= 0.05  # poles are reported for review, not gated
        report.append({"joint": jn, "position": head.round(5).tolist(), "limb_radius_m": round(r, 5),
                       **m, "rule": rule, "ok": ok})
    checked = [j for j in report if j.get("ok") is not None]
    gate = {"gate": "G4a", "status": ("needs_review" if checked and all(j["ok"] for j in checked) else
                                      "fail" if checked else "needs_review"),
            "metrics": {"joints_checked": len(checked), "joints_failing": [j["joint"] for j in checked if not j["ok"]]},
            "notes": ["rings = loops crossed by meridian half-planes (median of 8); approve from wireframe sheet"], "at": C.now_iso()}
    out = {"mesh": mesh.name, "armature": arm.name, "joints": report, "gate": gate}
    if args.get("project_dir"):
        rep = os.path.join(args["project_dir"], "reports")
        C.write_json(os.path.join(rep, "joint-report.json"), out)
        C.write_json(os.path.join(rep, "gate-G4a.json"), gate)
    return C.result_ok(**out)
