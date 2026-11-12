#!/usr/bin/env python3
"""Turns generated AI images into archive files, one category at a time.

For every scene of a category:
  1. quality-gates every generated attempt (tools/ai_quality.py, cached);
  2. keeps the best passing attempt (highest appeal);
  3. if no attempt passes and fewer than MAX_ATTEMPTS were made, regenerates
     it (normal mode, attempt n+1) and checks again;
  4. writes images/<category>/<id>.webp (long side 3000, 2K is Lanczos-upscaled
     and lightly sharpened), thumbs/<id>.webp (640 px square, centre crop),
     and a staging entry in ai/staging/<category>.json (dominant colour, appeal,
     quality, prompt, model, cost).

    tools/ai_process.py cute_pets            # gate + retry + write files
    tools/ai_process.py cute_pets --no-retry
    tools/ai_process.py cute_pets --sheet sheet.jpg
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_quality as q  # noqa: E402
from enhance import appeal, sharpen_thumb  # noqa: E402
from imaging import dominant_color, encode_webp, hamming  # noqa: E402
from generate_ai import load_scenes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "ai" / "raw"
STAGING_DIR = ROOT / "ai" / "staging"  # one JSON per category (parallel-safe)
MAX_ATTEMPTS = 3          # first try + 2 regenerations
WEBP_QUALITY = 88
THUMB = 640
THUMB_QUALITY = 82


def attempts_for(scene_id: str, category: str) -> list[Path]:
    files = [p for p in (RAW / category).glob(f"{scene_id}-2k*") if p.suffix.lower() in (".png", ".jpg", ".webp")]
    return sorted(files)


def gate(path: Path) -> dict:
    cache = q.QC / (path.stem + ".json")
    if cache.exists():
        r = json.loads(cache.read_text())
        if not r.get("reviewPending") or os.environ.get("JIGLUME_NO_REVIEW"):
            return r
    q.QC.mkdir(parents=True, exist_ok=True)
    r = q.check(path)
    cache.write_text(json.dumps(r, ensure_ascii=False, indent=1))
    return r


def regenerate(scene_id: str, attempt: int) -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "generate_ai.py"), "run", "--ids", scene_id,
                    "--size", "2K", "--attempt", str(attempt)], check=False)


def write_files(scene: dict, path: Path, qc: dict) -> dict:
    meta = json.loads(path.with_suffix(".json").read_text())
    img = Image.open(path).convert("RGB")
    final = q.to_final(img)
    cat = scene["category"]
    image_path = f"images/{cat}/{scene['id']}.webp"
    thumb_path = f"thumbs/{scene['id']}.webp"
    (ROOT / image_path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / thumb_path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / image_path).write_bytes(encode_webp(final, WEBP_QUALITY))
    side = min(final.size)
    left, top = (final.width - side) // 2, (final.height - side) // 2
    thumb = sharpen_thumb(final.crop((left, top, left + side, top + side)).resize((THUMB, THUMB), Image.LANCZOS))
    (ROOT / thumb_path).write_bytes(encode_webp(thumb, THUMB_QUALITY))
    return {
        "id": scene["id"], "categoryId": cat, "kind": scene["kind"], "titleKey": scene["id"],
        "title": scene["title"], "imagePath": image_path, "thumbPath": thumb_path,
        "width": final.width, "height": final.height, "dominantColor": dominant_color(thumb),
        "quality": qc["vivid"], "appeal": appeal(qc["vivid"]), "flatShare": qc["flatShare"],
        "source": "ai-generated", "model": meta["model"], "imageSize": meta["imageSize"],
        "palette": meta.get("palette") or scene.get("palette"), "scenePrompt": meta["scenePrompt"],
        "prompt": meta["prompt"], "generatedAt": meta["generatedAt"], "attempt": meta.get("attempt", 0),
        "costUsd": qc.get("costUsd", 0), "phash": qc["phash"], "file": str(path.relative_to(ROOT)),
        "reviewed": not qc.get("reviewPending", False),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--sheet")
    args = ap.parse_args()
    _, scenes = load_scenes()
    scenes = [s for s in scenes if s["category"] == args.category]
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staging_file = STAGING_DIR / f"{args.category}.json"
    staging = json.loads(staging_file.read_text()) if staging_file.exists() else {}
    report = {"accepted": 0, "retried": 0, "missing": [], "rejected": {}}
    accepted_qc = []
    for s in scenes:
        while True:
            files = attempts_for(s["id"], s["category"])
            results = [(p, gate(p)) for p in files]
            # Near-duplicates of images already accepted in this category fail too.
            for p, r in results:
                dup = next((a["id"] for a in accepted_qc if a["id"] != s["id"]
                            and hamming(a["phash"], r["phash"]) <= q.DUPLICATE_HAMMING), None)
                if dup and r["pass"]:
                    r["pass"] = False
                    r["problems"].append(f"near-duplicate of {dup}")
            passing = [(p, r) for p, r in results if r["pass"]]
            for p, r in results:
                if not r["pass"]:
                    report["rejected"][p.stem] = r["problems"]
            if passing or args.no_retry or len(files) >= MAX_ATTEMPTS:
                break
            report["retried"] += 1
            regenerate(s["id"], len(files))
            if len(attempts_for(s["id"], s["category"])) == len(files):  # generation failed
                break
        if not passing:
            report["missing"].append(s["id"])
            staging.pop(s["id"], None)
            continue
        path, r = max(passing, key=lambda pr: appeal(pr[1]["vivid"]))
        staging[s["id"]] = write_files(s, path, r)
        accepted_qc.append(r)
        report["accepted"] += 1
        staging_file.write_text(json.dumps(staging, ensure_ascii=False, indent=1))
    if args.sheet:
        chosen = [gate(ROOT / staging[s["id"]]["file"]) for s in scenes if s["id"] in staging]
        total = sum(json.loads(p.with_suffix(".json").read_text())["cost"]["usd"]
                    for s in scenes for p in attempts_for(s["id"], s["category"]))
        q.contact_sheet(chosen, Path(args.sheet), total, title=f"{args.category}: {len(chosen)} images")
    print(json.dumps({"category": args.category, **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
