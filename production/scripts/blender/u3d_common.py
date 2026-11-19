"""Shared helpers for Universal 3D Production scripts running inside Blender (5.x).

Every stage script exposes ``run(args: dict) -> dict`` and is executed through the
Blender MCP (official server: ``execute_blender_code``), e.g.::

    import runpy
    ns = runpy.run_path("<repo>/production/scripts/blender/intake.py")
    result = ns["run"]({...})

Scripts import this module by path so they work without installing anything::

    import importlib.util, os
    _p = os.path.join(os.path.dirname(__file__), "u3d_common.py")
    ...

No third-party packages: Blender ships numpy; YAML is NOT available inside
Blender, so specs are read by the agent and passed in ``args`` as plain values.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os

import bpy
import bmesh
import numpy as np
from mathutils import Vector

SCHEMA_VERSION = 1


# ---------------------------------------------------------------- files / state
def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def write_json(path: str, data) -> str:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=_json_default)
    return path


def read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray, Vector)):
        return [float(x) for x in obj]
    return str(obj)


def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, np.integer, np.floating)):
        return repr(float(v)) if isinstance(v, (float, np.floating)) else str(int(v))
    s = str(v)
    try:
        float(s)
        return json.dumps(s)  # keep numeric-looking strings as strings
    except ValueError:
        pass
    if s == "" or any(c in s for c in ":#{}[],&*?|<>=!%@`'\"\n") or s.strip() != s or s.lower() in ("null", "true", "false", "yes", "no", "on", "off", "~"):
        return json.dumps(s, ensure_ascii=False)
    return s


def to_yaml(obj, indent: int = 0) -> str:
    """Minimal YAML emitter (Blender ships without PyYAML). Output is valid YAML 1.2."""
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}\n"
        out = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{_yaml_scalar(k)}:\n{to_yaml(v, indent + 1)}")
            elif isinstance(v, dict):
                out.append(f"{pad}{_yaml_scalar(k)}: {{}}\n")
            elif isinstance(v, list):
                out.append(f"{pad}{_yaml_scalar(k)}: []\n")
            else:
                out.append(f"{pad}{_yaml_scalar(k)}: {_yaml_scalar(v)}\n")
        return "".join(out)
    if isinstance(obj, (list, tuple, np.ndarray)):
        if len(obj) == 0:
            return pad + "[]\n"
        if all(not isinstance(x, (dict, list, tuple)) for x in obj):
            return pad + "[" + ", ".join(_yaml_scalar(x) for x in obj) + "]\n"
        out = []
        for x in obj:
            body = to_yaml(x, indent + 1).lstrip()
            out.append(f"{pad}- {body}")
        return "".join(out)
    return pad + _yaml_scalar(obj) + "\n"


def write_yaml(path: str, data, header: str = "") -> str:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        if header:
            fh.write("".join(f"# {line}\n" for line in header.splitlines()))
        fh.write(to_yaml(data))
    return path


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def project_paths(project_dir: str) -> dict:
    return {k: os.path.join(project_dir, k) for k in
            ("input", "working", "output", "textures", "reports", "checkpoints")}


def update_state(project_dir: str, stage: str, status: str, **fields) -> dict:
    """Record a stage result in state.json. status: running|passed|failed|needs_review."""
    path = os.path.join(project_dir, "state.json")
    state = read_json(path, {"schema": SCHEMA_VERSION, "project": os.path.basename(project_dir), "stages": {}})
    entry = state["stages"].get(stage, {})
    entry.update(fields)
    entry["status"] = status
    entry["updated_at"] = now_iso()
    state["stages"][stage] = entry
    if status == "passed" and fields.get("checkpoint"):
        state["last_good_checkpoint"] = fields["checkpoint"]
    write_json(path, state)
    return state


def save_checkpoint(project_dir: str, index: int, stage: str) -> str:
    """Save a COPY of the current file as checkpoints/NN_stage.blend (the open file path is unchanged)."""
    rel = os.path.join("checkpoints", f"{index:02d}_{stage}.blend")
    path = os.path.join(project_dir, rel)
    ensure_dir(os.path.dirname(path))
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=True)
    return rel


# ---------------------------------------------------------------- scenes
@contextlib.contextmanager
def temp_scene(name: str, keep: bool = False):
    """Create a scene, make it active in the window, restore the previous one afterwards.

    With keep=False the scene, its objects and orphaned data are removed on exit.
    """
    win = bpy.context.window
    sc = bpy.data.scenes.new(name)
    if win is not None:  # interactive Blender (MCP addon in a running UI)
        prev = win.scene
        win.scene = sc
        try:
            yield sc
        finally:
            win.scene = prev
            if not keep:
                remove_scene(sc)
    else:  # background / CLI: no window, override the context instead
        try:
            with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
                yield sc
        finally:
            if not keep:
                remove_scene(sc)


def remove_scene(sc) -> None:
    for ob in list(sc.objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and getattr(data, "users", 1) == 0:
            for coll in (bpy.data.meshes, bpy.data.armatures, bpy.data.curves):
                if data.name in coll and coll[data.name] == data:
                    coll.remove(data)
                    break
    bpy.data.scenes.remove(sc)
    bpy.ops.outliner.orphans_purge(do_recursive=True)


def import_any(path: str) -> list:
    """Import a source file into the active scene. Returns the new objects."""
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        bpy.ops.wm.usd_import(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == ".blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for ob in dst.objects:
            if ob is not None:
                bpy.context.scene.collection.objects.link(ob)
    else:
        raise ValueError(f"Unsupported format: {ext}")
    return [o for o in bpy.data.objects if o not in before]


# ---------------------------------------------------------------- mesh metrics
def mesh_objects(objs=None) -> list:
    objs = objs if objs is not None else bpy.context.scene.objects
    return [o for o in objs if o.type == "MESH"]


def components_count(me) -> int:
    """Connected components over edges (vectorised label propagation)."""
    n = len(me.vertices)
    if n == 0:
        return 0
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    label = np.arange(n)
    for _ in range(10000):
        a, b = ev[:, 0], ev[:, 1]
        m = np.minimum(label[a], label[b])
        np.minimum.at(label, a, m)
        np.minimum.at(label, b, m)
        label = label[label]
        if np.array_equal(label[a], label[b]):
            break
    return int(len(np.unique(label)))


def edge_face_counts(me):
    ei = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("edge_index", ei)
    return np.bincount(ei, minlength=len(me.edges))


def mesh_stats(ob) -> dict:
    me = ob.data
    me.calc_loop_triangles()
    sizes = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_total", sizes)
    cnt = edge_face_counts(me)
    return {
        "name": ob.name,
        "vertices": len(me.vertices),
        "faces": len(me.polygons),
        "triangles": len(me.loop_triangles),
        "quads_ratio": round(float((sizes == 4).mean()) if len(sizes) else 0.0, 4),
        "ngons": int((sizes > 4).sum()),
        "boundary_edges": int((cnt == 1).sum()),
        "nonmanifold_edges": int((cnt > 2).sum()),
        "loose_edges": int((cnt == 0).sum()),
        "components": components_count(me),
        "uv_layers": [u.name for u in me.uv_layers],
        "shape_keys": len(me.shape_keys.key_blocks) if me.shape_keys else 0,
        "vertex_groups": len(ob.vertex_groups),
        "materials": [m.name if m else None for m in me.materials],
        "modifiers": [m.type for m in ob.modifiers],
        "scale": [round(x, 6) for x in ob.scale],
        "dimensions": [round(x, 6) for x in ob.dimensions],
    }


def welded_copy_stats(ob, dist: float = 1e-5) -> dict:
    """Weld a bmesh COPY (the object is not modified) and measure topology."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    v0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    bm.verts.ensure_lookup_table()
    seen = np.zeros(len(bm.verts), dtype=bool)
    comps = []
    for v in bm.verts:
        if seen[v.index]:
            continue
        stack = [v]
        seen[v.index] = True
        c = 0
        while stack:
            x = stack.pop()
            c += 1
            for e in x.link_edges:
                y = e.other_vert(x)
                if not seen[y.index]:
                    seen[y.index] = True
                    stack.append(y)
        comps.append(c)
    out = {
        "weld_distance": dist,
        "vertices_before": v0,
        "vertices_after": len(bm.verts),
        "components": len(comps),
        "largest_components": sorted(comps, reverse=True)[:8],
        "boundary_edges": sum(1 for e in bm.edges if e.is_boundary),
        "nonmanifold_edges": sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary),
    }
    bm.free()
    return out


