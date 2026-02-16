# generator.py
import requests
import csv
import re
import time
from pathlib import Path
from requests.exceptions import RequestException, Timeout
import json
from wisdomguild_scraper import fetch_text_from_wisdom_guild
import logging
logger = logging.getLogger(__name__)

SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"

# -------------------------
# Session (for performance optimization)
# -------------------------
session = requests.Session()
session.headers.update({
    "User-Agent": "CommanderTool/1.0"
})


# -------------------------
# Utilities
# -------------------------

def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", text)


def parse_decklist(path: Path):
    names = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            names.append(re.sub(r"^\d+\s+", "", line))
    return names


# -------------------------
# Scryfall
# -------------------------

def safe_get(session, url, *, params=None, timeout=5, retries=2, sleep=1):
    """
    Safe wrapper around requests.get
    Returns None on failure
    """
    time.sleep(0.2)
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, timeout=timeout)
            return r
        except (Timeout, RequestException) as e:
            logger.warning(f"[WARN] GET failed ({attempt+1}/{retries+1}): {url}")
            if attempt < retries:
                time.sleep(sleep)
            else:
                return None


def search_card_images(card_name: str, languages=("ja",)):
    results = []
    search_name = card_name

    with requests.Session() as session:
        base = None
        for key in ("exact", "fuzzy"):
            r = safe_get(
                session,
                "https://api.scryfall.com/cards/named",
                params={key: search_name},
                timeout=5,
            )
            if r and r.status_code == 200:
                base = r.json()
                break

        if not base:
            return []

        oracle_id = base.get("oracle_id")
        if not oracle_id:
            return []

        for lang in languages:
            url = "https://api.scryfall.com/cards/search"
            params = {
                "q": f"oracleid:{oracle_id} lang:{lang}",
                "unique": "prints"
            }

            while url:
                r = safe_get(session, url, params=params, timeout=5)
                if not r or r.status_code != 200:
                    break

                data = r.json()
                for card in data.get("data", []):
                    temp_oracle_id = card.get("oracle_id")
                    if not temp_oracle_id:
                        continue
                    entry = {
                        "card_id": card["id"],
                        "oracle_id": card["oracle_id"],
                        "lang": card["lang"],
                        "name": card["name"],
                        "faces": []
                    }


                    # ---- Single-faced card ----
                    if "image_uris" in card:
                        entry["faces"].append({
                            "face_index": 0,
                            "side": "front",
                            "name": card["name"],
                            "image_normal": card["image_uris"]["normal"],
                            "image_small": card["image_uris"].get("small"),
                        })

                    # ---- Double-faced / Adventure card ----
                    elif "card_faces" in card:
                        for i, face in enumerate(card["card_faces"]):
                            if "image_uris" in face:
                                entry["faces"].append({
                                    "face_index": i,                  
                                    "side": "front" if i == 0 else "back",
                                    "name": face["name"],
                                    "image_normal": face["image_uris"]["normal"],
                                    "image_small": face["image_uris"]["small"],
                                })


                    if entry["faces"]:
                        results.append(entry)

                url = data.get("next_page")
                params = None

    return results

def fetch_card(card_name: str, lang: str = "ja"):
    """
    Fetch a card, prioritizing Japanese if available.
    Falls back to English if a Japanese version is not found.
    Returns None only if the card cannot be found at all.
    """
    base = None
    for key in ("exact", "fuzzy"):
        r = safe_get(
            session,
            SCRYFALL_NAMED_URL,
            params={key: card_name},
            timeout=5,
        )
        if r and r.status_code == 200:
            base = r.json()
            break

    if not base:
        logger.warning(f"[WARN] fetch_card failed: {card_name}")
        return None

    # --- Prefer Japanese ---
    if lang == "ja":
        oracle_id = base.get("oracle_id")
        if not oracle_id:
            return []
        r = safe_get(
            session,
            "https://api.scryfall.com/cards/search",
            params={"q": f"oracleid:{oracle_id} lang:ja"},
            timeout=5,
        )
        if r and r.status_code == 200:
            data = r.json()
            if data.get("total_cards", 0) > 0:
                # Return the Japanese card if it exists
                return data["data"][0]

        # Fall back to the English card (base) if Japanese is not available
        return base if base else None

    # --- English specified ---
    return base




def download_image(url: str, path: Path):
    # Skip if the file already exists
    if path.exists():
        return False   # Not downloaded

    r = requests.get(url)
    r.raise_for_status()
    path.write_bytes(r.content)
    return True        # Downloaded as a new file



def join_room_text(card):
    texts = []
    for face in card.get("card_faces", []):
        t = face.get("printed_text") or face.get("oracle_text")
        if t:
            texts.append(t)
    return "\n\n".join(texts)

