#!/usr/bin/env python3
"""Release helpers used by publish.sh.

  tools/write_manifest.py stamp v3          # set catalog contentVersion + isNew flags
  tools/write_manifest.py manifest v3 <sha> # write manifest.json for that release

* `isNew` is true for images added within the last 30 days.
* manifest.json is tiny and is the ONLY file read from a moving ref (main).
  Everything else is read from the release's **commit SHA** (`bases`), which is
  as immutable as a tag, is cached forever by jsDelivr, and works even where a
  tag cannot be pushed. The human-readable tag (`latest`) is kept alongside.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta

from common import CATALOG, MANIFEST, REPO, SCHEMA_VERSION, load_catalog, save_catalog

NEW_FOR_DAYS = 30


def stamp(version: str) -> None:
    cat = load_catalog()
    cutoff = (date.today() - timedelta(days=NEW_FOR_DAYS)).isoformat()
    for p in cat["puzzles"]:
        p["isNew"] = p["addedAt"] >= cutoff
    cat["contentVersion"] = version
    save_catalog(cat)
    print(f"catalog stamped {version}")


def manifest(version: str, ref: str) -> None:
    cat = load_catalog()
    data = {
        "schemaVersion": SCHEMA_VERSION,
        "latest": version,
        "ref": ref,
        "publishedAt": date.today().isoformat(),
        "catalog": "catalog.json",
        "catalogSha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "puzzleCount": len(cat["puzzles"]),
        # Tried in order by the app; both are immutable for a commit SHA.
        "bases": [
            f"https://cdn.jsdelivr.net/gh/{REPO}@{ref}/",
            f"https://raw.githubusercontent.com/{REPO}/{ref}/",
        ],
    }
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n")
    print(f"manifest → {version} @ {ref[:10]}, {data['puzzleCount']} puzzles")


if __name__ == "__main__":
    cmd, version = sys.argv[1], sys.argv[2]
    stamp(version) if cmd == "stamp" else manifest(version, sys.argv[3])
