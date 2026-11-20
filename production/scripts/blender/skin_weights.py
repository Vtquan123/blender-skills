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


def auto_weights(mesh, arm, rigid_groups, max_inf, clean, smooth, transfers=None):
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
    _activate(mesh)
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    if smooth:
        bpy.ops.object.vertex_group_smooth(group_select_mode="BONE_DEFORM", factor=0.5, repeat=int(smooth))
    bpy.ops.object.vertex_group_clean(group_select_mode="BONE_DEFORM", limit=clean)
    bpy.ops.object.vertex_group_limit_total(group_select_mode="BONE_DEFORM", limit=max_inf)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="BONE_DEFORM", lock_active=False)
    bpy.ops.object.mode_set(mode="OBJECT")


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
    return {"armature_modifier": has_mod, "deform_bones": len(deform), "deform_bones_without_weights": unused,
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
        auto_weights(mesh, arm, args.get("rigid_groups"), max_inf,
                     float(args.get("clean_threshold", 0.01)), int(args.get("smooth_iterations", 0)),
                     args.get("transfers"))
        out["rigid_objects"] = attach_rigid_objects(arm, args.get("rigid_parts"))
    m = check(mesh, arm, max_inf)
    notes = []
    collapsed = len(m["deform_bones_without_weights"]) > 0.25 * max(m["deform_bones"], 1)
    if collapsed:
        notes.append("more than 25% of deform bones have no weights: automatic weights collapsed "
                     "(check that the rig overlaps the mesh — an unapplied metarig transform displaces the "
                     "generated rig — and Blender's bone-heat warnings)")
    status = "pass" if (m["armature_modifier"] and m["unweighted_verts"] == 0 and not collapsed and
                        m["verts_over_max_influences"] == 0 and m["unnormalized_verts"] == 0) else "fail"
    gate = {"gate": "G4b", "status": status, "metrics": m, "notes": notes, "at": C.now_iso()}
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", "gate-G4b.json"), gate)
    return C.result_ok(gate=gate, **out)
