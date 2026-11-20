"""Fit a skeleton template to a mesh (deformation-prep steps 2 and 6). Produces a PROPOSAL the user confirms.

args:
    mesh        (str, required)  deform mesh (or source) to fit
    template    (str, required)  rigify metarig name: human | basic_human | basic_quadruped | cat | wolf | horse | shark,
                                 or "bird" (production/rigs/bird_metarig.py)
    forward     (str, "-Y")      direction the model faces (Rigify metarigs face -Y)
    fit         (str)            "feet"   (default for cat | wolf | horse | basic_quadruped): scale length and width
                                          from the four paw contacts, height from the bbox — handles stylised
                                          proportions (chibi, cartoon) where a uniform fit fails
                                 "axes"   scale each axis to the mesh bbox
                                 "height" uniform scale from the bbox height (default for other templates)
    snap        (bool, True)     move bone heads to cross-section centres of the mesh
    prune       (list[str])      fnmatch patterns of metarig bones to delete WITH their descendants before
                                 generating, e.g. ["face", "f_palm.*", "r_palm.*"] (web budgets, stylised assets)
    trace       (list[dict])     run bone chains through the middle of a tube of the mesh (tails, necks, ears):
                                 [{"bones": ["tail.001", ...], "base": [x,y,z], "tip": [x,y,z]}]  (world, metres;
                                 base defaults to the first bone head). Walks from tip to base along the
                                 cross-section centres, then spaces the bones evenly by arc length. A chain whose
                                 first head touches its parent keeps that head; its first bone spans head → base.
    overrides   (dict)           {bone: {"head": [x,y,z], "tail": [x,y,z], "parent": str, "connect": bool,
                                 "rigify_type": str}} world positions; a missing bone is created (needs head,
                                 tail, parent). Applied last: explicit placement wins. Moving a head keeps shared
                                 joints shared: the parent's tail and children starting at the same point follow.
    generate    (bool, False)    run Rigify generate (after the user approved joint placement)
    flatten_bbones (bool, True)  after generate, set deform bones to 1 B-Bone segment (glTF cannot carry B-Bones)
    paw_auto_track (bool, False) keep Rigify's paw auto-tracking (DAMPED_TRACK on MCH-*_track); off by default
                                 because it moves the paw away from the bind pose in IK
    Rigify is always generated facing -Y (its paw helpers use world axes) and the result is turned to `forward`.
    metarig     (str, optional)  existing metarig name (skip creation and fit; prune/snap/trace/overrides still apply)

    fix_rolls   (bool, True)     re-align bone rolls to the template's X axes after fitting (see restore_rolls)

Order: create → fit → prune → snap → trace → overrides → roll fix → (generate).

Rigify assumes 1 unit = 1 m: normalise the mesh scale first (asset real_size_m).
"""
import importlib.util
import math
import os
import runpy
import sys

import addon_utils
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
FORWARD_ROT = {"-Y": 0.0, "+Y": math.pi, "+X": math.pi / 2, "-X": -math.pi / 2}


def ensure_rigify() -> str:
    for mod in addon_utils.modules():
        name = mod.__name__
        if name == "rigify" or name.endswith(".rigify"):
            if not addon_utils.check(name)[1]:
                addon_utils.enable(name, default_set=True, persistent=True)
            return name
    raise RuntimeError("Rigify add-on not found in this Blender")


def add_metarig(template: str):
    before = set(bpy.data.objects)
    if template == "bird":
        here = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
        script = os.path.normpath(os.path.join(here, "..", "..", "rigs", "bird_metarig.py"))
        ns = runpy.run_path(script)
        return bpy.data.objects[ns["build"]()["metarig"]]
    op_name = f"armature_{template}_metarig_add"
    op = getattr(bpy.ops.object, op_name, None)
    if op is None or not hasattr(op, "poll"):
        available = [n for n in dir(bpy.ops.object) if n.endswith("_metarig_add")]
        raise RuntimeError(f"metarig operator {op_name} not available; available: {available}")
    op()
    new = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
    return new[0]


