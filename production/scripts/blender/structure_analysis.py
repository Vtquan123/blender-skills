"""Structure analysis: what can move and how, measured from geometry alone (Production Mode ANALYZE → PLAN).

Works for any model — creature, ball, vehicle, plant, furniture, prop — and does not rely on object names or a
category preset. Surface points are sampled from the triangles and voxelised, so split UV seams, fused AI meshes
and separate parts are handled alike. Measured:

  parts        connected pieces (separate objects or disconnected shells) with a shape class from PCA and radial
               spread: sphere, disk (wheel-like, with axis and radius), elongated, flat panel, blob
  contacts     clusters of surface touching the ground plane (feet, wheels, a base, a strip)
  skeleton     Reeb graph of geodesic distance on the voxel surface from the body core: extremities (legs, head,
               tail, branches) with length, thickness, tip, direction, ground contact; junctions
  symmetry     mirror score across each horizontal axis
  wheels       disks touching the ground — separate parts, or circles in the outermost side slab of a fused mesh
  archetypes   scored candidates with reasons:
                 rigid_whole  (one rigid body: ball → roll/bounce, prop → turntable/hover/bounce)
                 rigid_parts  (separate rigid parts on pivots: vehicle wheels/steering, lid, door, drawer)
                 chain_flex   (bone chains along branches: tree/plant sway, snake/rope/tentacle)
                 skinned      (skin over a skeleton: legged creature, biped)
                 morph        (shape keys: soft blob, squash without a rig)
  questions    what must be confirmed before planning — only where the measurement is not decisive or the choice
               changes the result — each with options, a recommendation and why (AskUserQuestion-ready)

args:
    objects       (list[str], optional)  mesh objects to analyse (default: every visible mesh in the scene)
    scene         (str, optional)        scene to read (default: current)
    source        (str, optional)        instead of objects: import this file into a scratch scene, analyse, remove
    resolution    (int, 120)             voxels along the bounding-box diagonal
    up_axis       (str, "Z")             world up
    real_size_m   (float, optional)      longest real dimension, when known (scales the clip suggestions)
    project_dir   (str, optional)        write reports/structure.json
returns {"ok", "structure": {...}}
"""
import importlib.util
import math
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
OFFS = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)])


