"""Motion quality measures for gate G5 — what a contact sheet hides, measured on the evaluated rig and skin.

Complements anim_check.py (clips present, seam angle, foot slide) and deform_check.py (folds, flips).
The measures and targets follow blender-kiln's measured animation rules (MIT,
`references/animation.md` rules 3, 5, 6 and § Humanoid presets): each one is a cycle that looked
fine on a still and wrong in motion. Implemented here from scratch for any rig — names are found by
pattern (Rigify DEF-, Mixamo, kiln) or given in `limbs`.

args:
    armature     (str, required)
    clips        (list[str])        action names ("AN_" optional). Default: the active action
    mesh         (str)              skinned mesh (default: the largest mesh deformed by the armature)
    limbs        (list[dict])       [{"name": "leg.L", "start": "DEF-thigh.L", "end": "DEF-foot.L",
                                      "knee": "DEF-shin.L", "foot": "DEF-foot.L"}]. Default: found by name —
                                    an end bone (foot/hand/paw/toe-less) and its upper ancestor
                                    (thigh/upper_arm/UpLeg/Arm). `knee` is the first bone of the lower segment.
    loops        (list[str])        clips that must loop (seam measured); default: every clip
    floor_z      (float)            world floor height; default: lowest skin vertex at rest
    every        (int, 1)           sample every Nth frame for the skin measures (heavy meshes)
    contact_eps  (float, 0.01)      metres above a foot's lowest height that still count as standing
    thresholds   (dict)             override the defaults below (null disables one)
    project_dir  (str)              write reports/motion-qa.json

Measures per clip (defaults are failing thresholds):
    reach_max          largest limb extension, start-to-end distance / rest chain length   (> 0.95 locks
                       the leg straight and reads as too long — kiln rule 3)
    joint_pops         frames where a knee/elbow bend spikes >= 8 deg against BOTH neighbours (one-frame
                       snap straight or bent — read as trembling knees)                           (> 0)
    jitter_deg         worst out-and-back turn of any deform bone across one frame (t-1 -> t -> t+1),
                       relative to its parent: catches popping keys and constraint flips           (> 8)
    under_floor_mm     deepest skin vertex below the floor on any sampled frame                    (> 5)
    frames_below_pct   sampled frames with skin more than 5 mm under the floor                      (info)
    standing_pitch_deg median pitch of each foot bone off its rest pitch while it stands (sole flat at
                       rest = 0; tiptoeing feet read wrong)                                          (> 5
                       for limbs named leg/foot only; null for paws by default — they roll on purpose)
    seam_ratio         pose step across the loop point / mean frame step; with a closing key equal to
                       the first (rule 5) the step measured is last-1 -> first                     (> 1.2)
    closing_key        whether the last frame equals the first (glTF plays the closing key)
"""
from __future__ import annotations

import fnmatch
import importlib.util
import math
import os
import re
import sys

import bpy
import numpy as np


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

DEFAULTS = {"reach_max": 0.95, "joint_pops": 0, "jitter_deg": 8.0, "under_floor_mm": 5.0,
            "standing_pitch_deg": 5.0, "seam_ratio": 1.2}
POP_DEG = 8.0
_END = re.compile(r"(foot|hand|paw|hoof)(?!.*(toe|finger|thumb|ik|fk|tweak|heel))", re.I)
_START = re.compile(r"(thigh|upper_?arm|upleg|^(left|right)?arm$|humerus|femur)", re.I)


def _core(name):
    n = re.sub(r"^(DEF|ORG|MCH|mixamorig)[-_:]", "", name)
    return re.sub(r"\.\d{3}$", "", n)


def _side(name):
    m = re.search(r"([._-](L|R|l|r)(\.\d+)?$)|^(Left|Right)", name)
    return m.group(0) if m else ""


