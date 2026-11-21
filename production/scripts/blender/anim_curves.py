"""Key and curve tools for polishing animation through the MCP (no Graph Editor needed).

Inspired by the animator workflow of AnimAide (aresdevo/animaide, GPL-3): the ideas — tween, blend to
neighbours, push/pull, smooth, anim offset with a falloff mask, time offset — are re-implemented here
from scratch; no AnimAide code is used. Chain overlap, exact loops and loop-window extraction follow the
measured rules of blender-kiln (MIT) `references/animation.md` (rules 1, 4, 5).

Every op works on the F-curves picked by `bones` / `channels` / `indices` in one action, on the keys
inside `frames` (the "selection"). The keys just outside the selection are its neighbours.

args:
    object      (str, required)   armature or object that owns the animation
    action      (str)             action name (default: the object's active action); "AN_" prefix optional
    bones       (list[str])       fnmatch patterns of pose bones (default: every bone; ignored for objects)
    channels    (list[str])       "location" | "rotation" | "scale" | "props" (custom properties) or exact
                                  property names ("rotation_quaternion"). Default ["location", "rotation"]
    indices     (list[int])       array indices to keep (quaternion: 0=w 1=x 2=y 3=z). Default all
    frames      ([f0, f1])        selection range (inclusive). Default: every key of each curve
    backup      (bool, True)      copy the action to "<action>__bak" before the first edit (kept if it exists)
    op          (str)             one op, its parameters at the top level of args, or
    ops         (list[dict])      several ops applied in order: [{"op": "smooth", "iterations": 2}, ...]

ops (values are written in the curve's own units — radians, metres):
    tween          t (0..1, 0.5)            every selected key at one value between the neighbours
                   mode ("flat"|"linear")   "linear": each key on the straight line between the neighbours
    blend_neighbor factor (-1..1)           towards the left (<0) or right (>0) neighbour
    blend_frame    frame, factor (0..1)     towards the value the curve had at `frame`
    blend_default  factor (0..1)            towards the rest value (0; scale 1; quaternion w 1)
    push_pull      factor                   exaggerate (>0) or flatten (<0, -1 = straight line) the selection
                                            relative to the line between the neighbours
    smooth         iterations (1), factor (0.5), cyclic (False)   neighbour averaging over the keys
    ease           shape ("inout"|"in"|"out"), power (2)   keys on an ease curve between the neighbours
    scale          factor, pivot ("average"|"left"|"right"|"rest"|number)
    time_offset    shift (frames), cyclic (True)   move the motion in time (value at x := value at x - shift)
    wave           amplitude, period (frames), phase (rad, 0), kind ("sine"|"noise"), seed (0)
    offset         anim-offset layer: add a delta to the selection with a smooth falloff `blend` frames
                   wide on each side (default 0 = hard edges). Delta from
                     delta     {bone: {channel: [values]}}  (rotation_quaternion: a quaternion multiplied in)
                     from_pose frame — the difference between the current (posed) values and the curves at
                               `frame`: pose the rig by script, then spread that change over the range
    overlap        chain [bone, ...] (root first), lag (frames per link, 2), mode ("follow"|"delay"),
                   gain (1.0), falloff (0.8 per link), cyclic (True), step (1)
                     follow: each link adds the FIRST bone's rotation from `lag * i` frames earlier, carried
                             through the bones' rest orientations, scaled by gain * falloff^(i-1)
                     delay:  each link's own curves are shifted `lag * i` frames later (resampled first)
    match_cycle    period (frame where the loop closes; default last key), mode ("first"|"average"):
                   the key at `period` equals the first key (rule 5: glTF plays the closing key);
                   quaternion signs kept continuous
    loop_window    min_len (12), crossfade (4), root (bone whose horizontal drift is removed), out (name):
                   writes a NEW action — the window whose end matches its start in pose and direction,
                   cross-faded, root drift removed, keyed every frame with key P = key 0
    resample       step (1)                 re-key every `step` frames (keeps the shape; needed before delay)
    clean          tolerance (0.001)        delete keys the curve does not need within tolerance
    interpolation  interpolation ("BEZIER"|"LINEAR"|"CONSTANT"|...), easing, handle_type ("AUTO_CLAMPED"...)
    restore        copy "<action>__bak" back over the action

returns: per op {op, curves, keys, max_change}, plus op-specific data.
Quaternion keys touched are re-normalised at frames where all four components have a key.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import math
import os
import random
import re
import sys

import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion


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
EPS = 1e-4
_BONE_RE = re.compile(r'^pose\.bones\["(.+?)"\]\.(.+)$')


# ---------------------------------------------------------------- curve access
def _find_action(obj, name):
    if name:
        return bpy.data.actions.get(name) or bpy.data.actions.get("AN_" + name)
    ad = obj.animation_data
    return ad.action if ad else None


def _slot_for(obj, act):
    ad = obj.animation_data
    if ad is not None and ad.action == act and getattr(ad, "action_slot", None) is not None:
        return ad.action_slot
    slots = getattr(act, "slots", None)
    return slots[0] if slots else None


def _parse(fc):
    """(bone or None, property name) of an F-curve's data path."""
    m = _BONE_RE.match(fc.data_path)
    if m:
        return m.group(1), m.group(2)
    return None, fc.data_path


