"""Rigid rigs from the structure analysis: ball (roll/bounce/squash) and vehicle (wheels, steering, body).

Rigid parts are parented to bones (no skinning): cheapest at runtime, exact in every engine, and the clips are
armature actions like any other (export_glb.py, sample_vertices.py, G7 work unchanged).

kind "ball":     root (ground contact) → squash (contact, scales along up) → spin (centre, bone axis = roll axis)
                 → the mesh. Squash keeps the ball on the ground; spin turns inside it.
kind "vehicle":  root (ground) → body (bob/pitch/roll) → body meshes
                 root → steer_F* (vertical bone at each front wheel, when steering) → wheel_F* → wheel mesh
                 root → wheel_R* → wheel mesh. Wheel bones point along the axle, so spin = local Y rotation.
                 Fused wheels (one AI mesh) are cut out first when split_wheels is true: vertices inside each
                 measured wheel cylinder, from the outer face to the inner face measured below the axle; holes
                 in body and wheel are filled.

args:
    kind            (str, required)   "ball" | "vehicle"
    objects         (list[str])       mesh objects of the model
    structure       (dict | str)      structure_analysis result (or path to reports/structure.json)
    forward         (str, optional)   "X", "-X", "Y", "-Y" (confirmed by the user); default from the structure
    split_wheels    (bool, False)     cut fused wheels into separate objects (ask the user first)
    steer_front     (bool, True)      front wheels get steering bones
    name            (str, "RIG")      armature name prefix
returns {"rig", "bones", "parts": {object: bone}, "wheels": [...]}; stores rig["u3d_rigid"]
"""
import importlib.util
import json
import math
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
AX = {"X": Vector((1, 0, 0)), "-X": Vector((-1, 0, 0)), "Y": Vector((0, 1, 0)), "-Y": Vector((0, -1, 0))}


def _world_verts(ob):
    co = np.empty(len(ob.data.vertices) * 3); ob.data.vertices.foreach_get("co", co)
    mw = np.array(ob.matrix_world)
    return co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]


def _fill_holes(bm):
    edges = [e for e in bm.edges if e.is_boundary]
    if edges:
        bmesh.ops.holes_fill(bm, edges=edges, sides=0)


def split_fused_wheels(ob, wheels, up):
    """Cut each wheel cylinder out of `ob` into its own object. Returns the new objects (same order as wheels)."""
    P = _world_verts(ob)
    up = np.asarray(up, float)
    out = []
    assign = -np.ones(len(P), dtype=np.int64)
    for k, w in enumerate(wheels):
        c = np.array(w["centre"]); a = np.array(w["axis"]) * (1 if w.get("side", 1) > 0 else -1)
        a /= np.linalg.norm(a)
        if (c - P.mean(0)) @ a < 0:
            a = -a                                   # outward
        r = float(w["radius"])
        rel = P - c
        t = rel @ a                                  # along the axle, 0 at the outer face, negative inward
        radial = np.linalg.norm(rel - np.outer(t, a), axis=1)
        inside = radial < 1.03 * r
        below = inside & ((rel @ up) < -0.5 * r) & (t > -0.6 * r)
        inner = float(np.percentile(t[below], 2)) if below.sum() > 10 else -0.5 * r
        sel = inside & (t >= inner - 1e-4) & (t <= 0.02 * r)
        assign[sel & (assign < 0)] = k
    me = ob.data
    for k, w in enumerate(wheels):
        idx = set(np.where(assign == k)[0].tolist())
        bm = bmesh.new(); bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        keep_faces = [f for f in bm.faces if all(v.index in idx for v in f.verts)]
        others = [f for f in bm.faces if f not in set(keep_faces)]
        bmesh.ops.delete(bm, geom=others, context="FACES")
        _fill_holes(bm)
        wm = bpy.data.meshes.new(f"{ob.name}_wheel{k + 1}")
        bm.to_mesh(wm); bm.free()
        for m in me.materials:
            wm.materials.append(m)
        wo = bpy.data.objects.new(f"{ob.name}_wheel{k + 1}", wm)
        wo.matrix_world = ob.matrix_world.copy()
        for col in ob.users_collection:
            col.objects.link(wo)
        out.append(wo)
    # remove wheel faces from the body
    bm = bmesh.new(); bm.from_mesh(me)
    cut = set(np.where(assign >= 0)[0].tolist())
    faces = [f for f in bm.faces if any(v.index in cut for v in f.verts)]   # no shared ring with the wheels
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    _fill_holes(bm)
    bm.to_mesh(me); bm.free()
    me.update()
    return out


def _armature(name, scene):
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    scene.collection.objects.link(rig)
    return rig


def _edit(rig, scene):
    for o in scene.objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    return rig.data.edit_bones


def _bone(eb, name, head, tail, parent=None, roll_up=None):
    b = eb.new(name)
    b.head = Vector(head); b.tail = Vector(tail)
    if roll_up is not None:
        b.align_roll(Vector(roll_up))
    if parent:
        b.parent = eb[parent]
    b.use_deform = True
    return b


def _parent(ob, rig, bone):
    mw = ob.matrix_world.copy()
    ob.parent = rig
    ob.parent_type = "BONE"
    ob.parent_bone = bone
    bpy.context.view_layer.update()
    ob.matrix_world = mw


