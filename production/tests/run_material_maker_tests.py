"""Tests for material_maker.py (Material Maker .ptex → maps → glTF-ready material).

Run inside Blender through the MCP (or `blender --background --python-expr ...`):

    import runpy
    ns = runpy.run_path("<repo>/production/tests/run_material_maker_tests.py")
    result = ns["run"]({})                       # every test
    result = ns["run"]({"only": ["material_from_maps"]})

Offline tests always run: overrides, material building + glTF export, and the export call against a stand-in
executable (POSIX only) that mimics Material Maker's command line. `real_export` needs the app and a desktop
session; without them it reports {"pass": True, "skipped": "..."}. Everything is built in a throw-away scene
("TEST_material_maker") and temp folders that are removed afterwards.
"""
import json
import os
import runpy
import shutil
import sys
import tempfile
import traceback

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts", "blender")
PREFIX = "TMM_"
_TMP = []


def _script():
    return runpy.run_path(os.path.join(SCRIPTS, "material_maker.py"))


def _tmpdir():
    d = tempfile.mkdtemp(prefix="u3d_mm_test_")
    _TMP.append(d)
    return d


def _png(path, rgba):
    """Write a 16x16 PNG; rgba = callable(x, y) -> (r, g, b, a) or a constant tuple."""
    img = bpy.data.images.new(PREFIX + os.path.basename(path), 16, 16, alpha=True)
    px = np.zeros((16, 16, 4), dtype=np.float32)
    for yy in range(16):
        for xx in range(16):
            px[yy, xx] = rgba(xx, yy) if callable(rgba) else rgba
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def _maps(folder, name, emission=(0, 0, 0, 1)):
    _png(os.path.join(folder, name + "_albedo.png"), lambda x, y: (x / 15, y / 15, 0.3, 1))
    _png(os.path.join(folder, name + "_orm.png"), (1.0, 0.6, 0.2, 1))
    _png(os.path.join(folder, name + "_normal.png"), (0.5, 0.5, 1.0, 1))
    _png(os.path.join(folder, name + "_emission.png"), emission)


def _plane(name):
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.active_object
    ob.name = ob.data.name = PREFIX + name
    return ob


def _linked(mat, socket_name):
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    return bsdf.inputs[socket_name].is_linked


# ---------------------------------------------------------------- offline
def test_probe():
    p = _script()["probe"]()
    ok = (p["available"] and p.get("exe")) or (not p["available"] and "install" in p)
    return {"pass": bool(ok), "available": p["available"], "exe": p.get("exe"),
            "examples": len(p.get("examples", []))}


def test_missing_app_errors():
    r = _script()["run"]({"ptex": "bricks", "mm_path": os.path.join(HERE, "__no_material_maker__")})
    return {"pass": (not r["ok"]) and "install" in r, "error": r.get("error")}


def test_overrides():
    doc = {"nodes": [
        {"name": "Perlin", "type": "perlin", "parameters": {"scale_x": 4, "scale_y": 4}},
        {"name": "hsv", "type": "adjust_hsv", "parameters": {"hue": 0.0}},
        {"name": "ctl", "type": "remote", "parameters": {"param1": 0.0},
         "widgets": [{"label": "Hue", "name": "param1", "type": "linked_control",
                      "linked_widgets": [{"node": "hsv", "widget": "hue"}]}]},
        {"name": "sub", "type": "graph", "parameters": {}, "connections": [],
         "nodes": [{"name": "Bricks", "type": "bricks", "parameters": {"rows": 6}}]},
    ]}
    ns = _script()
    r = ns["apply_overrides"](doc, {"Perlin": {"scale_x": 9}, "Bricks": {"rows": 12}}, {"Hue": 0.25})
    bad = ns["apply_overrides"](copy_doc(doc), {"Nope": {"x": 1}, "Perlin": {"missing": 1}}, {"NoLabel": 1})
    nodes = {n["name"]: n for n in doc["nodes"]}
    ok = (nodes["Perlin"]["parameters"]["scale_x"] == 9 and nodes["sub"]["nodes"][0]["parameters"]["rows"] == 12
          and nodes["ctl"]["parameters"]["param1"] == 0.25 and nodes["hsv"]["parameters"]["hue"] == 0.25
          and not r["unknown"] and len(bad["unknown"]) == 3)
    return {"pass": bool(ok), "applied": r["applied"], "unknown_reported": bad["unknown"]}