def world_bbox(objs) -> tuple:
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    if not pts:
        return [0, 0, 0], [0, 0, 0]
    mn = [min(p[i] for p in pts) for i in range(3)]
    mx = [max(p[i] for p in pts) for i in range(3)]
    return mn, mx


def evaluated_vertex_positions(ob, depsgraph=None) -> np.ndarray:
    """World-space vertex positions after modifiers/armature (for ROM tests and sampling)."""
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    co = co.reshape(-1, 3)
    mw = np.array(ob.matrix_world)
    return co @ mw[:3, :3].T + mw[:3, 3]


def count_rings(co, edges, head, axis, halfwidth, radius, angles: int = 8) -> dict:
    """Count edge loops around a limb inside a joint band.

    A meridian half-plane (contains the bone axis, one side only) crosses each loop around the limb once,
    so the number of band edges it crosses equals the number of loops. Median over several angles makes
    it robust to spiral/irregular remesh flow. Returns {"rings": median, "per_angle": [...]}.
    """
    axis = axis / (np.linalg.norm(axis) or 1.0)
    a_ref = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
    u1 = np.cross(axis, a_ref)
    u1 /= np.linalg.norm(u1)
    u2 = np.cross(axis, u1)
    rel = co - head
    t = rel @ axis
    radial = np.linalg.norm(rel - np.outer(t, axis), axis=1)
    inb = (np.abs(t) <= halfwidth) & (radial <= 2.0 * radius)
    e = edges[inb[edges[:, 0]] & inb[edges[:, 1]]]
    if len(e) == 0:
        return {"rings": 0, "per_angle": []}
    pa, pb = rel[e[:, 0]], rel[e[:, 1]]
    counts = []
    for k in range(angles):
        th = 2 * np.pi * k / angles
        d = np.cos(th) * u1 + np.sin(th) * u2      # direction of the half-plane
        n = -np.sin(th) * u1 + np.cos(th) * u2     # plane normal
        sa, sb = pa @ n, pb @ n
        cross = sa * sb < 0
        f = sa[cross] / (sa[cross] - sb[cross])
        p = pa[cross] + (pb[cross] - pa[cross]) * f[:, None]
        counts.append(int(((p @ d) > 0).sum()))
    return {"rings": int(np.median(counts)), "per_angle": counts}


# ---------------------------------------------------------------- animation (Blender 4.4+/5.x slotted actions)
def action_fcurves(action, slot=None) -> list:
    """Return F-curves of an action for a slot (layered/slotted API in 5.x, legacy fallback)."""
    try:
        from bpy_extras import anim_utils
        slot = slot or (action.slots[0] if len(action.slots) else None)
        if slot is None:
            return []
        cb = anim_utils.action_get_channelbag_for_slot(action, slot)
        return list(cb.fcurves) if cb else []
    except (ImportError, AttributeError):
        return list(getattr(action, "fcurves", []))


def result_ok(**data) -> dict:
    return {"ok": True, "schema": SCHEMA_VERSION, "at": now_iso(), **data}


def result_error(message: str, **data) -> dict:
    return {"ok": False, "schema": SCHEMA_VERSION, "at": now_iso(), "error": message, **data}
