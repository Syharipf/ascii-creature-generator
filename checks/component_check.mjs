import path from "node:path";
import { pathToFileURL } from "node:url";

const [mjsPath] = process.argv.slice(2);
if (!mjsPath) {
  console.error("Usage: node component_check.mjs <creature.mjs>");
  process.exit(1);
}

const modUrl = pathToFileURL(path.resolve(mjsPath)).href;
const mod = await import(modUrl);

// 1. Verify exports
const { creature, createAppearance, motionNodes, drawCreature } = mod;
if (!creature || typeof creature !== "object") throw new Error("Missing creature export");
if (typeof createAppearance !== "function") throw new Error("Missing createAppearance export");
if (typeof motionNodes !== "function") throw new Error("Missing motionNodes export");
if (typeof drawCreature !== "function") throw new Error("Missing drawCreature export");

// 2. Creature descriptor schema
if (creature.format !== "ascii-creature/1") throw new Error(`Invalid format: ${creature.format}`);
if (!creature.id || typeof creature.id !== "string") throw new Error("Invalid id");
if (!creature.name || typeof creature.name !== "string") throw new Error("Invalid name");
if (!creature.grid || creature.grid.cols < 8 || creature.grid.rows < 1) throw new Error("Invalid grid");
if (!Array.isArray(creature.cells) || creature.cells.length === 0) throw new Error("No cells in creature");
if (!creature.motion || typeof creature.motion !== "object") throw new Error("Missing motion in creature");
const validPovs = new Set(["side", "top", "isometric", "bottom"]);
if (!validPovs.has(creature.motion.pov)) throw new Error(`Invalid motion pov: ${creature.motion.pov}`);
if (typeof creature.motion.pitch !== "number" || !Number.isFinite(creature.motion.pitch)) {
  throw new Error(`Invalid motion pitch: ${creature.motion.pitch}`);
}
if (typeof creature.motion.roll !== "number" || !Number.isFinite(creature.motion.roll)) {
  throw new Error(`Invalid motion roll: ${creature.motion.roll}`);
}

const hexRe = /^#[0-9a-f]{6}$/i;
for (const cell of creature.cells) {
  if (cell.u < 0 || cell.u > 1 || cell.v < 0 || cell.v > 1) {
    throw new Error(`Cell coordinate out of bounds: u=${cell.u}, v=${cell.v}`);
  }
  if (typeof cell.g !== "string" || cell.g.length !== 1) {
    throw new Error(`Invalid glyph: ${cell.g}`);
  }
  if (!hexRe.test(cell.bg)) throw new Error(`Invalid bg color: ${cell.bg}`);
  if (!hexRe.test(cell.fg)) throw new Error(`Invalid fg color: ${cell.fg}`);
}

// 3. createAppearance tests
let threw = false;
try {
  createAppearance(0);
} catch (e) {
  threw = true;
}
if (!threw) throw new Error("createAppearance(0) did not throw");

const app1 = createAppearance(240);
if (app1.length !== 240) throw new Error("Appearance length mismatch");
if (!Array.isArray(app1.strips) || app1.strips.length !== 12) throw new Error("Expected 12 strips");

let totalStripCells = 0;
for (const s of app1.strips) {
  if (typeof s.start !== "number" || typeof s.end !== "number") throw new Error("Invalid strip boundaries");
  totalStripCells += s.cells.length;
}
if (totalStripCells !== creature.cells.length) {
  throw new Error(`Strip cells count ${totalStripCells} != creature cells ${creature.cells.length}`);
}

const app2 = createAppearance(240);
if (app1 !== app2) throw new Error("createAppearance memoization failed");

// 4. motionNodes tests
const nodes = motionNodes(1.2, 240);
if (!(nodes instanceof Float32Array) || nodes.length !== 40) throw new Error("motionNodes must return Float32Array(40)");
for (let i = 0; i < 40; i++) {
  if (!Number.isFinite(nodes[i])) throw new Error(`Node ${i} is not finite: ${nodes[i]}`);
}

const customOut = new Float32Array(40);
const returned = motionNodes(0.5, 200, customOut);
if (returned !== customOut) throw new Error("motionNodes did not reuse out buffer");

// 5. drawCreature mock canvas test
let saves = 0;
let restores = 0;
let fillRects = 0;
let fillTexts = 0;

const mockCtx = {
  font: "",
  textAlign: "",
  textBaseline: "",
  fillStyle: "",
  globalAlpha: 1.0,
  scaleCalls: [],
  scale(sx, sy) {
    if (!Number.isFinite(sx) || !Number.isFinite(sy) || sx <= 0 || sy <= 0) {
      throw new Error(`scale invalid: ${sx}, ${sy}`);
    }
    this.scaleCalls.push({ sx, sy });
  },
  save() { saves++; },
  restore() { restores++; },
  translate(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error(`translate NaN: ${x}, ${y}`);
  },
  rotate(a) {
    if (!Number.isFinite(a)) throw new Error(`rotate NaN: ${a}`);
  },
  fillRect(x, y, w, h) {
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(w) || !Number.isFinite(h)) {
      throw new Error(`fillRect non-finite: ${x}, ${y}, ${w}, ${h}`);
    }
    fillRects++;
  },
  fillText(text, x, y) {
    if (typeof text !== "string" || !Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error(`fillText invalid args: ${text}, ${x}, ${y}`);
    }
    fillTexts++;
  }
};

drawCreature(mockCtx, { x: 100, y: 150, angle: Math.PI, length: 240, time: 0.5, opacity: 0.9 });

if (saves === 0 || saves !== restores) {
  throw new Error(`Unbalanced save/restore calls: saves=${saves}, restores=${restores}`);
}
if (fillRects === 0) throw new Error("No fillRect calls made during drawCreature");
if (fillTexts === 0) throw new Error("No fillText calls made during drawCreature");

if (mockCtx.scaleCalls.length === 0) throw new Error("No scale calls made during drawCreature");

mockCtx.scaleCalls = [];
drawCreature(mockCtx, { x: 100, y: 150, angle: 0, length: 240, time: 0, pitch: 45, roll: 0 });
if (mockCtx.scaleCalls.length === 0) throw new Error("No scale calls recorded for pitch=45");
for (const sc of mockCtx.scaleCalls) {
  if (Math.abs(sc.sy - Math.cos(45 * Math.PI / 180)) > 0.01) {
    throw new Error(`Expected scale sy around 0.707, got ${sc.sy}`);
  }
}

console.log("PASS: component runtime");
