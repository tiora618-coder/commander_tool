# wisdomguild_scraper.py
import requests
import time
import urllib.parse
from bs4 import BeautifulSoup
import re
import logging

logger = logging.getLogger(__name__)

# HTTP headers (basic User-Agent to avoid blocking)
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def extract_japanese_name(full_name: str) -> str:
    """
    Extract the Japanese card name from a combined name string.
    Example:
      "ソード・コーストの海蛇/Sword Coast Serpent"
      -> "ソード・コーストの海蛇"
    """
    if "/" in full_name:
        return full_name.split("/", 1)[0].strip()
    return full_name.strip()

# Mapping from Japanese mana symbols to MTG mana symbols
MANA_MAP = {
    "白": "W",
    "青": "U",
    "黒": "B",
    "赤": "R",
    "緑": "G",
    "◇": "C",
    "Ｘ": "X",
    "Ｔ": "T",
    "Ｑ": "Q",
}

SYMBOL_MAP = {
    # Colors (Japanese)
    "白": "W",
    "青": "U",
    "黒": "B",
    "赤": "R",
    "緑": "G",

    # Special mana
    "◇": "C",
    "Ｓ": "S",   # Snow mana
    "Ｐ": "P",   # Phyrexian

    # Other symbols
    "Ｔ": "T",
    "Ｑ": "Q",
    "Ｘ": "X",
}

# Translation table for full-width digits → half-width digits
ZENKAKU_DIGITS = str.maketrans(
    "０１２３４５６７８９",
    "0123456789"
)

def convert_mana_symbols(text: str) -> str:
    """
    Convert Wisdom Guild mana notation to MTG-style symbols.
    Supports:
      (６)(青)     → {6}{U}
      (２/Ｕ)      → {2/U}
      (白/青)      → {W/U}
      (白/Ｐ)      → {W/P}
      (Ｓ)         → {S}
      (Ｔ)         → {T}
    """
    def normalize(part: str) -> str:
        part = part.translate(ZENKAKU_DIGITS)
        return SYMBOL_MAP.get(part, part)

    def repl(match: re.Match):
        inner = match.group(1)

        # Hybrid / Phyrexian mana
        if "/" in inner:
            parts = inner.split("/")
            norm = [normalize(p) for p in parts]
            return "{" + "/".join(norm) + "}"

        # Single symbol
        inner = normalize(inner)

        if inner.isdigit() or inner.isalpha():
            return "{" + inner + "}"

        return match.group(0)

    return re.sub(r"[（(]([^）)]+)[）)]", repl, text)