def _prop_matches(prop, channels):
    for c in channels:
        if c == prop:
            return True
        if c == "rotation" and prop.startswith("rotation_"):
            return True
        if c in ("location", "scale") and prop == c:
            return True
        if c == "props" and prop.startswith('["'):
            return True
    return False


def select_fcurves(obj, act, args):
    fcs = C.action_fcurves(act, _slot_for(obj, act))
    pats = args.get("bones")
    chans = args.get("channels") or ["location", "rotation"]
    idx = args.get("indices")
    out = []
    for fc in fcs:
        bone, prop = _parse(fc)
        if obj.type == "ARMATURE" and pats and (bone is None or not any(fnmatch.fnmatch(bone, p) for p in pats)):
            continue
        if not _prop_matches(prop, chans):
            continue
        if idx is not None and fc.array_index not in idx:
            continue
        out.append(fc)
    return out


def _new_fcurve(act, obj, path, index, group=None):
    try:
        fc = act.fcurve_ensure_for_datablock(obj, path, index=index, group_name=group or "")
    except TypeError:
        fc = act.fcurve_ensure_for_datablock(obj, path, index=index)
    except AttributeError:  # pre-4.4 legacy actions
        fc = act.fcurves.find(path, index=index) or act.fcurves.new(path, index=index, action_group=group or "")
    return fc


import contextlib


@contextlib.contextmanager
def assigned(obj, act):
    """Temporarily make `act` the object's active action (Blender 5 creates F-curves only for assigned slots)."""
    ad = obj.animation_data or obj.animation_data_create()
    prev_act = ad.action
    prev_slot = getattr(ad, "action_slot", None)
    if prev_act != act:
        ad.action = act
        if getattr(act, "slots", None) and len(act.slots):
            ad.action_slot = act.slots[0]
    try:
        yield
    finally:
        if prev_act != act:
            ad.action = prev_act
            if prev_act is not None and prev_slot is not None:
                try:
                    ad.action_slot = prev_slot
                except (TypeError, RuntimeError):
                    pass


def _keys(fc):
    kp = fc.keyframe_points
    co = np.empty(len(kp) * 2)
    kp.foreach_get("co", co)
    return co.reshape(-1, 2)


def _selected(fc, frames):
    co = _keys(fc)
    if frames is None:
        return list(range(len(co)))
    f0, f1 = frames
    return [i for i, (x, _) in enumerate(co) if f0 - EPS <= x <= f1 + EPS]


def _set_value(kp, v):
    d = v - kp.co.y
    kp.co.y = v
    kp.handle_left.y += d
    kp.handle_right.y += d


def _rest_value(fc):
    _, prop = _parse(fc)
    if prop == "scale":
        return 1.0
    if prop == "rotation_quaternion" and fc.array_index == 0:
        return 1.0
    if prop == "rotation_axis_angle" and fc.array_index == 2:
        return 1.0
    return 0.0


def _neighbors(fc, sel):
    """Left / right neighbour (frame, value) of a selection; a bookend uses the selection's own end key."""
    kp = fc.keyframe_points
    i0, i1 = sel[0], sel[-1]
    left = kp[i0 - 1] if i0 > 0 else kp[i0]
    right = kp[i1 + 1] if i1 + 1 < len(kp) else kp[i1]
    return (left.co.x, left.co.y), (right.co.x, right.co.y)


def _sampler(fc, cyclic, span=None):
    """Value of the ORIGINAL curve at any frame (captured now), wrapping over the key span when cyclic."""
    co = _keys(fc)
    if len(co) == 0:
        return lambda x: 0.0
    a, b = span if span else (co[0, 0], co[-1, 0])
    xs = np.arange(math.floor(a), math.ceil(b) + 1, 0.25)
    ys = np.array([fc.evaluate(float(x)) for x in xs])
    period = b - a

    def f(x):
        if cyclic and period > 0:
            x = a + (x - a) % period
        return float(np.interp(x, xs, ys))
    return f