def find_limbs(arm):
    """Two-segment limbs among the deform bones, by name: end bone + its upper ancestor."""
    bones = arm.data.bones
    deform = [b for b in bones if b.use_deform]
    limbs = []
    for b in deform:
        core = _core(b.name)
        if not _END.search(core) or re.search(r"\.\d{3}$", b.name):
            continue
        chain, a = [], b.parent
        while a is not None:
            chain.append(a)
            if a.use_deform and _START.search(_core(a.name)) and not re.search(r"\.\d{3}$", a.name):
                break
            a = a.parent
        else:
            continue
        chain.reverse()                       # start ... bone before the end
        deform_chain = [x for x in chain if x.use_deform]
        if len(deform_chain) < 2:
            continue
        start = deform_chain[0]
        start_core = _core(start.name)
        knee = next((x for x in deform_chain[1:] if _core(x.name) != start_core), deform_chain[-1])
        kind = "leg" if re.search(r"thigh|upleg|femur|foot|paw|hoof", core + start.name, re.I) else "arm"
        limbs.append({"name": f"{kind}{_side(b.name)}", "start": start.name, "knee": knee.name,
                      "end": b.name, "foot": b.name, "chain": [x.name for x in deform_chain], "kind": kind,
                      "paw": bool(re.search(r"paw|hoof|hand", b.name, re.I) and kind == "leg")})
    return limbs


def _chain_length(arm, limb):
    bones = arm.data.bones
    chain = limb.get("chain")
    if not chain:
        chain, a = [], bones[limb["end"]].parent
        while a is not None and a.name != limb["start"]:
            chain.append(a.name)
            a = a.parent
        chain.append(limb["start"])
        chain.reverse()                       # start first
    head = lambda n: bones[n].head_local
    pts = [head(n) for n in chain] + [head(limb["end"])]
    # rest length along the joints (bones with twist segments share joints)
    return sum((pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)) or 1e-6


def _skin(arm, name):
    if name:
        return bpy.data.objects.get(name)
    cands = [o for o in bpy.data.objects if o.type == "MESH" and o.find_armature() == arm
             and bpy.context.scene in o.users_scene]
    return max(cands, key=lambda o: len(o.data.vertices)) if cands else None


def _assign(arm, act):
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if getattr(act, "slots", None) and len(act.slots):
        ad.action_slot = act.slots[0]


def _rel_quats(arm, names):
    out = []
    for n in names:
        pb = arm.pose.bones[n]
        q = pb.matrix.to_quaternion()
        if pb.parent is not None:
            q = pb.parent.matrix.to_quaternion().inverted() @ q
        out.append(q)
    return out


def _qangle(a, b):
    return math.degrees(a.rotation_difference(b).angle)


def _pose_dist(P, i, j):
    return float(np.mean([_qangle(P[i][k], P[j][k]) for k in range(len(P[i]))]))


def _pitch(v):
    return math.degrees(math.asin(max(-1.0, min(1.0, v.normalized().z))))