def safe_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "", text)  # Remove invalid filename characters
    text = re.sub(r"\s+", "_", text)          # Replace whitespace with underscores
    return text


def looks_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ン一-龯ー]", text))

def fetch_japanese_text_by_oracle_id(oracle_id: str) -> str:
    if not oracle_id:
        return ""

    url = "https://api.scryfall.com/cards/search"
    params = {
        "q": f"oracleid:{oracle_id} lang:ja",
        "unique": "prints",
    }

    while url:
        r = safe_get(session, url, params=params, timeout=5)
        if not r or r.status_code != 200:
            break

        data = r.json()
        for card in data.get("data", []):
            # ---- single-faced ----
            if "card_faces" not in card:
                t = card.get("printed_text")
                if t and looks_japanese(t):
                    return t
            # ---- double-faced ----
            else:
                texts = []
                for face in card["card_faces"]:
                    t = face.get("printed_text")
                    if t and looks_japanese(t):
                        texts.append(t)
                if texts:
                    return "\n\n".join(texts)

        url = data.get("next_page")
        params = None

    return ""


def get_card_text(card, lang: str = "ja"):
    if card is None:
        return ""

    # ---- English ----
    if lang == "en":
        texts = []
        if "card_faces" in card:
            for face in card["card_faces"]:
                t = face.get("oracle_text")
                if t:
                    texts.append(t)
        else:
            t = card.get("oracle_text")
            if t:
                texts.append(t)
        return "\n\n".join(texts)

    # ---- Japanese ----
    texts = []
    has_printed = False

    def pick_ja(face_or_card):
        nonlocal has_printed
        if face_or_card.get("printed_text"):
            has_printed = True
            return face_or_card["printed_text"]
        return None

    # ① try current card printed_text only
    if "card_faces" in card:
        for face in card["card_faces"]:
            t = pick_ja(face)
            if t:
                texts.append(t)
    else:
        t = pick_ja(card)
        if t:
            texts.append(t)

    # ③ fallback: other JP printings
    oracle_id = card.get("oracle_id")
    card_name = card.get("name", "")

    if not oracle_id:
        texts = []
        if "card_faces" in card:
            for face in card["card_faces"]:
                t = face.get("printed_text") or face.get("oracle_text")
                if t:
                    texts.append(t)
        else:
            t = card.get("printed_text") or card.get("oracle_text")
            if t:
                texts.append(t)
        return "\n\n".join(texts)

    jp_txt = fetch_japanese_text_by_oracle_id(oracle_id)
    logging.info(card_name + ":" + jp_txt)
    if looks_japanese(jp_txt):
        return jp_txt
    
    return card.get("oracle_text") or ""


def fetch_japanese_name_by_oracle_id(oracle_id: str) -> str:
    if not oracle_id:
        return ""

    url = "https://api.scryfall.com/cards/search"
    params = {
        "q": f"oracleid:{oracle_id} lang:ja",
        "unique": "prints",
    }

    while url:
        r = safe_get(session, url, params=params, timeout=5)
        if not r or r.status_code != 200:
            break

        data = r.json()
        for card in data.get("data", []):
            # ★ card-level printed_name（単面用）
            pn = card.get("printed_name")
            if pn and looks_japanese(pn):
                return pn

            # ★ Adventure / MDFC 用
            if "card_faces" in card:
                names = []
                for face in card["card_faces"]:
                    fn = face.get("printed_name")
                    if fn and looks_japanese(fn):
                        names.append(fn)
                if len(names) >= 2:
                    return " // ".join(names)

        url = data.get("next_page")
        params = None

    return ""


def get_card_name(card, lang: str = "ja"):
    if card is None:
        return ""

    # ---- English ----
    if lang == "en":
        return card.get("name", "")

    # ---- Single-faced ----
    if not ("card_faces" in card):
        name = card.get("printed_name")
        if name and looks_japanese(name):
            return name
        else:
            en_name = card["name"]
            [jp_name, jp_txt] = fetch_text_from_wisdom_guild(en_name, "front")
            if looks_japanese(jp_name):
                return jp_name


    # ---- Adventure / MDFC ----
    if "card_faces" in card:
        names = []
        has_english = False

        for face in card["card_faces"]:
            pn = face.get("printed_name")
            if pn and looks_japanese(pn):
                names.append(pn)
            else:
                has_english = True

        if has_english:
            names = []
            en_name = card["name"]
            [jp_name, jp_txt] = fetch_text_from_wisdom_guild(en_name, "front")
            names.append(jp_name)
            [jp_name, jp_txt] = fetch_text_from_wisdom_guild(en_name, "back")
            names.append(jp_name)
        
        if looks_japanese(" // ".join(names)):
            return " // ".join(names)

    return card.get("name", "")


