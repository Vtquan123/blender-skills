"""Procedural test assets for the analysis → rig → clip pipeline (no source files needed).

Run inside Blender (through MCP: runpy.run_path(this)["run"]({...})). Builds each asset in a scratch scene,
exports it as GLB and removes the scene, so the user's scene is untouched. Object names are neutral
("Object_1", ...) so analysis must work from geometry, not names. "fused" variants are voxel-remeshed into a
single closed mesh, like AI-generated assets (Tripo, Meshy): parts are not separate objects.

args:
    out_dir  (str, required)
    assets   (list, optional)  subset of: ball, car_parts, car_fused, tree_fused, chest_parts, snake_fused
returns {"files": {name: path}}
"""
import math
import os

import bpy
from mathutils import Matrix, Vector


def _scene():
    sc = bpy.data.scenes.new("TMP_test_assets")
    return sc


def _link(sc, ob):
    sc.collection.objects.link(ob)
    return ob


def _mesh_from_bm(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return bpy.data.objects.new(name, me)


def _prim(kind, **kw):
    import bmesh
    bm = bmesh.new()
    if kind == "sphere":
        bmesh.ops.create_icosphere(bm, subdivisions=kw.get("sub", 4), radius=kw["r"])
    elif kind == "cyl":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=kw.get("seg", 32), radius1=kw["r1"], radius2=kw.get("r2", kw["r1"]),
                              depth=kw["depth"])
    elif kind == "box":
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=Vector(kw["size"]), verts=bm.verts)
    elif kind == "torus":
        # ring of the tyre: sweep a circle
        R, r, seg, rs = kw["R"], kw["r"], kw.get("seg", 32), kw.get("rseg", 12)
        verts = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            ring = []
            for j in range(rs):
                b = 2 * math.pi * j / rs
                ring.append(bm.verts.new(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b))))
            verts.append(ring)
        for i in range(seg):
            for j in range(rs):
                bm.faces.new((verts[i][j], verts[(i + 1) % seg][j], verts[(i + 1) % seg][(j + 1) % rs], verts[i][(j + 1) % rs]))
    if kw.get("matrix") is not None:
        bmesh.ops.transform(bm, matrix=kw["matrix"], verts=bm.verts)
    return bm


def _obj(sc, name, bm, mat=None, smooth=True):
    ob = _link(sc, _mesh_from_bm(name, bm))
    if smooth:
        for p in ob.data.polygons:
            p.use_smooth = True
    if mat:
        ob.data.materials.append(mat)
    return ob


def _mat(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*rgb, 1)
    return m


def _evaluated_mesh(sc, ob):
    with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    me.transform(ob.matrix_world)
    return me


def _fuse(sc, objs, name, voxel):
    """Merge objects (modifiers applied) and voxel-remesh them into one closed mesh, like AI generators.
    No operators: works whatever scene the window shows."""
    import bmesh
    bm = bmesh.new()
    for o in objs:
        me = _evaluated_mesh(sc, o)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    for o in objs:
        me = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if me.users == 0:
            bpy.data.meshes.remove(me)
    ob = _obj(sc, name + "_src", bm)
    mod = ob.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    mod.use_smooth_shade = True
    me = _evaluated_mesh(sc, ob)
    src = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.meshes.remove(src)
    me.name = name
    out = _link(sc, bpy.data.objects.new(name, me))
    for p in out.data.polygons:
        p.use_smooth = True
    return out


def _export(sc, path):
    vl = sc.view_layers[0]
    with bpy.context.temp_override(scene=sc, view_layer=vl):
        for o in sc.objects:
            o.select_set(True, view_layer=vl)
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, use_active_scene=True,
                                  export_apply=True, export_animations=False)


def ball(sc):
    _obj(sc, "Object_1", _prim("sphere", r=0.11, sub=5, matrix=Matrix.Translation((0, 0, 0.11))), _mat("M_ball", (0.9, 0.3, 0.2)))


def _car_parts(sc):
    body = _obj(sc, "Object_1", _prim("box", size=(0.42, 0.18, 0.08), matrix=Matrix.Translation((0, 0, 0.095))), _mat("M_body", (0.2, 0.4, 0.8)), smooth=False)
    bev = body.modifiers.new("bevel", "BEVEL"); bev.width = 0.015; bev.segments = 3
    cab = _obj(sc, "Object_2", _prim("box", size=(0.2, 0.16, 0.07), matrix=Matrix.Translation((-0.03, 0, 0.17))), _mat("M_body", (0.2, 0.4, 0.8)), smooth=False)
    bev = cab.modifiers.new("bevel", "BEVEL"); bev.width = 0.02; bev.segments = 3
    wheels = []
    k = 3
    for x in (0.13, -0.13):
        for y in (0.095, -0.095):
            m = Matrix.Translation((x, y, 0.05)) @ Matrix.Rotation(math.pi / 2, 4, "X")
            k += 1
            wheels.append(_obj(sc, f"Object_{k}", _prim("cyl", r1=0.05, depth=0.032, seg=40, matrix=m), _mat("M_tyre", (0.05, 0.05, 0.05))))
    return [body, cab] + wheels


