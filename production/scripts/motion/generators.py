"""Parameterised motion generators driven by motion-brief.yaml (runs inside Blender via MCP).

Guide: .claude/skills/animation/references/reference-driven-motion.md

``run(args)`` with:
    generator  (str, required)   see GENERATORS below
    target     (str, required)   armature (bone generators) or object (object generators)
    action     (str, required)   action name to create/replace, e.g. "AN_walk"
    bones      (dict)            role → pose-bone name, e.g. {"foot_fl": "foot_ik.L", "body": "torso", "tail": [..]}
    fps        (int, 30)
    cycle_s    (float)           loop length / clip length
    loop       (bool, True)      last frame equals first frame
    params     (dict)            generator parameters (from the brief)
    secondary  (list[dict])      follow-through chains: [{"bones": [...], "amp_deg": 10, "delay_frames": 2, "axis": "Z"}]
    keys       (list[dict])      for "pose_keys": [{"t": 0.0, "bones": {"name": {"rot": [x,y,z], "loc": [x,y,z]}}}]
    ikfk       (dict)            {"upper_arm_parent.L": 0.0, ...} key Rigify IK_FK switches on the first and last frame
                                 (0 = IK, 1 = FK). Every clip of a Rigify rig should key them: an unkeyed clip
                                 inherits whatever value the previous clip left, so Blender and the export disagree.
    append     (bool, False)     key into the existing action instead of replacing it — layer several generators
                                 in one clip (idle = biped_idle + tail_wag + head_tilt); use distinct bones per layer

Bone generators key CONTROL bones (IK feet, FK chains). The glTF exporter samples the evaluated pose,
so deform bones receive the motion; optionally bake with bake_to_deform().
All rotations in degrees; locations in metres in the bone's local space. Axis parameters (forward_axis, up_axis,
pitch_axis, head_axis, breath_axis, sway_axis, axis) name the CONTROL bone's local axes: read them from the rig
(e.g. Rigify torso/IK controls are world-aligned, so a +X-facing rig pitches around "Y").
"""
import importlib.util
import math
import os
import sys

import bpy
from mathutils import Euler, Vector


def _load_common():
    here = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
    path = os.path.normpath(os.path.join(here, "..", "blender", "u3d_common.py"))
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
AX = {"X": 0, "Y": 1, "Z": 2}


# ----------------------------------------------------------------- keying helpers
def key_rot(owner, deg_xyz, frame):
    e = Euler([math.radians(d) for d in deg_xyz])
    mode = getattr(owner, "rotation_mode", "XYZ")
    if mode == "QUATERNION":
        owner.rotation_quaternion = e.to_quaternion()
        owner.keyframe_insert("rotation_quaternion", frame=frame)
    elif mode == "AXIS_ANGLE":
        ax, ang = e.to_quaternion().to_axis_angle()
        owner.rotation_axis_angle = (ang, ax.x, ax.y, ax.z)
        owner.keyframe_insert("rotation_axis_angle", frame=frame)
    else:
        owner.rotation_euler = e
        owner.keyframe_insert("rotation_euler", frame=frame)


def key_loc(owner, loc, frame):
    owner.location = Vector(loc)
    owner.keyframe_insert("location", frame=frame)


def key_scale(owner, s, frame):
    owner.scale = Vector((s, s, s)) if isinstance(s, (int, float)) else Vector(s)
    owner.keyframe_insert("scale", frame=frame)


def axis_vec(axis, amount):
    v = [0.0, 0.0, 0.0]
    v[AX[axis]] = amount
    return v


def frames_for(fps, seconds, loop):
    n = max(2, int(round(fps * seconds)))
    return list(range(1, n + 2)) if loop else list(range(1, n + 1))


def ease(u, kind="inout"):
    if kind == "in":
        return u * u
    if kind == "out":
        return 1 - (1 - u) ** 2
    if kind == "linear":
        return u
    return 3 * u * u - 2 * u * u * u