def get_card_autocomplete(query: str) -> list:
    """
    Fetch autocomplete suggestions from Scryfall.
    Supports Japanese by falling back to search API.
    """
    if not query or len(query) < 2:
        return []

    if looks_japanese(query):
        # Scryfall's /autocomplete is English only.
        # For Japanese, we use /search with a name fragment.
        search_q = f"name:{query} lang:ja"
        r = safe_get(
            session,
            "https://api.scryfall.com/cards/search",
            params={"q": search_q, "unique": "cards"},
            timeout=3
        )
        if r and r.status_code == 200:
            data = r.json().get("data", [])
            results = []
            for card in data:
                # Prioritize Japanese printed name
                name = card.get("printed_name") or card["name"]
                if name not in results:
                    results.append(name)
            logger.info(f"Autocomplete JA: {query} -> {results[:5]}")
            return results[:20] # Limit suggestions
        return []
    else:
        # Standard English autocomplete
        r = safe_get(
            session,
            "https://api.scryfall.com/cards/autocomplete",
            params={"q": query},
            timeout=3
        )
        if r and r.status_code == 200:
            return r.json().get("data", [])
    
    return []


def create_card_row(name: str, out_dir: Path, language: str = "ja"):
    """
    Fetch card data and download images for a single card name.
    Returns a row dictionary compatible with the CSV schema.
    """
    card = fetch_card(name, language)
    if card is None:
        return None

    en = card["name"]
    ja = card.get("printed_name", "")
    safe_en = safe_filename(en)

    row = {
        "card_file_front": "",
        "card_file_back": "",
        "name_front": "",
        "name_back": "",
        "name_ja": get_card_name(card, "ja"),
        "name_en": get_card_name(card, "en"),
        "type_front": "",
        "type_back": "",
        "mana_cost": card.get("mana_cost", ""),
        "text_front_ja": "",
        "text_front_en": "",
        "text_back_ja": "",
        "text_back_en": "",
        "Commander_A": "",
        "Commander_B": "",
        "Companion": "",
    }

    # 1. Image Download & Basic Info (SFC vs DFC)
    if "image_uris" in card:
        # Single-faced
        row["card_file_front"] = f"{safe_en}_front.jpg"
        download_image(card["image_uris"]["normal"], out_dir / row["card_file_front"])
        
        row["name_front"] = en
        row["type_front"] = card.get("type_line", "")
        
        row["text_front_en"] = get_card_text(card, "en")
        row["text_front_ja"] = get_card_text(card, "ja")
        if not looks_japanese(row["text_front_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
            if looks_japanese(jp_txt):
                row["text_front_ja"] = jp_txt
    
    elif "card_faces" in card and len(card["card_faces"]) >= 2:
        # Double-faced
        face1, face2 = card["card_faces"]
        row["card_file_front"] = f"{safe_en}_front.jpg"
        row["card_file_back"] = f"{safe_en}_back.jpg"
        
        download_image(face1["image_uris"]["normal"], out_dir / row["card_file_front"])
        download_image(face2["image_uris"]["normal"], out_dir / row["card_file_back"])
        
        row["name_front"] = face1.get("printed_name", face1["name"])
        row["name_back"] = face2.get("printed_name", face2["name"])
        row["type_front"] = face1.get("type_line", "")
        row["type_back"] = face2.get("type_line", "")
        
        row["text_front_en"] = get_card_text(face1, "en")
        row["text_back_en"] = get_card_text(face2, "en")
        row["text_front_ja"] = get_card_text(face1, "ja")
        if not looks_japanese(row["text_front_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
            if looks_japanese(jp_txt):
                row["text_front_ja"] = jp_txt
        
        row["text_back_ja"] = get_card_text(face2, "ja")
        if not looks_japanese(row["text_back_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "back")
            if looks_japanese(jp_txt):
                row["text_back_ja"] = jp_txt
    else:
        logger.info(f"Card format not supported: {en}")
        return None

    return row

def generate_from_txt(
    txt_path: Path,
    out_dir: Path,
    language="ja",
    progress_callback=None
):
    names = parse_decklist(txt_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{txt_path.stem}.csv"
    rows = []
    total = len(names)

    for i, name in enumerate(names, 1):
        if progress_callback:
            progress_callback(i, total, name)
            
        row = create_card_row(name, out_dir, language)
        if row:
            rows.append(row)
        
        time.sleep(0.1)

    if not rows:
        return None

    fieldnames = [
        "card_file_front", "card_file_back", "name_front", "name_back",
        "name_ja", "name_en", "type_front", "type_back", "mana_cost",
        "text_front_ja", "text_front_en", "text_back_ja", "text_back_en",
        "Commander_A", "Commander_B", "Companion",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path
