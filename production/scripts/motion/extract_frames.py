#!/usr/bin/env python3
"""Turn a motion source (video / GIF / image folder) into frames + a contact sheet for the motion brief.

Runs with plain Python 3.9+ and ffmpeg/ffprobe on PATH (outside Blender).

    python3 production/scripts/motion/extract_frames.py --source input/motion/walk.mp4 \
        --out reports/motion/walk [--trim 1.2 3.4] [--max-fps 12] [--cols 6] [--width 320]

Writes:
  <out>/frames/f_0001.png ...     sampled frames
  <out>/frames.json               {"source_fps", "sample_fps", "duration_s", "frames": [{"file", "t"}]}
  <out>/sheet.png                 grid of the sampled frames in time order (left→right, top→bottom)
Only reads the source; never modifies it.
"""
import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=r_frame_rate,avg_frame_rate,nb_read_packets:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    st = info["streams"][0]

    def rate(s):
        n, d = (s or "0/1").split("/")
        return float(n) / float(d) if float(d) else 0.0

    fps = rate(st.get("avg_frame_rate")) or rate(st.get("r_frame_rate"))
    dur = float(info.get("format", {}).get("duration") or 0) or (int(st.get("nb_read_packets", 0)) / fps if fps else 0)
    return fps, dur


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trim", nargs=2, type=float)
    ap.add_argument("--max-fps", type=float, default=12.0)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--width", type=int, default=320)
    a = ap.parse_args(argv)
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"{tool} not found on PATH")

    frames_dir = os.path.join(a.out, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for f in glob.glob(os.path.join(frames_dir, "f_*.png")):
        os.remove(f)

    if os.path.isdir(a.source):  # image sequence
        files = sorted(glob.glob(os.path.join(a.source, "*.png")) + glob.glob(os.path.join(a.source, "*.jpg")))
        src_fps, duration = a.max_fps, len(files) / a.max_fps
        for i, f in enumerate(files, 1):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vf", f"scale={a.width}:-2",
                            os.path.join(frames_dir, f"f_{i:04d}.png")], check=True)
        sample_fps, start = src_fps, 0.0
    else:
        src_fps, duration = probe(a.source)
        start = a.trim[0] if a.trim else 0.0
        end = a.trim[1] if a.trim else duration
        sample_fps = min(src_fps or a.max_fps, a.max_fps)
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start}", "-to", f"{end}", "-i", a.source,
               "-vf", f"fps={sample_fps},scale={a.width}:-2", os.path.join(frames_dir, "f_%04d.png")]
        subprocess.run(cmd, check=True)
        duration = end - start

    files = sorted(glob.glob(os.path.join(frames_dir, "f_*")))
    meta = {"source": a.source, "source_fps": src_fps, "sample_fps": sample_fps, "trim_start_s": start,
            "duration_s": round(duration, 4),
            "frames": [{"file": os.path.relpath(f, a.out), "t": round(i / sample_fps, 4)} for i, f in enumerate(files)]}
    with open(os.path.join(a.out, "frames.json"), "w") as fh:
        json.dump(meta, fh, indent=2)

    if files:
        rows = math.ceil(len(files) / a.cols)
        pattern = os.path.join(frames_dir, "f_%04d.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-start_number", "1", "-i", pattern,
                        "-vf", f"tile={a.cols}x{rows}:padding=4:margin=4", "-frames:v", "1",
                        os.path.join(a.out, "sheet.png")], check=True)
    print(json.dumps({"ok": True, "frames": len(files), "sheet": os.path.join(a.out, "sheet.png"),
                      "meta": os.path.join(a.out, "frames.json")}))


if __name__ == "__main__":
    main()
