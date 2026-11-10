#!/usr/bin/env python3
"""Fetch CC0 open-access paintings for the "art" category.

Source: The Met Open Access (CC0). An object is used only when the object API
itself reports isPublicDomain == true and has a primary image.

Not used (see README): the Art Institute of Chicago's image server sits behind
a bot challenge for scripted clients, and the Rijksmuseum API needs a key.

Portraits and figure scenes are skipped (title filter); landscapes,
seascapes, still lifes and flowers are searched for. Writes
inbox/art/<id>.jpg + JSON sidecar, like fetch_commons.py.

Usage: tools/fetch_museums.py [--count 20]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time

from common import review_rejected_ids, INBOX, LICENSE_URLS, http_get, http_json, load_catalog, log, looks_excluded

TERMS = ["landscape", "seascape", "still life", "flowers", "river", "garden", "harbor",
         "mountains", "forest", "snow", "sunset", "boats"]
DEPARTMENTS = ["11", "21"]  # European Paintings, Modern and Contemporary Art (PD works only)
FIGURE_WORDS = ["portrait", "woman", "man ", "girl", "boy", "lady", "madame", "madonna", "saint",
                "christ", "virgin", "nude", "bather", "family", "child", "head of", "mrs.", "mr.",
                "monsieur", "dancer", "nymph", "venus", "mother", "self-"]


def met(term: str, department: str) -> list[dict]:
    d = http_json("https://collectionapi.metmuseum.org/public/collection/v1.1/search", params={
        "q": term, "isPublicDomain": "true", "hasImages": "true", "departmentId": department, "limit": "40"})
    out = []
    for oid in (d.get("objectIDs") or [])[:30]:
        o = http_json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}")
        time.sleep(1.5)  # gentle: the Met API sits behind a bot-protection rate limiter
        if not (o.get("isPublicDomain") is True and o.get("primaryImage") and o.get("classification") == "Paintings"):
            continue
        out.append({
            "title": o.get("title") or "Untitled",
            "photographer": o.get("artistDisplayName") or "Unknown artist",
            "sourceUrl": o.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{oid}",
            "_download": o["primaryImage"],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--category", default="art")
    ap.add_argument("--terms", default=",".join(TERMS))
    args = ap.parse_args()
    terms = [t for t in args.terms.split(",") if t]
    out_dir = INBOX / args.category
    out_dir.mkdir(parents=True, exist_ok=True)
    seen = {p["sourceUrl"] for p in load_catalog()["puzzles"]}
    seen |= {json.loads(s.read_text())["sourceUrl"] for s in INBOX.glob("*/*.json")}
    have = len(list(out_dir.glob("*.json")))
    per_artist: dict[str, int] = {}
    for term in terms:
        for dep in DEPARTMENTS:
            if have >= args.count:
                break
            log(f"[{args.category}] met {term!r} dept {dep}")
            try:
                items = met(term, dep)
            except Exception as e:  # noqa: BLE001
                log(f"  failed: {e}")
                continue
            taken = 0
            for it in items:
                if have >= args.count or taken >= 3:
                    break
                title = it["title"].lower() + " "
                if it["sourceUrl"] in seen or per_artist.get(it["photographer"], 0) >= 2:
                    continue
                if looks_excluded(it["title"]) or any(w in title for w in FIGURE_WORDS):
                    continue
                try:
                    data = http_get(it.pop("_download"), timeout=180)
                except Exception as e:  # noqa: BLE001
                    log(f"  download failed: {e}")
                    continue
                pid = f"{args.category}-{hashlib.sha1(it['sourceUrl'].encode()).hexdigest()[:8]}"
                if pid in review_rejected_ids():
                    continue
                meta = {**it, "title": f"{it['title']} (The Met)", "license": "CC0 1.0",
                        "licenseUrl": LICENSE_URLS["CC0 1.0"], "attributionRequired": False,
                        "origin": "met-open-access"}
                (out_dir / f"{pid}.jpg").write_bytes(data)
                (out_dir / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                seen.add(meta["sourceUrl"])
                per_artist[meta["photographer"]] = per_artist.get(meta["photographer"], 0) + 1
                have += 1
                taken += 1
                log(f"  + {pid} {meta['title'][:70]} — {meta['photographer']}")
    log(f"[{args.category}] {have} in inbox")


if __name__ == "__main__":
    main()