def fetch_text_from_wisdom_guild(card_name_en: str, side=0):
    """
    Fetch Japanese card name and rules text from Wisdom Guild.

    Parameters:
      card_name_en : English card name (used in URL).
                     For split/prepare cards like "Scheming Silvertongue // Sign in Blood",
                     only the front name is used for URL lookup.
      side         : 0 / "front" for front face
                     1 / "back"  for back face (Adventure / MDFC / Prepare)

    Returns:
      [japanese_name, japanese_text]
    """

    # Polite delay to avoid hammering the site
    time.sleep(1)

    # Normalize side parameter
    if side == "front":
        side = 0
    elif side == "back":
        side = 1

    # Build Wisdom Guild card URL — use only front face name (before " // ")
    front_name = card_name_en.split(" // ")[0].strip()
    url = f"https://whisper.wisdom-guild.net/card/{front_name.replace(' ', '+')}/"
    r = requests.get(url, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        return ["", ""]

    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.find_all("tr")

    faces = []
    current = None

    # Parse table rows sequentially
    for tr in rows:
        th = tr.find("th", class_="dc")
        if not th:
            continue

        label = th.get_text(strip=True)

        # New card face starts at "カード名"
        if label == "カード名":
            if current:
                faces.append(current)

            td = tr.find("td", class_="mc")
            raw_name = td.find("b").get_text(strip=True) if td else ""
            current = {
                "name": extract_japanese_name(raw_name),
                "texts": []
            }

        # Rules text block
        elif label == "テキスト" and current:
            td = tr.find("td", class_="lc")
            if td:
                ps = td.find_all("p")
                for p in ps:
                    text = p.get_text(strip=True)
                    if text:
                        current["texts"].append(convert_mana_symbols(text))

    # Append the final face
    if current:
        faces.append(current)

    # Post-process: split faces embedded as "//...// marker" blocks
    # Wisdom Guild encodes Prepare spells (and some Adventures) with all faces
    # in a single HTML block, using //準備// as an in-text separator.
    # Example text list for Scheming Silvertongue:
    #   ["飛行、絆魂", "あなたの第２...", "//準備//", "血の署名/Sign in Blood", "{B}{B}", ...]
    split_faces = []
    for f in faces:
        sub_faces = []
        current_texts = []
        face_name = f["name"]
        skip_next = False

        for idx, t in enumerate(f["texts"]):
            if skip_next:
                skip_next = False
                continue
            # A marker like //準備// signals the start of a new embedded face.
            # The next line is the face name in "日本語名/English Name" format.
            if re.match(r'^//.+//$', t) and idx + 1 < len(f["texts"]):
                sub_faces.append({"name": face_name, "texts": current_texts})
                next_line = f["texts"][idx + 1]
                face_name = next_line.split('/')[0].strip()
                current_texts = []
                skip_next = True
                continue
            current_texts.append(t)

        sub_faces.append({"name": face_name, "texts": current_texts})
        split_faces.extend(sub_faces)

    faces = split_faces

    # Safety check
    if not faces or side >= len(faces):
        return ["", ""]

    face = faces[side]
    logger.debug("Fetched from Wisdom Guild")
    logger.debug(face["name"])
    logger.debug("\n\n".join(face["texts"]))
    return [
        face["name"],
        "\n\n".join(face["texts"])
    ]


def fetch_english_name_by_japanese(jp_name: str) -> str:
    """
    Search Wisdom Guild by Japanese name and try to find the corresponding English name.
    Useful for resolving cards Scryfall struggles with via Japanese names.
    """
    time.sleep(1)
    url = f"https://whisper.wisdom-guild.net/search.php?name={urllib.parse.quote(jp_name)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return ""

        # If it redirected to a card page, extract English name from title or rows
        if "card/" in r.url:
            soup = BeautifulSoup(r.text, "html.parser")
            # Look for <th class="dc">カード名</th>
            for tr in soup.find_all("tr"):
                th = tr.find("th", class_="dc")
                if th and th.get_text(strip=True) == "カード名":
                    td = tr.find("td", class_="mc")
                    if td:
                        full_name = td.get_text(strip=True)
                        # Name format is usually "Japanese Name/English Name"
                        if "/" in full_name:
                            return full_name.split("/", 1)[1].strip()
            return ""

        # If it's a search results page
        soup = BeautifulSoup(r.text, "html.parser")
        # Look for links that look like cards
        links = soup.find_all("a", href=re.compile(r"/card/"))
        for a in links:
            # Recurse into the first result's card page
            first_card_url = urllib.parse.urljoin("https://whisper.wisdom-guild.net", a["href"])
            r2 = requests.get(first_card_url, headers=HEADERS, timeout=10)
            if r2.status_code == 200:
                soup2 = BeautifulSoup(r2.text, "html.parser")
                for tr in soup2.find_all("tr"):
                    th = tr.find("th", class_="dc")
                    if th and th.get_text(strip=True) == "カード名":
                        td = tr.find("td", class_="mc")
                        if td:
                            full_name = td.get_text(strip=True)
                            if "/" in full_name:
                                return full_name.split("/", 1)[1].strip()
            break  # Only try first result

    except Exception as e:
        logger.warning(f"Wisdom Guild EN lookup failed: {e}")

    return ""
