#!/usr/bin/env python3
"""Validates catalog.json against the schema and the files on disk."""
from __future__ import annotations

import re
import sys

from common import (CATEGORY_IDS, LICENSE_URLS, MIN_LONG_SIDE, ROOT, SCHEMA_VERSION, ATTRIBUTION_LICENSES,
                    load_catalog)

FIELDS = {"id": str, "categoryId": str, "title": str, "imagePath": str, "thumbPath": str, "width": int,
          "height": int, "dominantColor": str, "photographer": str, "sourceUrl": str, "license": str,
          "licenseUrl": str, "attributionRequired": bool, "addedAt": str, "isNew": bool, "tier": str}
TIERS = {"free", "premium"}


def main() -> int:
    cat = load_catalog()
    errors = []
    if cat.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("schemaVersion mismatch")
    ids = set()
    for p in cat["puzzles"]:
        pid = p.get("id", "?")
        for k, t in FIELDS.items():
            if not isinstance(p.get(k), t):
                errors.append(f"{pid}: field {k} missing or not {t.__name__}")
        if pid in ids:
            errors.append(f"{pid}: duplicate id")
        ids.add(pid)
        if p.get("categoryId") not in CATEGORY_IDS:
            errors.append(f"{pid}: unknown category")
        if p.get("license") not in LICENSE_URLS:
            errors.append(f"{pid}: licence {p.get('license')!r} not allowed")
        if p.get("license") in ATTRIBUTION_LICENSES and (not p.get("attributionRequired")
                                                        or p.get("photographer") in ("", "Unknown")):
            errors.append(f"{pid}: CC BY needs attribution data")
        if p.get("tier") not in TIERS:
            errors.append(f"{pid}: tier must be free or premium")
        if not re.fullmatch(r"#[0-9a-f]{6}", p.get("dominantColor", "")):
            errors.append(f"{pid}: bad dominantColor")
        if max(p.get("width", 0), p.get("height", 0)) < MIN_LONG_SIDE:
            errors.append(f"{pid}: smaller than {MIN_LONG_SIDE}px")
        for rel in (p.get("imagePath", ""), p.get("thumbPath", "")):
            if not (ROOT / rel).is_file():
                errors.append(f"{pid}: missing file {rel}")
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    print(f"{len(cat['puzzles'])} puzzles, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
