import path from "node:path";
import { pathToFileURL } from "node:url";

const args = process.argv.slice(2);
let enginePath = null;
let kind = null;

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--engine" && i + 1 < args.length) {
    enginePath = args[++i];
  } else if (args[i] === "--kind" && i + 1 < args.length) {
    kind = args[++i];
  }
}

if (!enginePath || !kind) {
  console.error("Usage: node consumer_engine_check.mjs --engine <path/to/engine.mjs> --kind <kind-id>");
  process.exit(1);
}

const engineUrl = pathToFileURL(path.resolve(enginePath)).href;
const mod = await import(engineUrl);

const { OceanEngine, getSharkSpecs } = mod;
if (typeof OceanEngine !== "function") throw new Error("OceanEngine export missing");
if (typeof getSharkSpecs !== "function") throw new Error("getSharkSpecs export missing");

const specs = getSharkSpecs(kind);
if (!Array.isArray(specs) || specs.length !== 4) {
  throw new Error(`getSharkSpecs("${kind}") did not return 4 specs, got: ${JSON.stringify(specs)}`);
}
for (const s of specs) {
  if (s.kind !== kind) {
    throw new Error(`Spec kind mismatch: expected ${kind}, got ${s.kind}`);
  }
}

const engine = new OceanEngine({ sharkKind: kind });
engine.resize(1280, 720);

let frame = null;
for (let step = 0; step < 60; step++) {
  frame = engine.advance(1 / 30);
}

if (!frame || !Array.isArray(frame.animals) || frame.animals.length !== 4) {
  throw new Error(`Expected 4 animals in frame, got ${frame ? (frame.animals ? frame.animals.length : "no animals") : "null"}`);
}

for (let i = 0; i < frame.animals.length; i++) {
  const anim = frame.animals[i];
  if (!anim.appearance || !Array.isArray(anim.appearance.strips) || anim.appearance.strips.length !== 12) {
    throw new Error(`Animal ${i} appearance missing 12 strips`);
  }

  let totalCells = 0;
  for (const strip of anim.appearance.strips) {
    totalCells += (strip.cells || []).length;
  }
  if (totalCells === 0) {
    throw new Error(`Animal ${i} has 0 total cells in appearance`);
  }

  if (!anim.nodes || anim.nodes.length !== 40) {
    throw new Error(`Animal ${i} nodes expected 40, got ${anim.nodes ? anim.nodes.length : "none"}`);
  }
  for (let n = 0; n < anim.nodes.length; n++) {
    if (!Number.isFinite(anim.nodes[n])) {
      throw new Error(`Animal ${i} node ${n} is not finite: ${anim.nodes[n]}`);
    }
  }
}

console.log("PASS: consumer engine integration");
