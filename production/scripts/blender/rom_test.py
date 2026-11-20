"""Range-of-motion test (deformation-prep step 8, gate G4c).

Builds action AN_ROM on the rig (one block per joint: rest → limit A → rest → limit B → rest),
evaluates the deformed mesh at each limit and measures per joint:
  volume_loss       max(0, 1 - cross-section hull area at limit / at rest) on the joint bisector plane
  pinch             1 - (closest band vertex to the posed joint centre at limit / same at rest)
  stretch_max       max edge-length ratio limit/rest inside the joint band
  self_intersections overlapping non-adjacent face pairs touching the band (BVH)
Worst frames are returned so the agent can capture the contact sheet with the MCP screenshot tool.

args:
    rig          (str, required)   armature with controls (e.g. Rigify FK controls)
    mesh         (str, required)   deformed mesh
    joints       (list[dict], required)
        [{"name": "elbow.L", "control": "forearm_fk.L", "measure_bone": "DEF-forearm.L",
          "axis": "X", "limits": [0, 140], "kind": "bend"}]   # kind: bend | twist
    frames_per_step (int, 8)
    fk           (bool, True)      set every "IK_FK" custom property (Rigify limbs) to 1.0 = FK for the test,
                                   so rotating *_fk controls moves the limbs; previous values are restored
    thresholds   (dict)            {"volume_loss_max": .., "pinch_max": .., "stretch_max": .., "self_intersections_max": ..}
    keep_action  (bool, True)
    project_dir  (str, optional)   write reports/rom.json and gate-G4c.json
"""
import importlib.util
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Euler, Quaternion
from mathutils.bvhtree import BVHTree


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
AX = {"X": 0, "Y": 1, "Z": 2}


def key_rotation(pb, axis, deg, frame):
    e = [0.0, 0.0, 0.0]
    e[AX[axis]] = math.radians(deg)
    if pb.rotation_mode == "QUATERNION":
        pb.rotation_quaternion = Euler(e).to_quaternion()
        pb.keyframe_insert("rotation_quaternion", frame=frame)
    elif pb.rotation_mode == "AXIS_ANGLE":
        q = Euler(e).to_quaternion()
        ax, ang = q.to_axis_angle()
        pb.rotation_axis_angle = (ang, ax.x, ax.y, ax.z)
        pb.keyframe_insert("rotation_axis_angle", frame=frame)
    else:
        pb.rotation_euler = e
        pb.keyframe_insert("rotation_euler", frame=frame)


