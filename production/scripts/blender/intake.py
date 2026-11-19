"""Asset intake (gate G0): import a source asset into a temporary scene, measure it, write input-spec.

Skill: .claude/skills/asset-intake/SKILL.md

args:
    source        (str, required)  absolute path of the source file (normally projects/<name>/input/<file>)
    project_dir   (str, optional)  project folder; when given, reports + checkpoint + state are written
    weld_distance (float, 1e-5)    weld distance for the topology check on a COPY
    keep_scene    (bool, False)    keep the INTAKE_ scene (e.g. to take screenshots); remove it later with
                                   u3d_common.remove_scene(bpy.data.scenes["INTAKE_<name>"])
    save_checkpoint (bool, True)   save checkpoints/01_intake.blend (requires project_dir and keep_scene)

returns: dict with ok, spec (input-spec content), gate (G0 json), paths written
"""
import importlib.util
import os
import sys
import time

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
    if "u3d_common" in sys.modules:  # inline mode: u3d_common was executed first
        return sys.modules["u3d_common"]
    raise ImportError("u3d_common.py not found next to this script and not preloaded")


C = _load_common()

CATEGORY_TOKENS = {
    "human": ["human", "man", "woman", "girl", "boy", "person", "character"],
    "dog": ["dog", "puppy", "corgi", "shiba", "husky"],
    "cat": ["cat", "kitten", "calico"],
    "parrot": ["parrot", "macaw", "bird", "cockatoo"],
    "book": ["book"],
    "box": ["box", "chest", "crate"],
    "chair": ["chair", "stool", "seat"],
    "table": ["table", "desk"],
}


def _category_guess(name: str) -> dict:
    low = name.lower()
    for cat, toks in CATEGORY_TOKENS.items():
        if any(t in low for t in toks):
            return {"value": cat, "confidence": 0.6, "basis": "file/object name"}
    return {"value": "unknown", "confidence": 0}


def _generator_guess(objs) -> dict:
    names = " ".join(o.name.lower() for o in objs)
    for key, label in (("tripo", "Tripo"), ("meshy", "Meshy"), ("hunyuan", "Hunyuan3D"), ("rodin", "Rodin")):
        if key in names:
            return {"value": label, "confidence": 0.9, "basis": "object names"}
    return {"value": "unknown", "confidence": 0}


def _materials(meshes):
    mats = {m for o in meshes for m in o.data.materials if m}
    out = []
    for m in sorted(mats, key=lambda x: x.name):
        linked = {}
        if m.use_nodes and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED":
                    for inp in n.inputs:
                        if inp.is_linked:
                            src = inp.links[0].from_node
                            img = getattr(getattr(src, "image", None), "name", None)
                            linked[inp.name] = f"{src.type}:{img}" if img else src.type
        out.append({"name": m.name, "linked_inputs": linked,
                    "blend_method": getattr(m, "surface_render_method", "unknown")})
    return out


def _textures():
    out = []
    for img in bpy.data.images:
        if img.users == 0 or img.name in ("Render Result", "Viewer Node"):
            continue
        out.append({"name": img.name, "width": int(img.size[0]), "height": int(img.size[1]),
                    "colorspace": img.colorspace_settings.name, "format": img.file_format,
                    "packed": bool(img.packed_file), "missing": (img.size[0] == 0)})
    return out


