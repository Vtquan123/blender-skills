#!/usr/bin/env node
// Optimise a master GLB for the web with glTF-Transform, driven by output-spec.yaml (web-export step 3).
//
//   node production/scripts/node/optimize.mjs --in <master.glb> --out <web.glb> --spec <output-spec.yaml> \
//        [--report <reports/optimize.json>] [--dry-run]
//
// Order: dedup → prune → weld → resample → (simplify only if allowed) → texture resize/compress → meshopt|draco.
// Every value comes from the spec; nothing is hardcoded except safe structural flags (no join/flatten/palette,
// which could merge rigid parts or alter materials of animated assets).
import { execFileSync } from 'node:child_process';
import { readFileSync, statSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptDecoder, MeshoptEncoder } from 'meshoptimizer';

const here = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
for (const k of ['in', 'out', 'spec']) if (!args[k]) { console.error(`missing --${k}`); process.exit(2); }

const spec = parse(readFileSync(args.spec, 'utf8')) ?? {};
const comp = spec.compression ?? {};
const budgets = spec.budgets ?? {};
const geomStrategy = spec.geometry?.strategy ?? 'auto';
const animated = (spec.animation?.clips ?? []).length > 0 || spec.rig?.required === true;

const geometry = comp.geometry ?? 'meshopt';            // meshopt | draco | none
const textures = comp.textures ?? budgets.textures?.format ?? 'ktx2';   // ktx2 | webp | none
const maxSize = budgets.textures?.max_size ?? null;

if (textures === 'ktx2' && !args['dry-run']) {
  try { execFileSync('ktx', ['--version'], { stdio: 'ignore' }); }
  catch { console.error('KTX2 requested but KTX-Software `ktx` CLI is not on PATH. Install it or set compression.textures: webp in the spec.'); process.exit(3); }
}

const cli = resolve(here, '..', '..', 'node_modules', '.bin', 'gltf-transform');
const bin = existsSync(cli) ? cli : 'gltf-transform';
const flags = [
  'optimize', args.in, args.out,
  '--compress', geometry === 'none' ? 'false' : geometry,
  '--texture-compress', textures === 'none' ? 'false' : textures,
  '--simplify', (geomStrategy === 'decimate' && spec.geometry?.allow_post_export_simplify && !animated) ? 'true' : 'false',
  '--resample', 'true',
  '--prune', 'true',
  '--weld', 'true',
  '--join', 'false',
  '--flatten', 'false',
  '--palette', 'false',
  '--instance', 'false',
];
if (maxSize) flags.push('--texture-size', String(maxSize));

async function stats(path) {
  await MeshoptDecoder.ready;
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    'meshopt.decoder': MeshoptDecoder, 'meshopt.encoder': MeshoptEncoder });
  const doc = await io.read(path);
  const root = doc.getRoot();
  let tris = 0, verts = 0, prims = 0;
  for (const mesh of root.listMeshes()) for (const p of mesh.listPrimitives()) {
    prims++;
    const pos = p.getAttribute('POSITION'); if (pos) verts += pos.getCount();
    const idx = p.getIndices(); tris += Math.floor((idx ? idx.getCount() : (pos?.getCount() ?? 0)) / 3);
  }
  const tex = root.listTextures().map(t => ({ name: t.getName(), mime: t.getMimeType(), size: t.getSize(), bytes: t.getImage()?.byteLength ?? 0 }));
  const anims = root.listAnimations().map(a => ({ name: a.getName(), channels: a.listChannels().length,
    keyframes: a.listSamplers().reduce((s, x) => s + (x.getInput()?.getCount() ?? 0), 0) }));
  return { bytes: statSync(path).size, triangles: tris, vertices: verts, primitives: prims,
    materials: root.listMaterials().length, skins: root.listSkins().length,
    extensionsUsed: root.listExtensionsUsed().map(e => e.extensionName), textures: tex, animations: anims };
}

const before = await stats(args.in);
if (args['dry-run']) { console.log(JSON.stringify({ command: [bin, ...flags].join(' '), before }, null, 2)); process.exit(0); }
mkdirSync(dirname(resolve(args.out)), { recursive: true });
execFileSync(bin, flags, { stdio: 'inherit' });
const after = await stats(args.out);
const version = JSON.parse(readFileSync(resolve(here, '..', '..', 'node_modules', '@gltf-transform', 'core', 'package.json'), 'utf8')).version;
const report = { ok: true, command: [bin, ...flags].join(' '), gltf_transform: version, before, after,
  ratio: +(after.bytes / before.bytes).toFixed(4) };
if (args.report) { mkdirSync(dirname(resolve(args.report)), { recursive: true }); writeFileSync(args.report, JSON.stringify(report, null, 2)); }
console.log(JSON.stringify(report, null, 2));
