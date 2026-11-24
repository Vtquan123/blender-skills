"""Quad remesh through the AutoRemesher core — optional backend for deform_mesh.py, also usable on its own.

AutoRemesher (Jeremy Hu, MIT) turns a dense triangle mesh into an even, curvature-adaptive quad mesh. Its
Blender build (github.com/jakeblakeley/autoremesher-blender) ships the C++ core as the Python module
`autoremesher_core` inside a Blender extension. This script only *calls* that module; none of the
extension's own add-on code (GPL-3.0) is used here — the worker below is an independent implementation.

Install (user, once per machine): download `autoremesher-<version>-<platform>.zip` from the extension's
releases page (Blender 5.1+; `-blender42-` zips for 4.2 LTS–5.0) → Preferences → Get Extensions → ▾ →
Install from Disk. `mode: "probe"` tells whether this Blender can use it.

Why a subprocess: the core is native code; a crash there must not take Blender (and the MCP session) down.
The worker runs in Blender's own Python (`sys.executable`, isolated mode) and talks through two .npz files
in a temporary folder. The call blocks until the worker ends or `timeout` passes — the MCP needs a
finished result, so the extension's modal operator (which returns RUNNING_MODAL at once) is not used.

Compared to QuadriFlow: no manifold pre-check, no scale trick, islands that fail keep their triangles
instead of vanishing, thin parts (claws, horns) keep density (`preserve_thin`), sharp creases can be kept
(`sharp_edge_deg`). No symmetry option. Output is quad-dominant; hole fixing may leave a few tris/n-gons.

args:
    mode            (str, "remesh")  "remesh" | "probe"
    source          (str)            mesh object (remesh mode)
    name            (str)            result object name, default "<source>_autoremesh" (ignored with in_place)
    in_place        (bool, False)    replace the source's mesh data instead of adding a new object
    target_faces    (int, required)  quad target (≈ triangle budget / 2)
    fit_target      (bool, True)     re-run with a corrected request until faces land within `tolerance` of
                                     target_faces (the core's count is approximate; up to `max_passes` runs,
                                     the closest result wins, preferring one not over the budget)
    tolerance       (float, 0.2)     accepted |faces / target_faces - 1|
    max_passes      (int, 4)
    total_timeout   (float, 1200)    seconds for all passes together (keep under the MCP client's own limit)
    budget_strict   (bool, True)     still over budget after fitting with preserve_thin on → one more pass
                                     without it (reported in warnings); False keeps thin parts over budget
    adaptivity      (float, 0.0)     0 = uniform quads, 1 = finer quads where curvature is high. Leave it
                                     unset to let fitting switch ends when the count ignores the request
                                     (see fit_remesh); set it to pin it
    edge_scaling    (float, 1.0)     1–4, larger = coarser
    sharp_edge_deg  (float, 90)      dihedral angle kept as a feature edge (30–180)
    smooth_normal_deg (float, 0)     0 = faceted guide field; larger follows the source normals
    island_detail   (int, 10)        min quads across small disconnected parts (teeth, plates); 0 = off
    preserve_thin   (bool, True)     finer quads on thin features (medial-axis sizing; may exceed the target)
    hard_surface    (bool, False)    hard-surface mode, when the installed core supports it
    weld_shells     (bool, False)    voxel-fuse intersecting shells into one watertight surface first
                                     (interior geometry is removed — never on meshes with intended gaps)
    timeout         (float, 900)     seconds per pass before the worker is killed
    core_path       (str)            folder that contains autoremesher_core (default: found automatically;
                                     env AUTOREMESHER_CORE_PATH also works)
"""
import glob
import importlib.util
import json
import math
import os
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

RELEASES_URL = "https://github.com/jakeblakeley/autoremesher-blender/releases"
MODULE = "autoremesher_core"

