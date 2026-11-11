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

from common import (category_count, review_rejected_ids, CATEGORY_IDS, INBOX, LICENSE_URLS, ATTRIBUTION_LICENSES, ROOT, http_get, http_json,
                    load_catalog, log, looks_excluded, normalize_license, strip_html)

API = "https://commons.wikimedia.org/w/api.php"
LICENSE_FILTER = ("haswbstatement:P275=Q6938433|P275=Q20007257|P275=Q14947546|P275=Q19125117"
                  "|P6216=Q19652")
DOWNLOAD_WIDTH = 3840  # a standard Wikimedia thumbnail step; originals are often 6000+ px
MIN_SOURCE_LONG_SIDE = 2400


EXTRA_QUERY = ""  # e.g. 'hastemplate:"PD-USGov-NPS"' (set by --extra-query)


FEATURED = 'incategory:"Featured_pictures_on_Wikimedia_Commons"'
QUALITY = 'incategory:"Quality_images"'


def search(term: str, quality_only: bool | str, limit: int = 50) -> list[dict]:
    """quality_only: False (all files), True (Quality images) or a raw
    incategory: filter (e.g. FEATURED)."""
    lic = EXTRA_QUERY or LICENSE_FILTER
    q = f"{term} filetype:bitmap filew:>{MIN_SOURCE_LONG_SIDE - 1} {lic}"
    if isinstance(quality_only, str):
        q += " " + quality_only
    elif quality_only:
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
    # Must stay sharp at 1000 pieces after the app's fill crop.
    from upgrade_resolution import passes, stored_size
    sw, _ = stored_size(w, h)
    if not passes(*stored_size(w, h)):
        return None, "too small for 1000 pieces"
    name = page["title"].removeprefix("File:")
    # commons.wikimedia.org/w/thumb.php renders any size; upload.wikimedia.org
    # throttles shared cloud IPs.
    download = "https://commons.wikimedia.org/w/thumb.php?" + urllib.parse.urlencode({"f": name, "w": sw})
    return {
        "title": strip_html(get("ObjectName")) or title,
        "photographer": artist or "Unknown",
        "sourceUrl": ii.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{page['title']}",
        "license": lic,
        "licenseUrl": LICENSE_URLS[lic],
        "attributionRequired": attribution,
        "origin": "wikimedia-commons",
        "_download": download,
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
    ap.add_argument("--terms", default="sources.json", help="terms file in tools/")
    ap.add_argument("--extra-query", default="",
                    help='replaces the licence pre-filter, e.g. hastemplate:"PD-USGov-NPS" '
                         '(the licence is still verified from extmetadata)')
    ap.add_argument("--no-quality-pass", action="store_true")
    ap.add_argument("--featured", action="store_true",
                    help="search only Commons Featured pictures, then Quality images (v4); "
                         "include art; reject dull downloads (tools/vividness.py)")
    ap.add_argument("--width", type=int, default=DOWNLOAD_WIDTH,
                    help="thumbnail width to download (1920 is a cached Wikimedia step; 3840 may be throttled)")
    ap.add_argument("--per-term", action="store_true",
                    help="one search per term (more relevant than one OR-query), at most 3 images per term")
    ap.add_argument("--targets", default="", help='JSON {category: target count} overriding --per-category')
    ap.add_argument("--have", default="",
                    help="JSON {category: count} overriding the catalog counts (e.g. after pruning)")
    args = ap.parse_args()
    have_override = json.loads(args.have) if args.have else {}
    targets = json.loads(args.targets) if args.targets else {}
    globals()["DOWNLOAD_WIDTH"] = args.width
    global EXTRA_QUERY
    EXTRA_QUERY = args.extra_query
    terms = json.loads((ROOT / "tools" / args.terms).read_text())
    only = {c for c in args.only.split(",") if c}
    seen = existing_sources()
    rejected = review_rejected_ids()
    report: dict[str, dict] = {}

    for cat_id, cat_terms in terms.items():
        if cat_id.startswith("_") or (only and cat_id not in only) or (not only and cat_id == "art" and not args.featured):
            continue
        assert cat_id in CATEGORY_IDS, cat_id
        out = INBOX / cat_id
        out.mkdir(parents=True, exist_ok=True)
        have = have_override.get(cat_id, category_count(cat_id)) + len(list(out.glob("*.json")))
        per_artist: dict[str, int] = {}
        for side in out.glob("*.json"):
            a = json.loads(side.read_text())["photographer"]
            per_artist[a] = per_artist.get(a, 0) + 1
        stats = report.setdefault(cat_id, {"accepted": 0, "rejected": {}})
        target = targets.get(cat_id, args.per_category)
        if only and targets and cat_id not in targets:
            continue
        # One OR-query per pass keeps API calls (the rate-limited part) low:
        # first among Commons "Quality images", then in general.
        # Single words only: quoted phrases inside an OR group return nothing.
        query = " OR ".join(t for t in cat_terms if " " not in t)
        passes = (FEATURED, QUALITY) if args.featured else ((False,) if args.no_quality_pass else (True, False))
        jobs = [(f"({query})", q) for q in passes]
        if args.per_term:
            jobs = [(t, q) for t in cat_terms for q in passes]
        per_term_taken: dict[str, int] = {}
        for term_query, quality_only in jobs:
            if have >= target:
                break
            if per_term_taken.get(term_query, 0) >= 3:
                continue
            log(f"[{cat_id}] search ({term_query}) quality_only={quality_only}")
            try:
                pages = search(term_query, quality_only, limit=20 if args.per_term else 50)
            except Exception as e:  # noqa: BLE001
                log(f"  search failed: {e}")
                continue
            if not pages:
                log("  no results")
            for page in pages:
                if have >= target or per_term_taken.get(term_query, 0) >= 3:
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
                if pid in rejected:
                    continue
                url = meta.pop("_download")
                ext = "jpg"
                try:
                    data = http_get(url, timeout=120)
                except Exception as e:  # noqa: BLE001
                    log(f"  download failed {url}: {e}")
                    continue
                if args.featured:
                    from io import BytesIO

                    from PIL import Image
                    from vividness import dull_reason, metrics
                    try:
                        m = metrics(Image.open(BytesIO(data)))
                    except Exception as e:  # noqa: BLE001
                        log(f"  unreadable {url}: {e}")
                        continue
                    dull = dull_reason(m, category=cat_id)
                    if dull:
                        stats["rejected"]["dull"] = stats["rejected"].get("dull", 0) + 1
                        log(f"  - dull {pid}: {dull}")
                        seen.add(meta["sourceUrl"])
                        continue
                (out / f"{pid}.{ext}").write_bytes(data)
                (out / f"{pid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                seen.add(meta["sourceUrl"])
                per_artist[meta["photographer"]] = per_artist.get(meta["photographer"], 0) + 1
                have += 1
                per_term_taken[term_query] = per_term_taken.get(term_query, 0) + 1
                stats["accepted"] += 1
                log(f"  + {pid} [{meta['license']}] {meta['title'][:60]}")
                time.sleep(4 if args.width <= 1920 else 12)  # be gentle with upload.wikimedia.org
            log(f"  pass stats: {stats}")
            time.sleep(3)
        log(f"[{cat_id}] {have} in inbox")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
