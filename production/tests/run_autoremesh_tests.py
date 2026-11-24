"""Tests for the AutoRemesher backend: autoremesh.py and deform_mesh.py `remesher`.

Run inside Blender through the MCP (or `blender --background --factory-startup --python-expr ...`):

    import runpy
    ns = runpy.run_path("<repo>/production/tests/run_autoremesh_tests.py")
    result = ns["run"]({})                               # every test
    result = ns["run"]({"only": ["auto_fallback"]})

Tests that need the AutoRemesher extension report {"pass": True, "skipped": "..."} when it is not
installed; the fallback and error-path tests always run. Everything is built in a throw-away scene
("TEST_autoremesh") that is removed afterwards.
"""
import os
import runpy
import traceback

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts", "blender")
PREFIX = "TAR_"
NO_CORE = os.path.join(HERE, "__no_autoremesher_here__")   # a core_path that never holds the module
_PROBE = {}


def _script(name):
    return runpy.run_path(os.path.join(SCRIPTS, name + ".py"))


def _available():
    if "r" not in _PROBE:
        _PROBE["r"] = _script("autoremesh")["probe"]()
    return _PROBE["r"]


def _skip_without_core():
    p = _available()
    return None if p["available"] else {"pass": True, "skipped": "AutoRemesher extension not installed"}


# ---------------------------------------------------------------- builders
def sphere(name, radius=1.0, subdiv=5, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=radius, location=location)
    ob = bpy.context.active_object
    ob.name = ob.data.name = PREFIX + name
    return ob


