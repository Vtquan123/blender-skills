"""Tests for mocap_capture.py (MoCapAnything V2 capture → BVH import → retarget onto a project rig).

Run inside Blender through the MCP (or `blender --background --python-expr ...`):

    import runpy
    ns = runpy.run_path("<repo>/production/tests/run_mocap_tests.py")
    result = ns["run"]({})                          # offline tests
    result = ns["run"]({"real": True})              # + a real 2 s capture (minutes on CPU)

Offline tests need nothing installed: bone roles, the automatic bone map, BVH import, the capture status log,
and a retarget between two synthetic armatures with different bone names, rolls, facing and scale (checked
against the source's world bone directions). `real_capture` runs MoCapAnything on its demo cat clip when the
install is found; otherwise it reports {"pass": True, "skipped": "..."}. Objects are prefixed "TMC_" and
removed afterwards, with the "MOCAP" collection when the tests created it.
"""
import math
import os
import runpy
import shutil
import tempfile
import traceback

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts", "blender")
PREFIX = "TMC_"
_TMP = []
_NS = {}


def _m():
    if not _NS:
        _NS.update(runpy.run_path(os.path.join(SCRIPTS, "mocap_capture.py")))
    return _NS


def _tmpdir():
    d = tempfile.mkdtemp(prefix="u3d_mocap_test_")
    _TMP.append(d)
    return d


# bone: (head, tail, parent) in the armature's own space — a small biped facing -Y
BIPED = {
    "Pelvis": ((0, 0, 1.0), (0, 0, 1.1), None),
    "Spine": ((0, 0, 1.1), (0, 0, 1.4), "Pelvis"),
    "Neck": ((0, 0, 1.4), (0, 0, 1.5), "Spine"),
    "Head": ((0, 0, 1.5), (0, -0.05, 1.7), "Neck"),
    "L_Thigh": ((0.1, 0, 1.0), (0.1, 0.02, 0.55), "Pelvis"),
    "L_Calf": ((0.1, 0.02, 0.55), (0.1, 0, 0.1), "L_Thigh"),
    "R_Thigh": ((-0.1, 0, 1.0), (-0.1, 0.02, 0.55), "Pelvis"),
    "R_Calf": ((-0.1, 0.02, 0.55), (-0.1, 0, 0.1), "R_Thigh"),
}
SRC_NAMES = {k: f"Bip01_{k}" for k in BIPED}
TGT_NAMES = {"Pelvis": "spine", "Spine": "spine.001", "Neck": "neck", "Head": "head", "L_Thigh": "thigh.L",
             "L_Calf": "shin.L", "R_Thigh": "thigh.R", "R_Calf": "shin.R"}


def _armature(name, names, roll=0.0, rot_z=0.0, scale=1.0):
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(ob)
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    vl.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for key, (h, t, p) in BIPED.items():
        eb = arm.edit_bones.new(names[key])
        eb.head, eb.tail, eb.roll = Vector(h), Vector(t), roll
        if p:
            eb.parent = arm.edit_bones[names[p]]
            eb.use_connect = (Vector(BIPED[p][1]) - Vector(h)).length < 1e-6
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.rotation_euler = (0, 0, math.radians(rot_z))
    ob.scale = (scale, scale, scale)
    vl.update()
    return ob


def _animate(ob, names, frames=10):
    ob.animation_data_create()
    ob.animation_data.action = bpy.data.actions.new(PREFIX + "src_action")
    moves = {"Spine": ("X", 25), "Neck": ("Z", 30), "Head": ("Y", -20), "L_Thigh": ("X", -45),
             "L_Calf": ("X", 60), "R_Thigh": ("Y", 30), "R_Calf": ("X", 35), "Pelvis": ("Z", 15)}
    for f in range(1, frames + 1):
        w = math.sin(math.pi * (f - 1) / (frames - 1))
        for key, (axis, deg) in moves.items():
            pb = ob.pose.bones[names[key]]
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = Matrix.Rotation(math.radians(deg * w), 3, axis).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=f)


def _world_dir(ob, bone):
    pb = ob.pose.bones[bone]
    return ((ob.matrix_world @ pb.tail) - (ob.matrix_world @ pb.head)).normalized()


