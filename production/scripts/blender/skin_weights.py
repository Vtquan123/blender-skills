"""Skin weights (deformation-prep step 7, gate G4b).

mode "auto":  parent deform mesh to the generated rig with automatic weights (deform bones only),
              attach rigid parts to single bones, limit influences, normalize, clean.
mode "check": measure weights only (no changes).

args:
    mode            (str, "check")   auto | check
    mesh            (str, required)  skinned (deform) mesh
    armature        (str, required)  generated rig (deform bones)
    rigid_parts     (dict)           {"object_name": "bone_name"} separate rigid objects, parented to one bone
    rigid_groups    (dict)           {"vertex_group_name": "bone_name"} vertex sets of the mesh weighted 1.0 to one bone
    max_influences  (int, 4)
    clean_threshold (float, 0.01)
    smooth_iterations (int, 0)       optional weight smoothing passes (all groups)
    transfers       (list[dict])     move weight from limb bones to a body bone on one side of a plane, e.g. the
                                     chest skin of a chubby animal that auto weights gave to the upper arm:
                                     [{"from": ["DEF-upper_arm.L", "DEF-upper_arm.L.001"], "to": "DEF-spine.003",
                                       "point": [0, 0, -0.072], "normal": [0, 0, 1], "falloff": 0.02}]
                                     (world metres; full transfer at `falloff` beyond the plane, smoothstep between).
                                     Region of several planes: "planes": [{"point", "normal", "falloff"}, ...];
                                     "to" may be a list (nearest bone wins), e.g. belly skin between front and
                                     hind legs → ["DEF-spine.001", "DEF-spine.002", "DEF-spine.003"]
    project_dir     (str, optional)  write reports/gate-G4b.json
"""
import importlib.util
import os
import sys

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


def _activate(*objs):
    for o in bpy.context.view_layer.objects:
        if o is not None:  # stale entries right after bpy.data.objects.remove
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[-1]


def apply_transfers(mesh, transfers, arm=None):
    """Move weight from `from` bones to body bone(s) inside a region bounded by planes.

    Each transfer: {"from": [...], "to": bone | [bones], "planes": [{"point", "normal", "falloff"}]}
    (or a single "point"/"normal"/"falloff"). A vertex is inside when it is on the normal side of every plane;
    the amount moved is the product of smoothsteps over each plane's falloff, so the region has soft edges.
    With a list in "to", each vertex goes to the nearest of those bones (needs the armature)."""
    from mathutils import Vector
    from mathutils.geometry import intersect_point_line
    mw = mesh.matrix_world
    report = []
    for t in transfers or []:
        planes = t.get("planes") or [{"point": t["point"], "normal": t.get("normal", (0, 0, 1)),
                                      "falloff": t.get("falloff", 0.02)}]
        planes = [(Vector(pl["point"]), Vector(pl.get("normal", (0, 0, 1))).normalized(),
                   max(float(pl.get("falloff", 0.02)), 1e-6)) for pl in planes]
        targets = t["to"] if isinstance(t["to"], (list, tuple)) else [t["to"]]
        segs = []
        if len(targets) > 1:
            if arm is None:
                raise ValueError("transfer to several bones needs the armature")
            amw = arm.matrix_world
            segs = [(n, amw @ arm.data.bones[n].head_local, amw @ arm.data.bones[n].tail_local) for n in targets]
        dst = {n: (mesh.vertex_groups.get(n) or mesh.vertex_groups.new(name=n)) for n in targets}
        src = {g.index: g for g in (mesh.vertex_groups.get(n) for n in t["from"]) if g is not None}
        moved = 0
        for v in mesh.data.vertices:
            p = mw @ v.co
            k = 1.0
            for P, N, fall in planes:
                d = (p - P).dot(N)
                if d <= 0:
                    k = 0.0
                    break
                x = min(d / fall, 1.0)
                k *= x * x * (3 - 2 * x)
            if k <= 0:
                continue
            take = 0.0
            for ge in v.groups:
                g = src.get(ge.group)
                if g is not None and ge.weight > 0:
                    w = ge.weight * k
                    g.add([v.index], ge.weight - w, "REPLACE")
                    take += w
            if take <= 0:
                continue
            if segs:
                def dist(seg):
                    q, f = intersect_point_line(p, seg[1], seg[2])
                    f = min(max(f, 0.0), 1.0)
                    return (p - (seg[1] + (seg[2] - seg[1]) * f)).length
                name = min(segs, key=dist)[0]
            else:
                name = targets[0]
            g = dst[name]
            cur = next((ge.weight for ge in v.groups if ge.group == g.index), 0.0)
            g.add([v.index], cur + take, "REPLACE")
            moved += 1
        report.append({"to": targets, "verts": moved})
    return report


