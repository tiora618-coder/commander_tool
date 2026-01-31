
import sys
from pathlib import Path
import re

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