# ----------------------------------------------------------------- generators
def quadruped_walk(rig, b, p, fps, cyc, loop):
    """Lateral-sequence walk in place. Feet slide back during stance, lift and swing forward."""
    stride, lift = p.get("stride", 0.3), p.get("lift", 0.05)
    duty = p.get("duty", 0.6)
    phases = p.get("phases", {"foot_hl": 0.0, "foot_fl": 0.25, "foot_hr": 0.5, "foot_fr": 0.75})
    fwd = p.get("forward_axis", "Y")
    sign = -1.0 if p.get("forward_negative", True) else 1.0
    bounce, pitch = p.get("bounce", 0.01), p.get("body_pitch_deg", 2.0)
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    for i, fr in enumerate(frames):
        u = (i % n) / n
        for role, ph in phases.items():
            name = b.get(role)
            if not name:
                continue
            pb = rig.pose.bones[name]
            s = (u + ph) % 1.0
            if s < duty:  # stance: move back
                k = s / duty
                along, up = stride * (0.5 - k), 0.0
            else:  # swing: arc forward
                k = (s - duty) / (1 - duty)
                along, up = stride * (-0.5 + ease(k)), lift * math.sin(math.pi * k)
            loc = [0.0, 0.0, 0.0]
            loc[AX[fwd]] = sign * along
            loc[AX[p.get("up_axis", "Z")]] = up  # axes are the control bone's LOCAL axes; check on the rig
            key_loc(pb, loc, fr)
        if b.get("body"):
            pb = rig.pose.bones[b["body"]]
            key_loc(pb, [0, 0, bounce * math.sin(4 * math.pi * u)], fr)
            key_rot(pb, axis_vec(p.get("pitch_axis", "X"), pitch * math.sin(2 * math.pi * u)), fr)
        if b.get("head"):
            key_rot(rig.pose.bones[b["head"]],
                    axis_vec(p.get("head_axis", "X"), p.get("head_bob_deg", 3) * math.sin(4 * math.pi * u + 0.5)), fr)


def _signed_angle(u, v, axis):
    """Angle (radians) from u to v around axis (all mathutils Vectors, u and v ⟂ axis)."""
    return math.atan2(u.cross(v).dot(axis), u.dot(v))


def _two_bone_plane(S, E, W, T, lat):
    """Planar two-bone IK: joints S→E→W, target T for W, bend kept on the rest side.
    Returns (new E, clamped T). All vectors lie in the plane perpendicular to `lat`."""
    a, b = (E - S).length, (W - E).length
    d = T - S
    c = max(min(d.length, a + b - 1e-6), abs(a - b) + 1e-6)
    d = d.normalized()
    T = S + d * c
    cos_al = max(-1.0, min(1.0, (a * a + c * c - b * b) / (2 * a * c)))
    al = math.acos(cos_al)
    side = 1.0 if _signed_angle(W - S, E - S, lat) >= 0 else -1.0   # rest bend side
    from mathutils import Matrix
    dir_u = Matrix.Rotation(side * al, 3, lat) @ d
    return S + dir_u * a, T


