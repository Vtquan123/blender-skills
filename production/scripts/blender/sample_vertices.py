"""Sample deformed vertex positions per clip, for the Blender <-> three.js comparison in gate G7.

glTF export splits/reorders vertices, so the runtime check matches samples by REST position
(nearest neighbour), not by index.

args:
    meshes      (list[str], required)  skinned mesh objects
    armature    (str, required)
    clips       (list[str])            action names; default: all actions
    fractions   (list[float])          default [0, 0.25, 0.5, 0.75, 1.0]
    count       (int, 200)             vertices per mesh
    out         (str, required)        JSON path (e.g. reports/blender-samples.json)
    yup         (bool, True)           convert to glTF axes (x, z, -y)
"""
import importlib.util
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


def _to_gltf(p, yup):
    return np.stack([p[:, 0], p[:, 2], -p[:, 1]], 1) if yup else p


def run(args: dict) -> dict:
    arm = bpy.data.objects.get(args.get("armature", ""))
    meshes = [bpy.data.objects[n] for n in args.get("meshes", [])]
    if arm is None or not meshes:
        return C.result_error("armature and meshes required")
    scene = bpy.context.scene
    fracs = args.get("fractions", [0, 0.25, 0.5, 0.75, 1.0])
    count = int(args.get("count", 200))
    yup = bool(args.get("yup", True))
    clips = args.get("clips") or [a.name for a in bpy.data.actions]
    rng = np.random.default_rng(1)

    ad = arm.animation_data or arm.animation_data_create()
    prev_action, prev_frame = ad.action, scene.frame_current
    ad.action = None
    rest = {}
    pick = {}
    # rest pose: no action, pose position REST
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    for m in meshes:
        p = C.evaluated_vertex_positions(m)
        idx = rng.choice(len(p), size=min(count, len(p)), replace=False)
        pick[m.name] = idx
        rest[m.name] = _to_gltf(p[idx], yup).round(6).tolist()
    arm.data.pose_position = "POSE"

    out = {"rest": rest, "clips": {}, "fps": scene.render.fps, "axes": "gltf" if yup else "blender"}
    for name in clips:
        act = bpy.data.actions.get(name)
        if act is None:
            continue
        # each glTF clip starts from the rest pose; a bone keyed only in an earlier clip would otherwise keep that
        # clip's last value here (Blender keeps un-keyed channels), and the samples would not match the export
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
        ad.action = act
        if hasattr(ad, "action_slot") and len(getattr(act, "slots", [])):
            ad.action_slot = act.slots[0]
        f0, f1 = act.frame_range
        frames, times = {}, {}
        for f in fracs:
            fr = f0 + (f1 - f0) * f
            times[str(f)] = round((fr - f0) / scene.render.fps, 6)  # clip time after slide-to-zero export
            scene.frame_set(int(fr), subframe=fr - int(fr))
            frames[str(f)] = {m.name: _to_gltf(C.evaluated_vertex_positions(m)[pick[m.name]], yup).round(6).tolist()
                              for m in meshes}
        out["clips"][name] = {"frame_range": [f0, f1], "times_s": times, "samples": frames}
    ad.action = prev_action
    scene.frame_set(prev_frame)
    C.write_json(args["out"], out)
    return C.result_ok(out=args["out"], clips=list(out["clips"]), count=count)
