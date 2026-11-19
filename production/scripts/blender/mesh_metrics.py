"""Geometry and surface metrics for gates G2 (geometry) and G3 (surface).

args:
    target        (str, required)  object name of the processed mesh
    source        (str, optional)  object name of the original/source mesh (for silhouette deviation)
    samples       (int, 4000)      vertices sampled for deviation
    uv_resolution (int, 256)       raster size for the UV overlap estimate
    project_dir   (str, optional)  write reports/metrics-<target>.json

returns: dict with geometry, deviation, uv metrics
"""
import importlib.util
import os
import sys

import bpy
import numpy as np
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


def _bvh_world(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ob.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys)


def silhouette_deviation(target, source, samples=4000) -> dict:
    """Two-way surface distance (target→source and source→target) on sampled vertices, in metres
    and as a fraction of the source bbox diagonal."""
    bt, bs = _bvh_world(target), _bvh_world(source)
    pt = C.evaluated_vertex_positions(target)
    ps = C.evaluated_vertex_positions(source)
    rng = np.random.default_rng(0)

    def dists(points, tree):
        idx = rng.choice(len(points), size=min(samples, len(points)), replace=False)
        out = []
        for p in points[idx]:
            hit = tree.find_nearest(p)
            out.append(hit[3] if hit[0] is not None else np.nan)
        return np.array(out)

    d1, d2 = dists(pt, bs), dists(ps, bt)
    mn, mx = C.world_bbox([source])
    diag = float(np.linalg.norm(np.array(mx) - np.array(mn))) or 1.0
    both = np.concatenate([d1, d2])
    return {"max_m": float(np.nanmax(both)), "mean_m": float(np.nanmean(both)),
            "p95_m": float(np.nanpercentile(both, 95)), "max_ratio": float(np.nanmax(both) / diag),
            "bbox_diag_m": diag}


def uv_overlap(ob, res=256) -> dict:
    me = ob.data
    if not me.uv_layers:
        return {"uv_layers": 0}
    me.calc_loop_triangles()
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("loops", tris)
    tris = tris.reshape(-1, 3)
    grid = np.zeros((res, res), dtype=np.int32)
    outside = 0
    for t in tris:
        a, b, c = uv[t[0]] * res, uv[t[1]] * res, uv[t[2]] * res
        lo = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        hi = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        if (lo < 0).any() or (hi > res).any():
            outside += 1
        lo = np.clip(lo, 0, res - 1)
        hi = np.clip(hi, 0, res)
        if hi[0] <= lo[0] or hi[1] <= lo[1]:
            continue
        xs, ys = np.meshgrid(np.arange(lo[0], hi[0]) + 0.5, np.arange(lo[1], hi[1]) + 0.5)
        p = np.stack([xs.ravel(), ys.ravel()], 1)
        v0, v1, v2 = c - a, b - a, p - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-12:
            continue
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        inside = (v >= 0) & (w >= 0) & (v + w <= 1)
        grid[p[inside, 1].astype(int), p[inside, 0].astype(int)] += 1
    used = (grid > 0).sum()
    return {"uv_layers": len(me.uv_layers), "coverage": float(used / grid.size),
            "overlap_ratio": float((grid > 1).sum() / max(1, used)), "tris_outside_0_1": int(outside),
            "resolution": res}


def run(args: dict) -> dict:
    tgt = bpy.data.objects.get(args.get("target", ""))
    if tgt is None or tgt.type != "MESH":
        return C.result_error(f"target mesh not found: {args.get('target')}")
    out = {"geometry": C.mesh_stats(tgt),
           "transforms_applied": all(abs(s - 1) < 1e-5 for s in tgt.scale)
           and all(abs(r) < 1e-6 for r in tgt.rotation_euler)}
    src_name = args.get("source")
    if src_name:
        src = bpy.data.objects.get(src_name)
        if src is None:
            return C.result_error(f"source mesh not found: {src_name}")
        out["silhouette"] = silhouette_deviation(tgt, src, int(args.get("samples", 4000)))
    out["uv"] = uv_overlap(tgt, int(args.get("uv_resolution", 256)))
    if args.get("project_dir"):
        out["written"] = C.write_json(os.path.join(args["project_dir"], "reports", f"metrics-{tgt.name}.json"), out)
    return C.result_ok(**out)