def _side(name):
    for suf, sgn in ((".L", 1.0), (".R", -1.0), ("_L", 1.0), ("_R", -1.0)):
        if name.endswith(suf) or (suf + ".") in name:
            return sgn
    return 0.0


def refine_limbs(mesh, arm, opts):
    """Clean automatic weights where limbs meet a round body (belly, groin, armpit).

    Bone heat on chubby characters leaks: lower-leg bones weigh on the belly, the left leg weighs on the right
    inner thigh, the thigh drags the flank. Under a walk those vertices fold or flip. Steps (all optional):
      side split   — a .L limb bone loses its weight on vertices beyond `side_margin` on the right side (and v.v.)
      capsules     — each limb bone keeps weight only within `capsule_scale` × its core radius (95th percentile
                     distance of its ≥0.7-weight vertices to the bone segment), fading over `capsule_falloff`
      junction     — Laplacian smoothing of the weights only on vertices that mix limb and body bones (plus
                     `junction_rings` rings around them), `junction_iterations` × `junction_factor`
    Removed weight goes to the vertex's remaining bones; a vertex left with nothing goes to the nearest body bone.
    opts: {"limb_prefixes": ["DEF-upper_arm", "DEF-forearm", "DEF-hand", "DEF-thigh", "DEF-shin", "DEF-foot"],
           "side_axis": [0, 1, 0] (world, toward .L), "side_margin": 0.006, "capsule_scale": 1.25,
           "capsule_falloff": 0.008, "junction_iterations": 0, "junction_factor": 0.5, "junction_rings": 2,
           "helpers": {"DEF-thigh.L": "DEF-thigh_half.L", ...} or true (read from helper_bones.py), "helper_upper_share": 0..1}
    helpers      — junction vertices re-mapped body → half-rotation helper → limb (see helper_bones.py);
                   helper_upper_share moves that share of the upper segment's own weight (thigh, upper arm) to the
                   helper too
    Returns metrics (weight moved per step).
    """
    import numpy as np
    me = mesh.data
    nv = len(me.vertices)
    deform = [b.name for b in arm.data.bones if b.use_deform]
    groups = [mesh.vertex_groups.get(n) for n in deform]
    names = [n for n, g in zip(deform, groups) if g is not None]
    col = {mesh.vertex_groups[n].index: i for i, n in enumerate(names)}
    W = np.zeros((nv, len(names)))
    for v in me.vertices:
        for ge in v.groups:
            j = col.get(ge.group)
            if j is not None:
                W[v.index, j] = ge.weight
    co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    mw = np.array(mesh.matrix_world); P = co @ mw[:3, :3].T + mw[:3, 3]
    amw = arm.matrix_world
    seg = {n: (np.array(amw @ arm.data.bones[n].head_local), np.array(amw @ arm.data.bones[n].tail_local)) for n in names}
    prefixes = tuple(opts.get("limb_prefixes", ["DEF-upper_arm", "DEF-forearm", "DEF-hand", "DEF-thigh", "DEF-shin", "DEF-foot"]))
    limb_set = {n for n in names if n.startswith(prefixes)}
    # everything below a limb bone is limb too (toes, paws, digits), whatever its name — a toe counted as
    # body would be re-mapped to the hip helper and the paw would swing with the hip
    for n in list(limb_set):
        limb_set |= {c.name for c in arm.data.bones[n].children_recursive if c.use_deform}
    for hn in (arm.get("u3d_helpers") or {}).values():
        limb_set.add(hn)
    limb = np.array([n in limb_set for n in names])
    body = ~limb
    total0 = W.sum(1, keepdims=True)
    moved = {}

    def seg_dist(n):
        a, b = seg[n]; ab = b - a
        t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)

    def smoothstep(x):
        x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)

    def side_split():
        ax = np.array(opts.get("side_axis", (0, 1, 0)), float); ax /= np.linalg.norm(ax)
        m = float(opts.get("side_margin", 0.006)); fall = max(float(opts.get("side_falloff", 0.006)), 1e-6)
        s = P @ ax - float(np.median(P @ ax))
        out = 0.0
        for j, n in enumerate(names):
            sg = _side(n)
            if not limb[j] or sg == 0:
                continue
            k = smoothstep((-sg * s - m) / fall)          # 0 on own side, 1 well past the midline
            out += float((W[:, j] * k).sum()); W[:, j] *= 1 - k
        return out

    def capsules():
        sc = float(opts.get("capsule_scale", 1.25)); fall = max(float(opts.get("capsule_falloff", 0.008)), 1e-6)
        out = 0.0
        for j, n in enumerate(names):
            if not limb[j]:
                continue
            dist = seg_dist(n)
            core = W[:, j] >= 0.7
            if core.sum() < 8:
                continue
            r = float(np.percentile(dist[core], 95)) * sc
            k = smoothstep((dist - r) / fall)
            out += float((W[:, j] * k).sum()); W[:, j] *= 1 - k
        return out

    def renorm():
        s = W.sum(1)
        empty = s < 1e-6
        if empty.any():
            bj = np.where(body)[0]
            dists = np.stack([seg_dist(names[j])[empty] for j in bj], 1)
            W[np.where(empty)[0], bj[dists.argmin(1)]] = 1.0
            s = W.sum(1)
        W[:] = W / s[:, None] * np.where(total0 > 0, total0, 1.0)

    if opts.get("side_split", True):
        moved["side_split"] = round(side_split(), 3); renorm()
    if opts.get("capsule_scale"):
        moved["capsules"] = round(capsules(), 3); renorm()
    iters = int(opts.get("junction_iterations", 0))
    if iters:
        ev = np.empty(len(me.edges) * 2, dtype=np.int64); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
        lw = W[:, limb].sum(1)
        mask = (lw > 0.02) & (lw < 0.98)
        for _ in range(int(opts.get("junction_rings", 2))):
            grow = mask.copy(); grow[ev[mask[ev[:, 0]], 1]] = True; grow[ev[mask[ev[:, 1]], 0]] = True; mask = grow
        deg = np.zeros(nv); np.add.at(deg, ev[:, 0], 1); np.add.at(deg, ev[:, 1], 1)
        a = float(opts.get("junction_factor", 0.5))
        for _ in range(iters):
            acc = np.zeros_like(W); np.add.at(acc, ev[:, 0], W[ev[:, 1]]); np.add.at(acc, ev[:, 1], W[ev[:, 0]])
            avg = acc / np.maximum(deg, 1)[:, None]
            W[mask] = (1 - a) * W[mask] + a * avg[mask]
        moved["junction_verts"] = int(mask.sum())
        if opts.get("side_split", True):
            side_split(); renorm()
    helpers = opts.get("helpers")
    if helpers:
        # helpers: {"DEF-thigh.L": "DEF-thigh_half.L", ...} from helper_bones.py; True = read rig["u3d_helpers"]
        if helpers is True:
            helpers = dict(arm.get("u3d_helpers", {}))
        moved["helpers"] = {}
        for limb_bone, hname in helpers.items():
            if limb_bone not in names or hname not in arm.data.bones:
                continue
            if hname not in names:
                g = mesh.vertex_groups.get(hname) or mesh.vertex_groups.new(name=hname)
                names.append(hname); W = np.concatenate([W, np.zeros((nv, 1))], 1)
                limb = np.append(limb, True); body = np.append(body, False)
            hj = names.index(hname)
            # chain = the limb bone and its deform descendants
            root = arm.data.bones[limb_bone]
            chain = {root.name} | {c.name for c in root.children_recursive if c.use_deform}
            cj = [j for j, n in enumerate(names) if n in chain]
            bj = np.where(body)[0]
            wl = W[:, cj].sum(1); wb = W[:, bj].sum(1); tot = wl + wb
            sel = (wl > 1e-4) & (wb > 1e-4)
            s_ = np.where(tot > 0, wl / np.maximum(tot, 1e-12), 0)
            new_l = tot * np.clip(2 * s_ - 1, 0, 1)
            new_h = tot * (1 - np.abs(2 * s_ - 1))
            new_b = tot * np.clip(1 - 2 * s_, 0, 1)
            fl = np.where(wl > 0, new_l / np.maximum(wl, 1e-12), 0)
            fb = np.where(wb > 0, new_b / np.maximum(wb, 1e-12), 0)
            W[np.ix_(sel, cj)] *= fl[sel][:, None]
            W[np.ix_(sel, bj)] *= fb[sel][:, None]
            W[sel, hj] += new_h[sel]
            # upper segment share: on stubby / chubby limbs the upper segment (thigh, upper arm) is mostly inside the
            # body; letting its skin follow the helper (half rotation) spreads the hip/shoulder swing further
            f = float(opts.get("helper_upper_share", 0.0))
            if f > 0:
                base = limb_bone.rsplit(".", 1)[0] if limb_bone[-2:] in (".L", ".R") else limb_bone
                uj = [j for j, n in enumerate(names) if n in chain and n.startswith(base)]
                take = W[:, uj] * f
                W[:, uj] -= take
                W[:, hj] += take.sum(1)
            moved["helpers"][hname] = int(sel.sum())
    # write back
    for j, n in enumerate(names):
        g = mesh.vertex_groups[n]
        g.remove(list(range(nv)))
        nz = np.nonzero(W[:, j] > 1e-6)[0]
        for vi in nz:
            g.add([int(vi)], float(W[vi, j]), "REPLACE")
    return moved