# ---------------------------------------------------------------- quaternion helpers
def _quat_groups(fcs):
    """{bone: [fc_w, fc_x, fc_y, fc_z]} for complete quaternion sets among the picked curves."""
    g = {}
    for fc in fcs:
        bone, prop = _parse(fc)
        if prop == "rotation_quaternion":
            g.setdefault(bone, [None] * 4)[fc.array_index] = fc
    return {b: v for b, v in g.items() if all(v)}


def _normalize_quats(fcs):
    n = 0
    for bone, q in _quat_groups(fcs).items():
        frames = set(round(k.co.x, 4) for k in q[0].keyframe_points)
        for fc in q[1:]:
            frames &= set(round(k.co.x, 4) for k in fc.keyframe_points)
        maps = [{round(k.co.x, 4): k for k in fc.keyframe_points} for fc in q]
        for fr in frames:
            ks = [m[fr] for m in maps]
            v = np.array([k.co.y for k in ks])
            norm = np.linalg.norm(v)
            if norm > 1e-8 and abs(norm - 1.0) > 1e-6:
                for k, c in zip(ks, v / norm):
                    _set_value(k, float(c))
                n += 1
    for fc in fcs:
        fc.update()
    return n


def _eval_quat(q_fcs, x):
    return Quaternion([fc.evaluate(x) for fc in q_fcs]).normalized()


def _rot_mode(obj, bone):
    pb = obj.pose.bones.get(bone) if obj.type == "ARMATURE" and bone else None
    return (pb or obj).rotation_mode


def _rot_curves(act_fcs, bone):
    """Rotation curves of one bone, by mode: {"quat": [4]} or {"euler": [3]}."""
    q = [None] * 4
    e = [None] * 3
    for fc in act_fcs:
        b, prop = _parse(fc)
        if b != bone:
            continue
        if prop == "rotation_quaternion":
            q[fc.array_index] = fc
        elif prop == "rotation_euler":
            e[fc.array_index] = fc
    return q, e


def _local_rot(obj, act_fcs, bone, x, mode):
    q, e = _rot_curves(act_fcs, bone)
    if mode == "QUATERNION":
        if all(q):
            return _eval_quat(q, x)
        return Quaternion()
    vals = [fc.evaluate(x) if fc else 0.0 for fc in e]
    return Euler(vals, mode).to_quaternion()


def _key_rot(obj, act, bone, x, quat, mode, prev_euler=None):
    """Insert a rotation key on bone at frame x (in the bone's own rotation mode)."""
    path = f'pose.bones["{bone}"].'
    if mode == "QUATERNION":
        for i, c in enumerate(quat):
            fc = _new_fcurve(act, obj, path + "rotation_quaternion", i, bone)
            fc.keyframe_points.insert(x, c, options={"FAST"})
        return None
    eu = quat.to_euler(mode, prev_euler) if prev_euler is not None else quat.to_euler(mode)
    for i, c in enumerate(eu):
        fc = _new_fcurve(act, obj, path + "rotation_euler", i, bone)
        fc.keyframe_points.insert(x, c, options={"FAST"})
    return eu


# ---------------------------------------------------------------- per-curve ops
def _apply_values(fc, new_vals):
    """new_vals: {key index: value}. Returns max |change|."""
    kp = fc.keyframe_points
    worst = 0.0
    for i, v in new_vals.items():
        worst = max(worst, abs(v - kp[i].co.y))
        _set_value(kp[i], float(v))
    fc.update()
    return worst


def op_tween(fc, sel, p):
    (xl, yl), (xr, yr) = _neighbors(fc, sel)
    t = float(p.get("t", 0.5))
    kp = fc.keyframe_points
    if p.get("mode", "flat") == "linear":
        return {i: yl + (yr - yl) * ((kp[i].co.x - xl) / (xr - xl) if xr > xl else t) for i in sel}
    return {i: yl + (yr - yl) * t for i in sel}


def op_blend_neighbor(fc, sel, p):
    (xl, yl), (xr, yr) = _neighbors(fc, sel)
    f = max(-1.0, min(1.0, float(p.get("factor", 0.5))))
    target = yl if f < 0 else yr
    kp = fc.keyframe_points
    return {i: kp[i].co.y + (target - kp[i].co.y) * abs(f) for i in sel}