def copy_doc(doc):
    return json.loads(json.dumps(doc))


def test_material_from_maps():
    """Maps on disk → material; glTF export carries base colour, ORM, normal, occlusion; no black emission."""
    d = _tmpdir()
    _maps(d, "rock")
    ob = _plane("mat")
    r = _script()["run"]({"mode": "material", "name": "rock", "maps_dir": d, "objects": [ob.name], "tiling": 2})
    if not r["ok"]:
        return {"pass": False, **r}
    mat = bpy.data.materials[r["material"]]
    glb = os.path.join(d, "check.glb")
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.ops.export_scene.gltf(filepath=glb, use_selection=True, export_format="GLB")
    gj = _glb_json(glb)
    m = next((x for x in gj.get("materials", []) if x.get("name") == mat.name), {})
    pbr = m.get("pbrMetallicRoughness", {})
    ok = (_linked(mat, "Base Color") and _linked(mat, "Roughness") and _linked(mat, "Metallic")
          and _linked(mat, "Normal") and not _linked(mat, "Emission Color") and r["emissive"] is False
          and ob.data.materials[0] == mat and "baseColorTexture" in pbr and "metallicRoughnessTexture" in pbr
          and "normalTexture" in m and "occlusionTexture" in m and "emissiveTexture" not in m)
    return {"pass": bool(ok), "wired": r["wired"], "gltf_material_keys": sorted(m), "pbr_keys": sorted(pbr)}


def test_emission_wired():
    d = _tmpdir()
    _maps(d, "lava", emission=(1.0, 0.3, 0.0, 1))
    r = _script()["run"]({"mode": "material", "name": "lava", "maps_dir": d})
    mat = bpy.data.materials.get(r.get("material", ""))
    ok = r["ok"] and r["emissive"] and mat is not None and _linked(mat, "Emission Color")
    if mat:
        bpy.data.materials.remove(mat)
    return {"pass": bool(ok), "emissive": r.get("emissive")}


def _glb_json(path):
    with open(path, "rb") as f:
        data = f.read()
    n = int.from_bytes(data[12:16], "little")
    return json.loads(data[20:20 + n])


def test_export_cli_contract():
    """export/apply against a stand-in for the Material Maker binary: argv, output naming, override file."""
    if os.name == "nt":
        return {"pass": True, "skipped": "stand-in executable is POSIX-only"}
    d = _tmpdir()
    maps = os.path.join(d, "maps")
    os.makedirs(maps)
    _maps(maps, "SRC")
    fake = os.path.join(d, "material_maker")
    with open(fake, "w") as f:
        f.write(f"#!{sys.executable}\n" + r'''
import json, os, shutil, sys
a = sys.argv[1:]
assert a[0] == "--export-material", a
t, size, out, src = a[a.index("--target") + 1], a[a.index("--size") + 1], a[a.index("-o") + 1], a[-1]
name = os.path.splitext(os.path.basename(src))[0]
maps = os.environ["U3D_FAKE_MAPS"]
for suf in ("_albedo.png", "_orm.png", "_normal.png", "_emission.png"):
    shutil.copy(os.path.join(maps, "SRC" + suf), os.path.join(out, name + suf))
json.dump({"argv": a, "doc": json.load(open(src))}, open(os.path.join(out, name + "_seen.json"), "w"))
print("Exporting Material", name)
''')
    os.chmod(fake, 0o755)
    ptex = os.path.join(d, "bricks.ptex")
    with open(ptex, "w") as f:
        json.dump({"nodes": [{"name": "Bricks", "type": "bricks", "parameters": {"rows": 6}},
                             {"name": "Material", "type": "material", "parameters": {}}], "connections": []}, f)
    os.environ["U3D_FAKE_MAPS"] = maps
    out = os.path.join(d, "out")
    ob = _plane("cli")
    try:
        r = _script()["run"]({"ptex": ptex, "name": "wall", "mm_path": fake, "out_dir": out, "size": 512,
                              "params": {"Bricks": {"rows": 10}}, "objects": [ob.name]})
        bad = _script()["run"]({"ptex": ptex, "mm_path": fake, "out_dir": out, "params": {"Nope": {"a": 1}}})
    finally:
        os.environ.pop("U3D_FAKE_MAPS", None)
    if not r["ok"]:
        return {"pass": False, **r}
    seen = json.load(open(os.path.join(out, "wall_seen.json")))
    ok = (set(r["files"]) == {"albedo", "orm", "normal", "emission"} and seen["argv"][2] == "GLTF/Plane"
          and seen["argv"][4] == "512" and seen["doc"]["nodes"][0]["parameters"]["rows"] == 10
          and json.load(open(ptex))["nodes"][0]["parameters"]["rows"] == 6          # source .ptex untouched
          and r["assigned"] == [ob.name] and not bad["ok"] and "unknown overrides" in bad["error"])
    return {"pass": bool(ok), "files": sorted(r["files"]), "argv": seen["argv"][:6], "bad_error": bad.get("error")}


