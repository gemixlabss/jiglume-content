#!/usr/bin/env python3
"""Removes images from the archive: tools/remove_image.py <id> [<id> ...]"""
from __future__ import annotations

import sys

from common import ROOT, load_catalog, load_phash_index, save_catalog, save_phash_index


def main() -> None:
    ids = set(sys.argv[1:])
    cat = load_catalog()
    index = load_phash_index()
    keep = []
    for p in cat["puzzles"]:
        if p["id"] in ids:
            for rel in (p["imagePath"], p["thumbPath"]):
                (ROOT / rel).unlink(missing_ok=True)
            # Keep the hash so the same image is not re-added by a later fetch.
            print(f"removed {p['id']}")
        else:
            keep.append(p)
    cat["puzzles"] = keep
    save_catalog(cat)
    save_phash_index(index)


if __name__ == "__main__":
    main()