def op_blend_frame(fc, sel, p):
    ref = fc.evaluate(float(p["frame"]))
    f = float(p.get("factor", 1.0))
    kp = fc.keyframe_points
    return {i: kp[i].co.y + (ref - kp[i].co.y) * f for i in sel}


def op_blend_default(fc, sel, p):
    ref = _rest_value(fc)
    f = float(p.get("factor", 1.0))
    kp = fc.keyframe_points
    return {i: kp[i].co.y + (ref - kp[i].co.y) * f for i in sel}


def op_push_pull(fc, sel, p):
    (xl, yl), (xr, yr) = _neighbors(fc, sel)
    f = float(p.get("factor", 0.25))
    kp = fc.keyframe_points
    out = {}
    for i in sel:
        r = (kp[i].co.x - xl) / (xr - xl) if xr > xl else 0.0
        lin = yl + (yr - yl) * r
        out[i] = lin + (kp[i].co.y - lin) * (1.0 + f)
    return out


def op_smooth(fc, sel, p):
    kp = fc.keyframe_points
    n = len(kp)
    y = np.array([k.co.y for k in kp])
    f = float(p.get("factor", 0.5))
    cyclic = bool(p.get("cyclic", False))
    selset = set(sel)
    for _ in range(int(p.get("iterations", 1))):
        z = y.copy()
        for i in sel:
            if 0 < i < n - 1:
                avg = (y[i - 1] + y[i + 1]) / 2
            elif cyclic and n > 2:
                # first and last key are the same pose of a loop: average across the seam
                avg = (y[n - 2] + y[1]) / 2
            else:
                continue
            z[i] = y[i] + (avg - y[i]) * f
        if cyclic and n > 2 and 0 in selset and n - 1 in selset:
            z[n - 1] = z[0]
        y = z
    return {i: float(y[i]) for i in sel}


def _ease(u, shape, power):
    u = min(1.0, max(0.0, u))
    if shape == "in":
        return u ** power
    if shape == "out":
        return 1 - (1 - u) ** power
    return u ** power / (u ** power + (1 - u) ** power) if 0 < u < 1 else u


def op_ease(fc, sel, p):
    (xl, yl), (xr, yr) = _neighbors(fc, sel)
    kp = fc.keyframe_points
    shape, power = p.get("shape", "inout"), float(p.get("power", 2.0))
    return {i: yl + (yr - yl) * _ease((kp[i].co.x - xl) / (xr - xl) if xr > xl else 0, shape, power) for i in sel}


def op_scale(fc, sel, p):
    kp = fc.keyframe_points
    f = float(p.get("factor", 1.0))
    piv = p.get("pivot", "average")
    if isinstance(piv, (int, float)):
        c = float(piv)
    elif piv == "left":
        c = _neighbors(fc, sel)[0][1]
    elif piv == "right":
        c = _neighbors(fc, sel)[1][1]
    elif piv == "rest":
        c = _rest_value(fc)
    else:
        c = float(np.mean([kp[i].co.y for i in sel]))
    return {i: c + (kp[i].co.y - c) * f for i in sel}


def op_time_offset(fc, sel, p):
    src = _sampler(fc, bool(p.get("cyclic", True)))
    d = float(p.get("shift", 1.0))
    kp = fc.keyframe_points
    return {i: src(kp[i].co.x - d) for i in sel}


def _value_noise(x, seed):
    i = math.floor(x)
    rnd = lambda k: random.Random(hash((seed, k))).uniform(-1, 1)
    a, b = rnd(i), rnd(i + 1)
    t = x - i
    t = t * t * (3 - 2 * t)
    return a + (b - a) * t


def op_wave(fc, sel, p):
    kp = fc.keyframe_points
    amp, period = float(p.get("amplitude", 0.05)), max(float(p.get("period", 24.0)), 1e-3)
    phase, kind, seed = float(p.get("phase", 0.0)), p.get("kind", "sine"), int(p.get("seed", 0))
    x0 = kp[sel[0]].co.x if sel else 0.0
    seed = seed * 7919 + fc.array_index * 31 + (hash(fc.data_path) & 0xFFFF)
    out = {}
    for i in sel:
        u = (kp[i].co.x - x0) / period
        w = math.sin(2 * math.pi * u + phase) if kind == "sine" else _value_noise(u + phase, seed)
        out[i] = kp[i].co.y + amp * w
    return out


