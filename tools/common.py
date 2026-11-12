"""Shared helpers for the jiglume-content tools.

Only Pillow and numpy are required (see tools/requirements.txt).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.json"
MANIFEST = ROOT / "manifest.json"
LICENSES = ROOT / "LICENSES.md"
INBOX = ROOT / "inbox"
PHASH_INDEX = ROOT / "tools" / "phash_index.json"

SCHEMA_VERSION = 1
REPO = "gemixlabss/jiglume-content"
USER_AGENT = f"JiglumeContentTools/1.0 (https://github.com/{REPO})"

# Image processing rules.
FULL_LONG_SIDE = 4096  # a 3:2 photo then keeps ≥ MIN_CELL_PIXELS per cell at 1000 pieces after the fill crop
THUMB_LONG_SIDE = 640  # 2-column grids on 3× phones stay sharp
# Every catalog image must stay sharp at 1000 pieces after the app crops it to
# fill the board (3:4 on phones, up to 1:1 on tablets): at least this many
# source pixels per cell.
MIN_CELL_PIXELS = 60
MAX_PIECES = 1000
FILL_ASPECTS = (0.75, 1.0)


def cell_pixels(width: int, height: int) -> float:
    """Smallest source pixels per cell at MAX_PIECES over the fill-crop aspects."""
    import math
    worst = float("inf")
    for a in FILL_ASPECTS:
        cw, ch = (height * a, height) if width / height > a else (width, width / a)
        cols = math.sqrt(MAX_PIECES * a)  # rows × cols ≈ MAX_PIECES, cols / rows ≈ a
        worst = min(worst, min(cw, ch) / cols)
    return worst


MIN_LONG_SIDE = 1600  # ≥ the app starter-pack size; Commons originals under 1920 px are accepted down to this
WEBP_QUALITY = 85
THUMB_QUALITY = 80
DUPLICATE_HAMMING = 8  # pHash distance at or below which two images are "the same"

# Category definitions: the single source of truth, written into catalog.json.
# `l10nKey` is resolved by the app's localisation files (20 languages); the
# `names` map is a fallback for app versions that do not know the key yet.
# v5 (AI illustrations). Names in the app's 20 languages (+ "pt" / "zh" for its
# language-code fallback); `l10nKey` is resolved first by apps that know it.
CATEGORIES = [
    {"id": "cute_pets", "order": 1, "icon": "pets", "names": {"en": "Cute Pets", "tr": "Sevimli Dostlar", "de": "Süße Haustiere", "fr": "Adorables compagnons", "es": "Mascotas adorables", "pt-BR": "Pets fofos", "it": "Cuccioli adorabili", "ru": "Милые питомцы", "ar": "حيوانات أليفة لطيفة", "ja": "かわいいペット", "ko": "귀여운 반려동물", "zh-Hans": "可爱萌宠", "hi": "प्यारे पालतू", "id": "Hewan Peliharaan Lucu", "nl": "Lieve huisdieren", "pl": "Urocze zwierzaki", "uk": "Милі улюбленці", "vi": "Thú cưng đáng yêu", "th": "สัตว์เลี้ยงน่ารัก", "sv": "Söta husdjur", "pt": "Pets fofos", "zh": "可爱萌宠"}},
    {"id": "wildlife", "order": 2, "icon": "cruelty_free", "names": {"en": "Wildlife", "tr": "Vahşi Doğa", "de": "Wildtiere", "fr": "Animaux sauvages", "es": "Vida salvaje", "pt-BR": "Vida selvagem", "it": "Animali selvatici", "ru": "Дикая природа", "ar": "الحياة البرية", "ja": "野生動物", "ko": "야생 동물", "zh-Hans": "野生动物", "hi": "वन्यजीव", "id": "Satwa Liar", "nl": "Wilde dieren", "pl": "Dzika przyroda", "uk": "Дика природа", "vi": "Động vật hoang dã", "th": "สัตว์ป่า", "sv": "Vilda djur", "pt": "Vida selvagem", "zh": "野生动物"}},
    {"id": "birds_butterflies", "order": 3, "icon": "emoji_nature", "names": {"en": "Birds & Butterflies", "tr": "Kuşlar ve Kelebekler", "de": "Vögel & Schmetterlinge", "fr": "Oiseaux et papillons", "es": "Aves y mariposas", "pt-BR": "Pássaros e borboletas", "it": "Uccelli e farfalle", "ru": "Птицы и бабочки", "ar": "طيور وفراشات", "ja": "鳥と蝶", "ko": "새와 나비", "zh-Hans": "鸟与蝴蝶", "hi": "पक्षी और तितलियाँ", "id": "Burung & Kupu-kupu", "nl": "Vogels & vlinders", "pl": "Ptaki i motyle", "uk": "Птахи й метелики", "vi": "Chim và bướm", "th": "นกและผีเสื้อ", "sv": "Fåglar & fjärilar", "pt": "Pássaros e borboletas", "zh": "鸟与蝴蝶"}},
    {"id": "flowers_gardens", "order": 4, "icon": "local_florist", "names": {"en": "Flowers & Gardens", "tr": "Çiçekler ve Bahçeler", "de": "Blumen & Gärten", "fr": "Fleurs et jardins", "es": "Flores y jardines", "pt-BR": "Flores e jardins", "it": "Fiori e giardini", "ru": "Цветы и сады", "ar": "زهور وحدائق", "ja": "花と庭", "ko": "꽃과 정원", "zh-Hans": "花与花园", "hi": "फूल और बगीचे", "id": "Bunga & Taman", "nl": "Bloemen & tuinen", "pl": "Kwiaty i ogrody", "uk": "Квіти та сади", "vi": "Hoa và khu vườn", "th": "ดอกไม้และสวน", "sv": "Blommor & trädgårdar", "pt": "Flores e jardins", "zh": "花与花园"}},
    {"id": "landscapes", "order": 5, "icon": "landscape", "names": {"en": "Landscapes", "tr": "Manzaralar", "de": "Landschaften", "fr": "Paysages", "es": "Paisajes", "pt-BR": "Paisagens", "it": "Paesaggi", "ru": "Пейзажи", "ar": "مناظر طبيعية", "ja": "風景", "ko": "풍경", "zh-Hans": "风景", "hi": "प्राकृतिक दृश्य", "id": "Pemandangan", "nl": "Landschappen", "pl": "Krajobrazy", "uk": "Краєвиди", "vi": "Phong cảnh", "th": "ทิวทัศน์", "sv": "Landskap", "pt": "Paisagens", "zh": "风景"}},
    {"id": "sea_coast", "order": 6, "icon": "sailing", "names": {"en": "Sea & Coast", "tr": "Deniz ve Kıyı", "de": "Meer & Küste", "fr": "Mer et côte", "es": "Mar y costa", "pt-BR": "Mar e litoral", "it": "Mare e costa", "ru": "Море и побережье", "ar": "البحر والساحل", "ja": "海と海岸", "ko": "바다와 해안", "zh-Hans": "海洋与海岸", "hi": "समुद्र और तट", "id": "Laut & Pantai", "nl": "Zee & kust", "pl": "Morze i wybrzeże", "uk": "Море й узбережжя", "vi": "Biển và bờ biển", "th": "ทะเลและชายฝั่ง", "sv": "Hav & kust", "pt": "Mar e litoral", "zh": "海洋与海岸"}},
    {"id": "colorful_streets", "order": 7, "icon": "storefront", "names": {"en": "Colourful Streets", "tr": "Renkli Sokaklar", "de": "Bunte Gassen", "fr": "Rues colorées", "es": "Calles coloridas", "pt-BR": "Ruas coloridas", "it": "Strade colorate", "ru": "Яркие улочки", "ar": "شوارع ملونة", "ja": "カラフルな街並み", "ko": "알록달록 거리", "zh-Hans": "多彩街巷", "hi": "रंगीन गलियाँ", "id": "Jalan Penuh Warna", "nl": "Kleurrijke straatjes", "pl": "Kolorowe uliczki", "uk": "Яскраві вулички", "vi": "Phố phường rực rỡ", "th": "ถนนหลากสี", "sv": "Färgglada gator", "pt": "Ruas coloridas", "zh": "多彩街巷"}},
    {"id": "world_places", "order": 8, "icon": "public", "names": {"en": "Around the World", "tr": "Dünyadan Yerler", "de": "Rund um die Welt", "fr": "Tour du monde", "es": "Lugares del mundo", "pt-BR": "Pelo mundo", "it": "Giro del mondo", "ru": "Вокруг света", "ar": "حول العالم", "ja": "世界の名所", "ko": "세계 여행", "zh-Hans": "环游世界", "hi": "दुनिया की सैर", "id": "Keliling Dunia", "nl": "De wereld rond", "pl": "Dookoła świata", "uk": "Навколо світу", "vi": "Vòng quanh thế giới", "th": "รอบโลก", "sv": "Jorden runt", "pt": "Pelo mundo", "zh": "环游世界"}},
    {"id": "treats", "order": 9, "icon": "cake", "names": {"en": "Sweet Treats", "tr": "Lezzetler", "de": "Leckereien", "fr": "Gourmandises", "es": "Delicias", "pt-BR": "Delícias", "it": "Golosità", "ru": "Вкусности", "ar": "حلويات ومأكولات", "ja": "スイーツ・ごちそう", "ko": "달콤한 간식", "zh-Hans": "美食甜点", "hi": "मिठाइयाँ और व्यंजन", "id": "Kudapan Lezat", "nl": "Lekkernijen", "pl": "Smakołyki", "uk": "Смаколики", "vi": "Món ngon", "th": "ของอร่อย", "sv": "Godsaker", "pt": "Delícias", "zh": "美食甜点"}},
    {"id": "cozy_corners", "order": 10, "icon": "weekend", "names": {"en": "Cozy Corners", "tr": "Sıcak Köşeler", "de": "Gemütliche Ecken", "fr": "Coins douillets", "es": "Rincones acogedores", "pt-BR": "Cantinhos aconchegantes", "it": "Angoli accoglienti", "ru": "Уютные уголки", "ar": "زوايا دافئة", "ja": "くつろぎの空間", "ko": "아늑한 공간", "zh-Hans": "温馨角落", "hi": "आरामदायक कोने", "id": "Sudut Nyaman", "nl": "Knusse hoekjes", "pl": "Przytulne zakątki", "uk": "Затишні куточки", "vi": "Góc ấm cúng", "th": "มุมอบอุ่น", "sv": "Mysiga hörn", "pt": "Cantinhos aconchegantes", "zh": "温馨角落"}},
    {"id": "nostalgia", "order": 11, "icon": "radio", "names": {"en": "Nostalgia", "tr": "Nostalji", "de": "Nostalgie", "fr": "Nostalgie", "es": "Nostalgia", "pt-BR": "Nostalgia", "it": "Nostalgia", "ru": "Ностальгия", "ar": "حنين للماضي", "ja": "ノスタルジー", "ko": "추억의 풍경", "zh-Hans": "怀旧时光", "hi": "पुरानी यादें", "id": "Nostalgia", "nl": "Nostalgie", "pl": "Nostalgia", "uk": "Ностальгія", "vi": "Hoài niệm", "th": "ย้อนวันวาน", "sv": "Nostalgi", "pt": "Nostalgia", "zh": "怀旧时光"}},
    {"id": "fairytale", "order": 12, "icon": "castle", "names": {"en": "Fairy Tales", "tr": "Masal Dünyası", "de": "Märchenwelt", "fr": "Contes de fées", "es": "Cuentos de hadas", "pt-BR": "Contos de fadas", "it": "Fiabe", "ru": "Сказки", "ar": "عالم الحكايات", "ja": "おとぎの国", "ko": "동화 나라", "zh-Hans": "童话世界", "hi": "परीकथाएँ", "id": "Negeri Dongeng", "nl": "Sprookjes", "pl": "Baśnie", "uk": "Казки", "vi": "Thế giới cổ tích", "th": "เทพนิยาย", "sv": "Sagor", "pt": "Contos de fadas", "zh": "童话世界"}},
    {"id": "night_stars", "order": 13, "icon": "nights_stay", "names": {"en": "Night & Stars", "tr": "Gece ve Yıldızlar", "de": "Nacht & Sterne", "fr": "Nuit et étoiles", "es": "Noche y estrellas", "pt-BR": "Noite e estrelas", "it": "Notte e stelle", "ru": "Ночь и звёзды", "ar": "الليل والنجوم", "ja": "夜と星", "ko": "밤과 별", "zh-Hans": "夜与星空", "hi": "रात और तारे", "id": "Malam & Bintang", "nl": "Nacht & sterren", "pl": "Noc i gwiazdy", "uk": "Ніч і зорі", "vi": "Đêm và sao", "th": "ราตรีและดวงดาว", "sv": "Natt & stjärnor", "pt": "Noite e estrelas", "zh": "夜与星空"}},
    {"id": "four_seasons", "order": 14, "icon": "park", "names": {"en": "Four Seasons", "tr": "Dört Mevsim", "de": "Vier Jahreszeiten", "fr": "Quatre saisons", "es": "Cuatro estaciones", "pt-BR": "Quatro estações", "it": "Quattro stagioni", "ru": "Времена года", "ar": "الفصول الأربعة", "ja": "四季", "ko": "사계절", "zh-Hans": "四季", "hi": "चार ऋतुएँ", "id": "Empat Musim", "nl": "Vier seizoenen", "pl": "Cztery pory roku", "uk": "Пори року", "vi": "Bốn mùa", "th": "สี่ฤดู", "sv": "Fyra årstider", "pt": "Quatro estações", "zh": "四季"}},
    {"id": "art_styles", "order": 15, "icon": "palette", "names": {"en": "Art Styles", "tr": "Sanat Akımları", "de": "Kunststile", "fr": "Styles artistiques", "es": "Estilos artísticos", "pt-BR": "Estilos artísticos", "it": "Stili artistici", "ru": "Художественные стили", "ar": "أساليب فنية", "ja": "アートスタイル", "ko": "예술 양식", "zh-Hans": "艺术风格", "hi": "कला शैलियाँ", "id": "Gaya Seni", "nl": "Kunststijlen", "pl": "Style artystyczne", "uk": "Мистецькі стилі", "vi": "Phong cách nghệ thuật", "th": "สไตล์ศิลปะ", "sv": "Konststilar", "pt": "Estilos artísticos", "zh": "艺术风格"}},
    {"id": "collections", "order": 16, "icon": "inventory", "names": {"en": "Collections", "tr": "Koleksiyonlar", "de": "Sammlungen", "fr": "Collections", "es": "Colecciones", "pt-BR": "Coleções", "it": "Collezioni", "ru": "Коллекции", "ar": "مجموعات", "ja": "コレクション", "ko": "컬렉션", "zh-Hans": "收藏品", "hi": "संग्रह", "id": "Koleksi", "nl": "Verzamelingen", "pl": "Kolekcje", "uk": "Колекції", "vi": "Bộ sưu tập", "th": "ของสะสม", "sv": "Samlingar", "pt": "Coleções", "zh": "收藏品"}},
    {"id": "winter_tale", "order": 17, "icon": "ac_unit", "names": {"en": "Winter Tale", "tr": "Kış Masalı", "de": "Wintermärchen", "fr": "Conte d'hiver", "es": "Cuento de invierno", "pt-BR": "Conto de inverno", "it": "Racconto d'inverno", "ru": "Зимняя сказка", "ar": "حكاية الشتاء", "ja": "冬の物語", "ko": "겨울 이야기", "zh-Hans": "冬日童话", "hi": "सर्दियों की कहानी", "id": "Kisah Musim Dingin", "nl": "Wintersprookje", "pl": "Zimowa opowieść", "uk": "Зимова казка", "vi": "Chuyện mùa đông", "th": "นิทานฤดูหนาว", "sv": "Vintersaga", "pt": "Conto de inverno", "zh": "冬日童话"}},
]
EVENT_CATEGORIES = {"winter_tale"}
for _c in CATEGORIES:
    _c["l10nKey"] = f"category_{_c['id']}"
CATEGORY_IDS = {c["id"] for c in CATEGORIES}

# Photo archive v1–v4.1 (no longer in the catalog; kept for the legacy tools).
LEGACY_CATEGORIES = [
    {"id": "nature", "order": 1, "icon": "forest", "names": {"en": "Nature", "tr": "Doğa"}},
    {"id": "animals", "order": 2, "icon": "pets", "names": {"en": "Animals", "tr": "Hayvanlar"}},
    {"id": "cities", "order": 3, "icon": "location_city", "names": {"en": "Cities", "tr": "Şehirler"}},
    {"id": "travel", "order": 4, "icon": "flight_takeoff", "names": {"en": "Travel", "tr": "Seyahat"}},
    {"id": "sea", "order": 5, "icon": "beach_access", "names": {"en": "Sea & Beach", "tr": "Deniz & Sahil"}},
    {"id": "mountains", "order": 6, "icon": "landscape", "names": {"en": "Mountains", "tr": "Dağlar"}},
    {"id": "flowers", "order": 7, "icon": "local_florist", "names": {"en": "Flowers", "tr": "Çiçekler"}},
    {"id": "food", "order": 8, "icon": "restaurant", "names": {"en": "Food", "tr": "Yemek"}},
    {"id": "art", "order": 9, "icon": "palette", "names": {"en": "Art", "tr": "Sanat"}},
    {"id": "architecture", "order": 10, "icon": "account_balance", "names": {"en": "Architecture", "tr": "Mimari"}},
    {"id": "night", "order": 11, "icon": "nights_stay", "names": {"en": "Night & Sky", "tr": "Gece & Gökyüzü"}},
    {"id": "seasons", "order": 12, "icon": "eco", "names": {"en": "Seasons", "tr": "Mevsimler"}},
    {"id": "patterns", "order": 13, "icon": "texture", "names": {"en": "Colorful & Patterns", "tr": "Renkli & Desenler"}},
    {"id": "vehicles", "order": 14, "icon": "directions_railway", "names": {"en": "Vehicles", "tr": "Araçlar"}},
]



# --------------------------------------------------------------------------
# Licences

LICENSE_URLS = {
    "Jiglume": "https://github.com/gemixlabss/jiglume-content/blob/main/LICENSES.md",
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public domain": "https://creativecommons.org/publicdomain/mark/1.0/",
    "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "Pexels License": "https://www.pexels.com/license/",
}
ATTRIBUTION_LICENSES = {"CC BY 2.0", "CC BY 3.0", "CC BY 4.0"}


def normalize_license(short_name: str | None) -> str | None:
    """Maps a Commons `LicenseShortName` to an accepted licence, or None.

    Accepted: CC0, public domain (PD-*, PDM, "Public domain"), CC BY 2.0 /
    3.0 / 4.0. Everything else is rejected — notably any BY-SA, NC or ND
    variant, GFDL, "fair use" and unknown / empty values. Never guesses.
    """
    if not short_name:
        return None
    s = html.unescape(re.sub(r"<[^>]+>", "", short_name)).strip().lower()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    # Hard rejections first, so "CC BY-SA 4.0" can never match "CC BY 4.0".
    if re.search(r"(^|[^a-z])(sa|nc|nd)([^a-z]|$)", s) or any(
        bad in s for bad in ("share", "noncommercial", "non-commercial", "noderiv", "fair use",
                             "gfdl", "gnu", "copyrighted", "all rights reserved", "unknown")):
        return None
    if s in {"cc0", "cc0 1.0", "cc-zero", "cc zero", "cc0 1.0 universal"}:
        return "CC0 1.0"
    if s in {"public domain", "pd", "pdm", "public domain mark", "pdm 1.0", "public domain mark 1.0"} or s.startswith("pd-"):
        return "Public domain"
    m = re.fullmatch(r"cc[ -]by[ -]([234])\.0", s)
    if m:
        return f"CC BY {m.group(1)}.0"
    return None


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


# Words that suggest a recognisable person, a logo/brand or a commercial
# product is prominent. Matched against title, description and categories.
EXCLUDE_WORDS = [
    "portrait", "people", "person", "persons", "woman", "women", "man ", " men", "girl", "boy",
    "child", "children", "kid", "crowd", "face", "faces", "selfie", "model", "bride", "groom",
    "wedding", "tourist", "tourists", "cyclist", "runner", "player", "musician", "dancer",
    "logo", "logos", "brand", "trademark", "advert", "billboard", "packaging", "product",
    "label", "store", "shop", "supermarket", "restaurant interior", "nude", "nudity",
    "protest", "demonstration", "military", "weapon", "gun", "police", "funeral", "accident",
    "fire truck", "ambulance", "car show", "auto show", "mercedes", "bmw", "toyota", "ford ",
    "coca", "pepsi", "mcdonald", "starbucks", "airline", "airways", "boeing", "airbus",
]


def looks_excluded(*texts: str) -> str | None:
    hay = " " + " ".join(t.lower() for t in texts if t) + " "
    for w in EXCLUDE_WORDS:
        if w in hay:
            return w.strip()
    return None


# --------------------------------------------------------------------------
# Catalog I/O

def empty_catalog() -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "contentVersion": None, "generatedAt": None,
            "categories": CATEGORIES, "puzzles": []}


def load_catalog() -> dict:
    if CATALOG.exists():
        cat = json.loads(CATALOG.read_text(encoding="utf-8"))
        cat["categories"] = CATEGORIES  # definitions live in code
        return cat
    return empty_catalog()


def save_catalog(cat: dict) -> None:
    cat["schemaVersion"] = SCHEMA_VERSION
    cat["generatedAt"] = date.today().isoformat()
    cat["puzzles"].sort(key=lambda p: (next(c["order"] for c in CATEGORIES if c["id"] == p["categoryId"]), p["id"]))
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def review_rejected_ids() -> set[str]:
    """Ids rejected in manual review (tools/review_rejected.json): never re-fetched."""
    p = ROOT / "tools" / "review_rejected.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def category_count(category: str) -> int:
    """Images a category already has: published in the catalog + waiting in inbox/."""
    published = sum(1 for p in load_catalog()["puzzles"] if p["categoryId"] == category)
    return published + len(list((INBOX / category).glob("*.json")))


def load_phash_index() -> dict:
    return json.loads(PHASH_INDEX.read_text()) if PHASH_INDEX.exists() else {}


def save_phash_index(index: dict) -> None:
    PHASH_INDEX.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# HTTP with polite retries (Wikimedia & museum APIs rate-limit shared IPs)

def http_get(url: str, *, params: dict | None = None, headers: dict | None = None,
             attempts: int = 12, timeout: int = 60) -> bytes:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    delay = 4.0
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            retry = e.headers.get("Retry-After")
            wait = max(delay, float(retry) if retry and retry.isdigit() else 0)
            log(f"  HTTP {e.code}, retrying in {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 1.6, 90)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == attempts - 1:
                raise
            log(f"  network error {e}, retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 1.6, 90)
    raise RuntimeError("unreachable")


def http_json(url: str, **kw) -> dict:
    return json.loads(http_get(url, **kw))


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
