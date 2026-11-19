"""Animation checks for gate G5.

args:
    armature     (str, required)
    clips        (list[str], required)  expected clip/action names (spec names; "AN_" prefixed names also accepted)
    fps          (int, optional)        expected scene fps
    loops        (list[str])            clips that must loop seamlessly
    feet         (list[str])            deform bones touching the ground (for foot-slide)
    contact_eps  (float, 0.01)          metres above the lowest foot height that still counts as contact
    thresholds   (dict)                 {"loop_seam_max_deg": .., "foot_slide_max_m": ..}
    project_dir  (str, optional)        write reports/gate-G5.json
"""
import importlib.util
import math
import os
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


def _find_action(name):
    return bpy.data.actions.get(name) or bpy.data.actions.get("AN_" + name)


def _pose_snapshot(arm):
    mw = arm.matrix_world
    return {pb.name: (mw @ pb.matrix) for pb in arm.pose.bones if pb.bone.use_deform}


def _max_angle_deg(s0, s1):
    worst = 0.0
    for k, m0 in s0.items():
        q0, q1 = m0.to_quaternion(), s1[k].to_quaternion()
        worst = max(worst, math.degrees(q0.rotation_difference(q1).angle))
    return worst


def run(args: dict) -> dict:
    arm = bpy.data.objects.get(args.get("armature", ""))
    if arm is None:
        return C.result_error("armature required")
    scene = bpy.context.scene
    ad = arm.animation_data or arm.animation_data_create()
    prev = ad.action
    loops = set(args.get("loops", []))
    feet = [f for f in args.get("feet", []) if f in arm.pose.bones]
    eps = float(args.get("contact_eps", 0.01))
    clips = {}
    missing = []
    for name in args.get("clips", []):
        act = _find_action(name)
        if act is None:
            missing.append(name)
            continue
        ad.action = act
        if hasattr(ad, "action_slot") and len(getattr(act, "slots", [])):
            ad.action_slot = act.slots[0]
        f0, f1 = (int(round(x)) for x in act.frame_range)
        info = {"action": act.name, "frame_range": [f0, f1], "duration_s": round((f1 - f0) / scene.render.fps, 3)}
        scene.frame_set(f0)
        s0 = _pose_snapshot(arm)
        scene.frame_set(f1)
        s1 = _pose_snapshot(arm)
        if name in loops:
            info["loop_seam_deg"] = round(_max_angle_deg(s0, s1), 3)
        if feet:
            track = {f: [] for f in feet}
            for fr in range(f0, f1 + 1):
                scene.frame_set(fr)
                for f in feet:
                    track[f].append(np.array(arm.matrix_world @ arm.pose.bones[f].head))
            slide = 0.0
            for f, pts in track.items():
                pts = np.array(pts)
                ground = pts[:, 2].min()
                contact = pts[:, 2] <= ground + eps
                for i in range(1, len(pts)):
                    if contact[i] and contact[i - 1]:
                        slide = max(slide, float(np.linalg.norm(pts[i, :2] - pts[i - 1, :2])))
            info["foot_slide_max_m"] = round(slide, 5)
        clips[name] = info
    ad.action = prev

    th = args.get("thresholds") or {}
    problems = list(f"missing clip {m}" for m in missing)
    if args.get("fps") and scene.render.fps != int(args["fps"]):
        problems.append(f"scene fps {scene.render.fps} != {args['fps']}")
    for n, i in clips.items():
        if th.get("loop_seam_max_deg") is not None and i.get("loop_seam_deg", 0) > th["loop_seam_max_deg"]:
            problems.append(f"{n}: loop seam {i['loop_seam_deg']} deg")
        if th.get("foot_slide_max_m") is not None and i.get("foot_slide_max_m", 0) > th["foot_slide_max_m"]:
            problems.append(f"{n}: foot slide {i['foot_slide_max_m']} m")
    gate = {"gate": "G5", "status": "fail" if problems else "needs_review",
            "metrics": {"clips": clips, "missing": missing}, "thresholds": th, "notes": problems
            + ["similarity to source is approved by the user from the side-by-side sheet"], "at": C.now_iso()}
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", "gate-G5.json"), gate)
    return C.result_ok(gate=gate)