def fit_bbox(rig, mesh, forward):
    rig.rotation_euler = (0, 0, FORWARD_ROT.get(forward, 0.0))
    bpy.context.view_layer.update()
    rmn, rmx = C.world_bbox([rig])
    mmn, mmx = C.world_bbox([mesh])
    s = (mmx[2] - mmn[2]) / max(rmx[2] - rmn[2], 1e-6)
    rig.scale = (s, s, s)
    bpy.context.view_layer.update()
    rmn, rmx = C.world_bbox([rig])
    rig.location += Vector(((mmn[0] + mmx[0]) / 2 - (rmn[0] + rmx[0]) / 2,
                            (mmn[1] + mmx[1]) / 2 - (rmn[1] + rmx[1]) / 2,
                            mmn[2] - rmn[2]))
    bpy.context.view_layer.update()
    return s


def _move_head(eb, new_head):
    """Move an edit bone's head and keep shared joints shared: the parent's tail (when they touched) and
    sibling-style children whose heads started at the same point (Rigify tails, pelvis bones)."""
    old = eb.head.copy()
    if eb.parent is not None and not eb.use_connect and (old - eb.parent.tail).length < 1e-6:
        eb.parent.tail = new_head.copy()
    for c in eb.children:
        if not c.use_connect and (c.head - old).length < 1e-6:
            c.head = new_head.copy()
    eb.head = new_head


def snap_heads(rig, mesh):
    """Move each bone head to the centroid of the mesh cross-section through it (keeps axial position)."""
    co = C.evaluated_vertex_positions(mesh)
    mn, mx = C.world_bbox([mesh])
    diag = float(np.linalg.norm(np.array(mx) - np.array(mn)))
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    mw = rig.matrix_world
    inv = mw.inverted()
    moved = {}
    for eb in rig.data.edit_bones:
        if eb.parent is not None and not eb.use_connect and (eb.head - eb.parent.head).length < 1e-6:
            continue  # starts where its parent starts (Rigify tails, pelvis): follows the parent, see _move_head
        head = np.array(mw @ eb.head)
        d = np.array((mw @ eb.tail) - (mw @ eb.head))
        if np.linalg.norm(d) < 1e-9:
            continue
        d /= np.linalg.norm(d)
        rel = co - head
        t = rel @ d
        slab = (np.abs(t) < 0.01 * diag) & (np.linalg.norm(rel, axis=1) < 0.15 * diag)
        if slab.sum() < 6:
            continue
        pts = co[slab]
        radial = np.linalg.norm((pts - head) - np.outer((pts - head) @ d, d), axis=1)
        pts = pts[radial < radial.min() * 3 + 0.01 * diag]
        c = pts.mean(0)
        c = c - ((c - head) @ d) * d  # keep axial position
        if np.linalg.norm(c - head) > 0.08 * diag:
            continue  # implausible jump: leave for manual placement
        _move_head(eb, inv @ Vector(c))  # shared joints stay shared (Rigify chains refuse disjoint bones)
        moved[eb.name] = round(float(np.linalg.norm(c - head)), 5)
    bpy.ops.object.mode_set(mode="OBJECT")
    return moved


QUAD_TEMPLATES = {"cat", "wolf", "horse", "basic_quadruped"}
AXIS = {"-Y": (0.0, -1.0, 0.0), "+Y": (0.0, 1.0, 0.0), "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0)}
LIMB_TYPES = ("limbs.front_paw", "limbs.rear_paw", "limbs.paw", "limbs.leg", "limbs.arm")


def _apply(rig, rotation=False, scale=False, location=False):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale)


def _rig_feet(rig, fwd):
    """Lowest world point of each limb chain → {("front"|"rear", "L"|"R"): Vector}."""
    lows = []
    for b in rig.data.bones:
        if getattr(rig.pose.bones[b.name], "rigify_type", "") not in LIMB_TYPES:
            continue
        side = "L" if b.name.endswith(".L") else "R" if b.name.endswith(".R") else None
        if side is None:
            continue
        chain = [b] + [c for c in b.children_recursive
                       if not getattr(rig.pose.bones[c.name], "rigify_type", "")]
        pts = [rig.matrix_world @ c.tail_local for c in chain] + [rig.matrix_world @ b.head_local]
        lows.append((side, min(pts, key=lambda v: v.z)))
    if len(lows) != 4:
        return None
    order = sorted(lows, key=lambda sl: sl[1].dot(fwd), reverse=True)
    return {("front" if i < 2 else "rear", side): v.copy() for i, (side, v) in enumerate(order)}


