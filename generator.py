# generator.py
import requests
import csv
import re
import time
from pathlib import Path
from requests.exceptions import RequestException, Timeout
import json
from wisdomguild_scraper import fetch_text_from_wisdom_guild, fetch_english_name_by_japanese
from common_func import exe_dir
import logging
logger = logging.getLogger(__name__)

SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"

# Session (for performance optimization)
session = requests.Session()
session.headers.update({
    "User-Agent": "CommanderTool/1.0"
})

# Utilities and Cache
# -------------------------
TOKEN_CACHE_PATH = exe_dir() / "token_cache.json"
_token_cache = {}

def prune_card_data(card: dict) -> dict:
    """
    Remove heavy/unnecessary fields from Scryfall card data to keep the cache lightweight.
    """
    if not card: return None
    
    # Essential fields we need for display, text, and token discovery
    essential_fields = [
        "name", "oracle_id", "type_line", "mana_cost", "oracle_text", 
        "layout", "image_uris", "card_faces", "all_parts", "printed_name", "printed_text"
    ]
    
    pruned = {k: card[k] for k in essential_fields if k in card}
    
    # Recursively prune card faces if present
    if "card_faces" in pruned:
        pruned["card_faces"] = [
            {k: face[k] for k in essential_fields if k in face}
            for face in pruned["card_faces"]
        ]
        
    return pruned

def load_token_cache():
    global _token_cache
    if TOKEN_CACHE_PATH.exists():
        try:
            with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                _token_cache = json.load(f)
            
            # V21.0: Prune existing heavy cache on first load
            for name, entry in _token_cache.items():
                if entry:
                    if "main" in entry and entry["main"]:
                        entry["main"] = prune_card_data(entry["main"])
                    if "main_ja" in entry and entry["main_ja"]:
                        entry["main_ja"] = prune_card_data(entry["main_ja"])
                    if "tokens" in entry and entry["tokens"]:
                        entry["tokens"] = [prune_card_data(t) for t in entry["tokens"]]
            save_token_cache()
            logger.info(f"[INFO] Loaded and pruned {len(_token_cache)} cards from token cache.")
        except Exception as e:
            logger.error(f"[ERROR] Failed to load/prune token cache: {e}")
            _token_cache = {}

def save_token_cache():
    global _token_cache
    try:
        with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_token_cache, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[ERROR] Failed to save token cache: {e}")

# Initial load
load_token_cache()

def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", text)

def clean_card_name(name: str) -> str:
    """
    Remove Japanese ruby characters (FURIGANA) like '統（とう）率（そつ）の塔（とう）' -> '統率の塔'.
    Also strips whitespace.
    """
    if not name: return ""
    # Remove contents of full-width parentheses
    cleaned = re.sub(r"（[^）]*）", "", name)
    # Remove contents of half-width parentheses as well
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    return cleaned.strip()

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
    card_name = clean_card_name(card_name)
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
        # Fallback to search API if named endpoint fails (often happens with Japanese names with punctuation)
        # V21.3: Use lang:any to ensure we find the card regardless of language
        query = f'name:"{card_name}"' if " " in card_name or "、" in card_name else f'! "{card_name}"'
        r = safe_get(
            session,
            "https://api.scryfall.com/cards/search",
            params={"q": f"{query} lang:any", "include_extras": "true"},
            timeout=5,
        )
        if r and r.status_code == 200:
            data = r.json()
            if data.get("total_cards", 0) > 0:
                base = data["data"][0]
                logger.info(f"[INFO] fetch_card fallback search success: {card_name} -> {base.get('name')}")

    if not base:
        logger.warning(f"[WARN] fetch_card failed on Scryfall: {card_name}")
        # Final Fallback: Ask Wisdom Guild for the English name
        if looks_japanese(card_name):
            en_name = fetch_english_name_by_japanese(card_name)
            if en_name:
                logger.info(f"[INFO] Wisdom Guild resolved English name: {card_name} -> {en_name}")
                # Try Scryfall one last time with the English name
                r = safe_get(
                    session,
                    SCRYFALL_NAMED_URL,
                    params={"exact": en_name},
                    timeout=5,
                )
                if r and r.status_code == 200:
                    base = r.json()
        
    if not base:
        logger.warning(f"[WARN] fetch_card failed completely: {card_name}")
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
    if lang == "en" and base.get("lang") != "en":
        en_name = base.get("name")
        if en_name and en_name != card_name:
            r = safe_get(
                session,
                SCRYFALL_NAMED_URL,
                params={"exact": en_name},
                timeout=5,
            )
            if r and r.status_code == 200:
                base = r.json()
    return base