def auto_weights(mesh, arm, rigid_groups, max_inf, clean, smooth, transfers=None, refine=None):
    _activate(mesh, arm)
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    deform = {b.name for b in arm.data.bones if b.use_deform}
    apply_transfers(mesh, transfers, arm)
    # rigid vertex sets: weight 1.0 to one bone, 0 elsewhere
    for vg_name, bone in (rigid_groups or {}).items():
        src = mesh.vertex_groups.get(vg_name)
        if src is None:
            continue
        idx = [v.index for v in mesh.data.vertices if any(g.group == src.index and g.weight > 0.5 for g in v.groups)]
        for g in mesh.vertex_groups:
            if g.name in deform and g.name != bone:
                g.remove(idx)
        tgt = mesh.vertex_groups.get(bone) or mesh.vertex_groups.new(name=bone)
        tgt.add(idx, 1.0, "REPLACE")
    refined = refine_limbs(mesh, arm, refine) if refine else None
    _activate(mesh)
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    if smooth:
        bpy.ops.object.vertex_group_smooth(group_select_mode="BONE_DEFORM", factor=0.5, repeat=int(smooth))
    bpy.ops.object.vertex_group_clean(group_select_mode="BONE_DEFORM", limit=clean)
    bpy.ops.object.vertex_group_limit_total(group_select_mode="BONE_DEFORM", limit=max_inf)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="BONE_DEFORM", lock_active=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return refined


