"""Procedural PBR materials from Material Maker (.ptex) — export the maps, build a glTF-ready Blender material.

Material Maker (RodZill4, MIT) is a Godot app with a node editor for tileable procedural textures. Its command
line exports a .ptex graph to image maps:

    material_maker --export-material --target <profile> --size <px> -o <dir> <file.ptex>

This script runs that command in a separate process, then builds the material in Blender the same way
`bake_maps.py` does (Principled BSDF, ORM split, glTF occlusion group), so the result goes through the web/engine
export unchanged. The app is installed by the user (releases: github.com/RodZill4/material-maker/releases);
nothing of it is bundled here. Material Maker renders on the GPU through a window: it needs a desktop session
(no `--headless`, no SSH without a display).

Parameters cannot be set on Material Maker's command line, so overrides are written into a copy of the .ptex
(it is JSON): `params` by node name, `controls` by the label of a remote (exposed) control.

Profiles: "GLTF/Plane" (default: albedo, orm, normal, emission PNG — the maps this pipeline ships) or "Blender"
(albedo/normal/emission PNG + rough/metal/occlusion/displace EXR).

args:
    mode        (str, "apply")   "probe" | "list" | "export" | "material" | "apply" (export + material + assign)
    ptex        (str)            .ptex path, or the name of an example shipped with the app ("bricks", "wood")
    params      (dict)           {"<node name>": {"<parameter>": value}} — nodes searched in nested graphs too
    controls    (dict)           {"<remote control label>": value}, e.g. {"Hue": 0.1}
    size        (int, 2048)      map resolution (px)
    target      (str, "GLTF/Plane")  export profile
    name        (str)            material / file base name, default the .ptex name
    out_dir     (str)            where maps go; default <project_dir>/textures/material_maker/<name>,
                                 else a temp folder (reported as a warning: move or pack before saving)
    project_dir (str)
    maps_dir    (str)            "material" mode: folder holding <name>_albedo.png ... from an earlier export
    objects     (list[str])      "apply": mesh objects that get the material
    assign      (str, "replace") "replace" all slots | "append" a slot | "none"
    tiling      (float|[u,v], 1) texture repeats per UV unit (or per metre with projection "box")
    projection  (str, "uv")      "uv" | "box" (object-space box mapping for meshes without good UVs; bake
                                 to UVs with bake_maps.py before a game/web export — glTF has no box mapping)
    timeout     (float, 300)     seconds before the export process is killed
    mm_path     (str)            Material Maker executable (default: found automatically; env MATERIAL_MAKER_PATH)
"""
import copy
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

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

RELEASES_URL = "https://github.com/RodZill4/material-maker/releases"
# map key -> file suffix written by each export profile (Material Maker's material node, "exports")
PROFILES = {
    "GLTF/Plane": {"albedo": "_albedo.png", "orm": "_orm.png", "normal": "_normal.png", "emission": "_emission.png"},
    "Blender": {"albedo": "_albedo.png", "roughness": "_rough.exr", "metallic": "_metal.exr",
                "normal": "_normal.png", "displace": "_displace.exr", "sss": "_sss.exr",
                "emission": "_emission.png", "occlusion": "_occlusion.exr"},
}


# ---------------------------------------------------------------- finding the app
def _candidates(mm_path=None):
    if mm_path:
        return [mm_path]
    out = []
    env = os.environ.get("MATERIAL_MAKER_PATH")
    if env:
        out.append(env)
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        for root in ("/Applications", os.path.join(home, "Applications")):
            for app in sorted(glob.glob(os.path.join(root, "*aterial*aker*.app"))):
                out.extend(sorted(glob.glob(os.path.join(app, "Contents", "MacOS", "*"))))
    elif os.name == "nt":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", ""),
                     os.path.join(home, "Downloads"), home):
            if root:
                out.extend(sorted(glob.glob(os.path.join(root, "*aterial*aker*", "material_maker*.exe"))))
    else:
        exe = shutil.which("material_maker")
        if exe:
            out.append(exe)
        for root in (home, os.path.join(home, "Applications"), os.path.join(home, ".local", "share"), "/opt"):
            out.extend(sorted(glob.glob(os.path.join(root, "*aterial*aker*", "material_maker*"))))
    return out


