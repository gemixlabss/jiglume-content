#!/usr/bin/env python3
"""Builds catalog v5 from the processed AI illustrations (ai/staging/*.json).

* categories: tools/common.py CATEGORIES (20 languages); event categories
  (winter_tale, valentine, spring_festival) are listed by the app only
  between `start` and `end`;
* display titles: ai/titles_i18n.json (20 languages) as the shared `titles`
  table, `titleKey` = scene id;
* tiers: per category ~60 % free / ~40 % premium — the most striking (appeal)
  pictures are premium, except the starter-pack picks, which stay free;
* `legacy.bases`: the v4.1 archive on the CDN, so saved games on photos that
  v5 no longer lists keep opening in the app;
* the photo archive (images of v1–v4.1) leaves the working tree (it stays in
  git history and at the v4.1 commit on the CDN); LICENSES.md is rewritten.

    tools/build_v5.py --check           # report only
    tools/build_v5.py                   # write catalog.json, LICENSES.md, remove old files
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CATEGORIES, EVENT_CATEGORIES, LICENSE_URLS, ROOT, SCHEMA_VERSION, cell_pixels  # noqa: E402

STAGING = ROOT / "ai" / "staging"
TITLES = ROOT / "ai" / "titles_i18n.json"
LANGS = ["en", "tr", "de", "fr", "es", "pt-BR", "it", "ru", "ar", "ja", "ko", "zh-Hans", "hi", "id", "nl", "pl",
         "uk", "vi", "th", "sv"]
PREMIUM_SHARE = 0.40
STARTER_COUNT = 12
LEGACY_REF = "052b840bdae36bbb94e99d2cddb2aebc3da9a682"  # content v4.1
LEGACY_BASES = [f"https://cdn.jsdelivr.net/gh/gemixlabss/jiglume-content@{LEGACY_REF}/",
                f"https://raw.githubusercontent.com/gemixlabss/jiglume-content/{LEGACY_REF}/"]
# Listed by the app only between start and end (month-day, may wrap New Year);
# testers can show them all with the hidden settings option.
EVENTS = [{"id": "winter_tale", "categoryId": "winter_tale", "start": "12-01", "end": "01-15"},
          {"id": "valentine", "categoryId": "valentine", "start": "02-01", "end": "02-15"},
          {"id": "spring_festival", "categoryId": "spring_festival", "start": "04-01", "end": "04-30"}]
PROMPTS_URL = "https://github.com/gemixlabss/jiglume-content/blob/main/ai/prompts.yaml"


def load_staged(allow_unreviewed: bool) -> tuple[list[dict], list[str]]:
    puzzles, problems = [], []
    for f in sorted(STAGING.glob("*.json")):
        for p in json.loads(f.read_text()).values():
            if not p.get("reviewed", False) and not allow_unreviewed:
                problems.append(f"{p['id']}: vision review pending")
            puzzles.append(p)
    return puzzles, problems


def pick_starters(by_cat: dict[str, list[dict]]) -> list[str]:
    """Best picture of each everyday category, most striking first."""
    best = sorted((max(ps, key=lambda p: p["appeal"]) for c, ps in by_cat.items() if c not in EVENT_CATEGORIES),
                  key=lambda p: -p["appeal"])
    return [p["id"] for p in best[:STARTER_COUNT]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--allow-unreviewed", action="store_true")
    ap.add_argument("--min-per-category", type=int, default=20)
    args = ap.parse_args()

    staged, problems = load_staged(args.allow_unreviewed)
    titles = json.loads(TITLES.read_text()) if TITLES.exists() else {}
    by_cat: dict[str, list[dict]] = {}
    for p in staged:
        by_cat.setdefault(p["categoryId"], []).append(p)
    for c in CATEGORIES:
        n = len(by_cat.get(c["id"], []))
        need = 15 if c["id"] in EVENT_CATEGORIES else args.min_per_category
        if n < need:
            problems.append(f"{c['id']}: only {n} pictures (< {need})")
    starters = set(pick_starters(by_cat))

    today = date.today().isoformat()
    puzzles = []
    for c in CATEGORIES:
        ps = sorted(by_cat.get(c["id"], []), key=lambda p: -p["appeal"])
        n_premium = math.floor(len(ps) * PREMIUM_SHARE + 0.5)
        premium = [p["id"] for p in ps if p["id"] not in starters][:n_premium]
        for p in sorted(ps, key=lambda p: p["id"]):
            t = titles.get(p["id"])
            if not t or any(not t.get(lang) for lang in LANGS):
                problems.append(f"{p['id']}: display title missing in some languages")
            if cell_pixels(p["width"], p["height"]) < 60:
                problems.append(f"{p['id']}: too small for 1000 pieces")
            for rel in (p["imagePath"], p["thumbPath"]):
                if not (ROOT / rel).is_file():
                    problems.append(f"{p['id']}: missing {rel}")
            puzzles.append({
                "id": p["id"], "categoryId": p["categoryId"], "title": p["title"], "titleKey": p["id"],
                "imagePath": p["imagePath"], "thumbPath": p["thumbPath"],
                "width": p["width"], "height": p["height"], "dominantColor": p["dominantColor"],
                "photographer": "Jiglume", "sourceUrl": PROMPTS_URL, "license": "Jiglume",
                "licenseUrl": LICENSE_URLS["Jiglume"], "attributionRequired": False,
                "addedAt": today, "isNew": True, "tier": "premium" if p["id"] in premium else "free",
                "appeal": p["appeal"], "quality": p["quality"], "modified": False,
                "source": "ai-generated", "model": p["model"], "prompt": p["scenePrompt"],
                "palette": p.get("palette"), "generatedAt": p["generatedAt"],
            })

    catalog = {
        "schemaVersion": SCHEMA_VERSION, "contentVersion": None, "generatedAt": today,
        "categories": [{**c, "l10nKey": f"category_{c['id']}"} for c in CATEGORIES],
        "events": EVENTS,
        "legacy": {"bases": LEGACY_BASES, "note": "photo archive v1–v4.1 (saved games only)"},
        "titles": {p["id"]: titles[p["id"]] for p in puzzles if p["id"] in titles},
        "starters": sorted(starters),
        "puzzles": puzzles,
    }
    counts = {c["id"]: sum(1 for p in puzzles if p["categoryId"] == c["id"]) for c in CATEGORIES}
    tiers = {t: sum(1 for p in puzzles if p["tier"] == t) for t in ("free", "premium")}
    print(json.dumps({"puzzles": len(puzzles), "tiers": tiers, "perCategory": counts,
                      "starters": sorted(starters), "problems": problems[:40], "problemCount": len(problems)},
                     ensure_ascii=False, indent=1))
    if args.check or problems:
        return 1 if problems else 0

    (ROOT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_licenses(puzzles)
    remove_legacy_files({p["imagePath"] for p in puzzles} | {p["thumbPath"] for p in puzzles})
    return 0


def write_licenses(puzzles: list[dict]) -> None:
    old = (ROOT / "LICENSES.md").read_text(encoding="utf-8") if (ROOT / "LICENSES.md").exists() else ""
    if "# Archive (photo catalog v1–v4.1)" in old:
        old = old.split("# Archive (photo catalog v1–v4.1)", 1)[1]
    models = sorted({p["model"] for p in puzzles})
    lines = [
        "# Licences", "",
        "## Jiglume illustrations (catalog v5+)", "",
        f"All {len(puzzles)} pictures in the current catalog are original illustrations generated for Jiglume with "
        f"Google's Gemini image model ({', '.join(models)}) from Jiglume's own prompts "
        "([ai/prompts.yaml](ai/prompts.yaml)). They belong to Jiglume; every picture carries Google's invisible "
        "SynthID watermark. They contain no third-party photographs, artworks, brands or characters.", "",
        "| Category | Pictures |", "|---|---|",
    ]
    for c in CATEGORIES:
        n = sum(1 for p in puzzles if p["categoryId"] == c["id"])
        lines.append(f"| {c['names']['en']} | {n} |")
    lines += ["", "---", "", "# Archive (photo catalog v1–v4.1)", "",
              "These images are no longer in the catalog. They remain in the repository history and at commit "
              f"`{LEGACY_REF}` (CDN) so that saved games keep working. Their original licences and credits:", ""]
    (ROOT / "LICENSES.md").write_text("\n".join(lines) + old.lstrip("\n"), encoding="utf-8")


def remove_legacy_files(keep: set[str]) -> None:
    removed = 0
    for folder in ("images", "thumbs"):
        for f in (ROOT / folder).rglob("*.webp"):
            rel = str(f.relative_to(ROOT))
            if rel not in keep:
                subprocess.run(["git", "rm", "-q", "--cached", "--ignore-unmatch", rel], cwd=ROOT, check=False)
                f.unlink()
                removed += 1
    for d in sorted((ROOT / "images").iterdir()):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    print(f"removed {removed} legacy files from the working tree")


if __name__ == "__main__":
    sys.exit(main())
