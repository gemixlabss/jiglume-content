#!/usr/bin/env python3
"""Quality gate for AI illustrations (ai/raw → ai/qc).

For every generated image:
  * resolution: native size, size after processing to FINAL_LONG_SIDE
    (2K is upscaled with Lanczos + light sharpening, 4K is downscaled), and
    the short side after the app's fill crops (3:4 phone, 1:1 square) — must
    be ≥ MIN_CROP_SHORT_SIDE; also source pixels per cell at 1000 pieces;
  * vividness: colourfulness / contrast / sharpness (tools/vividness.py);
  * jigsaw-friendliness: share of flat, detail-less tiles (big empty sky);
  * forbidden content: text / letters / numbers (OCR, RapidOCR) and close-up
    faces (YuNet face detector);
  * duplicates: perceptual hash distance to every other image.

    tools/ai_quality.py                 # all images in ai/raw
    tools/ai_quality.py --sheet out.jpg # + numbered contact sheet
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imaging import hamming, phash  # noqa: E402
from vividness import metrics as vivid_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "ai" / "raw"
QC = ROOT / "ai" / "qc"
MODELS = ROOT / "tools" / "models"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")

FINAL_LONG_SIDE = 3000
MIN_CROP_SHORT_SIDE = 1600
MIN_CELL_PIXELS = 60
MAX_FLAT_SHARE = 0.20          # at most 20 % of tiles may be flat
MIN_COLORFULNESS = 28.0
MIN_CONTRAST = 0.16
MIN_SHARPNESS = 3.6
TEXT_MIN_SCORE = 0.80          # OCR confidence for a "text" hit
FACE_MAX_HEIGHT = 0.06         # a face taller than 6 % of the picture is a close-up
DUPLICATE_HAMMING = 10


# ---------------------------------------------------------------------------
# Processing (shared with the publishing step)

def to_final(img: Image.Image, long_side: int = FINAL_LONG_SIDE) -> Image.Image:
    """2K → upscale (Lanczos + light unsharp mask); 4K → downscale (Lanczos)."""
    img = img.convert("RGB")
    s = long_side / max(img.size)
    size = (round(img.width * s), round(img.height * s))
    out = img.resize(size, Image.LANCZOS)
    if s > 1:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.6, percent=55, threshold=2))
    return out


def crop_short_sides(w: int, h: int) -> dict:
    out = {}
    for name, a in (("3:4", 0.75), ("1:1", 1.0)):
        cw, ch = (h * a, h) if w / h > a else (w, w / a)
        cols = math.sqrt(1000 * a)
        out[name] = {"shortSide": round(min(cw, ch)), "cellPx1000": round(min(cw, ch) / cols, 1)}
    return out


# ---------------------------------------------------------------------------
# Detectors

_ocr = None
_faces = None


def ocr_hits(img: Image.Image) -> list[dict]:
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    small = img.copy()
    small.thumbnail((1600, 1600))
    result, _ = _ocr(np.array(small.convert("RGB")))
    hits = []
    for box, text, score in result or []:
        alnum = sum(ch.isalnum() for ch in text)
        if float(score) >= TEXT_MIN_SCORE and alnum >= 2:
            hits.append({"text": text, "score": round(float(score), 2)})
    return hits


def face_hits(img: Image.Image) -> list[dict]:
    global _faces
    import cv2
    if _faces is None:
        if not YUNET.exists():
            import urllib.request
            MODELS.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(YUNET_URL, YUNET)
        _faces = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.75)
    small = img.copy()
    small.thumbnail((1280, 1280))
    arr = cv2.cvtColor(np.array(small.convert("RGB")), cv2.COLOR_RGB2BGR)
    _faces.setInputSize((arr.shape[1], arr.shape[0]))
    _, found = _faces.detect(arr)
    hits = []
    for f in found if found is not None else []:
        rel = float(f[3]) / arr.shape[0]
        hits.append({"height": round(rel, 3), "score": round(float(f[14]), 2), "closeUp": rel > FACE_MAX_HEIGHT})
    return hits


def flat_share(img: Image.Image, cols: int = 8, rows: int = 10) -> float:
    """Share of grid tiles with almost no detail (empty sky, flat fills)."""
    g = np.asarray(img.convert("L").resize((cols * 64, rows * 64)), dtype=np.float32)
    lap = np.abs(g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    flat = 0
    for r in range(rows):
        for c in range(cols):
            t = g[r * 64:(r + 1) * 64, c * 64:(c + 1) * 64]
            e = lap[max(0, r * 64 - 1):(r + 1) * 64 - 1, max(0, c * 64 - 1):(c + 1) * 64 - 1]
            if t.std() < 6 and e.mean() < 2.5:
                flat += 1
    return round(flat / (cols * rows), 3)


# ---------------------------------------------------------------------------

def check(path: Path) -> dict:
    meta = json.loads(path.with_suffix(".json").read_text())
    img = Image.open(path).convert("RGB")
    final = to_final(img)
    m = vivid_metrics(final)
    crops = crop_short_sides(*final.size)
    r = {
        "file": str(path.relative_to(ROOT)), "id": meta["id"], "category": meta["category"],
        "title": meta["title"], "imageSize": meta["imageSize"], "native": list(img.size),
        "final": list(final.size), "crops": crops, "vivid": m, "flatShare": flat_share(final),
        "text": ocr_hits(img), "faces": face_hits(img), "phash": phash(img),
        "costUsd": meta.get("cost", {}).get("usd", 0),
    }
    problems = []
    if min(c["shortSide"] for c in crops.values()) < MIN_CROP_SHORT_SIDE:
        problems.append("crop short side < 1600")
    if min(c["cellPx1000"] for c in crops.values()) < MIN_CELL_PIXELS:
        problems.append("< 60 px per cell at 1000 pieces")
    if m["colorfulness"] < MIN_COLORFULNESS:
        problems.append(f"dull colours ({m['colorfulness']})")
    if m["contrast"] < MIN_CONTRAST:
        problems.append(f"low contrast ({m['contrast']})")
    if m["sharpness"] < MIN_SHARPNESS:
        problems.append(f"soft ({m['sharpness']})")
    if r["flatShare"] > MAX_FLAT_SHARE:
        problems.append(f"flat areas {r['flatShare']:.0%}")
    if r["text"]:
        problems.append("text: " + ", ".join(h["text"] for h in r["text"][:3]))
    if any(f["closeUp"] for f in r["faces"]):
        problems.append("close-up face")
    r["problems"] = problems
    r["pass"] = not problems
    return r


def contact_sheet(results: list[dict], out: Path, total_usd: float) -> None:
    cols, tw, th, pad = 5, 360, 480, 12
    rows = math.ceil(len(results) / cols)
    head = 70
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, head + rows * (th + 120 + pad)), (246, 244, 239))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=16)
        small = ImageFont.load_default(size=13)
        big = ImageFont.load_default(size=26)
    except TypeError:
        font = small = big = ImageFont.load_default()
    d.text((pad, 18), f"Jiglume AI style test - {len(results)} images — total ${total_usd:.2f}", fill=(30, 30, 40), font=big)
    for i, r in enumerate(results):
        x = pad + (i % cols) * (tw + pad)
        y = head + (i // cols) * (th + 120 + pad)
        im = Image.open(ROOT / r["file"]).convert("RGB")
        im.thumbnail((tw, th))
        sheet.paste(im, (x + (tw - im.width) // 2, y))
        d.rectangle((x, y, x + 34, y + 26), fill=(20, 20, 30))
        d.text((x + 6, y + 4), f"{i + 1}", fill=(255, 220, 120), font=font)
        ok = (40, 140, 70) if r["pass"] else (200, 60, 50)
        ty = y + th + 4
        d.text((x, ty), f"{r['category']} / {r['title']}"[:44], fill=(30, 30, 40), font=font)
        d.text((x, ty + 20), f"{r['imageSize']} {r['native'][0]}x{r['native'][1]} -> {r['final'][0]}x{r['final'][1]}  ${r['costUsd']:.3f}",
               fill=(60, 60, 70), font=small)
        v = r["vivid"]
        d.text((x, ty + 38), f"colour {v['colorfulness']}  contrast {v['contrast']}  sharp {v['sharpness']}  flat {r['flatShare']:.0%}",
               fill=(60, 60, 70), font=small)
        c = r["crops"]
        d.text((x, ty + 56), f"crop 3:4 {c['3:4']['shortSide']}px/{c['3:4']['cellPx1000']}  1:1 {c['1:1']['shortSide']}px/{c['1:1']['cellPx1000']}",
               fill=(60, 60, 70), font=small)
        status = "PASS" if r["pass"] else "FAIL: " + "; ".join(r["problems"])
        d.text((x, ty + 76), status[:52], fill=ok, font=font)
        if len(status) > 52:
            d.text((x, ty + 94), status[52:104], fill=ok, font=small)
    sheet.save(out, quality=86)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="*/*.png")
    ap.add_argument("--sheet")
    args = ap.parse_args()
    QC.mkdir(parents=True, exist_ok=True)
    results = []
    for p in sorted(RAW.glob(args.glob)):
        if not p.with_suffix(".json").exists():
            continue
        r = check(p)
        results.append(r)
        (QC / (p.stem + ".json")).write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print(f"{'PASS' if r['pass'] else 'FAIL'} {p.stem}: {'; '.join(r['problems'])}", file=sys.stderr)
    # Duplicates within the set.
    for i, a in enumerate(results):
        for b in results[i + 1:]:
            if a["id"] != b["id"] and hamming(a["phash"], b["phash"]) <= DUPLICATE_HAMMING:
                for x, y in ((a, b), (b, a)):
                    x["problems"].append(f"near-duplicate of {y['id']}")
                    x["pass"] = False
    total = sum(r["costUsd"] for r in results)
    if args.sheet:
        contact_sheet(results, Path(args.sheet), total)
    print(json.dumps({"checked": len(results), "passed": sum(r["pass"] for r in results), "usd": round(total, 4)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