def car_parts(sc):
    _car_parts(sc)


def car_fused(sc):
    ob = _fuse(sc, _car_parts(sc), "Object_1", 0.004)
    ob.data.materials.append(_mat("M_body", (0.2, 0.4, 0.8)))


def tree_fused(sc):
    parts = []
    trunk = _prim("cyl", r1=0.06, r2=0.035, depth=0.6, seg=24, matrix=Matrix.Translation((0, 0, 0.3)))
    parts.append(_obj(sc, "t", trunk))
    branches = [((0, 0, 0.45), 0.0, 0.7, 0.35), ((0, 0, 0.5), 2.1, 0.8, 0.32), ((0, 0, 0.55), 4.2, 0.6, 0.3), ((0, 0, 0.58), 1.0, 0.25, 0.3)]
    for base, yaw, tilt, length in branches:
        rot = Matrix.Rotation(yaw, 4, "Z") @ Matrix.Rotation(tilt, 4, "Y")
        m = Matrix.Translation(base) @ rot @ Matrix.Translation((0, 0, length / 2))
        parts.append(_obj(sc, "b", _prim("cyl", r1=0.025, r2=0.012, depth=length, seg=16, matrix=m)))
        tip = Vector(base) + (rot.to_3x3() @ Vector((0, 0, length)))
        parts.append(_obj(sc, "f", _prim("sphere", r=0.12, sub=3, matrix=Matrix.Translation(tip))))
    parts.append(_obj(sc, "f", _prim("sphere", r=0.16, sub=3, matrix=Matrix.Translation((0, 0, 0.82)))))
    ob = _fuse(sc, parts, "Object_1", 0.008)
    ob.data.materials.append(_mat("M_tree", (0.3, 0.5, 0.2)))


def chest_parts(sc):
    box = _obj(sc, "Object_1", _prim("box", size=(0.4, 0.25, 0.18), matrix=Matrix.Translation((0, 0, 0.09))), _mat("M_wood", (0.5, 0.3, 0.15)), smooth=False)
    lid = _obj(sc, "Object_2", _prim("box", size=(0.4, 0.25, 0.05), matrix=Matrix.Translation((0, 0, 0.205))), _mat("M_wood", (0.5, 0.3, 0.15)), smooth=False)


def snake_fused(sc):
    """Limbless elongated body: a chain along a gentle S curve."""
    parts = []
    n = 30
    for i in range(n):
        t = i / (n - 1)
        x = -0.5 + t * 1.0
        y = 0.08 * math.sin(t * 2 * math.pi)
        r = 0.035 * (1 - 0.6 * t) + 0.01
        parts.append(_obj(sc, "s", _prim("sphere", r=r, sub=3, matrix=Matrix.Translation((x, y, r)))))
    parts.append(_obj(sc, "h", _prim("sphere", r=0.04, sub=3, matrix=Matrix.Translation((-0.53, 0, 0.04)))))
    ob = _fuse(sc, parts, "Object_1", 0.006)
    ob.data.materials.append(_mat("M_snake", (0.4, 0.6, 0.2)))


BUILDERS = {"ball": ball, "car_parts": car_parts, "car_fused": car_fused, "tree_fused": tree_fused,
            "chest_parts": chest_parts, "snake_fused": snake_fused}


def run(args: dict) -> dict:
    out = args["out_dir"]
    os.makedirs(out, exist_ok=True)
    files = {}
    for name in args.get("assets") or list(BUILDERS):
        mats_before = set(bpy.data.materials)
        sc = _scene()
        try:
            BUILDERS[name](sc)
            path = os.path.join(out, f"{name}.glb")
            _export(sc, path)
            files[name] = path
        finally:
            for o in list(sc.objects):
                me = o.data
                bpy.data.objects.remove(o, do_unlink=True)
                if me is not None:
                    bpy.data.meshes.remove(me)
            bpy.data.scenes.remove(sc)
            for m in [m for m in bpy.data.materials if m not in mats_before and m.users == 0]:
                bpy.data.materials.remove(m)
    return {"ok": True, "files": files}
