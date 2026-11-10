#!/usr/bin/env python3
"""Add images to the archive.

For every image in the input folder (default: inbox/, one sub-folder per
category, each image with a JSON sidecar written by the fetch_* tools):

  * applies EXIF orientation, rejects images whose long side < 2000 px
  * rejects perceptual duplicates (pHash Hamming distance <= 8) of anything
    already in the archive or added earlier in this run
  * resizes WITHOUT cropping to a 3000 px long side → images/<cat>/<id>.webp (q85)
  * 480 px thumbnail → thumbs/<id>.webp
  * computes the dominant colour, appends the entry to catalog.json and
    removes the processed source files from the inbox

Images without a sidecar can be added by hand:
  tools/add_images.py my_folder --category nature --license "CC0 1.0" \
      --photographer "Jane Doe" --source-url https://example.org/photo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from common import (CATEGORY_IDS, DUPLICATE_HAMMING, FULL_LONG_SIDE, INBOX, LICENSE_URLS, MIN_LONG_SIDE,
                    ROOT, THUMB_LONG_SIDE, THUMB_QUALITY, WEBP_QUALITY, ATTRIBUTION_LICENSES,
                    load_catalog, load_phash_index, log, normalize_license, save_catalog, save_phash_index)
from imaging import dominant_color, encode_webp, fit_long_side, hamming, open_upright, phash, quality_problem, trim_flat_border

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
REQUIRED = ("title", "photographer", "sourceUrl", "license")


def validate_meta(meta: dict) -> str | None:
    for k in REQUIRED:
        if not meta.get(k):
            return f"missing {k}"
    lic = meta["license"]
    if lic not in LICENSE_URLS and normalize_license(lic) is None:
        return f"licence not allowed: {lic}"
    if lic in ATTRIBUTION_LICENSES and meta["photographer"] in ("", "Unknown"):
        return "attribution licence without author"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(INBOX))
    ap.add_argument("--category")
    ap.add_argument("--license")
    ap.add_argument("--photographer")
    ap.add_argument("--source-url")
    ap.add_argument("--keep", action="store_true", help="do not delete processed inbox files")
    args = ap.parse_args()

    folder = Path(args.folder)
    cat = load_catalog()
    index = load_phash_index()
    known = {p["id"] for p in cat["puzzles"]}
    review = ROOT / "tools" / "review_rejected.json"
    review_rejected = json.loads(review.read_text()) if review.exists() else {}
    today = date.today().isoformat()
    added, rejected = 0, []

    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXTS)
    for src in files:
        category = args.category or src.parent.name
        if category not in CATEGORY_IDS:
            rejected.append((src.name, f"unknown category {category!r}"))
            continue
        side = src.with_suffix(".json")
        meta = json.loads(side.read_text()) if side.exists() else {}
        if args.license:
            meta.update({"license": normalize_license(args.license) or args.license,
                         "photographer": args.photographer or meta.get("photographer"),
                         "sourceUrl": args.source_url or meta.get("sourceUrl"),
                         "title": meta.get("title") or src.stem.replace("_", " ")})
        problem = validate_meta(meta)
        if problem:
            rejected.append((src.name, problem))
            continue
        pid = src.stem if src.stem.startswith(category + "-") else \
            f"{category}-{hashlib.sha1(meta['sourceUrl'].encode()).hexdigest()[:8]}"
        if pid in known:
            rejected.append((src.name, "already in catalog"))
            continue
        if pid in review_rejected:
            rejected.append((src.name, f"rejected in review: {review_rejected[pid]}"))
            continue
        try:
            img = trim_flat_border(open_upright(src))
        except Exception as e:  # noqa: BLE001
            rejected.append((src.name, f"unreadable: {e}"))
            continue
        if max(img.size) < MIN_LONG_SIDE:
            rejected.append((src.name, f"too small {img.size[0]}x{img.size[1]} (< {MIN_LONG_SIDE})"))
            continue
        problem = quality_problem(img)
        if problem:
            rejected.append((src.name, problem))
            continue
        h = phash(img)
        dup = next((k for k, v in index.items() if hamming(h, v) <= DUPLICATE_HAMMING), None)
        if dup:
            rejected.append((src.name, f"duplicate of {dup}"))
            continue

        full = fit_long_side(img, FULL_LONG_SIDE)
        thumb = fit_long_side(img, THUMB_LONG_SIDE)
        image_path = f"images/{category}/{pid}.webp"
        thumb_path = f"thumbs/{pid}.webp"
        (ROOT / image_path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / thumb_path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / image_path).write_bytes(encode_webp(full, WEBP_QUALITY))
        (ROOT / thumb_path).write_bytes(encode_webp(thumb, THUMB_QUALITY))

        lic = meta["license"]
        cat["puzzles"].append({
            "id": pid,
            "categoryId": category,
            "title": meta["title"],
            "imagePath": image_path,
            "thumbPath": thumb_path,
            "width": full.size[0],
            "height": full.size[1],
            "dominantColor": dominant_color(thumb),
            "photographer": meta["photographer"],
            "sourceUrl": meta["sourceUrl"],
            "license": lic,
            "licenseUrl": meta.get("licenseUrl") or LICENSE_URLS.get(lic, ""),
            "attributionRequired": bool(meta.get("attributionRequired", lic in ATTRIBUTION_LICENSES)),
            "addedAt": today,
            "isNew": True,
        })
        index[pid] = h
        known.add(pid)
        added += 1
        log(f"+ {pid} {full.size[0]}x{full.size[1]} {lic}")
        if not args.keep and folder.resolve() == INBOX.resolve():
            src.unlink()
            if side.exists():
                side.unlink()

    save_catalog(cat)
    save_phash_index(index)
    for name, why in rejected:
        log(f"- {name}: {why}")
    print(f"added {added}, rejected {len(rejected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
