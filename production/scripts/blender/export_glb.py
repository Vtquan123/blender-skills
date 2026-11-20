"""Export the uncompressed master GLB (web-export step 2 / export-pipeline).

Compression happens once, later, in production/scripts/node/optimize.mjs — never here.

args:
    filepath        (str, required)  e.g. projects/<name>/output/<name>.master.glb
    objects         (list[str])      objects to export (armature + meshes). Default: all visible objects in scene.
    clips           (list[str])      export only these clips (spec names or action names; "AN_" prefix optional).
                                     Other actions (AN_ROM, work-in-progress) are excluded with the glTF add-on's
                                     action filter. Default: every action (the exporter's ACTIONS mode).
    clip_names      (dict)           {"AN_Walk": "walk"} rename actions for the export, restored afterwards
    strip_prefix    (str, "AN_")     prefix removed from action names when clip_names does not cover them
    max_influences  (int, 4)
    tangents        (bool, True)     export tangents (needed for portable normal mapping; small size cost)
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


def _set_action_filter(keep_names, restore):
    """Use the glTF add-on's own action filter (scene.gltf_action_filter, items with keep=False are skipped)."""
    import io_scene_gltf2
    scene = bpy.data.scenes[0]  # the add-on reads scenes[0]
    created = not hasattr(scene, "gltf_action_filter")
    if created:
        bpy.types.Scene.gltf_action_filter = bpy.props.CollectionProperty(type=io_scene_gltf2.GLTF2_filter_action)
        bpy.types.Scene.gltf_action_filter_active = bpy.props.IntProperty()
    prev = [(item.action, item.keep) for item in scene.gltf_action_filter]
    scene.gltf_action_filter.clear()
    excluded = []
    for act in bpy.data.actions:
        original = restore.get(act.name, act.name)
        item = scene.gltf_action_filter.add()
        item.action = act
        item.keep = act.name in keep_names or original in keep_names
        if not item.keep:
            excluded.append(original)
    return {"created": created, "prev": prev, "excluded": sorted(excluded)}


def _clear_action_filter(state):
    scene = bpy.data.scenes[0]
    scene.gltf_action_filter.clear()
    if state["created"]:
        del bpy.types.Scene.gltf_action_filter
        del bpy.types.Scene.gltf_action_filter_active
    else:
        for act, keep in state["prev"]:
            item = scene.gltf_action_filter.add()
            item.action, item.keep = act, keep


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
    # hidden objects cannot be selected, and use_selection would silently drop them (an armature hidden in
    # the viewport exports a mesh with no skin and no clips): unhide for the export, restore afterwards
    hidden = [o for o in objs if o.hide_get() or o.hide_viewport or o.hide_select]
    prev_hide = {o.name: (o.hide_get(), o.hide_viewport, o.hide_select) for o in hidden}
    for o in hidden:
        o.hide_viewport = False
        o.hide_select = False
        o.hide_set(False)
    for o in objs:
        o.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]
    not_selected = [o.name for o in objs if not o.select_get()]
    if not_selected:
        for o in hidden:
            h, hv, hs = prev_hide[o.name]
            o.hide_set(h)
            o.hide_viewport, o.hide_select = hv, hs
        return C.result_error(f"could not select objects for export (excluded from the view layer?): {not_selected}")

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
        "use_active_scene": True,                # other scenes in the .blend would export as empty scenes (G6 error)
        "export_yup": True,
        "export_apply": True,
        "export_texcoords": True,
        "export_normals": True,
        "export_tangents": bool(args.get("tangents", True)),  # normal-mapped materials: portable tangent space
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
    excluded, filter_state = [], None
    if args.get("clips") is not None and "export_action_filter" in supported:
        keep = set(args["clips"]) | {prefix + c for c in args["clips"]} | {rename.get(prefix + c, c) for c in args["clips"]}
        filter_state = _set_action_filter(keep, restore)
        excluded = filter_state["excluded"]
        wanted["export_action_filter"] = True
    kwargs = {k: v for k, v in wanted.items() if k in supported}
    skipped = sorted(set(wanted) - set(kwargs))
    try:
        bpy.ops.export_scene.gltf(**kwargs)
    finally:
        for name, (h, hv, hs) in prev_hide.items():
            o = bpy.data.objects.get(name)
            if o:
                o.hide_set(h)
                o.hide_viewport, o.hide_select = hv, hs
        if filter_state is not None:
            _clear_action_filter(filter_state)
        for new, old in restore.items():
            act = bpy.data.actions.get(new)
            if act:
                act.name = old

    if not os.path.exists(path):
        return C.result_error("export finished but file missing", kwargs=kwargs)
    info = {"filepath": path, "bytes": os.path.getsize(path), "objects": [o.name for o in objs],
            "excluded_actions": excluded,
            "clip_renames": rename, "settings": kwargs, "unsupported_settings": skipped,
            "blender": bpy.app.version_string}
    if args.get("project_dir"):
        info["written"] = C.write_json(os.path.join(args["project_dir"], "reports", "export.json"), info)
    return C.result_ok(**info)
