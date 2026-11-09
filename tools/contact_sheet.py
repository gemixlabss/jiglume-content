#!/usr/bin/env python3
"""Renders review/sheet_NN.jpg contact sheets (id-labelled thumbnails) for a
manual check of every image before publishing: no recognisable people, no
prominent logos/brands/products.

Usage: tools/contact_sheet.py [--inbox] [--cols 5 --rows 4]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import INBOX, ROOT, load_catalog
from imaging import open_upright

CELL = 300


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", action="store_true", help="review inbox/ instead of the catalog")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--rows", type=int, default=4)
    args = ap.parse_args()
    if args.inbox:
        items = [(p.stem, p) for p in sorted(INBOX.rglob("*")) if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".tif")]
    else:
        items = [(p["id"], ROOT / p["thumbPath"]) for p in load_catalog()["puzzles"]]
    out = ROOT / "review"
    out.mkdir(exist_ok=True)
    for old in out.glob("sheet_*.jpg"):
        old.unlink()
    per = args.cols * args.rows
    font = ImageFont.load_default(size=16)
    for s in range(0, len(items), per):
        sheet = Image.new("RGB", (args.cols * CELL, args.rows * (CELL + 24)), (20, 18, 40))
        draw = ImageDraw.Draw(sheet)
        for i, (pid, path) in enumerate(items[s:s + per]):
            img = open_upright(path)
            img.thumbnail((CELL - 8, CELL - 8))
            x = (i % args.cols) * CELL
            y = (i // args.cols) * (CELL + 24)
            sheet.paste(img, (x + (CELL - img.width) // 2, y + (CELL - img.height) // 2))
            draw.text((x + 6, y + CELL + 2), pid, fill=(232, 182, 90), font=font)
        sheet.save(out / f"sheet_{s // per:02d}.jpg", quality=80)
    print(f"{len(items)} images → {out}")


if __name__ == "__main__":
    main()