def op_resample(fc, frames, p):
    """Re-key a curve every `step` frames over its key span (or `frames`). Returns keys written."""
    co = _keys(fc)
    if len(co) < 2:
        return 0
    a, b = (frames if frames else (co[0, 0], co[-1, 0]))
    step = max(float(p.get("step", 1.0)), 0.01)
    xs = list(np.arange(a, b + step * 0.5, step))
    if abs(xs[-1] - b) > EPS:
        xs.append(b)
    vals = [fc.evaluate(float(x)) for x in xs]
    keep = [(k.co.x, k.co.y) for k in fc.keyframe_points if not (a - EPS <= k.co.x <= b + EPS)]
    fc.keyframe_points.clear()
    for x, v in sorted(keep + list(zip(xs, vals))):
        k = fc.keyframe_points.insert(float(x), float(v), options={"FAST"})
        k.interpolation = "BEZIER"
        k.handle_left_type = k.handle_right_type = "AUTO_CLAMPED"
    fc.update()
    return len(xs)


def op_clean(fc, p):
    tol = float(p.get("tolerance", 0.001))
    co = _keys(fc)
    if len(co) < 3:
        return 0
    xs = np.arange(co[0, 0], co[-1, 0] + 0.5, 1.0)
    ref = np.array([fc.evaluate(float(x)) for x in xs])
    removed = 0
    i = 1
    while i < len(fc.keyframe_points) - 1:
        k = fc.keyframe_points[i]
        x, y = k.co.x, k.co.y
        state = (k.interpolation, k.handle_left_type, k.handle_right_type,
                 tuple(k.handle_left), tuple(k.handle_right))
        lo, hi = fc.keyframe_points[i - 1].co.x, fc.keyframe_points[i + 1].co.x
        fc.keyframe_points.remove(k, fast=True)
        fc.update()
        m = (xs >= lo) & (xs <= hi)
        err = max(abs(fc.evaluate(float(xx)) - r) for xx, r in zip(xs[m], ref[m])) if m.any() else 0.0
        if err > tol:
            nk = fc.keyframe_points.insert(x, y, options={"FAST"})
            nk.interpolation, nk.handle_left_type, nk.handle_right_type = state[:3]
            if state[1] in ("FREE", "ALIGNED"):
                nk.handle_left = state[3]
            if state[2] in ("FREE", "ALIGNED"):
                nk.handle_right = state[4]
            fc.update()
            i += 1
        else:
            removed += 1
    return removed


def op_interpolation(fc, sel, p):
    kp = fc.keyframe_points
    for i in sel:
        if p.get("interpolation"):
            kp[i].interpolation = p["interpolation"]
        if p.get("easing"):
            kp[i].easing = p["easing"]
        if p.get("handle_type"):
            kp[i].handle_left_type = kp[i].handle_right_type = p["handle_type"]
    fc.update()
    return len(sel)


CURVE_OPS = {"tween": op_tween, "blend_neighbor": op_blend_neighbor, "blend_frame": op_blend_frame,
             "blend_default": op_blend_default, "push_pull": op_push_pull, "smooth": op_smooth,
             "ease": op_ease, "scale": op_scale, "time_offset": op_time_offset, "wave": op_wave}


# ---------------------------------------------------------------- action-level ops
def _weight(x, frames, blend):
    if frames is None:
        return 1.0
    f0, f1 = frames
    if f0 - EPS <= x <= f1 + EPS:
        return 1.0
    if blend <= 0:
        return 0.0
    d = (f0 - x) if x < f0 else (x - f1)
    if d >= blend:
        return 0.0
    u = 1 - d / blend
    return u * u * (3 - 2 * u)


def _current_value(obj, fc):
    try:
        return float(obj.path_resolve(fc.data_path)[fc.array_index])
    except (TypeError, IndexError):
        return float(obj.path_resolve(fc.data_path))
    except ValueError:
        return None