def _mesh_feet(co, fwd, lat, frac=0.04):
    z = co[:, 2]
    low = co[z < z.min() + frac * (z.max() - z.min())]
    f, l = low @ np.array(fwd), low @ np.array(lat)
    fm, lm = (f.min() + f.max()) / 2, (l.min() + l.max()) / 2
    feet = {}
    for fr, fsel in (("front", f >= fm), ("rear", f < fm)):
        for side, ssel in (("L", l >= lm), ("R", l < lm)):
            sel = fsel & ssel
            if sel.sum() < 3:
                return None
            feet[(fr, side)] = Vector(low[sel].mean(0))
    return feet


def _span(feet, axis, a_keys, b_keys):
    a = sum((feet[k] for k in a_keys), Vector()) / len(a_keys)
    b = sum((feet[k] for k in b_keys), Vector()) / len(b_keys)
    return (a - b).dot(axis)


def fit_feet(rig, mesh, forward):
    """Length/width from paw contacts, height from bbox. Falls back to fit_bbox when paws are not found."""
    rig.rotation_euler = (0, 0, FORWARD_ROT.get(forward, 0.0))
    bpy.context.view_layer.update()
    _apply(rig, rotation=True)
    fwd = Vector(AXIS.get(forward, AXIS["-Y"]))
    lat = Vector((0, 0, 1)).cross(fwd)
    co = C.evaluated_vertex_positions(mesh)
    rf, mf = _rig_feet(rig, fwd), _mesh_feet(co, fwd, lat)
    if not rf or not mf:
        return {"mode": "height (paws not found)", "scale": fit_bbox(rig, mesh, "-Y")}
    F, R = [("front", "L"), ("front", "R")], [("rear", "L"), ("rear", "R")]
    Ls, Rs = [("front", "L"), ("rear", "L")], [("front", "R"), ("rear", "R")]
    sf = _span(mf, fwd, F, R) / max(_span(rf, fwd, F, R), 1e-6)
    sl = _span(mf, lat, Ls, Rs) / max(_span(rf, lat, Ls, Rs), 1e-6)
    # vertical: torso centre height above the paws, measured midway between front and rear paws
    # (bbox height is unreliable: raised tails, big heads and ears inflate it on stylised models)
    mid = sum((mf[k].dot(fwd) for k in mf), 0.0) / 4
    span_len = _span(mf, fwd, F, R)
    slab = co[np.abs(co @ np.array(fwd) - mid) < max(0.1 * span_len, 1e-4)]
    paw_z_m = sum(v.z for v in mf.values()) / 4
    rmid = sum((rf[k].dot(fwd) for k in rf), 0.0) / 4
    spine_z = _spine_z_at(rig, fwd, rmid)
    paw_z_r = sum(v.z for v in rf.values()) / 4
    if len(slab) >= 10 and spine_z is not None and spine_z - paw_z_r > 1e-6:
        torso_z = (slab[:, 2].min() + slab[:, 2].max()) / 2
        sv = (torso_z - paw_z_m) / (spine_z - paw_z_r)
        v_mode = "torso"
    else:
        rmn, rmx = C.world_bbox([rig])
        mmn, mmx = C.world_bbox([mesh])
        sv = (mmx[2] - mmn[2]) / max(rmx[2] - rmn[2], 1e-6)
        v_mode = "bbox"
    rig.scale = tuple(abs(fwd[i]) * sf + abs(lat[i]) * sl + (sv if i == 2 else 0.0) for i in range(3))
    bpy.context.view_layer.update()
    rf = _rig_feet(rig, fwd)
    rc = sum(rf.values(), Vector()) / 4
    mc = sum(mf.values(), Vector()) / 4
    rig.location += mc - rc  # paw centroids coincide (x, y and z)
    bpy.context.view_layer.update()
    return {"mode": "feet", "vertical": v_mode, "scale_forward": round(sf, 4), "scale_lateral": round(sl, 4),
            "scale_up": round(sv, 4), "mesh_paws": {f"{k[0]}.{k[1]}": [round(x, 4) for x in v] for k, v in mf.items()}}