def _examples_dir(exe):
    """Examples ship next to the binary (Windows/Linux) or inside the bundle (macOS)."""
    roots = [os.path.dirname(exe)]
    if ".app" + os.sep in exe:
        roots.append(exe.split(".app" + os.sep)[0] + ".app")
    for root in roots:
        for depth in ("examples", os.path.join("*", "examples"), os.path.join("*", "*", "examples")):
            for d in glob.glob(os.path.join(root, depth)):
                if glob.glob(os.path.join(d, "*.ptex")):
                    return d
    return None


def probe(mm_path=None) -> dict:
    for exe in _candidates(mm_path):
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            ex = _examples_dir(exe)
            return {"available": True, "exe": exe, "examples_dir": ex,
                    "examples": sorted(os.path.splitext(os.path.basename(p))[0]
                                       for p in glob.glob(os.path.join(ex, "*.ptex"))) if ex else []}
    return {"available": False, "tried": _candidates(mm_path),
            "install": f"Install Material Maker from {RELEASES_URL} (macOS .dmg → Applications; Windows .zip; "
                       "Linux .tar.gz), or pass mm_path / set MATERIAL_MAKER_PATH to the executable."}


def resolve_ptex(ptex, found) -> str:
    if ptex and os.path.isfile(os.path.abspath(bpy.path.abspath(ptex))):
        return os.path.abspath(bpy.path.abspath(ptex))
    ex = found.get("examples_dir")
    if ptex and ex:
        cand = os.path.join(ex, ptex if ptex.endswith(".ptex") else ptex + ".ptex")
        if os.path.isfile(cand):
            return cand
    return None


# ---------------------------------------------------------------- .ptex overrides
def _walk_nodes(graph):
    for n in graph.get("nodes", []):
        yield n
        if n.get("nodes"):                  # nested graph node
            yield from _walk_nodes(n)


def apply_overrides(doc, params=None, controls=None) -> dict:
    """Write overrides into a parsed .ptex in place. Returns {"applied": [...], "unknown": [...]}."""
    nodes = list(_walk_nodes(doc))
    by_name = {}
    for n in nodes:
        by_name.setdefault(n.get("name"), []).append(n)
    applied, unknown = [], []
    for node_name, values in (params or {}).items():
        targets = by_name.get(node_name)
        if not targets:
            unknown.append(f"node {node_name}")
            continue
        for key, value in values.items():
            hit = False
            for n in targets:
                p = n.setdefault("parameters", {})
                if key in p:
                    p[key] = value
                    hit = True
            (applied if hit else unknown).append(f"{node_name}.{key}")
    for label, value in (controls or {}).items():
        hit = False
        for n in nodes:
            for w in n.get("widgets") or []:
                if w.get("label") != label:
                    continue
                n.setdefault("parameters", {})[w["name"]] = value        # the remote's own value
                for lw in w.get("linked_widgets", []):                 # and every control it drives
                    for t in by_name.get(lw.get("node"), []):
                        t.setdefault("parameters", {})[lw.get("widget")] = value
                hit = True
        (applied if hit else unknown).append(f"control {label}")
    return {"applied": applied, "unknown": unknown}


