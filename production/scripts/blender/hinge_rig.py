"""Hinge setup for articulated objects (book, box, folding/swivel chair) — deformation-prep family
`articulated_object`.

mode "pivot" (default): each moving rigid part gets its ORIGIN on the hinge axis and its local X axis
along the hinge, so a clip only rotates the object around local X. glTF exports this as node animation
(no skinning, cheapest at runtime).
mode "chain": adds a small armature with a bone chain across a bending part (book pages) and
skins that part with automatic weights.

args:
    parts  (list[dict], required)
        pivot: {"object": "Lid", "edge": ["+Y", "-Z"]}           hinge = bbox edge where the +Y face meets the -Z face
               {"object": "Cover", "points": [[x,y,z], [x,y,z]]}  explicit axis through two world points
               optional "limits_deg": [0, 110] (stored as custom property for the animator/generators)
        chain: {"object": "Pages", "mode": "chain", "from": [x,y,z], "to": [x,y,z], "bones": 4}
"""
import importlib.util
import os
import sys

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
AXES = {"X": 0, "Y": 1, "Z": 2}


def edge_axis(ob, faces):
    mn, mx = C.world_bbox([ob])
    fixed = {}
    for f in faces:
        sign, ax = f[0], AXES[f[1].upper()]
        fixed[ax] = mx[ax] if sign == "+" else mn[ax]
    free = [a for a in range(3) if a not in fixed][0]
    a = [0.0, 0.0, 0.0]
    b = [0.0, 0.0, 0.0]
    for ax, v in fixed.items():
        a[ax] = b[ax] = v
    a[free], b[free] = mn[free], mx[free]
    return np.array(a), np.array(b)


def set_pivot(ob, p0, p1):
    axis = p1 - p0
    axis /= np.linalg.norm(axis)
    center = (p0 + p1) / 2
    # build a world matrix whose X axis is the hinge axis, origin at the hinge centre
    up = np.array([0, 0, 1.0]) if abs(axis[2]) < 0.9 else np.array([0, 1.0, 0])
    y = np.cross(up, axis)
    y /= np.linalg.norm(y)
    z = np.cross(axis, y)
    new_mw = Matrix(((axis[0], y[0], z[0], center[0]),
                     (axis[1], y[1], z[1], center[1]),
                     (axis[2], y[2], z[2], center[2]),
                     (0, 0, 0, 1)))
    # move mesh data so the object can take the new matrix without visual change
    delta = new_mw.inverted() @ ob.matrix_world
    ob.data.transform(delta)
    ob.matrix_world = new_mw
    return center.tolist(), axis.tolist()


def chain(ob, p0, p1, n):
    arm_data = bpy.data.armatures.new(f"ARM_{ob.name}")
    arm = bpy.data.objects.new(f"ARM_{ob.name}", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    prev = None
    for i in range(n):
        eb = arm_data.edit_bones.new(f"chain_{i:02d}")
        eb.head = Vector(p0 + (p1 - p0) * i / n)
        eb.tail = Vector(p0 + (p1 - p0) * (i + 1) / n)
        if prev:
            eb.parent, eb.use_connect = prev, True
        prev = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.view_layer.objects:
        if o is not None:  # stale entries right after bpy.data.objects.remove
            o.select_set(False)
    ob.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    return arm.name


def run(args: dict) -> dict:
    out = []
    for part in args.get("parts", []):
        ob = bpy.data.objects.get(part.get("object", ""))
        if ob is None:
            out.append({"object": part.get("object"), "error": "not found"})
            continue
        if part.get("mode") == "chain":
            name = chain(ob, np.array(part["from"], float), np.array(part["to"], float), int(part.get("bones", 4)))
            out.append({"object": ob.name, "mode": "chain", "armature": name})
            continue
        if "points" in part:
            p0, p1 = (np.array(p, float) for p in part["points"])
        elif "edge" in part:
            p0, p1 = edge_axis(ob, part["edge"])
        else:
            out.append({"object": ob.name, "error": "need 'edge' or 'points'"})
            continue
        center, axis = set_pivot(ob, p0, p1)
        if part.get("limits_deg"):
            ob["u3d_hinge_limits_deg"] = list(part["limits_deg"])
        ob["u3d_hinge_axis"] = "local_X"
        out.append({"object": ob.name, "mode": "pivot", "center": center, "axis": axis,
                    "limits_deg": part.get("limits_deg")})
    return C.result_ok(parts=out, next="screenshot the axis; user confirms when unsure")