def measure_clip(arm, act, skin, limbs, args, floor_z):
    sc = bpy.context.scene
    _assign(arm, act)
    f0, f1 = (int(round(x)) for x in act.frame_range)
    frames = list(range(f0, f1 + 1))
    every = max(1, int(args.get("every", 1)))
    mw = arm.matrix_world
    deform = [b.name for b in arm.data.bones if b.use_deform]
    P, J, E, S, F = [], [], [], [], []
    under, below_frames, sampled = 0.0, 0, 0
    for n, fr in enumerate(frames):
        sc.frame_set(fr)
        P.append(_rel_quats(arm, deform))
        row_j, row_e, row_s, row_f = [], [], [], []
        for lb in limbs:
            pb = arm.pose.bones
            s = mw @ pb[lb["start"]].head
            k = mw @ pb[lb["knee"]].head
            e = mw @ pb[lb["end"]].head
            row_e.append((e - s).length)
            u, w = (k - s), (e - k)
            row_j.append(math.degrees(u.angle(w)) if u.length > 1e-6 and w.length > 1e-6 else 0.0)
            ft = pb[lb["foot"]]
            row_s.append((mw.to_3x3() @ (ft.tail - ft.head)))
            row_f.append(e.z)
        J.append(row_j); E.append(row_e); S.append(row_s); F.append(row_f)
        if skin is not None and n % every == 0:
            co = C.evaluated_vertex_positions(skin)
            d = (floor_z - co[:, 2].min()) * 1000.0
            under = max(under, d)
            below_frames += int(d > 5.0)
            sampled += 1
    m = {"action": act.name, "frame_range": [f0, f1], "frames": len(frames)}
    # limbs
    per_limb = {}
    for li, lb in enumerate(limbs):
        L = _chain_length(arm, lb)
        reach = [E[t][li] / L for t in range(len(frames))]
        bend = [J[t][li] for t in range(len(frames))]
        pops = [frames[t] for t in range(1, len(frames) - 1)
                if (bend[t] - bend[t - 1] >= POP_DEG and bend[t] - bend[t + 1] >= POP_DEG)
                or (bend[t - 1] - bend[t] >= POP_DEG and bend[t + 1] - bend[t] >= POP_DEG)]
        info = {"reach_max": round(max(reach), 3), "reach_mean": round(float(np.mean(reach)), 3),
                "joint_pops": len(pops), "pop_frames": pops[:12]}
        heights = np.array([F[t][li] for t in range(len(frames))])
        stand = heights <= heights.min() + float(args.get("contact_eps", 0.01))
        rest_v = arm.data.bones[lb["foot"]].tail_local - arm.data.bones[lb["foot"]].head_local
        rest_pitch = _pitch(mw.to_3x3() @ rest_v)
        pitches = [abs(_pitch(S[t][li]) - rest_pitch) for t in range(len(frames)) if stand[t]]
        info["standing_pitch_deg"] = round(float(np.median(pitches)), 2) if pitches else None
        info["standing_frames_pct"] = round(100.0 * stand.mean(), 1)
        info["kind"] = lb.get("kind")
        info["paw"] = lb.get("paw", False)
        per_limb[lb["name"]] = info
    m["limbs"] = per_limb
    # jitter: out-and-back turn across one frame, any deform bone
    worst, where = 0.0, None
    for t in range(1, len(P) - 1):
        for k, bn in enumerate(deform):
            d = _qangle(P[t - 1][k], P[t][k]) + _qangle(P[t][k], P[t + 1][k]) - _qangle(P[t - 1][k], P[t + 1][k])
            if d / 2 > worst:
                worst, where = d / 2, (frames[t], bn)
    m["jitter_deg"] = round(worst, 2)
    m["jitter_at"] = where
    # seam
    steps = [_pose_dist(P, t, t + 1) for t in range(len(P) - 1)]
    mean_step = float(np.mean(steps)) if steps else 0.0
    closing = _pose_dist(P, 0, len(P) - 1) < 0.05 if len(P) > 1 else False
    across = steps[-1] if closing else (_pose_dist(P, len(P) - 1, 0) if len(P) > 1 else 0.0)
    m["closing_key"] = bool(closing)
    m["seam_ratio"] = round(across / mean_step, 2) if mean_step > 1e-6 else None
    m["mean_step_deg"] = round(mean_step, 3)
    if skin is not None:
        m["under_floor_mm"] = round(under, 1)
        m["frames_below_pct"] = round(100.0 * below_frames / max(sampled, 1), 1)
    return m