def op_offset(obj, act, fcs, frames, p):
    blend = float(p.get("blend", 0.0))
    explicit = p.get("delta") or {}
    ref = p.get("from_pose")
    changed, worst = 0, 0.0
    qgroups = _quat_groups(fcs)
    quat_fcs = {id(fc) for g in qgroups.values() for fc in g}
    # quaternions: one rotation multiplied in, weighted by slerp
    for bone, q in qgroups.items():
        if ref is not None:
            pb = obj.pose.bones[bone]
            qd = pb.rotation_quaternion.normalized() @ _eval_quat(q, float(ref)).inverted()
        elif bone in explicit and "rotation_quaternion" in explicit[bone]:
            qd = Quaternion(explicit[bone]["rotation_quaternion"]).normalized()
        else:
            continue
        xs = sorted(set(round(k.co.x, 4) for fc in q for k in fc.keyframe_points))
        vals = {}
        for x in xs:
            w = _weight(x, frames, blend)
            if w > 0:
                vals[x] = Quaternion().slerp(qd, w) @ _eval_quat(q, x)
        for x, qq in vals.items():
            for fc, c in zip(q, qq):
                worst = max(worst, abs(fc.evaluate(x) - c))
                fc.keyframe_points.insert(x, c, options={"FAST", "REPLACE"})
            changed += 1
        for fc in q:
            fc.update()
    for fc in fcs:
        if id(fc) in quat_fcs:
            continue
        bone, prop = _parse(fc)
        if ref is not None:
            cur = _current_value(obj, fc)
            if cur is None:
                continue
            d = cur - fc.evaluate(float(ref))
        else:
            d = ((explicit.get(bone) or explicit.get(obj.name) or {}).get(prop) or [None] * 4)
            d = d[fc.array_index] if fc.array_index < len(d) else None
            if d is None:
                continue
        if abs(d) < 1e-9:
            continue
        new = {}
        for i, k in enumerate(fc.keyframe_points):
            w = _weight(k.co.x, frames, blend)
            if w > 0:
                new[i] = k.co.y + d * w
        worst = max(worst, _apply_values(fc, new))
        changed += len(new)
    return {"keys": changed, "max_change": round(worst, 6)}


def op_overlap(obj, act, fcs_all, frames, p):
    chain = [b for b in p.get("chain", []) if b in obj.pose.bones]
    if len(chain) < 2:
        raise ValueError("overlap needs a chain of at least two existing bones")
    lag, mode = float(p.get("lag", 2.0)), p.get("mode", "follow")
    gain, fall = float(p.get("gain", 1.0)), float(p.get("falloff", 0.8))
    cyclic, step = bool(p.get("cyclic", True)), max(float(p.get("step", 1.0)), 0.1)
    a, b = frames if frames else [float(v) for v in act.frame_range]
    period = b - a
    xs = list(np.arange(a, b + step * 0.5, step))
    keys = 0
    if mode == "delay":
        for i, bone in enumerate(chain[1:], start=1):
            for fc in fcs_all:
                bn, prop = _parse(fc)
                if bn != bone or not prop.startswith("rotation_"):
                    continue
                op_resample(fc, [a, b], {"step": step})
                src = _sampler(fc, cyclic, (a, b))
                new = {j: src(k.co.x - lag * i) for j, k in enumerate(fc.keyframe_points) if a - EPS <= k.co.x <= b + EPS}
                _apply_values(fc, new)
                keys += len(new)
        return {"keys": keys, "chain": chain, "mode": mode}
    # follow: the driver's local rotation, carried into each follower's rest frame
    drv = chain[0]
    dmode = _rot_mode(obj, drv)
    R = {bn: obj.data.bones[bn].matrix_local.to_quaternion() for bn in chain}

    def wrap(x):
        return a + (x - a) % period if cyclic and period > 0 else min(max(x, a), b)

    def drive(x):
        return _local_rot(obj, fcs_all, drv, wrap(x), dmode)

    for i, bone in enumerate(chain[1:], start=1):
        mode_b = _rot_mode(obj, bone)
        g = gain * (fall ** (i - 1))
        to_f = R[bone].inverted() @ R[drv]
        own = {x: _local_rot(obj, fcs_all, bone, x, mode_b) for x in xs}
        prev = None
        for x in xs:
            qd = drive(x - lag * i)
            qd_f = to_f @ qd @ to_f.inverted()            # same rotation, expressed in the follower's frame
            q = Quaternion().slerp(qd_f, g) @ own[x]
            prev = _key_rot(obj, act, bone, x, q, mode_b, prev)
            keys += 1
        for fc in C.action_fcurves(act, _slot_for(obj, act)):
            if _parse(fc)[0] == bone:
                fc.update()
    return {"keys": keys, "chain": chain, "mode": mode, "gain_per_link": [round(gain * fall ** (i - 1), 3) for i in range(1, len(chain))]}