def quadruped_walk_fk(rig, b, p, fps, cyc, loop):
    """Lateral-sequence walk keyed on FK controls with planar two-bone IK per leg.

    For short / stylised legs where Rigify IK picks a different bend plane per frame (knees flip, paws twist,
    legs cross). Each leg is solved in its sagittal plane, keeping the rest bend direction; the paw keeps its
    rest orientation (plus `paw_curl_deg` during swing), so contacts stay planted with root motion.

    bones: {"leg_fl": [upper_fk, lower_fk, paw_fk], "leg_fr": [...], "leg_hl": [...], "leg_hr": [...],
            "body": torso, "head": head, "ikfk": ["upper_arm_parent.L", ...]}  (IK_FK keyed to 1.0 = FK)
    params: as quadruped_walk (stride, lift, duty, phases with keys foot_fl/fr/hl/hr, bounce, body_pitch_deg,
            pitch_axis, head_bob_deg, head_axis) + forward_axis ("X", "-X", "Y", "-Y" in rig space), paw_curl_deg,
            paw_curl_sign (+1/-1: flip if the paw curls upward instead of tucking during swing).
    """
    stride, lift, duty = p.get("stride", 0.3), p.get("lift", 0.05), p.get("duty", 0.6)
    phases = p.get("phases", {"foot_hl": 0.0, "foot_fl": 0.25, "foot_hr": 0.5, "foot_fr": 0.75})
    fa = p.get("forward_axis", "X")
    F = Vector(axis_vec(fa.strip("-"), -1.0 if fa.startswith("-") else 1.0))
    U = Vector((0.0, 0.0, 1.0))
    lat = U.cross(F)
    curl = math.radians(p.get("paw_curl_deg", 15.0))
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    legs = {}
    for role, key in (("leg_fl", "foot_fl"), ("leg_fr", "foot_fr"), ("leg_hl", "foot_hl"), ("leg_hr", "foot_hr")):
        names = b.get(role)
        if not names:
            continue
        pbs = [rig.pose.bones[nm] for nm in names]
        S, E, W = (pb.bone.head_local.copy() for pb in pbs)
        # local X of each control in armature space: sign of its rotation relative to `lat`
        signs = [1.0 if pb.bone.matrix_local.to_3x3().col[0].dot(lat) >= 0 else -1.0 for pb in pbs]
        legs[role] = (pbs, S, E, W, signs, phases.get(key, 0.0))
    for nm in b.get("ikfk", []):
        pb = rig.pose.bones[nm]
        for fr in (frames[0], frames[-1]):
            pb["IK_FK"] = 1.0
            pb.keyframe_insert('["IK_FK"]', frame=fr)
    from mathutils import Matrix
    body = rig.pose.bones[b["body"]] if b.get("body") else None
    for i, fr in enumerate(frames):
        u = (i % n) / n
        bounce = p.get("bounce", 0.01) * math.sin(4 * math.pi * u)
        pitch = p.get("body_pitch_deg", 2.0) * math.sin(2 * math.pi * u)
        # body pose as a rigid transform in armature space; paw targets stay on the ground, so they are
        # expressed in the moving body frame before solving (no sinking or floating while the body bobs)
        Mb = Matrix.Identity(4)
        body_pitch_lat = 0.0
        if body is not None:
            R0 = body.bone.matrix_local.to_3x3()
            P = body.bone.head_local
            ax = R0 @ Vector(axis_vec(p.get("pitch_axis", "X"), 1.0))
            Mb = (Matrix.Translation(P + R0 @ Vector((0.0, 0.0, bounce))) @ Matrix.Rotation(math.radians(pitch), 4, ax)
                  @ Matrix.Translation(-P))
            body_pitch_lat = math.radians(pitch) * (1.0 if ax.dot(lat) >= 0 else -1.0)
            key_loc(body, [0, 0, bounce], fr)
            key_rot(body, axis_vec(p.get("pitch_axis", "X"), pitch), fr)
        Mb_inv = Mb.inverted()
        for role, (pbs, S, E, W, signs, ph) in legs.items():
            s_ = (u + ph) % 1.0
            if s_ < duty:
                k = s_ / duty
                along, up, c = stride * (0.5 - k), 0.0, 0.0
            else:
                k = (s_ - duty) / (1 - duty)
                along, up = stride * (-0.5 + ease(k)), lift * math.sin(math.pi * k)
                c = curl * math.sin(math.pi * k)
            T = Mb_inv @ (W + F * along + U * up)
            E2, T = _two_bone_plane(S, E, W, T, lat)
            th_u = _signed_angle(E - S, E2 - S, lat)
            th_l_world = _signed_angle(W - E, T - E2, lat)
            th_l = th_l_world - th_u
            th_p = -th_l_world - body_pitch_lat + c * p.get("paw_curl_sign", 1.0)
            for pb, ang, sg in zip(pbs, (th_u, th_l, th_p), signs):
                key_rot(pb, [math.degrees(sg * ang), 0.0, 0.0], fr)
        if b.get("head"):
            key_rot(rig.pose.bones[b["head"]],
                    axis_vec(p.get("head_axis", "X"), p.get("head_bob_deg", 3) * math.sin(4 * math.pi * u + 0.5)), fr)


def quadruped_trot(rig, b, p, fps, cyc, loop):
    p = dict(p)
    p.setdefault("phases", {"foot_hl": 0.0, "foot_fr": 0.0, "foot_hr": 0.5, "foot_fl": 0.5})
    p.setdefault("duty", 0.45)
    quadruped_walk(rig, b, p, fps, cyc, loop)


