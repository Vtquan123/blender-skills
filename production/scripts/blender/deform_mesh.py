"""Build the deform mesh (deformation-prep step 4, gate G4a).

Pipeline: copy source → weld + fill tiny holes → (pre-decimate for speed) → QuadriFlow quad remesh
→ shrinkwrap to source → enforce joint loops with edge-ring cuts → shrinkwrap again.

The source object is never modified.

args:
    source          (str, required)  source mesh object
    name            (str)            new object name, default "<source>_deform"
    target_faces    (int, required)  quad face target (≈ triangle budget / 2)
    predecimate_tris (int, 300000)   decimate the COPY to this many triangles before QuadriFlow (0 = off)
    symmetry        (bool, False)    QuadriFlow mesh symmetry (X)
    joints          (list[dict])     [{"name": "elbow.L", "head": [x,y,z], "axis": [x,y,z],
                                       "loops": 3, "band_halfwidth": 0.02, "radius": 0.02}]  (from joint_analysis.py)
    shrinkwrap_offset (float, 0.0)
    collection      (str, "COL_Deform")
"""
import importlib.util
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


def _activate(ob):
    for o in bpy.context.view_layer.objects:
        if o is not None:  # stale entries right after bpy.data.objects.remove
            o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def copy_source(src, name, collection):
    col = bpy.data.collections.get(collection) or bpy.data.collections.new(collection)
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = ob.data.name = name
    ob.modifiers.clear()
    col.objects.link(ob)
    _activate(ob)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)  # local == world from here on
    return ob


def weld_and_fill(ob, dist=1e-5, max_hole_sides=64):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    boundary = [e for e in bm.edges if e.is_boundary]
    if boundary:
        bmesh.ops.holes_fill(bm, edges=boundary, sides=max_hole_sides)
    bm.to_mesh(ob.data)
    bm.free()


def predecimate(ob, tris):
    ob.data.calc_loop_triangles()
    n = len(ob.data.loop_triangles)
    if tris and n > tris:
        mod = ob.modifiers.new("PreDecimate", "DECIMATE")
        mod.ratio = tris / n
        _activate(ob)
        bpy.ops.object.modifier_apply(modifier=mod.name)


def shrinkwrap(ob, target, offset=0.0):
    mod = ob.modifiers.new("ShrinkToSource", "SHRINKWRAP")
    mod.target = target
    mod.wrap_method = "NEAREST_SURFACEPOINT"
    mod.offset = offset
    _activate(ob)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def edge_ring(start_edge, allowed=lambda e: True, max_len=4096):
    """Walk an edge ring through quads in both directions, staying on edges where allowed(e) is True."""
    ring = [start_edge]
    seen = {start_edge.index}
    for f0 in start_edge.link_faces[:2]:
        e, f = start_edge, f0
        while f is not None and len(f.edges) == 4 and len(ring) < max_len:
            edges = list(f.edges)
            opp = edges[(edges.index(e) + 2) % 4]
            if opp.index in seen or not allowed(opp):
                break
            ring.append(opp)
            seen.add(opp.index)
            nxt = [lf for lf in opp.link_faces if lf != f]
            e, f = opp, (nxt[0] if nxt else None)
    return ring