def op_match_cycle(obj, act, fcs, frames, p):
    mode = p.get("mode", "first")
    period = p.get("period")
    n = 0
    worst = 0.0
    qgroups = _quat_groups(fcs)
    qset = {id(fc) for g in qgroups.values() for fc in g}
    for fc in fcs:
        if id(fc) in qset or len(fc.keyframe_points) < 2:
            continue
        kp = fc.keyframe_points
        first = kp[0]
        x_end = float(period) if period is not None else kp[-1].co.x
        last = next((k for k in kp if abs(k.co.x - x_end) < EPS), None)
        if last is None:
            last = kp.insert(x_end, fc.evaluate(x_end), options={"FAST"})
        v = first.co.y if mode == "first" else (first.co.y + last.co.y) / 2
        worst = max(worst, abs(last.co.y - v), abs(first.co.y - v))
        _set_value(last, v)
        _set_value(first, v)
        fc.update()
        n += 1
    for bone, q in qgroups.items():
        x0 = min(k.co.x for k in q[0].keyframe_points)
        x_end = float(period) if period is not None else max(k.co.x for k in q[0].keyframe_points)
        q0 = _eval_quat(q, x0)
        q_before = _eval_quat(q, x_end - 1)
        if q_before.dot(q0) < 0:
            q0 = -q0
        for fc, c in zip(q, q0):
            worst = max(worst, abs(fc.evaluate(x_end) - c))
            fc.keyframe_points.insert(x_end, c, options={"FAST", "REPLACE"})
            fc.update()
        n += 4
    return {"curves": n, "max_change": round(worst, 6)}


def op_loop_window(obj, act, fcs, frames, p):
    """Crop the action to the window that loops best; writes a new action keyed every frame."""
    a, b = (int(round(v)) for v in (frames or act.frame_range))
    K, min_len = int(p.get("crossfade", 4)), int(p.get("min_len", 12))
    allf = C.action_fcurves(act, _slot_for(obj, act))
    xs = np.arange(a, b + 1)
    V = np.array([[fc.evaluate(float(x)) for fc in fcs] for x in xs])            # cost space: picked curves
    A = np.array([[fc.evaluate(float(x)) for fc in allf] for x in xs])           # everything is copied
    sd = V.std(axis=0)
    Vn = V[:, sd > 1e-6] / sd[sd > 1e-6] if (sd > 1e-6).any() else V
    steps = np.linalg.norm(np.diff(Vn, axis=0), axis=1)
    med = float(np.median(steps)) or 1e-6
    N = len(xs)
    best = None
    for i in range(K, N - min_len):
        for j in range(i + min_len, N):
            moving = steps[i:j].mean()
            if moving < 0.7 * med:
                continue
            cost = (np.linalg.norm(Vn[j] - Vn[i]) + np.linalg.norm(Vn[j - 1] - Vn[i - 1])) / moving - 0.01 * (j - i)
            if best is None or cost < best[0]:
                best = (cost, i, j)
    if best is None:
        raise ValueError("no moving stretch long enough to loop (lower min_len or check the clip)")
    _, i, j = best
    L = j - i
    W = A[i:j].copy()
    for k in range(K):                       # fade the window's end into the frames that lead into its start
        w = (k + 1) / (K + 1)
        W[L - K + k] = (1 - w) * W[L - K + k] + w * A[i - K + k]
    root = p.get("root")
    drift_removed = None
    if root and obj.type == "ARMATURE" and root in obj.pose.bones:
        loc_idx = [n for n, fc in enumerate(allf) if _parse(fc) == (root, "location")]
        if len(loc_idx) == 3:
            loc_idx.sort(key=lambda n: allf[n].array_index)
            to_w = np.array(obj.matrix_world.to_3x3() @ obj.data.bones[root].matrix_local.to_3x3())
            Lw = A[:, loc_idx] @ to_w.T
            drift = Lw[j] - Lw[i]
            drift[2] = 0.0
            Wl = W[:, loc_idx] @ to_w.T - np.outer(np.arange(L) / L, drift)
            W[:, loc_idx] = Wl @ np.linalg.inv(to_w).T
            drift_removed = [round(float(d), 5) for d in drift]
    out_name = p.get("out") or (act.name + "_loop")
    old = bpy.data.actions.get(out_name)
    if old is not None:
        bpy.data.actions.remove(old)
    new = bpy.data.actions.new(out_name)
    new.use_fake_user = True
    with assigned(obj, new):
        for n, fc in enumerate(allf):
            bone, _ = _parse(fc)
            nf = _new_fcurve(new, obj, fc.data_path, fc.array_index, bone or "Object")
            for t in range(L + 1):               # key P = key 0
                k = nf.keyframe_points.insert(float(a + t), float(W[t % L, n]), options={"FAST"})
                k.handle_left_type = k.handle_right_type = "AUTO_CLAMPED"
            nf.update()
    raw_seam = np.linalg.norm(Vn[-1] - Vn[0]) / med
    Wn = W[:, [n for n, fc in enumerate(allf) if fc in fcs]]
    Wn = Wn[:, sd > 1e-6] / sd[sd > 1e-6] if (sd > 1e-6).any() else Wn
    local = (np.linalg.norm(Wn[-1] - Wn[-2]) + np.linalg.norm(Wn[1] - Wn[0])) / 2 or 1e-6
    seam = np.linalg.norm(Wn[0] - Wn[-1]) / local
    return {"action": new.name, "source_frames": [int(xs[i]), int(xs[j])], "frames": L,
            "frame_range": [a, a + L], "seam": round(float(seam), 2), "seam_raw": round(float(raw_seam), 2),
            "root_drift_removed": drift_removed,
            "note": "assign the new action and check it in motion; seam about 1.0 is invisible"}


