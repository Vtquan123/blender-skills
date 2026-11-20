"""Regression test for structure_analysis.py on the procedural assets (make_test_assets.py).

Run inside Blender: runpy.run_path(this)["run"]({"assets_dir": ".../_tests/assets"}) → {"passed", "failed", "results"}.
Add real models with "extra": [{"source": path, "expect": {"archetype": "...", "subtype": "...", "wheels": n}}].
"""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
EXPECT = {
    "ball": {"archetype": "rigid_whole", "subtype": "round"},
    "car_parts": {"archetype": "rigid_parts", "subtype": "vehicle", "wheels": 4},
    "car_fused": {"archetype": "rigid_parts", "subtype": "vehicle", "wheels": 4, "question": "split_wheels"},
    "tree_fused": {"archetype": "chain_flex", "subtype": "plant"},
    "chest_parts": {"archetype": "rigid_parts", "subtype": "hinged", "question": "hinge"},
    "snake_fused": {"archetype": "chain_flex", "subtype": "body_chain"},
    "baseball": {"archetype": "rigid_whole", "subtype": "round"},
}


def run(args: dict) -> dict:
    sa = runpy.run_path(os.path.join(HERE, "..", "scripts", "blender", "structure_analysis.py"))["run"]
    d = args["assets_dir"]
    if args.get("build", True):
        runpy.run_path(os.path.join(HERE, "make_test_assets.py"))["run"]({"out_dir": d})
    cases = [({"source": os.path.join(d, f"{k}.glb")}, k, v) for k, v in EXPECT.items()]
    cases += [({"source": e["source"]}, os.path.basename(e["source"]), e["expect"]) for e in args.get("extra", [])]
    cases += [({"objects": e["objects"], "scene": e.get("scene")}, e["name"], e["expect"]) for e in args.get("scene_objects", [])]
    results, failed = {}, []
    for a, name, exp in cases:
        r = sa(a)
        if not r.get("ok"):
            failed.append(name); results[name] = r.get("error"); continue
        S = r["structure"]
        top = S["archetypes"][0]
        got = {"archetype": top["archetype"], "subtype": top["subtype"], "wheels": len(S["wheels"]),
               "questions": [q["id"] for q in S["questions"]]}
        ok = got["archetype"] == exp["archetype"] and got["subtype"] == exp.get("subtype", got["subtype"])
        ok &= "wheels" not in exp or got["wheels"] == exp["wheels"]
        ok &= "question" not in exp or exp["question"] in got["questions"]
        results[name] = {"ok": bool(ok), **got}
        if not ok:
            failed.append(name)
    return {"ok": not failed, "passed": len(results) - len(failed), "failed": failed, "results": results}