def enforce_joint_loops(ob, joints):
    results = []
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    for j in joints:
        head, axis = np.array(j["head"], float), np.array(j["axis"], float)
        axis /= np.linalg.norm(axis) or 1.0
        hw, need = float(j["band_halfwidth"]), int(j.get("loops", 3))
        bm.edges.ensure_lookup_table()
        cand, steps = [], []
        for e in bm.edges:
            a, b = np.array(e.verts[0].co), np.array(e.verts[1].co)
            mid = (a + b) / 2
            if abs((mid - head) @ axis) > hw:
                continue
            v = b - a
            ln = np.linalg.norm(v)
            if ln == 0:
                continue
            if abs(v @ axis) / ln > 0.7:
                cand.append((abs((mid - head) @ axis), e))   # closest to the joint plane first
                steps.append(abs(v @ axis))
        if not cand:
            results.append({"joint": j.get("name"), "status": "no_axial_edges_in_band"})
            continue
        step = float(np.median(steps))
        bm.verts.index_update()
        me_co = np.array([v.co for v in bm.verts])
        me_ed = np.array([[ed.verts[0].index, ed.verts[1].index] for ed in bm.edges])
        radius = float(j.get("radius", hw))
        have = C.count_rings(me_co, me_ed, head, axis, hw, radius)["rings"]
        missing = max(0, need - have)
        if missing == 0:
            results.append({"joint": j.get("name"), "status": "ok", "rings": have})
            continue
        cand.sort(key=lambda x: x[0])
        t_of = {e.index: float(((np.array(e.verts[0].co) + np.array(e.verts[1].co)) / 2 - head) @ axis) for _, e in cand}
        start = cand[0][1]
        t0 = t_of[start.index]
        # stay on ONE level around the limb: same axial position within one edge step (spiral-safe)
        ring = edge_ring(start, allowed=lambda e: e.index in t_of and abs(t_of[e.index] - t0) <= step,
                         max_len=len(t_of))
        bmesh.ops.subdivide_edges(bm, edges=ring, cuts=missing, use_grid_fill=True)
        results.append({"joint": j.get("name"), "status": "cut", "rings_before": have, "cuts": missing,
                        "ring_edges": len(ring)})
    bm.to_mesh(ob.data)
    bm.free()
    return results


def _quadriflow_scale(me, limit=1e-4, margin=3.0) -> float:
    """Factor that lifts the shortest edge above QuadriFlow's per-axis 1e-4 duplicate-vertex check."""
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    co, ev = co.reshape(-1, 3), ev.reshape(-1, 2)
    if not len(ev):
        return 1.0
    shortest = float(np.abs(co[ev[:, 0]] - co[ev[:, 1]]).max(1).min())
    if shortest >= limit * margin:
        return 1.0
    return float(min(limit * margin / max(shortest, 1e-12), 1e4))


def run(args: dict) -> dict:
    src = bpy.data.objects.get(args.get("source", ""))
    if src is None or src.type != "MESH":
        return C.result_error("source mesh required")
    if "target_faces" not in args:
        return C.result_error("target_faces required (from budgets.triangles / 2)")
    name = args.get("name", f"{src.name}_deform")
    ob = copy_source(src, name, args.get("collection", "COL_Deform"))
    weld_and_fill(ob)
    predecimate(ob, int(args.get("predecimate_tris", 300000)))
    _activate(ob)
    # Blender's QuadriFlow pre-check rejects edges shorter than 1e-4 on every axis ("needs to be manifold…"),
    # which small real-scale assets (a 25 cm kitten) hit after decimation. QuadriFlow is scale-invariant,
    # so remesh a temporarily enlarged copy and scale it back.
    k = _quadriflow_scale(ob.data)
    if k != 1.0:
        ob.data.transform(Matrix.Scale(k, 4))
    res = bpy.ops.object.quadriflow_remesh(target_faces=int(args["target_faces"]),
                                           use_mesh_symmetry=bool(args.get("symmetry", False)),
                                           use_preserve_sharp=False, use_preserve_boundary=False,
                                           preserve_attributes=False, smooth_normals=False, seed=0)
    if k != 1.0:
        ob.data.transform(Matrix.Scale(1.0 / k, 4))
        ob.data.update()
    if "FINISHED" not in res:
        return C.result_error(f"QuadriFlow failed: {res} (mesh must be manifold with consistent normals)",
                              object=ob.name, prescale=k)
    shrinkwrap(ob, src, float(args.get("shrinkwrap_offset", 0.0)))
    loops = enforce_joint_loops(ob, args.get("joints", [])) if args.get("joints") else []
    if loops:
        shrinkwrap(ob, src, float(args.get("shrinkwrap_offset", 0.0)))
    ob.data.shade_smooth()  # QuadriFlow output is flat; a flat cage bakes faceting into the normal map
    return C.result_ok(object=ob.name, stats=C.mesh_stats(ob), joint_loops=loops, prescale=k)
