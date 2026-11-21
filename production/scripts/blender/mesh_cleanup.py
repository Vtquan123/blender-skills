"""Mesh cleanup before UVs, rigging or export — the safe order, measured before and after.

The order and the guards come from blender-kiln's cleanup and topology rules (MIT,
`references/pipeline-import-cleanup.md`, `references/topology-rules.md`), re-implemented with bmesh so it
runs through the MCP without operator context:

    weld (merge by distance) → delete loose → dissolve degenerate → fill small holes (optional)
    → recalculate normals → n-gons (optional) → apply transforms → decimate (guarded, optional)
    → origin at the base

Guards:
- **Never weight a mesh with split edges** (kiln rule 26): `duplicate_verts` counts vertices that a weld
  would merge — each copy gets its own weights and the skin opens at every joint.
- **Decimate is refused when it opens the mesh**: open (boundary) and non-manifold edge counts are
  compared before/after; worse → the pass is undone and the next try decimates less (up to 2x the
  target, the tier's soft ceiling). Thin parts (wires, handles, straps) break first: protect them with
  a vertex group (`protect_group`) or rebuild them as curves; never split edges to hide the damage.
- **Print models are not welded** (`print: true`): a 0.1 mm merge broke a closed printable model in kiln's
  bench while its own count read 0.

args:
    object          (str, required)  mesh object
    in_place        (bool, False)    work on the object itself; default: a copy "<name>_clean" (source kept)
    steps           (list[str])      subset/order of: weld, loose, degenerate, holes, normals, ngons,
                                     transforms, decimate, origin. Default: all but holes/ngons/decimate
                                     (decimate runs when `decimate` is given)
    merge_distance  (float, 0.0001)  metres (0.1 mm)
    keep_loose_edges (bool, False)   keep wire edges (intended wires/curves)
    holes_max_sides (int, 8)         fill holes up to this many sides ("holes" step)
    ngons           (str, "triangulate")  "triangulate" | "report"
    decimate        (dict)           {"target_tris": N} or {"ratio": r}; "mode": "COLLAPSE" (default) |
                                     "PLANAR" (angle_deg) | "UNSUBDIV" (iterations); "passes" (2);
                                     "protect_group" (vertex group kept at full detail); "max_relax" (2.0)
    budget          (dict)           {"tris": N} or {"tier": "lightweight|balanced|detailed",
                                     "role": "hero|prop|background"} — reported, never enforced
    print           (bool, False)    3D-print model: skip weld and decimate
    measure_pose    (bool, False)    characters: arm angle → T-pose / A-pose / I-pose (+ wingspan/height)
    forward         (str, "-Y")      facing axis for the pose measure (lateral axis = the other horizontal)
    project_dir     (str)            write reports/cleanup-<object>.json

returns: {object, before, after, steps: [{step, ...}], decimate, budget, pose, warnings}
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector


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

TIERS = {  # triangles, from kiln's detail tiers (soft ranges)
    "lightweight": {"hero": (3000, 8000), "prop": (300, 1500), "background": (50, 300)},
    "balanced": {"hero": (8000, 20000), "prop": (1500, 5000), "background": (300, 1500)},
    "detailed": {"hero": (20000, 80000), "prop": (5000, 15000), "background": (1500, 5000)},
}
DEFAULT_STEPS = ["weld", "loose", "degenerate", "normals", "transforms", "decimate", "origin"]


# ---------------------------------------------------------------- measures
def stats(me, merge_distance=1e-4) -> dict:
    bm = bmesh.new()
    bm.from_mesh(me)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    quads = sum(1 for f in bm.faces if len(f.verts) == 4)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonman = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary and e.link_faces)
    loose_v = sum(1 for v in bm.verts if not v.link_edges)
    loose_e = sum(1 for e in bm.edges if not e.link_faces)
    degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    dup = bmesh.ops.find_doubles(bm, verts=bm.verts, dist=merge_distance)["targetmap"]
    bm.free()
    return {"verts": len(me.vertices), "faces": len(me.polygons), "tris": tris, "quads": quads, "ngons": ngons,
            "open_edges": boundary, "nonmanifold_edges": nonman, "loose_verts": loose_v, "loose_edges": loose_e,
            "degenerate_faces": degenerate, "duplicate_verts": len(dup),
            "components": C.components_count(me)}


def budget_report(tris, budget):
    if not budget:
        return None
    if "tris" in budget:
        lo, hi = 0, int(budget["tris"])
    else:
        lo, hi = TIERS[budget.get("tier", "balanced")][budget.get("role", "prop")]
    state = "under" if tris < lo else ("in" if tris <= hi else ("over" if tris <= 2 * hi else "over_2x"))
    advice = {"under": "fine — keep the detail", "in": "in range", "over": "over the soft range but under 2x: "
              "report where the triangles go, keep them", "over_2x": "past 2x the top: propose a reduction "
              "(before/after, the user decides)"}[state]
    return {"tris": tris, "range": [lo, hi], "state": state, "advice": advice}


def measure_pose(ob, forward="-Y"):
    """Arm angle from two sections along the arm (robust to big heads), kiln's IMPORT measure."""
    mw = ob.matrix_world
    co = np.array([mw @ v.co for v in ob.data.vertices])
    lat = 0 if forward.upper().endswith("Y") else 1
    z = co[:, 2]
    H = float(z.max() - z.min())
    if H <= 0:
        return None
    cx = float(np.median(co[:, lat]))
    side = co[co[:, lat] > cx]
    if len(side) < 20:
        return None
    hand = side[np.argmax(side[:, lat])]
    reach = hand[lat] - cx

    def section(a, b):
        q = side[(side[:, lat] >= cx + a * reach) & (side[:, lat] <= cx + b * reach)
                 & (np.abs(side[:, 2] - hand[2]) < 0.15 * H)]
        return q.mean(axis=0) if len(q) else None
    inner, outer = section(0.55, 0.65), section(0.85, 0.95)
    if inner is None or outer is None:
        return None
    angle = math.degrees(math.atan2(outer[2] - inner[2], outer[lat] - inner[lat]))
    span = float(co[:, lat].max() - co[:, lat].min())
    pose = "T-pose" if angle >= -15 else ("A-pose" if angle >= -45 else "I-pose")
    return {"arm_angle_deg": round(angle, 1), "pose": pose, "wingspan_over_height": round(span / H, 2),
            "advice": {"T-pose": "proceed", "A-pose": "rig as-is with A-pose aware templates, or convert to T",
                       "I-pose": "arms touch the torso: convert the pose (or separate the arms) before skinning"}[pose],
            "note": "meaningful for bipeds facing " + forward + "; wingspan ≈ height on a T-pose"}


