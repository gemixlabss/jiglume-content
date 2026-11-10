#!/usr/bin/env python3
"""Smithsonian Open Access (api.si.edu) → inbox/. CC0 only.

An item is used only when BOTH the record (`metadata_usage.access`) and the
chosen media file (`usage.access`) say "CC0". Needs a free api.data.gov key:
read from the SI_API_KEY environment variable and sent as the X-Api-Key
header (in the cloud session a proxy injects the real key; never stored).

Usage: SI_API_KEY=... tools/fetch_smithsonian.py [--per-category 18] [--only flowers]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time

from common import category_count, review_rejected_ids, INBOX, LICENSE_URLS, http_get, http_json, load_catalog, log, looks_excluded

API = "https://api.si.edu/openaccess/api/v1.0/search"
# Each query adds `AND online_media_type:"Images"`. Units: NZP = National Zoo,
# SG = Smithsonian Gardens, NASM = Air and Space, CHNDM = Cooper Hewitt.
QUERIES = {
    "animals": ['unit_code:"NZP"', "bird photograph", "butterfly"],
    "flowers": ['unit_code:"SG" AND orchid', 'unit_code:"SG" AND flower', "botanical illustration flowers",
                'unit_code:"SIL" AND roses', 'unit_code:"SIL" AND botanical', 'unit_code:"SAAM" AND flowers'],
    "vehicles": ['unit_code:"NASM" AND aircraft', "locomotive", "automobile carriage",
                 'unit_code:"SAAM" AND ship', 'unit_code:"SAAM" AND train', "sailing ship painting"],
    "architecture": ["smithsonian castle", "building exterior photograph", "interior architecture",
                     'unit_code:"SAAM" AND cathedral', 'unit_code:"SAAM" AND church'],
    "patterns": ['unit_code:"CHNDM" AND textile', 'unit_code:"CHNDM" AND wallpaper', 'unit_code:"CHNDM" AND sidewall',
                 'unit_code:"CHNDM" AND "printed cotton"', 'unit_code:"CHNDM" AND brocade', 'unit_code:"CHNDM" AND tile'],
    "food": ["fruit painting", "still life fruit", 'unit_code:"SAAM" AND "still life"', 'unit_code:"SAAM" AND fruit'],
}


def search(q: str, start: int = 0) -> list[dict]:
    key = os.environ.get("SI_API_KEY", "")
    d = http_json(API, params={"q": f'{q} AND online_media_type:"Images"', "rows": "100", "start": str(start)},
                  headers={"X-Api-Key": key} if key else {})
    return d.get("response", {}).get("rows", [])


def _access(value) -> str | None:
    """`metadata_usage` / `usage` is an object, or sometimes a list of them."""
    if isinstance(value, dict):
        return value.get("access")
    if isinstance(value, list):
        values = {v.get("access") for v in value if isinstance(v, dict)}
        return "CC0" if values == {"CC0"} else None
    return None


def best_media(row: dict) -> tuple[str, int, int] | None:
    dnr = row.get("content", {}).get("descriptiveNonRepeating", {})
    if _access(dnr.get("metadata_usage")) != "CC0":
        return None
    for m in (dnr.get("online_media") or {}).get("media", []):
        if _access(m.get("usage")) != "CC0" or m.get("type") != "Images":
            continue
        best = None
        for r in m.get("resources", []):
            w, h = int(r.get("width") or 0), int(r.get("height") or 0)
            if r.get("url") and max(w, h) >= 2400:
                if best is None or w * h > best[1] * best[2]:
                    best = (r["url"], w, h)
        if best:
            return best
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=18)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = {c for c in args.only.split(",") if c}
    seen = {p["sourceUrl"] for p in load_catalog()["puzzles"]}
    rejected = review_rejected_ids()
    for cat_id, queries in QUERIES.items():
        if only and cat_id not in only:
            continue
        out = INBOX / cat_id
        out.mkdir(parents=True, exist_ok=True)
        seen |= {json.loads(s.read_text())["sourceUrl"] for s in out.glob("*.json")}
        have = category_count(cat_id)
        for q in queries:
            if have >= args.per_category:
                break
            log(f"[{cat_id}] si {q!r}")
            taken = 0
            for row in search(q):
                if have >= args.per_category or taken >= 6:
                    break
                try:
                    media = best_media(row)
                except (AttributeError, TypeError, ValueError):
                    continue  # unexpected record shape: skip, never guess
                if not media:
                    continue
                title = row.get("title") or "Untitled"
                if looks_excluded(title):
                    continue
                link = (row.get("content", {}).get("descriptiveNonRepeating", {}).get("record_link")
                        or f"https://collections.si.edu/search/detail/{row.get('id')}")
                if link in seen:
                    continue
                pid = f"{cat_id}-s{re.sub(r'[^a-z0-9]', '', str(row.get('id', '')).lower())[-10:]}"
                if pid in rejected:
                    continue
                url, w, h = media
                try:
                    data = http_get(url, timeout=180)
                except Exception as e:  # noqa: BLE001
                    log(f"  download failed: {e}")
                    continue
                unit = row.get("unitCode", "SI")
                (out / f"{pid}.jpg").write_bytes(data)
                meta = {"title": f"{title} (Smithsonian {unit})", "photographer": f"Smithsonian Institution ({unit})",
                        "sourceUrl": link, "license": "CC0 1.0", "licenseUrl": LICENSE_URLS["CC0 1.0"],
                        "attributionRequired": False, "origin": "smithsonian-open-access"}
                (out / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                seen.add(link)
                have += 1
                taken += 1
                log(f"  + {pid} {w}x{h} {title[:60]}")
                time.sleep(1)
        log(f"[{cat_id}] {have} in inbox")


if __name__ == "__main__":
    main()