# Runs in Blender's Python, outside Blender (no bpy). argv: in.npz out.npz core_dir
WORKER_SOURCE = r'''
import json, sys, threading, time
in_path, out_path, core_dir = sys.argv[1], sys.argv[2], sys.argv[3]
if core_dir:
    sys.path.insert(0, core_dir)
import numpy as np
try:
    import autoremesher_core as core
except Exception as e:  # wrong Python tag, missing library, ...
    print("ERROR import " + repr(e), flush=True)
    sys.exit(3)
if in_path == "--probe":
    print("PROBE " + json.dumps({"file": getattr(core, "__file__", None),
                                  "hard_surface": hasattr(core.Remesher, "hard_surface")}), flush=True)
    sys.exit(0)
job = np.load(in_path, allow_pickle=False)
p = json.loads(str(job["params"]))
r = core.Remesher(np.ascontiguousarray(job["vertices"], dtype=np.float64),
                  np.ascontiguousarray(job["triangles"], dtype=np.uint32))
for key, value in p.items():
    if hasattr(r, key):
        setattr(r, key, value)
    else:
        print("SKIPPED " + key, flush=True)
box = {}
def work():
    try:
        box["ok"] = bool(r.run())
    except Exception as e:
        box["error"] = repr(e)
t = threading.Thread(target=work)
t0 = time.time()
t.start()
while t.is_alive():
    t.join(1.0)
    print("PROGRESS %.3f %s" % (r.progress, r.status), flush=True)
if not box.get("ok"):
    print("ERROR run " + box.get("error", "returned False"), flush=True)
    sys.exit(2)
np.savez(out_path, vertices=np.asarray(r.vertices(), dtype=np.float64),
         face_indices=np.asarray(r.face_indices(), dtype=np.int64),
         face_sizes=np.asarray(r.face_sizes(), dtype=np.int64),
         seconds=np.float64(time.time() - t0))
print("DONE", flush=True)
'''


# ---------------------------------------------------------------- locating the core
def _candidate_dirs(core_path=None):
    if core_path:
        return [core_path]                         # explicit path: no guessing
    dirs = []
    env = os.environ.get("AUTOREMESHER_CORE_PATH")
    if env:
        dirs.append(env)
    try:
        spec = importlib.util.find_spec(MODULE)    # extension enabled → its wheels are on sys.path
    except (ImportError, ValueError):
        spec = None
    if spec and spec.origin:
        dirs.append(os.path.dirname(spec.origin))
    # extension installed but its site-packages not on sys.path (disabled, installed this session)
    try:
        root = bpy.utils.user_resource("EXTENSIONS", path=".local")
    except Exception:  # Blender < 4.2: no extensions
        root = None
    if root:
        tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
        dirs.extend(glob.glob(os.path.join(root, "lib", tag, "site-packages")))
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def _has_module(d):
    return bool(glob.glob(os.path.join(d, MODULE + "*"))) or os.path.isdir(os.path.join(d, MODULE))


def _python():
    exe = sys.executable
    if exe and os.path.basename(exe).lower().startswith("python") and os.path.exists(exe):
        return exe
    # very old builds report the Blender binary; look for the bundled interpreter
    base = os.path.dirname(os.path.dirname(os.__file__))
    for pat in ("bin/python3*", "../bin/python3*", "bin/python.exe", "../bin/python.exe"):
        hits = sorted(glob.glob(os.path.join(base, pat)))
        if hits:
            return os.path.abspath(hits[0])
    return exe


def _spawn(args, timeout):
    """Run the worker; return (returncode, lines). returncode None = timed out."""
    with tempfile.TemporaryDirectory(prefix="u3d_autoremesh_") as tmp:
        worker = os.path.join(tmp, "worker.py")
        with open(worker, "w", encoding="utf-8") as f:
            f.write(WORKER_SOURCE)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen([_python(), "-I", worker, *args], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, creationflags=flags)
        try:
            out, _ = proc.communicate(timeout=timeout)
            return proc.returncode, out.splitlines()
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            return None, (out or "").splitlines()


