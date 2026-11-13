#!/usr/bin/env python3
"""Merges a prompt additions file (new scenes per category, new events) into
ai/prompts.yaml, then the caller runs tools/assign_palettes.py, which gives
only the new scenes a palette.

    tools/merge_prompts.py ai/prompts_add_round2.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "ai" / "prompts.yaml"


def main() -> int:
    add = yaml.safe_load(Path(sys.argv[1]).read_text())
    doc = yaml.safe_load(PROMPTS.read_text())
    groups = {g["id"]: g for g in doc["categories"] + doc["events"]}
    known = {s["id"] for g in groups.values() for s in g["scenes"]}
    added = 0
    for cat, scenes in (add.get("categories") or {}).items():
        for s in scenes:
            if s["id"] not in known:
                groups[cat]["scenes"].append(s)
                added += 1
    for ev, spec in (add.get("events") or {}).items():
        if not spec:
            continue
        if ev not in groups:
            meta = spec.get("meta", {})
            g = {"id": ev, "starts": meta.get("starts"), "ends": meta.get("ends"), "scenes": []}
            doc["events"].append(g)
            groups[ev] = g
        for s in spec["scenes"]:
            if s["id"] not in known:
                groups[ev]["scenes"].append(s)
                added += 1
    PROMPTS.write_text(PROMPTS.read_text().split("\n", 2)[0] + "\n" + PROMPTS.read_text().split("\n", 2)[1] + "\n"
                       + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110))
    print(f"added {added} scenes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