def hull_area(pts2d):
    if len(pts2d) < 3:
        return 0.0
    p = sorted(map(tuple, pts2d))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    h = np.array(lower[:-1] + upper[:-1])
    x, y = h[:, 0], h[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def plane_basis(n):
    n = n / (np.linalg.norm(n) or 1)
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def joint_frame(rig, bone_name):
    pb = rig.pose.bones[bone_name]
    mw = rig.matrix_world
    head = np.array(mw @ pb.head)
    d = np.array((mw @ pb.tail) - (mw @ pb.head))
    d /= np.linalg.norm(d) or 1
    if pb.parent:
        pd = np.array((mw @ pb.parent.tail) - (mw @ pb.parent.head))
        pd /= np.linalg.norm(pd) or 1
        n = d + pd
    else:
        n = d
    return head, n / (np.linalg.norm(n) or 1), float(pb.length * rig.scale[0])


def section_area(co, idx, head, n, thick):
    p = co[idx] - head
    t = p @ n
    sl = np.abs(t) < thick
    if sl.sum() < 3:
        return 0.0
    u, v = plane_basis(n)
    q = p[sl]
    return hull_area(np.stack([q @ u, q @ v], 1))


def self_intersections(mesh, band_mask):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = mesh.evaluated_get(dg)
    me = ev.to_mesh()
    mw = mesh.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    tree = BVHTree.FromPolygons(verts, polys)
    count = 0
    for a, b in tree.overlap(tree):
        if a >= b:
            continue
        if set(polys[a]) & set(polys[b]):
            continue
        if band_mask[list(polys[a])].any() or band_mask[list(polys[b])].any():
            count += 1
    return count


def run(args: dict) -> dict:
    rig = bpy.data.objects.get(args.get("rig", ""))
    mesh = bpy.data.objects.get(args.get("mesh", ""))
    joints = args.get("joints") or []
    if rig is None or mesh is None or not joints:
        return C.result_error("rig, mesh and joints required")
    scene = bpy.context.scene
    fps_step = int(args.get("frames_per_step", 8))
    ikfk_prev = {}
    if args.get("fk", True):
        for pb in rig.pose.bones:
            if "IK_FK" in pb.keys():
                ikfk_prev[pb.name] = pb["IK_FK"]
                pb["IK_FK"] = 1.0
        rig.update_tag()
    ad = rig.animation_data or rig.animation_data_create()
    prev_action = ad.action
    act = bpy.data.actions.get("AN_ROM") or bpy.data.actions.new("AN_ROM")
    ad.action = act

    me = mesh.data
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)

    # build keys
    frame = 1
    blocks = []
    for j in joints:
        pb = rig.pose.bones.get(j["control"])
        if pb is None:
            blocks.append({"joint": j["name"], "error": f"control {j['control']} not found"})
            continue
        lo, hi = j["limits"]
        fr = {}
        for label, deg in (("rest0", 0), ("A", lo), ("rest1", 0), ("B", hi), ("rest2", 0)):
            key_rotation(pb, j.get("axis", "X"), deg, frame)
            fr[label] = frame
            frame += fps_step
        blocks.append({"joint": j["name"], "frames": fr, "spec": j})
    scene.frame_start, scene.frame_end = 1, frame

    # measure
    scene.frame_set(1)
    rest_co = C.evaluated_vertex_positions(mesh)
    results = []
    for blk in blocks:
        if "error" in blk:
            results.append(blk)
            continue
        j = blk["spec"]
        mb = j.get("measure_bone", j["control"])
        scene.frame_set(blk["frames"]["rest0"])
        head, n, blen = joint_frame(rig, mb)
        rel = rest_co - head
        t = rel @ n
        radial = np.linalg.norm(rel - np.outer(t, n), axis=1)
        slab0 = np.abs(t) < 0.1 * blen
        r = float(np.median(radial[slab0])) if slab0.any() else 0.25 * blen
        band = (np.abs(t) < max(r, 0.25 * blen)) & (radial < 2.5 * r)
        idx = np.nonzero(band)[0]
        thick = max(0.15 * r, 1e-4)
        a0 = section_area(rest_co, idx, head, n, thick)
        d0 = float(np.linalg.norm(rest_co[idx] - head, axis=1).min()) if len(idx) else 0.0
        e_band = band[ev[:, 0]] & band[ev[:, 1]]
        l0 = np.linalg.norm(rest_co[ev[e_band, 0]] - rest_co[ev[e_band, 1]], axis=1)
        per = {}
        for lim in ("A", "B"):
            scene.frame_set(blk["frames"][lim])
            co = C.evaluated_vertex_positions(mesh)
            h, nn, _ = joint_frame(rig, mb)
            a = section_area(co, idx, h, nn, thick)
            l1 = np.linalg.norm(co[ev[e_band, 0]] - co[ev[e_band, 1]], axis=1)
            d1 = float(np.linalg.norm(co[idx] - h, axis=1).min()) if len(idx) else 0.0
            per[lim] = {"frame": blk["frames"][lim],
                        "volume_loss": round(max(0.0, 1 - a / a0), 4) if a0 > 0 else None,
                        "pinch": round(max(0.0, 1 - d1 / d0), 4) if d0 > 0 else None,
                        "stretch_max": round(float((l1 / np.maximum(l0, 1e-9)).max()), 4) if len(l0) else None,
                        "self_intersections": self_intersections(mesh, band)}
        worst = max(per.values(), key=lambda x: (x["volume_loss"] or 0) + (x["pinch"] or 0) + (x["self_intersections"] or 0))
        results.append({"joint": j["name"], "kind": j.get("kind", "bend"), "band_verts": int(band.sum()),
                        "limits": per, "worst_frame": worst["frame"],
                        "volume_loss": max((p["volume_loss"] or 0) for p in per.values()),
                        "pinch": max((p["pinch"] or 0) for p in per.values()),
                        "stretch_max": max((p["stretch_max"] or 0) for p in per.values()),
                        "self_intersections": max(p["self_intersections"] for p in per.values())})
    scene.frame_set(1)
    for name, val in ikfk_prev.items():
        rig.pose.bones[name]["IK_FK"] = val
    if not args.get("keep_action", True):
        ad.action = prev_action
        bpy.data.actions.remove(act)

    th = args.get("thresholds") or {}
    failing = []
    for r_ in results:
        if "error" in r_:
            failing.append(r_["joint"])
            continue
        if th.get("volume_loss_max") is not None and r_["volume_loss"] > th["volume_loss_max"]:
            failing.append(r_["joint"])
        elif th.get("pinch_max") is not None and r_["pinch"] > th["pinch_max"]:
            failing.append(r_["joint"])
        elif th.get("stretch_max") is not None and r_["stretch_max"] > th["stretch_max"]:
            failing.append(r_["joint"])
        elif th.get("self_intersections_max") is not None and r_["self_intersections"] > th["self_intersections_max"]:
            failing.append(r_["joint"])
    gate = {"gate": "G4c", "status": "fail" if failing else "needs_review",
            "metrics": {"joints": len(results), "failing": failing}, "thresholds": th,
            "notes": ["approve from the contact sheet of worst_frame per joint"], "at": C.now_iso()}
    out = {"action": "AN_ROM", "frame_range": [1, frame], "joints": results, "gate": gate,
           "fk_switched": sorted(ikfk_prev)}
    if args.get("project_dir"):
        rep = os.path.join(args["project_dir"], "reports")
        C.write_json(os.path.join(rep, "rom.json"), out)
        C.write_json(os.path.join(rep, "gate-G4c.json"), gate)
    return C.result_ok(**out)
