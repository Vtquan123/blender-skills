"""Local review server for production/review/viewer.html — pin notes on a model, read them back exactly.

Standard library only. Binds 127.0.0.1 (never the network). Serves:
    /                       the viewer (three.js from production/node_modules when installed, else the CDN)
    /project/<path>         read-only files of the project folder (GLBs, reports)
    /nm/<path>              production/node_modules (three.js), when present
    GET  /api/state         models, manifest, notes, motion_qa frames to mark
    GET  /api/notes         notes
    POST /api/note          upsert one note (by id) into <project>/review/notes.json

Run it from a terminal:
    python3 production/scripts/review/serve.py --project projects/<name> [--port 8765]
or from Blender through the MCP (review_notes.py mode=serve), which starts it in a background thread.
No phone sharing, no remote access, no agent launched from the page: Claude reads notes.json.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCTION = os.path.dirname(os.path.dirname(HERE))
VIEWER = os.path.join(PRODUCTION, "review", "viewer.html")
NODE_MODULES = os.path.join(PRODUCTION, "node_modules")
THREE_VERSION = "0.187.0"
MAX_BODY = 2 * 1024 * 1024
_LOCK = threading.Lock()
_SERVERS = {}

mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


# ---------------------------------------------------------------- notes file (shared with review_notes.py)
def notes_path(project):
    return os.path.join(project, "review", "notes.json")


def read_notes(project):
    p = notes_path(project)
    if not os.path.exists(p):
        return {"version": 1, "notes": []}
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {"version": 1, "notes": data}
    return data


def write_notes(project, data):
    p = notes_path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def upsert_note(project, note):
    """Insert or update one note by id; returns the stored note. Thread-safe within this process."""
    if not isinstance(note, dict):
        raise ValueError("note must be an object")
    with _LOCK:
        data = read_notes(project)
        notes = data.setdefault("notes", [])
        note = dict(note)
        note.setdefault("id", "n" + uuid.uuid4().hex[:8])
        note.setdefault("created", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        note["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for i, n in enumerate(notes):
            if n.get("id") == note["id"]:
                merged = {**n, **note}
                if "replies" in n and "replies" not in note:
                    merged["replies"] = n["replies"]
                notes[i] = merged
                note = merged
                break
        else:
            notes.append(note)
        write_notes(project, data)
    return note


# ---------------------------------------------------------------- state for the viewer
def _rel(project, path):
    return os.path.relpath(path, project).replace(os.sep, "/")


def state(project):
    models = []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("checkpoints", "node_modules")]
        for f in files:
            if f.lower().endswith((".glb", ".gltf")):
                p = os.path.join(root, f)
                models.append({"path": _rel(project, p), "bytes": os.path.getsize(p), "mtime": os.path.getmtime(p)})
    models.sort(key=lambda m: (not m["path"].startswith("review/current"), m["path"]))
    manifest = {}
    mp = os.path.join(project, "review", "manifest.json")
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as fh:
            manifest = json.load(fh)
    marks = {}
    qa = os.path.join(project, "reports", "motion-qa.json")
    if os.path.exists(qa):
        try:
            with open(qa, encoding="utf-8") as fh:
                rep = json.load(fh)
            rep = rep.get("report", rep)
            for clip, m in (rep.get("clips") or {}).items():
                frames = set()
                for li in (m.get("limbs") or {}).values():
                    frames.update(li.get("pop_frames") or [])
                if m.get("jitter_at"):
                    frames.add(m["jitter_at"][0])
                marks[clip] = {"frames": sorted(frames), "action": m.get("action", clip)}
        except (ValueError, OSError):
            pass
    return {"project": os.path.basename(os.path.abspath(project)), "models": models, "manifest": manifest,
            "notes": read_notes(project).get("notes", []), "motion_qa_marks": marks}


# ---------------------------------------------------------------- HTTP
def _inside(base, path):
    base = os.path.realpath(base)
    path = os.path.realpath(path)
    return path == base or path.startswith(base + os.sep)


class Handler(BaseHTTPRequestHandler):
    project = "."
    server_version = "u3d-review/1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _local_host(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, base, rel):
        path = os.path.join(base, *[p for p in rel.split("/") if p not in ("", ".", "..")])
        if not _inside(base, path) or not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def do_GET(self):
        if not self._local_host():
            return self._send(403, {"error": "local only"})
        url = urlparse(self.path)
        p = unquote(url.path)
        if p in ("/", "/index.html"):
            with open(VIEWER, encoding="utf-8") as fh:
                html = fh.read()
            base = "/nm/three" if os.path.exists(os.path.join(NODE_MODULES, "three", "build", "three.module.js")) \
                else f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}"
            return self._send(200, html.replace("__THREE_BASE__", base), "text/html; charset=utf-8")
        if p == "/api/state":
            return self._send(200, state(self.project))
        if p == "/api/notes":
            return self._send(200, read_notes(self.project))
        if p.startswith("/project/"):
            return self._file(self.project, p[len("/project/"):])
        if p.startswith("/nm/") and os.path.isdir(NODE_MODULES):
            return self._file(NODE_MODULES, p[len("/nm/"):])
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._local_host():
            return self._send(403, {"error": "local only"})
        if urlparse(self.path).path != "/api/note":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413, {"error": "body size"})
        try:
            note = json.loads(self.rfile.read(n).decode("utf-8"))
            return self._send(200, upsert_note(self.project, note))
        except (ValueError, TypeError) as e:
            return self._send(400, {"error": str(e)})


def start(project, port=8765):
    """Start (or reuse) a server for this project in a daemon thread. Returns the URL."""
    project = os.path.abspath(project)
    os.makedirs(os.path.join(project, "review"), exist_ok=True)
    old = _SERVERS.get(port)
    if old is not None:
        if old[1] == project:
            return f"http://127.0.0.1:{port}/"
        stop(port)
    handler = type("ProjectHandler", (Handler,), {"project": project})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, name=f"u3d-review-{port}", daemon=True)
    t.start()
    _SERVERS[port] = (httpd, project)
    return f"http://127.0.0.1:{port}/"


def stop(port=8765):
    old = _SERVERS.pop(port, None)
    if old is not None:
        old[0].shutdown()
        old[0].server_close()
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, help="project folder (projects/<name>)")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    url = start(a.project, a.port)
    print(f"review: {url}  (project {os.path.abspath(a.project)}) — Ctrl+C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop(a.port)


if __name__ == "__main__":
    main()
