#!/usr/bin/env node
// Gate G7: load the web GLB in headless Chromium with three.js, play every clip, measure, and compare
// sampled vertex positions with Blender (production/scripts/blender/sample_vertices.py).
//
//   node production/scripts/validation/runtime_check.mjs --glb <web.glb> [--samples <blender-samples.json>]
//        [--spec <output-spec.yaml>] [--gate <reports/gate-G7.json>] [--shots <reports/runtime>]
//        [--chrome [<path to chrome>]]   use installed Google Chrome (bare flag) or a given executable
//
// Requires: npm install (in production/) and `npx playwright install chromium` once.
import http from 'node:http';
import { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from 'node:fs';
import { dirname, resolve, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..', '..');                 // production/
const nm = join(root, 'node_modules');
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
if (!args.glb) { console.error('missing --glb'); process.exit(2); }
const glbPath = resolve(args.glb);
const samples = args.samples && existsSync(args.samples) ? JSON.parse(readFileSync(args.samples, 'utf8')) : null;
const spec = args.spec ? parse(readFileSync(args.spec, 'utf8')) : {};
const th = spec?.acceptance?.G7 ?? {};

const PAGE = `<!doctype html><html><body style="margin:0"><canvas id="c" width="640" height="640"></canvas>
<script type="importmap">{"imports":{"three":"/nm/three/build/three.module.js","three/addons/":"/nm/three/examples/jsm/"}}</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
window.run = async (samples) => {
  const t0 = performance.now();
  const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('c'), antialias: true, preserveDrawingBuffer: true });
  const ktx2 = new KTX2Loader().setTranscoderPath('/nm/three/examples/jsm/libs/basis/').detectSupport(renderer);
  const draco = new DRACOLoader().setDecoderPath('/nm/three/examples/jsm/libs/draco/');
  const loader = new GLTFLoader().setKTX2Loader(ktx2).setDRACOLoader(draco).setMeshoptDecoder(MeshoptDecoder);
  const gltf = await loader.loadAsync('/asset.glb');
  const loadMs = performance.now() - t0;
  const scene = new THREE.Scene(); scene.add(gltf.scene);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2));
  const box = new THREE.Box3().setFromObject(gltf.scene); const size = box.getSize(new THREE.Vector3()).length();
  const center = box.getCenter(new THREE.Vector3());
  const cam = new THREE.PerspectiveCamera(35, 1, size / 100, size * 10);
  cam.position.copy(center).add(new THREE.Vector3(size * 1.3, size * 0.6, size * 1.3)); cam.lookAt(center);
  const skinned = []; gltf.scene.traverse(o => { if (o.isSkinnedMesh) skinned.push(o); });
  const v = new THREE.Vector3();
  const positions = () => skinned.map(m => { const n = m.geometry.attributes.position.count; const a = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { m.getVertexPosition(i, v); m.localToWorld(v); a[i*3]=v.x; a[i*3+1]=v.y; a[i*3+2]=v.z; } return a; });
  gltf.scene.updateMatrixWorld(true);
  renderer.render(scene, cam);
  const info = { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles,
    textures: renderer.info.memory.textures, geometries: renderer.info.memory.geometries };
  const mixer = new THREE.AnimationMixer(gltf.scene);
  const rest = positions();
  // match Blender samples by rest position (nearest neighbour over all skinned meshes)
  let match = null;
  if (samples) {
    match = {};
    for (const [mesh, pts] of Object.entries(samples.rest)) match[mesh] = pts.map(p => {
      let best = [Infinity, -1, -1];
      rest.forEach((arr, mi) => { for (let i = 0; i < arr.length; i += 3) {
        const d = (arr[i]-p[0])**2 + (arr[i+1]-p[1])**2 + (arr[i+2]-p[2])**2; if (d < best[0]) best = [d, mi, i / 3]; } });
      return { mi: best[1], vi: best[2], restDist: Math.sqrt(best[0]) };
    });
  }
  const clips = {}; const shots = {};
  for (const clip of gltf.animations) {
    const action = mixer.clipAction(clip); action.setLoop(THREE.LoopOnce, 1); action.clampWhenFinished = true; action.reset().play();
    const res = { duration_s: clip.duration, tracks: clip.tracks.length, max_vertex_dev_m: null };
    const key = clip.name; const bkey = samples && (samples.clips[key] ? key : samples.clips['AN_' + key] ? 'AN_' + key : null);
    if (bkey) {
      let worst = 0; res.per_fraction = {};
      for (const [frac, perMesh] of Object.entries(samples.clips[bkey].samples)) {
        const tt = samples.clips[bkey].times_s?.[frac] ?? clip.duration * Number(frac);
        mixer.setTime(tt); gltf.scene.updateMatrixWorld(true);
        const cur = positions(); let w = 0;
        for (const [mesh, pts] of Object.entries(perMesh)) pts.forEach((p, k) => {
          const m = match[mesh][k]; const a = cur[m.mi]; const i = m.vi * 3;
          w = Math.max(w, Math.hypot(a[i]-p[0], a[i+1]-p[1], a[i+2]-p[2]));
        });
        res.per_fraction[frac] = w; worst = Math.max(worst, w);
      }
      res.max_vertex_dev_m = worst;
    }
    mixer.setTime(clip.duration * 0.5); gltf.scene.updateMatrixWorld(true); renderer.render(scene, cam);
    shots[clip.name] = renderer.domElement.toDataURL('image/png');
    action.stop(); clips[clip.name] = res;
  }
  if (!gltf.animations.length) { renderer.render(scene, cam); shots['static'] = renderer.domElement.toDataURL('image/png'); }
  const restMatch = match ? Math.max(...Object.values(match).flat().map(m => m.restDist)) : null;
  return { loadMs, info, skinnedMeshes: skinned.length, clips, restMatchMax_m: restMatch, shots };
};
window.ready = true;
</script></body></html>`;

const types = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.wasm': 'application/wasm', '.glb': 'model/gltf-binary', '.html': 'text/html' };
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  let file = null;
  if (url === '/favicon.ico') { res.writeHead(204); return res.end(); }
  if (url === '/' || url === '/index.html') { res.writeHead(200, { 'content-type': 'text/html' }); return res.end(PAGE); }
  if (url === '/asset.glb') file = glbPath;
  else if (url.startsWith('/nm/')) file = join(nm, url.slice(4));
  if (!file || !existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const launchArgs = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
let browser;
if (typeof args.chrome === 'string') browser = await chromium.launch({ executablePath: args.chrome, args: launchArgs });
else if (args.chrome) browser = await chromium.launch({ channel: 'chrome', args: launchArgs });   // bare --chrome
else {
  try { browser = await chromium.launch({ args: launchArgs }); }                 // playwright's own Chromium
  catch { browser = await chromium.launch({ channel: 'chrome', args: launchArgs }); } // installed Google Chrome
}
let out;
try {
  const page = await browser.newPage();
  const logs = []; page.on('console', m => logs.push(`${m.type()}: ${m.text()}`)); page.on('pageerror', e => logs.push(`pageerror: ${e.message}`));
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.waitForFunction(() => window.ready === true, null, { timeout: 30000 });
  out = await page.evaluate(s => window.run(s), samples);
  out.console = logs.slice(0, 50);
} finally { await browser.close(); server.close(); }

if (args.shots) {
  mkdirSync(args.shots, { recursive: true });
  for (const [name, data] of Object.entries(out.shots)) writeFileSync(join(args.shots, `${name}.png`), Buffer.from(data.split(',')[1], 'base64'));
}
delete out.shots;
const bytes = statSync(glbPath).size;
const devs = Object.values(out.clips).map(c => c.max_vertex_dev_m).filter(x => x != null);
const metrics = { bytes, file_size_mb: +(bytes / 1e6).toFixed(3), draw_calls: out.info.calls, triangles: out.info.triangles,
  textures: out.info.textures, load_ms: Math.round(out.loadMs), clips: Object.keys(out.clips), clips_detail: out.clips,
  max_vertex_dev_m: devs.length ? Math.max(...devs) : null, rest_match_max_m: out.restMatchMax_m,
  page_errors: out.console.filter(l => l.startsWith('pageerror') || l.startsWith('error')) };
const fails = [];
if (th.file_size_mb_max != null && metrics.file_size_mb > th.file_size_mb_max) fails.push('file_size');
if (th.draw_calls_max != null && metrics.draw_calls > th.draw_calls_max) fails.push('draw_calls');
if (th.max_vertex_dev_m != null && metrics.max_vertex_dev_m != null && metrics.max_vertex_dev_m > th.max_vertex_dev_m) fails.push('vertex_dev');
if (metrics.page_errors.length) fails.push('page_errors');
const gate = { gate: 'G7', status: fails.length ? 'fail' : 'pass', metrics, thresholds: th, failing: fails, at: new Date().toISOString() };
if (args.gate) { mkdirSync(dirname(resolve(args.gate)), { recursive: true }); writeFileSync(args.gate, JSON.stringify(gate, null, 2)); }
console.log(JSON.stringify(gate, null, 2));
process.exit(fails.length ? 1 : 0);