def download_image(url: str, path: Path):
    # Skip if the file already exists and has content
    if path.exists() and path.stat().st_size > 0:
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
    Find related tokens for a card.
    Uses Scryfall's 'oracleid' search which is the most reliable way 
    to find tokens/emblems associated with a card.
    """
    tokens = []
    seen_oracle_ids = set()
    
    oracle_id = card.get("oracle_id")
    if not oracle_id:
        return []

    def is_valid_token(t_data):
        """Helper to ensure a card is actually a token or emblem."""
        layout = t_data.get("layout", "")
        type_line = (t_data.get("type_line") or "").lower()
        # Strictly allow only tokens, emblems, or cards with the 'token' layout
        return layout in ["token", "emblem", "double_faced_token"] or "token" in type_line or "emblem" in type_line

    # 1. Primary Method: Standard Scryfall 'all_parts' links
    all_parts = card.get("all_parts", [])
    for part in all_parts:
        if part.get("component") == "token":
            token_uri = part.get("uri")
            if token_uri:
                r = safe_get(session, token_uri, timeout=5)
                if r and r.status_code == 200:
                    t_data = r.json()
                    oid = t_data.get("oracle_id")
                    if oid and oid not in seen_oracle_ids and is_valid_token(t_data):
                        if lang == "ja":
                            ja_token = fetch_card_by_oracle_id(oid, "ja")
                            if ja_token: t_data = ja_token
                        tokens.append(t_data)
                        seen_oracle_ids.add(oid)

    # 2. Fallbacks: If all_parts didn't work, try broader searches
    if not tokens:
        # A. Search by Oracle ID tag (Reliable for planeswalkers)
        # V20.0: Added strict type filter to the query
        query_tag = f'otag:creations-of-oracle-{oracle_id} (is:token or t:emblem)'
        r = safe_get(session, "https://api.scryfall.com/cards/search", params={"q": query_tag}, timeout=5)
        if r and r.status_code == 200:
            data = r.json()
            for t_data in data.get("data", []):
                oid = t_data.get("oracle_id")
                if oid and oid not in seen_oracle_ids and is_valid_token(t_data):
                    if lang == "ja":
                        ja_t = fetch_card_by_oracle_id(oid, "ja")
                        if ja_t: t_data = ja_t
                    tokens.append(t_data)
                    seen_oracle_ids.add(oid)

        # B. Search for tokens mentioning the card's EXACT name
        if not tokens:
            name_en = card["name"]
            # V20.0: Ensure search is restricted to tokens/emblems
            search_query = f'(is:token or t:emblem) "{name_en}"'
            r = safe_get(session, "https://api.scryfall.com/cards/search", params={"q": search_query}, timeout=5)
            if r and r.status_code == 200:
                data = r.json()
                for t_data in data.get("data", []):
                    oid = t_data.get("oracle_id")
                    if oid and oid not in seen_oracle_ids and is_valid_token(t_data):
                        # HEURISTIC: Only keep it if it's actually related
                        t_text = (t_data.get("oracle_text") or "").lower()
                        t_name = t_data.get("name", "").lower()
                        if name_en.lower() in t_text or name_en.lower() in t_name:
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


    # ---- Adventure / MDFC / Prepare ----
    if "card_faces" in card:
        names = []
        has_english = False
        en_name = card["name"]

        for face in card["card_faces"]:
            pn = face.get("printed_name")
            if pn and looks_japanese(pn):
                names.append(pn)
            else:
                has_english = True

        if has_english:
            names = []
            [jp_name, _] = fetch_text_from_wisdom_guild(en_name, "front")
            names.append(jp_name)
            [jp_name, _] = fetch_text_from_wisdom_guild(en_name, "back")
            names.append(jp_name)

        # For prepare spells: only keep non-empty names
        names = [n for n in names if n]
        if names and looks_japanese(" // ".join(names)):
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
                display_name = card.get("printed_name") or card["name"]
                english_name = card["name"]
                if (display_name, english_name) not in results:
                    results.append((display_name, english_name))
            logger.info(f"Autocomplete JA: {query} -> {[r[0] for r in results[:5]]}")
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
            names = r.json().get("data", [])
            return [(n, n) for n in names]
    
    return []


def create_card_row(name: str, out_dir: Path, language: str = "ja", count: int = 1, is_token: bool = False, card_data: dict = None, name_en: str = None):
    """
    Fetch card data and download images for a single card name.
    Returns a list of rows (main card + potential tokens).
    - name: The search name (might be Japanese with Ruby)
    - name_en: Optional explicit English name (high fidelity for metadata)
    """
    card_en = None
    card_ja = None
    tokens = []

    # 0. If data is provided directly (recursion for tokens)
    if card_data:
        card_en = card_data

    # 1. Performance Optimization: Global Cache (Main Cards only)
    search_name = clean_card_name(name)
    is_cached = False
    if not is_token and card_en is None:
        if search_name in _token_cache:
            entry = _token_cache[search_name]
            if entry is not None and entry.get("main") is not None:
                # V21.2: If we have full results cached, check if expected images exist.
                # This skips ALL network calls, including text fallback and token recursion.
                if "results" in entry and entry["results"]:
                    all_exist = True
                    for r in entry["results"]:
                        front = r.get("card_file_front")
                        if front:
                            fpath = out_dir / front
                            if not fpath.exists() or fpath.stat().st_size == 0:
                                all_exist = False
                                break
                        back = r.get("card_file_back")
                        if back:
                            bpath = out_dir / back
                            if not bpath.exists() or bpath.stat().st_size == 0:
                                all_exist = False
                                break
                    if all_exist:
                        logger.info(f"[INFO] Full result cache hit with images: {search_name}")
                        return entry["results"], True
                    else:
                        logger.info(f"[INFO] Full result cache hit but images missing, regenerating: {search_name}")
                
                card_en = entry.get("main")
                tokens = entry.get("tokens", [])
                card_ja = entry.get("main_ja")
                is_cached = True
                logger.info(f"[INFO] Partial token cache hit: {search_name}")

    if not card_en:
        # 1. Fetch Master English Card for metadata logic
        lookup_name = name_en if name_en else name
        card_en = fetch_card(lookup_name, "en")

        if card_en is None:
            if not is_token:
                _token_cache[search_name] = {"main": None, "tokens": [], "main_ja": None}
                save_token_cache()
            return [], False
        
        if not is_token:
            tokens = fetch_related_tokens(card_en, language)

    # 2. Fetch Localized Card (if needed) for display strings
    # V20.1: Avoid redundant fetch if already cached/found
    if language == "ja" and not card_ja:
        oid = card_en.get("oracle_id")
        if oid:
            card_ja = fetch_card_by_oracle_id(oid, "ja")
    
    # helper to get field from ja if exists, else en
    def pick(field, default=""):
        if card_ja and card_ja.get(field):
            return card_ja.get(field)
        return card_en.get(field, default)

    # V21.2: Intermediate Scryfall objects are still used for row generation,
    # but the full result will be cached at the end of the function.
    pass

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
        # Single-faced card (may still have card_faces for prepare/adventure layout)
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

        # Check if this is a prepare spell (single image but has card_faces)
        # Prepare spells embed the spell face inside card_faces but share one card image.
        faces_en = card_en.get("card_faces", [])
        if len(faces_en) >= 2:
            # Prepare spell: front face = creature, back face = the prepare spell
            face1_en = faces_en[0]
            face2_en = faces_en[1]
            face1_ja = (card_ja.get("card_faces", []) or [None])[0] if card_ja else None
            face2_ja = (card_ja.get("card_faces", []) or [None, None])[1] if card_ja and len(card_ja.get("card_faces", [])) > 1 else None

            row["name_front"] = face1_en.get("name", en)
            row["name_back"] = face2_en.get("name", "")
            row["type_front"] = face1_en.get("type_line", card_en.get("type_line", ""))
            row["type_back"] = face2_en.get("type_line", "")
            row["mana_cost"] = face1_en.get("mana_cost", card_en.get("mana_cost", ""))

            # English text: use face oracle_text
            row["text_front_en"] = face1_en.get("oracle_text", "")
            row["text_back_en"] = face2_en.get("oracle_text", "")

            # Japanese text: try printed_text from ja card faces
            row["text_front_ja"] = (face1_ja.get("printed_text") or face1_ja.get("oracle_text") or "") if face1_ja else ""
            row["text_back_ja"] = (face2_ja.get("printed_text") or face2_ja.get("oracle_text") or "") if face2_ja else ""

            # Fallback to Wisdom Guild for front
            if not is_cached and not looks_japanese(row["text_front_ja"]):
                [jp_name, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
                if jp_name:
                    row["name_front"] = jp_name
                if looks_japanese(jp_txt):
                    row["text_front_ja"] = jp_txt

            # Fallback to Wisdom Guild for back (prepare spell face)
            if not is_cached and not looks_japanese(row["text_back_ja"]):
                [jp_name, jp_txt] = fetch_text_from_wisdom_guild(en, "back")
                if jp_name:
                    row["name_back"] = jp_name
                if looks_japanese(jp_txt):
                    row["text_back_ja"] = jp_txt
        else:
            # Truly single-faced card
            row["text_front_en"] = get_card_text(card_en, "en")
            row["text_front_ja"] = get_card_text(card_ja or card_en, "ja")
            if not is_cached and not looks_japanese(row["text_front_ja"]):
                [_, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
                if looks_japanese(jp_txt):
                    row["text_front_ja"] = jp_txt
    
    elif "card_faces" in card_en and len(card_en["card_faces"]) >= 2:
        # Double-faced card (each face has its own image_uris)
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
        if not is_cached and not looks_japanese(row["text_front_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "front")
            if looks_japanese(jp_txt):
                row["text_front_ja"] = jp_txt
        
        row["text_back_ja"] = get_card_text(face2_ja or face2_en, "ja")
        if not is_cached and not looks_japanese(row["text_back_ja"]):
            [_, jp_txt] = fetch_text_from_wisdom_guild(en, "back")
            if looks_japanese(jp_txt):
                row["text_back_ja"] = jp_txt
    else:
        logger.info(f"Card format not supported: {en}")
        return [], False

    results = [row]

    # If this is not a token, process related tokens (populated from cache or fetch above)
    if not is_token:
        for t_data in tokens:
            t_name = t_data["name"]
            t_rows, _ = create_card_row(t_name, out_dir, language, count=0, is_token=True, card_data=t_data)
            results.extend(t_rows)

    # V21.2: Save the FULL results list to cache if this was a fresh scan or partial hit
    if not is_token and (not is_cached or "results" not in _token_cache.get(search_name, {})):
        entry = _token_cache.get(search_name, {"main": card_en, "tokens": tokens, "main_ja": card_ja})
        entry["results"] = results
        # Also ensure we save pruned versions of everything
        entry["main"] = prune_card_data(card_en)
        entry["main_ja"] = prune_card_data(card_ja)
        entry["tokens"] = [prune_card_data(t) for t in tokens]
        
        _token_cache[search_name] = entry
        save_token_cache()

    return results, is_cached

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
            
        card_rows, is_cached = create_card_row(name, out_dir, language, count=cnt)
        if card_rows:
            for r in card_rows:
                existing = find_existing_card_in_list(r, rows)
                
                if existing:
                    if str(r.get("is_token")) != "True":
                        existing["count"] = str(int(str(existing.get("count") or 1)) + int(str(r.get("count") or 1)))
                    # Skip duplicate tokens
                else:
                    rows.append(r)
        
        if not is_cached:
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