# ----------------------------------------------------------------------------------------------- geometry intake
def _gather(objs, scene):
    vl = scene.view_layers[0]
    with bpy.context.temp_override(scene=scene, view_layer=vl):
        dg = bpy.context.evaluated_depsgraph_get()
        Vs, Ts, ids, off = [], [], [], 0
        for k, ob in enumerate(objs):
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
            me.calc_loop_triangles()
            v = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", v); v = v.reshape(-1, 3)
            t = np.empty(len(me.loop_triangles) * 3, dtype=np.int64); me.loop_triangles.foreach_get("vertices", t)
            mw = np.array(ob.matrix_world)
            Vs.append(v @ mw[:3, :3].T + mw[:3, 3]); Ts.append(t.reshape(-1, 3) + off); ids.append(np.full(len(t) // 3, k))
            off += len(v)
            ev.to_mesh_clear()
    return np.concatenate(Vs), np.concatenate(Ts), np.concatenate(ids)


def _sample(V, T, tri_obj, n, rng):
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    p = area / max(area.sum(), 1e-18)
    pick = rng.choice(len(T), size=n, p=p)
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    P = (1 - s)[:, None] * a[pick] + (s * (1 - r2))[:, None] * b[pick] + (s * r2)[:, None] * c[pick]
    return P, tri_obj[pick], float(area.sum())


class Grid:
    """Surface voxels with 26-neighbour adjacency."""

    def __init__(self, P, obj, vox):
        self.vox = vox
        self.lo = P.min(0) - vox
        ijk = np.floor((P - self.lo) / vox).astype(np.int64)
        keys, inv = np.unique(ijk, axis=0, return_inverse=True)
        inv = inv.ravel()
        self.ijk = keys
        self.n = len(keys)
        self.centre = self.lo + (keys + 0.5) * vox
        self.count = np.bincount(inv, minlength=self.n)
        # majority object per voxel
        nobj = obj.max() + 1
        oc = np.zeros((self.n, nobj), dtype=np.int32)
        np.add.at(oc, (inv, obj), 1)
        self.obj = oc.argmax(1)
        dims = keys.max(0) + 3
        grid = -np.ones(dims, dtype=np.int64)
        grid[keys[:, 0] + 1, keys[:, 1] + 1, keys[:, 2] + 1] = np.arange(self.n)
        nb = np.empty((self.n, 26), dtype=np.int64)
        for j, o in enumerate(OFFS):
            q = keys + 1 + o
            nb[:, j] = grid[q[:, 0], q[:, 1], q[:, 2]]
        self.nb = nb
        self.P_inv = inv

    def components(self, mask_edge=None):
        """Connected components; mask_edge(u, v) → bool array to restrict edges (same shape as nb)."""
        lab = np.arange(self.n)
        valid = self.nb >= 0
        if mask_edge is not None:
            valid &= mask_edge
        nbs = np.where(valid, self.nb, np.arange(self.n)[:, None])
        while True:
            m = np.minimum(lab, lab[nbs].min(1))
            m = m[m]
            if np.array_equal(m, lab):
                break
            lab = m
        _, lab = np.unique(lab, return_inverse=True)
        return lab.ravel()

    def bfs(self, roots, allowed=None):
        dist = -np.ones(self.n, dtype=np.int64)
        fr = np.unique(np.asarray(roots))
        dist[fr] = 0
        d = 0
        while len(fr):
            d += 1
            nb = self.nb[fr].ravel()
            nb = nb[nb >= 0]
            nb = nb[dist[nb] < 0]
            if allowed is not None:
                nb = nb[allowed[nb]]
            fr = np.unique(nb)
            dist[fr] = d
        return dist


# ---------------------------------------------------------------------------------------------- shape measures
def _pca(X):
    c = X.mean(0)
    w, v = np.linalg.eigh(np.cov((X - c).T) + 1e-15 * np.eye(3))
    order = w.argsort()[::-1]
    return c, np.maximum(w[order], 1e-18), v[:, order]


def _outline_cv(q2, bins=36):
    """Circularity of an outline: spread of the farthest point per angular sector (0 = perfect circle)."""
    ang = np.arctan2(q2[:, 1], q2[:, 0])
    rr = np.linalg.norm(q2, axis=1)
    k = ((ang + math.pi) / (2 * math.pi) * bins).astype(int) % bins
    mx = np.zeros(bins)
    np.maximum.at(mx, k, rr)
    mx = mx[mx > 0]
    if len(mx) < bins * 0.8:
        return 1.0, float(rr.max()) if len(rr) else 0.0
    return float(mx.std() / max(mx.mean(), 1e-9)), float(mx.mean())


def _shape(X):
    c, w, v = _pca(X)
    r = np.linalg.norm(X - c, axis=1)
    radial_cv = float(r.std() / max(r.mean(), 1e-9))
    e2, e3 = float(math.sqrt(w[1] / w[0])), float(math.sqrt(w[2] / w[0]))
    ax = v[:, 2]
    q = (X - c) - np.outer((X - c) @ ax, ax)
    q2 = np.c_[q @ v[:, 0], q @ v[:, 1]]
    out_cv, out_r = _outline_cv(q2)
    scores = {
        "sphere": max(0.0, 1 - radial_cv / 0.12) * min(e3 / 0.85, 1.0),
        # disk/wheel: round outline around the thin axis, thinner than wide
        "disk": max(0.0, 1 - out_cv / 0.08) * max(0.0, min(1.0, (0.85 - e3) / 0.25)) * min(e2 / 0.85, 1.0),
        "elongated": max(0.0, 1 - e2 / 0.45),
        "panel": max(0.0, 1 - e3 / 0.35) * min(e2 / 0.4, 1.0) * (1 - max(0.0, 1 - out_cv / 0.08)),
    }
    scores["blob"] = 0.3                     # anything without a clearer class
    kind = max(scores, key=scores.get)
    out = {"class": kind, "scores": {k: round(s, 2) for k, s in scores.items()}, "centre": _r(c),
           "axes_ratio": [1.0, round(e2, 3), round(e3, 3)], "major_axis": _r(v[:, 0]), "minor_axis": _r(v[:, 2])}
    if kind == "disk":
        out["radius"] = round(out_r, 4)
        out["axis"] = _r(ax)
    if kind == "sphere":
        out["radius"] = round(float(r.mean()), 4)
    return out


def _r(x, n=4):
    return [round(float(a), n) for a in x]


def _circle_fit(U):
    """Algebraic (Kåsa) circle fit in 2D → centre, radius, relative residual."""
    A = np.c_[2 * U, np.ones(len(U))]
    b = (U ** 2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[:2]
    rad = math.sqrt(max(sol[2] + cx * cx + cy * cy, 1e-18))
    res = np.abs(np.linalg.norm(U - [cx, cy], axis=1) - rad)
    return np.array([cx, cy]), rad, float(np.median(res) / rad)


# ----------------------------------------------------------------------------------------------- analysis steps
def _contacts(G, up, ground, height):
    tol = max(0.02 * height, 1.5 * G.vox)
    near = (G.centre @ up - ground) < tol
    if not near.any():
        return [], near
    # cluster contact voxels by adjacency inside the contact band (+1 ring)
    allowed = near
    lab = G.components(mask_edge=allowed[G.nb.clip(0)] & allowed[:, None])
    out = []
    for l in np.unique(lab[near]):
        idx = np.where(near & (lab == l))[0]
        if len(idx) < 2:
            continue
        P = G.centre[idx]
        span = P.max(0) - P.min(0)
        out.append({"voxels": int(len(idx)), "centre": _r(P.mean(0)), "span": _r(span), "_idx": idx})
    out.sort(key=lambda c: -c["voxels"])
    return out, near


def _reeb(G, members, root, step):
    """Level-set graph of BFS distance from root inside `members` (bool mask)."""
    dist = G.bfs([root], allowed=members)
    ok = dist >= 0
    level = np.where(ok, dist // step, -1)
    same = (level[G.nb.clip(0)] == level[:, None]) & (G.nb >= 0) & ok[:, None]
    lab = G.components(mask_edge=same)
    nodes = {}
    ids = np.where(ok)[0]
    for l in np.unique(lab[ids]):
        vs = ids[lab[ids] == l]
        nodes[int(l)] = {"level": int(level[vs[0]]), "verts": vs, "centre": G.centre[vs].mean(0), "count": len(vs)}
    # parent edges: node → node one level down
    u = np.repeat(np.arange(G.n), 26)
    v = G.nb.ravel()
    m = (v >= 0) & ok[u] & ok[np.clip(v, 0, None)]
    u, v = u[m], v[m]
    down = level[v] == level[u] - 1
    pairs = np.unique(np.c_[lab[u[down]], lab[v[down]]], axis=0)
    parent = {}
    for a, b in pairs:
        a, b = int(a), int(b)
        if a not in parent or nodes[b]["count"] > nodes[parent[a]]["count"]:
            parent[a] = b
    children = {k: [] for k in nodes}
    for a, b in parent.items():
        children[b].append(a)
    return nodes, parent, children, dist


def _extremities(G, nodes, parent, children, min_len_levels, step, up, ground):
    leaves = [k for k, ch in children.items() if not ch]
    ext = []
    _ext_voxels.clear()
    used = set()
    for leaf in sorted(leaves, key=lambda k: -nodes[k]["level"]):
        path = [leaf]
        k = leaf
        while k in parent:
            p = parent[k]
            if len(children[p]) > 1 and len(path) >= 1:
                # stop at a junction whose other subtree is substantial
                path.append(p)
                break
            path.append(p)
            k = p
        if len(path) < min_len_levels or path[0] in used:
            continue
        used.update(path[:-1])
        tip = nodes[path[0]]["centre"]
        base = nodes[path[-1]]["centre"]
        radii = [nodes[q]["count"] * G.vox / (2 * math.pi * step) for q in path[1:-1]] or [nodes[path[0]]["count"] * G.vox / (2 * math.pi * step)]
        length = (len(path) - 1) * step * G.vox
        d = tip - base
        ext.append({"tip": _r(tip), "base": _r(base), "length": round(length, 4),
                    "radius_median": round(float(np.median(radii)), 4),
                    "slenderness": round(length / max(2 * float(np.median(radii)), 1e-6), 2),
                    "direction": _r(d / max(np.linalg.norm(d), 1e-9), 3),
                    "touches_ground": bool((np.min(G.centre[nodes[path[0]]["verts"]] @ up) - ground) < max(0.03 * (G.extent_up), 2 * G.vox)),
                    "levels": len(path)})
        _ext_voxels.append(np.concatenate([nodes[q]["verts"] for q in path[:-1]]))
    return ext


_ext_voxels = []


def _hull_planes(P, rng, n=4000):
    import bmesh
    from mathutils import Vector
    sub = P[rng.choice(len(P), size=min(n, len(P)), replace=False)]
    bm = bmesh.new()
    for p in sub:
        bm.verts.new(Vector(p))
    res = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
    planes = []
    for f in [g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)]:
        f.normal_update()
        nrm = np.array(f.normal)
        planes.append((nrm, float(nrm @ np.array(f.verts[0].co))))
    bm.free()
    N = np.array([p[0] for p in planes]); D = np.array([p[1] for p in planes])
    return N, D


def _hull_depth(X, N, D):
    """Distance of points inside the convex hull to its surface (0 on the hull)."""
    if len(X) == 0 or len(N) == 0:
        return np.zeros(len(X))
    return np.clip((D[None, :] - X @ N.T).min(1), 0, None)


def _symmetry(G, axis, centre):
    """Mirror the voxel centres across the plane through `centre` with normal `axis`; share that land on a voxel."""
    P = G.centre
    d = (P - centre) @ axis
    Q = P - 2 * d[:, None] * axis
    ijk = np.floor((Q - G.lo) / G.vox).astype(np.int64)
    keys = {tuple(k) for k in G.ijk}
    hit = 0
    for k in ijk:
        if tuple(k) in keys or any((k[0] + dx, k[1], k[2]) in keys for dx in (-1, 1)):
            hit += 1
    return hit / max(len(P), 1)


def _side_wheels(G, up, fwd, lat, ground, height, contacts):
    """Wheels in a fused mesh: circles in the outermost lateral slabs that touch the ground."""
    found = []
    L = G.centre @ lat
    for sgn in (1, -1):
        s = sgn * L
        edge = np.percentile(s, 99.5)
        slab = s > edge - 3 * G.vox
        if slab.sum() < 12:
            continue
        sub = np.where(slab)[0]
        lab = G.components(mask_edge=slab[G.nb.clip(0)] & slab[:, None] & (G.nb >= 0))
        for l in np.unique(lab[sub]):
            vs = sub[lab[sub] == l]
            if len(vs) < 12:
                continue
            U = np.c_[G.centre[vs] @ fwd, G.centre[vs] @ up - ground]
            c0 = U.mean(0)
            ang = np.arctan2(*(U - c0).T[::-1]); rr = np.linalg.norm(U - c0, axis=1)
            k = ((ang + math.pi) / (2 * math.pi) * 36).astype(int) % 36
            far = np.zeros(36, dtype=np.int64) - 1
            for i in np.argsort(rr):
                far[k[i]] = i
            far = far[far >= 0]
            if len(far) < 24:
                continue
            c, rad, res = _circle_fit(U[far])
            touches = abs((c[1] - rad)) < max(0.08 * rad, 2 * G.vox)
            fill = len(vs) * G.vox ** 2 / (math.pi * rad * rad)
            if res < 0.12 and touches and rad > 3 * G.vox and rad < 0.6 * height:
                found.append({"centre": _r(c[0] * fwd + (c[1] + ground) * up + float(np.median(G.centre[vs] @ lat)) * lat),
                              "radius": round(rad, 4), "axis": _r(lat), "side": sgn, "fit_residual": round(res, 3),
                              "face_fill": round(min(fill, 1.0), 2), "source": "fused_side_slab"})
    return found


# ---------------------------------------------------------------------------------------------- interpretation
def _archetypes(S):
    parts, ext, cont, wheels = S["parts"], S["skeleton"]["extremities"], S["contacts"], S["wheels"]
    main = parts[0] if parts else {"class": "blob", "scores": {}}
    legs = [e for e in ext if e["touches_ground"] and e["direction"][2] < -0.3]
    h, w = S["size"]["height"], S["size"]["width_major"]
    narrow = len(cont) == 1 and cont[0]["voxels"] * S["voxel"] ** 2 < 0.1 * w * w
    cand = []

    def add(name, score, reasons, subtype=None):
        cand.append({"archetype": name, "subtype": subtype, "score": round(min(max(score, 0), 1), 2), "reasons": reasons})

    sph = main["scores"].get("sphere", 0)
    if len(parts) == 1 and len(ext) <= 1 and sph > 0.5:
        add("rigid_whole", 0.6 + 0.4 * sph, [f"one closed body, sphere score {sph:.2f}", "no limbs or branches"], "round")
    elif len([p for p in parts if p["share"] > 0.02]) == 1 and len(ext) <= 1:
        add("rigid_whole", 0.7, ["one compact body without limbs or branches"], "prop")
    if len(wheels) >= 3:
        add("rigid_parts", 0.55 + 0.1 * min(len(wheels), 4),
            [f"{len(wheels)} wheel-like disks touching the ground" + (" (fused into the body)" if any(x.get('source') == 'fused_side_slab' for x in wheels) else " (separate parts)")],
            "vehicle")
    panels = [p for p in parts[1:] if p["class"] == "panel" and p["share"] > 0.05]
    if len(parts) >= 2 and panels and not wheels:
        add("rigid_parts", 0.6, [f"{len(panels)} flat separate part(s) on a larger body (lid, door, flap)"], "hinged")
    if len(legs) >= 2 and len(wheels) < 3 and not (narrow and len(cont) == 1):
        sym = max(S["symmetry"].values()) if S["symmetry"] else 0
        sub = "quadruped" if len(legs) >= 4 else ("biped" if len(legs) == 2 else "multi_legged")
        add("skinned", 0.45 + 0.1 * min(len(legs), 4) + 0.2 * (sym > 0.8),
            [f"{len(legs)} limb tips touch the ground", f"bilateral symmetry {sym:.2f}", f"{len(ext) - len(legs)} other extremities (head, tail, ears)"], sub)
    trunk = [e for e in legs if e["length"] > 0.25 * h]
    branches = [e for e in ext if not e["touches_ground"]]
    if narrow and S["centre_height_ratio"] > 0.45 and (trunk or len(branches) >= 2):
        add("chain_flex", 0.55 + 0.1 * bool(trunk) + 0.06 * min(len(branches), 4),
            ["one narrow ground contact with the mass above it" + (" on a long trunk" if trunk else ""), f"{len(branches)} branches"], "plant")
    if main.get("axes_ratio", [1, 1, 1])[1] < 0.3 and len(legs) < 2 and main["share"] > 0.9:
        add("chain_flex", 0.75, [f"one elongated body (axis ratio {main['axes_ratio'][1]}) without legs"], "body_chain")
    if not cand or max(c["score"] for c in cand) < 0.5:
        add("morph", 0.35, ["no clear rigid parts, limbs or chains; shape keys can squash or wobble it"], "soft")
    else:
        add("morph", 0.15, ["alternative for small squash/wobble effects without a rig"], "soft")
    cand.sort(key=lambda c: -c["score"])
    return cand


CLIPS = {
    ("rigid_whole", "round"): ["roll", "bounce", "idle_wobble"],
    ("rigid_whole", "prop"): ["turntable", "hover", "bounce_in"],
    ("rigid_parts", "vehicle"): ["drive", "idle_engine", "turn"],
    ("rigid_parts", "hinged"): ["open", "close", "idle"],
    ("chain_flex", "plant"): ["wind_sway", "gust"],
    ("chain_flex", "body_chain"): ["slither", "idle"],
    ("skinned", "quadruped"): ["idle", "walk", "trot", "sit"],
    ("skinned", "biped"): ["idle", "walk", "wave"],
    ("skinned", "multi_legged"): ["idle", "walk"],
    ("morph", "soft"): ["squash", "wobble"],
}


def _questions(S):
    qs = []
    a = S["archetypes"]
    top = a[0]
    margin = top["score"] - (a[1]["score"] if len(a) > 1 else 0)
    if top["score"] < 0.7 or margin < 0.2:
        qs.append({"id": "archetype", "header": "Motion type", "blocking": True,
                   "question": "How should this model move? The geometry does not settle it.",
                   "options": [{"label": f"{c['archetype']}/{c['subtype']}", "description": "; ".join(c["reasons"])[:150]} for c in a[:3]],
                   "recommended": f"{top['archetype']}/{top['subtype']}",
                   "why": f"top score {top['score']} with margin {margin:.2f}"})
    f = S["forward"]
    if f["confidence"] < 0.8 and top["archetype"] in ("skinned", "rigid_parts", "chain_flex") and top["subtype"] not in ("plant",):
        qs.append({"id": "forward", "header": "Front", "blocking": True,
                   "question": "Which way does the model face (its front)?",
                   "options": [{"label": f["value"], "description": "measured guess"},
                               {"label": ("-" + f["value"]) if not f["value"].startswith("-") else f["value"][1:], "description": "the opposite end"}],
                   "recommended": f["value"], "why": f["basis"]})
    if top["archetype"] == "rigid_parts" and top["subtype"] == "vehicle":
        fused = any(w.get("source") == "fused_side_slab" for w in S["wheels"])
        if fused:
            qs.append({"id": "split_wheels", "header": "Wheels", "blocking": True,
                       "question": f"The {len(S['wheels'])} wheels are fused into the body. Cut them out as separate parts so they can spin?",
                       "options": [{"label": "Cut out wheels", "description": "separate wheel meshes at the measured circles; the body's hidden side is filled"},
                                   {"label": "Keep fused", "description": "body moves only (bob, tilt); wheels do not spin"}],
                       "recommended": "Cut out wheels", "why": "spinning wheels need separate rigid parts"})
        qs.append({"id": "steering", "header": "Steering", "blocking": False,
                   "question": "Should the front wheels steer in turning clips?",
                   "options": [{"label": "Front wheels steer"}, {"label": "No steering"}],
                   "recommended": "Front wheels steer", "why": "typical for cars; trucks/carts may differ"})
    if top["archetype"] == "rigid_parts" and top["subtype"] == "hinged":
        qs.append({"id": "hinge", "header": "Hinge", "blocking": True,
                   "question": "Where is the hinge of the moving flat part (lid/door)?",
                   "options": [{"label": "Back edge"}, {"label": "Left edge"}, {"label": "Right edge"}, {"label": "Slides (drawer)"}],
                   "recommended": "Back edge", "why": "the hinge cannot be seen in the geometry"})
    if top["archetype"] == "chain_flex" and top["subtype"] == "plant":
        qs.append({"id": "plant_method", "header": "Sway", "blocking": False,
                   "question": "How should the plant sway?",
                   "options": [{"label": "Bone chains", "description": "smooth bending of trunk and branches; a few bones per branch"},
                               {"label": "Shape keys", "description": "lighter for many copies; fixed wind pattern"}],
                   "recommended": "Bone chains", "why": f"{len(S['skeleton']['extremities'])} branches measured"})
    if top["archetype"] == "skinned" and S["deformation_hints"].get("short_limbs_round_body"):
        S["plan_notes"].append("short limbs on a round body: add half-rotation helpers at hips/shoulders and use refine "
                               "(deformation-prep/references/limb-junctions.md)")
    qs.append({"id": "clips", "header": "Clips", "blocking": True, "multiSelect": True,
               "question": "Which animations should be made?",
               "options": [{"label": c} for c in CLIPS.get((top["archetype"], top["subtype"]), ["idle"])][:4],
               "recommended": CLIPS.get((top["archetype"], top["subtype"]), ["idle"])[:2],
               "why": "suggested for the measured motion type; add a video/GIF for any clip you want imitated"})
    return qs


# ---------------------------------------------------------------------------------------------- entry
def _analyse(objs, scene, args):
    rng = np.random.default_rng(7)
    V, T, tri_obj = _gather(objs, scene)
    up = np.array({"Z": (0, 0, 1), "Y": (0, 1, 0)}[args.get("up_axis", "Z")], float)
    diag = float(np.linalg.norm(V.max(0) - V.min(0)))
    vox = diag / int(args.get("resolution", 120))
    area_est = 0.5 * np.linalg.norm(np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]]), axis=1).sum()
    n = int(np.clip(area_est / (vox * vox) * 8, 60000, 600000))
    P, pobj, area = _sample(V, T, tri_obj, n, rng)
    G = Grid(P, pobj, vox)
    hgt = P @ up
    ground = float(hgt.min())
    height = float(hgt.max() - ground)
    G.extent_up = height
    centre_height_ratio = float((P @ up).mean() - ground) / max(height, 1e-9)
    horiz = P - np.outer(hgt, up)
    _, w, v = _pca(horiz)
    fwd_axis = v[:, 0] - (v[:, 0] @ up) * up; fwd_axis /= np.linalg.norm(fwd_axis)
    lat_axis = np.cross(up, fwd_axis)
    span = lambda ax: float((P @ ax).max() - (P @ ax).min())
    S = {"voxel": round(vox, 5), "samples": n, "surface_area_m2": round(area, 5),
         "size": {"height": round(height, 4), "width_major": round(span(fwd_axis), 4), "width_minor": round(span(lat_axis), 4),
                  "diagonal": round(diag, 4)},
         "axes": {"up": _r(up), "major_horizontal": _r(fwd_axis), "minor_horizontal": _r(lat_axis)},
         "objects": [o.name for o in objs], "plan_notes": [], "centre_height_ratio": round(centre_height_ratio, 3)}
    # parts: shells of the same object (separate objects that touch stay separate parts)
    same_obj = (G.obj[G.nb.clip(0)] == G.obj[:, None])
    lab = G.components(mask_edge=same_obj)
    parts = []
    for l in np.unique(lab):
        vs = np.where(lab == l)[0]
        if len(vs) < 0.002 * G.n:
            continue
        pts = P[np.isin(G.P_inv, vs)]
        sh = _shape(pts)
        sh.update({"share": round(len(vs) / G.n, 3), "objects": sorted({objs[i].name for i in np.unique(G.obj[vs])}),
                   "bbox_min": _r(G.centre[vs].min(0)), "bbox_max": _r(G.centre[vs].max(0)),
                   "touches_ground": bool((G.centre[vs] @ up).min() - ground < 2 * vox), "_vs": vs})
        parts.append(sh)
    parts.sort(key=lambda p: -p["share"])
    # which parts touch which (adjacent voxels across parts): lid on box, wheel on axle/body
    pid = -np.ones(G.n, dtype=np.int64)
    for i, p in enumerate(parts):
        pid[p["_vs"]] = i
    a = np.repeat(pid, 26); b = pid[G.nb.clip(0)].ravel(); m = (G.nb.ravel() >= 0) & (a >= 0) & (b >= 0) & (a != b)
    touch = {tuple(sorted(x)) for x in np.c_[a[m], b[m]].tolist()}
    for i, p in enumerate(parts):
        p["touches_parts"] = sorted({j for x in touch for j in x if i in x and j != i})
    S["parts"] = parts
    # contacts
    cont, _ = _contacts(G, up, ground, height)
    S["contacts"] = cont
    # skeleton on the main part
    main = parts[0]
    members = np.zeros(G.n, bool); members[main["_vs"]] = True
    core = np.array(main["centre"])
    root = main["_vs"][np.argmin(np.linalg.norm(G.centre[main["_vs"]] - core, axis=1))]
    step = 2
    nodes, parent, children, dist = _reeb(G, members, root, step)
    min_len = max(3, int(0.04 * diag / (vox * step)))
    ext = _extremities(G, nodes, parent, children, min_len, step, up, ground)
    # keep protrusions only: a limb or branch leaves concave skin around it (inside the convex hull);
    # the corners of a box or the rim of a lid lie on the hull
    N, D = _hull_planes(G.centre[members], rng)
    kept = []
    for e, path_vs in zip(ext, _ext_voxels):
        depth = _hull_depth(G.centre[path_vs], N, D)
        e["concavity"] = round(float(np.percentile(depth, 90)) / max(e["radius_median"], vox), 2)
        e["thin"] = e["radius_median"] < 1.5 * vox
        if float(np.percentile(depth, 90)) > 1.5 * vox and e["concavity"] > 0.25:
            kept.append(e)
    S["skeleton_discarded"] = len(ext) - len(kept)
    ext = kept
    S["skeleton"] = {"root": _r(G.centre[root]), "nodes": len(nodes), "extremities": ext,
                     "junctions": int(sum(1 for k, ch in children.items() if len(ch) > 1))}
    # symmetry
    S["symmetry"] = {"across_minor": round(_symmetry(G, lat_axis, core), 3), "across_major": round(_symmetry(G, fwd_axis, core), 3)}
    # wheels: separate disks touching the ground, else fused side slabs
    wheels = [{"centre": p["centre"], "radius": p.get("radius"), "axis": p.get("axis"), "objects": p["objects"], "source": "separate_part"}
              for p in parts if p["class"] == "disk" and p["touches_ground"]]
    if len(wheels) < 3 and len(parts) <= 2 and len(cont) >= 3:
        wheels = _side_wheels(G, up, fwd_axis, lat_axis, ground, height, cont)
    S["wheels"] = wheels
    if wheels:
        for e in ext:
            tip = np.array(e["tip"])
            for wh in wheels:
                if np.linalg.norm(tip - np.array(wh["centre"])) < 1.6 * (wh["radius"] or 0):
                    e["is_wheel"] = True
                    e["touches_ground"] = False
    # forward guess
    fwd = {"value": "unknown", "confidence": 0.0, "basis": "no cue"}
    legs = [e for e in ext if e["touches_ground"] and e["direction"][2] < -0.3]
    others = [e for e in ext if e not in legs]
    sym_ok = S["symmetry"]["across_minor"] > S["symmetry"]["across_major"]
    others = [e for e in others if not e.get("thin") and not e.get("is_wheel")]
    tails_only = others and all(e["slenderness"] >= 1.5 for e in others)
    if legs and tails_only:
        t = max(others, key=lambda e: e["length"])
        st = float((np.array(t["tip"]) - core) @ fwd_axis)
        fwd = {"value": _axis_name(-np.sign(st) * fwd_axis), "confidence": 0.7 if sym_ok else 0.5,
               "basis": "opposite the slender extremity (tail); the head is not a separate protrusion"}
    elif legs and others:
        heads = [e for e in others if e["slenderness"] < 1.5] or others
        head = max(heads, key=lambda e: e["radius_median"])
        tails = [e for e in others if e["slenderness"] >= 1.5 and e is not head]
        sh = float((np.array(head["tip"]) - core) @ fwd_axis)
        opposite = any(float((np.array(t["tip"]) - core) @ fwd_axis) * sh < 0 for t in tails)
        fwd = {"value": _axis_name(np.sign(sh) * fwd_axis), "confidence": (0.85 if opposite else 0.65) if sym_ok else 0.5,
               "basis": "thickest non-leg extremity (head)" + (", slender one (tail) at the other end" if opposite else "")}
    elif wheels and len(wheels) >= 3:
        top_pts = P[hgt > ground + 0.7 * height]
        s = float((top_pts.mean(0) - core) @ fwd_axis) if len(top_pts) else 0.0
        fwd = {"value": _axis_name(-np.sign(s or 1) * fwd_axis), "confidence": 0.5,
               "basis": "longer horizontal axis; the cabin/high part usually sits toward the back — unreliable"}
    elif parts and parts[0]["class"] in ("sphere",) or (S["size"]["width_major"] - S["size"]["width_minor"]) < 0.05 * diag:
        fwd = {"value": "none", "confidence": 1.0, "basis": "rotationally symmetric in plan view"}
    S["forward"] = fwd
    # deformation hints
    if legs and len(legs) >= 2:
        leg_len = float(np.median([e["length"] for e in legs]))
        S["deformation_hints"] = {"leg_length_over_height": round(leg_len / height, 3),
                                  "short_limbs_round_body": bool(leg_len / height < 0.45 and S["size"]["width_minor"] / height > 0.45),
                                  "leg_slenderness": round(float(np.median([e["slenderness"] for e in legs])), 2)}
    else:
        S["deformation_hints"] = {}
    S["archetypes"] = _archetypes(S)
    S["questions"] = _questions(S)
    S["suggested_clips"] = CLIPS.get((S["archetypes"][0]["archetype"], S["archetypes"][0]["subtype"]), ["idle"])
    for p in parts:
        p.pop("_vs", None)
    for c in cont:
        c.pop("_idx", None)
    return S


