"""Video motion capture with MoCapAnything V2 — capture a clip, import the BVH, retarget it onto a project rig.

MoCapAnything V2 (MIT, github.com/kehong-gong/MoCapAnything) predicts the joint rotations of a reference
skeleton from a monocular video, for animals as well as people. It is installed by the user into its own
folder and Python environment (≈ 3 GB with weights and the demo data); nothing of it is bundled here. The
capture runs in that environment, in a separate process (`production/scripts/motion/mocapanything_runner.py`),
so Blender never imports torch.

Reference skeletons ("rigs") are the characters of the processed data folder: the demo data (`zoo1030`) has
80 animals (Cat, Dog, Horse, Eagle, Trex …), no human. The video may show a different animal than the rig
(eagle footage onto Parrot). A person or a project character needs its own rig preprocessed first
(MoCapAnything `examples/custom_rig`, CUDA). Output is in place: rotations only, no root trajectory.

Licences: code and weights MIT; the background remover it downloads (briaai/RMBG-1.4) is
non-commercial; the zoo1030 characters are Truebones Zoo data (no redistribution). Ask before shipping.

args:
    mode         (str, "apply")  "probe" | "rigs" | "capture" | "status" | "import" | "bones" | "retarget" |
                                 "apply" (capture + import + retarget when `target` is given)
    home         (str)           MoCapAnything checkout (default: env MOCAPANYTHING_HOME, else ~/MoCapAnything)
    python       (str)           its Python (default: <home>/.venv/bin/python, Windows .venv/Scripts/python.exe)
    data_dir     (str)           processed data root (default: <home>/demo/data/zoo1030)
    -- capture --
    video        (str)           input clip (one subject, whole body visible, static camera works best)
    rig          (str)           reference skeleton from `rigs` (e.g. "Cat")
    out_dir      (str)           default <project_dir>/working/mocap/<clip>, else a temp folder (warning)
    project_dir  (str)
    device       (str, "auto")   auto (cuda, else Apple mps, else cpu) | cpu | cuda | mps
    fps          (float, 15)     sampling rate (the model was trained at 15 fps)
    start, duration (float)      trim the clip (seconds); the model keeps at most 301 frames
    max_side     (int, 720)      downscale frames first (speed; background removal works at 1024 internally)
    preview      (bool, False)   also write the skeleton comparison video (slow on CPU)
    export_glb   (bool, False)   also write the rig's skinned mesh + skeleton as GLB
    wait         (bool, True)    False: start the capture and return; poll with mode "status" + out_dir
    timeout      (float, 3600)   seconds (wait=True)
    -- import --
    bvh          (str)           BVH to import (capture/apply pass it on)
    name         (str)           armature / clip name (default: the clip name); armature "MC_<name>",
                                 action "AN_<name>_mocap"
    scale        (float|"auto")  "auto": target's height when `target` is given, else 1 (BVH units are metres)
    -- bones / retarget --
    source       (str)           armature with the captured motion (default: the one just imported)
    target       (str)           armature to animate (project rig, game skeleton, Rigify FK controls)
    bone_map     (dict)          {"<target bone>": "<source bone>"}; default: built automatically (review it:
                                 mode "bones" returns the suggestion and both hierarchies)
    frame_start  (int)           first target frame (default: scene start)
    action       (str)           target action name (default "AN_<name>_mocap")
    yaw          (float|"auto")  rotation (deg, about Z) applied to the source so both face the same way;
                                 "auto" fits it from the mapped bones' rest positions
    ikfk         (float|None)    value keyed on every Rigify "IK_FK" property (default 1.0 = FK when FK
                                 controls are mapped; None leaves them)

returns (retarget): {target, action, frames, mapped, unmapped_target, error_deg {mean, max, worst}}
"""
from __future__ import annotations

import glob
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

import bpy
import numpy as np
from mathutils import Matrix


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

REPO_URL = "https://github.com/kehong-gong/MoCapAnything"
HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "")) or ".")
RUNNER = os.path.normpath(os.path.join(HERE, "..", "motion", "mocapanything_runner.py"))


# ---------------------------------------------------------------- install lookup
def _home(args):
    return os.path.abspath(os.path.expanduser(
        args.get("home") or os.environ.get("MOCAPANYTHING_HOME") or "~/MoCapAnything"))


