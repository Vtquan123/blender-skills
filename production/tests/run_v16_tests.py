"""Regression tests for the v1.6 scripts: anim_curves, motion_qa, game_skeleton, mesh_cleanup.

Run inside Blender through the MCP (or `blender --background --python run_v16_tests.py`):

    import runpy
    ns = runpy.run_path("<repo>/production/tests/run_v16_tests.py")
    result = ns["run"]({"only": ["anim_curves"]})      # default: every test

Everything is built in a throw-away scene ("TEST_v16") that is removed afterwards; nothing in the
user's scenes is touched. Each test returns {"pass": bool, ...measures}.
"""
import math
import os
import runpy
import traceback

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts", "blender")
PREFIX = "T16_"


def _script(name):
    return runpy.run_path(os.path.join(SCRIPTS, name + ".py"))


# ---------------------------------------------------------------- builders
def chain_rig(name, n=4, seg=0.2):
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    prev = None
    for i in range(n):
        b = arm.edit_bones.new(f"tail.{i}")
        b.head, b.tail = (0, i * seg, 0), (0, (i + 1) * seg, 0)
        if prev:
            b.parent, b.use_connect = prev, True
        prev = b
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def leg_rig(name):
    """Root → hips → thigh/shin/foot (L) with a skinned tube, for motion_qa and game_skeleton."""
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    root = eb.new("root"); root.head, root.tail = (0, 0, 0), (0, 0.3, 0); root.use_deform = False
    hips = eb.new("DEF-hips"); hips.head, hips.tail = (0, 0, 1.0), (0, 0, 1.2); hips.parent = root
    org = eb.new("ORG-thigh.L"); org.head, org.tail = (0.1, 0, 1.0), (0.1, 0.02, 0.55); org.parent = hips
    org.use_deform = False
    th = eb.new("DEF-thigh.L"); th.head, th.tail = (0.1, 0, 1.0), (0.1, 0.02, 0.55); th.parent = org
    sh = eb.new("DEF-shin.L"); sh.head, sh.tail = (0.1, 0.02, 0.55), (0.1, 0, 0.1); sh.parent = th; sh.use_connect = True
    ft = eb.new("DEF-foot.L"); ft.head, ft.tail = (0.1, 0, 0.1), (0.1, -0.15, 0.02); ft.parent = sh; ft.use_connect = True
    th.bbone_segments = 4
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.06, depth=1.0, location=(0.1, 0, 0.55))
    tube = bpy.context.active_object
    tube.name = name + "_skin"
    tube.data.name = name + "_skin"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=10)
    bpy.ops.object.mode_set(mode="OBJECT")
    tube.parent = rig
    mod = tube.modifiers.new("Armature", "ARMATURE"); mod.object = rig
    for bn in ("DEF-hips", "DEF-thigh.L", "DEF-shin.L", "DEF-foot.L", "DEF-unused"):
        tube.vertex_groups.new(name=bn)
    for v in tube.data.vertices:
        z = v.co.z + 0.55
        g = "DEF-foot.L" if z < 0.12 else ("DEF-shin.L" if z < 0.55 else "DEF-thigh.L")
        tube.vertex_groups[g].add([v.index], 1.0, "REPLACE")
    return rig, tube


# ---------------------------------------------------------------- tests
def test_anim_curves():
    ns = _script("anim_curves")
    rig = chain_rig(PREFIX + "chain")
    act = bpy.data.actions.new(PREFIX + "wag")
    rig.animation_data_create().action = act
    pb = rig.pose.bones["tail.0"]
    pb.rotation_mode = "XYZ"
    for f in range(1, 26, 4):
        pb.rotation_euler = (0, 0, 0.5 * math.sin(2 * math.pi * (f - 1) / 24))
        pb.keyframe_insert("rotation_euler", frame=f)
    sc = bpy.context.scene
    r = {}
    r["overlap"] = ns["run"]({"object": rig.name, "action": act.name, "op": "overlap", "frames": [1, 25],
                              "chain": ["tail.0", "tail.1", "tail.2", "tail.3"], "lag": 2, "falloff": 0.9})

    def zrot(bn, f):
        sc.frame_set(f)
        return rig.pose.bones[bn].matrix_basis.to_quaternion().to_euler().z
    lag_err = max(abs(zrot("tail.0", f - 2) - zrot("tail.1", f)) for f in (5, 9, 13))
    r["overlap_lag_error_rad"] = round(lag_err, 5)
    r["ops"] = ns["run"]({"object": rig.name, "action": act.name, "ops": [
        {"op": "push_pull", "bones": ["tail.0"], "factor": 0.5, "frames": [5, 9]},
        {"op": "smooth", "bones": ["tail.0"], "iterations": 2},
        {"op": "match_cycle", "bones": ["tail.*"], "period": 25},
        {"op": "wave", "bones": ["tail.3"], "amplitude": 0.02, "period": 12, "kind": "noise"},
        {"op": "clean", "bones": ["tail.1"], "tolerance": 0.002},
        {"op": "time_offset", "bones": ["tail.0"], "shift": 3},
        {"op": "offset", "bones": ["tail.0"], "frames": [9, 13], "blend": 4,
         "delta": {"tail.0": {"rotation_euler": [0, 0, 0.2]}}},
    ]})
    sc.frame_set(1)
    q1 = rig.pose.bones["tail.2"].matrix_basis.to_quaternion()
    sc.frame_set(25)
    q25 = rig.pose.bones["tail.2"].matrix_basis.to_quaternion()
    r["cycle_seam_deg"] = round(math.degrees(q1.rotation_difference(q25).angle), 4)
    r["loop"] = ns["run"]({"object": rig.name, "action": act.name, "op": "loop_window",
                           "bones": ["tail.*"], "min_len": 10, "crossfade": 3})
    r["restore"] = ns["run"]({"object": rig.name, "action": act.name, "op": "restore"}).get("ok")
    ok = (r["overlap"]["ok"] and lag_err < 1e-3 and r["ops"]["ok"] and r["cycle_seam_deg"] < 0.01
          and r["loop"]["ok"] and r["loop"]["ops"][0]["seam"] <= 1.5 and r["restore"])
    return {"pass": bool(ok), **r}


