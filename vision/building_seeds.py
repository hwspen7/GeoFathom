"""Scale-aware watershed seed selection with bounded source-pixel spacing."""
import math
import numpy as np


def seed_spacing(radius, maximum):
    """Use local inscribed radius; narrow roofs may have closer seed centers."""
    return max(1, min(maximum, max(2, int(math.ceil(1.5*radius)))))


def select_seeds(candidates, radii, maximum, *, adaptive=False, limit=20000):
    """Greedy stable suppression using a bounded spatial bucket neighborhood.

    A large roof must not suppress a nearby small roof solely because of its
    radius. Pairwise spacing is the smaller local spacing. Fixed mode retains
    the original constant-distance behavior.
    """
    selected, buckets = [], {}
    for _, y, x in sorted(candidates, key=lambda t: (-t[0], t[1], t[2])):
        spacing = seed_spacing(float(radii[y, x]), maximum) if adaptive else maximum
        by, bx = y//maximum, x//maximum
        neighbors = [pos for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                     for pos in buckets.get((by+dy, bx+dx), [])]
        if all((y-sy)**2+(x-sx)**2 >= min(spacing, sr)**2 for sy, sx, sr in neighbors):
            selected.append((y, x))
            buckets.setdefault((by, bx), []).append((y, x, spacing))
            if len(selected) > limit:
                raise ValueError("Too many instance seeds; reduce the study area.")
    return selected