def _python(args, home):
    if args.get("python"):
        return os.path.expanduser(args["python"])
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return os.path.join(home, ".venv", *sub)


def _data_dir(args, home):
    return os.path.abspath(os.path.expanduser(args.get("data_dir") or os.path.join(home, "demo", "data", "zoo1030")))


def list_rigs(data_dir) -> list:
    root = os.path.join(data_dir, "bvh_pose")
    if not os.path.isdir(root):
        return []
    return sorted({d.split("#")[0] for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))})


def probe(args) -> dict:
    home = _home(args)
    py = _python(args, home)
    data = _data_dir(args, home)
    ckpts = sorted(glob.glob(os.path.join(home, "checkpoints", "*.pt")))
    missing = []
    if not os.path.isfile(os.path.join(home, "inference", "video2pose2rot.py")):
        missing.append(f"checkout ({home})")
    if not os.path.isfile(py):
        missing.append(f"python environment ({py})")
    if not ckpts:
        missing.append(f"checkpoint ({os.path.join(home, 'checkpoints', '*.pt')})")
    rigs = list_rigs(data)
    if not rigs:
        missing.append(f"processed data with bvh_pose/ ({data})")
    info = {"available": not missing, "home": home, "python": py, "data_dir": data,
            "checkpoint": ckpts[0] if ckpts else None, "rigs": len(rigs), "runner": RUNNER}
    if missing:
        info["missing"] = missing
        info["install"] = (f"Clone {REPO_URL} to ~/MoCapAnything (or set MOCAPANYTHING_HOME), create .venv with "
                           "Python 3.11 and its requirements, download the checkpoint and demo data "
                           "(see docs/BLENDER_MCP_SETUP.md, 'Optional — MoCapAnything V2'). Ask the user before "
                           "downloading: several GB, third-party licences.")
        return info
    if args.get("check_torch", True):
        try:
            r = subprocess.run([py, "-c", "import torch,json;print(json.dumps({'torch':torch.__version__,"
                                "'cuda':torch.cuda.is_available(),'mps':bool(getattr(torch.backends,'mps',None) "
                                "and torch.backends.mps.is_available())}))"],
                               capture_output=True, text=True, timeout=120)
            info.update(json.loads(r.stdout.strip().splitlines()[-1]))
        except Exception as e:  # noqa: BLE001
            info.update(available=False, missing=[f"torch import failed: {e}"])
    return info


# ---------------------------------------------------------------- capture (external process)
def _clip_name(video):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(os.path.basename(video))[0]) or "clip"


def _out_dir(args, clip, warnings):
    if args.get("out_dir"):
        return os.path.abspath(os.path.expanduser(args["out_dir"]))
    if args.get("project_dir"):
        return os.path.join(args["project_dir"], "working", "mocap", clip)
    warnings.append("no project_dir/out_dir: results are in a temp folder — move them into the project")
    return tempfile.mkdtemp(prefix=f"u3d_mocap_{clip}_")