def attach_rigid_objects(arm, parts):
    out = {}
    for obj_name, bone in (parts or {}).items():
        ob = bpy.data.objects.get(obj_name)
        if ob is None or bone not in arm.data.bones:
            out[obj_name] = "missing object or bone"
            continue
        mw = ob.matrix_world.copy()
        ob.parent = arm
        ob.parent_type = "BONE"
        ob.parent_bone = bone
        bpy.context.view_layer.update()
        ob.matrix_world = mw
        out[obj_name] = bone
    return out


def _far_weights(mesh, arm, gidx, share=0.2, ratio=3.0, min_rel=0.08):
    """Vertices with ≥ `share` weight on a bone far from them: farther than `ratio` × the distance to the nearest
    deform bone and than `min_rel` × the mesh size. Catches a paw re-mapped to a hip bone, a hand weighted to the
    other arm, a head following a foot — skin that will slide off its limb when posed."""
    import numpy as np
    me = mesh.data
    nv = len(me.vertices)
    co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    mw = np.array(mesh.matrix_world); P = co @ mw[:3, :3].T + mw[:3, 3]
    size = float(np.linalg.norm(P.max(0) - P.min(0)))
    amw = arm.matrix_world
    names = sorted(set(gidx.values()))
    D = {}
    for n in names:
        b = arm.data.bones[n]
        a = np.array(amw @ b.head_local); t = np.array(amw @ b.tail_local); ab = t - a
        u = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        D[n] = np.linalg.norm(P - (a + u[:, None] * ab), axis=1)
    nearest = np.min(np.stack([D[n] for n in names], 1), 1) if names else np.zeros(nv)
    # a half-rotation helper stands in for its limb's upper segment: measure it against that segment too
    for limb, h in (arm.get("u3d_helpers") or {}).items():
        if h in D:
            seg = [n for n in names if n == limb or (n.startswith(limb + ".") and n[len(limb) + 1:].isdigit())]
            for n in seg:
                D[h] = np.minimum(D[h], D[n])
    bad = set()
    bones = {}
    for v in me.vertices:
        for g in v.groups:
            n = gidx.get(g.group)
            if n is None or g.weight < share:
                continue
            dist = D[n][v.index]
            if dist > ratio * max(nearest[v.index], 1e-4) and dist > min_rel * size:
                bad.add(v.index)
                bones[n] = bones.get(n, 0) + 1
    return len(bad), dict(sorted(bones.items(), key=lambda x: -x[1])[:6])


