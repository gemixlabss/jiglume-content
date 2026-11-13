#!/usr/bin/env python3
"""2K-vs-4K comparison: both versions of the same scenes processed to the
final 3000 px (2K: Lanczos upscale + light sharpening, 4K: Lanczos
downscale), with 100 % crops side by side and sharpness / detail numbers.

    tools/ai_compare.py --ids cute_pets-01,landscapes-01 --out compare.jpg
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_quality import RAW, to_final  # noqa: E402
from vividness import metrics  # noqa: E402


def find(scene_id: str, size: str) -> Path | None:
    hits = [p for p in RAW.glob(f"*/{scene_id}-{size.lower()}.*") if p.suffix != ".json"]
    return hits[0] if hits else None


def fine_detail(img: Image.Image) -> float:
    """Mean absolute Laplacian at full resolution (fine texture energy)."""
    g = np.asarray(img.convert("L"), dtype=np.float32)
    lap = np.abs(g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    return round(float(lap.mean()), 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--crop", type=int, default=520)
    args = ap.parse_args()
    font = ImageFont.load_default(size=18)
    rows = []
    stats = []
    for sid in args.ids.split(","):
        pair = {s: find(sid, s) for s in ("2K", "4K")}
        if not all(pair.values()):
            continue
        tiles = []
        for size, path in pair.items():
            final = to_final(Image.open(path))
            m = metrics(final)
            det = fine_detail(final)
            cost = json.loads(path.with_suffix(".json").read_text())["cost"]["usd"]
            stats.append({"id": sid, "size": size, "final": final.size, "sharpness": m["sharpness"],
                          "fineDetail": det, "usd": cost})
            # A 100 % crop from the detailed middle of the final image.
            cx, cy = final.width // 2, int(final.height * 0.55)
            c = args.crop // 2
            crop = final.crop((cx - c, cy - c, cx + c, cy + c))
            thumb = final.copy()
            thumb.thumbnail((args.crop * 3 // 4, args.crop))
            tile = Image.new("RGB", (thumb.width + args.crop + 12, args.crop + 34), (246, 244, 239))
            tile.paste(thumb, (0, 34))
            tile.paste(crop, (thumb.width + 12, 34))
            ImageDraw.Draw(tile).text((4, 6), f"{sid} {size}: final {final.width}x{final.height}, sharp {m['sharpness']}, "
                                               f"detail {det}, ${cost:.3f}", fill=(30, 30, 40), font=font)
            tiles.append(tile)
        row = Image.new("RGB", (sum(t.width for t in tiles) + 24, max(t.height for t in tiles)), (246, 244, 239))
        x = 0
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width + 24
        rows.append(row)
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 16 for r in rows)), (246, 244, 239))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 16
    sheet.save(args.out, quality=88)
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
