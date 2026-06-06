#!/usr/bin/env python3
"""Generate the Solkart integration icon (map + house + sun) with Pillow.

Renders a high-res master and downscales to the PNG sizes Home Assistant /
HACS / the brands repo expect. No SVG rasterizer required.
"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 2048  # master (supersampled) size
R_TILE = int(S * 0.18)  # tile corner radius


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_col(c1, c2, t):
    return tuple(int(round(lerp(c1[i], c2[i], t))) for i in range(len(c1)))


def cubic(p0, p1, p2, p3, n=80):
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
        out.append((x, y))
    return out


def clip(layer, mask_l):
    r, g, b, a = layer.split()
    a = ImageChops.multiply(a, mask_l)
    return Image.merge("RGBA", (r, g, b, a))


img = Image.new("RGBA", (S, S), (0, 0, 0, 255))
d = ImageDraw.Draw(img)

# ---- 1. Map land: soft vertical green gradient ------------------------------
top, bot = (212, 235, 200, 255), (181, 214, 168, 255)
for y in range(S):
    d.line([(0, y), (S, y)], fill=lerp_col(top, bot, y / (S - 1)))

# ---- 2. Coastline / water (bottom-left, evokes the Norwegian coast) ---------
water = Image.new("RGBA", (S, S), (0, 0, 0, 0))
wd = ImageDraw.Draw(water)
coast = cubic((0, S * 0.58), (S * 0.24, S * 0.70), (S * 0.16, S * 0.96), (S * 0.44, S))
wd.polygon([(0, S * 0.58)] + coast + [(0, S)], fill=(150, 205, 232, 255))
water = water.filter(ImageFilter.GaussianBlur(S * 0.004))
img.alpha_composite(water)

# ---- 3. Roads (cream with casing) ------------------------------------------
def road(points, w, fill=(252, 244, 222, 255), casing=(206, 192, 162, 255)):
    d.line(points, fill=casing, width=int(w * 1.6), joint="curve")
    d.line(points, fill=fill, width=w, joint="curve")


road(cubic((S * 0.02, S * 0.34), (S * 0.40, S * 0.20), (S * 0.58, S * 0.56), (S * 1.00, S * 0.46)), int(S * 0.020))
road(cubic((S * 0.66, -S * 0.02), (S * 0.52, S * 0.30), (S * 0.74, S * 0.55), (S * 0.70, S * 1.02)), int(S * 0.013))

# ---- 4. Fold creases (subtle, like a paper map) ----------------------------
crease, hi = (60, 50, 40, 26), (255, 255, 255, 38)
for fx in (S / 3, 2 * S / 3):
    d.line([(fx, 0), (fx, S)], fill=crease, width=max(2, int(S * 0.004)))
    d.line([(fx + S * 0.006, 0), (fx + S * 0.006, S)], fill=hi, width=max(1, int(S * 0.0022)))
for fy in (S / 3, 2 * S / 3):
    d.line([(0, fy), (S, fy)], fill=crease, width=max(2, int(S * 0.004)))
    d.line([(0, fy + S * 0.006), (S, fy + S * 0.006)], fill=hi, width=max(1, int(S * 0.0022)))

# ---- 5. Sun (top-right): glow, rays, radial disc ---------------------------
cx, cy, Rsun = S * 0.705, S * 0.265, S * 0.125

glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse(
    [cx - Rsun * 2.6, cy - Rsun * 2.6, cx + Rsun * 2.6, cy + Rsun * 2.6],
    fill=(255, 211, 110, 95),
)
img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S * 0.032)))

rays = Image.new("RGBA", (S, S), (0, 0, 0, 0))
rd = ImageDraw.Draw(rays)
nray = 12
for i in range(nray):
    a = 2 * math.pi * i / nray + math.pi / nray
    r1, r2, w = Rsun * 1.32, Rsun * 1.92, 0.10
    p1 = (cx + math.cos(a - w) * r1, cy + math.sin(a - w) * r1)
    p2 = (cx + math.cos(a + w) * r1, cy + math.sin(a + w) * r1)
    p3 = (cx + math.cos(a) * r2, cy + math.sin(a) * r2)
    rd.polygon([p1, p2, p3], fill=(255, 197, 46, 255))
img.alpha_composite(rays)

disc = Image.new("RGBA", (S, S), (0, 0, 0, 0))
dd = ImageDraw.Draw(disc)
steps = 140
for i in range(steps, 0, -1):
    t = i / steps
    rr = Rsun * t
    col = lerp_col((255, 231, 120), (255, 176, 0), t)
    dd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col + (255,))
img.alpha_composite(disc)

# ---- 6. House drop shadow ---------------------------------------------------
sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).ellipse([S * 0.30, S * 0.745, S * 0.72, S * 0.83], fill=(40, 30, 20, 120))
img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(S * 0.018)))

# ---- 7. House --------------------------------------------------------------
wall_l, wall_r, wall_t, wall_b = S * 0.365, S * 0.635, S * 0.545, S * 0.785
roof = [(S * 0.50, S * 0.395), (S * 0.30, S * 0.556), (S * 0.70, S * 0.556)]
outline = (45, 40, 33, 255)
ow = max(2, int(S * 0.006))

# walls
d.rectangle([wall_l, wall_t, wall_r, wall_b], fill=(255, 253, 247, 255))
d.rectangle([wall_l, wall_t, wall_r, wall_b], outline=outline, width=ow)

# roof (navy solar field)
d.polygon(roof, fill=(23, 59, 94, 255))

# solar-panel grid clipped to roof triangle
roof_mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(roof_mask).polygon(roof, fill=255)
grid = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gdr = ImageDraw.Draw(grid)
gcol = (96, 150, 196, 235)
gw = max(2, int(S * 0.0035))
for k in range(1, 9):
    x = lerp(S * 0.30, S * 0.70, k / 9)
    gdr.line([(x, S * 0.39), (x, S * 0.56)], fill=gcol, width=gw)
for yy in (0.443, 0.487, 0.531):
    gdr.line([(S * 0.28, S * yy), (S * 0.72, S * yy)], fill=gcol, width=gw)
img.alpha_composite(clip(grid, roof_mask))

# roof sheen (upper-left)
sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sheen).polygon(
    [(S * 0.50, S * 0.395), (S * 0.355, S * 0.51), (S * 0.50, S * 0.51)],
    fill=(255, 255, 255, 36),
)
img.alpha_composite(clip(sheen, roof_mask))
d.polygon(roof, outline=outline, width=ow)

# door
d.rectangle([S * 0.470, S * 0.660, S * 0.530, S * 0.785], fill=(120, 80, 50, 255), outline=outline, width=max(1, int(S * 0.004)))
d.ellipse([S * 0.516, S * 0.722, S * 0.527, S * 0.733], fill=(245, 224, 150, 255))

# windows (sky reflection + cross)
def window(x0, y0, x1, y1):
    d.rectangle([x0, y0, x1, y1], fill=(176, 220, 240, 255), outline=outline, width=max(1, int(S * 0.004)))
    d.line([((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)], fill=outline, width=max(1, int(S * 0.003)))
    d.line([(x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)], fill=outline, width=max(1, int(S * 0.003)))


window(S * 0.395, S * 0.600, S * 0.452, S * 0.662)
window(S * 0.548, S * 0.600, S * 0.605, S * 0.662)

# ---- 8. Clip everything to the rounded tile + subtle inner stroke ----------
tile = Image.new("L", (S, S), 0)
ImageDraw.Draw(tile).rounded_rectangle([0, 0, S - 1, S - 1], radius=R_TILE, fill=255)
final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
final.paste(img, (0, 0), tile)
ImageDraw.Draw(final).rounded_rectangle(
    [int(S * 0.012)] * 2 + [int(S - S * 0.012)] * 2,
    radius=int(R_TILE * 0.92), outline=(255, 255, 255, 70), width=max(2, int(S * 0.006)),
)

# ---- 9. Export -------------------------------------------------------------
import os

BASE = "/home/blc/ha-solkart"
TARGETS = {
    "icons/icon.png": 256,
    "icons/icon@2x.png": 512,
    # Staged in the layout the home-assistant/brands repo expects.
    "brands/custom_integrations/solkart/icon.png": 256,
    "brands/custom_integrations/solkart/icon@2x.png": 512,
}
for rel, size in TARGETS.items():
    path = f"{BASE}/{rel}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    final.resize((size, size), Image.LANCZOS).save(path)
print("wrote:", ", ".join(TARGETS))
