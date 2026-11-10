#!/usr/bin/env python3
"""Rijksmuseum (data.rijksmuseum.nl, Linked Art) → inbox/art. CC0 only.

A record is used only when its own Linked Art JSON-LD carries the CC0 rights
statement (creativecommons.org/publicdomain/zero/1.0) and an IIIF image.

Usage: tools/fetch_rijksmuseum.py [--count 12]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time

from common import review_rejected_ids, INBOX, LICENSE_URLS, http_get, http_json, load_catalog, log, looks_excluded

SEARCH = "https://data.rijksmuseum.nl/search/collection"
TERMS = ["landschap", "zeegezicht", "stilleven", "bloemen", "rivierlandschap", "wintergezicht", "stadsgezicht"]
FIGURES = re.compile(r"portret|portrait|vrouw|man |meisje|jongen|heilige|madonna|christus|naakt|self", re.I)


def record(uri: str) -> dict:
    return http_json(uri, headers={"Accept": "application/ld+json"})


def labels(node, key: str = "_label") -> list[str]:
    out = []
    if isinstance(node, dict):
        if key in node and isinstance(node[key], str):
            out.append(node[key])
        for v in node.values():
            out += labels(v, key)
    elif isinstance(node, list):
        for v in node:
            out += labels(v, key)
    return out


def title_of(rec: dict) -> str:
    for ident in rec.get("identified_by", []):
        if ident.get("type") == "Name" and ident.get("content"):
            return ident["content"]
    return rec.get("_label") or "Untitled"


def creator_of(rec: dict) -> str:
    try:
        for p in rec["produced_by"].get("part", [rec["produced_by"]]):
            for who in p.get("carried_out_by", []):
                if who.get("_label"):
                    return who["_label"]
    except (KeyError, AttributeError, TypeError):
        pass
    return "Unknown artist"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--category", default="art")
    ap.add_argument("--terms", default=",".join(TERMS), help="comma-separated Dutch search terms")
    args = ap.parse_args()
    terms = [t for t in args.terms.split(",") if t]
    out = INBOX / args.category
    out.mkdir(parents=True, exist_ok=True)
    seen = {p["sourceUrl"] for p in load_catalog()["puzzles"]}
    seen |= {json.loads(s.read_text())["sourceUrl"] for s in out.glob("*.json")}
    got = 0
    for term in terms:
        if got >= args.count:
            break
        log(f"[{args.category}] rijksmuseum {term!r}")
        d = http_json(SEARCH, params={"description": term, "imageAvailable": "true", "type": "schilderij"})
        taken = 0
        for item in d.get("orderedItems", [])[:30]:
            if got >= args.count or taken >= 3:
                break
            uri = item.get("id")
            if not uri or uri in seen:
                continue
            raw = json.dumps(rec := record(uri))
            if "publicdomain/zero/1.0" not in raw:
                continue
            m = re.search(r"https://iiif\.micr\.io/([A-Za-z0-9]+)/", raw)
            if not m:
                continue
            title = title_of(rec)
            if FIGURES.search(title) or looks_excluded(title):
                continue
            try:
                info = http_json(f"https://iiif.micr.io/{m.group(1)}/info.json")
                if max(info.get("width", 0), info.get("height", 0)) < 2400:
                    continue
                data = http_get(f"https://iiif.micr.io/{m.group(1)}/full/!3000,3000/0/default.jpg", timeout=180)
            except Exception as e:  # noqa: BLE001
                log(f"  skipped: {e}")
                continue
            pid = f"{args.category}-r{hashlib.sha1(uri.encode()).hexdigest()[:8]}"
            if pid in review_rejected_ids():
                continue
            (out / f"{pid}.jpg").write_bytes(data)
            meta = {"title": f"{title} (Rijksmuseum)", "photographer": creator_of(rec), "sourceUrl": uri,
                    "license": "CC0 1.0", "licenseUrl": LICENSE_URLS["CC0 1.0"], "attributionRequired": False,
                    "origin": "rijksmuseum"}
            (out / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            seen.add(uri)
            got += 1
            taken += 1
            log(f"  + {pid} {title[:60]} — {meta['photographer']}")
            time.sleep(1)
    log(f"[{args.category}] rijksmuseum added {got}")


if __name__ == "__main__":
    main()
