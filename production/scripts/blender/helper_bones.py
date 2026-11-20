"""Half-rotation helper bones at limb roots (deformation-prep, after the rig and before skinning).

Linear blend skinning collapses skin where a limb meets the body: a vertex weighted half to the body and half to
a thigh swung 30° lands between two rigidly moved copies, so armpit, groin and belly skin folds or flips. A
helper deform bone at the limb root that turns half as far as the limb (Copy Rotation, influence 0.5) splits the
junction into two smaller steps. `skin_weights.py` (refine → "helpers") then re-maps each junction vertex:
body → helper → limb. The glTF exporter bakes the constraint, so the GLB plays it with plain skinning.

args:
    rig        (str, required)
    limbs      (list, required)  [{"bone": "DEF-thigh.L", "parent": optional (default: the bone's parent),
                                   "influence": 0.5, "length": 0.5}]
                                 helper name: DEF-thigh_half.L (side suffix kept, so side-aware steps still work)
    remove     (bool, False)     delete the helpers named for these limbs instead
Returns {"helpers": {limb: helper}}. Re-running replaces existing helpers.
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


def helper_name(bone):
    for suf in (".L", ".R", "_L", "_R"):
        if bone.endswith(suf):
            return bone[: -len(suf)] + "_half" + suf
    return bone + "_half"


def run(args: dict) -> dict:
    rig = bpy.data.objects.get(args.get("rig", ""))
    if rig is None or rig.type != "ARMATURE":
        return C.result_error("rig (armature) required")
    limbs = args.get("limbs") or []
    missing = [l["bone"] for l in limbs if l["bone"] not in rig.data.bones]
    if missing:
        return C.result_error(f"bones not in the rig: {missing}")
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = rig.mode
    for o in bpy.context.selected_objects:
        o.select_set(False)
    rig.hide_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    made = {}
    for l in limbs:
        name = helper_name(l["bone"])
        if name in eb:
            eb.remove(eb[name])
        if args.get("remove"):
            continue
        src = eb[l["bone"]]
        h = eb.new(name)
        h.head = src.head.copy()
        h.tail = src.head + (src.tail - src.head) * float(l.get("length", 0.5))
        h.roll = src.roll
        par = l.get("parent") or (src.parent.name if src.parent else None)
        h.parent = eb[par] if par else None
        h.use_connect = False
        h.use_deform = True
        h.bbone_segments = 1
        made[l["bone"]] = name
    bpy.ops.object.mode_set(mode="POSE")
    for l in limbs:
        name = made.get(l["bone"])
        if not name:
            continue
        pb = rig.pose.bones[name]
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        c = pb.constraints.new("COPY_ROTATION")
        c.name = "half_rotation"
        c.target = rig
        c.subtarget = l["bone"]
        c.owner_space = c.target_space = "WORLD"
        c.mix_mode = "REPLACE"
        c.influence = float(l.get("influence", 0.5))
        b = rig.data.bones[name]
        # same bone collections as the limb's deform bone, so layer-based visibility stays consistent
        for coll in rig.data.bones[l["bone"]].collections:
            coll.assign(b)
    bpy.ops.object.mode_set(mode="OBJECT")
    reg = dict(rig.get("u3d_helpers", {}))
    for l in limbs:
        reg.pop(l["bone"], None)
    reg.update(made)
    rig["u3d_helpers"] = reg
    if prev_active is not None:
        bpy.context.view_layer.objects.active = prev_active
    return C.result_ok(helpers=made)
