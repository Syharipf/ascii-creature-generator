"""Motion presets and spine node calculation."""

import math

MOTION_PRESETS: dict[str, dict[str, float]] = {
    "swim": {"amplitude": 1.0, "speed": 0.55, "wavelength": 1.1, "bob": 0.35},
    "glide": {"amplitude": 0.35, "speed": 0.25, "wavelength": 1.6, "bob": 0.8},
    "flap": {"amplitude": 1.6, "speed": 0.90, "wavelength": 0.8, "bob": 0.6},
    "crawl": {"amplitude": 0.6, "speed": 0.35, "wavelength": 0.5, "bob": 0.15},
}

POV_PRESETS: dict[str, dict[str, float]] = {
    "side": {"pitch": 0.0, "roll": 0.15},
    "top": {"pitch": 55.0, "roll": 0.35},
    "isometric": {"pitch": 30.0, "roll": 0.25},
    "bottom": {"pitch": -30.0, "roll": 0.20},
}


def perspective_scale(
    pitch_deg: float,
    roll_factor: float,
    time: float,
    s: float,
    wav: float = 1.1,
    speed: float = 0.55,
) -> float:
    pitch_rad = math.radians(pitch_deg)
    roll_rad = roll_factor * math.sin(2.0 * math.pi * (s / max(0.01, wav) - speed * time))
    return max(0.12, math.cos(pitch_rad) * math.cos(roll_rad))


def motion_nodes(motion: dict, time: float, length: float) -> list[tuple[float, float]]:
    amp = length * 0.055 * float(motion.get("amplitude", 1.0))
    bob = length * 0.04 * float(motion.get("bob", 0.35))
    wav = max(0.25, float(motion.get("wavelength", 1.1)))
    speed = float(motion.get("speed", 0.55))

    nodes: list[tuple[float, float]] = []
    for i in range(20):
        s = i / 19.0
        lateral = amp * (s ** 1.4) * math.sin(2.0 * math.pi * (s / wav - speed * time))
        y = lateral + bob * math.sin(2.0 * math.pi * (0.35 * time + 0.5 * s))
        x = -length * s
        nodes.append((x, y))
    return nodes
