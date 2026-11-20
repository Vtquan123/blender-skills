"""Preview clip of a rigged asset (Production Mode PREVIEW, animation review, G5 evidence).

Builds a separate scene with linked COPIES of the rig and its meshes (the working objects and actions are
not modified), a checker ground, sun + fill light, a camera that follows the root, the clip repeated on an
NLA track and optional root motion for in-place cycles. Renders PNG frames in chunks so each MCP call stays
short; encode afterwards, e.g.
    ffmpeg -framerate 30 -i frames/<prefix>%04d.png -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p out.mp4

args (mode "setup"):
    rig            (str, required)   armature object
    meshes         (list[str])       skinned meshes (default: meshes whose Armature modifier uses the rig)
    action         (str, required)   action to play, e.g. "AN_walk"
    repeat         (int, 4)          number of cycles
    root_velocity  (list[float])     m/s in rig space for in-place cycles, e.g. [0.05, 0, 0]; default no motion
    scene          (str)             default "PREVIEW_<action>"
    camera_offset  (list[float])     camera position relative to the root (metres); default from the asset size
    target_offset  (list[float])     look-at point relative to the root; default bbox centre
    resolution     (list[int])       [1280, 720]
    fps            (int)             default scene fps of the source
    engine         (str)             "BLENDER_EEVEE" (default) or "CYCLES"
    background     (list[float])     world colour RGB 0-1 (match a reference video), default light blue-grey
    ground_colors  (list[list])      two RGB checker colours; [c, c] for a plain floor
args (mode "render"):
    scene          (str, required)
    out_dir        (str, required)   frames are written as <out_dir>/<prefix>NNNN.png
    prefix         (str, "frame_")
    frame_start, frame_end (int)     chunk to render (default: whole scene range)

Returns dict with scene name, frame range and written frames.
"""
import importlib.util
import math
import os
import sys

import bpy
from mathutils import Vector


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
PREFIX = "PRV_"


def _clear_scene(name):
    sc = bpy.data.scenes.get(name)
    if sc is None:
        return
    for o in list(sc.objects):
        if o.name.startswith(PREFIX):
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None and getattr(data, "users", 1) == 0 and isinstance(data, (bpy.types.Light, bpy.types.Camera)):
                (bpy.data.lights if isinstance(data, bpy.types.Light) else bpy.data.cameras).remove(data)
    for a in [a for a in bpy.data.actions if a.name == f"{PREFIX}root_{name}"]:
        bpy.data.actions.remove(a)
    bpy.data.scenes.remove(sc)


def _engine_id(wanted):
    items = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    if wanted in items:
        return wanted
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in items else items[0]


def _fcurves(action, slot):
    try:
        from bpy_extras import anim_utils
        return anim_utils.action_get_channelbag_for_slot(action, slot).fcurves
    except Exception:
        return getattr(action, "fcurves", [])


