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
    items = [] # List of {"name": str, "count": int}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # e.g., "4 Sol Ring" or "Sol Ring"
            match = re.match(r"^(\d+)\s+(.*)$", line)
            if match:
                count = int(match.group(1))
                name = match.group(2).strip()
            else:
                count = 1
                name = line
            
            items.append({"name": name, "count": count})
    return items


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


def search_card_images(card_name: str, languages=("ja",), is_token: bool = False):
    results = []
    
    with requests.Session() as session:
        # 1. Determine Search Query
        if is_token:
            # Consolidation: Search all tokens with this name in all languages at once
            query = f'is:token name:"{card_name}" lang:any'
        else:
            # Regular cards: First get any version to get the Oracle ID
            oracle_ids = []
            base = None
            for key in ("exact", "fuzzy"):
                r = safe_get(session, "https://api.scryfall.com/cards/named", params={key: card_name}, timeout=5)
                if r and r.status_code == 200:
                    base = r.json()
                    break

            if not base or not base.get("oracle_id"):
                return []
            
            # Consolidation: Search all prints of this Oracle ID in all languages at once
            query = f'oracleid:{base["oracle_id"]} lang:any'

        # 2. Execute Consolidated Search
        url = "https://api.scryfall.com/cards/search"
        params = {
            "q": query,
            "unique": "prints"
        }

        while url:
            r = safe_get(session, url, params=params, timeout=5)
            if not r or r.status_code != 200:
                break

            data = r.json()
            for card in data.get("data", []):
                # Local Filtering: Scryfall 'lang:any' returns everything. 
                # We filter by requested languages here to avoid $O(N*M)$ network requests.
                if card["lang"] not in languages:
                    continue

                entry = {
                    "card_id": card["id"],
                    "oracle_id": card.get("oracle_id"),
                    "lang": card["lang"],
                    "name": card["name"],
                    "power": card.get("power", ""),
                    "toughness": card.get("toughness", ""),
                    "oracle_text": card.get("oracle_text", ""),
                    "faces": []
                }

                # ---- Single-faced card ----
                if "image_uris" in card:
                    entry["faces"].append({
                        "face_index": 0,
                        "side": "front",
                        "name": card["name"],
                        "power": card.get("power", ""),
                        "toughness": card.get("toughness", ""),
                        "oracle_text": card.get("oracle_text", ""),
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
                                "power": face.get("power", ""),
                                "toughness": face.get("toughness", ""),
                                "oracle_text": face.get("oracle_text", ""),
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
            return base # Return base if no oracle_id

        r = safe_get(
            session,
            "https://api.scryfall.com/cards/search",
            params={"q": f"oracleid:{oracle_id} lang:ja", "include_extras": "true"},
            timeout=5,
        )
        if r and r.status_code == 200:
            data = r.json()
            if data.get("total_cards", 0) > 0:
                # Return the Japanese card if it exists
                return data["data"][0]

        # Fall back to the English card (base) if Japanese is not available
        return base

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

def fetch_related_tokens(card, lang):
    """
    Find related tokens in all_parts and fetch their card data.
    Broadens search but strictly filters for Token/Emblem types.
    """
    tokens = []
    seen_oracle_ids = set()

    def is_actual_token(c_data):
        layout = c_data.get("layout", "")
        t_line = c_data.get("type_line", "")
        set_type = c_data.get("set_type", "")
        
        # DEFINITELY NOT a token if it's a standard set release (unless it's a token/promo)
        # Standard set_types that are normal cards: 'core', 'expansion', 'masters', 'commander', 'planechase', 'archenemy', 'vanguard', 'spellbook', 'starter'
        # Token set_types: 'token', 'memorabilia', 'treasure_chest'
        if set_type in ("core", "expansion", "masters", "commander", "starter") and layout not in ("token", "emblem", "double_faced_token"):
            return False
            
        # Layouts that are definitively tokens/emblems
        if layout in ("token", "emblem", "double_faced_token"):
            return True
        # Type line check as fallback
        if "Token" in t_line or "Emblem" in t_line:
            # Still, if it's a normal layout like 'normal', be very suspicious
            if layout == "normal" and set_type in ("core", "expansion", "masters", "commander"):
                return False
            return True
        return False

    # 1. Check all_parts (Reliable but sometimes missed)
    all_parts = card.get("all_parts", [])
    for part in all_parts:
        # Strictly only 'token' component. 
        # 'combo_piece' and 'extra_card' are usually normal cards.
        if part.get("component") == "token":
            token_uri = part.get("uri")
            if token_uri:
                r = safe_get(session, token_uri, timeout=5)
                if r and r.status_code == 200:
                    t_data = r.json()
                    if not is_actual_token(t_data):
                        continue
                        
                    oid = t_data.get("oracle_id")
                    if oid and oid not in seen_oracle_ids:
                        # If we need JA text, fetch it
                        if lang == "ja":
                            ja_token = fetch_card_by_oracle_id(oid, "ja")
                            if ja_token:
                                t_data = ja_token
                        tokens.append(t_data)
                        seen_oracle_ids.add(oid)

    # 2. Fallback: Parse card text for "token" or "emblem" keywords
    txt = card.get("oracle_text", "")
    if "card_faces" in card:
        txt += " ".join(f.get("oracle_text", "") for f in card["card_faces"])
    
    txt_lower = txt.lower()
    if "token" in txt_lower or "emblem" in txt_lower:
        if len(tokens) < 1:
            name_en = card.get("name")
            # Strictly filter for is:token in query
            query = f'is:token "{name_en}"'
            r = safe_get(session, "https://api.scryfall.com/cards/search", params={"q": query}, timeout=5)
            if r and r.status_code == 200:
                data = r.json()
                for t_data in data.get("data", []):
                    if not is_actual_token(t_data):
                        continue
                    oid = t_data.get("oracle_id")
                    if oid and oid not in seen_oracle_ids:
                        if lang == "ja":
                            ja_t = fetch_card_by_oracle_id(oid, "ja")
                            if ja_t: t_data = ja_t
                        tokens.append(t_data)
                        seen_oracle_ids.add(oid)

            # Special check for Emblems
            if "emblem" in txt_lower and not any("Emblem" in t.get("type_line", "") for t in tokens):
                query_emblem = f't:emblem "{name_en}"'
                r = safe_get(session, "https://api.scryfall.com/cards/search", params={"q": query_emblem}, timeout=5)
                if r and r.status_code == 200:
                    data = r.json()
                    for t_data in data.get("data", []):
                        if not is_actual_token(t_data):
                            continue
                        oid = t_data.get("oracle_id")
                        if oid and oid not in seen_oracle_ids:
                            if lang == "ja":
                                ja_t = fetch_card_by_oracle_id(oid, "ja")
                                if ja_t: t_data = ja_t
                            tokens.append(t_data)
                            seen_oracle_ids.add(oid)

    return tokens

def fetch_card_by_oracle_id(oracle_id, lang="ja"):
    if not oracle_id: return None
    params = {"q": f"oracleid:{oracle_id} lang:{lang}", "include_extras": "true"}
    r = safe_get(session, "https://api.scryfall.com/cards/search", params=params, timeout=5)
    if r and r.status_code == 200:
        data = r.json()
        if data.get("total_cards", 0) > 0:
            return data["data"][0]
    return None

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


def create_card_row(name: str, out_dir: Path, language: str = "ja", count: int = 1, is_token: bool = False, card_data: dict = None):
    """
    Fetch card data and download images for a single card name.
    Returns a list of rows (main card + potential tokens).
    ALWAYS uses English card for relationships and metadata logic,
    then fetches localized data if needed.
    """
    # 1. Fetch Master English Card for metadata logic
    # (Japanese cards often miss all_parts or have limited oracle_text)
    if card_data and not card_data.get("all_parts") and not is_token:
        # If passed card_data lacks all_parts, try to refresh from EN
        card_en = fetch_card(name, "en")
    elif not card_data:
        card_en = fetch_card(name, "en")
    else:
        card_en = card_data

    if card_en is None:
        return []

    # 2. Fetch Localized Card (if needed) for display strings
    card_ja = None
    if language == "ja":
        oid = card_en.get("oracle_id")
        if oid:
            card_ja = fetch_card_by_oracle_id(oid, "ja")
    
    # helper to get field from ja if exists, else en
    def pick(field, default=""):
        if card_ja and card_ja.get(field):
            return card_ja.get(field)
        return card_en.get(field, default)

    en = card_en["name"]
    ja = pick("printed_name")
    safe_en = safe_filename(en)

    row = {
        "card_file_front": "",
        "card_file_back": "",
        "name_front": "",
        "name_back": "",
        "name_ja": get_card_name(card_ja or card_en, "ja"),
        "name_en": get_card_name(card_en, "en"),
        "type_front": "",
        "type_back": "",
        "mana_cost": card_en.get("mana_cost", ""),
        "text_front_ja": "",
        "text_front_en": "",
        "text_back_ja": "",
        "text_back_en": "",
        "Commander_A": "",
        "Commander_B": "",
        "Companion": "",
        "count": count,
        "is_token": "True" if is_token else "False",
        "oracle_id": card_en.get("oracle_id", ""),
    }

    # 1. Image Download & Basic Info (SFC vs DFC)
    # Using English card for layout/face structure
    oid = card_en.get("oracle_id", "")
    short_oid = f"_{oid[:8]}" if is_token and oid else ""

    if "image_uris" in card_en:
        # Single-faced
        row["card_file_front"] = f"{safe_en}{short_oid}_front.jpg"
        # Download localized image if available, else EN
        img_url = None
        if card_ja:
            img_url = card_ja.get("image_uris", {}).get("normal")
        if not img_url:
            img_url = card_en.get("image_uris", {}).get("normal")
            
        download_image(img_url, out_dir / row["card_file_front"])
        
        row["name_front"] = en
        row["type_front"] = card_en.get("type_line", "")
        
        row["text_front_en"] = get_card_text(card_en, "en")
        row["text_front_ja"] = get_card_text(card_ja or card_en, "ja")
        if not looks_japanese(row["text_front_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
            if looks_japanese(jp_txt):
                row["text_front_ja"] = jp_txt
    
    elif "card_faces" in card_en and len(card_en["card_faces"]) >= 2:
        # Double-faced
        face1_en, face2_en = card_en["card_faces"]
        face1_ja = card_ja["card_faces"][0] if card_ja and "card_faces" in card_ja else face1_en
        face2_ja = card_ja["card_faces"][1] if card_ja and "card_faces" in card_ja else face2_en

        row["card_file_front"] = f"{safe_en}{short_oid}_front.jpg"
        row["card_file_back"] = f"{safe_en}{short_oid}_back.jpg"
        
        url_f = (face1_ja.get("image_uris", {}) if face1_ja else {}).get("normal") or face1_en.get("image_uris", {}).get("normal")
        url_b = (face2_ja.get("image_uris", {}) if face2_ja else {}).get("normal") or face2_en.get("image_uris", {}).get("normal")
        download_image(url_f, out_dir / row["card_file_front"])
        download_image(url_b, out_dir / row["card_file_back"])
        
        row["name_front"] = face1_en.get("name")
        row["name_back"] = face2_en.get("name")
        row["type_front"] = face1_en.get("type_line", "")
        row["type_back"] = face2_en.get("type_line", "")
        row["mana_cost"] = face1_en.get("mana_cost", "")
        
        row["text_front_en"] = get_card_text(face1_en, "en")
        row["text_back_en"] = get_card_text(face2_en, "en")
        row["text_front_ja"] = get_card_text(face1_ja or face1_en, "ja")
        if not looks_japanese(row["text_front_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
            if looks_japanese(jp_txt):
                row["text_front_ja"] = jp_txt
        
        row["text_back_ja"] = get_card_text(face2_ja or face2_en, "ja")
        if not looks_japanese(row["text_back_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "back")
            if looks_japanese(jp_txt):
                row["text_back_ja"] = jp_txt
    else:
        logger.info(f"Card format not supported: {en}")
        return []

    results = [row]

    # If this is not a token, fetch related tokens using MASTER English card
    if not is_token:
        tokens = fetch_related_tokens(card_en, language)
        for t_data in tokens:
            t_name = t_data["name"]
            # t_data from fetch_related_tokens might already be JA if requested
            t_rows = create_card_row(t_name, out_dir, language, count=0, is_token=True, card_data=t_data)
            results.extend(t_rows)

    return results

def find_existing_card_in_list(row: dict, card_list: list) -> dict:
    """
    Robust identity check to find if a card already exists in a list.
    Prioritizes Oracle ID, falls back to Name matching.
    """
    oid = row.get("oracle_id")
    name = row.get("name_en")
    is_token = (str(row.get("is_token")) == "True")
    
    for c in card_list:
        c_oid = c.get("oracle_id")
        c_name = c.get("name_en")
        c_is_token = (str(c.get("is_token")) == "True")
        
        if c_is_token != is_token:
            continue
        
        # 1. Match by Oracle ID if both have it
        if oid and c_oid:
            if str(oid).strip() == str(c_oid).strip():
                return c
        
        # 2. Match by Name if either lacks ID or IDs are empty
        if name and c_name:
            if str(name).strip().lower() == str(c_name).strip().lower():
                if not oid or not c_oid:
                    return c
    return None

def generate_from_txt(
    txt_path: Path,
    out_dir: Path,
    language="ja",
    progress_callback=None
):
    items = parse_decklist(txt_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{txt_path.stem}.csv"
    rows = []
    total = len(items)

    for i, item in enumerate(items, 1):
        name = item["name"]
        cnt = item["count"]
        if progress_callback:
            progress_callback(i, total, name)
            
        card_rows = create_card_row(name, out_dir, language, count=cnt)
        if card_rows:
            for r in card_rows:
                existing = find_existing_card_in_list(r, rows)
                
                if existing:
                    if str(r.get("is_token")) != "True":
                        c_curr = int(str(existing.get("count", 1)))
                        existing["count"] = str(c_curr + int(str(r.get("count", 1))))
                    # Skip duplicate tokens
                else:
                    rows.append(r)
        
        time.sleep(0.1)

    if not rows:
        return None

    fieldnames = [
        "card_file_front", "card_file_back", "name_front", "name_back",
        "name_ja", "name_en", "type_front", "type_back", "mana_cost",
        "text_front_ja", "text_front_en", "text_back_ja", "text_back_en",
        "Commander_A", "Commander_B", "Companion", "count", "is_token", "oracle_id"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path