# ---------------------------------------------------------------- steps
def _bm_step(me, fn):
    bm = bmesh.new()
    bm.from_mesh(me)
    info = fn(bm) or {}
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()
    return info


def step_weld(me, a):
    d = float(a.get("merge_distance", 1e-4))

    def f(bm):
        n = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=d)
        return {"merged": n - len(bm.verts), "distance": d}
    return _bm_step(me, f)


def step_loose(me, a):
    keep_e = bool(a.get("keep_loose_edges", False))

    def f(bm):
        e = [] if keep_e else [x for x in bm.edges if not x.link_faces]
        if e:
            bmesh.ops.delete(bm, geom=e, context="EDGES")
        v = [x for x in bm.verts if not x.link_edges]
        if v:
            bmesh.ops.delete(bm, geom=v, context="VERTS")
        return {"edges_removed": len(e), "verts_removed": len(v)}
    return _bm_step(me, f)


def step_degenerate(me, a):
    d = float(a.get("merge_distance", 1e-4))

    def f(bm):
        nf, ne = len(bm.faces), len(bm.edges)
        bmesh.ops.dissolve_degenerate(bm, dist=d, edges=bm.edges)
        return {"faces_removed": nf - len(bm.faces), "edges_removed": ne - len(bm.edges)}
    return _bm_step(me, f)


def step_holes(me, a):
    sides = int(a.get("holes_max_sides", 8))

    def f(bm):
        nf = len(bm.faces)
        bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=sides)
        return {"faces_added": len(bm.faces) - nf, "max_sides": sides}
    return _bm_step(me, f)


