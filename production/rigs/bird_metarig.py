"""Bird metarig for Rigify (Rigify ships Human, Basic Human, Basic Quadruped, Cat, Wolf, Horse, Shark — no bird).

``build(name="METARIG_bird") -> {"metarig": name}`` creates a metarig facing -Y, about 1 m tall, made of
Rigify rig types so ``rigify_generate`` produces controls:

  spine   : hips (root) → belly → chest → (neck_1, neck_2) → head      spines.basic_spine + spines.super_head
  wings   : wing_shoulder (basic.super_copy) → upper → fore → hand (L/R)  limbs.arm
  legs    : thigh → shin → tarsus → toe  (L/R)                   limbs.rear_paw
  tail    : tail_feather_1..3 (child of hips)                   spines.basic_tail
  crest   : crest_1..2                                            basic.copy_chain

rig_fit.py scales it to the mesh bbox and snaps heads; the user confirms placement before generating.
Proportions are generic parrot-like defaults; everything is meant to be adjusted.
"""
import bpy
from mathutils import Vector

# (name, head, tail, parent, connected)
BONES = [
    ("hips", (0, 0.10, 0.42), (0, 0.05, 0.46), None, False),
    ("belly", (0, 0.05, 0.46), (0, 0.0, 0.52), "hips", True),
    ("chest", (0, 0.0, 0.52), (0, -0.06, 0.66), "belly", True),
    ("neck_1", (0, -0.06, 0.66), (0, -0.08, 0.74), "chest", False),   # not connected: head rig owns the neck
    ("neck_2", (0, -0.08, 0.74), (0, -0.09, 0.82), "neck_1", True),
    ("head", (0, -0.09, 0.82), (0, -0.12, 0.98), "neck_2", True),
    ("crest_1", (0, -0.06, 0.94), (0, -0.02, 1.02), "head", False),
    ("crest_2", (0, -0.02, 1.02), (0, 0.03, 1.08), "crest_1", True),
    ("tail_feather_1", (0, 0.20, 0.38), (0, 0.34, 0.26), "hips", False),
    ("tail_feather_2", (0, 0.34, 0.26), (0, 0.48, 0.16), "tail_feather_1", True),
    ("tail_feather_3", (0, 0.48, 0.16), (0, 0.62, 0.08), "tail_feather_2", True),
]
SIDE = [
    ("wing_shoulder", (0.05, -0.02, 0.62), (0.11, 0.0, 0.62), "chest", False),
    ("wing_upper", (0.11, 0.0, 0.62), (0.13, 0.08, 0.52), "wing_shoulder", False),
    ("wing_fore", (0.13, 0.08, 0.52), (0.12, 0.18, 0.42), "wing_upper", True),
    ("wing_hand", (0.12, 0.18, 0.42), (0.10, 0.30, 0.34), "wing_fore", True),
    ("thigh", (0.05, 0.04, 0.40), (0.06, 0.0, 0.28), "hips", False),
    ("shin", (0.06, 0.0, 0.28), (0.06, 0.03, 0.14), "thigh", True),
    ("tarsus", (0.06, 0.03, 0.14), (0.06, 0.0, 0.04), "shin", True),
    ("toe", (0.06, 0.0, 0.04), (0.06, -0.06, 0.0), "tarsus", True),
]
RIG_TYPES = {
    "hips": "spines.basic_spine",
    "wing_shoulder": "basic.super_copy",
    "neck_1": "spines.super_head",
    "tail_feather_1": "spines.basic_tail",
    "crest_1": "basic.copy_chain",
    "wing_upper": "limbs.arm",
    "thigh": "limbs.rear_paw",
}


def _mirror(p):
    return (-p[0], p[1], p[2])


def build(name="METARIG_bird"):
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(ob)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    for n, h, t, p, c in BONES:
        b = eb.new(n)
        b.head, b.tail = Vector(h), Vector(t)
        if p:
            b.parent, b.use_connect = eb[p], c
    for side, f in (("L", lambda p: p), ("R", _mirror)):
        for n, h, t, p, c in SIDE:
            b = eb.new(f"{n}.{side}")
            b.head, b.tail = Vector(f(h)), Vector(f(t))
            parent = p if p in (x[0] for x in BONES) else f"{p}.{side}"
            b.parent, b.use_connect = eb[parent], c
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in ob.pose.bones:
        base = pb.name.split(".")[0]
        if base in RIG_TYPES and hasattr(pb, "rigify_type"):
            pb.rigify_type = RIG_TYPES[base]
            if base == "hips" and hasattr(pb.rigify_parameters, "pivot_pos"):
                pb.rigify_parameters.pivot_pos = 1  # torso pivot at hips→belly joint
    _bone_collections(arm)
    return {"metarig": ob.name}


# Rigify needs bone collections with UI rows to build its control panel.
COLLECTIONS = [  # (collection, ui row, predicate on bone name)
    ("Torso", 1, lambda n: n in ("hips", "belly", "chest", "neck_1", "neck_2", "head")),
    ("Crest", 1, lambda n: n.startswith("crest")),
    ("Wing.L", 2, lambda n: n.startswith("wing_") and n.endswith(".L")),
    ("Wing.R", 2, lambda n: n.startswith("wing_") and n.endswith(".R")),
    ("Leg.L", 3, lambda n: n.split(".")[0] in ("thigh", "shin", "tarsus", "toe") and n.endswith(".L")),
    ("Leg.R", 3, lambda n: n.split(".")[0] in ("thigh", "shin", "tarsus", "toe") and n.endswith(".R")),
    ("Tail", 4, lambda n: n.startswith("tail_feather")),
]


def _bone_collections(arm):
    for name, row, pred in COLLECTIONS:
        coll = arm.collections.get(name) or arm.collections.new(name)
        if hasattr(coll, "rigify_ui_row"):
            coll.rigify_ui_row = row
        else:
            coll["rigify_ui_row"] = row
        for b in arm.bones:
            if pred(b.name):
                coll.assign(b)


if __name__ == "__main__":
    build()