def _spine_z_at(rig, fwd, f_coord):
    """Height of the torso spine chain where it crosses the forward coordinate f_coord."""
    root = next((b for b in rig.data.bones
                 if getattr(rig.pose.bones[b.name], "rigify_type", "") == "spines.basic_spine"), None)
    if root is None:
        return None
    chain, b = [root], root
    while True:
        nxt = [c for c in b.children if c.use_connect]
        if not nxt:
            break
        b = nxt[0]
        chain.append(b)
    pts = [rig.matrix_world @ chain[0].head_local] + [rig.matrix_world @ c.tail_local for c in chain]
    for a, c in zip(pts, pts[1:]):
        fa, fc = a.dot(fwd), c.dot(fwd)
        if min(fa, fc) <= f_coord <= max(fa, fc) and abs(fc - fa) > 1e-9:
            t = (f_coord - fa) / (fc - fa)
            return a.z + t * (c.z - a.z)
    return None


def fit_axes(rig, mesh, forward):
    rig.rotation_euler = (0, 0, FORWARD_ROT.get(forward, 0.0))
    bpy.context.view_layer.update()
    _apply(rig, rotation=True)
    rmn, rmx = C.world_bbox([rig])
    mmn, mmx = C.world_bbox([mesh])
    s = [(mmx[i] - mmn[i]) / max(rmx[i] - rmn[i], 1e-6) for i in range(3)]
    rig.scale = s
    bpy.context.view_layer.update()
    rmn, rmx = C.world_bbox([rig])
    rig.location += Vector(((mmn[0] + mmx[0] - rmn[0] - rmx[0]) / 2, (mmn[1] + mmx[1] - rmn[1] - rmx[1]) / 2,
                            mmn[2] - rmn[2]))
    bpy.context.view_layer.update()
    return {"mode": "axes", "scale": [round(x, 4) for x in s]}


def prune_bones(rig, patterns):
    """Delete metarig bones matching fnmatch patterns, with all their descendants."""
    import fnmatch
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    doomed = set()
    for b in eb:
        if any(fnmatch.fnmatchcase(b.name, p) for p in patterns):
            doomed.add(b.name)
            doomed.update(c.name for c in b.children_recursive)
    for name in doomed:
        eb.remove(eb[name])
    bpy.ops.object.mode_set(mode="OBJECT")
    return sorted(doomed)


def trace_points(co, base, tip, step):
    """Medial polyline from tip to base through cross-section centres; returned base → tip."""
    base, tip = np.asarray(base, float), np.asarray(tip, float)
    p = tip.copy()
    d = base - tip
    d /= np.linalg.norm(d)
    pts, r_est = [p.copy()], None
    axis = tip - base
    max_steps = int(3 * np.linalg.norm(axis) / step) + 10  # a tube is at most ~3x its chord
    for _ in range(max_steps):
        q = p + d * step
        rel = co - q
        t = rel @ d
        radial = np.linalg.norm(rel - np.outer(t, d), axis=1)
        lim = r_est * 2.5 if r_est else step * 4
        sel = (np.abs(t) < step * 0.5) & (radial < lim)
        if sel.sum() >= 4:
            c = co[sel].mean(0)
            c = c - ((c - q) @ d) * d
            r = float(np.median(radial[sel]))
            r_est = r if r_est is None else 0.7 * r_est + 0.3 * r
        else:
            c = q
        to_b = base - c
        dist = float(np.linalg.norm(to_b))
        if dist < max(2 * step, r_est or 0.0) or np.dot(c - base, axis) <= 0:
            break  # reached (or passed) the base plane: stop before wandering into the body
        nd = c - p
        nd /= max(np.linalg.norm(nd), 1e-12)
        d = 0.6 * nd + 0.4 * to_b / dist
        d /= np.linalg.norm(d)
        p = c
        pts.append(p.copy())
    pts.append(base.copy())
    return np.array(pts[::-1])


def resample(pts, n):
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    targets = np.linspace(0.0, s[-1], n + 1)
    return np.stack([np.interp(targets, s, pts[:, i]) for i in range(3)], 1), float(s[-1])