def read_status(out_dir) -> dict:
    log = os.path.join(out_dir, "mocap.log")
    if not os.path.isfile(log):
        return {"state": "missing", "log": log}
    with open(log, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    res = next((ln[7:] for ln in reversed(lines) if ln.startswith("RESULT ")), None)
    if res:
        return {"state": "done", "log": log, **json.loads(res)}
    err = [ln[6:] for ln in lines if ln.startswith("ERROR ")]
    stages = [ln[9:] for ln in lines if ln.startswith("PROGRESS ")]
    pid_file = os.path.join(out_dir, "mocap.pid")
    running = False
    if os.path.isfile(pid_file):
        try:
            pid = int(open(pid_file).read().strip())
            os.kill(pid, 0)
            running = True
        except (OSError, ValueError):
            running = False
    if err or not running:
        tail = [ln for ln in lines if not ln.startswith(("PROGRESS", "RESULT"))][-6:]
        return {"state": "failed", "log": log, "error": err[0] if err else "runner exited without a result",
                "stage": stages[-1] if stages else None, "tail": tail}
    return {"state": "running", "log": log, "stage": stages[-1] if stages else "starting"}


def capture(args, warnings) -> dict:
    found = probe({**args, "check_torch": False})
    if not found["available"]:
        return {"error": "MoCapAnything not installed", **found}
    video = os.path.abspath(os.path.expanduser(args.get("video") or ""))
    if not os.path.isfile(video):
        return {"error": f"video not found: {args.get('video')!r}"}
    rig = args.get("rig")
    rigs = list_rigs(found["data_dir"])
    if rig not in rigs:
        return {"error": f"rig {rig!r} not in {found['data_dir']}", "rigs": rigs}
    clip = _clip_name(video)
    out_dir = _out_dir(args, clip, warnings)
    os.makedirs(out_dir, exist_ok=True)
    job = {"home": found["home"], "video": video, "rig": rig, "data_dir": found["data_dir"],
           "out_dir": out_dir, "device": args.get("device", "auto"), "fps": args.get("fps", 15),
           "start": args.get("start"), "duration": args.get("duration"), "max_side": args.get("max_side", 720),
           "preview": bool(args.get("preview")), "export_glb": bool(args.get("export_glb"))}
    job_path = os.path.join(out_dir, "mocap_job.json")
    C.write_json(job_path, job)
    log_path = os.path.join(out_dir, "mocap.log")
    env = dict(os.environ, PYTHONUNBUFFERED="1", TOKENIZERS_PARALLELISM="false")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([found["python"], RUNNER, job_path], stdout=log, stderr=subprocess.STDOUT,
                                cwd=found["home"], env=env, creationflags=flags)
    with open(os.path.join(out_dir, "mocap.pid"), "w") as f:
        f.write(str(proc.pid))
    info = {"out_dir": out_dir, "clip": clip, "rig": rig, "pid": proc.pid, "log": log_path}
    if not args.get("wait", True):
        return {**info, "state": "running"}
    deadline = time.time() + float(args.get("timeout", 3600))
    while proc.poll() is None:
        if time.time() > deadline:
            proc.kill()
            proc.wait()
            return {**info, "error": f"capture timed out after {args.get('timeout', 3600)} s"}
        time.sleep(1.0)
    st = read_status(out_dir)
    if st["state"] != "done":
        return {**info, "error": st.get("error", "capture failed"), **st}
    return {**info, **st}


# ---------------------------------------------------------------- import
def _armature_height(ob) -> float:
    zs = [(ob.matrix_world @ b.head_local).z for b in ob.data.bones] + \
         [(ob.matrix_world @ b.tail_local).z for b in ob.data.bones]
    return max(zs) - min(zs) if zs else 0.0


def import_bvh(path, name, scale=1.0, frame_start=None) -> bpy.types.Object:
    sc = bpy.context.scene
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=path, target="ARMATURE", global_scale=1.0,
                            frame_start=int(frame_start if frame_start is not None else sc.frame_start),
                            use_fps_scale=True, update_scene_fps=False, update_scene_duration=False,
                            rotate_mode="NATIVE", axis_forward="-Z", axis_up="Y")
    new = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
    if not new:
        raise RuntimeError(f"BVH import created no armature: {path}")
    ob = new[0]
    ob.name = f"MC_{name}"
    ob.data.name = f"MC_{name}"
    if ob.animation_data and ob.animation_data.action:
        ob.animation_data.action.name = f"AN_{name}_mocap_src"
    ob.scale = (scale, scale, scale)
    ob.show_in_front = True
    coll = bpy.data.collections.get("MOCAP") or bpy.data.collections.new("MOCAP")
    if coll.name not in sc.collection.children:
        sc.collection.children.link(coll)
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)
    bpy.context.view_layer.update()
    return ob


def _action_range(ob):
    act = ob.animation_data.action if ob.animation_data else None
    if act is None:
        return None
    a, b = act.frame_range
    return int(math.floor(a)), int(math.ceil(b))


# ---------------------------------------------------------------- bone map
_SKIP = re.compile(r"(^|[^a-z])(mch|org|tweak|ik|pole|target|parent|prop|vis|socket|root|torso|master|"
                   r"properties|nub)([^a-z]|$)", re.I)
_DRIVEN = {"COPY_TRANSFORMS", "COPY_ROTATION", "CHILD_OF", "DAMPED_TRACK", "IK", "STRETCH_TO", "TRACK_TO",
           "LOCKED_TRACK", "ARMATURE"}
