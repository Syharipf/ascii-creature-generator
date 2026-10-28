"""Generate self-contained ES module for creature component."""

import json


def module_source(component: dict) -> str:
    creature_json = json.dumps(component, ensure_ascii=False, separators=(",", ":"))
    return f"""export const creature = {creature_json};

let _lastLength = 0;
let _lastAppearance = null;

export function createAppearance(length) {{
  if (!(length > 0)) {{
    throw new Error("length must be > 0");
  }}
  if (length === _lastLength && _lastAppearance) {{
    return _lastAppearance;
  }}

  const cols = creature.grid.cols;
  const rows = creature.grid.rows;
  const cw = length / cols;
  const ch = cw / creature.grid.cellAspect;
  const reach = rows * ch * 0.5;

  const strips = [];
  for (let i = 0; i < 12; i++) {{
    strips.push({{
      start: (length * i) / 12,
      end: (length * (i + 1)) / 12,
      cells: []
    }});
  }}

  const cells = creature.cells;
  for (let i = 0; i < cells.length; i++) {{
    const cell = cells[i];
    const x = cell.u * length;
    const si = Math.min(11, Math.max(0, Math.floor((x / length) * 12)));
    strips[si].cells.push({{
      x: x - strips[si].start,
      y: (cell.v - 0.5) * rows * ch,
      v: cell.v,
      glyph: cell.g,
      background: cell.bg,
      foreground: cell.fg
    }});
  }}

  const app = {{
    key: creature.id + ":" + length.toFixed(2),
    length: length,
    reach: reach,
    cellWidth: cw,
    cellHeight: ch,
    strips: strips
  }};
  _lastLength = length;
  _lastAppearance = app;
  return app;
}}

let _cachedNodes = new Float32Array(40);

export function motionNodes(time, length, out) {{
  const m = creature.motion;
  const nodes = out || new Float32Array(40);
  const amp = length * 0.055 * m.amplitude;
  const bob = length * 0.04 * m.bob;
  const wav = Math.max(0.25, m.wavelength);
  for (let i = 0; i < 20; i++) {{
    const s = i / 19;
    const lateral = amp * Math.pow(s, 1.4) * Math.sin(2 * Math.PI * (s / wav - m.speed * time));
    nodes[i * 2] = -length * s;
    nodes[i * 2 + 1] = lateral + bob * Math.sin(2 * Math.PI * (0.35 * time + 0.5 * s));
  }}
  return nodes;
}}

export function drawCreature(ctx, opts) {{
  if (!opts) return;
  const length = opts.length;
  if (!(length > 0)) return;

  const x = opts.x || 0;
  const y = opts.y || 0;
  const angle = opts.angle || 0;
  const time = opts.time || 0;
  const opacity = opts.opacity !== undefined ? opts.opacity : 1;

  const appearance = createAppearance(length);
  const nodes = motionNodes(time, length, _cachedNodes);

  ctx.save();
  if (opacity < 1) {{
    ctx.globalAlpha = (ctx.globalAlpha !== undefined ? ctx.globalAlpha : 1) * opacity;
  }}
  ctx.translate(x, y);
  if (angle) {{
    ctx.rotate(angle);
  }}


  const m = creature.motion || {{}};
  const pitch = opts.pitch !== undefined ? opts.pitch : (m.pitch !== undefined ? m.pitch : 0);
  const roll = opts.roll !== undefined ? opts.roll : (m.roll !== undefined ? m.roll : 0.15);
  const basePitchScale = Math.max(0.15, Math.cos(pitch * Math.PI / 180));
  const wav = Math.max(0.25, m.wavelength || 1.1);
  const speed = m.speed !== undefined ? m.speed : 0.55;
  const hasScale = typeof ctx.scale === "function";
  const doDepthShade = pitch !== 0;
  const sinPitch = doDepthShade ? Math.sin(pitch * Math.PI / 180) : 0;
  const cw = appearance.cellWidth;
  const ch = appearance.cellHeight;
  ctx.font = "600 " + Math.max(1, Math.round(ch * 0.74)) + "px ui-monospace, Menlo, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  for (let i = 0; i < appearance.strips.length; i++) {{
    const strip = appearance.strips[i];
    if (!strip.cells || strip.cells.length === 0) continue;

    const sCenter = (strip.start + strip.end) * 0.5;
    const sNorm = sCenter / length;
    const stripRoll = roll * Math.sin(2 * Math.PI * (sNorm / wav - speed * time));
    const stripScaleY = Math.max(0.10, basePitchScale * Math.cos(stripRoll));
    const nodePos = (sCenter / length) * 19;
    const k = Math.min(18, Math.max(0, Math.floor(nodePos)));
    const f = nodePos - k;
    const nodeX = nodes[k * 2] * (1 - f) + nodes[(k + 1) * 2] * f;
    const nodeY = nodes[k * 2 + 1] * (1 - f) + nodes[(k + 1) * 2 + 1] * f;
    const prevX = nodes[Math.max(0, k - 1) * 2];
    const prevY = nodes[Math.max(0, k - 1) * 2 + 1];
    const nextX = nodes[Math.min(19, k + 1) * 2];
    const nextY = nodes[Math.min(19, k + 1) * 2 + 1];
    const stripAngle = Math.atan2(nextY - prevY, nextX - prevX);

    ctx.save();
    ctx.translate(nodeX, nodeY);
    ctx.rotate(stripAngle);
    if (hasScale) {{
      ctx.scale(1.0, stripScaleY);
    }}

    const baseAlpha = ctx.globalAlpha !== undefined ? ctx.globalAlpha : 1;
    for (let c = 0; c < strip.cells.length; c++) {{
      const cell = strip.cells[c];
      const cx = cell.x - cw * 0.25;
      const cy = hasScale ? cell.y : cell.y * stripScaleY;
      const chScaled = hasScale ? ch : ch * stripScaleY;
      if (doDepthShade) {{
        const vNorm = cell.v !== undefined ? cell.v : 0.5;
        const shade = 1.0 - (vNorm - 0.5) * sinPitch * 0.35;
        ctx.globalAlpha = Math.max(0.2, Math.min(1.0, baseAlpha * shade));
      }}
      ctx.fillStyle = cell.background;
      ctx.fillRect(Math.round(cx - cw * 0.5 + 1), Math.round(cy - chScaled * 0.5 + 1), cw - 1, Math.max(1, Math.round(chScaled - 1)));
      ctx.fillStyle = cell.foreground;
      ctx.fillText(cell.glyph, Math.round(cx), Math.round(cy + 1));
    }}
    if (doDepthShade) {{
      ctx.globalAlpha = baseAlpha;
    }}
    ctx.restore();
  }}
  ctx.restore();
}}
"""
