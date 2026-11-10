#!/usr/bin/env python3
"""Assigns `"tier": "free" | "premium"` to catalog puzzles.

In every category the most striking ~35 % of the images become premium
(opened in the app with Lume, later with a subscription); the rest are free.

"Striking" is measured on the 480 px thumbnail as the sum of z-scores (within
the category) of
  * colourfulness (Hasler–Süsstrunk),
  * global contrast (std of luminance),
  * detail (edge density — rich, varied puzzles),
  * saturation in the mid tones (vivid but not blown out).

Rules:
  * Images pinned in tools/tiers_pinned.json keep that tier (the offline
    starter pack is always free).
  * Images that already have a tier keep it (players may have unlocked them),
    unless --reassign is given.
  * New images: the category is topped up to its premium quota from the
    highest-scoring untiered images; the remainder is free.

  tools/assign_tiers.py               # assign tiers to untiered images
  tools/assign_tiers.py --reassign    # recompute every non-pinned image
  tools/assign_tiers.py --report      # print scores, change nothing
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
from PIL import Image, ImageFilter

from common import ROOT, load_catalog, save_catalog

PREMIUM_SHARE = 0.35
PINNED = ROOT / "tools" / "tiers_pinned.json"
TIERS = ("free", "premium")


def features(path) -> tuple[float, float, float, float]:
    img = Image.open(path).convert("RGB")
    img.thumbnail((480, 480))
    a = np.asarray(img, dtype=np.float32)
    rg = a[..., 0] - a[..., 1]
    yb = 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    contrast = float(lum.std())
    edges = float((np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32) > 24).mean())
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32)
    mid = (hsv[..., 2] > 40) & (hsv[..., 2] < 235)
    vivid = float(hsv[..., 1][mid].mean() / 255) if mid.any() else 0.0
    return colorful, contrast, edges, vivid


def zscores(values: list[float]) -> list[float]:
    m = sum(values) / len(values)
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / len(values)) or 1.0
    return [(v - m) / sd for v in values]


def main(argv: list[str]) -> int:
    reassign = "--reassign" in argv
    report = "--report" in argv
    pinned = json.loads(PINNED.read_text())
    pin = {**{i: "free" for i in pinned.get("free", [])}, **{i: "premium" for i in pinned.get("premium", [])}}
    cat = load_catalog()
    by_cat: dict[str, list[dict]] = {}
    for p in cat["puzzles"]:
        by_cat.setdefault(p["categoryId"], []).append(p)

    changed = 0
    for cid, items in sorted(by_cat.items()):
        feats = [features(ROOT / p["thumbPath"]) for p in items]
        cols = list(zip(*feats))
        z = [zscores(list(c)) for c in cols]
        # Colour and contrast matter most for a "wow" puzzle.
        weights = (1.2, 1.0, 0.6, 0.8)
        scores = [sum(w * z[k][i] for k, w in enumerate(weights)) for i in range(len(items))]
        quota = round(len(items) * PREMIUM_SHARE)
        ranked = sorted(range(len(items)), key=lambda i: -scores[i])

        tier: dict[str, str] = {}
        for p in items:
            if p["id"] in pin:
                tier[p["id"]] = pin[p["id"]]
            elif not reassign and p.get("tier") in TIERS:
                tier[p["id"]] = p["tier"]
        have = sum(1 for t in tier.values() if t == "premium")
        for i in ranked:
            pid = items[i]["id"]
            if pid in tier:
                continue
            if have < quota:
                tier[pid] = "premium"
                have += 1
            else:
                tier[pid] = "free"

        if report:
            print(f"\n{cid}: {len(items)} images, quota {quota} premium")
            for i in ranked:
                f = feats[i]
                print(f"  {scores[i]:+6.2f}  {tier[items[i]['id']]:<7}  {items[i]['id']:<26} "
                      f"colour {f[0]:5.1f}  contrast {f[1]:5.1f}  edges {f[2]:.3f}  vivid {f[3]:.2f}")
            continue
        for p in items:
            if p.get("tier") != tier[p["id"]]:
                p["tier"] = tier[p["id"]]
                changed += 1

    if not report:
        save_catalog(cat)
        n = len(cat["puzzles"])
        prem = sum(1 for p in cat["puzzles"] if p.get("tier") == "premium")
        print(f"tiers: {prem}/{n} premium ({prem / n:.0%}), {changed} changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
