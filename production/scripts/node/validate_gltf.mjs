#!/usr/bin/env node
// Gate G6: validate a GLB/glTF with the Khronos glTF-Validator.
//
//   node production/scripts/node/validate_gltf.mjs --in <file.glb> [--gate <reports/gate-G6.json>] [--max-errors 0]
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import validator from 'gltf-validator';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
if (!args.in) { console.error('missing --in'); process.exit(2); }
const maxErrors = Number(args['max-errors'] ?? 0);
const file = resolve(args.in);
const bytes = new Uint8Array(readFileSync(file));

const report = await validator.validateBytes(bytes, {
  uri: file,
  maxIssues: 500,
  externalResourceFunction: (uri) => Promise.resolve(new Uint8Array(readFileSync(join(dirname(file), decodeURIComponent(uri))))),
});
const issues = report.issues;
const gate = {
  gate: 'G6',
  status: issues.numErrors <= maxErrors ? 'pass' : 'fail',
  metrics: { validator_errors: issues.numErrors, validator_warnings: issues.numWarnings, infos: issues.numInfos,
    hints: issues.numHints, validator_version: report.validatorVersion,
    extensions_used: report.info?.extensionsUsed ?? [], animation_count: report.info?.animationCount,
    skin_count: report.info?.skinCount, total_triangles: report.info?.totalTriangleCount },
  thresholds: { validator_errors_max: maxErrors },
  messages: issues.messages.filter(m => m.severity <= 1).slice(0, 50),
  at: new Date().toISOString(),
};
if (args.gate) { mkdirSync(dirname(resolve(args.gate)), { recursive: true }); writeFileSync(args.gate, JSON.stringify(gate, null, 2)); }
console.log(JSON.stringify(gate, null, 2));
process.exit(gate.status === 'pass' ? 0 : 1);