_ROLES = [  # (role, pattern on the cleaned lowercase name) — first match wins
    ("clavicle", r"clavicle|shoulder|scapula|collar"),
    ("upperarm", r"upper ?arm|uparm|^arm$|humerus"),
    ("forearm", r"fore ?arm|lower ?arm|lowarm|elbow|radius"),
    ("hand", r"hand|wrist|carpal|front ?foot|palm"),
    ("finger", r"finger|thumb|index|middle|ring|pinky|claw"),
    ("thigh", r"thigh|up ?leg|upper ?leg|femur"),
    ("horselink", r"horse ?link|hock|metatars|ankle"),
    ("shin", r"calf|shin|low ?leg|lower ?leg|knee|tibia|^leg$"),
    ("foot", r"foot|paw|hoof"),
    ("toe", r"toe|digit"),
    ("tail", r"tail|tai$"),
    ("wing", r"wing"),
    ("jaw", r"\bjaw|\bmouth|\bchin"),
    ("ear", r"\bears?\b"),
    ("head", r"head|skull"),
    ("neck", r"neck"),
    ("spine", r"spine|chest|torso|pelvis|hips?|back|abdomen|body"),
]


def _clean(name):
    n = re.sub(r"^(DEF|ORG|MCH|mixamorig|Bip0?1|BN|CC_Base|b)[_:\-. ]", "", name, flags=re.I)
    n = re.sub(r"([a-z])([A-Z])", r"\1 \2", n)
    return re.sub(r"[_:.\-]+", " ", n).strip().lower()


def _side(name):
    n = name.lower()
    if re.search(r"(^|[_. \-:])(l|left)([_. \-:]|$)|\.l$|_l$|left", n):
        return "L"
    if re.search(r"(^|[_. \-:])(r|right)([_. \-:]|$)|\.r$|_r$|right", n):
        return "R"
    return "C"


def _role(name):
    n = _clean(name)
    n = re.sub(r"\b(l|r|left|right)\b", " ", n).strip()
    n = re.sub(r"\d+$", "", n).strip()
    for role, pat in _ROLES:
        if re.search(pat, n):
            return role
    return None


def _depth(bone):
    d = 0
    while bone.parent:
        bone, d = bone.parent, d + 1
    return d


def _overrides(c) -> bool:
    """A constraint that replaces the bone's own rotation (keys would do nothing). Additive Copy Rotation
    (Rigify tail and finger chains) is fine: retarget() corrects for it."""
    if c.mute or c.influence <= 0 or c.type not in _DRIVEN:
        return False
    return not (c.type == "COPY_ROTATION" and getattr(c, "mix_mode", "REPLACE") != "REPLACE")


def _candidates(ob, target=False):
    """Bones that can take keys: on a target, no helper names (MCH/ORG/IK/tweak …) and no driving constraint.

    On a generated Rigify rig (it has ORG- bones) only controls qualify: DEF-/ORG-/MCH- bones are driven, and
    the IK spine controls `hips` / `chest` are left alone when the FK spine (`spine_fk*`) is there.
    """
    names = set(ob.data.bones.keys())
    rigify = target and any(n.startswith("ORG-") for n in names)
    fk_spine = rigify and any(n.startswith("spine_fk") for n in names)
    out = []
    for b in ob.data.bones:
        if target:
            if _SKIP.search(b.name):
                continue
            if rigify and (b.name.startswith(("DEF-", "ORG-", "MCH-")) or (fk_spine and b.name in {"hips", "chest"})):
                continue
            if any(_overrides(c) for c in ob.pose.bones[b.name].constraints):
                continue
        out.append(b)
    return out


def _natural(name):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name.lower())]


def _order(bones):
    """Root-to-tip: by depth when the bones lie on one parent chain, else by natural name (spine_fk, .001 …)."""
    by_depth = sorted(bones, key=lambda b: (_depth(b), _natural(b.name)))
    chain = all(by_depth[i] in by_depth[i + 1].parent_recursive for i in range(len(by_depth) - 1))
    return by_depth if chain else sorted(bones, key=lambda b: _natural(b.name))


def _groups(ob, target=False):
    g = {}
    for b in _candidates(ob, target):
        role = _role(b.name)
        if role is None:
            continue
        g.setdefault((role, _side(b.name)), []).append(b)
    for k in list(g):
        bones = _order(g[k])
        if not target:  # a BVH root at the same spot as its first child (Hips -> Pelvis) duplicates it
            bones = [b for b in bones if not any(c in bones and (c.head_local - b.head_local).length < 1e-6
                                                 for c in b.children)] or bones
        g[k] = bones
    return g