def test_roles():
    m = _m()
    cases = {"Bip01_L_Thigh": ("thigh", "L"), "Bip01_R_HorseLink": ("horselink", "R"), "thigh_fk.L": ("thigh", "L"),
             "DEF-forearm.R": ("forearm", "R"), "mixamorig:LeftUpLeg": ("thigh", "L"), "BN_Tail_03": ("tail", "C"),
             "Bip01_Spine0_Tail2": ("tail", "C"), "BN_Wing_L_04": ("wing", "L"), "Bip01_Head1_Jaw": ("jaw", "C"),
             "BN_Ear_R": ("ear", "R"), "BN_Beard_L": (None, "L"), "spine.003": ("spine", "C"),
             "Bip01_R_Calf": ("shin", "R"), "mixamorig:RightForeArm": ("forearm", "R")}
    bad = {n: [m["_role"](n), m["_side"](n), exp] for n, exp in cases.items()
           if (m["_role"](n), m["_side"](n)) != exp}
    return {"pass": not bad, "mismatch": bad}


def test_auto_map():
    m = _m()
    src = _armature(PREFIX + "map_src", SRC_NAMES)
    tgt = _armature(PREFIX + "map_tgt", TGT_NAMES)
    got = m["auto_map"](src, tgt)
    want = {TGT_NAMES[k]: SRC_NAMES[k] for k in BIPED}
    diff = {t: [got.get(t), s] for t, s in want.items() if got.get(t) != s}
    return {"pass": not diff, "map": got, "diff": diff}


def test_retarget_synthetic():
    m = _m()
    src = _armature(PREFIX + "src", SRC_NAMES)
    _animate(src, SRC_NAMES)
    # different names, bone rolls, facing (+90 deg) and scale: the motion must still match in world space
    tgt = _armature(PREFIX + "tgt", TGT_NAMES, roll=0.6, rot_z=90.0, scale=2.0)
    res = m["run"]({"mode": "retarget", "source": src.name, "target": tgt.name, "action": PREFIX + "tgt_action"})
    if not res.get("ok"):
        return {"pass": False, "result": res}
    ry = Matrix.Rotation(math.radians(res["yaw_deg"]), 3, "Z")
    worst = 0.0
    sc = bpy.context.scene
    for f in (1, 4, 6, 10):
        sc.frame_set(f)
        for k in BIPED:
            a = ry @ _world_dir(src, SRC_NAMES[k])
            b = _world_dir(tgt, TGT_NAMES[k])
            worst = max(worst, math.degrees(a.angle(b)))
    ok = abs(res["yaw_deg"] - 90.0) < 1.0 and worst < 1.0 and res["error_deg"]["max"] < 1.0 and res["mapped"] == 8
    return {"pass": ok, "yaw_deg": res["yaw_deg"], "world_dir_err_deg": round(worst, 3),
            "error_deg": res["error_deg"], "action": res["action"]}


def test_retarget_offset_frames():
    m = _m()
    src = _armature(PREFIX + "off_src", SRC_NAMES)
    _animate(src, SRC_NAMES)
    tgt = _armature(PREFIX + "off_tgt", TGT_NAMES)
    res = m["run"]({"mode": "retarget", "source": src.name, "target": tgt.name, "frame_start": 101,
                    "action": PREFIX + "off_action"})
    if not res.get("ok"):
        return {"pass": False, "result": res}
    sc = bpy.context.scene
    sc.frame_set(5)
    a = _world_dir(src, SRC_NAMES["L_Calf"])
    sc.frame_set(105)
    b = _world_dir(tgt, TGT_NAMES["L_Calf"])
    err = math.degrees(a.angle(b))
    return {"pass": res["frames"] == [101, 110] and err < 1.0, "frames": res["frames"], "err_deg": round(err, 3)}


BVH = """HIERARCHY
ROOT Hips
{
\tOFFSET 0.0 1.0 0.0
\tCHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
\tJOINT Spine
\t{
\t\tOFFSET 0.0 0.3 0.0
\t\tCHANNELS 3 Zrotation Yrotation Xrotation
\t\tEnd Site
\t\t{
\t\t\tOFFSET 0.0 0.3 0.0
\t\t}
\t}
}
MOTION
Frames: 3
Frame Time: 0.066667
0 0 0 0 0 0 0 0 0
0 0 0 0 0 0 10 0 0
0 0 0 0 0 0 20 0 0
"""