def tube(name, length=1.0, radius=0.08):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=length, location=(0, 0, length / 2))
    ob = bpy.context.active_object
    ob.name = ob.data.name = PREFIX + name
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=24)
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def _coords(ob):
    co = np.empty(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


# ---------------------------------------------------------------- always run
def test_probe():
    p = _available()
    shape_ok = "available" in p and (p["available"] and p.get("core_dir") or not p["available"] and p.get("install"))
    return {"pass": bool(shape_ok), "available": p["available"], "core_dir": p.get("core_dir"),
            "tried": p.get("tried")}


def test_missing_core_errors():
    """Explicit backend without the core: clear error, install hint, source untouched."""
    src = sphere("err_src", subdiv=3)
    before = _coords(src).copy()
    ar = _script("autoremesh")["run"]({"source": src.name, "target_faces": 200, "core_path": NO_CORE})
    dm = _script("deform_mesh")["run"]({"source": src.name, "target_faces": 200, "remesher": "autoremesher",
                                        "autoremesher": {"core_path": NO_CORE}, "collection": PREFIX + "COL",
                                        "name": PREFIX + "err_deform"})
    bad = _script("deform_mesh")["run"]({"source": src.name, "target_faces": 200, "remesher": "instant",
                                         "collection": PREFIX + "COL"})
    untouched = np.allclose(before, _coords(src))
    ok = (not ar["ok"] and "install" in ar and not dm["ok"] and "install the extension" in dm["error"]
          and not bad["ok"] and untouched)
    return {"pass": bool(ok), "autoremesh_error": ar.get("error"), "deform_error": dm.get("error"),
            "bad_choice_error": bad.get("error"), "source_untouched": bool(untouched)}


def test_auto_fallback():
    """remesher=auto without the core: QuadriFlow result, fallback reported."""
    src = sphere("fb_src", subdiv=4)
    r = _script("deform_mesh")["run"]({"source": src.name, "target_faces": 400, "remesher": "auto",
                                       "autoremesher": {"core_path": NO_CORE}, "collection": PREFIX + "COL",
                                       "name": PREFIX + "fb_deform"})
    rm = r.get("remesh", {})
    st = r.get("stats", {})
    ok = (r["ok"] and rm.get("used") == "quadriflow" and rm.get("fallback")
          and st.get("quads_ratio", 0) > 0.9 and st.get("boundary_edges", 1) == 0)
    return {"pass": bool(ok), "remesh": {k: rm.get(k) for k in ("requested", "used", "fallback")},
            "faces": st.get("faces"), "quads_ratio": st.get("quads_ratio")}


# ---------------------------------------------------------------- need the extension
def test_autoremesh_sphere():
    skip = _skip_without_core()
    if skip:
        return skip
    src = sphere("ar_src", subdiv=5)
    r = _script("autoremesh")["run"]({"source": src.name, "target_faces": 600, "name": PREFIX + "ar_out"})
    if not r["ok"]:
        return {"pass": False, **r}
    st = r["stats"]
    dims = np.array(st["dimensions"])
    ok = (st["quads_ratio"] >= 0.9 and st["boundary_edges"] == 0 and 300 <= st["faces"] <= 1500
          and np.allclose(dims, 2.0, rtol=0.05) and src.name in bpy.data.objects)
    return {"pass": bool(ok), "faces": st["faces"], "quads_ratio": st["quads_ratio"],
            "boundary_edges": st["boundary_edges"], "dimensions": st["dimensions"],
            "seconds": r["autoremesher"].get("seconds")}


def test_deform_autoremesher():
    skip = _skip_without_core()
    if skip:
        return skip
    src = tube("dm_src")
    joint = {"name": "mid", "head": [0, 0, 0.5], "axis": [0, 0, 1], "loops": 3, "band_halfwidth": 0.05,
             "radius": 0.1}
    r = _script("deform_mesh")["run"]({"source": src.name, "target_faces": 800, "remesher": "autoremesher",
                                       "joints": [joint], "collection": PREFIX + "COL",
                                       "name": PREFIX + "dm_deform"})
    if not r["ok"]:
        return {"pass": False, **r}
    st, rm = r["stats"], r["remesh"]
    # a thin tube is the shape where adaptivity 0 ignores the request (3–8k faces for 800): fitting must
    # bring it near the budget (joint-loop cuts may add a few rings on top)
    ok = (rm["used"] == "autoremesher" and "fallback" not in rm and st["quads_ratio"] >= 0.85
          and st["components"] == 1 and st["faces"] <= 800 * 1.6
          and r["joint_loops"] and r["joint_loops"][0]["status"] in ("ok", "cut"))
    return {"pass": bool(ok), "faces": st["faces"], "quads_ratio": st["quads_ratio"],
            "joint_loops": r["joint_loops"], "seconds": rm["autoremesher"].get("seconds"),
            "settings": rm["autoremesher"].get("settings"), "warnings": rm["autoremesher"].get("warnings")}


def test_weld_shells():
    skip = _skip_without_core()
    if skip:
        return skip
    a = sphere("ws_a", radius=0.5, subdiv=4, location=(-0.3, 0, 0))
    b = sphere("ws_b", radius=0.5, subdiv=4, location=(0.3, 0, 0))
    bpy.ops.object.select_all(action="DESELECT")
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.join()
    r = _script("autoremesh")["run"]({"source": a.name, "target_faces": 800, "weld_shells": True,
                                      "name": PREFIX + "ws_out"})
    if not r["ok"]:
        return {"pass": False, **r}
    st = r["stats"]
    ok = st["components"] == 1 and st["boundary_edges"] == 0 and r["autoremesher"].get("weld_voxel")
    return {"pass": bool(ok), "components": st["components"], "faces": st["faces"],
            "weld_voxel": r["autoremesher"].get("weld_voxel")}


TESTS = {"probe": test_probe, "missing_core_errors": test_missing_core_errors, "auto_fallback": test_auto_fallback,
         "autoremesh_sphere": test_autoremesh_sphere, "deform_autoremesher": test_deform_autoremesher,
         "weld_shells": test_weld_shells}


def _cleanup(sc):
    for ob in list(sc.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.scenes.remove(sc)
    for kind in ("objects", "meshes", "collections"):
        coll = getattr(bpy.data, kind)
        for nm in [d.name for d in coll if d.name.startswith(PREFIX)]:
            d = coll.get(nm)
            if d is not None:
                coll.remove(d)


def run(args=None):
    args = args or {}
    only = args.get("only") or list(TESTS)
    win = bpy.context.window
    prev = win.scene if win else bpy.context.scene
    sc = bpy.data.scenes.new("TEST_autoremesh")
    if win:
        win.scene = sc
    out = {}
    try:
        with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
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
    left = [d.name for c in (bpy.data.objects, bpy.data.meshes) for d in c if d.name.startswith(PREFIX)]
    return {"all_pass": all(v.get("pass") for v in out.values()), "results": out,
            "skipped": [k for k, v in out.items() if v.get("skipped")], "left_behind": left}