def trace_chains(rig, mesh, specs):
    co = C.evaluated_vertex_positions(mesh)
    mn, mx = C.world_bbox([mesh])
    diag = float(np.linalg.norm(np.array(mx) - np.array(mn)))
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    mw, inv = rig.matrix_world, rig.matrix_world.inverted()
    out = {}
    for spec in specs:
        names = [n for n in spec["bones"] if n in eb]
        if not names or "tip" not in spec:
            out[",".join(spec.get("bones", []))] = "skipped (bones or tip missing)"
            continue
        b0 = eb[names[0]]
        base = spec.get("base") or list(mw @ b0.head)
        poly = trace_points(co, base, spec["tip"], float(spec.get("step", 0.01 * diag)))
        # A chain attached to its parent (Rigify tails/necks with connect_chain) keeps its first head: that bone
        # runs inside the body from the attachment to `base`, the others follow the traced tube.
        anchored = b0.parent is not None and min((b0.head - b0.parent.head).length,
                                                 (b0.head - b0.parent.tail).length) < 1e-6
        anchor = np.array(mw @ b0.head)
        if anchored and len(names) > 1 and np.linalg.norm(anchor - np.asarray(base, float)) > 1e-4:
            rest, length = resample(poly, len(names) - 1)
            pts = np.vstack([anchor[None, :], rest])
            length += float(np.linalg.norm(rest[0] - anchor))
        else:
            anchored = False
            pts, length = resample(poly, len(names))
        for i, n in enumerate(names):
            b = eb[n]
            if i > 0:
                b.use_connect = True
            elif not anchored:
                b.head = inv @ Vector(pts[0])
            b.tail = inv @ Vector(pts[i + 1])
        out[names[0]] = {"bones": len(names), "length_m": round(length, 4), "samples": len(poly),
                         "anchored_to_parent": anchored}
    bpy.ops.object.mode_set(mode="OBJECT")
    return out


def apply_overrides(rig, overrides):
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    inv = rig.matrix_world.inverted()
    done, types = [], {}
    for name, o in overrides.items():
        b = eb.get(name)
        if b is None:
            if not {"head", "tail"} <= set(o):
                continue
            b = eb.new(name)
        if "parent" in o:
            b.parent = eb.get(o["parent"]) if o["parent"] else None
        if "head" in o:
            # keep adjacency: a head that touched its parent's tail still touches it (Rigify chains such as
            # spines.super_head refuse "disjoint" bones)
            _move_head(b, inv @ Vector(o["head"]))
        if "tail" in o:
            b.tail = inv @ Vector(o["tail"])
        if "connect" in o:
            b.use_connect = bool(o["connect"])
        if "rigify_type" in o:
            types[name] = o["rigify_type"]
        done.append(name)
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, t in types.items():
        rig.pose.bones[name].rigify_type = t
    return done


def template_x_axes(rig, forward):
    """Bone X axes of the untouched template, turned to face `forward` (rotation only: no scale distortion)."""
    R = Matrix.Rotation(FORWARD_ROT.get(forward, 0.0), 3, "Z")
    return {b.name: list((R @ b.matrix_local.to_3x3().col[0]).normalized()) for b in rig.data.bones}


def restore_rolls(rig, x_ref):
    """Re-align every bone's roll so its X axis matches the template's (the bend axis of Rigify limbs and the
    lateral axis of spine/neck/tail). Non-uniform fitting, snapping, tracing and overrides change directions
    while keeping roll angles, which twists controls (a 'nod' becomes a diagonal tilt)."""
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    inv3 = rig.matrix_world.to_3x3().inverted()
    fixed = 0
    for eb in rig.data.edit_bones:
        ref = x_ref.get(eb.name)
        if ref is None:
            continue
        y = (eb.tail - eb.head).normalized()
        x = inv3 @ Vector(ref)
        x = x - y * x.dot(y)
        if x.length < 1e-4:
            continue  # bone now points along its old X axis: keep the roll
        eb.align_roll(x.normalized().cross(y))  # align_roll aims the bone's Z axis
        fixed += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    return fixed