def test_import_bvh():
    m = _m()
    path = os.path.join(_tmpdir(), "tiny.bvh")
    with open(path, "w") as f:
        f.write(BVH)
    res = m["run"]({"mode": "import", "bvh": path, "name": PREFIX + "tiny"})
    if not res.get("ok"):
        return {"pass": False, "result": res}
    imp = res["imported"]
    ob = bpy.data.objects.get(imp["armature"])
    ok = ob is not None and imp["bones"] == 2 and imp["frames"][0] == bpy.context.scene.frame_start
    return {"pass": ok, "imported": imp}


def test_status_log():
    m = _m()
    d = _tmpdir()
    st0 = m["read_status"](d)["state"]
    with open(os.path.join(d, "mocap.log"), "w") as f:
        f.write("PROGRESS frames\nERROR rig 'Unicorn' has no reference pose\n")
    st1 = m["read_status"](d)
    with open(os.path.join(d, "mocap.log"), "w") as f:
        f.write('PROGRESS p2r\nRESULT {"rig": "Cat", "files": {"bvh": "/x.bvh"}}\n')
    st2 = m["read_status"](d)
    ok = st0 == "missing" and st1["state"] == "failed" and "Unicorn" in st1["error"] and \
        st2["state"] == "done" and st2["files"]["bvh"] == "/x.bvh"
    return {"pass": ok, "states": [st0, st1["state"], st2["state"]]}


def test_missing_install_errors():
    m = _m()
    res = m["run"]({"mode": "probe", "home": _tmpdir()})
    return {"pass": bool((not res["ok"]) and "install" in res and res.get("missing")), "missing": res.get("missing")}


def test_real_capture(enabled=False):
    m = _m()
    info = m["probe"]({"check_torch": False})
    clip = os.path.join(info["home"], "demo", "data", "inputs", "nbg_wild", "Cat#Cat_Act0.mp4")
    if not info["available"] or not os.path.isfile(clip):
        return {"pass": True, "skipped": "MoCapAnything or its demo clip not installed"}
    if not enabled:
        return {"pass": True, "skipped": "slow (minutes on CPU): run with {'real': True}"}
    out = _tmpdir()
    res = m["run"]({"mode": "apply", "video": clip, "rig": "Cat", "out_dir": out, "duration": 2.0,
                    "name": PREFIX + "cat", "timeout": 3600})
    if not res.get("ok"):
        return {"pass": False, "result": res}
    cap, imp = res["capture"], res["imported"]
    ok = os.path.isfile(cap["files"]["bvh"]) and imp["bones"] >= 30 and imp["frames"][1] - imp["frames"][0] >= 20
    return {"pass": ok, "seconds": cap.get("seconds"), "device": cap.get("device"), "frames": cap.get("frames"),
            "imported": imp}


TESTS = {
    "roles": test_roles,
    "auto_map": test_auto_map,
    "retarget_synthetic": test_retarget_synthetic,
    "retarget_offset_frames": test_retarget_offset_frames,
    "import_bvh": test_import_bvh,
    "status_log": test_status_log,
    "missing_install_errors": test_missing_install_errors,
    "real_capture": test_real_capture,
}


def _cleanup(had_mocap):
    for ob in [o for o in bpy.data.objects if o.name.startswith(PREFIX) or o.name.startswith("MC_" + PREFIX)]:
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.armatures.remove(data)
    for act in [a for a in bpy.data.actions if a.name.startswith(PREFIX) or f"_{PREFIX}" in a.name]:
        bpy.data.actions.remove(act)
    coll = bpy.data.collections.get("MOCAP")
    if coll is not None and not had_mocap and not coll.objects:
        bpy.data.collections.remove(coll)
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)


def run(args=None):
    args = args or {}
    only = args.get("only") or list(TESTS)
    sc = bpy.context.scene
    frame = sc.frame_current
    had_mocap = "MOCAP" in bpy.data.collections
    out = {}
    try:
        for name in only:
            try:
                out[name] = test_real_capture(bool(args.get("real"))) if name == "real_capture" else TESTS[name]()
            except Exception:
                out[name] = {"pass": False, "trace": traceback.format_exc()}
            if bpy.context.object and bpy.context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        sc.frame_set(frame)
        if not args.get("keep"):
            _cleanup(had_mocap)
    return {"all_pass": all(v.get("pass") for v in out.values()), "results": out,
            "skipped": [k for k, v in out.items() if v.get("skipped")]}
