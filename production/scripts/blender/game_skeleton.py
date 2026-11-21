"""Game-ready skeleton: audit a rig for engine export, or build a clean export skeleton from it.

The problems are the ones GameRig (Arminando/GameRig, GPL-2) was written to solve inside Rigify — deform
bones spread over several hierarchies (DEF-thigh under ORG-pelvis, DEF-spine under the non-deform root),
scaled deform bones, B-Bones whose bend no engine reproduces. GameRig changes Rigify's rig types; this
script works on ANY generated rig instead and uses none of GameRig's code: it reads the deform bones and
builds a separate deform-only armature that follows them (the common "export rig" pattern), then bakes
the clips onto it. The control rig stays untouched for animating; the export rig is what ships.
Rig density checks (deform bones per vertex, dead bones) follow blender-kiln's rule 26 (MIT).

args:
    armature      (str, required)   control rig (Rigify or any armature with deform bones)
    mode          (str, "audit")    "audit" | "export_rig"
    meshes        (list[str])       skinned meshes (default: every mesh deformed by the armature)
    actions       (list[str])       clips to check (audit: sampled for scale) / bake (export_rig).
                                    "AN_*" style fnmatch patterns allowed. Default audit: none; export: none
    sample_frames (int, 8)          frames sampled per action in the audit
    -- export_rig --
    name          (str)             export armature name (default "<armature>_game")
    root          (str, "root")     name of the single root bone (created at the origin; follows the
                                    control rig's own root bone when it has one, so root motion is kept)
    rename        ("keep"|"strip_def"|dict, "strip_def")  bone names on the export rig; vertex groups follow
    keep_scale    (bool, False)     copy scale too (default: location + rotation only — engines and glTF
                                    viewers handle scaled joints differently from Blender)
    action_suffix (str, "_game")    baked action names: "<action><suffix>" (export_glb clip_names renames)
    frame_step    (int, 1)
    mesh_mode     (str, "copy")     "copy": duplicate the skinned meshes onto the export rig (originals kept)
                                    "retarget": point the original meshes' Armature modifier at the export rig
                                    "none": skeleton only
    collection    (str, "COL_GameExport")
    keep_constraints (bool)         default: removed after baking (the export rig then plays its own clips);
                                    kept when nothing was baked, so the export rig follows the controls live
    project_dir   (str)             write reports/game-skeleton.json

returns: audit {deform_bones, roots, non_deform_parents, bbones, scaled, stretch, weights, density,
         problems, verdict}; export_rig adds {export_rig, bones, roots, hierarchy, baked, meshes,
         parity_mm (bone heads and skin, control rig vs export rig, on sampled frames)}
"""
from __future__ import annotations

import fnmatch
import importlib.util
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector


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
PREFIXES = ("DEF-", "ORG-", "MCH-")


# ---------------------------------------------------------------- hierarchy
def deform_parent_map(arm):
    """{deform bone: parent deform bone or None}, following the rig's own hierarchy.

    Walk up from each deform bone: the first deform ancestor wins; a non-deform ancestor named ORG-x / x
    maps to DEF-x when that exists (Rigify parents DEF-thigh to ORG-pelvis, whose deform twin is
    DEF-pelvis... or further up, DEF-spine). A twin that hangs under the bone itself is skipped (Rigify
    tails); any cycle left is broken at the root.
    """
    bones = arm.data.bones
    deform = {b.name for b in bones if b.use_deform}

    def twin(name):
        core = name
        for p in PREFIXES:
            if core.startswith(p):
                core = core[len(p):]
                break
        for cand in ("DEF-" + core, core):
            if cand in deform:
                return cand
        return None

    def below(cand, name):
        """cand hangs (directly or not) under name in the rig: taking it as parent would loop."""
        a = bones[cand].parent
        while a is not None:
            if a.name == name:
                return True
            a = a.parent
        return False

    pmap = {}
    for name in deform:
        b, parent = bones[name], None
        a = b.parent
        while a is not None:
            if a.name in deform and a.name != name:
                parent = a.name
                break
            t = twin(a.name)
            # Rigify tails run the DEF chain opposite to the ORG chain: the ORG ancestors' twins are this
            # bone's own children — skip them and keep climbing to the body
            if t and t != name and not below(t, name):
                parent = t
                break
            a = a.parent
        pmap[name] = parent
    for name in list(pmap):  # break cycles
        seen, cur = {name}, pmap[name]
        while cur is not None:
            if cur in seen:
                pmap[name] = None
                break
            seen.add(cur)
            cur = pmap.get(cur)
    return pmap