def run(args: dict) -> dict:
    kind = args.get("kind")
    S = args.get("structure")
    if isinstance(S, str):
        S = json.load(open(S))
    if not S:
        return C.result_error("structure (structure_analysis result) required")
    objs = [bpy.data.objects[n] for n in args.get("objects", [])]
    if not objs:
        return C.result_error("objects required")
    scene = bpy.context.scene
    up = Vector(S["axes"]["up"])
    ground = min(float(_world_verts(o)[:, 2].min()) for o in objs)
    fwd = args.get("forward") or S["forward"]["value"]
    if fwd not in AX:                                  # "none"/"unknown": round or undecided → world X, or the major axis
        fwd = "X" if S["forward"]["value"] == "none" else fwd
    F = AX.get(fwd, Vector(S["axes"]["major_horizontal"])).normalized()
    L = up.cross(F).normalized()                       # left
    name = args.get("name", "RIG")
    meta = {"kind": kind, "forward": list(F), "left": list(L), "up": list(up)}
    parts = {}
    if kind == "ball":
        part = S["parts"][0]
        c = Vector(part["centre"]); r = float(part.get("radius") or S["size"]["height"] / 2)
        rig = _armature(name, scene)
        eb = _edit(rig, scene)
        base = Vector((c.x, c.y, ground))
        _bone(eb, "root", base, base + up * r * 0.5, roll_up=F)
        _bone(eb, "squash", base, base + up * r * 0.4, "root", roll_up=F)
        _bone(eb, "spin", c, c + L * r * 0.6, "squash", roll_up=up)
        bpy.ops.object.mode_set(mode="OBJECT")
        for o in objs:
            _parent(o, rig, "spin"); parts[o.name] = "spin"
        meta.update({"radius": r, "spin_bone": "spin", "squash_bone": "squash", "root_bone": "root"})
    elif kind == "vehicle":
        wheels = list(S["wheels"])
        if len(wheels) < 2:
            return C.result_error("no wheels in the structure; confirm the parts with the user")
        if any(w.get("source") == "fused_side_slab" for w in wheels):
            if not args.get("split_wheels"):
                return C.result_error("wheels are fused into the body: pass split_wheels=true after the user agrees")
            body = max(objs, key=lambda o: len(o.data.vertices))
            wobjs = split_fused_wheels(body, wheels, up)
            wheel_obj = {k: [wo] for k, wo in enumerate(wobjs)}
            body_objs = [body]
        else:
            wheel_obj = {}
            for k, w in enumerate(wheels):
                wheel_obj[k] = [bpy.data.objects[n] for n in w.get("objects", []) if n in bpy.data.objects]
            used = {o.name for v in wheel_obj.values() for o in v}
            body_objs = [o for o in objs if o.name not in used]
        cen = Vector(np.mean([w["centre"] for w in wheels], axis=0))
        rig = _armature(name, scene)
        eb = _edit(rig, scene)
        base = Vector((cen.x, cen.y, ground))
        hgt = S["size"]["height"]
        _bone(eb, "root", base, base + up * hgt * 0.3, roll_up=F)
        bc = Vector(S["parts"][0]["centre"])
        _bone(eb, "body", bc, bc + up * hgt * 0.25, "root", roll_up=F)
        winfo = []
        for k, w in enumerate(wheels):
            wc = Vector(w["centre"]); r = float(w["radius"])
            front = (wc - cen).dot(F) > 0
            left = (wc - cen).dot(L) > 0
            tag = ("F" if front else "R") + ("L" if left else "R")
            out = L if left else -L
            parent = "root"
            if front and args.get("steer_front", True):
                _bone(eb, f"steer_{tag}", wc, wc + up * r, "root", roll_up=F)
                parent = f"steer_{tag}"
            _bone(eb, f"wheel_{tag}", wc, wc + out * r * 0.6, parent, roll_up=up)
            winfo.append({"bone": f"wheel_{tag}", "steer": parent if parent != "root" else None, "radius": r,
                          "front": front, "left": left, "objects": [o.name for o in wheel_obj.get(k, [])]})
        bpy.ops.object.mode_set(mode="OBJECT")
        for o in body_objs:
            _parent(o, rig, "body"); parts[o.name] = "body"
        for k, wi in enumerate(winfo):
            for o in wheel_obj.get(k, []):
                _parent(o, rig, wi["bone"]); parts[o.name] = wi["bone"]
        fr = [w for w in winfo if w["front"]]; rr = [w for w in winfo if not w["front"]]
        wb = 0.0
        if fr and rr:
            wb = float(np.mean([Vector(wheels[winfo.index(a)]["centre"]).dot(F) for a in fr]) -
                       np.mean([Vector(wheels[winfo.index(a)]["centre"]).dot(F) for a in rr]))
        meta.update({"wheels": winfo, "wheelbase": wb, "root_bone": "root", "body_bone": "body"})
    else:
        return C.result_error(f"unknown kind {kind}")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    rig["u3d_rigid"] = json.dumps(meta)
    return C.result_ok(rig=rig.name, bones=[b.name for b in rig.data.bones], parts=parts, meta=meta)