def run(args: dict) -> dict:
    arm = bpy.data.objects.get(args.get("armature", ""))
    if arm is None or arm.type != "ARMATURE":
        return C.result_error("armature required")
    ad = arm.animation_data or arm.animation_data_create()
    prev_act, prev_slot = ad.action, getattr(ad, "action_slot", None)
    names = args.get("clips") or ([prev_act.name] if prev_act else [])
    acts = [bpy.data.actions.get(n) or bpy.data.actions.get("AN_" + n) for n in names]
    missing = [n for n, a in zip(names, acts) if a is None]
    acts = [a for a in acts if a is not None]
    if not acts:
        return C.result_error("no clips found", missing=missing)
    limbs = args.get("limbs") or find_limbs(arm)
    limbs = [lb for lb in limbs if all(lb.get(k) in arm.pose.bones for k in ("start", "knee", "end", "foot"))]
    skin = _skin(arm, args.get("mesh"))
    th = {**DEFAULTS, **(args.get("thresholds") or {})}
    loops = set(args.get("loops") or names)
    win = bpy.context.window
    prev_scene = None
    if bpy.context.scene not in arm.users_scene and arm.users_scene:
        if win is None:
            return C.result_error(f"{arm.name} is not in the current scene ({bpy.context.scene.name})")
        prev_scene, win.scene = win.scene, arm.users_scene[0]
    sc = bpy.context.scene
    frame0 = sc.frame_current
    # floor at rest
    floor_z = args.get("floor_z")
    if floor_z is None and skin is not None:
        pos = arm.data.pose_position
        arm.data.pose_position = "REST"
        bpy.context.view_layer.update()
        floor_z = float(C.evaluated_vertex_positions(skin)[:, 2].min())
        arm.data.pose_position = pos
        bpy.context.view_layer.update()
    clips, problems = {}, []
    try:
        for name, act in zip([n for n in names if n not in missing], acts):
            m = measure_clip(arm, act, skin, limbs, args, floor_z if floor_z is not None else 0.0)
            clips[name] = m
            for ln, li in m["limbs"].items():
                if th.get("reach_max") is not None and li["reach_max"] > th["reach_max"]:
                    problems.append(f"{name}: {ln} reaches {li['reach_max']:.0%} of its length (> {th['reach_max']:.0%}) "
                                    "— shorten the stride or lower the hips")
                if th.get("joint_pops") is not None and li["joint_pops"] > th["joint_pops"]:
                    problems.append(f"{name}: {ln} joint pops at frames {li['pop_frames']} — smooth the bend "
                                    "(anim_curves smooth) or ease the reach")
                if (th.get("standing_pitch_deg") is not None and li["standing_pitch_deg"] is not None
                        and li["kind"] == "leg" and not li["paw"] and li["standing_pitch_deg"] > th["standing_pitch_deg"]):
                    problems.append(f"{name}: {ln} stands {li['standing_pitch_deg']} deg off its rest pitch (heel or toe lifted)")
            if m["mean_step_deg"] < 1e-3:
                problems.append(f"{name}: nothing moves — wrong action/slot, or the deform bones do not follow the controls")
            if th.get("jitter_deg") is not None and m["jitter_deg"] > th["jitter_deg"]:
                problems.append(f"{name}: {m['jitter_at'][1]} jumps {m['jitter_deg']} deg and back at frame "
                                f"{m['jitter_at'][0]} — a popping key or a constraint flip")
            if th.get("under_floor_mm") is not None and m.get("under_floor_mm", 0) > th["under_floor_mm"]:
                problems.append(f"{name}: skin {m['under_floor_mm']} mm under the floor")
            if name in loops and th.get("seam_ratio") is not None and m["seam_ratio"] is not None:
                if m["seam_ratio"] > th["seam_ratio"]:
                    problems.append(f"{name}: loop seam {m['seam_ratio']}x the mean step — anim_curves loop_window "
                                    "or match_cycle")
                if not m["closing_key"]:
                    problems.append(f"{name}: no closing key equal to the first — glTF skips the step back to the start "
                                    "(anim_curves match_cycle)")
    finally:
        ad.action = prev_act
        if prev_act is not None and prev_slot is not None:
            try:
                ad.action_slot = prev_slot
            except (TypeError, RuntimeError):
                pass
        sc.frame_set(frame0)
        if prev_scene is not None:
            win.scene = prev_scene
    report = {"gate": "G5-motion", "status": "fail" if problems else "pass", "clips": clips,
              "limbs": limbs, "skin": skin.name if skin else None, "floor_z": floor_z,
              "thresholds": th, "missing": missing, "notes": problems, "at": C.now_iso()}
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", "motion-qa.json"), report)
    return C.result_ok(report=report)
