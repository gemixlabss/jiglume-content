#!/usr/bin/env python3
"""Gentle, natural-looking image enhancement for the archive (v4+).

  1. auto levels — black / white points from the 0.4 % / 99.6 % luminance
     percentiles, the same stretch on every channel (colour balance kept),
     never more than ×1.25
  2. a mild S-curve on luminance (+ a touch of local contrast)
  3. vibrance +12 % — boosts muted colours more than saturated ones; skin
     tones (orange hues) get only a third of it
  4. thumbnails: light unsharp mask after downscaling

Every enhanced image is marked "modified": true in catalog.json; for CC BY
images LICENSES.md and the app say "colours adjusted" (the licence requires
indicating changes).

`appeal()` turns the vividness metrics into a 0–100 score ("Popular").
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

MODIFICATION = "levels, contrast and vibrance adjusted"


def enhance(img: Image.Image) -> Image.Image:
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    lo, hi = np.percentile(lum, [0.4, 99.6])
    span = max(hi - lo, 1 / 1.25)
    a = np.clip((a - lo) / span, 0, 1)

    # Mild S-curve on luminance, applied as a ratio (keeps hue).
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    s = lum * lum * (3 - 2 * lum)  # smoothstep
    curved = 0.78 * lum + 0.22 * s
    ratio = np.where(lum > 1e-4, curved / np.maximum(lum, 1e-4), 1.0)
    a = np.clip(a * ratio[..., None], 0, 1)

    # Vibrance in HSV.
    hsv = np.asarray(Image.fromarray((a * 255 + 0.5).astype(np.uint8), "RGB").convert("HSV"), dtype=np.float32)
    h, sat, v = hsv[..., 0] / 255 * 360, hsv[..., 1] / 255, hsv[..., 2]
    skin = (h >= 5) & (h <= 50)
    amount = np.where(skin, 0.04, 0.12)
    sat = np.clip(sat + amount * sat * (1 - sat) * 2.2, 0, 1)
    hsv = np.stack([hsv[..., 0], sat * 255, v], axis=-1)
    out = Image.fromarray(np.clip(hsv + 0.5, 0, 255).astype(np.uint8), "HSV").convert("RGB")
    # A touch of local contrast (large-radius unsharp mask, low amount).
    return out.filter(ImageFilter.UnsharpMask(radius=30, percent=12, threshold=0))


def sharpen_thumb(img: Image.Image) -> Image.Image:
    return img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=65, threshold=2))


def appeal(m: dict) -> float:
    c = min(max(m["colorfulness"] / 70, 0), 1)
    k = min(max((m["contrast"] - 0.10) / 0.20, 0), 1)
    s = min(max((m["sharpness"] - 3.5) / 4.5, 0), 1)
    return round(100 * (0.5 * c + 0.3 * k + 0.2 * s), 1)
