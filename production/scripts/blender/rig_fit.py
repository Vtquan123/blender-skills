"""Fit a skeleton template to a mesh (deformation-prep steps 2 and 6). Produces a PROPOSAL the user confirms.

args:
    mesh        (str, required)  deform mesh (or source) to fit
    template    (str, required)  rigify metarig name: human | basic_human | basic_quadruped | cat | wolf | horse | shark,
                                 or "bird" (production/rigs/bird_metarig.py)
    forward     (str, "-Y")      direction the model faces (Rigify metarigs face -Y)
    snap        (bool, True)     move bone heads to cross-section centres of the mesh
    generate    (bool, False)    run Rigify generate (after the user approved joint placement)
    metarig     (str, optional)  existing metarig name (skip creation, e.g. to snap/generate again)

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
        eb.head = inv @ Vector(c)
        moved[eb.name] = round(float(np.linalg.norm(c - head)), 5)
    bpy.ops.object.mode_set(mode="OBJECT")
    return moved


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
        scale = fit_bbox(rig, mesh, args.get("forward", "-Y"))
        for o in bpy.context.selected_objects:
            o.select_set(False)
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    moved = snap_heads(rig, mesh) if args.get("snap", True) else {}
    out = {"metarig": rig.name, "rigify_module": rig_mod, "scale": scale, "snapped": moved,
           "bones": len(rig.data.bones), "next": "screenshot front/side with X-ray; user confirms joints"}
    if args.get("generate"):
        bpy.context.view_layer.objects.active = rig
        before = set(bpy.data.objects)
        bpy.ops.pose.rigify_generate()
        gen = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
        out["rig"] = gen[0].name if gen else rig.data.get("rigify_target_rig", None)
        if gen:
            out["deform_bones"] = sum(1 for b in gen[0].data.bones if b.use_deform)
    return C.result_ok(**out)
