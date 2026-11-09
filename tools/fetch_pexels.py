#!/usr/bin/env python3
"""Fetch landscape, high-resolution photos from Pexels (Pexels License).

Needs the PEXELS_API_KEY environment variable. The key is read from the
environment only — it is never written to any file, log or commit. Without
it this step is skipped (exit code 0) so publish.sh keeps working.

Usage: PEXELS_API_KEY=... tools/fetch_pexels.py [--per-category 10]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from common import INBOX, LICENSE_URLS, ROOT, http_get, http_json, load_catalog, log, looks_excluded


def main() -> int:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        log("PEXELS_API_KEY is not set — skipping Pexels.")
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=10)
    args = ap.parse_args()
    terms = json.loads((ROOT / "tools" / "sources.json").read_text())
    seen = {p["sourceUrl"] for p in load_catalog()["puzzles"]}
    headers = {"Authorization": key}
    for cat_id, cat_terms in terms.items():
        if cat_id.startswith("_"):
            continue
        out = INBOX / cat_id
        out.mkdir(parents=True, exist_ok=True)
        got = 0
        for term in cat_terms:
            if got >= args.per_category:
                break
            d = http_json("https://api.pexels.com/v1/search", headers=headers,
                          params={"query": term, "orientation": "landscape", "size": "large", "per_page": "30"})
            for ph in d.get("photos", []):
                if got >= args.per_category:
                    break
                if ph["url"] in seen or max(ph["width"], ph["height"]) < 2400:
                    continue
                if looks_excluded(ph.get("alt") or "", ph["url"]):
                    continue
                pid = f"{cat_id}-px{ph['id']}"
                (out / f"{pid}.jpg").write_bytes(http_get(ph["src"]["original"], timeout=180))
                meta = {"title": ph.get("alt") or term.title(), "photographer": ph["photographer"],
                        "sourceUrl": ph["url"], "license": "Pexels License",
                        "licenseUrl": LICENSE_URLS["Pexels License"], "attributionRequired": False,
                        "origin": "pexels"}
                (out / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                seen.add(ph["url"])
                got += 1
                log(f"  + {pid} {meta['photographer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
