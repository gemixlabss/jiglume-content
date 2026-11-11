#!/usr/bin/env python3
"""Image appeal metrics used to keep the archive vivid.

* colourfulness — Hasler & Süsstrunk (2003) M3 on a 640 px copy
  (≈ <15 dull/grey, 15–33 moderate, 33–45 quite, >45 highly colourful)
* contrast      — RMS contrast: std of luminance / 255 (0…0.5)
* sharpness     — variance of the Laplacian on a 1024 px greyscale copy,
                  log-scaled to roughly 0…10 (blurry < ~4)

`dull_reason()` returns why an image is too dull for the archive, or None.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

MIN_COLORFULNESS = 28.0  # v4.1: raised from 22 — "European rabbit kitten" (26.9) looked washed out
MIN_CONTRAST = 0.16
MIN_SHARPNESS = 3.6


def _rgb(img: Image.Image, side: int) -> np.ndarray:
    small = img.convert("RGB")
    small.thumbnail((side, side), Image.LANCZOS)
    return np.asarray(small, dtype=np.float32)


def colorfulness(img: Image.Image) -> float:
    a = _rgb(img, 640)
    rg = a[..., 0] - a[..., 1]
    yb = 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def contrast(img: Image.Image) -> float:
    a = _rgb(img, 640)
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    return float(lum.std() / 255)


def sharpness(img: Image.Image) -> float:
    g = img.convert("L")
    g.thumbnail((1024, 1024), Image.LANCZOS)
    a = np.asarray(g, dtype=np.float32)
    lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:])
    return float(math.log1p(lap.var()))


def metrics(img: Image.Image) -> dict:
    return {
        "colorfulness": round(colorfulness(img), 1),
        "contrast": round(contrast(img), 3),
        "sharpness": round(sharpness(img), 2),
    }


def dull_reason(m: dict, *, category: str = "") -> str | None:
    # Night skies / art are legitimately darker or more muted: a little slack.
    slack = 0.8 if category in ("night", "art", "patterns") else 1.0
    if m["colorfulness"] < MIN_COLORFULNESS * slack:
        return f"dull colours ({m['colorfulness']})"
    if m["contrast"] < MIN_CONTRAST * slack:
        return f"flat contrast ({m['contrast']})"
    if m["sharpness"] < MIN_SHARPNESS:
        return f"blurry ({m['sharpness']})"
    return None
