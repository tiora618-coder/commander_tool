# generator.py
import requests
import csv
import re
import time
from pathlib import Path
from requests.exceptions import RequestException, Timeout
import json


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

def safe_get(session, url, *, params=None, timeout=5, retries=2, sleep=0.5):
    """
    Safe wrapper around requests.get
    Returns None on failure
    """
    time.sleep(0.05)
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, timeout=timeout)
            return r
        except (Timeout, RequestException) as e:
            print(f"[WARN] GET failed ({attempt+1}/{retries+1}): {url}")
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

        oracle_id = base["oracle_id"]

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
        print(f"[WARN] fetch_card failed: {card_name}")
        return None

    # --- Prefer Japanese ---
    if lang == "ja":
        oracle_id = base["oracle_id"]
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



def get_card_text(card, lang: str = "ja"):
    """
    lang:
      - "ja": Prefer Japanese (printed_text → oracle_text)
      - "en": English only (oracle_text)
    """
    if card is None:
        return ""
    texts = []

    def pick_text(face_or_card):
        if lang == "ja":
            return face_or_card.get("printed_text") or face_or_card.get("oracle_text")
        else:
            return face_or_card.get("oracle_text")

    if "card_faces" in card:
        for face in card["card_faces"]:
            t = pick_text(face)
            if t:
                texts.append(t)
    else:
        t = pick_text(card)
        if t:
            texts.append(t)

    return "\n\n".join(texts)

def get_card_name(card, lang):
    if card is None:
        return ""
    if lang == "ja":
        return card.get("printed_name") or card["name"]
    return card["name"]



# -------------------------
# Main processing
# -------------------------
def generate_from_txt(
    txt_path: Path,
    out_dir: Path,
    language="ja",
    progress_callback=None
):
    index = 1
    names = parse_decklist(txt_path)
    out_dir.mkdir(exist_ok=True)

    csv_path = out_dir / f"{txt_path.stem}.csv"
    rows = []

    total = len(names)

    for i, name in enumerate(names, 1):
        card = fetch_card(name,language)
        if card is None:
            continue  

        en = card["name"]
        ja = card.get("printed_name", "")
        display_name = ja or en
        base_name = safe_filename(f"{en}_{ja}" if ja else en)

        # -------------------------
        # Single-faced card
        # -------------------------
        if "image_uris" in card:
            img_url = card["image_uris"]["normal"]

            safe_en = safe_filename(en)

            card_file_front = f"{safe_en}_front.jpg"
            card_file_back = ""


            download_image(img_url, out_dir / card_file_front)

            card = fetch_card(name,"ja")
            text_front_ja = get_card_text(card, "ja")
            text_front_en = get_card_text(card, "en")

            rows.append({
                "card_file_front": card_file_front,
                "card_file_back": "",
                "name_front": en,
                "name_back": "",


                "name_ja": get_card_name(card, "ja"),
                "name_en": get_card_name(card, "en"),

                "type": card["type_line"],
                "mana_cost": card.get("mana_cost", ""),

                "text_front_ja": text_front_ja,
                "text_front_en": text_front_en,
                "text_back_ja": "",
                "text_back_en": "",
            })


            index += 1

            if progress_callback:
                progress_callback(i, total, display_name)

        # -------------------------
        # Double-faced card
        # -------------------------
        elif "card_faces" in card and len(card["card_faces"]) >= 2:
            face1, face2 = card["card_faces"]

            safe_en = safe_filename(en)

            card_file_front = f"{safe_en}_front.jpg"
            card_file_back = f"{safe_en}_back.jpg"


            download_image(face1["image_uris"]["normal"], out_dir / card_file_front)
            download_image(face2["image_uris"]["normal"], out_dir / card_file_back)

            card = fetch_card(name,"ja")
            rows.append({
                "card_file_front": card_file_front,
                "card_file_back": card_file_back,

                "name_front": face1.get("printed_name", face1["name"]),
                "name_back": face2.get("printed_name", face2["name"]),
                

                "name_ja": get_card_name(card, "ja"),
                "name_en": get_card_name(card, "en"),

                "type": card["type_line"],
                "mana_cost": card.get("mana_cost", ""),


                "text_front_ja": get_card_text(face1, "ja"),
                "text_front_en": get_card_text(face1, "en"),
                "text_back_ja": get_card_text(face2, "ja"),
                "text_back_en": get_card_text(face2, "en"),
            })

            index += 1


            if progress_callback:
                progress_callback(i, total, display_name)

        else:
            print(f"Image not supported for card: {en}")

        time.sleep(0.1)  # Throttle requests to avoid overloading Scryfall

 
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "card_file_front",
                "card_file_back",
                "name_front",
                "name_back",
                "name_ja",
                "name_en",
                "type",
                "mana_cost",
                "text_front_ja",
                "text_front_en",
                "text_back_ja",
                "text_back_en",
                "Commander_A",
                "Commander_B",
                "Companion",
            ],
            quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        for row in rows:
            row["Commander_A"] = ""
            row["Commander_B"] = ""
            row["Companion"] = ""
            writer.writerow(row)


    return csv_path
