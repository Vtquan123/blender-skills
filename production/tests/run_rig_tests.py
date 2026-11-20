"""End-to-end test in Blender: analyse → rig by archetype → clips → checks → GLB + Blender samples.

For each procedural asset (make_test_assets.py) a scratch scene TEST_<asset> is built; nothing touches other
scenes. Afterwards validate the GLBs (node production/scripts/node/validate_gltf.mjs) and compare Blender and
three.js (production/scripts/validation/runtime_check.mjs --samples <asset>_samples.json).

args:
    assets_dir  (str, required)   where make_test_assets.py wrote the GLBs
    out_dir     (str, required)   GLBs + samples + JSON summary
    assets      (list, optional)  subset of ball, car_parts, car_fused, tree_fused, snake_fused
    keep_scenes (bool, False)
"""
import json
import os
import runpy

import bpy

HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
B = os.path.join(HERE, "..", "scripts", "blender")
M = os.path.join(HERE, "..", "scripts", "motion", "generators.py")

PLANS = {
    "ball": {"rig": ("rigid", {"kind": "ball"}),
             "clips": [("AN_roll", "ball_roll", 2.0, {"speed": 0.6}), ("AN_bounce", "ball_bounce", 1.0, {"height": 0.25})]},
    "car_parts": {"rig": ("rigid", {"kind": "vehicle", "forward": "X"}),
                  "clips": [("AN_drive", "vehicle_drive", 2.0, {"speed": 0.8}), ("AN_turn", "vehicle_drive", 2.0, {"speed": 0.5, "steer_deg": 20})]},
    "car_fused": {"rig": ("rigid", {"kind": "vehicle", "forward": "X", "split_wheels": True}),
                  "clips": [("AN_drive", "vehicle_drive", 2.0, {"speed": 0.8}), ("AN_turn", "vehicle_drive", 2.0, {"speed": 0.5, "steer_deg": 20})]},
    "tree_fused": {"rig": ("chain", {"mode": "plant"}), "skin": True,
                   "clips": [("AN_sway", "wind_sway", 4.0, {"amp_deg": 5, "sway_cycles": 2, "gust": 0.4})]},
    "snake_fused": {"rig": ("chain", {"mode": "spine"}), "skin": True,
                    "clips": [("AN_slither", "wind_sway", 4.0, {"amp_deg": 40, "sway_cycles": 2, "axis": "Z", "phase_step": 0.18, "taper": 0.3, "gust": 0.0})]},
}


def _fresh(name):
    old = bpy.data.scenes.get(name)
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.scenes.remove(old)
    sc = bpy.data.scenes.new(name)
    bpy.context.window.scene = sc
    return sc


def run(args: dict) -> dict:
    A, OUT = args["assets_dir"], args["out_dir"]
    os.makedirs(OUT, exist_ok=True)
    prev_scene = bpy.context.window.scene
    report = {}
    try:
        for asset in args.get("assets") or list(PLANS):
            plan = PLANS[asset]
            sc = _fresh(f"TEST_{asset}")
            before = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=os.path.join(A, f"{asset}.glb"))
            objs = [o.name for o in bpy.data.objects if o not in before and o.type == "MESH"]
            S = runpy.run_path(os.path.join(B, "structure_analysis.py"))["run"]({"objects": objs})["structure"]
            rig_name = f"RIG_{asset}"
            kind, rargs = plan["rig"]
            if kind == "rigid":
                rr = runpy.run_path(os.path.join(B, "rigid_rig.py"))["run"]({**rargs, "objects": objs, "structure": S, "name": rig_name})
            else:
                rr = runpy.run_path(os.path.join(B, "chain_rig.py"))["run"]({**rargs, "structure": S, "name": rig_name})
            if not rr.get("ok"):
                report[asset] = {"error": rr.get("error")}
                continue
            rec = {"archetype": [S["archetypes"][0]["archetype"], S["archetypes"][0]["subtype"]], "bones": len(bpy.data.objects[rig_name].data.bones)}
            if plan.get("skin"):
                sw = runpy.run_path(os.path.join(B, "skin_weights.py"))["run"]({"mode": "auto", "mesh": objs[0], "armature": rig_name,
                                                                               "max_influences": 4, "clean_threshold": 0.01, "smooth_iterations": 3})
                rec["G4b"] = sw["gate"]["status"]; rec["weight_method"] = sw.get("weight_method")
            g = runpy.run_path(M)["run"]
            clips = []
            for action, gen, cyc, params in plan["clips"]:
                r = g({"generator": gen, "target": rig_name, "action": action, "cycle_s": cyc, "params": params})
                clips.append(action)
                rec.setdefault("clips", {})[action] = r.get("ok", r.get("error"))
            meshes = [o.name for o in sc.objects if o.type == "MESH"]
            if plan.get("skin"):
                dc = runpy.run_path(os.path.join(B, "deform_check.py"))["run"]({"rig": rig_name, "mesh": objs[0], "clips": clips, "step": 3})
                rec["fold_verts"] = dc["metrics"]["fold_verts"]
            rig = bpy.data.objects[rig_name]
            rig.animation_data.action = None
            for pb in rig.pose.bones:
                pb.matrix_basis.identity()
            sc.frame_set(1)
            glb = os.path.join(OUT, f"{asset}.glb")
            e = runpy.run_path(os.path.join(B, "export_glb.py"))["run"]({"filepath": glb, "objects": [rig_name] + meshes, "clips": clips,
                                                                         "fps": 30, "max_influences": 4, "deform_bones_only": True})
            s = runpy.run_path(os.path.join(B, "sample_vertices.py"))["run"]({"armature": rig_name, "meshes": meshes, "clips": clips,
                                                                             "out": os.path.join(OUT, f"{asset}_samples.json")})
            rec.update({"export": e.get("ok"), "samples": s.get("ok"), "bytes": os.path.getsize(glb)})
            report[asset] = rec
            if not args.get("keep_scenes"):
                for o in list(sc.objects):
                    bpy.data.objects.remove(o, do_unlink=True)
                bpy.data.scenes.remove(sc)
    finally:
        if prev_scene and prev_scene.name in bpy.data.scenes:
            bpy.context.window.scene = prev_scene
    json.dump(report, open(os.path.join(OUT, "rig_tests.json"), "w"), indent=1)
    return {"ok": all("error" not in r for r in report.values()), "report": report}