def _depth(pmap, n):
    d = 0
    while pmap.get(n):
        n = pmap[n]
        d += 1
    return d


def _new_name(name, rename):
    if isinstance(rename, dict):
        return rename.get(name, name)
    if rename == "strip_def" and name.startswith("DEF-"):
        return name[4:]
    return name


def _skinned(arm, names):
    if names:
        return [bpy.data.objects[n] for n in names if n in bpy.data.objects]
    return [o for o in bpy.data.objects if o.type == "MESH" and any(
        m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]


def _actions(patterns):
    if not patterns:
        return []
    out = []
    for a in bpy.data.actions:
        if any(fnmatch.fnmatch(a.name, p) for p in patterns) and a not in out:
            out.append(a)
    return out


def _assign(obj, act):
    ad = obj.animation_data or obj.animation_data_create()
    ad.action = act
    if act is not None and getattr(act, "slots", None) and len(act.slots):
        ad.action_slot = act.slots[0]


# ---------------------------------------------------------------- audit
def weights_report(arm, meshes, deform):
    total_v, dead, over4, unweighted, to_non_deform = 0, set(deform), 0, 0, set()
    bone_names = {b.name for b in arm.data.bones}
    for ob in meshes:
        names = [g.name for g in ob.vertex_groups]
        is_def = [n in deform for n in names]
        used = np.zeros(len(names), dtype=bool)
        for v in ob.data.vertices:
            infl = [g for g in v.groups if g.weight > 1e-4 and g.group < len(names)]
            d = [g for g in infl if is_def[g.group]]
            for g in infl:
                if g.weight > 0.01:
                    used[g.group] = True
                    if not is_def[g.group] and names[g.group] in bone_names:
                        to_non_deform.add(names[g.group])
            over4 += len(d) > 4
            unweighted += len(d) == 0
        total_v += len(ob.data.vertices)
        dead -= {names[i] for i in range(len(names)) if used[i]}
    return {"vertices": total_v, "dead_deform_bones": sorted(dead), "verts_over_4_influences": over4,
            "unweighted_verts": unweighted, "weights_on_non_deform_bones": sorted(to_non_deform)}


def scale_report(arm, acts, n_samples):
    worst, bones = 0.0, {}
    sc = bpy.context.scene
    ad = arm.animation_data or arm.animation_data_create()
    prev, prev_slot = ad.action, getattr(ad, "action_slot", None)
    f_cur = sc.frame_current
    deform = [pb for pb in arm.pose.bones if pb.bone.use_deform]
    try:
        for act in acts:
            _assign(arm, act)
            f0, f1 = act.frame_range
            for fr in np.linspace(f0, f1, max(2, n_samples)):
                sc.frame_set(int(round(fr)))
                for pb in deform:
                    rest = pb.bone.matrix_local.to_scale()
                    s = pb.matrix.to_scale()
                    dev = max(abs(s[i] / rest[i] - 1.0) for i in range(3))
                    if dev > 0.01:
                        bones[pb.name] = max(bones.get(pb.name, 0.0), dev)
                    worst = max(worst, dev)
    finally:
        ad.action = prev
        if prev is not None and prev_slot is not None:
            try:
                ad.action_slot = prev_slot
            except (TypeError, RuntimeError):
                pass
        sc.frame_set(f_cur)
    top = sorted(bones.items(), key=lambda kv: -kv[1])[:10]
    return {"max_scale_deviation": round(worst, 4), "scaled_bones": len(bones),
            "worst": [(k, round(v, 3)) for k, v in top]}


def audit(arm, args):
    bones = arm.data.bones
    deform = {b.name for b in bones if b.use_deform}
    pmap = deform_parent_map(arm)
    roots = sorted(n for n, p in pmap.items() if p is None)
    non_def_parent = sorted(b.name for b in bones if b.use_deform and b.parent is not None and not b.parent.use_deform)
    bb = sorted(b.name for b in bones if b.use_deform and b.bbone_segments > 1)
    stretch = sorted(pb.name for pb in arm.pose.bones if pb.bone.use_deform and any(
        c.type in ("STRETCH_TO", "MAINTAIN_VOLUME") and not c.mute for c in pb.constraints))
    meshes = _skinned(arm, args.get("meshes"))
    w = weights_report(arm, meshes, deform) if meshes else None
    acts = _actions(args.get("actions"))
    sc = scale_report(arm, acts, int(args.get("sample_frames", 8))) if acts else None
    problems, notes = [], []
    if len(roots) > 1:
        problems.append(f"{len(roots)} deform roots ({', '.join(roots[:6])}) — engines want one skeleton root "
                        "(Unreal refuses several); export_rig builds one")
    if non_def_parent:
        notes.append(f"{len(non_def_parent)} deform bones hang from non-deform bones (e.g. {non_def_parent[0]} under "
                     f"{bones[non_def_parent[0]].parent.name}): an FBX export of deform bones only re-parents them "
                     "unpredictably; glTF keeps them as extra roots")
    if bb:
        problems.append(f"{len(bb)} deform bones use B-Bone segments ({', '.join(bb[:4])}) — no engine bends them; "
                        "Blender and the runtime will differ")
    if sc and sc["max_scale_deviation"] > 0.02:
        problems.append(f"deform bones scale up to {sc['max_scale_deviation']:.1%} in the clips "
                        f"({sc['worst'][0][0]}) — stretch/squash does not survive engine import the same way; "
                        "export_rig keeps location + rotation only")
    if stretch:
        notes.append(f"{len(stretch)} deform bones carry Stretch To / Maintain Volume: limbs can lengthen")
    density = None
    if w:
        n_def = len(deform)
        budget = max(1, w["vertices"] // 20)
        density = {"deform_bones": n_def, "vertices": w["vertices"], "verts_per_bone": round(w["vertices"] / max(n_def, 1), 1),
                   "bone_budget": budget}
        if n_def > budget:
            problems.append(f"{n_def} deform bones for {w['vertices']} vertices (budget ~{budget}: one bone per 20 "
                            "vertices) — the rig is too dense for this mesh; prune bones or use a smaller template")
        if w["dead_deform_bones"]:
            (problems if len(w["dead_deform_bones"]) > 0.1 * n_def else notes).append(
                f"{len(w['dead_deform_bones'])} deform bones move no vertex ({', '.join(w['dead_deform_bones'][:6])}) "
                "— turn off their deform flag or prune them")
        if w["verts_over_4_influences"]:
            problems.append(f"{w['verts_over_4_influences']} vertices have more than 4 deform influences "
                            "(web/mobile read 4) — skin_weights.py limit")
        if w["unweighted_verts"]:
            problems.append(f"{w['unweighted_verts']} vertices have no deform weight (they stay behind)")
        if w["weights_on_non_deform_bones"]:
            problems.append(f"weights on non-deform bones: {', '.join(w['weights_on_non_deform_bones'][:6])}")
    verdict = "ready" if not problems else ("export_rig" if all(
        ("deform roots" in p or "B-Bone" in p or "scale" in p) for p in problems) else "fix_first")
    return {"deform_bones": len(deform), "roots": roots, "non_deform_parents": non_def_parent, "bbones": bb,
            "stretch": stretch, "scaled": sc, "weights": w, "density": density, "meshes": [m.name for m in meshes],
            "problems": problems, "notes": notes, "verdict": verdict,
            "verdict_help": {"ready": "export as is", "export_rig": "run mode=export_rig and export that",
                             "fix_first": "fix weights/density, then export_rig"}[verdict]}


# ---------------------------------------------------------------- export rig
def build_export_rig(arm, args):
    pmap = deform_parent_map(arm)
    rename = args.get("rename", "strip_def")
    root_name = args.get("root", "root")
    keep_scale = bool(args.get("keep_scale", False))
    name = args.get("name") or f"{arm.name}_game"
    coll_name = args.get("collection", "COL_GameExport")
    scene = bpy.context.scene
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
        scene.collection.children.link(coll)
    elif coll.name not in {c.name for c in scene.collection.children_recursive}:
        scene.collection.children.link(coll)
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    data = bpy.data.armatures.new(name)
    game = bpy.data.objects.new(name, data)
    coll.objects.link(game)
    game.matrix_world = arm.matrix_world.copy()
    names = {n: _new_name(n, rename) for n in pmap}
    if root_name in names.values():
        root_name = root_name + "_root"
    src_root = arm.data.bones.get("root")
    if src_root is not None and src_root.use_deform:
        src_root = None
    height = max(arm.dimensions) or 1.0
    prev_active = bpy.context.view_layer.objects.active
    mode_prev = bpy.context.mode
    if mode_prev != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = game
    for o in bpy.context.selected_objects:
        o.select_set(False)
    game.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = data.edit_bones
    def copy_rest(e, b):
        # head/tail + roll from the source Z axis: EditBone.matrix assignment flipped some rolls by ~180 deg
        e.head, e.tail = b.head_local.copy(), b.tail_local.copy()
        e.align_roll(b.matrix_local.to_3x3().col[2])

    r = eb.new(root_name)
    if src_root is not None:
        copy_rest(r, src_root)
    else:
        r.head, r.tail, r.roll = (0, 0, 0), (0, 0.1 * height, 0), 0.0
    order = sorted(pmap, key=lambda n: _depth(pmap, n))
    for n in order:
        b = arm.data.bones[n]
        e = eb.new(names[n])
        copy_rest(e, b)
        e.use_deform = True
        e.bbone_segments = 1
        e.inherit_scale = "FULL"
    for n in order:
        e = eb[names[n]]
        e.parent = eb[names[pmap[n]]] if pmap[n] else r
        e.use_connect = False
    r.use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")
    # follow the control rig
    for n in order:
        pb = game.pose.bones[names[n]]
        pb.rotation_mode = "QUATERNION"
        for t in (("COPY_LOCATION", "U3D_loc"), ("COPY_ROTATION", "U3D_rot")) + ((("COPY_SCALE", "U3D_scale"),) if keep_scale else ()):
            c = pb.constraints.new(t[0])
            c.name, c.target, c.subtarget = t[1], arm, n
            c.target_space = c.owner_space = "WORLD"
    rp = game.pose.bones[root_name]
    rp.rotation_mode = "QUATERNION"
    if src_root is not None:
        c = rp.constraints.new("COPY_TRANSFORMS")
        c.name, c.target, c.subtarget = "U3D_root", arm, src_root.name
    bpy.context.view_layer.objects.active = prev_active
    rest_err = 0.0
    for n in order:
        a, g = arm.data.bones[n].matrix_local, data.bones[names[n]].matrix_local
        ang = a.to_quaternion().rotation_difference(g.to_quaternion()).angle
        rest_err = max(rest_err, math.degrees(min(ang, 2 * math.pi - ang)),
                       (a.translation - g.translation).length * 1000)
    if rest_err > 0.01:
        raise RuntimeError(f"export rig rest pose differs from the source by {rest_err:.3f} (deg or mm)")
    return game, names, root_name, pmap


def _clear_constraints(game):
    for pb in game.pose.bones:
        for c in list(pb.constraints):
            if c.name.startswith("U3D_"):
                pb.constraints.remove(c)


def bake(arm, game, acts, step, suffix, keep_scale):
    sc = bpy.context.scene
    baked = []
    ad = arm.animation_data or arm.animation_data_create()
    prev, prev_slot = ad.action, getattr(ad, "action_slot", None)
    gad = game.animation_data or game.animation_data_create()
    pbs = list(game.pose.bones)
    try:
        for act in acts:
            _assign(arm, act)
            _assign(game, None)
            f0, f1 = (int(round(x)) for x in act.frame_range)
            frames = list(range(f0, f1 + 1, max(1, step)))
            if frames[-1] != f1:
                frames.append(f1)
            L = {pb.name: [] for pb in pbs}
            Q = {pb.name: [] for pb in pbs}
            S = {pb.name: [] for pb in pbs}
            for fr in frames:
                sc.frame_set(fr)
                for pb in pbs:
                    m = game.convert_space(pose_bone=pb, matrix=pb.matrix, from_space="POSE", to_space="LOCAL")
                    loc, q, s = m.decompose()
                    if Q[pb.name] and Q[pb.name][-1].dot(q) < 0:
                        q = -q
                    L[pb.name].append(loc); Q[pb.name].append(q); S[pb.name].append(s)
            new_name = act.name + suffix
            old = bpy.data.actions.get(new_name)
            if old is not None:
                bpy.data.actions.remove(old)
            new = bpy.data.actions.new(new_name)
            new.use_fake_user = True
            _assign(game, new)
            for pb in pbs:
                path = f'pose.bones["{pb.name}"].'
                chans = [("location", 3, L), ("rotation_quaternion", 4, Q)] + ([("scale", 3, S)] if keep_scale else [])
                for prop, n, store in chans:
                    for i in range(n):
                        try:
                            fc = new.fcurve_ensure_for_datablock(game, path + prop, index=i, group_name=pb.name)
                        except TypeError:
                            fc = new.fcurve_ensure_for_datablock(game, path + prop, index=i)
                        co = []
                        for fr, v in zip(frames, store[pb.name]):
                            co += [float(fr), float(v[i])]
                        fc.keyframe_points.add(len(frames))
                        fc.keyframe_points.foreach_set("co", co)
                        for k in fc.keyframe_points:
                            k.interpolation = "LINEAR"
                        fc.update()
            baked.append({"source": act.name, "action": new.name, "frames": len(frames), "range": [f0, f1]})
    finally:
        ad.action = prev
        if prev is not None and prev_slot is not None:
            try:
                ad.action_slot = prev_slot
            except (TypeError, RuntimeError):
                pass
    return baked


def attach_meshes(arm, game, meshes, names, mode, coll_name):
    out = []
    coll = bpy.data.collections.get(coll_name)
    for ob in meshes:
        if mode == "copy":
            new = ob.copy()
            new.data = ob.data.copy()
            new.name = ob.name + "_game"
            new.data.name = ob.data.name + "_game"
            for c in list(new.users_collection):
                c.objects.unlink(new)
            coll.objects.link(new)
            mw = ob.matrix_world.copy()
            new.parent = game
            new.matrix_world = mw
            target = new
        elif mode == "retarget":
            target = ob
        else:
            continue
        for m in target.modifiers:
            if m.type == "ARMATURE" and m.object == arm:
                m.object = game
        for vg in target.vertex_groups:
            if vg.name in names:
                vg.name = names[vg.name]
        out.append(target.name)
    return out


def parity(arm, game, names, acts, baked, mesh_pairs, frames_per_clip=4):
    """Bone heads (mm) and skin (mm), control rig + source clip vs export rig + baked clip."""
    sc = bpy.context.scene
    worst_bone, worst_skin = 0.0, 0.0
    ad, gad = arm.animation_data, game.animation_data
    prev, prev_slot = ad.action, getattr(ad, "action_slot", None)
    try:
        for act, b in zip(acts, baked):
            _assign(arm, act)
            _assign(game, bpy.data.actions[b["action"]])
            f0, f1 = b["range"]
            for fr in np.linspace(f0, f1, frames_per_clip):
                sc.frame_set(int(round(fr)))
                for src, dst in names.items():
                    a = arm.matrix_world @ arm.pose.bones[src].head
                    g = game.matrix_world @ game.pose.bones[dst].head
                    worst_bone = max(worst_bone, (a - g).length * 1000)
                for so, go in mesh_pairs:
                    pa, pg = C.evaluated_vertex_positions(so), C.evaluated_vertex_positions(go)
                    if pa.shape == pg.shape:
                        worst_skin = max(worst_skin, float(np.linalg.norm(pa - pg, axis=1).max()) * 1000)
    finally:
        ad.action = prev
        if prev is not None and prev_slot is not None:
            try:
                ad.action_slot = prev_slot
            except (TypeError, RuntimeError):
                pass
    return {"bone_heads_mm": round(worst_bone, 3), "skin_mm": round(worst_skin, 3) if mesh_pairs else None}


def run(args: dict) -> dict:
    arm = bpy.data.objects.get(args.get("armature", ""))
    if arm is None or arm.type != "ARMATURE":
        return C.result_error("armature required")
    win = bpy.context.window
    prev_scene = None
    if bpy.context.scene not in arm.users_scene and arm.users_scene and win is not None:
        prev_scene, win.scene = win.scene, arm.users_scene[0]
    f_cur = bpy.context.scene.frame_current
    try:
        rep = audit(arm, args)
        out = {"audit": rep}
        if args.get("mode", "audit") == "export_rig":
            game, names, root_name, pmap = build_export_rig(arm, args)
            acts = _actions(args.get("actions"))
            keep_scale = bool(args.get("keep_scale", False))
            baked = bake(arm, game, acts, int(args.get("frame_step", 1)), args.get("action_suffix", "_game"),
                         keep_scale) if acts else []
            meshes = _skinned(arm, args.get("meshes"))
            mode = args.get("mesh_mode", "copy")
            attached = attach_meshes(arm, game, meshes, names, mode, args.get("collection", "COL_GameExport"))
            pairs = [(m, bpy.data.objects[a]) for m, a in zip(meshes, attached)] if mode == "copy" else []
            keep_c = args.get("keep_constraints", not baked)
            if not keep_c:
                _clear_constraints(game)
            par = parity(arm, game, names, acts, baked, pairs) if baked and not keep_c else None
            if baked and not keep_c:
                _assign(game, bpy.data.actions[baked[0]["action"]])
            roots = [b.name for b in game.data.bones if b.parent is None]
            out.update(export_rig=game.name, root=root_name, bones=len(game.data.bones), roots=roots,
                       hierarchy={names[n]: (names[p] if p else root_name) for n, p in sorted(pmap.items())},
                       baked=baked, meshes=attached, mesh_mode=mode, constraints_kept=bool(keep_c), parity_mm=par,
                       next=("export the export rig + its meshes (export_glb objects=[...], clips=the baked actions; "
                             "deform_bones_only stays true — the root is not deforming and is still exported as the "
                             "parent of the hierarchy by FBX; glTF keeps it as the skeleton root)"))
    finally:
        bpy.context.scene.frame_set(f_cur)
        if prev_scene is not None:
            win.scene = prev_scene
    if args.get("project_dir"):
        C.write_json(os.path.join(args["project_dir"], "reports", "game-skeleton.json"), out)
    return C.result_ok(**out)
