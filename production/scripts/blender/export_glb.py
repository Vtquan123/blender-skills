"""Export the uncompressed master GLB (web-export step 2 / export-pipeline).

Compression happens once, later, in production/scripts/node/optimize.mjs — never here.

args:
    filepath        (str, required)  e.g. projects/<name>/output/<name>.master.glb
    objects         (list[str])      objects to export (armature + meshes). Default: all visible objects in scene.
    clip_names      (dict)           {"AN_Walk": "walk"} rename actions for the export, restored afterwards
    strip_prefix    (str, "AN_")     prefix removed from action names when clip_names does not cover them
    max_influences  (int, 4)
    deform_bones_only (bool, True)
    fps             (int, optional)  set scene fps before export
    project_dir     (str, optional)  write reports/export.json

Only operator properties that exist in the running Blender are passed (checked at runtime).
"""
import importlib.util
import os
import sys

import bpy


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


def _supported(op) -> set:
    return {p.identifier for p in op.get_rna_type().properties}


def run(args: dict) -> dict:
    path = args.get("filepath")
    if not path:
        return C.result_error("filepath required")
    C.ensure_dir(os.path.dirname(path))
    scene = bpy.context.scene
    if args.get("fps"):
        scene.render.fps = int(args["fps"])

    names = args.get("objects")
    objs = [bpy.data.objects[n] for n in names] if names else [o for o in scene.objects if o.visible_get()]
    for o in scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]

    # temporary action renames
    rename = dict(args.get("clip_names") or {})
    prefix = args.get("strip_prefix", "AN_")
    for a in bpy.data.actions:
        if a.name not in rename and prefix and a.name.startswith(prefix):
            rename[a.name] = a.name[len(prefix):]
    restore = {}
    for old, new in rename.items():
        act = bpy.data.actions.get(old)
        if act and new and new != old:
            act.name = new
            restore[act.name] = old

    wanted = {
        "filepath": path,
        "export_format": "GLB",
        "use_selection": True,
        "export_yup": True,
        "export_apply": True,
        "export_texcoords": True,
        "export_normals": True,
        "export_materials": "EXPORT",
        "export_image_format": "AUTO",
        "export_skins": True,
        "export_influence_nb": int(args.get("max_influences", 4)),
        "export_all_influences": False,
        "export_def_bones": bool(args.get("deform_bones_only", True)),
        "export_animations": True,
        "export_animation_mode": "ACTIONS",
        "export_force_sampling": True,
        "export_frame_step": 1,
        "export_optimize_animation_size": False,
        "export_anim_slide_to_zero": True,      # every clip starts at t=0 (web runtimes expect this)
        "export_morph": True,
        "export_draco_mesh_compression_enable": False,
        "export_meshopt_compression_enable": False,
    }
    supported = _supported(bpy.ops.export_scene.gltf)
    kwargs = {k: v for k, v in wanted.items() if k in supported}
    skipped = sorted(set(wanted) - set(kwargs))
    try:
        bpy.ops.export_scene.gltf(**kwargs)
    finally:
        for new, old in restore.items():
            act = bpy.data.actions.get(new)
            if act:
                act.name = old

    if not os.path.exists(path):
        return C.result_error("export finished but file missing", kwargs=kwargs)
    info = {"filepath": path, "bytes": os.path.getsize(path), "objects": [o.name for o in objs],
            "clip_renames": rename, "settings": kwargs, "unsupported_settings": skipped,
            "blender": bpy.app.version_string}
    if args.get("project_dir"):
        info["written"] = C.write_json(os.path.join(args["project_dir"], "reports", "export.json"), info)
    return C.result_ok(**info)
