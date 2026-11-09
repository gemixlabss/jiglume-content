#!/usr/bin/env python3
"""Stamps catalog.json with a content version and writes manifest.json.

  tools/write_manifest.py v3

* `isNew` is true for images added within the last 30 days.
* manifest.json is tiny and is the ONLY file read from a moving ref (main);
  everything else is read from the immutable tag (`bases`).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta

from common import CATALOG, MANIFEST, REPO, SCHEMA_VERSION, load_catalog, save_catalog

NEW_FOR_DAYS = 30


def main() -> None:
    version = sys.argv[1]
    cat = load_catalog()
    cutoff = (date.today() - timedelta(days=NEW_FOR_DAYS)).isoformat()
    for p in cat["puzzles"]:
        p["isNew"] = p["addedAt"] >= cutoff
    cat["contentVersion"] = version
    save_catalog(cat)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "latest": version,
        "publishedAt": date.today().isoformat(),
        "catalog": "catalog.json",
        "catalogSha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "puzzleCount": len(cat["puzzles"]),
        # Tried in order by the app; both are immutable per tag.
        "bases": [
            f"https://cdn.jsdelivr.net/gh/{REPO}@{version}/",
            f"https://raw.githubusercontent.com/{REPO}/{version}/",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest → {version}, {manifest['puzzleCount']} puzzles")


if __name__ == "__main__":
    main()
