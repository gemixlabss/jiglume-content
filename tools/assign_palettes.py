#!/usr/bin/env python3
"""Gives every scene in ai/prompts.yaml its own light / colour palette, so the
gallery is not one long golden sunset.

* Generic lighting phrases ("warm evening light", "golden hour", …) are
  removed from the scene prompts; the assigned palette describes the light.
  Scenes whose very subject is a time of day (night sky, aurora, "Lions at
  sunset") keep it and only get a compatible palette.
* Palettes are spread per category: none may exceed 30 % of a category.
* Text-prone props get explicit guards (clock faces without numerals, blank
  book spines, toy blocks with pictures, signs without writing…).

    tools/assign_palettes.py          # rewrites ai/prompts.yaml in place
    tools/assign_palettes.py --check  # report only
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "ai" / "prompts.yaml"
MAX_SHARE = 0.30

PALETTES = {
    "morning": "Fresh early-morning light: airy pastel palette (soft pink, mint, pale blue, butter yellow), "
               "a little morning mist, long gentle shadows.",
    "midday": "Bright midday sun: clear deep-blue sky with a few white clouds wherever sky shows, vivid fresh "
              "greens and saturated true colours, crisp clean shadows.",
    "golden": "Golden hour: low warm sun, honeyed amber light, long shadows and glowing rim light.",
    "blue_hour": "Blue hour / twilight: deep blue and violet sky, the first warm lights in windows and lamps, "
                 "a cool-and-warm colour contrast.",
    "night": "Night: moonlight and starlight with warm lanterns, candles or windows as light sources; deep navy, "
             "indigo and teal with golden accents; still clearly lit and full of readable detail.",
    "snowy": "Snowy cold palette: crisp whites, icy blues and silvery greys with a few warm accents (red, gold); "
             "soft diffused winter light.",
    "rainy": "Rainy day: rain on the windows and wet, glistening reflections, soft grey-blue daylight outside "
             "contrasted with warm lamp light inside (or the fresh, shiny moment just after rain outdoors).",
}

LIGHT_WORDS = set("""soft warm golden late bright gentle crisp dappled glowing light lights glow sunshine sun hour sunset
sunrise evening morning afternoon dusk dawn at pink and gold humid late-afternoon day sunny sky orange interior lamp
firelight lantern forest savanna mediterranean provençal australian pastel misty mist sunbeams rays magical festive
cozy mood beams of the a through window sunlight reflections warmly glowing amber honeyed""".split())
SEASON_WORDS = {"spring", "summer", "autumn", "winter", "snow", "snowy", "rain", "rainy"}
STRIP_INLINE = [r" at golden hour", r" at sunset", r" at sunrise", r" at dusk", r" in warm evening light",
                r" at blue hour", r" in golden light", r",? ?(?:late )?afternoon sun(?: through [a-z ]+)?",
                r",? ?warm (?:summer|late|spring|autumn|winter|sunset|sunrise|pink and gold|pink|golden|evening|morning|"
                r"afternoon|midnight-sun|late-summer|late-afternoon)[a-z -]*?(?:light|glow|sun|sky)\b",
                r",? ?(?:soft )?(?:pink )?winter sunset(?: light)?", r",? ?a warm (?:late-summer )?sunset", r",? ?low warm sun",
                r",? ?glowing orange sky(?: with detail-rich clouds)?", r",? ?pink and gold sky", r",? ?summer evening glow",
                r",? ?golden (?:afternoon|evening|morning|sunset) light", r",? ?a sunset with layered warm clouds",
                r",? ?a glowing sunset sky", r",? ?soft golden sunshine", r",? ?warm summer evening sky",
                r",? ?bright warm afternoon sky", r",? ?a pink sky", r",? ?pink sunset light", r",? ?and pink sunset light",
                r",? ?snowy peaks glowing pink", r",? ?soft pink spring light", r",? ?soft spring light", r",? ?soft morning light",
                r",? ?morning mist lit by the sun", r",? ?soft sunbeams", r",? ?misty sunbeams", r",? ?sunshine breaking through"]
STRIP_INLINE += [r",? ?warm summer afternoon", r",? ?dappled golden light on the water", r"a pink and gold arctic sunset",
                 r",? ?warm sunset colours", r",? ?summer afternoon", r",? ?warm summer evening", r",? ?warm late spring evening",
                 r",? ?warm market light", r",? ?warm kitchen light", r",? ?(?:and )?soft afternoon light", r" and warm lamp light",
                 r",? ?sunset desert light", r",? ?warm autumn evening", r",? ?golden evening light"]
SUNNY_RE = re.compile(r"\bsunny (spring|summer|winter|autumn) (day|morning|afternoon)\b", re.I)

NIGHT_RE = re.compile(r"\b(night|moon|moonlit|starry|stars|aurora|northern lights|milky way|firefl\w*|meteor|"
                      r"bioluminescen\w*|star trails|lantern festival|midnight)\b", re.I)
DUSK_RE = re.compile(r"\b(dusk|blue hour|twilight)\b", re.I)
SUN_RE = re.compile(r"\b(sunset|sunrise|dawn|golden hour)\b", re.I)
SNOW_RE = re.compile(r"\b(snow\w*|winter|frozen|frost\w*|ice rink|icy|skat\w*|sleigh|sled\w*|polar)\b", re.I)
INDOOR_RE = re.compile(r"\b(inside|interior|room|kitchen|library|nook|study|attic|bedroom|conservatory|greenhouse|"
                       r"workshop|pantry|parlour|lobby|compartment|fireplace|window seat|bathroom|diner|"
                       r"windowsill|mudroom|nursery|hutch|bookshop|shop corner|counter)\b", re.I)
INDOOR_CATEGORIES = {"cozy_corners", "collections"}
WARM_SEASON_RE = re.compile(r"\b(spring|summer|bloom\w*|blossom\w*|flowers?|garden|meadow|veranda|beach|picnic|"
                            r"orchard|tulips?|roses?|hydrangeas?)\b", re.I)
DAY_ONLY_RE = re.compile(r"\b(butterfl\w*|bees?|bumblebee|picnic|beach day|sunflower\w*|tulip\w*|lavender|poppy|"
                         r"poppies|wildflower\w*|blossom\w*|orchard|harvest|berry|berries|lemonade|ice-cream|"
                         r"kite\w*|hummingbird\w*|dragonfl\w*)\b", re.I)

GUARDS = [
    (re.compile(r"\bclock", re.I), "Clock faces are plain with simple tick marks only, no numerals."),
    (re.compile(r"\b(book|library|bookshop|bookshelves)", re.I),
     "Book spines are plain colour blocks with simple ornaments, never titles or letters."),
    (re.compile(r"\b(blocks?|toy|toys)\b", re.I), "Toy blocks and toys show pictures or plain colours only, no letters or numbers."),
    (re.compile(r"\b(shop|store|market|stall|bakery|café|cafe|diner|kiosk|awning|pharmacy|apothecary|garage|motel|station)\b", re.I),
     "Shop fronts, signboards, menus and awnings carry no writing at all; jars, tins and packaging have no labels."),
    (re.compile(r"\b(lighthouse|weather ?vane)\b", re.I), "Any weather vane is a simple arrow without letters."),
    (re.compile(r"\b(train|tram|locomotive|bus|car|cars|truck|van|boat|boats|ship|plane|rocket)\b", re.I),
     "Vehicles carry no numbers, plates, names or badges."),
    (re.compile(r"\b(map|maps|globe|sheet music|letters|typewriter|chalkboard|calendar|stamp)\b", re.I),
     "Maps, papers and boards are decorative without any readable writing or numbers."),
]

HERO = {
    "cute_pets": "The pet(s) are the clear hero of the picture: large in the frame (roughly a third to half of the "
                 "image), facing the viewer with big expressive friendly eyes and adorable faces, fur rendered in fine "
                 "detail; the setting is detailed but calmer and less busy than the animals.",
    "wildlife": "The animal(s) are the clear hero of the picture: large in the frame (roughly a third to half of the "
                "image), with appealing expressive eyes and faces, fur or skin rendered in fine detail; the habitat is "
                "detailed but calmer and less busy than the animals.",
    "birds_butterflies": "The birds or butterflies are the clear heroes: large and close in the frame, with bright "
                         "eyes and finely detailed feathers or wing patterns; flowers and branches frame them without "
                         "crowding them out.",
}


def strip_light(prompt: str, keep: bool) -> str:
    if keep:
        return prompt
    text = prompt
    for pat in STRIP_INLINE:
        text = re.sub(pat, "", text, flags=re.I)
    text = SUNNY_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)
    text = re.sub(r"\bsunny\b ", "", text)
    text = text.replace("icebergs, reflected on the water", "icebergs and the sky reflected on the water")
    text = re.sub(r"\s+,", ",", text).replace(",,", ",").replace(" .", ".")
    body = text.rstrip(".").strip()
    segs = [s.strip() for s in body.split(",")]
    kept = []
    for s in segs:
        words = re.findall(r"[a-zçé'-]+", s.lower())
        if words and all(w in LIGHT_WORDS for w in words) and not SEASON_WORDS & set(words):
            continue
        kept.append(s)
    out = ", ".join(kept).strip(", ") + "."
    out = re.sub(r" and\.$", ".", out)
    out = re.sub(r" (with|of|the|a)\.$", ".", out)
    out = out.replace("birds in.", "birds overhead.")
    out = out.replace("icebergs, reflected on the water", "icebergs and the sky reflected on the water")
    return out


def allowed(scene: dict, category: str) -> list[str]:
    text = f"{scene['title']} {scene['basePrompt']}"
    indoor = category in INDOOR_CATEGORIES or bool(INDOOR_RE.search(text))
    opts = _allowed(scene, category, text, indoor)
    # Snow only where it can be (winter scenes, or indoors seen through a window
    # when nothing in the scene says spring / summer / flowers).
    if "snowy" in opts and not SNOW_RE.search(text) and (not indoor or WARM_SEASON_RE.search(text)):
        opts.remove("snowy")
    # Rain is an indoor mood here (or a garden right after spring rain).
    rainy_night = category == "night_stars" and re.search(r"\b(street|café|cafe|canal|city|market|window|terrace|bridge)\b", text, re.I)
    if "rainy" in opts and not indoor and not rainy_night and not re.search(r"\brain", text, re.I):
        opts.remove("rainy")
    if re.search(r"\bspring\b", text, re.I) and "night" in opts and len(opts) > 1:
        opts.remove("night")
    return opts or ["golden"]


def _allowed(scene: dict, category: str, text: str, indoor: bool) -> list[str]:
    if category == "night_stars" or NIGHT_RE.search(text):
        opts = ["night", "blue_hour"]
        if SNOW_RE.search(text):
            opts.append("snowy")
        if re.search(r"\b(café|cafe|street|rain|market|window|canal|city|terrace|bridge)\b", text, re.I):
            opts.append("rainy")
        if re.search(r"\b(moonrise|sunset|dusk|harbour|skyline)\b", text, re.I):
            opts.append("golden")
        return opts
    if DUSK_RE.search(text):
        return ["blue_hour", "night", "golden"]
    if SNOW_RE.search(text):
        opts = ["snowy", "morning", "midday", "blue_hour", "night"]
        if indoor:
            opts.append("rainy")
        return opts
    if SUN_RE.search(scene["title"]):
        return ["golden", "morning", "blue_hour"]
    if DAY_ONLY_RE.search(text):
        opts = ["morning", "midday", "golden"]
        if not re.search(r"\b(butterfl|bee|hummingbird|dragonfl)", text, re.I):
            opts.append("blue_hour")
        if indoor:
            opts.append("rainy")
        return opts
    opts = ["morning", "midday", "golden", "blue_hour", "night"]
    if indoor:
        opts += ["rainy", "snowy"]
    if re.search(r"\brain", text, re.I):
        opts.append("rainy")
    return opts


def assign(scenes: list[dict], category: str) -> list[str]:
    cap = max(1, math.floor(len(scenes) * MAX_SHARE))
    opts = [allowed(s, category) for s in scenes]
    order = sorted(range(len(scenes)), key=lambda i: len(opts[i]))  # most constrained first
    counts: Counter = Counter()
    out = [None] * len(scenes)
    rotation = list(PALETTES)
    for k, i in enumerate(order):
        choices = sorted(opts[i], key=lambda p: (counts[p] >= cap, counts[p], (rotation.index(p) - k) % 7))
        p = choices[0]
        out[i] = p
        counts[p] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    doc = yaml.safe_load(PROMPTS.read_text())
    doc["style"] = ("Richly detailed digital painting, storybook illustration quality. Vivid, saturated but "
                    "easy-on-the-eye colours; luminous, appealing light that follows the light and palette given above; "
                    "cheerful, peaceful, cozy atmosphere. Jigsaw-friendly composition: fine detail and texture in "
                    "every region of the picture, no large empty sky or single-colour areas; the main subject is "
                    "near the centre so the picture also works as a square crop. Original scene, not imitating any "
                    "existing artwork, film, game or app.")
    doc["palettes"] = PALETTES
    worst = 0.0
    for group in doc.get("categories", []) + doc.get("events", []):
        cat = group["id"]
        if cat in HERO:
            group["directive"] = HERO[cat]
        scenes = group["scenes"]
        for s in scenes:
            s.setdefault("basePrompt", s["prompt"])
            text = f"{s['title']} {s['basePrompt']}"
            keep = bool(NIGHT_RE.search(s["title"]) or DUSK_RE.search(s["title"]) or SUN_RE.search(s["title"]))
            s["prompt"] = strip_light(s["basePrompt"], keep)
            s["guards"] = [g for rx, g in GUARDS if rx.search(text)]
        palette = assign(scenes, cat)
        for s, p in zip(scenes, palette):
            s["palette"] = p
        c = Counter(palette)
        share = max(c.values()) / len(scenes)
        worst = max(worst, share)
        print(f"{cat:18s} " + " ".join(f"{k}:{c[k]}" for k in PALETTES) + f"   max {share:.0%}")
    print(f"worst share {worst:.0%}")
    if not args.check:
        PROMPTS.write_text("# Jiglume AI illustration prompts (tools/generate_ai.py). Palettes and guards are\n"
                           "# assigned by tools/assign_palettes.py; edit basePrompt, then re-run it.\n" +
                           yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110))
    return 0 if worst <= MAX_SHARE + 1e-9 else 1


if __name__ == "__main__":
    sys.exit(main())