def probe(core_path=None, timeout=60.0) -> dict:
    """Is autoremesher_core loadable by this Blender's Python? Tries each candidate folder."""
    tried = []
    for d in _candidate_dirs(core_path):
        if not _has_module(d):
            tried.append({"dir": d, "result": "module not in folder"})
            continue
        code, lines = _spawn(["--probe", "", d], timeout)
        info = next((ln[6:] for ln in lines if ln.startswith("PROBE ")), None)
        if code == 0 and info:
            return {"available": True, "core_dir": d, **json.loads(info)}
        tried.append({"dir": d, "result": f"exit {code}", "tail": lines[-3:]})
    return {"available": False, "tried": tried,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "blender": bpy.app.version_string,
            "install": f"Download the extension zip for this platform from {RELEASES_URL} "
                       "(Blender 5.1+: autoremesher-<ver>-<platform>.zip; 4.2–5.0: the -blender42- zip), "
                       "then Preferences > Get Extensions > Install from Disk."}


# ---------------------------------------------------------------- mesh <-> arrays
def mesh_arrays(ob):
    """Evaluated (modifiers applied) triangles in the object's local space."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        tri = np.empty(len(me.loop_triangles) * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
    finally:
        ev.to_mesh_clear()
    return co.reshape(-1, 3).astype(np.float64), tri.reshape(-1, 3).astype(np.uint32)


def build_mesh(name, verts, face_indices, face_sizes):
    sizes = np.asarray(face_sizes, dtype=np.int32)
    loops = np.asarray(face_indices, dtype=np.int32)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", np.asarray(verts, dtype=np.float32).ravel())
    me.loops.add(len(loops))
    me.loops.foreach_set("vertex_index", loops)
    me.polygons.add(len(sizes))
    starts = np.zeros(len(sizes), dtype=np.int32)
    if len(sizes) > 1:
        np.cumsum(sizes[:-1], out=starts[1:])
    me.polygons.foreach_set("loop_start", starts)
    me.polygons.foreach_set("loop_total", sizes)
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    return me


def voxel_fuse(verts, tris, target_faces):
    """Fuse intersecting shells with Blender's voxel remesh. Voxel ≈ half the expected quad edge."""
    corners = verts[tris]
    area = 0.5 * float(np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0],
                                               corners[:, 2] - corners[:, 0]), axis=1).sum())
    quad_edge = math.sqrt(max(area, 1e-12) / max(int(target_faces), 1))
    extent = float(np.ptp(verts, axis=0).max()) if len(verts) else 0.0
    voxel = max(quad_edge * 0.5, extent / 600.0, 1e-6)       # cap the grid at ~600 cells per side
    me = build_mesh("U3D_voxel_fuse", verts, tris.ravel(), np.full(len(tris), 3))
    ob = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(ob)
    try:
        mod = ob.modifiers.new("Fuse", "REMESH")
        mod.mode, mod.voxel_size = "VOXEL", voxel
        out = mesh_arrays(ob)
    finally:
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me)
    return out[0], out[1], voxel


def core_params(args) -> dict:
    return {
        "target_quad_count": int(args["target_faces"]),
        "adaptivity": float(args.get("adaptivity", 0.0)),
        "scaling": float(args.get("edge_scaling", 1.0)),
        "sharp_edge_degrees": float(args.get("sharp_edge_deg", 90.0)),
        "smooth_normal_degrees": float(args.get("smooth_normal_deg", 0.0)),
        "island_detail_spans": int(args.get("island_detail", 10)),
        "feature_size_factor": 1.0 if args.get("preserve_thin", True) else 0.0,
        "hard_surface": bool(args.get("hard_surface", False)),
    }


def remesh_arrays(verts, tris, args, core_dir) -> dict:
    """Run the worker. Returns {"ok", "verts", "face_indices", "face_sizes", "seconds", "log"} or an error."""
    params = core_params(args)
    with tempfile.TemporaryDirectory(prefix="u3d_autoremesh_io_") as tmp:
        src, dst = os.path.join(tmp, "in.npz"), os.path.join(tmp, "out.npz")
        np.savez(src, vertices=verts, triangles=tris, params=json.dumps(params))
        t0 = time.time()
        code, lines = _spawn([src, dst, core_dir], float(args.get("timeout", 900.0)))
        log = [ln for ln in lines if not ln.startswith("PROGRESS")][-8:]
        if code is None:
            return {"ok": False, "error": f"timed out after {args.get('timeout', 900.0)} s", "log": log}
        if code != 0 or not os.path.exists(dst):
            why = {2: "remesh failed", 3: "core could not be imported"}.get(code, f"worker crashed (exit {code})")
            return {"ok": False, "error": why, "log": log}
        out = np.load(dst, allow_pickle=False)
        res = {"ok": True, "verts": out["vertices"].reshape(-1, 3), "face_indices": out["face_indices"],
               "face_sizes": out["face_sizes"], "seconds": round(time.time() - t0, 2), "log": log}
    if not len(res["face_sizes"]):
        return {"ok": False, "error": "remesh returned no faces", "log": res["log"]}
    return res