def auto_map(src, tgt) -> dict:
    """{target bone: source bone} by role (spine/neck/tail chains resampled by position along the chain)."""
    gs, gt = _groups(src), _groups(tgt, target=True)
    m = {}
    for key, tb in gt.items():
        sb = gs.get(key)
        if not sb:
            continue
        if len(sb) == 1 and len(tb) > 1:
            # one source bone drives the whole group rigidly; constrained followers (Rigify finger chains copy
            # rotation on limited axes) would fight it, so only free bones take it
            free = [b for b in tb if not any(not c.mute and c.influence > 0 for c in tgt.pose.bones[b.name].constraints)]
            tb = free or tb[:1]
        if len(tb) == 1:
            m[tb[0].name] = sb[0].name if key[0] not in {"head", "hand", "foot"} else sb[-1].name
            continue
        for i, b in enumerate(tb):
            j = round(i * (len(sb) - 1) / (len(tb) - 1)) if len(tb) > 1 else 0
            m[b.name] = sb[j].name
    # Digitigrade source legs (Biped: thigh, calf, HorseLink = metatarsus, foot = toes) onto 3+1-bone rig legs
    # (thigh, shin, foot = metatarsus, toe): shift foot and toe down one bone.
    for side in ("L", "R"):
        hl, sf = gs.get(("horselink", side)), gs.get(("foot", side))
        if not hl or gt.get(("horselink", side)):
            continue
        for b in gt.get(("foot", side), []):
            m[b.name] = hl[0].name
        for b in gt.get(("toe", side), []):
            if sf:
                m[b.name] = sf[-1].name
    return m


def bones_report(ob):
    return [{"name": b.name, "parent": b.parent.name if b.parent else None, "role": _role(b.name),
             "side": _side(b.name), "length": round(b.length, 4)} for b in ob.data.bones]


# ---------------------------------------------------------------- retarget
def _rot3(m):
    return m.to_3x3().normalized()


def _fit_yaw(src, tgt, bone_map) -> float:
    """Best rotation about Z (deg) taking the source's mapped rest heads onto the target's (2-D Kabsch)."""
    pairs = [(tgt.matrix_world @ tgt.data.bones[t].head_local, src.matrix_world @ src.data.bones[s].head_local)
             for t, s in bone_map.items()]
    if len(pairs) < 3:
        return 0.0
    T = np.array([[p.x, p.y] for p, _ in pairs])
    S = np.array([[q.x, q.y] for _, q in pairs])
    T -= T.mean(0)
    S -= S.mean(0)
    h = S.T @ T
    return math.degrees(math.atan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1]))


def _angle(a, b) -> float:
    d = (a.inverted() @ b).to_quaternion()
    return math.degrees(2 * math.acos(min(1.0, abs(d.w))))


def _rest_parent(pb):
    """Armature-space rotation the bone's basis is applied to: parent pose x rest offset (rest alone at root)."""
    rest = _rot3(pb.bone.matrix_local)
    if pb.parent is None:
        return rest
    return _rot3(pb.parent.matrix) @ _rot3(pb.parent.bone.matrix_local).inverted() @ rest


def _key_rotation(pb, frame, prev):
    """Key the bone's rotation, kept continuous with its previous key (no quaternion sign / euler flips)."""
    if pb.rotation_mode == "QUATERNION":
        q = pb.rotation_quaternion.copy()
        if pb.name in prev and q.dot(prev[pb.name]) < 0:
            pb.rotation_quaternion = -q
        prev[pb.name] = pb.rotation_quaternion.copy()
        path = "rotation_quaternion"
    elif pb.rotation_mode == "AXIS_ANGLE":
        path = "rotation_axis_angle"
    else:
        if pb.name in prev:
            pb.rotation_euler = pb.rotation_euler.to_matrix().to_euler(pb.rotation_mode, prev[pb.name])
        prev[pb.name] = pb.rotation_euler.copy()
        path = "rotation_euler"
    pb.keyframe_insert(path, frame=frame, group=pb.name)


