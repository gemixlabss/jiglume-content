#!/usr/bin/env python3
"""Generates Jiglume's AI illustrations with the Gemini API (Nano Banana).

Prompts come from ai/prompts.yaml (scene prompt + shared style + hard
negative rules). Every image is written to ai/raw/<category>/<file>.png with
a JSON sidecar: scene id, full prompt, model, resolution, date, token usage
and cost. Re-running skips images that already exist (idempotent), so an
interrupted run simply continues.

The API key is never read from or written to a file: the session's network
proxy injects the `x-goog-api-key` header for generativelanguage.googleapis.com.
(Locally, export GEMINI_API_KEY instead.)

    # normal (synchronous) generation
    tools/generate_ai.py run --first-per-category 1 --event-first 4 --size 2K
    tools/generate_ai.py run --ids cute_pets-01,wildlife-02 --size 4K
    # batch mode (50 % cheaper, asynchronous)
    tools/generate_ai.py batch-submit --all --size 2K
    tools/generate_ai.py batch-poll          # downloads finished jobs
    tools/generate_ai.py cost                # spending so far
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "ai" / "prompts.yaml"
RAW = ROOT / "ai" / "raw"
BATCHES = ROOT / "ai" / "batches.json"
API = "https://generativelanguage.googleapis.com"

# USD, from the Gemini API pricing page (gemini-nano-banana-2.1, verified
# 2026-11-11): image output $30 / 1M tokens standard, $15 batch; input
# $1.50 / 1M standard, $0.75 batch.
PRICE = {
    "standard": {"image_out": 30.0, "text_out": 7.50, "in": 1.50},
    "batch": {"image_out": 15.0, "text_out": 3.75, "in": 0.75},
}
PER_IMAGE = {"standard": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113},
             "batch": {"1K": 0.0168, "2K": 0.0252, "4K": 0.0567}}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Prompts

def load_scenes() -> tuple[dict, list[dict]]:
    doc = yaml.safe_load(PROMPTS.read_text())
    scenes = []
    for group, kind in ((doc.get("categories", []), "category"), (doc.get("events", []), "event")):
        for c in group:
            for i, s in enumerate(c["scenes"]):
                scenes.append({**s, "category": c["id"], "kind": kind, "index": i,
                               "directive": c.get("directive")})
    return doc, scenes


def full_prompt(doc: dict, scene: dict) -> str:
    parts = [scene["prompt"].strip()]
    if scene.get("directive"):
        parts.append(scene["directive"].strip())
    palette = (doc.get("palettes") or {}).get(scene.get("palette", ""))
    if palette:
        parts.append(f"Light and palette: {palette}")
    parts.append(f"Style: {doc['style'].strip()}")
    rules = doc["negative"].strip()
    if scene.get("guards"):
        rules += " " + " ".join(scene["guards"])
    parts.append(f"Rules: {rules}")
    parts.append("Vertical 3:4 composition.")
    return "\n\n".join(parts)


def out_path(scene: dict, size: str, attempt: int = 0) -> Path:
    suffix = f"-{size.lower()}" + (f"-r{attempt}" if attempt else "")
    return RAW / scene["category"] / f"{scene['id']}{suffix}.png"


def request_body(doc: dict, scene: dict, size: str) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": full_prompt(doc, scene)}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": doc.get("aspect_ratio", "3:4"), "imageSize": size},
        },
    }


# ---------------------------------------------------------------------------
# HTTP

def _headers(extra: dict | None = None) -> dict:
    # The proxy replaces this placeholder with the real key.
    h = {"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "proxy-injected"),
         "Content-Type": "application/json"}
    h.update(extra or {})
    return h


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None,
         attempts: int = 6, timeout: int = 600) -> tuple[bytes, dict]:
    delay = 5.0
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, method=method, headers=_headers(headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            detail = e.read()[:600].decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                log(f"  HTTP {e.code}, retrying in {delay:.0f}s: {detail[:160]}")
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            raise RuntimeError(f"HTTP {e.code} {url}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == attempts - 1:
                raise
            log(f"  network error {e}, retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Results

def cost_of(usage: dict, size: str, mode: str) -> dict:
    p = PRICE[mode]
    inp = usage.get("promptTokenCount", 0)
    details = {d.get("modality"): d.get("tokenCount", 0) for d in usage.get("candidatesTokensDetails", [])}
    img_out = details.get("IMAGE", usage.get("candidatesTokenCount", 0))
    txt_out = details.get("TEXT", 0) + usage.get("thoughtsTokenCount", 0)
    usd = (inp * p["in"] + img_out * p["image_out"] + txt_out * p["text_out"]) / 1e6
    if not img_out:  # no usage reported: list price per image
        usd = PER_IMAGE[mode][size]
    return {"usd": round(usd, 5), "mode": mode, "promptTokens": inp, "imageTokens": img_out,
            "textTokens": txt_out}


def save_result(doc: dict, scene: dict, size: str, response: dict, mode: str, attempt: int = 0,
                extra: dict | None = None) -> Path | None:
    parts = (response.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    image = next((p for p in parts if "inlineData" in p or "inline_data" in p), None)
    if image is None:
        reason = (response.get("candidates") or [{}])[0].get("finishReason") or response.get("promptFeedback")
        log(f"  {scene['id']}: no image returned ({reason})")
        return None
    data = image.get("inlineData") or image.get("inline_data")
    path = out_path(scene, size, attempt)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(data["data"])
    mime = data.get("mimeType") or data.get("mime_type", "image/png")
    if "png" not in mime:  # keep the original bytes; record the real type
        path = path.with_suffix(".jpg" if "jpeg" in mime else ".webp")
    path.write_bytes(raw)
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    meta = {
        "id": scene["id"], "category": scene["category"], "kind": scene["kind"], "title": scene["title"],
        "scenePrompt": scene["prompt"], "palette": scene.get("palette"), "prompt": full_prompt(doc, scene),
        "model": doc["model"],
        "aspectRatio": doc.get("aspect_ratio", "3:4"), "imageSize": size, "width": w, "height": h,
        "mimeType": mime, "attempt": attempt,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usage": response.get("usageMetadata", {}),
        "cost": cost_of(response.get("usageMetadata", {}), size, mode),
        "source": "ai-generated", **(extra or {}),
    }
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    log(f"  + {path.relative_to(ROOT)} {w}x{h} ${meta['cost']['usd']:.4f}")
    return path


def existing(scene: dict, size: str, attempt: int = 0) -> Path | None:
    p = out_path(scene, size, attempt)
    for ext in (".png", ".jpg", ".webp"):
        if p.with_suffix(ext).exists():
            return p.with_suffix(ext)
    return None


# ---------------------------------------------------------------------------
# Commands

def select(scenes: list[dict], args) -> list[dict]:
    if getattr(args, "ids", None):
        wanted = set(args.ids.split(","))
        return [s for s in scenes if s["id"] in wanted]
    out = []
    for s in scenes:
        if getattr(args, "all", False):
            out.append(s)
        elif s["kind"] == "category" and s["index"] < (args.first_per_category or 0):
            out.append(s)
        elif s["kind"] == "event" and s["index"] < (args.event_first or 0):
            out.append(s)
    return out


def cmd_run(args) -> int:
    doc, scenes = load_scenes()
    todo = select(scenes, args)
    url = f"{API}/v1beta/models/{doc['model']}:generateContent"
    spent = 0.0
    for s in todo:
        if existing(s, args.size, args.attempt):
            log(f"  = {s['id']} ({args.size}) exists")
            continue
        log(f"[{s['id']}] {args.size}")
        try:
            body, _ = http("POST", url, json.dumps(request_body(doc, s, args.size)).encode())
        except RuntimeError as e:
            log(f"  failed: {e}")
            continue
        path = save_result(doc, s, args.size, json.loads(body), "standard", args.attempt)
        if path:
            spent += json.loads(path.with_suffix(".json").read_text())["cost"]["usd"]
    print(f"spent this run: ${spent:.4f}")
    return 0


def _upload_jsonl(path: Path) -> str:
    """Resumable upload to the Files API; returns the file name (files/…)."""
    data = path.read_bytes()
    start, headers = http("POST", f"{API}/upload/v1beta/files", json.dumps(
        {"file": {"display_name": path.name}}).encode(), headers={
        "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(len(data)),
        "X-Goog-Upload-Header-Content-Type": "application/jsonl"})
    upload_url = next(v for k, v in headers.items() if k.lower() == "x-goog-upload-url")
    body, _ = http("POST", upload_url, data, headers={
        "Content-Length": str(len(data)), "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize", "Content-Type": "application/jsonl"})
    return json.loads(body)["file"]["name"]


def cmd_batch_submit(args) -> int:
    doc, scenes = load_scenes()
    todo = [s for s in select(scenes, args) if not existing(s, args.size, args.attempt)]
    jobs = json.loads(BATCHES.read_text()) if BATCHES.exists() else []
    pending = {k for j in jobs if j["state"] not in ("JOB_STATE_SUCCEEDED", "DONE", "JOB_STATE_FAILED",
                                                     "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED")
               for k in j["keys"]}
    todo = [s for s in todo if f"{s['id']}|{args.size}|{args.attempt}" not in pending]
    if not todo:
        print("nothing to submit")
        return 0
    jsonl = ROOT / "ai" / "batch-input" / f"batch-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    keys = []
    with jsonl.open("w") as f:
        for s in todo:
            key = f"{s['id']}|{args.size}|{args.attempt}"
            keys.append(key)
            f.write(json.dumps({"key": key, "request": request_body(doc, s, args.size)}) + "\n")
    file_name = _upload_jsonl(jsonl)
    body, _ = http("POST", f"{API}/v1beta/models/{doc['model']}:batchGenerateContent", json.dumps(
        {"batch": {"display_name": jsonl.stem, "input_config": {"file_name": file_name}}}).encode())
    job = json.loads(body)
    name = job.get("name") or job.get("metadata", {}).get("name")
    jobs.append({"name": name, "file": file_name, "input": str(jsonl.relative_to(ROOT)), "keys": keys,
                 "size": args.size, "state": "SUBMITTED",
                 "submittedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    BATCHES.write_text(json.dumps(jobs, indent=1))
    print(f"submitted {name}: {len(keys)} requests")
    return 0


def cmd_batch_poll(args) -> int:
    doc, scenes = load_scenes()
    by_id = {s["id"]: s for s in scenes}
    jobs = json.loads(BATCHES.read_text()) if BATCHES.exists() else []
    for j in jobs:
        if j["state"] in ("DONE", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
            continue
        body, _ = http("GET", f"{API}/v1beta/{j['name']}")
        info = json.loads(body)
        state = info.get("metadata", {}).get("state") or info.get("state", "?")
        j["state"] = state
        log(f"{j['name']}: {state}")
        if state != "JOB_STATE_SUCCEEDED":
            continue
        resp = info.get("response") or info.get("metadata", {}).get("output", {})
        results_file = resp.get("responsesFile") or (resp.get("output") or {}).get("responsesFile")
        lines = []
        if results_file:
            data, _ = http("GET", f"{API}/download/v1beta/{results_file}:download?alt=media")
            lines = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
        else:
            lines = (resp.get("inlinedResponses") or {}).get("inlinedResponses", [])
        for line in lines:
            key = line.get("key") or (line.get("metadata") or {}).get("key")
            sid, size, attempt = key.split("|")
            if "error" in line:
                log(f"  {sid}: {line['error']}")
                continue
            save_result(doc, by_id[sid], size, line.get("response", {}), "batch", int(attempt),
                        {"batchJob": j["name"]})
        j["state"] = "DONE"
        BATCHES.write_text(json.dumps(jobs, indent=1))
    BATCHES.write_text(json.dumps(jobs, indent=1))
    return 0


def cmd_cost(_args) -> int:
    total, n, by_mode = 0.0, 0, {}
    for meta in RAW.rglob("*.json"):
        c = json.loads(meta.read_text()).get("cost", {})
        total += c.get("usd", 0)
        n += 1
        by_mode[c.get("mode")] = by_mode.get(c.get("mode"), 0) + c.get("usd", 0)
    print(json.dumps({"images": n, "usd": round(total, 4), "byMode": {k: round(v, 4) for k, v in by_mode.items()}}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "batch-submit"):
        p = sub.add_parser(name)
        p.add_argument("--ids")
        p.add_argument("--all", action="store_true")
        p.add_argument("--first-per-category", type=int, default=0)
        p.add_argument("--event-first", type=int, default=0)
        p.add_argument("--size", choices=["1K", "2K", "4K"], default="2K")
        p.add_argument("--attempt", type=int, default=0, help="regeneration attempt number (new file)")
    sub.add_parser("batch-poll")
    sub.add_parser("cost")
    args = ap.parse_args()
    return {"run": cmd_run, "batch-submit": cmd_batch_submit, "batch-poll": cmd_batch_poll,
            "cost": cmd_cost}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