def check(mesh, arm, max_inf):
    deform = {b.name for b in arm.data.bones if b.use_deform}
    gidx = {g.index: g.name for g in mesh.vertex_groups if g.name in deform}
    unweighted = over = unnorm = 0
    worst = 0
    for v in mesh.data.vertices:
        ws = [g.weight for g in v.groups if g.group in gidx and g.weight > 0]
        if not ws:
            unweighted += 1
            continue
        worst = max(worst, len(ws))
        if len(ws) > max_inf:
            over += 1
        if abs(sum(ws) - 1.0) > 1e-3:
            unnorm += 1
    has_mod = any(m.type == "ARMATURE" and m.object == arm for m in mesh.modifiers)
    used = {gidx[g.group] for v in mesh.data.vertices for g in v.groups if g.group in gidx and g.weight > 0.01}
    unused = sorted(deform - used)
    far, far_bones = _far_weights(mesh, arm, gidx)
    return {"far_weight_verts": far, "far_weight_bones": far_bones, "armature_modifier": has_mod, "deform_bones": len(deform), "deform_bones_without_weights": unused,
            "unweighted_verts": unweighted,
            "verts_over_max_influences": over, "max_influences_found": worst,
            "unnormalized_verts": unnorm, "max_influences_allowed": max_inf}


def run(args: dict) -> dict:
    mesh = bpy.data.objects.get(args.get("mesh", ""))
    arm = bpy.data.objects.get(args.get("armature", ""))
    if mesh is None or arm is None:
        return C.result_error("mesh and armature required")
    max_inf = int(args.get("max_influences", 4))
    out = {}
    if args.get("mode", "check") == "auto":
        refined = auto_weights(mesh, arm, args.get("rigid_groups"), max_inf,
                               float(args.get("clean_threshold", 0.01)), int(args.get("smooth_iterations", 0)),
                               args.get("transfers"), args.get("refine"))
        if refined is not None:
            out["refine"] = refined
        out["rigid_objects"] = attach_rigid_objects(arm, args.get("rigid_parts"))
    m = check(mesh, arm, max_inf)
    notes = []
    collapsed = len(m["deform_bones_without_weights"]) > 0.25 * max(m["deform_bones"], 1)
    if collapsed:
        notes.append("more than 25% of deform bones have no weights: automatic weights collapsed "
                     "(check that the rig overlaps the mesh — an unapplied metarig transform displaces the "
                     "generated rig — and Blender's bone-heat warnings)")
    far_bad = m["far_weight_verts"] > 0.002 * max(len(mesh.data.vertices), 1)
    if far_bad:
        notes.append(f"{m['far_weight_verts']} vertices carry weight from distant bones {m['far_weight_bones']}: "
                     "they will slide off their limb when posed (e.g. paws mapped to a hip helper)")
    status = "pass" if (m["armature_modifier"] and m["unweighted_verts"] == 0 and not collapsed and not far_bad and
                        m["verts_over_max_influences"] == 0 and m["unnormalized_verts"] == 0) else "fail"
    gate = {"gate": "G4b", "status": status, "metrics": m, "notes": notes, "at": C.now_iso()}
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", "gate-G4b.json"), gate)
    return C.result_ok(gate=gate, **out)
