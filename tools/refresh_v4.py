#!/usr/bin/env python3
"""One-off v4 refresh of the existing archive.

  * removes the given ids (dull images, satellite / map views) like
    remove_image.py (their pHash stays known, so they are not re-added)
  * enhances every image not yet "modified" (tools/enhance.py) and rewrites
    the full image (3000 px, WebP q85)
  * regenerates every thumbnail at 640 px (sharpened)
  * stores vividness metrics, the appeal score and the modification note

Usage: tools/refresh_v4.py [--remove ids.txt]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from common import FULL_LONG_SIDE, ROOT, THUMB_LONG_SIDE, THUMB_QUALITY, WEBP_QUALITY, load_catalog, log, save_catalog
from enhance import MODIFICATION, appeal, enhance, sharpen_thumb
from imaging import dominant_color, encode_webp, fit_long_side
from vividness import metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", default="")
    args = ap.parse_args()
    cat = load_catalog()
    remove = set(Path(args.remove).read_text().split()) if args.remove else set()
    kept = []
    for p in cat["puzzles"]:
        if p["id"] in remove:
            for rel in (p["imagePath"], p["thumbPath"]):
                (ROOT / rel).unlink(missing_ok=True)
            log(f"- {p['id']}")
            continue
        img = Image.open(ROOT / p["imagePath"]).convert("RGB")
        if not p.get("modified"):
            img = enhance(img)
            full = fit_long_side(img, FULL_LONG_SIDE)
            (ROOT / p["imagePath"]).write_bytes(encode_webp(full, WEBP_QUALITY))
            p["modified"] = True
            p["modification"] = MODIFICATION
        else:
            full = img
        thumb = sharpen_thumb(fit_long_side(full, THUMB_LONG_SIDE))
        (ROOT / p["thumbPath"]).write_bytes(encode_webp(thumb, THUMB_QUALITY))
        p["width"], p["height"] = full.size
        p["dominantColor"] = dominant_color(thumb)
        p["quality"] = metrics(full)
        p["appeal"] = appeal(p["quality"])
        kept.append(p)
    cat["puzzles"] = kept
    save_catalog(cat)
    log(f"{len(kept)} images refreshed, {len(remove)} removed")


if __name__ == "__main__":
    main()