def setup(args):
    src_rig = bpy.data.objects.get(args.get("rig", ""))
    act = bpy.data.actions.get(args.get("action", ""))
    if src_rig is None or src_rig.type != "ARMATURE" or act is None:
        return C.result_error("rig (armature) and action required")
    meshes = [bpy.data.objects[n] for n in args["meshes"]] if args.get("meshes") else [
        o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == src_rig for m in o.modifiers)]
    if not meshes:
        return C.result_error("no skinned meshes found for the rig")
    name = args.get("scene") or f"PREVIEW_{act.name}"
    src_scene = src_rig.users_scene[0] if src_rig.users_scene else bpy.context.scene
    fps = int(args.get("fps") or src_scene.render.fps)
    _clear_scene(name)
    sc = bpy.data.scenes.new(name)

    rig = src_rig.copy()
    rig.name = f"{PREFIX}rig"
    # keep the copy's DRIVERS (Rigify IK/FK switches, follow sliders); drop only the action and NLA tracks.
    # animation_data_clear() would remove the drivers too and freeze the limbs in whatever mode they were in.
    if rig.animation_data:
        rig.animation_data.action = None
        for t in list(rig.animation_data.nla_tracks):
            rig.animation_data.nla_tracks.remove(t)
    drv_targets = {v.targets[0].id for d in (rig.animation_data.drivers if rig.animation_data else [])
                   for v in d.driver.variables if v.targets and v.targets[0].id is not None}
    if src_rig in drv_targets:
        return C.result_error("copied rig drivers still point at the source rig; cannot build an independent preview")
    rig.hide_render = True
    sc.collection.objects.link(rig)
    for pb in rig.pose.bones:
        pb.matrix_basis.identity()
    copies = []
    for m in meshes:
        c = m.copy()
        c.name = f"{PREFIX}{m.name}"
        if c.parent == src_rig:
            c.parent = rig
        for mod in c.modifiers:
            if mod.type == "ARMATURE" and mod.object == src_rig:
                mod.object = rig
        sc.collection.objects.link(c)
        copies.append(c)

    # clip on an NLA strip, repeated
    f0, f1 = act.frame_range
    length = max(1.0, f1 - f0)
    repeat = int(args.get("repeat", 4))
    ad = rig.animation_data_create()
    track = ad.nla_tracks.new()
    track.name = act.name
    strip = track.strips.new(act.name, 1, act)
    if hasattr(strip, "action_slot") and len(getattr(act, "slots", [])):
        strip.action_slot = act.slots[0]
    strip.action_frame_start, strip.action_frame_end = f0, f1
    strip.repeat = repeat
    frame_end = 1 + int(round(length * repeat))

    # root motion (in-place cycles)
    vel = Vector(args.get("root_velocity") or (0.0, 0.0, 0.0))
    if vel.length > 0:
        root = bpy.data.actions.new(f"{PREFIX}root_{name}")
        ad.action = root
        rig.location = (0.0, 0.0, 0.0)
        rig.keyframe_insert("location", frame=1)
        rig.location = vel * ((frame_end - 1) / fps)
        rig.keyframe_insert("location", frame=frame_end)
        for fc in _fcurves(root, ad.action_slot):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
        rig.location = (0.0, 0.0, 0.0)

    # framing from the rest-pose bbox
    mn, mx = C.world_bbox(meshes)
    mn, mx = Vector(mn), Vector(mx)
    size = max((mx - mn).length, 1e-3)
    centre = (mn + mx) / 2

    ground_mesh = bpy.data.meshes.new(f"{PREFIX}ground")
    g = 4.0 * size + vel.length * frame_end / fps * 2
    ground_mesh.from_pydata([(-g, -g, 0), (g, -g, 0), (g, g, 0), (-g, g, 0)], [], [(0, 1, 2, 3)])
    ground_mesh.uv_layers.new()
    ground = bpy.data.objects.new(f"{PREFIX}ground", ground_mesh)
    ground.location = (centre.x, centre.y, mn.z - 0.0005 * size)
    sc.collection.objects.link(ground)
    mat = bpy.data.materials.new(f"{PREFIX}ground_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    chk = nt.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 2 * g / (0.2 * size)   # squares ≈ 10 % of the asset size
    c1, c2 = args.get("ground_colors") or ((0.62, 0.60, 0.56), (0.52, 0.50, 0.47))
    chk.inputs["Color1"].default_value = (*c1, 1)
    chk.inputs["Color2"].default_value = (*c2, 1)
    nt.links.new(chk.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    ground_mesh.materials.append(mat)

    sun_d = bpy.data.lights.new(f"{PREFIX}sun", "SUN")
    sun_d.energy, sun_d.angle = 3.5, math.radians(8)
    sun = bpy.data.objects.new(f"{PREFIX}sun", sun_d)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(-35))
    sc.collection.objects.link(sun)
    fill_d = bpy.data.lights.new(f"{PREFIX}fill", "AREA")
    fill_d.energy, fill_d.size = 60.0 * size * size, size * 4
    fill = bpy.data.objects.new(f"{PREFIX}fill", fill_d)
    fill.parent = rig
    fill.location = centre + Vector((size, -3 * size, 2 * size))
    fill.rotation_euler = (math.radians(60), 0, math.radians(-10))
    sc.collection.objects.link(fill)
    world = bpy.data.worlds.new(f"{PREFIX}world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*(args.get("background") or (0.78, 0.84, 0.92)), 1)
    bg.inputs["Strength"].default_value = 0.9
    sc.world = world

    target = bpy.data.objects.new(f"{PREFIX}target", None)
    target.parent = rig
    target.location = Vector(args["target_offset"]) if args.get("target_offset") else centre
    sc.collection.objects.link(target)
    cam_d = bpy.data.cameras.new(f"{PREFIX}cam")
    cam_d.lens = 50
    cam = bpy.data.objects.new(f"{PREFIX}cam", cam_d)
    cam.parent = rig
    cam.location = Vector(args["camera_offset"]) if args.get("camera_offset") else centre + Vector((1.1, -2.4, 0.5)) * size * 1.0
    tt = cam.constraints.new("TRACK_TO")
    tt.target, tt.track_axis, tt.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    sc.collection.objects.link(cam)
    sc.camera = cam

    r = sc.render
    r.engine = _engine_id(args.get("engine", "BLENDER_EEVEE"))
    r.resolution_x, r.resolution_y = (args.get("resolution") or (1280, 720))
    r.resolution_percentage = 100
    r.fps = fps
    r.image_settings.file_format = "PNG"
    sc.frame_start, sc.frame_end = 1, frame_end
    items = [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items]
    sc.view_settings.view_transform = "AgX" if "AgX" in items else "Filmic"
    sc.view_settings.exposure = -0.3
    return C.result_ok(scene=sc.name, frame_range=[1, frame_end], fps=fps, objects=[o.name for o in sc.objects],
                       next="render in chunks of ~60 frames (mode: render), then encode with ffmpeg")


def render(args):
    sc = bpy.data.scenes.get(args.get("scene", ""))
    if sc is None:
        return C.result_error("scene not found; run mode=setup first")
    out_dir = C.ensure_dir(args["out_dir"])
    prefix = args.get("prefix", "frame_")
    full = (sc.frame_start, sc.frame_end)
    sc.frame_start = int(args.get("frame_start", full[0]))
    sc.frame_end = int(args.get("frame_end", full[1]))
    sc.render.filepath = os.path.join(out_dir, prefix)
    sc.render.image_settings.file_format = "PNG"
    try:
        bpy.ops.render.render(animation=True, scene=sc.name)
    finally:
        written = [sc.frame_start, sc.frame_end]
        sc.frame_start, sc.frame_end = full
    return C.result_ok(scene=sc.name, rendered=written, pattern=os.path.join(out_dir, prefix + "%04d.png"))


def run(args: dict) -> dict:
    mode = args.get("mode", "setup")
    if mode == "setup":
        return setup(args)
    if mode == "render":
        return render(args)
    return C.result_error(f"unknown mode {mode}; use setup or render")