def test_motion_qa():
    """A leg that snaps straight for one frame and pushes the foot through the floor must be caught."""
    ns = _script("motion_qa")
    rig, tube = leg_rig(PREFIX + "leg")
    act = bpy.data.actions.new(PREFIX + "kick")
    rig.animation_data_create().action = act
    th, sh = rig.pose.bones["DEF-thigh.L"], rig.pose.bones["DEF-shin.L"]
    for pb in (th, sh):
        pb.rotation_mode = "XYZ"
    for f in range(1, 25):
        bend = 0.6 + 0.3 * math.sin(2 * math.pi * (f - 1) / 24)
        if f == 12:
            bend = 0.0                        # one-frame snap straight: a pop
        th.rotation_euler = (-bend / 2, 0, 0)
        sh.rotation_euler = (bend, 0, 0)
        th.keyframe_insert("rotation_euler", frame=f)
        sh.keyframe_insert("rotation_euler", frame=f)
    rig.pose.bones["DEF-hips"].location = (0, 0, 0)
    rig.pose.bones["DEF-hips"].keyframe_insert("location", frame=1)
    rig.pose.bones["DEF-hips"].location = (0, -0.12, 0)   # bone points up: local Y is world Z (kiln rule 1)
    rig.pose.bones["DEF-hips"].keyframe_insert("location", frame=12)
    r = ns["run"]({"armature": rig.name, "clips": [act.name], "mesh": tube.name,
                   "limbs": [{"name": "leg.L", "start": "DEF-thigh.L", "knee": "DEF-shin.L",
                              "end": "DEF-foot.L", "foot": "DEF-foot.L"}]})
    m = r["report"]["clips"][act.name]
    leg = m["limbs"]["leg.L"]
    ok = (r["ok"] and leg["joint_pops"] >= 1 and 12 in leg["pop_frames"] and leg["reach_max"] > 0.95
          and m["under_floor_mm"] > 5 and not m["closing_key"] and r["report"]["status"] == "fail")
    auto = ns["find_limbs"](rig)
    return {"pass": bool(ok and any(lb["end"] == "DEF-foot.L" for lb in auto)), "leg": leg,
            "under_floor_mm": m["under_floor_mm"], "jitter": m["jitter_deg"], "closing_key": m["closing_key"],
            "auto_limbs": [(lb["start"], lb["knee"], lb["end"]) for lb in auto], "notes": r["report"]["notes"]}


