#!/usr/bin/env python3
"""Regenerates LICENSES.md from catalog.json (one row per image)."""
from __future__ import annotations

from collections import Counter

from common import CATEGORIES, LICENSES, load_catalog


def md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def main() -> None:
    cat = load_catalog()
    puzzles = cat["puzzles"]
    lines = [
        "# Image licences",
        "",
        "Every image in this repository is under one of these licences, all of which allow",
        "commercial use and modification (cutting an image into a jigsaw):",
        "",
        "* **CC0 1.0** — no rights reserved. Attribution is given anyway as good practice.",
        "* **Public domain** — e.g. works whose copyright expired, or US-government works.",
        "* **CC BY 2.0 / 3.0 / 4.0** — attribution required: author, licence and source link",
        "  are listed below, stored in `catalog.json` and shown in the app.",
        "* **Pexels License** — free commercial use, attribution not required.",
        "",
        "Never accepted: CC BY-SA, any NC or ND licence, GFDL, fair use, or unclear licences.",
        "Licence data for Wikimedia Commons files is read from the Commons API (`extmetadata`).",
        "",
        "Since v4 the images are gently enhanced (levels, contrast, vibrance; `tools/enhance.py`).",
        "Entries marked *modified* were changed in that way — as CC BY requires, the change is",
        "indicated here, in `catalog.json` (`\"modified\": true`) and in the app's credit line.",
        "",
        "Tools, code and catalog metadata are released under CC0 1.0.",
        "",
        "## Summary",
        "",
        "| Category | Images | " + " | ".join(sorted({p['license'] for p in puzzles})) + " |",
        "|---|---:|" + "---:|" * len({p['license'] for p in puzzles}),
    ]
    lic_names = sorted({p["license"] for p in puzzles})
    for c in CATEGORIES:
        items = [p for p in puzzles if p["categoryId"] == c["id"]]
        cnt = Counter(p["license"] for p in items)
        lines.append(f"| {c['names']['en']} | {len(items)} | " + " | ".join(str(cnt.get(l, 0)) for l in lic_names) + " |")
    lines += ["", f"Total: **{len(puzzles)}** images.", "", "## Images", ""]
    for c in CATEGORIES:
        items = [p for p in puzzles if p["categoryId"] == c["id"]]
        if not items:
            continue
        lines += [f"### {c['names']['en']}", "", "| ID | Title | Author | Licence | Source |", "|---|---|---|---|---|"]
        for p in items:
            lic = f"[{p['license']}]({p['licenseUrl']})" if p.get("licenseUrl") else p["license"]
            if p.get("modified"):
                lic += " · *modified*"
            lines.append(f"| `{p['id']}` | {md(p['title'])} | {md(p['photographer'])} | {lic} | [link]({p['sourceUrl']}) |")
        lines.append("")
    LICENSES.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"LICENSES.md: {len(puzzles)} images")


if __name__ == "__main__":
    main()
