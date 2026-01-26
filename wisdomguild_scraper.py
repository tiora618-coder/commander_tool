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
}

# Translation table for full-width digits → half-width digits
ZENKAKU_DIGITS = str.maketrans(
    "０１２３４５６７８９",
    "0123456789"
)

def convert_mana_symbols(text: str) -> str:
    """
    Convert Wisdom Guild mana notation to MTG-style symbols.
    Examples:
      (６)(青) → {6}{U}
      （赤）   → {R}
    Supports both full-width and half-width parentheses.
    """
    def repl(match: re.Match):
        inner = match.group(1)

        # Convert full-width digits to half-width
        inner = inner.translate(ZENKAKU_DIGITS)

        if inner in MANA_MAP:
            return "{" + MANA_MAP[inner] + "}"
        if inner.isdigit():
            return "{" + inner + "}"

        # Leave unconvertible patterns unchanged
        return match.group(0)

    # Match both full-width （） and half-width ()
    return re.sub(r"[（(]([^）)]+)[）)]", repl, text)


def fetch_text_from_wisdom_guild(card_name_en: str, side=0):
    """
    Fetch Japanese card name and rules text from Wisdom Guild.

    Parameters:
      card_name_en : English card name (used in URL)
      side         : 0 / "front" for front face
                     1 / "back"  for back face (Adventure / MDFC)

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

    # Build Wisdom Guild card URL
    url = f"https://whisper.wisdom-guild.net/card/{card_name_en.replace(' ', '+')}/"
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
