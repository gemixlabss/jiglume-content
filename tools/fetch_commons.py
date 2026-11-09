#!/usr/bin/env python3
"""Fetch openly licensed photos from Wikimedia Commons into inbox/<category>/.

Licence policy (strict, read ONLY from the Commons API extmetadata —
LicenseShortName, Artist, AttributionRequired, Restrictions — never guessed):
  accept: CC0, public domain (PD-*), CC BY 2.0 / 3.0 / 4.0
  reject: any BY-SA, NC or ND variant, GFDL, fair use, unknown/empty licence,
          files with personality-rights / trademark restrictions, CC BY files
          without an author.
Also rejected: files whose title/description/categories suggest people,
logos, brands or commercial products, and files whose long side < 2400 px.

The search itself is narrowed with Commons structured data (P275 licence /
P6216 public-domain status) and the result is then re-checked as above.

Each accepted file is written as inbox/<category>/<id>.<ext> with a JSON
sidecar holding title, photographer, sourceUrl, license, licenseUrl and
attributionRequired. Run tools/add_images.py afterwards.

Usage: tools/fetch_commons.py [--per-category 20] [--only animals,nature]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
from pathlib import Path

from common import (CATEGORY_IDS, INBOX, LICENSE_URLS, ATTRIBUTION_LICENSES, ROOT, http_get, http_json,
                    load_catalog, log, looks_excluded, normalize_license, strip_html)

API = "https://commons.wikimedia.org/w/api.php"
LICENSE_FILTER = ("haswbstatement:P275=Q6938433|P275=Q20007257|P275=Q14947546|P275=Q19125117"
                  "|P6216=Q19652")
DOWNLOAD_WIDTH = 3840  # a standard Wikimedia thumbnail step; originals are often 6000+ px
MIN_SOURCE_LONG_SIDE = 2400


def search(term: str, quality_only: bool, limit: int = 50) -> list[dict]:
    q = f"{term} filetype:bitmap filew:>{MIN_SOURCE_LONG_SIDE - 1} {LICENSE_FILTER}"
    if quality_only:
        q += ' incategory:"Quality images"'
    for attempt in range(8):
        data = _query(q, limit)
        err = data.get("error")
        if not err:
            break
        # MediaWiki reports rate limiting / lag as HTTP 200 + an error object.
        log(f"  API error {err.get('code')}: waiting {30 * (attempt + 1)}s")
        time.sleep(30 * (attempt + 1))
    else:
        raise RuntimeError(f"search kept failing: {err}")
    pages = list((data.get("query") or {}).get("pages", {}).values())
    pages.sort(key=lambda p: p.get("index", 0))
    return pages


def _query(q: str, limit: int) -> dict:
    return http_json(API, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": q, "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(DOWNLOAD_WIDTH),
        "iiextmetadatafilter": "LicenseShortName|AttributionRequired|Artist|ImageDescription"
                               "|ObjectName|Categories|Restrictions|UsageTerms",
    })


def evaluate(page: dict) -> tuple[dict | None, str]:
    """Returns (metadata, '') when acceptable, else (None, reason)."""
    ii = (page.get("imageinfo") or [{}])[0]
    meta = ii.get("extmetadata") or {}
    get = lambda k: (meta.get(k) or {}).get("value", "")  # noqa: E731
    if ii.get("mime") not in ("image/jpeg", "image/png", "image/tiff", "image/webp"):
        return None, f"mime {ii.get('mime')}"
    if max(ii.get("width", 0), ii.get("height", 0)) < MIN_SOURCE_LONG_SIDE:
        return None, "too small"
    lic = normalize_license(get("LicenseShortName"))
    if lic is None:
        return None, f"licence {get('LicenseShortName')!r}"
    restrictions = strip_html(get("Restrictions"))
    if restrictions:
        return None, f"restrictions {restrictions!r}"
    artist = strip_html(get("Artist"))
    attribution = str(get("AttributionRequired")).lower() == "true" or lic in ATTRIBUTION_LICENSES
    if lic in ATTRIBUTION_LICENSES and not artist:
        return None, "CC BY without author"
    title = page["title"].removeprefix("File:").rsplit(".", 1)[0]
    hit = looks_excluded(title, strip_html(get("ImageDescription")), get("Categories"))
    if not hit and any(w in (title + " " + get("Categories")).lower()
                       for w in ("portrait", "madonna", "saint ", "nude", "self-portrait")):
        hit = "figure painting"
    if hit:
        return None, f"content filter {hit!r}"
    w, h = ii["width"], ii["height"]
    if max(w, h) / min(w, h) > 2.4:
        return None, "panorama aspect"
    return {
        "title": strip_html(get("ObjectName")) or title,
        "photographer": artist or "Unknown",
        "sourceUrl": ii.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{page['title']}",
        "license": lic,
        "licenseUrl": LICENSE_URLS[lic],
        "attributionRequired": attribution,
        "origin": "wikimedia-commons",
        "_download": ii.get("thumburl") or ii["url"],
    }, ""


def existing_sources() -> set[str]:
    cat = load_catalog()
    seen = {p["sourceUrl"] for p in cat["puzzles"]}
    for side in INBOX.glob("*/*.json"):
        seen.add(json.loads(side.read_text())["sourceUrl"])
    return seen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=20)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    terms = json.loads((ROOT / "tools" / "sources.json").read_text())
    only = {c for c in args.only.split(",") if c}
    seen = existing_sources()
    report: dict[str, dict] = {}

    for cat_id, cat_terms in terms.items():
        if cat_id.startswith("_") or (only and cat_id not in only) or (not only and cat_id == "art"):
            continue
        assert cat_id in CATEGORY_IDS, cat_id
        out = INBOX / cat_id
        out.mkdir(parents=True, exist_ok=True)
        have = len(list(out.glob("*.json")))
        per_artist: dict[str, int] = {}
        for side in out.glob("*.json"):
            a = json.loads(side.read_text())["photographer"]
            per_artist[a] = per_artist.get(a, 0) + 1
        stats = report.setdefault(cat_id, {"accepted": 0, "rejected": {}})
        # One OR-query per pass keeps API calls (the rate-limited part) low:
        # first among Commons "Quality images", then in general.
        # Single words only: quoted phrases inside an OR group return nothing.
        query = " OR ".join(t for t in cat_terms if " " not in t)
        for quality_only in (True, False):
            if have >= args.per_category:
                break
            log(f"[{cat_id}] search ({query}) quality_only={quality_only}")
            try:
                pages = search(f"({query})", quality_only)
            except Exception as e:  # noqa: BLE001
                log(f"  search failed: {e}")
                continue
            if not pages:
                log("  no results")
            for page in pages:
                if have >= args.per_category:
                    break
                meta, why = evaluate(page)
                if meta is None:
                    key = why.split(" ")[0]
                    stats["rejected"][key] = stats["rejected"].get(key, 0) + 1
                    continue
                if meta["sourceUrl"] in seen:
                    continue
                # Variety: at most 3 images per photographer per category.
                if per_artist.get(meta["photographer"], 0) >= 3:
                    continue
                pid = f"{cat_id}-{hashlib.sha1(meta['sourceUrl'].encode()).hexdigest()[:8]}"
                url = meta.pop("_download")
                ext = Path(urllib.parse.urlparse(url).path).suffix.lstrip(".").lower() or "jpg"
                try:
                    data = http_get(url, timeout=120)
                except Exception as e:  # noqa: BLE001
                    log(f"  download failed {url}: {e}")
                    continue
                (out / f"{pid}.{ext}").write_bytes(data)
                (out / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                seen.add(meta["sourceUrl"])
                per_artist[meta["photographer"]] = per_artist.get(meta["photographer"], 0) + 1
                have += 1
                stats["accepted"] += 1
                log(f"  + {pid} [{meta['license']}] {meta['title'][:60]}")
                time.sleep(12)  # be gentle: upload.wikimedia.org rate-limits shared IPs hard
            log(f"  pass stats: {stats}")
            time.sleep(3)
        log(f"[{cat_id}] {have} in inbox")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
