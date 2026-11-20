"""Bake source detail/colour onto a rebuilt mesh (texture-workflow, gate G3).

The SOURCE object is never modified: its material is temporarily swapped for a bake-only copy and
restored afterwards.

args:
    source       (str, required)   source (high-detail) object name
    target       (str, required)   rebuilt mesh with UVs (active UV map is used)
    maps         (list[str])       subset of ["basecolor", "normal", "roughness", "metallic", "ao"]; default all
    size         (int, 2048)       image size (px) — from budgets.textures.max_size
    extrusion    (float, auto)     cage extrusion in metres; default 1% of source bbox diagonal
    max_ray      (float, auto)     max ray distance; default 2x extrusion
    margin       (int, 16)         px
    samples      (int, 16)         Cycles samples (AO uses these; others need few)
    device       (str, "auto")      auto | GPU | CPU — auto uses the GPU when Cycles has a compute device (Metal/CUDA/OptiX/HIP/oneAPI)
    out_dir      (str, required)   e.g. projects/<name>/textures
    name         (str)             file prefix, default target name
    pack_orm     (bool, True)      write <name>_ORM.png (R=AO, G=roughness, B=metallic) from baked maps
    build_material (bool, True)    create a glTF-ready material on the target from the baked maps
    use_existing (bool, True)      maps not baked in this call but already in out_dir (<name>_<map>.png from an
                                   earlier call) are used for the ORM pack and the material

Run one or two maps per MCP call on dense sources to stay within call timeouts; the last call (with
use_existing) packs ORM and builds the material from every map on disk.
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
ALL_MAPS = ["basecolor", "normal", "roughness", "metallic", "ao"]


def _pick_device(choice: str) -> str:
    if choice.upper() in ("CPU", "GPU"):
        return choice.upper()
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.refresh_devices()
        if prefs.compute_device_type != "NONE" and any(d.use and d.type != "CPU" for d in prefs.devices):
            return "GPU"
    except Exception:  # background builds without GPU support
        pass
    return "CPU"


def _principled(mat):
    if not (mat and mat.use_nodes):
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _emission_copy(mat, input_name):
    """Copy of `mat` whose output is Emission driven by the principled input `input_name`."""
    m = mat.copy()
    m.name = f"__bake_{input_name}_{mat.name}"
    nt = m.node_tree
    bsdf = _principled(m)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    emit = nt.nodes.new("ShaderNodeEmission")
    sock = bsdf.inputs[input_name]
    if sock.is_linked:
        nt.links.new(sock.links[0].from_socket, emit.inputs["Color"])
    else:
        v = sock.default_value
        emit.inputs["Color"].default_value = (v[0], v[1], v[2], 1) if hasattr(v, "__len__") else (v, v, v, 1)
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return m


def _new_image(name, size, non_color):
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def _target_bake_material(target, img):
    mat = bpy.data.materials.new(f"__bake_target_{target.name}")
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    return mat


def _bake(source, target, kind, img, s):
    """kind: Cycles bake type. Source materials may be swapped by caller."""
    tmat = _target_bake_material(target, img)
    old_target = [slot.material for slot in target.material_slots]
    if not target.material_slots:
        target.data.materials.append(tmat)
    for slot in target.material_slots:
        slot.material = tmat
    for o in bpy.context.view_layer.objects:
        if o is not None:  # stale entries right after bpy.data.objects.remove
            o.select_set(False)
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    try:
        bpy.ops.object.bake(type=kind, use_selected_to_active=True, cage_extrusion=s["extrusion"],
                            max_ray_distance=s["max_ray"], margin=s["margin"],
                            normal_space="TANGENT", use_clear=True)
    finally:
        for slot, m in zip(target.material_slots, old_target or [None] * len(target.material_slots)):
            slot.material = m
        bpy.data.materials.remove(tmat)


def _save(img, path):
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return path


def _gltf_output_group():
    """glTF exporter reads occlusion from a node group named 'glTF Material Output' (input 'Occlusion')."""
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    return g


def build_material(target, paths, name):
    mat = bpy.data.materials.new(f"MAT_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _principled(mat)
    x = -700
    if "basecolor" in paths:
        n = nt.nodes.new("ShaderNodeTexImage"); n.location = (x, 300)
        n.image = bpy.data.images.load(paths["basecolor"], check_existing=True)
        nt.links.new(n.outputs["Color"], bsdf.inputs["Base Color"])
    if "normal" in paths:
        n = nt.nodes.new("ShaderNodeTexImage"); n.location = (x, -300)
        n.image = bpy.data.images.load(paths["normal"], check_existing=True)
        n.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (x + 300, -300)
        nt.links.new(n.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if "orm" in paths:
        n = nt.nodes.new("ShaderNodeTexImage"); n.location = (x, 0)
        n.image = bpy.data.images.load(paths["orm"], check_existing=True)
        n.image.colorspace_settings.name = "Non-Color"
        sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (x + 300, 0)
        nt.links.new(n.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        grp = nt.nodes.new("ShaderNodeGroup"); grp.node_tree = _gltf_output_group(); grp.location = (x + 600, -500)
        nt.links.new(sep.outputs["Red"], grp.inputs["Occlusion"])
    target.data.materials.clear()
    target.data.materials.append(mat)
    return mat.name


def run(args: dict) -> dict:
    src = bpy.data.objects.get(args.get("source", ""))
    tgt = bpy.data.objects.get(args.get("target", ""))
    if src is None or tgt is None:
        return C.result_error("source and target objects required")
    if not tgt.data.uv_layers:
        return C.result_error("target has no UVs; run the UV stage first")
    warnings = []
    flat = sum(1 for poly in tgt.data.polygons if not poly.use_smooth)
    if flat:
        warnings.append(f"target has {flat} flat-shaded faces: the normal map will carry faceting "
                        "(shade the target smooth before baking normals)")
    out_dir = C.ensure_dir(args["out_dir"])
    name = args.get("name", tgt.name)
    size = int(args.get("size", 2048))
    mn, mx = C.world_bbox([src])
    diag = float(np.linalg.norm(np.array(mx) - np.array(mn)))
    s = {"extrusion": float(args.get("extrusion", 0.01 * diag)), "margin": int(args.get("margin", 16))}
    s["max_ray"] = float(args.get("max_ray", 2 * s["extrusion"]))
    maps = args.get("maps", ALL_MAPS)

    scene = bpy.context.scene
    prev_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(args.get("samples", 16))
    prev_device = scene.cycles.device
    scene.cycles.device = _pick_device(args.get("device", "auto"))
    paths, swapped = {}, []
    src_mats = [slot.material for slot in src.material_slots]
    try:
        for m in maps:
            non_color = m != "basecolor"
            img = _new_image(f"{name}_{m}", size, non_color)
            if m in ("basecolor", "roughness", "metallic"):
                input_name = {"basecolor": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}[m]
                copies = [(_emission_copy(mt, input_name) if _principled(mt) else mt) for mt in src_mats]
                for slot, cm in zip(src.material_slots, copies):
                    slot.material = cm
                swapped.extend(c for c in copies if c and c.name.startswith("__bake_"))
                _bake(src, tgt, "EMIT", img, s)
                for slot, om in zip(src.material_slots, src_mats):
                    slot.material = om
            elif m == "normal":
                _bake(src, tgt, "NORMAL", img, s)
            elif m == "ao":
                _bake(src, tgt, "AO", img, s)
            else:
                continue
            paths[m] = _save(img, os.path.join(out_dir, f"{name}_{m}.png"))
    finally:
        for slot, om in zip(src.material_slots, src_mats):
            slot.material = om
        for c in swapped:
            if c.name in bpy.data.materials:
                bpy.data.materials.remove(c)
        scene.render.engine = prev_engine
        scene.cycles.device = prev_device

    baked_now = sorted(paths)
    if args.get("use_existing", True):
        for m in ALL_MAPS:
            p = os.path.join(out_dir, f"{name}_{m}.png")
            if m not in paths and os.path.exists(p):
                paths[m] = p
    stats = {}
    for m, p in paths.items():
        img = bpy.data.images.load(p, check_existing=True)
        px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[:, :3]
        stats[m] = {"mean": px.mean(0).round(4).tolist(), "std": px.std(0).round(4).tolist(),
                    "empty": bool(px.std() < 1e-4)}

    if args.get("pack_orm", True) and {"ao", "roughness", "metallic"} <= set(paths):
        chans = []
        for m in ("ao", "roughness", "metallic"):
            img = bpy.data.images.load(paths[m], check_existing=True)
            px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            chans.append(px.reshape(-1, 4)[:, 0])
        orm = _new_image(f"{name}_ORM", size, True)
        packed = np.stack(chans + [np.ones_like(chans[0])], 1).ravel()
        orm.pixels.foreach_set(packed)
        paths["orm"] = _save(orm, os.path.join(out_dir, f"{name}_ORM.png"))

    mat_name = build_material(tgt, paths, name) if args.get("build_material", True) else None
    s["device"] = _pick_device(args.get("device", "auto"))
    return C.result_ok(paths=paths, baked_now=baked_now, warnings=warnings, stats=stats, settings=s, material=mat_name,
                       empty_maps=[m for m, st in stats.items() if st["empty"]])
