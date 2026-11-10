#!/usr/bin/env python3
"""NASA Image and Video Library (images-api.nasa.gov) → inbox/.

NASA imagery is generally not copyrighted (public domain). The licence is
decided from each item's own metadata: items whose description, title,
photographer or secondary creator credit a third party (ESA, ©, "courtesy",
agencies, universities, news agencies…) are rejected, as are items showing
logos/insignia/patches or featuring people (astronaut portraits, crews).

Usage: tools/fetch_nasa.py [--per-category 18] [--only night,sea]
"""
from __future__ import annotations

import argparse
import json
import re
import time

from common import category_count, review_rejected_ids, INBOX, http_get, http_json, load_catalog, log, looks_excluded

API = "https://images-api.nasa.gov"
LICENSE = "Public domain"
LICENSE_URL = "https://www.nasa.gov/nasa-brand-center/images-and-media/"

QUERIES = {
    "cities": ["city lights at night iss", "earth observation city night", "metropolitan area at night from space"],
    "night": ["nebula", "galaxy", "aurora iss", "milky way", "star cluster", "city lights at night iss",
              "spitzer infrared nebula", "wise infrared sky", "supernova remnant"],
    "sea": ["bahamas from space", "coral reef from space", "coastline astronaut photograph", "ocean color phytoplankton bloom"],
    "mountains": ["himalayas astronaut photograph", "andes from space", "volcano from space"],
    "nature": ["earth observatory river delta", "sand dunes from space", "glacier landsat"],
}
THIRD_PARTY = re.compile(
    r"©|copyright|courtesy|\besa\b|getty|reuters|associated press|\bap photo|afp|"
    r"university|observatory credit|jaxa|roscosmos|csa\b|eso\b|noirlab|spacex|boeing|lockheed|"
    r"all rights reserved|used with permission", re.I)
NO_GO = re.compile(
    r"logo|insignia|patch|emblem|portrait|crew|astronaut .* (smiles|poses)|selfie|headshot|"
    r"ceremony|press conference|mission control|official photo|people|students|team", re.I)


def items(query: str, page: int = 1) -> list[dict]:
    d = http_json(f"{API}/search", params={"q": query, "media_type": "image", "page": str(page), "page_size": "60"})
    return d.get("collection", {}).get("items", [])


def orig_url(nasa_id: str) -> str | None:
    d = http_json(f"{API}/asset/{nasa_id}")
    hrefs = [i["href"] for i in d.get("collection", {}).get("items", [])]
    for suffix in ("~orig.jpg", "~large.jpg"):
        for h in hrefs:
            if h.endswith(suffix):
                return h.replace("http://", "https://")
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
            taken = 0
            if have >= args.per_category:
                break
            log(f"[{cat_id}] nasa {q!r}")
            for it in items(q):
                if have >= args.per_category or taken >= 4:
                    break
                d = it["data"][0]
                text = " ".join(str(d.get(k, "")) for k in ("title", "description", "photographer", "secondary_creator", "keywords"))
                if THIRD_PARTY.search(text) or NO_GO.search(text) or looks_excluded(d.get("title", ""), " ".join(d.get("keywords", []))):
                    continue
                nid = d["nasa_id"]
                src = f"https://images.nasa.gov/details/{nid}"
                if src in seen:
                    continue
                pid = f"{cat_id}-n{re.sub(r'[^a-z0-9]', '', nid.lower())[-10:]}"
                if pid in rejected:
                    continue
                url = orig_url(nid)
                if not url:
                    continue
                try:
                    data = http_get(url, timeout=180)
                except Exception as e:  # noqa: BLE001
                    log(f"  download failed: {e}")
                    continue
                if len(data) < 300_000:  # tiny originals are never ≥ 2000 px of real detail
                    continue
                (out / f"{pid}.jpg").write_bytes(data)
                meta = {"title": d.get("title", nid), "photographer": d.get("photographer") or f"NASA ({d.get('center', 'NASA')})",
                        "sourceUrl": src, "license": LICENSE, "licenseUrl": LICENSE_URL,
                        "attributionRequired": False, "origin": "nasa"}
                (out / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                seen.add(src)
                have += 1
                taken += 1
                log(f"  + {pid} {meta['title'][:60]}")
                time.sleep(1)
        log(f"[{cat_id}] {have} in inbox")


if __name__ == "__main__":
    main()