def fit_remesh(verts, tris, args, core_dir) -> dict:
    """Search for settings whose face count lands within tolerance of target_faces.

    The core's count is approximate and shape-dependent (measured on 63k-tri inputs, target 800–32000):
    - Suzanne: adaptivity 0 follows the request (0.85–1.1x); adaptivity 1 plateaus far below it (32k → 3.6k).
    - thin tube (1 m × 8 cm): adaptivity 0 stays at 3–8k faces whatever the request; adaptivity 1 gives 941.
    So: rescale the request; when the count stops responding to it, switch adaptivity to the other end
    (unless the caller fixed `adaptivity`); still over budget → one pass without preserve_thin (budget_strict).
    The closest result wins, preferring one not over the budget.
    """
    target = int(args["target_faces"])
    tol = float(args.get("tolerance", 0.2))
    passes_max = max(1, int(args.get("max_passes", 4))) if args.get("fit_target", True) else 1
    per_pass = float(args.get("timeout", 900.0))
    deadline = time.time() + float(args.get("total_timeout", 1200.0))
    may_flip = args.get("fit_target", True) and "adaptivity" not in args
    ad = float(args.get("adaptivity", 0.0))
    thin = bool(args.get("preserve_thin", True))
    passes, warnings, state = [], [], {"best": None, "total": 0.0}

    def attempt(request, ad, thin):
        left = deadline - time.time()
        if left < 5:
            return None
        res = remesh_arrays(verts, tris, {**args, "target_faces": request, "adaptivity": ad,
                                          "preserve_thin": thin, "timeout": min(per_pass, left)}, core_dir)
        row = {"requested": request, "adaptivity": ad, "preserve_thin": thin}
        if not res["ok"]:
            passes.append({**row, "error": res["error"]})
            state.setdefault("first_error", res)
            return None
        faces = int(len(res["face_sizes"]))
        state["total"] += res["seconds"]
        passes.append({**row, "faces": faces, "ratio": round(faces / target, 3), "seconds": res["seconds"]})
        score = (faces > target * (1 + tol), abs(math.log(faces / target)))
        if state["best"] is None or score < state["best"][0]:
            state["best"] = (score, res, ad, thin)
        return faces

    request, prev, flipped = target, None, False
    while len(passes) < passes_max:
        faces = attempt(request, ad, thin)
        if faces is not None and abs(faces / target - 1) <= tol:
            break
        stuck = faces is None                            # failed or timed out at these settings
        if not stuck and prev is not None:
            want = math.log(request / prev[0])
            got = math.log(faces / prev[1])
            stuck = want == 0 or got / want < 0.3        # the count no longer follows the request
        nxt = None
        if faces is not None:
            nxt = int(round(request * min(max(target / faces, 0.25), 4.0)))
            nxt = max(1, min(nxt, target * 8))           # never ask for more than 8x the budget
            stuck = stuck or nxt == request
        if stuck:
            if not may_flip or flipped or time.time() > deadline:
                break
            ad, flipped, request, prev = (1.0 if ad < 0.5 else 0.0), True, target, None
            continue
        prev, request = (request, faces), nxt

    best = state["best"]
    if best is None:
        err = state.get("first_error") or {"ok": False, "error": "no pass finished before total_timeout", "log": []}
        return {**err, "passes": passes}
    # Thin-feature sizing sets a density floor a low budget cannot meet (Suzanne, 1000 quads: 1.4x with it,
    # 1.1x without). A budget is a hard spec limit, so trade the thin parts for it — and say so.
    if (best[0][0] and best[3] and args.get("budget_strict", True)
            and attempt(target, best[2], False) is not None and state["best"][3] is False):
        warnings.append("preserve_thin turned off to meet the face budget (thin parts get coarser); "
                        "raise target_faces or pass budget_strict: false to keep them")
    _, res, used_ad, used_thin = state["best"]
    if used_ad != float(args.get("adaptivity", 0.0)):
        warnings.append(f"adaptivity {used_ad:g} used: the face count did not follow the request at "
                        f"{float(args.get('adaptivity', 0.0)):g} (pass adaptivity to fix it)")
    faces = len(res["face_sizes"])
    if abs(faces / target - 1) > tol:
        warnings.append(f"face count {faces} is outside ±{int(tol * 100)}% of target {target} after "
                        f"{len(passes)} pass(es); preserve_thin/island_detail/sharp edges may set a density floor")
    res.update(seconds=round(state["total"], 2), passes=passes, warnings=warnings,
               settings={"adaptivity": used_ad, "preserve_thin": used_thin})
    return res