# ---------------------------------------------------------------- export
def export_maps(exe, ptex, out_dir, name, target="GLTF/Plane", size=2048, params=None, controls=None,
                timeout=300.0) -> dict:
    if target not in PROFILES:
        return {"ok": False, "error": f"target must be one of {sorted(PROFILES)}"}
    with open(ptex, encoding="utf-8") as f:
        doc = json.load(f)
    changes = apply_overrides(doc, params, controls)
    if changes["unknown"]:
        return {"ok": False, "error": "unknown overrides: " + ", ".join(changes["unknown"]), **changes}
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(out_dir, name)
    for suf in PROFILES[target].values():                      # a stale map must not pass for a new export
        if os.path.isfile(prefix + suf):
            os.remove(prefix + suf)
    with tempfile.TemporaryDirectory(prefix="u3d_mm_") as tmp:
        src = os.path.join(tmp, name + ".ptex")                # output files are named after this file
        with open(src, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        cmd = [exe, "--export-material", "--target", target, "--size", str(int(size)), "-o", out_dir, src]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  timeout=timeout, cwd=tmp)
            code, out = proc.returncode, proc.stdout or ""
        except subprocess.TimeoutExpired as e:
            raw = e.stdout or ""
            code, out = None, raw.decode(errors="replace") if isinstance(raw, bytes) else raw
    log = [ln for ln in out.splitlines() if ln.strip()][-10:]
    files = {k: prefix + suf for k, suf in PROFILES[target].items() if os.path.isfile(prefix + suf)}
    info = {"files": files, "seconds": round(time.time() - t0, 2), "log": log, **changes}
    if code is None:
        return {"ok": False, "error": f"Material Maker timed out after {timeout} s", **info}
    if "albedo" not in files:
        why = "no maps written" + (f" (exit {code})" if code else "")
        return {"ok": False, "error": why + " — Material Maker needs a desktop session with a GPU", **info}
    return {"ok": True, "exit": code, **info}


def find_maps(maps_dir, name, target="GLTF/Plane") -> dict:
    prefix = os.path.join(maps_dir, name)
    found = {}
    for profile in ([target] + [p for p in PROFILES if p != target]):
        for k, suf in PROFILES[profile].items():
            if k not in found and os.path.isfile(prefix + suf):
                found[k] = prefix + suf
    return found


# ---------------------------------------------------------------- Blender material
def _gltf_output_group():
    """glTF exporter reads occlusion from a node group named 'glTF Material Output' (input 'Occlusion')."""
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    return g