def test_game_skeleton():
    ns = _script("game_skeleton")
    rig, tube = leg_rig(PREFIX + "gs")
    act = bpy.data.actions.new(PREFIX + "swing")
    rig.animation_data_create().action = act
    th = rig.pose.bones["DEF-thigh.L"]
    th.rotation_mode = "XYZ"
    for f, a in ((1, 0.0), (12, 0.8), (24, 0.0)):
        th.rotation_euler = (a, 0, 0)
        th.keyframe_insert("rotation_euler", frame=f)
    th.scale = (1, 1.2, 1)                     # a scaled deform bone
    th.keyframe_insert("scale", frame=12)
    th.scale = (1, 1, 1)
    th.keyframe_insert("scale", frame=1)
    th.keyframe_insert("scale", frame=24)
    au = ns["run"]({"armature": rig.name, "actions": [act.name]})["audit"]
    ex = ns["run"]({"armature": rig.name, "mode": "export_rig", "name": PREFIX + "gs_game", "actions": [act.name],
                    "collection": PREFIX + "COL"})
    game = bpy.data.objects.get(PREFIX + "gs_game")
    ok = (au["bbones"] == ["DEF-thigh.L"] and "DEF-hips" in au["weights"]["dead_deform_bones"]
          and au["scaled"]["max_scale_deviation"] > 0.15 and "DEF-thigh.L" in au["non_deform_parents"]
          and ex["ok"] and ex["roots"] == ["root"] and ex["hierarchy"]["thigh.L"] == "hips"
          and ex["parity_mm"]["bone_heads_mm"] < 0.01 and all(b.bbone_segments == 1 for b in game.data.bones))
    for o in [o for o in bpy.data.objects if o.name.startswith(PREFIX + "gs") and o.name.endswith("_game")]:
        bpy.data.objects.remove(o, do_unlink=True)
    col = bpy.data.collections.get(PREFIX + "COL")
    if col:
        bpy.data.collections.remove(col)
    return {"pass": bool(ok), "audit_problems": au["problems"], "verdict": au["verdict"], "roots": ex.get("roots"),
            "hierarchy": ex.get("hierarchy"), "parity_mm": ex.get("parity_mm"),
            "skin_note": "skin parity differs by design here: the scaled thigh keeps its scale only on the control rig"}


def test_mesh_cleanup():
    ns = _script("mesh_cleanup")
    # a mug: body with doubled vertices, a loose vertex, one flipped face, and a thin handle
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.04, depth=0.1, location=(0, 0, 0.05))
    body = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=6)
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    body.data.polygons[0].select = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.flip_normals()
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.edge_split(type="EDGE")           # split edges: every vertex doubled
    bpy.ops.object.mode_set(mode="OBJECT")
    body.data.vertices.add(1)
    body.scale = (2, 2, 2)
    body.name = body.data.name = PREFIX + "mug"
    r = ns["run"]({"object": body.name, "decimate": {"target_tris": 1200}, "budget": {"tier": "lightweight", "role": "prop"}})
    b, a = r["before"], r["after"]
    ok = (r["ok"] and b["duplicate_verts"] > 0 and a["duplicate_verts"] == 0 and a["loose_verts"] == 0
          and a["open_edges"] <= 2 * 48 and r["decimate"]["applied"] and a["tris"] <= 1200 * 2
          and abs(bpy.data.objects[r["object"]].matrix_world.to_scale()[0] - 1) < 1e-6
          and bpy.data.objects[body.name].data.vertices[0] is not None)
    # guard: a torus ring (thin, closed) decimated to almost nothing must not open
    bpy.ops.mesh.primitive_torus_add(major_radius=0.05, minor_radius=0.004, major_segments=64, minor_segments=12)
    ring = bpy.context.active_object
    ring.name = ring.data.name = PREFIX + "ring"
    g = ns["run"]({"object": ring.name, "steps": ["decimate"], "decimate": {"target_tris": 40}})
    ga = g["after"]
    guard_ok = ga["open_edges"] == 0 and ga["nonmanifold_edges"] == 0
    for o in [o for o in bpy.data.objects if o.name.endswith("_clean")]:
        bpy.data.objects.remove(o, do_unlink=True)
    return {"pass": bool(ok and guard_ok), "before": b, "after": a, "steps": r["steps"], "budget": r["budget"],
            "ring_decimate": {k: v for k, v in (g["decimate"] or {}).items()}, "ring_after": ga,
            "warnings": r["warnings"] + g["warnings"]}


TESTS = {"anim_curves": test_anim_curves, "motion_qa": test_motion_qa, "game_skeleton": test_game_skeleton,
         "mesh_cleanup": test_mesh_cleanup}


def _cleanup(sc):
    for ob in list(sc.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.scenes.remove(sc)
    for kind in ("objects", "actions", "meshes", "armatures", "collections"):
        coll = getattr(bpy.data, kind)          # a new wrapper on every access: compare by name, not identity
        for nm in [d.name for d in coll if d.name.startswith(PREFIX)]:
            d = coll.get(nm)
            if d is not None and (kind in ("objects", "actions", "collections") or d.users == 0):
                coll.remove(d)


def run(args=None):
    args = args or {}
    only = args.get("only") or list(TESTS)
    win = bpy.context.window
    prev = win.scene if win else bpy.context.scene
    sc = bpy.data.scenes.new("TEST_v16")
    if win:
        win.scene = sc
    out = {}
    try:
        for name in only:
            try:
                out[name] = TESTS[name]()
            except Exception:
                out[name] = {"pass": False, "trace": traceback.format_exc()}
    finally:
        if win:
            win.scene = prev
        if not args.get("keep"):
            _cleanup(sc)
    left = [d.name for c in (bpy.data.actions, bpy.data.objects, bpy.data.meshes, bpy.data.armatures)
            for d in c if d.name.startswith(PREFIX)]
    return {"all_pass": all(v.get("pass") for v in out.values()), "results": out, "left_behind": left}
