import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [mjsPath, expectedJsonPath] = process.argv.slice(2);
if (!mjsPath || !expectedJsonPath) {
  console.error("Usage: node motion_check.mjs <creature.mjs> <expected.json>");
  process.exit(1);
}

const modUrl = pathToFileURL(path.resolve(mjsPath)).href;
const mod = await import(modUrl);
const expected = JSON.parse(fs.readFileSync(expectedJsonPath, "utf-8"));

if (typeof mod.motionNodes !== "function") {
  console.error("FAIL: motionNodes export missing");
  process.exit(1);
}

const actual = mod.motionNodes(expected.time, expected.length);
if (!actual || actual.length !== 40) {
  console.error(`FAIL: expected 40 floats, got ${actual ? actual.length : "null"}`);
  process.exit(1);
}

for (let i = 0; i < 40; i++) {
  const diff = Math.abs(actual[i] - expected.nodes[i]);
  if (diff > 1e-6) {
    console.error(`FAIL: node float mismatch at index ${i}: actual=${actual[i]} expected=${expected.nodes[i]} diff=${diff}`);
    process.exit(1);
  }
}

console.log("PASS: motion parity");