def _has_signal(img, eps=1.0 / 255) -> bool:
    """True when an emission map is not black (sampled, so large maps stay cheap)."""
    w, h = img.size
    if not w or not h:
        return False
    px = np.empty(w * h * img.channels, dtype=np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(-1, img.channels)[::97, :3]
    return bool(rgb.max() > eps)


def build_material(name, maps, tiling=1.0, projection="uv"):
    mat = bpy.data.materials.get(f"MAT_{name}") or bpy.data.materials.new(f"MAT_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (150, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    coord = nt.nodes.new("ShaderNodeTexCoord"); coord.location = (-1300, 0)
    mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-1100, 0)
    uv = tiling if isinstance(tiling, (list, tuple)) else (tiling, tiling)
    mapping.inputs["Scale"].default_value = (float(uv[0]), float(uv[1]), float(uv[0]))
    box = projection == "box"
    nt.links.new(coord.outputs["Object" if box else "UV"], mapping.inputs["Vector"])
    y = 400
    tex = {}
    for key, path in maps.items():
        if key in ("displace", "sss"):
            continue                                            # kept on disk; not wired (no glTF slot)
        n = nt.nodes.new("ShaderNodeTexImage"); n.location = (-800, y); y -= 280
        n.label = key
        n.image = bpy.data.images.load(path, check_existing=True)
        if key != "albedo" and key != "emission":
            n.image.colorspace_settings.name = "Non-Color"
        if box:
            n.projection, n.projection_blend = "BOX", 0.2
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        tex[key] = n
    if "albedo" in tex:
        nt.links.new(tex["albedo"].outputs["Color"], bsdf.inputs["Base Color"])
    if "normal" in tex:
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (-450, tex["normal"].location.y)
        nt.links.new(tex["normal"].outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    occlusion = None
    if "orm" in tex:
        sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-450, tex["orm"].location.y)
        nt.links.new(tex["orm"].outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        occlusion = sep.outputs["Red"]
    if "roughness" in tex:
        nt.links.new(tex["roughness"].outputs["Color"], bsdf.inputs["Roughness"])
    if "metallic" in tex:
        nt.links.new(tex["metallic"].outputs["Color"], bsdf.inputs["Metallic"])
    if "occlusion" in tex:
        occlusion = tex["occlusion"].outputs["Color"]
    if occlusion is not None:
        grp = nt.nodes.new("ShaderNodeGroup"); grp.node_tree = _gltf_output_group(); grp.location = (150, -450)
        nt.links.new(occlusion, grp.inputs["Occlusion"])
    emissive = "emission" in tex and _has_signal(tex["emission"].image)
    if emissive:
        nt.links.new(tex["emission"].outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0
    elif "emission" in tex:
        nt.nodes.remove(tex.pop("emission"))                   # black map: no emissive texture in the export
    return mat, {"wired": sorted(tex), "emissive": emissive}


def assign(mat, objects, how="replace"):
    done = []
    for name in objects or []:
        ob = bpy.data.objects.get(name)
        if ob is None or ob.type != "MESH":
            continue
        if how == "replace":
            ob.data.materials.clear()
            ob.data.materials.append(mat)
        elif how == "append" and mat.name not in [m.name for m in ob.data.materials if m]:
            ob.data.materials.append(mat)
        done.append(ob.name)
    return done


# ---------------------------------------------------------------- entry point
def _out_dir(args, name, warnings):
    if args.get("out_dir"):
        return os.path.abspath(bpy.path.abspath(args["out_dir"]))
    if args.get("project_dir"):
        return os.path.join(C.project_paths(args["project_dir"])["textures"], "material_maker", name)
    warnings.append("maps written to a temp folder: pass out_dir/project_dir, or pack the images before saving")
    return os.path.join(tempfile.gettempdir(), "u3d_material_maker", name)


def run(args: dict) -> dict:
    args = args or {}
    mode = args.get("mode", "apply")
    target = args.get("target", "GLTF/Plane")
    warnings = []
    if mode == "material":                                     # offline: maps already on disk
        name = args.get("name")
        if not name or not args.get("maps_dir"):
            return C.result_error("material mode needs name and maps_dir")
        maps = find_maps(os.path.abspath(bpy.path.abspath(args["maps_dir"])), name, target)
        if "albedo" not in maps:
            return C.result_error(f"no {name}_albedo.* in maps_dir", maps=maps)
        mat, info = build_material(name, maps, args.get("tiling", 1.0), args.get("projection", "uv"))
        return C.result_ok(material=mat.name, maps=maps, **info,
                           assigned=assign(mat, args.get("objects"), args.get("assign", "replace")))
    found = probe(args.get("mm_path"))
    if mode == "probe":
        return C.result_ok(**found)
    if not found["available"]:
        return C.result_error("Material Maker not found", **found)
    if mode == "list":
        return C.result_ok(examples=found["examples"], examples_dir=found["examples_dir"])
    ptex = resolve_ptex(args.get("ptex"), found)
    if ptex is None:
        return C.result_error(f"ptex not found: {args.get('ptex')!r} (a .ptex path or one of the examples)",
                              examples=found["examples"])
    name = args.get("name") or os.path.splitext(os.path.basename(ptex))[0]
    out_dir = _out_dir(args, name, warnings)
    exp = export_maps(found["exe"], ptex, out_dir, name, target, int(args.get("size", 2048)),
                      args.get("params"), args.get("controls"), float(args.get("timeout", 300.0)))
    if not exp.pop("ok"):
        return C.result_error(exp.pop("error"), ptex=ptex, out_dir=out_dir, **exp)
    if mode == "export":
        return C.result_ok(ptex=ptex, out_dir=out_dir, warnings=warnings, **exp)
    if mode != "apply":
        return C.result_error(f"unknown mode {mode!r}")
    mat, info = build_material(name, exp["files"], args.get("tiling", 1.0), args.get("projection", "uv"))
    if args.get("projection") == "box":
        warnings.append("box projection is viewport/render only: bake to UVs (bake_maps.py) before export")
    return C.result_ok(material=mat.name, ptex=ptex, out_dir=out_dir, warnings=warnings, **info, **exp,
                       assigned=assign(mat, args.get("objects"), args.get("assign", "replace")))