def biped_walk(rig, b, p, fps, cyc, loop):
    p = dict(p)
    p.setdefault("phases", {"foot_l": 0.0, "foot_r": 0.5})
    p.setdefault("duty", 0.6)
    quadruped_walk(rig, b, p, fps, cyc, loop)
    swing = p.get("arm_swing_deg", 15)
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    for i, fr in enumerate(frames):
        u = (i % n) / n
        for role, ph in (("arm_l", 0.5), ("arm_r", 0.0)):
            if b.get(role):
                key_rot(rig.pose.bones[b[role]], [swing * math.sin(2 * math.pi * (u + ph)), 0, 0], fr)


def biped_idle(rig, b, p, fps, cyc, loop):
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    for i, fr in enumerate(frames):
        u = (i % n) / n
        if b.get("chest"):
            key_rot(rig.pose.bones[b["chest"]],
                    axis_vec(p.get("breath_axis", "X"), p.get("breath_deg", 1.5) * math.sin(2 * math.pi * u)), fr)
        if b.get("body"):
            key_loc(rig.pose.bones[b["body"]], axis_vec(p.get("sway_axis", "X"), p.get("sway", 0.005) * math.sin(2 * math.pi * u)), fr)


def oscillate(rig, bone_names, axis, amp, fps, cyc, loop, phase_step=0.0, cycles=1.0):
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    for k, name in enumerate(bone_names):
        pb = rig.pose.bones[name]
        for i, fr in enumerate(frames):
            u = (i % n) / n
            key_rot(pb, axis_vec(axis, amp * math.sin(2 * math.pi * (cycles * u - k * phase_step))), fr)


def tail_wag(rig, b, p, fps, cyc, loop):
    chain = b.get("tail", [])
    oscillate(rig, chain, p.get("axis", "Z"), p.get("amp_deg", 20), fps, cyc, loop,
              phase_step=p.get("phase_step", 0.08), cycles=p.get("wags_per_cycle", 2))


def wing_flap(rig, b, p, fps, cyc, loop):
    amp, axis = p.get("amp_deg", 20), p.get("axis", "Y")
    cycles = p.get("flaps_per_cycle", 2)
    for side, sgn in (("wing_l", 1), ("wing_r", -1)):
        names = b.get(side, [])
        names = names if isinstance(names, list) else [names]
        frames = frames_for(fps, cyc, loop)
        n = len(frames) - (1 if loop else 0)
        for k, name in enumerate(names):
            pb = rig.pose.bones[name]
            for i, fr in enumerate(frames):
                u = (i % n) / n
                key_rot(pb, axis_vec(axis, sgn * amp * (0.5 + 0.5 * math.sin(2 * math.pi * cycles * u - k * 0.3))), fr)


def head_tilt(rig, b, p, fps, cyc, loop):
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    pb = rig.pose.bones[b["head"]]
    for i, fr in enumerate(frames):
        u = (i % n) / n
        w = ease(min(1, 4 * u), "inout") if u < 0.5 else ease(max(0, 2 - 2 * u), "inout")
        key_rot(pb, [0, p.get("tilt_deg", 20) * w, p.get("turn_deg", 0) * w], fr)


def perch_bob(rig, b, p, fps, cyc, loop):
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - (1 if loop else 0)
    for i, fr in enumerate(frames):
        u = (i % n) / n
        if b.get("body"):
            key_loc(rig.pose.bones[b["body"]], [0, 0, -abs(p.get("bob", 0.01) * math.sin(math.pi * 2 * u))], fr)
        if b.get("head"):
            key_rot(rig.pose.bones[b["head"]], [p.get("nod_deg", 6) * math.sin(2 * math.pi * u), 0, 0], fr)


def pose_keys(rig, b, p, fps, cyc, loop, keys=None):
    for k in keys or []:
        fr = 1 + round(k["t"] * fps)
        for name, tr in k["bones"].items():
            pb = rig.pose.bones[name]
            if "rot" in tr:
                key_rot(pb, tr["rot"], fr)
            if "loc" in tr:
                key_loc(pb, tr["loc"], fr)


# object generators (static / articulated objects)
def turntable(ob, b, p, fps, cyc, loop):
    frames = frames_for(fps, cyc, loop)
    n = len(frames) - 1
    for i, fr in enumerate(frames):
        key_rot(ob, axis_vec(p.get("axis", "Z"), 360.0 * i / n), fr)
    _linear(ob)