def step_normals(me, a):
    def f(bm):
        before = [f_.normal.copy() for f_ in bm.faces]
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        flipped = sum(1 for f_, n in zip(bm.faces, before) if f_.normal.dot(n) < 0)
        return {"faces_flipped": flipped}
    return _bm_step(me, f)


def step_ngons(me, a):
    mode = a.get("ngons", "triangulate")

    def f(bm):
        ng = [x for x in bm.faces if len(x.verts) > 4]
        if mode == "triangulate" and ng:
            bmesh.ops.triangulate(bm, faces=ng, quad_method="BEAUTY", ngon_method="BEAUTY")
        return {"ngons": len(ng), "mode": mode}
    return _bm_step(me, f)


def step_transforms(ob, a):
    if ob.data.users > 1:
        return {"skipped": "mesh data shared by several objects"}
    if ob.parent is not None:
        return {"skipped": f"parented to {ob.parent.name}: apply on the parent hierarchy instead"}
    mb = ob.matrix_basis.copy()
    if mb == Matrix.Identity(4):
        return {"applied": False}
    ob.data.transform(mb)
    if mb.determinant() < 0:
        ob.data.flip_normals()
    ob.matrix_basis = Matrix.Identity(4)
    ob.data.update()
    return {"applied": True, "negative_scale_fixed": mb.determinant() < 0}


def step_origin(ob, a):
    co = np.array([v.co[:] for v in ob.data.vertices])
    if not len(co):
        return {}
    mn, mx = co.min(axis=0), co.max(axis=0)
    base = Vector(((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]))
    if base.length < 1e-7:
        return {"moved": False}
    ob.data.transform(Matrix.Translation(-base))
    ob.matrix_world = ob.matrix_world @ Matrix.Translation(base)
    return {"moved": True, "offset": [round(x, 5) for x in base]}


def _decimate_once(ob, ratio, mode, d):
    mod = ob.modifiers.new("U3D_Decimate", "DECIMATE")
    mod.decimate_type = mode
    if mode == "COLLAPSE":
        mod.ratio = max(0.0001, min(1.0, ratio))
        mod.use_collapse_triangulate = False
        if d.get("protect_group") and d["protect_group"] in ob.vertex_groups:
            mod.vertex_group = d["protect_group"]
            mod.invert_vertex_group = True
            mod.vertex_group_factor = 1.0
        if d.get("symmetry"):
            mod.use_symmetry = True
    elif mode == "PLANAR":
        mod.angle_limit = math.radians(float(d.get("angle_deg", 5.0)))
    else:
        mod.iterations = int(d.get("iterations", 1))
    # apply: move to the end of the stack's evaluation by evaluating only this modifier
    others = [(m, m.show_viewport) for m in ob.modifiers if m != mod]
    for m, _ in others:
        m.show_viewport = False
    dg = bpy.context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    for m, vis in others:
        m.show_viewport = vis
    ob.modifiers.remove(mod)
    return new


def step_decimate(ob, a, warnings):
    d = a.get("decimate")
    if not d:
        return None
    if a.get("print"):
        return {"skipped": "print model"}
    if ob.data.shape_keys:
        warnings.append("decimate drops shape keys — decimate before authoring them")
    mode = d.get("mode", "COLLAPSE")
    m0 = stats(ob.data)
    tris0 = m0["tris"]
    tries = []
    if mode == "COLLAPSE":
        target = int(d["target_tris"]) if d.get("target_tris") else int(tris0 * float(d.get("ratio", 0.5)))
        if target >= tris0:
            return {"skipped": f"already at {tris0} tris (target {target})"}
        relax = float(d.get("max_relax", 2.0))
        targets = [target] + [int(target * f) for f in (1.25, 1.5, 1.75, 2.0) if f <= relax]
    else:
        targets = [None]
    passes = max(1, int(d.get("passes", 2)))
    kept = None
    for tgt in targets:
        work = ob.data.copy()
        orig = ob.data
        ob.data = work
        try:
            if tgt is not None:
                for p in range(passes):
                    cur = stats(ob.data)["tris"]
                    remaining = passes - p
                    ratio = (tgt / cur) ** (1.0 / remaining) if cur > tgt else 1.0
                    new = _decimate_once(ob, ratio, mode, d)
                    old = ob.data
                    ob.data = new
                    if old != orig:
                        bpy.data.meshes.remove(old)
            else:
                new = _decimate_once(ob, 1.0, mode, d)
                old = ob.data
                ob.data = new
                bpy.data.meshes.remove(old)
            m1 = stats(ob.data)
            ok = m1["open_edges"] <= m0["open_edges"] and m1["nonmanifold_edges"] <= m0["nonmanifold_edges"]
            tries.append({"target": tgt, "tris": m1["tris"], "open_edges": m1["open_edges"],
                          "nonmanifold_edges": m1["nonmanifold_edges"], "accepted": ok})
            if ok:
                kept = ob.data
                ob.data = orig
                break
            res = ob.data
            ob.data = orig
            bpy.data.meshes.remove(res)
        except Exception:
            ob.data = orig
            raise
    if kept is None:
        warnings.append("decimate refused: every try opened the mesh (more open or non-manifold edges than "
                        "before) — protect thin parts with protect_group, rebuild them as curves, or decimate less")
        return {"applied": False, "before_tris": tris0, "tries": tries}
    old = ob.data
    name = old.name
    ob.data = kept
    if old.users == 0:
        bpy.data.meshes.remove(old)
    kept.name = name
    return {"applied": True, "before_tris": tris0, "after_tris": tries[-1]["tris"], "tries": tries,
            "relaxed": tries[-1]["target"] != targets[0]}