def run(args: dict) -> dict:
    t0 = time.time()
    src = args.get("source")
    if not src or not os.path.exists(src):
        return C.result_error(f"source not found: {src}")
    project_dir = args.get("project_dir")
    weld = float(args.get("weld_distance", 1e-5))
    keep = bool(args.get("keep_scene", False))
    base = os.path.splitext(os.path.basename(src))[0]
    checksum_before = C.sha256(src)

    scene_name = f"INTAKE_{base}"
    with C.temp_scene(scene_name, keep=keep):
        objs = C.import_any(src)
        meshes = C.mesh_objects(objs)
        per_obj, welded = [], []
        for ob in meshes:
            st = C.mesh_stats(ob)
            per_obj.append(st)
            w = C.welded_copy_stats(ob, weld)
            w["object"] = ob.name
            welded.append(w)
        for ob in objs:
            if ob.type != "MESH":
                per_obj.append({"name": ob.name, "type": ob.type,
                                "parent": ob.parent.name if ob.parent else None})
        mn, mx = C.world_bbox(meshes)
        arms = [o for o in objs if o.type == "ARMATURE"]
        actions = [{"name": a.name, "frame_start": float(a.frame_range[0]), "frame_end": float(a.frame_range[1])}
                   for a in bpy.data.actions]
        textures = _textures()
        spec = {
            "source": {"file": os.path.basename(src), "format": os.path.splitext(src)[1].lstrip(".").lower(),
                       "bytes": os.path.getsize(src), "sha256": checksum_before,
                       "importer": f"Blender {bpy.app.version_string}"},
            "scene": {"objects": per_obj},
            "geometry": {
                "triangles_total": sum(s["triangles"] for s in per_obj if "triangles" in s),
                "vertices_total": sum(s["vertices"] for s in per_obj if "vertices" in s),
                "quads_ratio": (min(s["quads_ratio"] for s in per_obj if "quads_ratio" in s) if meshes else "unknown"),
                "components_raw": sum(s["components"] for s in per_obj if "components" in s),
                "components_welded": sum(w["components"] for w in welded),
                "boundary_edges_raw": sum(s["boundary_edges"] for s in per_obj if "boundary_edges" in s),
                "boundary_edges_welded": sum(w["boundary_edges"] for w in welded),
                "nonmanifold_edges_welded": sum(w["nonmanifold_edges"] for w in welded),
                "dimensions_m": [round(mx[i] - mn[i], 4) for i in range(3)],
                "bbox_min": [round(x, 4) for x in mn], "bbox_max": [round(x, 4) for x in mx],
                "weld": welded,
            },
            "materials": _materials(meshes),
            "textures": textures,
            "rig": {"armatures": [{"name": a.name, "bones": len(a.data.bones)} for a in arms],
                    "bones_total": sum(len(a.data.bones) for a in arms)},
            "animation": {"actions": actions},
            "hints": {
                "category_guess": _category_guess(base + " " + " ".join(o.name for o in objs)),
                "forward_axis_guess": {"value": "unknown", "confidence": 0, "basis": "confirm from screenshots"},
                "up_axis_guess": {"value": "+Z", "confidence": 0.7, "basis": "Blender import convention"},
                "pose_hint": {"value": "unknown", "confidence": 0, "basis": "set after screenshot review"},
                "generator_hint": _generator_guess(objs),
            },
            "issues": [],
        }
        g = spec["geometry"]
        if g["components_raw"] > g["components_welded"] and g["boundary_edges_raw"] > 10 * max(1, g["boundary_edges_welded"]):
            spec["issues"].append("split_on_uv_seams")
        if any(t["missing"] for t in textures):
            spec["issues"].append("missing_texture")
        if any(any(abs(s - 1.0) > 1e-4 for s in o.get("scale", [1, 1, 1])) for o in per_obj):
            spec["issues"].append("scale_not_applied")
        if g["quads_ratio"] == 0:
            spec["issues"].append("triangle_soup")
        if g["nonmanifold_edges_welded"] or g["boundary_edges_welded"]:
            spec["issues"].append("open_or_nonmanifold_after_weld")

        written = {}
        gate = {"gate": "G0", "status": "pass" if objs and "missing_texture" not in spec["issues"] else "fail",
                "metrics": {"import_ok": bool(objs), "triangles": g["triangles_total"],
                            "components_raw": g["components_raw"], "components_welded": g["components_welded"],
                            "boundary_edges_welded": g["boundary_edges_welded"],
                            "missing_images": sum(1 for t in textures if t["missing"])},
                "notes": spec["issues"], "at": C.now_iso()}
        if project_dir:
            rep = os.path.join(project_dir, "reports")
            written["input_spec"] = C.write_yaml(os.path.join(rep, "input-spec.yaml"), spec,
                                                 header="MEASURED by production/scripts/blender/intake.py - do not edit")
            if keep and args.get("save_checkpoint", True):
                gate["checkpoint"] = C.save_checkpoint(project_dir, 1, "intake")
            written["gate"] = C.write_json(os.path.join(rep, "gate-G0.json"), gate)
            C.update_state(project_dir, "intake", "passed" if gate["status"] == "pass" else "failed",
                           gate="G0", checkpoint=gate.get("checkpoint"))

    if C.sha256(src) != checksum_before:
        return C.result_error("source file changed during intake", spec=spec)
    return C.result_ok(spec=spec, gate=gate, written=written, scene=scene_name if keep else None,
                       seconds=round(time.time() - t0, 1))