def hinge_open(ob, b, p, fps, cyc, loop):
    ang, axis = p.get("angle_deg", 100), p.get("axis", "X")
    overshoot = p.get("overshoot_deg", 4)
    frames = frames_for(fps, cyc, False)
    n = len(frames) - 1
    for i, fr in enumerate(frames):
        u = i / n
        a = ang * ease(u, p.get("easing", "out"))
        if overshoot and u > 0.7:
            a += overshoot * math.sin(math.pi * (u - 0.7) / 0.3) * (1 - u) / 0.3
        key_rot(ob, axis_vec(axis, a), fr)


def bounce_in(ob, b, p, fps, cyc, loop):
    frames = frames_for(fps, cyc, False)
    n = len(frames) - 1
    bounces = p.get("bounces", 2)
    for i, fr in enumerate(frames):
        u = i / n
        s = 1 - math.exp(-6 * u) * math.cos(2 * math.pi * bounces * u)
        key_scale(ob, max(0.0, s), fr)


def _linear(ob):
    ad = ob.animation_data
    if ad and ad.action:
        for fc in C.action_fcurves(ad.action, getattr(ad, "action_slot", None)):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


GENERATORS = {
    "quadruped_walk": quadruped_walk, "quadruped_walk_fk": quadruped_walk_fk, "quadruped_trot": quadruped_trot, "biped_walk": biped_walk,
    "biped_idle": biped_idle, "tail_wag": tail_wag, "wing_flap": wing_flap, "head_tilt": head_tilt,
    "perch_bob": perch_bob, "pose_keys": pose_keys,
    "turntable": turntable, "hinge_open": hinge_open, "bounce_in": bounce_in,
}
OBJECT_GENERATORS = {"turntable", "hinge_open", "bounce_in"}


def follow_through(rig, chains, fps, cyc, loop):
    for ch in chains or []:
        oscillate(rig, ch["bones"], ch.get("axis", "Z"), ch.get("amp_deg", 8), fps, cyc, loop,
                  phase_step=ch.get("delay_frames", 2) / max(1, fps * cyc), cycles=ch.get("cycles", 1))


def bake_to_deform(rig, frame_start, frame_end):
    """Optional: bake visual pose of deform bones (keeps controls)."""
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for pb in rig.pose.bones:
        pb.bone.select = pb.bone.use_deform
    bpy.ops.nla.bake(frame_start=frame_start, frame_end=frame_end, only_selected=True, visual_keying=True,
                     clear_constraints=False, use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")


def run(args: dict) -> dict:
    gen = args.get("generator")
    if gen not in GENERATORS:
        return C.result_error(f"unknown generator {gen}", available=sorted(GENERATORS))
    target = bpy.data.objects.get(args.get("target", ""))
    if target is None:
        return C.result_error("target object not found")
    fps = int(args.get("fps", 30))
    cyc = float(args.get("cycle_s", 1.0))
    loop = bool(args.get("loop", gen not in ("hinge_open", "bounce_in")))
    bpy.context.scene.render.fps = fps
    ad = target.animation_data or target.animation_data_create()
    name = args.get("action") or f"AN_{gen}"
    old = bpy.data.actions.get(name)
    if old and args.get("append"):
        ad.action = old
    else:
        if old:
            bpy.data.actions.remove(old)
        ad.action = bpy.data.actions.new(name)
    fn = GENERATORS[gen]
    if gen == "pose_keys":
        fn(target, args.get("bones", {}), args.get("params", {}), fps, cyc, loop, keys=args.get("keys"))
    else:
        fn(target, args.get("bones", {}), args.get("params", {}), fps, cyc, loop)
    if gen not in OBJECT_GENERATORS:
        follow_through(target, args.get("secondary"), fps, cyc, loop)
        if args.get("ikfk"):
            f_last = frames_for(fps, cyc, loop)[-1]
            for nm, val in args["ikfk"].items():
                pb = target.pose.bones[nm]
                for fr in (1, f_last):
                    pb["IK_FK"] = float(val)
                    pb.keyframe_insert('["IK_FK"]', frame=fr)
    f0, f1 = ad.action.frame_range
    ad.action.use_fake_user = True
    if args.get("bake_deform") and target.type == "ARMATURE":
        bake_to_deform(target, int(f0), int(f1))
    return C.result_ok(action=ad.action.name, frame_range=[f0, f1], fps=fps, generator=gen)