def retarget(src, tgt, bone_map, frame_start=None, action_name=None, yaw="auto", ikfk=1.0) -> dict:
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    rng = _action_range(src)
    if rng is None:
        raise RuntimeError(f"{src.name} has no action")
    bad = [f"{t}->{s}" for t, s in bone_map.items() if t not in tgt.pose.bones or s not in src.pose.bones]
    if bad:
        raise KeyError(f"bone_map names not found: {bad[:8]}")
    if not tgt.animation_data:
        tgt.animation_data_create()
    prev_action = tgt.animation_data.action
    act = bpy.data.actions.new(action_name or f"AN_{src.name[3:]}_mocap")
    act.use_fake_user = True
    tgt.animation_data.action = act
    for pb in tgt.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)

    yaw_deg = _fit_yaw(src, tgt, bone_map) if yaw == "auto" else float(yaw or 0.0)
    Ry = Matrix.Rotation(math.radians(yaw_deg), 3, "Z")
    Ws, Wt = _rot3(src.matrix_world), _rot3(tgt.matrix_world)
    s_rest = {s: _rot3(src.data.bones[s].matrix_local) for s in bone_map.values()}
    t_rest = {t: _rot3(tgt.data.bones[t].matrix_local) for t in bone_map}
    levels = {}
    for t in bone_map:
        levels.setdefault(_depth(tgt.data.bones[t]), []).append(t)
    order = [levels[d] for d in sorted(levels)]

    ik_props = []
    if ikfk is not None:
        ik_props = [(pb, "IK_FK") for pb in tgt.pose.bones if "IK_FK" in pb.keys()]

    f0 = int(frame_start if frame_start is not None else rng[0])
    errs = {t: [] for t in bone_map}
    frames = list(range(rng[0], rng[1] + 1))
    prev = {}
    # Keys go on the SOURCE frame numbers and are shifted at the end: re-evaluating the target's new action at
    # another frame would overwrite the pose being built. Each bone is keyed right after it is set, before the
    # next update, for the same reason; parents are set (and evaluated) before their children.
    for f in frames:
        sc.frame_set(f)
        dw = {}
        for t, s in bone_map.items():
            sp = _rot3(src.pose.bones[s].matrix)
            dw[t] = Ry @ Ws @ sp @ s_rest[s].inverted() @ Ws.inverted() @ Ry.inverted()
        for pb, prop in ik_props:
            pb[prop] = float(ikfk)
            pb.keyframe_insert(f'["{prop}"]', frame=f, group=pb.name)
        for level in order:
            want = {t: Wt.inverted() @ dw[t] @ Wt @ t_rest[t] for t in level}
            for t in level:
                pb = tgt.pose.bones[t]
                loc, _, scl = pb.matrix.decompose()
                pb.matrix = Matrix.LocRotScale(loc, want[t].to_quaternion(), scl)
                _key_rotation(pb, f, prev)
            vl.update()
            # Additive constraints (Rigify chains copy their parent's rotation) move the result off target:
            # correct the key in the bone's own space, b' = P^-1 D A^-1 P b, a few rounds.
            for _ in range(3):
                off = [t for t in level if _angle(_rot3(tgt.pose.bones[t].matrix), want[t]) > 0.05]
                if not off:
                    break
                for t in off:
                    pb = tgt.pose.bones[t]
                    P = _rest_parent(pb)
                    A = _rot3(pb.matrix)
                    b = pb.matrix_basis.to_3x3().normalized()
                    nb = (P.inverted() @ want[t] @ A.inverted() @ P @ b).to_quaternion()
                    loc, _, scl = pb.matrix_basis.decompose()
                    pb.matrix_basis = Matrix.LocRotScale(loc, nb, scl)
                    _key_rotation(pb, f, prev)
                vl.update()
        if f % 5 == 0 or f == frames[-1]:
            for t in bone_map:
                got = Wt @ _rot3(tgt.pose.bones[t].matrix) @ t_rest[t].inverted() @ Wt.inverted()
                errs[t].append(_angle(got, dw[t]))
    shift = f0 - rng[0]
    if shift:
        for fc in C.action_fcurves(act):
            for kp in fc.keyframe_points:
                kp.co.x += shift
                kp.handle_left.x += shift
                kp.handle_right.x += shift
            fc.update()
    if prev_action is not None and prev_action != act:
        prev_action.use_fake_user = True
    per = {t: max(v) for t, v in errs.items() if v}
    allv = [x for v in errs.values() for x in v]
    worst = sorted(per.items(), key=lambda kv: -kv[1])[:5]
    return {"target": tgt.name, "action": act.name, "frames": [f0, f0 + len(frames) - 1], "yaw_deg": round(yaw_deg, 1),
            "mapped": len(bone_map), "ikfk_keyed": len(ik_props),
            "error_deg": {"mean": round(float(np.mean(allv)), 2) if allv else None,
                          "max": round(float(np.max(allv)), 2) if allv else None,
                          "worst": [[k, round(v, 1)] for k, v in worst]}}