def op_restore(obj, act):
    bak = bpy.data.actions.get(act.name + "__bak")
    if bak is None:
        raise ValueError(f"no backup {act.name}__bak")
    name = act.name
    fresh = bak.copy()
    ad = obj.animation_data
    users_active = ad is not None and ad.action == act
    act.name = name + "__old"
    fresh.name = name
    fresh.use_fake_user = act.use_fake_user
    if users_active:
        ad.action = fresh
        if getattr(fresh, "slots", None):
            ad.action_slot = fresh.slots[0]
    bpy.data.actions.remove(act)
    return fresh


# ---------------------------------------------------------------- driver
def run(args: dict) -> dict:
    obj = bpy.data.objects.get(args.get("object", ""))
    if obj is None:
        return C.result_error("object required")
    act = _find_action(obj, args.get("action"))
    if act is None:
        return C.result_error("no action (pass action or assign one)")
    ops = args.get("ops") or ([dict(args)] if args.get("op") else [])
    if not ops:
        return C.result_error("op or ops required")
    if args.get("backup", True) and not any(o.get("op") == "restore" for o in ops):
        if bpy.data.actions.get(act.name + "__bak") is None:
            bak = act.copy()
            bak.name = act.name + "__bak"
            bak.use_fake_user = True
    report = []
    act_name = act.name
    with assigned(obj, act):
        err = _run_ops(obj, act, ops, args, report)
    if err:
        return C.result_error(err, done=report)
    bpy.context.view_layer.update()
    return C.result_ok(object=obj.name, action=report[-1].get("restored", act_name) if report else act_name, ops=report)


def _run_ops(obj, act, ops, args, report):
    for o in ops:
        p = {**args, **o}
        name = p["op"]
        frames = p.get("frames")
        frames = [float(frames[0]), float(frames[1])] if frames else None
        fcs = select_fcurves(obj, act, p)
        entry = {"op": name, "curves": len(fcs)}
        if name in CURVE_OPS:
            keys, worst = 0, 0.0
            for fc in fcs:
                sel = _selected(fc, frames)
                if not sel:
                    continue
                worst = max(worst, _apply_values(fc, CURVE_OPS[name](fc, sel, p)))
                keys += len(sel)
            entry.update(keys=keys, max_change=round(worst, 6))
        elif name == "resample":
            entry["keys"] = sum(op_resample(fc, frames, p) for fc in fcs)
        elif name == "clean":
            entry["keys_removed"] = sum(op_clean(fc, p) for fc in fcs)
        elif name == "interpolation":
            entry["keys"] = sum(op_interpolation(fc, _selected(fc, frames), p) for fc in fcs)
        elif name == "offset":
            entry.update(op_offset(obj, act, fcs, frames, p))
        elif name == "overlap":
            entry.update(op_overlap(obj, act, C.action_fcurves(act, _slot_for(obj, act)), frames, p))
            fcs = select_fcurves(obj, act, {**p, "bones": p.get("chain")})
        elif name == "match_cycle":
            entry.update(op_match_cycle(obj, act, fcs, frames, p))
        elif name == "loop_window":
            entry.update(op_loop_window(obj, act, fcs, frames, p))
        elif name == "restore":
            act = op_restore(obj, act)
            entry["restored"] = act.name
        else:
            return f"unknown op {name}"
        if name not in ("loop_window", "restore", "interpolation"):
            entry["quats_normalized"] = _normalize_quats(fcs)
        report.append(entry)
    return None