def _axis_name(v):
    v = np.asarray(v, float)
    i = int(np.argmax(np.abs(v)))
    return ("" if v[i] > 0 else "-") + "XYZ"[i] + ("" if abs(v[i]) > 0.95 else f"~({v[0]:.2f},{v[1]:.2f},{v[2]:.2f})")


def run(args: dict) -> dict:
    scratch = None
    try:
        if args.get("source"):
            scratch = bpy.data.scenes.new("TMP_structure")
            before = set(bpy.data.objects)
            before_data = {k: set(getattr(bpy.data, k)) for k in ("meshes", "materials", "images", "textures")}
            with bpy.context.temp_override(scene=scratch, view_layer=scratch.view_layers[0]):
                bpy.ops.import_scene.gltf(filepath=args["source"]) if args["source"].lower().endswith((".glb", ".gltf")) else \
                    bpy.ops.wm.obj_import(filepath=args["source"])
            objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
            scene = scratch
        else:
            scene = bpy.data.scenes.get(args.get("scene", "")) or bpy.context.scene
            names = args.get("objects")
            objs = [bpy.data.objects[n] for n in names] if names else [o for o in scene.objects if o.type == "MESH" and o.visible_get()]
        if not objs:
            return C.result_error("no mesh objects to analyse")
        S = _analyse(objs, scene, args)
        if args.get("project_dir"):
            C.write_json(os.path.join(args["project_dir"], "reports", "structure.json"), S)
        return C.result_ok(structure=S)
    finally:
        if scratch is not None:
            for o in list(scratch.objects):
                data = o.data
                bpy.data.objects.remove(o, do_unlink=True)
                if isinstance(data, bpy.types.Mesh) and data.users == 0:
                    bpy.data.meshes.remove(data)
            bpy.data.scenes.remove(scratch)
            for k, prev in before_data.items():
                coll = getattr(bpy.data, k)
                for d in [d for d in coll if d not in prev and d.users == 0]:
                    coll.remove(d)