def remesh_object(ob, args, core_dir, in_place=True, name=None) -> dict:
    """Remesh `ob` (local space). In place: swap its mesh data; else link a new object beside it."""
    verts, tris = mesh_arrays(ob)
    if not len(tris):
        return {"ok": False, "error": "mesh has no faces"}
    info = {"input_triangles": int(len(tris))}
    if args.get("weld_shells"):
        verts, tris, voxel = voxel_fuse(verts, tris, int(args["target_faces"]))
        info.update(weld_voxel=round(voxel, 6), welded_triangles=int(len(tris)))
        if not len(tris):
            return {"ok": False, "error": "weld_shells produced an empty mesh", **info}
    res = fit_remesh(verts, tris, args, core_dir)
    info["passes"] = res.pop("passes")
    if not res["ok"]:
        return {**res, **info}
    me = build_mesh(name or f"{ob.name}_autoremesh", res["verts"], res["face_indices"], res["face_sizes"])
    sizes = np.asarray(res["face_sizes"])
    info.update(seconds=res["seconds"], faces=int(len(sizes)), quads=int((sizes == 4).sum()),
                other_faces=int((sizes != 4).sum()), settings=res.get("settings"), log=res["log"])
    if res.get("warnings"):
        info["warnings"] = res["warnings"]
    # Material slots carry over; per-face material indices, UVs and vertex groups do not (new topology).
    if in_place:
        old = ob.data
        keep_name = old.name
        for m in old.materials:
            me.materials.append(m)
        ob.data = me
        if old.users == 0:
            bpy.data.meshes.remove(old)
        else:
            old.name = keep_name + "_pre_autoremesh"
        me.name = keep_name
        return {"ok": True, "object": ob, **info}
    new = bpy.data.objects.new(name or f"{ob.name}_autoremesh", me)
    for m in ob.data.materials:
        me.materials.append(m)
    new.matrix_world = ob.matrix_world.copy()
    for col in ob.users_collection or (bpy.context.scene.collection,):
        col.objects.link(new)
    return {"ok": True, "object": new, **info}


def run(args: dict) -> dict:
    args = args or {}
    found = probe(args.get("core_path"))
    if args.get("mode", "remesh") == "probe":
        return C.result_ok(**found)
    src = bpy.data.objects.get(args.get("source", ""))
    if src is None or src.type != "MESH":
        return C.result_error("source mesh required")
    if "target_faces" not in args:
        return C.result_error("target_faces required (from budgets.triangles / 2)")
    if not found["available"]:
        return C.result_error("autoremesher_core not available", **found)
    res = remesh_object(src, args, found["core_dir"], in_place=bool(args.get("in_place", False)),
                        name=args.get("name"))
    if not res.pop("ok"):
        return C.result_error(res.pop("error"), **res)
    ob = res.pop("object")
    ob.data.shade_smooth()
    return C.result_ok(object=ob.name, stats=C.mesh_stats(ob), autoremesher=res, core_dir=found["core_dir"])
