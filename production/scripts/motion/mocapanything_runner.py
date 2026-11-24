"""Run one MoCapAnything V2 capture outside Blender, in MoCapAnything's own Python environment.

Called by production/scripts/blender/mocap_capture.py; it can also be run by hand:

    <home>/.venv/bin/python mocapanything_runner.py job.json

MoCapAnything V2 (https://github.com/kehong-gong/MoCapAnything, MIT) is installed by the user.
This file imports it from `home`; nothing of it is copied here. Upstream inference is written for
CUDA, so this runner:
  - picks the device itself (cuda, else Apple mps, else cpu — mps matched cpu to 1e-5 on the demo clip),
  - redirects the hard-coded `.cuda()` calls in its preprocessing to that device,
  - runs DINOv2 in float32 off CUDA (float16 matmuls are slow or missing on CPU),
  - processes exactly one clip (trimmed, resampled and downscaled with ffmpeg first),
  - skips the matplotlib comparison videos unless `preview` is set,
  - writes the BVH with the clip's real frame rate (upstream writes 30 fps regardless).

job.json:
    home          MoCapAnything checkout
    video         input clip
    rig           reference skeleton: a character folder in data_dir (wild mode uses its skeleton)
    data_dir      processed data root (bvh_pose/, species_info_dict.npy, cache/, characters_*)
    config        base YAML (default: <home>/demo/configs/demo_wild.yaml)
    checkpoint    .pt file (default: first *.pt in <home>/checkpoints)
    out_dir       where results are written
    device        auto (cuda > mps > cpu) | cpu | cuda | mps
    fps           resample the clip (default 15, the model's training rate)
    start, duration   trim in seconds (optional)
    max_side      downscale so the longer side is at most this many pixels (default 720)
    preview       also write the skeleton comparison video (slow on CPU)
    export_glb    also write the rig's skinned mesh + skeleton as GLB

Prints `PROGRESS <stage>` lines, then `RESULT <json>` on success; exits 1 with `ERROR <text>` otherwise.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback


def emit(tag, payload=""):
    print(f"{tag} {payload}".rstrip(), flush=True)


def fail(msg):
    emit("ERROR", msg)
    sys.exit(1)


def pick_device(torch, wanted):
    wanted = (wanted or "auto").lower()
    mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    if wanted == "auto":
        return "cuda" if torch.cuda.is_available() else ("mps" if mps else "cpu")
    if wanted == "cuda" and not torch.cuda.is_available():
        fail("device 'cuda' requested but torch.cuda.is_available() is False")
    if wanted == "mps" and not mps:
        fail("device 'mps' requested but MPS is not available")
    return wanted


def frames_from_video(ffmpeg, video, out_dir, fps, start, duration, max_side):
    os.makedirs(out_dir, exist_ok=True)
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", video]
    if duration:
        cmd += ["-t", str(duration)]
    filters = []
    if fps:
        filters.append(f"fps={fps}")
    if max_side:
        m = int(max_side)
        filters.append(f"scale='if(gt(iw,ih),min({m},iw),-2)':'if(gt(iw,ih),-2,min({m},ih))'")
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-start_number", "0", os.path.join(out_dir, "%05d.png")]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        fail(f"ffmpeg could not read {video}: {r.stderr.strip()[-400:]}")
    return len(glob.glob(os.path.join(out_dir, "*.png")))


def set_bvh_frame_time(path, fps):
    with open(path, "r") as f:
        text = f.read()
    text = re.sub(r"Frame Time:\s*[0-9.eE+-]+", f"Frame Time: {1.0 / fps:.6f}", text, count=1)
    with open(path, "w") as f:
        f.write(text)


def main():
    if len(sys.argv) != 2:
        fail("usage: mocapanything_runner.py job.json")
    with open(sys.argv[1]) as f:
        job = json.load(f)

    home = os.path.abspath(os.path.expanduser(job["home"]))
    video = os.path.abspath(os.path.expanduser(job["video"]))
    out_dir = os.path.abspath(os.path.expanduser(job["out_dir"]))
    data_dir = os.path.abspath(os.path.expanduser(job.get("data_dir") or os.path.join(home, "demo/data/zoo1030")))
    rig = job["rig"]
    fps = float(job.get("fps") or 15)
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isfile(video):
        fail(f"video not found: {video}")

    os.chdir(home)
    sys.path.insert(0, home)
    t0 = time.time()
    emit("PROGRESS", "import")
    # ops MPS lacks fall back to the CPU instead of failing (read when torch is imported)
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    import numpy as np
    import torch
    import yaml

    device = pick_device(torch, job.get("device"))
    dtype = torch.float16 if device == "cuda" else torch.float32

    if device != "cuda":
        # Upstream preprocessing calls .cuda() directly; send those tensors to the chosen device.
        torch.Tensor.cuda = lambda self, *a, **k: self.to(device)
    import utils.common as uc
    import inference.video2pose2rot as vp
    import imageio_ffmpeg

    uc.extract_and_compare_image_features_with_rmbg.__defaults__ = (device, str(dtype).split(".")[-1], None)
    vp.DinoPipe.__init__.__defaults__ = (dtype, "facebook/dinov2-large")
    if device == "mps":
        # Upstream picks `cfg device if torch.cuda.is_available() else "cpu"`; make that check pass inside its
        # inference module only (it calls no other CUDA API during inference).
        class _CudaShim:
            def __getattr__(self, name):
                return getattr(torch.cuda, name)

            @staticmethod
            def is_available():
                return True

        class _TorchShim:
            cuda = _CudaShim()

            def __getattr__(self, name):
                return getattr(torch, name)

        vp.torch = _TorchShim()
    if not job.get("preview"):
        vp.plot_pose_compare_from_npy = lambda *a, **k: None

    cfg_path = job.get("config") or os.path.join(home, "demo/configs/demo_wild.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    ckpt = job.get("checkpoint")
    if not ckpt:
        found = sorted(glob.glob(os.path.join(home, "checkpoints", "*.pt")))
        if not found:
            fail(f"no checkpoint (*.pt) in {os.path.join(home, 'checkpoints')}")
        ckpt = found[0]
    ckpt = os.path.abspath(os.path.expanduser(ckpt))
    if not os.path.isfile(ckpt):
        fail(f"checkpoint not found: {ckpt}")

    work = os.path.join(out_dir, "_work")
    shutil.rmtree(work, ignore_errors=True)
    split = "clip"
    clip = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(os.path.basename(video))[0]) or "clip"
    seq_name = f"{rig}#{clip}"
    frames_root = os.path.join(work, "frames")
    frames_dir = os.path.join(frames_root, split, seq_name)

    char_dir = cfg["data"].get("character_dir") or ""
    char_dir = os.path.join(data_dir, os.path.basename(os.path.normpath(char_dir))) if char_dir else ""
    if not os.path.isdir(char_dir):
        cands = [d for d in glob.glob(os.path.join(data_dir, "characters*")) if os.path.isdir(d)]
        char_dir = cands[0] if cands else char_dir

    cfg["runtime"]["device"] = device
    cfg["weights"]["video2pose_ckpt_root"] = os.path.dirname(ckpt)
    cfg["weights"]["ckpt_name"] = os.path.basename(ckpt)
    cfg["experiment"]["exp"] = ""
    cfg["data"].update({
        "base_dir": data_dir,
        "scale_dict_path": os.path.join(data_dir, "cache", "__mesh2pose1002_species_scale_cache.pkl"),
        "character_dir": char_dir,
        "bvh_roots": [os.path.join(data_dir, "bvh")],
        "image_roots": [os.path.join(frames_root, split)],
        "wild_flag": True,
        "wild_mode": True,
    })
    cfg["output"].update({
        "blender_path": None,
        "save_dir": os.path.join(work, "out"),
        "output_tag": "mocap",
        "fps": fps,
    })
    cfg["export_glb"] = bool(job.get("export_glb"))

    ref = vp.derive_wild_ref(seq_name, data_dir)
    if ref is None:
        pose_root = os.path.join(data_dir, "bvh_pose")
        have = sorted({d.split("#")[0] for d in os.listdir(pose_root)}) if os.path.isdir(pose_root) else []
        fail(f"rig '{rig}' has no reference pose in {pose_root}; available: {', '.join(have)}")
    cfg["data"]["retarget"]["ref_seq"] = ref

    emit("PROGRESS", "frames")
    n = frames_from_video(imageio_ffmpeg.get_ffmpeg_exe(), video, frames_dir, fps,
                          job.get("start"), job.get("duration"), job.get("max_side", 720))
    if n < 2:
        fail(f"only {n} frame(s) extracted from {video}")
    if n > 301:
        emit("PROGRESS", f"warning: {n} frames; MoCapAnything keeps the first 301")

    emit("PROGRESS", "load_models")
    vp.set_seed(cfg["runtime"]["seed"])
    rmbg = vp.BriaRMBG.from_pretrained(cfg["weights"]["rmbg_weights_dir"]).to(device).eval()
    pipe = vp.DinoPipe(device)
    model = vp.instantiate_from_config(cfg["model"]).float().to(device).eval()
    state = torch.load(ckpt, map_location=device)
    sd = None
    for k in ("model_state", "model", "model_state_dict", "state_dict"):
        if isinstance(state, dict) and k in state:
            sd = state[k]
            break
    sd = state if sd is None else sd
    model.load_state_dict({(k[7:] if k.startswith("module.") else k): v for k, v in sd.items()})

    emit("PROGRESS", f"inference frames={n} device={device}")
    try:
        vp.inference(cfg=cfg, device=torch.device(device), attention_design=cfg["model"]["attention_kwargs"],
                     model=model, pipe=pipe, rmbg_net=rmbg, seq_name=seq_name, image_folder=frames_dir,
                     stage_cb=lambda s: emit("PROGRESS", s))
    except Exception as e:
        fail(f"inference failed: {e}\n{traceback.format_exc()[-1500:]}")

    found = glob.glob(os.path.join(work, "out", "**", "*_rot6d_pred.npy"), recursive=True)
    if not found:
        fail("inference finished without *_rot6d_pred.npy")
    save_dir = os.path.dirname(found[0])
    result = {"rig": rig, "ref_seq": ref, "frames": n, "fps": fps, "device": device,
              "seconds": round(time.time() - t0, 1), "files": {}}
    for kind, pat in (("bvh", "*_rot6d_pred.bvh"), ("rot6d", "*_rot6d_pred.npy"),
                      ("positions", "*_pose_pred.npy"), ("mesh_glb", "*_mesh.glb"),
                      ("skeleton_glb", "*_skeleton.glb"), ("preview", "*_pose_compare*.mp4")):
        hits = sorted(glob.glob(os.path.join(save_dir, pat)) + glob.glob(os.path.join(os.path.dirname(save_dir), pat)))
        if not hits:
            continue
        ext = os.path.splitext(hits[0])[1]
        dst = os.path.join(out_dir, f"{clip}_{kind}{ext}")
        shutil.copyfile(hits[0], dst)
        if kind == "bvh":
            set_bvh_frame_time(dst, fps)
        result["files"][kind] = dst
    if "bvh" not in result["files"]:
        fail(f"no BVH written for rig '{rig}' (needs a *_ffs.bvh template in {os.path.join(char_dir, rig)})")
    pos = np.load(result["files"]["positions"]) if "positions" in result["files"] else None
    if pos is not None:
        result["joints"] = int(pos.shape[1])
    if not job.get("keep_work"):
        shutil.rmtree(work, ignore_errors=True)
    emit("RESULT", json.dumps(result))


if __name__ == "__main__":
    main()