# ---------------------------------------------------------------- entry
def _armature(name):
    ob = bpy.data.objects.get(name or "")
    return ob if ob is not None and ob.type == "ARMATURE" else None


def run(args: dict) -> dict:
    mode = args.get("mode", "apply")
    warnings = []
    if mode == "probe":
        info = probe(args)
        return C.result_ok(**info) if info["available"] else C.result_error("MoCapAnything not available", **info)
    if mode == "rigs":
        data = _data_dir(args, _home(args))
        rigs = list_rigs(data)
        return C.result_ok(data_dir=data, rigs=rigs) if rigs else C.result_error(f"no rigs in {data}")
    if mode == "status":
        if not args.get("out_dir"):
            return C.result_error("status needs out_dir")
        st = read_status(args["out_dir"])
        return C.result_error(st.pop("error"), **st) if st["state"] == "failed" else C.result_ok(**st)

    cap = None
    if mode in {"capture", "apply"}:
        cap = capture(args, warnings)
        if "error" in cap:
            return C.result_error(cap.pop("error"), warnings=warnings, **cap)
        if mode == "capture" or cap.get("state") == "running":
            return C.result_ok(warnings=warnings, **cap)

    src = _armature(args.get("source"))
    tgt = _armature(args.get("target"))
    if args.get("target") and tgt is None:
        return C.result_error(f"target armature not found: {args['target']!r}", capture=cap)
    imported = None
    if mode in {"import", "apply"}:
        bvh = args.get("bvh") or (cap or {}).get("files", {}).get("bvh")
        if not bvh or not os.path.isfile(bvh):
            return C.result_error(f"bvh not found: {bvh!r}", capture=cap)
        name = args.get("name") or (cap or {}).get("clip") or _clip_name(bvh)
        src = import_bvh(bvh, name, frame_start=args.get("frame_start"))
        scale = args.get("scale", "auto")
        h = _armature_height(src)
        if scale == "auto":
            scale = (_armature_height(tgt) / h) if (tgt is not None and h > 1e-6) else 1.0
        src.scale = (float(scale),) * 3
        bpy.context.view_layer.update()
        imported = {"armature": src.name, "bones": len(src.data.bones), "frames": list(_action_range(src) or []),
                    "scale": round(float(scale), 4), "bvh": bvh}
        if mode == "import" or tgt is None:
            return C.result_ok(imported=imported, capture=cap, warnings=warnings)

    if src is None:
        return C.result_error(f"source armature not found: {args.get('source')!r}")
    if mode == "bones":
        out = {"source": bones_report(src)}
        if tgt is not None:
            out["target"] = bones_report(tgt)
            out["suggested_map"] = auto_map(src, tgt)
        return C.result_ok(**out)
    if tgt is None:
        return C.result_error("retarget needs target")
    bone_map = args.get("bone_map") or auto_map(src, tgt)
    if not bone_map:
        return C.result_error("no bones could be mapped automatically; pass bone_map",
                              source=bones_report(src), target=bones_report(tgt))
    name = args.get("name") or src.name.removeprefix("MC_")
    try:
        res = retarget(src, tgt, bone_map, frame_start=args.get("frame_start"),
                       action_name=args.get("action") or f"AN_{name}_mocap", yaw=args.get("yaw", "auto"),
                       ikfk=args.get("ikfk", 1.0) if any(n.endswith(("_fk.L", "_fk.R")) or "_fk." in n
                                                          for n in bone_map) else None)
    except (KeyError, RuntimeError) as e:
        return C.result_error(str(e))
    if res["error_deg"]["max"] is not None and res["error_deg"]["max"] > 10:
        warnings.append("some bones follow the source poorly (locked axes, constraints, or rest poses that differ); "
                        "see error_deg.worst")
    return C.result_ok(**res, bone_map=bone_map, imported=imported, capture=cap, warnings=warnings)
