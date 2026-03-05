
import sys
from pathlib import Path
import re
import requests
from PyQt5.QtGui import QPixmap, QIcon, QColor
from PyQt5.QtCore import Qt
import platform

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

_app_icon_singleton = None

def get_app_icon() -> QIcon:
    """Returns a singleton QIcon instance for the application."""
    global _app_icon_singleton
    if _app_icon_singleton is not None:
        return _app_icon_singleton

    base = app_dir() / "icons"
    # V11: Prioritize PNG on Windows as ICO is showing as white/default for the user
    if platform.system() == "Windows":
        # Check for PNG first, fallback to ICO
        icon_file = base / "commander_tool_icon.png"
        if not icon_file.exists():
            icon_file = base / "commander_tool_icon.ico"
    elif platform.system() == "Darwin":
        icon_file = base / "commander_tool_icon.icns"
    else:
        icon_file = base / "commander_tool_icon.png"

    if not icon_file.exists():
        # Fallback to current directory for safety
        icon_file = Path(__file__).parent / "icons" / icon_file.name
        if not icon_file.exists() and icon_file.suffix == ".ico":
             icon_file = icon_file.with_suffix(".png")

    if icon_file.exists():
        print(f"[INFO] Loading icon from: {icon_file}", flush=True)
        # Final: Load real icon, but scale down PNG to ensure compatibility
        pix = QPixmap(str(icon_file))
        if not pix.isNull():
             if pix.width() > 256 or pix.height() > 256:
                 print(f"[INFO] Scaling down icon from {pix.width()} to 256...", flush=True)
                 pix = pix.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
             _app_icon_singleton = QIcon(pix)
        else:
             _app_icon_singleton = QIcon(str(icon_file))
    else:
        print(f"[INFO] WARNING: Icon file NOT found at: {icon_file}", flush=True)
        _app_icon_singleton = QIcon()
        
    return _app_icon_singleton

def set_window_icon_win32(window_id):
    """
    Forcefully sets the window icon using Win32 API.
    window_id is the result of QWidget.winId()
    """
    if platform.system() != "Windows":
        return

    try:
        import ctypes
        from ctypes import wintypes

        # Constants
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        LR_LOADFROMFILE = 0x00000010
        IMAGE_ICON = 1

        # We need the .ico file for this specific Win32 API
        base = app_dir() / "icons"
        ico_file = base / "commander_tool_icon.ico"
        if not ico_file.exists():
            return

        # Load the icon handle
        hicon = ctypes.windll.user32.LoadImageW(
            None, str(ico_file), IMAGE_ICON, 0, 0, LR_LOADFROMFILE
        )

        if hicon:
            # Send WM_SETICON to the window handle
            hwnd = int(window_id)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
            print("[INFO] Win32 WM_SETICON applied successfully.", flush=True)
    except Exception as e:
        print(f"[ERROR] Failed to set Win32 icon: {e}", flush=True)

def set_app_icon(window):
    """Applies the singleton application icon to the given window."""
    window.setWindowIcon(get_app_icon())