# ---------------------------------------------------------------- driver
def run(args: dict) -> dict:
    src = bpy.data.objects.get(args.get("object", ""))
    if src is None or src.type != "MESH":
        return C.result_error("mesh object required")
    warnings = []
    md = float(args.get("merge_distance", 1e-4))
    before = stats(src.data, md)
    if args.get("in_place"):
        ob = src
    else:
        ob = src.copy()
        ob.data = src.data.copy()
        ob.name = args.get("name") or src.name + "_clean"
        ob.data.name = ob.name
        for c in src.users_collection:
            c.objects.link(ob)
    steps = args.get("steps") or DEFAULT_STEPS
    if args.get("print"):
        steps = [s for s in steps if s not in ("weld", "decimate")]
        warnings.append("print model: weld and decimate skipped (a merge can break a closed printable model)")
    log, dec = [], None
    for s in steps:
        if s == "weld":
            log.append({"step": s, **step_weld(ob.data, args)})
        elif s == "loose":
            log.append({"step": s, **step_loose(ob.data, args)})
        elif s == "degenerate":
            log.append({"step": s, **step_degenerate(ob.data, args)})
        elif s == "holes":
            log.append({"step": s, **step_holes(ob.data, args)})
        elif s == "normals":
            log.append({"step": s, **step_normals(ob.data, args)})
        elif s == "ngons":
            log.append({"step": s, **step_ngons(ob.data, args)})
        elif s == "transforms":
            log.append({"step": s, **step_transforms(ob, args)})
        elif s == "decimate":
            dec = step_decimate(ob, args, warnings)
            if dec is not None:
                log.append({"step": s, **{k: v for k, v in dec.items() if k != "tries"}})
        elif s == "origin":
            log.append({"step": s, **step_origin(ob, args)})
        else:
            return C.result_error(f"unknown step {s}")
    after = stats(ob.data, md)
    if after["duplicate_verts"]:
        warnings.append(f"{after['duplicate_verts']} vertices still sit on top of another (split edges / UV seams "
                        "split as geometry): weld before skinning or the skin opens at the joints")
    if after["open_edges"] > before["open_edges"] or after["nonmanifold_edges"] > before["nonmanifold_edges"]:
        warnings.append("cleanup left more open or non-manifold edges than the source — welding seams where three "
                        "faces meet makes non-manifold edges: inspect those spots before UVs or skinning")
    if after["ngons"]:
        warnings.append(f"{after['ngons']} n-gons left (deforming meshes: triangulate or quad them)")
    out = {"object": ob.name, "source": src.name, "in_place": ob == src, "before": before, "after": after,
           "steps": log, "decimate": dec, "budget": budget_report(after["tris"], args.get("budget")),
           "pose": measure_pose(ob, args.get("forward", "-Y")) if args.get("measure_pose") else None,
           "warnings": warnings}
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", f"cleanup-{ob.name}.json"), out)
    return C.result_ok(**out)
