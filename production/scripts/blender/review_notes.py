"""Review notes: publish a model to the local viewer, read the user's pinned notes back as exact Blender data.

The viewer (production/review/viewer.html, served by production/scripts/review/serve.py on 127.0.0.1) lets
the user click a point on the model and pin a note. Each note stores the point in Blender coordinates —
posed (as seen at that frame) and REST (undeformed, so it matches the mesh data whatever frame it was
picked at) — the object, the skin weights under the point, the clip and Blender frame, and the camera.
This script turns notes into things Claude can act on without guessing from a screenshot.

args:
    mode         (str, required)  "publish" | "serve" | "stop" | "context" | "reply" | "view"
    project_dir  (str, required)  project folder (projects/<name>); review files live in <project>/review/
    -- publish --
    objects      (list[str])      objects to export (default: visible meshes + armatures of the scene)
    clips        (list[str])      actions to include (default: every action, as export_glb does)
    clip_names   (dict)           {"AN_walk": "walk"} as export_glb
    keep_previous (bool, True)    move review/current.glb to review/previous.glb first (before/after view)
    -- serve / stop --
    port         (int, 8765)
    -- context --
    ids          (list[str])      notes to resolve (default: every note with status "open")
    status       (str, "open")    "open" | "all"
    radius_mm    (float)          region radius around the point (default: 1.5 % of the object's size, ≥ 2 mm)
    mark         (bool, False)    also write the region into a vertex group "REVIEW_<id>" (weight 1.0) so the
                                  next scripts can target exactly those vertices (modifies the object)
    -- reply --
    id, text     (str)            reply shown under the note in the viewer
    status       (str, "resolved") "resolved" | "open" | "wontfix"
    measures     (dict)           numbers before → after (shown to the user, kept in notes.json)
    -- view --
    id           (str)            set the 3D viewport to the note's camera, the note's action and frame

returns per mode; context → {notes: [{id, text, category, object, region{verts, indices, center, radius_mm},
nearest_vertex{index, dist_mm}, frame, action, posed_check_mm, weights_at_point, region_weights,
nearest_bones, parent_bone, warnings}]}
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import runpy
import struct
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree


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
HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
SERVE = os.path.join(os.path.dirname(HERE), "review", "serve.py")


def _serve_module():
    """The server module, loaded once per Blender session (it keeps the running servers)."""
    mod = sys.modules.get("u3d_review_serve")
    if mod is None:
        spec = importlib.util.spec_from_file_location("u3d_review_serve", SERVE)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["u3d_review_serve"] = mod
        spec.loader.exec_module(mod)
    return mod


def _glb_animations(path):
    raw = open(path, "rb").read()
    jl, = struct.unpack_from("<I", raw, 12)
    gj = json.loads(raw[20:20 + jl])
    out = {}
    for an in gj.get("animations", []):
        ts = [(gj["accessors"][s["input"]].get("min", [0])[0], gj["accessors"][s["input"]].get("max", [0])[0])
              for s in an["samplers"]]
        out[an.get("name", "")] = (min(t[0] for t in ts), max(t[1] for t in ts))
    return out


# ---------------------------------------------------------------- publish
def publish(args):
    proj = args["project_dir"]
    rdir = C.ensure_dir(os.path.join(proj, "review"))
    cur, prev = os.path.join(rdir, "current.glb"), os.path.join(rdir, "previous.glb")
    had_prev = False
    if os.path.exists(cur) and args.get("keep_previous", True):
        os.replace(cur, prev)
        had_prev = True
    objs = args.get("objects")
    if not objs:
        objs = [o.name for o in bpy.context.scene.objects if o.type in ("MESH", "ARMATURE") and o.visible_get()]
    ex = runpy.run_path(os.path.join(HERE, "export_glb.py"))
    eargs = {"filepath": cur, "objects": objs, "clip_names": args.get("clip_names") or {}}
    if args.get("clips") is not None:
        eargs["clips"] = args["clips"]
    res = ex["run"](eargs)
    if not res.get("ok"):
        if had_prev and not os.path.exists(cur):
            os.replace(prev, cur)
        return res
    renames = res.get("clip_renames") or {}
    back = {new: old for old, new in renames.items()}
    sc = bpy.context.scene
    fps = sc.render.fps / (sc.render.fps_base or 1.0)
    clips = {}
    for name, (t0, t1) in _glb_animations(cur).items():
        act = bpy.data.actions.get(back.get(name, name)) or bpy.data.actions.get(name)
        fs = float(act.frame_range[0]) if act else 0.0
        clips[name] = {"action": act.name if act else None, "frame_start": fs,
                       "frame_end": float(act.frame_range[1]) if act else None,
                       "gltf_t0": round(t0, 5), "duration_s": round(t1 - t0, 5)}
    manifest = {"published": C.now_iso(), "fps": fps, "objects": res.get("objects"), "clips": clips,
                "previous": os.path.exists(prev), "blend_file": bpy.data.filepath or None,
                "coords": "notes store Blender Z-up world coordinates; the GLB is Y-up",
                "frame_rule": "blender_frame = frame_start + (time_s - gltf_t0) * fps"}
    C.write_json(os.path.join(rdir, "manifest.json"), manifest)
    return C.result_ok(glb=cur, previous=prev if os.path.exists(prev) else None, bytes=res.get("bytes"),
                       clips=list(clips), objects=res.get("objects"))


# ---------------------------------------------------------------- context
def _read(proj):
    return _serve_module().read_notes(proj)


def _manifest(proj):
    return C.read_json(os.path.join(proj, "review", "manifest.json"), {}) or {}


def _kd(ob):
    mw = ob.matrix_world
    co = [mw @ v.co for v in ob.data.vertices]
    kd = KDTree(len(co))
    for i, c in enumerate(co):
        kd.insert(c, i)
    kd.balance()
    return kd, co


def _seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / (ab.length_squared or 1e-12)))
    return (a + ab * t - p).length


def _frame_of(note, man):
    clip = note.get("clip")
    if not clip:
        return None, None
    info = (man.get("clips") or {}).get(clip)
    if info and note.get("time_s") is not None:
        f = info["frame_start"] + (float(note["time_s"]) - info.get("gltf_t0", 0.0)) * float(man.get("fps", 24))
        return f, info.get("action")
    return (float(note["frame"]) if note.get("frame") is not None else None), note.get("action")


def _posed_vertex(ob, arm, action, frame, vi):
    """World position of one vertex of ob with `action` on arm at `frame` (restores everything)."""
    sc = bpy.context.scene
    ad = arm.animation_data or arm.animation_data_create()
    prev_act, prev_slot, f_prev = ad.action, getattr(ad, "action_slot", None), sc.frame_current
    act = bpy.data.actions.get(action) if action else None
    try:
        if act is not None:
            ad.action = act
            if getattr(act, "slots", None) and len(act.slots):
                ad.action_slot = act.slots[0]
        sc.frame_set(int(math.floor(frame)), subframe=frame - math.floor(frame))
        return Vector(C.evaluated_vertex_positions(ob)[vi])
    finally:
        ad.action = prev_act
        if prev_act is not None and prev_slot is not None:
            try:
                ad.action_slot = prev_slot
            except (TypeError, RuntimeError):
                pass
        sc.frame_set(f_prev)


def context(args):
    proj = args["project_dir"]
    data = _read(proj)
    man = _manifest(proj)
    ids = set(args.get("ids") or [])
    want_all = args.get("status") == "all"
    out, cache = [], {}
    win = bpy.context.window
    for idx, n in enumerate(data.get("notes", [])):
        if ids and n.get("id") not in ids:
            continue
        if not ids and not want_all and n.get("status", "open") != "open":
            continue
        frame, action = _frame_of(n, man)
        e = {"id": n.get("id"), "num": idx + 1, "text": n.get("text"), "category": n.get("category"),
             "scope": n.get("scope", "point"), "object": n.get("object"), "clip": n.get("clip"),
             "action": action, "frame": round(frame, 2) if frame is not None else None,
             "weights_at_point": n.get("weights"), "parent_bone": n.get("parent_bone"), "warnings": []}
        ob = bpy.data.objects.get(n.get("object") or "")
        if e["scope"] == "model" or not n.get("rest_point"):
            out.append(e)
            continue
        if ob is None or ob.type != "MESH":
            e["warnings"].append(f"object {n.get('object')!r} not in this .blend — renamed, or the note is from another model")
            out.append(e)
            continue
        prev_scene = None
        if bpy.context.scene not in ob.users_scene and ob.users_scene and win is not None:
            prev_scene, win.scene = win.scene, ob.users_scene[0]
        try:
            if ob.name not in cache:
                cache[ob.name] = _kd(ob)
            kd, co = cache[ob.name]
            P = Vector(n["rest_point"])
            size = max(ob.dimensions) or 1.0
            r = float(args["radius_mm"]) / 1000 if args.get("radius_mm") else max(0.002, 0.015 * size)
            near_co, near_i, near_d = kd.find(P)
            region = kd.find_range(P, r)
            region.sort(key=lambda x: x[2])
            vids = [i for _, i, _ in region] or [near_i]
            e["nearest_vertex"] = {"index": near_i, "dist_mm": round(near_d * 1000, 2)}
            e["region"] = {"verts": len(vids), "indices": vids[:int(args.get("max_indices", 60))],
                           "center": [round(x, 5) for x in P], "radius_mm": round(r * 1000, 2)}
            if near_d > max(r, 0.005):
                e["warnings"].append(f"nearest vertex {near_d * 1000:.1f} mm away: the mesh changed since it was "
                                     "published, or the note belongs to another object — republish and re-check")
            # weights over the region
            arm = ob.find_armature()
            groups = {g.index: g.name for g in ob.vertex_groups}
            deform = {b.name for b in arm.data.bones if b.use_deform} if arm else None
            acc = {}
            for vi in vids:
                for g in ob.data.vertices[vi].groups:
                    nm = groups.get(g.group)
                    if nm and (deform is None or nm in deform) and g.weight > 1e-4:
                        acc[nm] = acc.get(nm, 0.0) + g.weight
            tot = sum(acc.values()) or 1.0
            e["region_weights"] = [[k, round(v / tot, 3)] for k, v in sorted(acc.items(), key=lambda kv: -kv[1])[:5]]
            if arm:
                mw = arm.matrix_world
                d = sorted(((_seg_dist(P, mw @ b.head_local, mw @ b.tail_local), b.name)
                            for b in arm.data.bones if b.use_deform), key=lambda x: x[0])[:3]
                e["nearest_bones"] = [[nm, round(dd * 1000, 1)] for dd, nm in d]
                if frame is not None and n.get("posed_point"):
                    pv = _posed_vertex(ob, arm, action, frame, near_i)
                    e["posed_check_mm"] = round((pv - Vector(n["posed_point"])).length * 1000, 2)
                    if e["posed_check_mm"] > max(r * 1000, 5):
                        e["warnings"].append("posed position differs from what the viewer showed: the clip or rig "
                                             "changed since publishing (republish), or the frame mapping is off")
            if args.get("mark"):
                vg_name = f"REVIEW_{n.get('id')}"
                vg = ob.vertex_groups.get(vg_name) or ob.vertex_groups.new(name=vg_name)
                vg.add(vids, 1.0, "REPLACE")
                e["vertex_group"] = vg_name
        finally:
            if prev_scene is not None:
                win.scene = prev_scene
        out.append(e)
    return C.result_ok(project=proj, manifest_published=man.get("published"), notes=out,
                       open=sum(1 for n in data.get("notes", []) if n.get("status", "open") == "open"))


# ---------------------------------------------------------------- reply / view
def reply(args):
    proj, nid = args["project_dir"], args.get("id")
    srv = _serve_module()
    data = srv.read_notes(proj)
    note = next((n for n in data.get("notes", []) if n.get("id") == nid), None)
    if note is None:
        return C.result_error(f"no note {nid}")
    replies = list(note.get("replies") or [])
    rep = {"by": args.get("by", "claude"), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "text": args.get("text", "")}
    if args.get("measures"):
        rep["measures"] = args["measures"]
    replies.append(rep)
    stored = srv.upsert_note(proj, {"id": nid, "status": args.get("status", "resolved"), "replies": replies})
    return C.result_ok(note=stored)


def view(args):
    proj, nid = args["project_dir"], args.get("id")
    note = next((n for n in _read(proj).get("notes", []) if n.get("id") == nid), None)
    if note is None:
        return C.result_error(f"no note {nid}")
    man = _manifest(proj)
    frame, action = _frame_of(note, man)
    ob = bpy.data.objects.get(note.get("object") or "")
    arm = ob.find_armature() if ob is not None and ob.type == "MESH" else None
    if arm is not None and action and bpy.data.actions.get(action):
        ad = arm.animation_data or arm.animation_data_create()
        ad.action = bpy.data.actions[action]
        if len(ad.action.slots):
            ad.action_slot = ad.action.slots[0]
    if frame is not None:
        bpy.context.scene.frame_set(int(round(frame)))
    cam = note.get("camera") or {}
    done = False
    if cam.get("position") and cam.get("target"):
        pos, tgt = Vector(cam["position"]), Vector(cam["target"])
        for area in bpy.context.window.screen.areas:
            if area.type == "VIEW_3D":
                rv3d = area.spaces.active.region_3d
                rv3d.view_perspective = "PERSP"
                rv3d.view_location = tgt
                rv3d.view_distance = (pos - tgt).length
                rv3d.view_rotation = (tgt - pos).to_track_quat("-Z", "Y")
                done = True
                break
    return C.result_ok(id=nid, frame=frame, action=action, viewport_set=done,
                       note="the armature's active action was set to the note's clip")


def run(args: dict) -> dict:
    mode = args.get("mode")
    if not args.get("project_dir"):
        return C.result_error("project_dir required")
    args["project_dir"] = os.path.abspath(args["project_dir"])
    if mode == "publish":
        return publish(args)
    if mode == "serve":
        url = _serve_module().start(args["project_dir"], int(args.get("port", 8765)))
        return C.result_ok(url=url, notes=os.path.join(args["project_dir"], "review", "notes.json"),
                           note="open the URL in a browser on this computer; the server runs inside Blender "
                                "until mode=stop or Blender quits")
    if mode == "stop":
        return C.result_ok(stopped=_serve_module().stop(int(args.get("port", 8765))))
    if mode == "context":
        return context(args)
    if mode == "reply":
        return reply(args)
    if mode == "view":
        return view(args)
    return C.result_error(f"unknown mode {mode}")