# ---------------------------------------------------------------- needs the app
def test_real_export():
    ns = _script()
    p = ns["probe"]()
    if not p["available"]:
        return {"pass": True, "skipped": "Material Maker not installed"}
    if bpy.app.background and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return {"pass": True, "skipped": "no display for Material Maker"}
    ptex = "bricks" if "bricks" in p["examples"] else (p["examples"][0] if p["examples"] else None)
    if ptex is None:
        return {"pass": True, "skipped": "no example .ptex found next to the app"}
    d = _tmpdir()
    ob = _plane("real")
    r = ns["run"]({"ptex": ptex, "out_dir": d, "size": 512, "objects": [ob.name], "name": PREFIX + "real"})
    if not r["ok"]:
        return {"pass": False, **r}
    img = bpy.data.images.load(r["files"]["albedo"])
    px = np.empty(img.size[0] * img.size[1] * img.channels, dtype=np.float32)
    img.pixels.foreach_get(px)
    varied = float(px.reshape(-1, img.channels)[:, :3].std()) > 0.01
    ok = (img.size[0] == 512 and varied and {"albedo", "orm", "normal"} <= set(r["files"])
          and r["assigned"] == [ob.name])
    return {"pass": bool(ok), "ptex": ptex, "files": sorted(r["files"]), "size": list(img.size),
            "albedo_std": round(float(px.reshape(-1, img.channels)[:, :3].std()), 4), "seconds": r.get("seconds")}


TESTS = {"probe": test_probe, "missing_app_errors": test_missing_app_errors, "overrides": test_overrides,
         "material_from_maps": test_material_from_maps, "emission_wired": test_emission_wired,
         "export_cli_contract": test_export_cli_contract, "real_export": test_real_export}


MATERIALS = ("MAT_rock", "MAT_lava", "MAT_wall", "MAT_" + PREFIX + "real")   # only what the tests create


def _cleanup(sc):
    for ob in list(sc.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for nm in [o.name for o in bpy.data.objects if o.name.startswith(PREFIX)]:
        bpy.data.objects.remove(bpy.data.objects[nm], do_unlink=True)
    bpy.data.scenes.remove(sc)
    roots = [os.path.realpath(t) for t in _TMP]
    for nm in [m.name for m in bpy.data.materials if m.name in MATERIALS]:
        bpy.data.materials.remove(bpy.data.materials[nm])
    for nm in [m.name for m in bpy.data.meshes if m.name.startswith(PREFIX)]:
        bpy.data.meshes.remove(bpy.data.meshes[nm])
    for nm in [i.name for i in bpy.data.images
               if i.name.startswith(PREFIX) or any(os.path.realpath(bpy.path.abspath(i.filepath)).startswith(r)
                                                    for r in roots if i.filepath)]:
        bpy.data.images.remove(bpy.data.images[nm])
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)


def run(args=None):
    args = args or {}
    only = args.get("only") or list(TESTS)
    win = bpy.context.window
    prev = win.scene if win else bpy.context.scene
    sc = bpy.data.scenes.new("TEST_material_maker")
    if win:
        win.scene = sc
    out = {}
    # No temp_override(scene=...): the glTF exporter crashed Blender 5.3 (background) inside one. Without a
    # window the tests build in the current scene; every object they make is prefixed and removed below.
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
    return {"all_pass": all(v.get("pass") for v in out.values()), "results": out,
            "skipped": [k for k, v in out.items() if v.get("skipped")]}