def run(args: dict) -> dict:
    mesh = bpy.data.objects.get(args.get("mesh", ""))
    if mesh is None:
        return C.result_error("mesh required")
    rig_mod = ensure_rigify()
    if args.get("metarig"):
        rig = bpy.data.objects[args["metarig"]]
        scale = None
    else:
        rig = add_metarig(args["template"])
        rig.name = f"metarig_{mesh.name}"  # Rigify names the generated rig "rig_<mesh>"
        forward = args.get("forward", "-Y")
        rig["u3d_x_ref"] = template_x_axes(rig, forward)  # kept on the metarig for later runs
        rig["u3d_forward"] = forward
        fit = args.get("fit") or ("feet" if args.get("template") in QUAD_TEMPLATES else "height")
        if fit == "feet":
            scale = fit_feet(rig, mesh, forward)
        elif fit == "axes":
            scale = fit_axes(rig, mesh, forward)
        else:
            scale = {"mode": "height", "scale": fit_bbox(rig, mesh, forward)}
        # Apply location too: Rigify builds the rig at the world origin from the metarig's LOCAL bone
        # positions, so a metarig with an unapplied offset produces a rig displaced from the mesh.
        _apply(rig, rotation=True, scale=True, location=True)
    pruned = prune_bones(rig, args["prune"]) if args.get("prune") else []
    moved = snap_heads(rig, mesh) if args.get("snap", True) else {}
    traced = trace_chains(rig, mesh, args["trace"]) if args.get("trace") else {}
    overridden = apply_overrides(rig, args["overrides"]) if args.get("overrides") else []
    x_ref = {k: list(v) for k, v in rig.get("u3d_x_ref", {}).items()}
    rolls = restore_rolls(rig, x_ref) if (x_ref and args.get("fix_rolls", True)) else 0
    out = {"metarig": rig.name, "rigify_module": rig_mod, "fit": scale, "pruned": len(pruned), "snapped": moved,
           "traced": traced, "overridden": overridden, "rolls_restored": rolls, "bones": len(rig.data.bones),
           "next": "screenshot front/side with X-ray; user confirms joints"}
    if args.get("generate"):
        if rig.matrix_world != Matrix.Identity(4):
            _apply(rig, rotation=True, scale=True, location=True)  # see note above: Rigify ignores the object transform
            out["applied_metarig_transform"] = True
        # Rigify builds some helper bones along WORLD axes assuming the character faces -Y (paw heel/track
        # bones of limbs.front_paw / rear_paw). Generate in that orientation and turn the result afterwards,
        # otherwise a +X-facing quadruped gets its paw IK targets pulled sideways (both paws skew to one side).
        forward = args.get("forward") or rig.get("u3d_forward", "-Y")
        turn = FORWARD_ROT.get(forward, 0.0)
        if abs(turn) > 1e-9:
            rig.rotation_euler = (0.0, 0.0, -turn)
            bpy.context.view_layer.update()
            _apply(rig, rotation=True)
        bpy.context.view_layer.objects.active = rig
        before = set(bpy.data.objects)
        try:
            bpy.ops.pose.rigify_generate()
        finally:
            if abs(turn) > 1e-9:
                rig.rotation_euler = (0.0, 0.0, turn)
                bpy.context.view_layer.update()
                _apply(rig, rotation=True)
        gen = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
        out["rig"] = gen[0].name if gen else rig.data.get("rigify_target_rig", None)
        if gen and abs(turn) > 1e-9:
            gen[0].rotation_euler = (0.0, 0.0, turn)
            bpy.context.view_layer.update()
            _apply(gen[0], rotation=True)
            out["generated_in_rigify_orientation"] = forward
        if gen:
            out["deform_bones"] = sum(1 for b in gen[0].data.bones if b.use_deform)
            if not args.get("paw_auto_track", False):
                # Rigify paws (limbs.front_paw) turn the heel toward the leg with a DAMPED_TRACK (influence 0.8)
                # that is not neutral at rest: in IK the paw rest pose is off by ~4 mm at the paw and 15 mm at
                # the forearm on the cat. Off by default so IK, FK and the bind pose agree.
                n = 0
                for pb in gen[0].pose.bones:
                    if pb.name.startswith("MCH-") and "_track" in pb.name:
                        for c in pb.constraints:
                            if c.type == "DAMPED_TRACK" and c.influence > 0:
                                c.influence = 0.0
                                n += 1
                out["paw_track_disabled"] = n
            if args.get("flatten_bbones", True):
                # glTF/three.js have no B-Bones: Rigify's segmented DEF bones (8-10 segments) make Blender deform
                # differently from the exported file (15 mm on a 25 cm cat). Flatten so Blender shows what ships.
                n = 0
                for b in gen[0].data.bones:
                    if b.use_deform and b.bbone_segments > 1:
                        b.bbone_segments = 1
                        n += 1
                out["bbones_flattened"] = n
    return C.result_ok(**out)
