# ASCII Creature Generator

Turn creature photos (sea, land, air, fantasy) into animated ASCII components.

Outputs:
- `<id>.mjs` — self-contained ES module (sprite data + `createAppearance` + `motionNodes` + `drawCreature`). No imports, no runtime dependencies.
- `<id>.json` — portable JSON descriptor for tooling.
- `<id>.txt` — monochrome ASCII art.

## Requirements

- Python 3.11+
- `Pillow`
- `numpy`

Check-only prerequisites (for running integration verification suites):
- Node.js 22+
- Qt 6.12 `qml6`

## Quick Start

CLI export:
```sh
python3 -m ascii_creature export path/to/creature.png --id my-creature --out out/
```

Interactive TUI:
```sh
python3 -m ascii_creature tui path/to/creature.png --out out/
```

Localhost Web GUI:
```sh
python3 -m ascii_creature gui path/to/creature.png --out out/
```

## Image Guidance

Background removal targets clean/simple solid backgrounds or transparent PNGs. Complex natural scenes require a pre-cutout PNG with alpha. Border-connected flood fill protects similarly coloured interior body parts, so interior holes matching the background color may remain filled. Head orientation is manual (`--head-side left|right`); if the creature swims backward, flip head side.

## Consumer Integration

### ascii-ocean

Copy `<id>.mjs` to `package/contents/ui/creatures/<id>.mjs`, then edit `package/contents/ui/engine.mjs`:

```js
// package/contents/ui/engine.mjs
import * as CUSTOM from "./creatures/<id>.mjs";

// add "<id>" to ALL_SPECIES_POOL
// add a case in getSharkSpecs:
case "<id>":
  return [
    { kind: "<id>", size: 1.0 },
    { kind: "<id>", size: 0.88 },
    { kind: "<id>", size: 0.78 },
    { kind: "<id>", size: 0.68 }
  ];

// in getAppearance, replace the animalAppearance call:
app = kind === CUSTOM.creature.id
  ? CUSTOM.createAppearance(length)
  : animalAppearance(kind, length, this.cellWidth, this.cellHeight);
```

### Generic Canvas Consumer

```js
import { drawCreature } from "./creatures/<id>.mjs";
requestAnimationFrame(function loop(now) {
  ctx.clearRect(0, 0, w, h);
  drawCreature(ctx, {x: w * 0.25, y: h * 0.5, angle: Math.PI, length: 240, time: now / 1000});
  requestAnimationFrame(loop);
});
```

### QML Spine Consumer

Use `createAppearance(length)` as the appearance object and `motionNodes(time, length)` as the 20-node spine, exactly like `Animal.qml` expects. `creature.cells` is the portable normalized grid for any other renderer. `ascii-sky` is currently empty, so it will use the same contract once it has a renderer.

## Verification

Run all automated checks:
```sh
python3 checks/selfcheck.py
```
