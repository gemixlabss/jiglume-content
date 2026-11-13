#!/usr/bin/env python3
"""Translates the short English display titles of ai/prompts.yaml into the
app's 20 languages with a Gemini text model; cached in ai/titles_i18n.json
(only missing titles are sent). Titles stay short (1–4 words), natural and
child-friendly; proper nouns are not invented.

    tools/translate_titles.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ai" / "titles_i18n.json"
MODEL = "gemini-3.8-flash"
LANGS = ["en", "tr", "de", "fr", "es", "pt-BR", "it", "ru", "ar", "ja", "ko", "zh-Hans", "hi", "id", "nl", "pl",
         "uk", "vi", "th", "sv"]
NAMES = {"tr": "Turkish", "de": "German", "fr": "French", "es": "Spanish", "pt-BR": "Brazilian Portuguese",
         "it": "Italian", "ru": "Russian", "ar": "Arabic", "ja": "Japanese", "ko": "Korean",
         "zh-Hans": "Simplified Chinese", "hi": "Hindi", "id": "Indonesian", "nl": "Dutch", "pl": "Polish",
         "uk": "Ukrainian", "vi": "Vietnamese", "th": "Thai", "sv": "Swedish"}


def ask(batch: dict[str, str]) -> dict:
    prompt = (
        "Translate these short picture titles of a jigsaw puzzle app into each language. Keep them short "
        "(1–4 words), natural, warm and suitable as a card title; no quotes, no trailing punctuation, sentence "
        "case where the language uses it. Languages: " + ", ".join(f"{k} = {v}" for k, v in NAMES.items()) +
        ". Return JSON: an object mapping each id to an object mapping each language code to its title.\n\n" +
        json.dumps(batch, ensure_ascii=False, indent=0))
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(), method="POST",
        headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "proxy-injected"),
                 "Content-Type": "application/json"})
    from budget import guard, record
    guard(0.05)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.load(r)
            u = d.get("usageMetadata", {})
            record((u.get("promptTokenCount", 0) * 0.75 + (u.get("candidatesTokenCount", 0)
                    + u.get("thoughtsTokenCount", 0)) * 3.75) / 1e6, "translate titles")
            text = next(p["text"] for p in reversed(d["candidates"][0]["content"]["parts"]) if "text" in p)
            return json.loads(text)
        except Exception as e:  # noqa: BLE001
            print(f"  retry {attempt}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("translation failed")


def main() -> int:
    doc = yaml.safe_load((ROOT / "ai" / "prompts.yaml").read_text())
    titles = {s["id"]: s["title"] for g in doc["categories"] + doc["events"] for s in g["scenes"]}
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = {k: v for k, v in titles.items() if k not in done or any(l not in done[k] for l in LANGS)}
    keys = list(todo)
    for i in range(0, len(keys), 40):
        batch = {k: todo[k] for k in keys[i:i + 40]}
        result = ask(batch)
        for k, en in batch.items():
            tr = result.get(k) or {}
            entry = {"en": en, **{lang: str(tr.get(lang, "")).strip() for lang in NAMES}}
            if all(entry.values()):
                done[k] = entry
        OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1))
        print(f"{min(i + 40, len(keys))}/{len(keys)}", file=sys.stderr)
    missing = [k for k in titles if k not in done]
    print(json.dumps({"titles": len(done), "missing": missing}))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
