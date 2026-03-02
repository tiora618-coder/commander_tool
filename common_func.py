
import sys
from pathlib import Path
import re
import requests
from PyQt5.QtGui import QPixmap

def app_dir() -> Path:
    # One-file: use the temporary MEIPASS directory
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)

    # One-folder: use the folder containing the executable
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent

    # Normal Python execution
    return Path(__file__).resolve().parent

def exe_dir() -> Path:
    if getattr(sys, 'frozen', False):
         # Directory of the executable (PyInstaller)
        return Path(sys.executable).parent
    return Path(__file__).parent

def strip_ruby(name: str) -> str:
    if not name:
        return name
    return re.sub(r"（[^）]*）", "", name)

def mana_symbol_to_filename(sym: str):
    sym = sym.upper()

    special = {
        "∞": "infinity"
    }

    if sym in special:
        return f"mana-{special[sym]}.png"

    return f"mana-{sym.lower().replace('/', '')}.png"

def load_or_download_card_back(back_path: Path) -> QPixmap:
    # すでに存在する場合
    if back_path.exists():
        return QPixmap(str(back_path))

    back_path.parent.mkdir(parents=True, exist_ok=True)

    url = "https://cards.scryfall.io/back.png"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        with back_path.open("wb") as f:
            f.write(response.content)

        print(f"[INFO] Card back image downloaded: {back_path}")

    except Exception as e:
        print(f"[ERROR] Could not download card back: {e}")
        return QPixmap(":/fallback/back.png")  # 内蔵画像などに切替可能

    return QPixmap(str(back_path))
