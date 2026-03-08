# main.py
import sys
import os
import csv
from pathlib import Path
import re
import platform
import logging
import zipfile
import io
import traceback
import requests
from typing import List, Dict

from PyQt5.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QTextBrowser, QComboBox,
    QSplitter, QSpinBox, QDialog, QProgressBar, QSizePolicy,
    QMessageBox, QMenu, QCheckBox, QFrame, QGridLayout, QScrollArea, QMainWindow,
    QGraphicsProxyWidget, QGraphicsView, QGraphicsScene
)
from PyQt5.QtCore import Qt, QUrl, QSize, QPoint, QTimer, QSortFilterProxyModel, QRunnable, QObject, pyqtSignal, QThreadPool
from PyQt5.QtGui import (
    QTextDocument, QPixmap, QFont, QFontMetrics, QIcon, QImage, QPalette, QColor, QFontInfo
)

# ==== Suppress Hugging Face / tqdm / transformers output ====
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

# V23.1: Heavy modules moved to local imports in the main block to speed up splash display
from config import APP_VERSION, EMOJI_DIR, UI_FONT_SIZE
from common_func import strip_ruby, mana_symbol_to_filename, app_dir, exe_dir, set_app_icon, get_app_icon, set_window_icon_win32
from gui_language import UI_TEXT, TYPE_LABELS

DEBUG_LOG = True
DEBUG_MODE = True


def setup_logging():
    log_dir = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).parent
    )
    log_file = log_dir / "CommanderTool.log"

    handlers = [
        logging.FileHandler(log_file, encoding="utf-8")
    ]

    if DEBUG_LOG:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.DEBUG if DEBUG_LOG else logging.ERROR,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers
    )

    # === excepthook ===
    def excepthook(exc_type, exc, tb):
        if DEBUG_LOG:
            print("=== UNCAUGHT EXCEPTION ===", file=sys.stderr)
            traceback.print_exception(exc_type, exc, tb)
        else:
            logging.critical(
                "Uncaught exception",
                exc_info=(exc_type, exc, tb)
            )

    sys.excepthook = excepthook

setup_logging()

# ================= Common Settings =================
def is_ascii_filename(path: Path) -> bool:
    try:
        path.name.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False

def enable_dark_mode(app: QApplication):
    palette = QPalette()

    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(20, 20, 20))
    palette.setColor(QPalette.AlternateBase, QColor(30, 30, 30))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(40, 40, 40))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Highlight, QColor(90, 130, 200))
    palette.setColor(QPalette.HighlightedText, Qt.black)

    app.setPalette(palette)


EMOJI_ZIP_URL = (
    "https://github.com/scryfall/manamoji-slack/archive/refs/heads/main.zip"
)


# V23.1: Global placeholders for heavy modules
generator = None
CameraWindow = None
PlayWindow = None
DeckBuildingWindow = None
TestPlayWindow = None
mulligan_simulator = None

def get_display_type(type_line: str, lang: str) -> str:
    if not type_line:
        return ""

    for key in TYPE_LABELS[lang]:
        if key in type_line:
            return TYPE_LABELS[lang][key]

    return type_line

class StartupSplashScreen(QDialog):
    """V23.0: Premium splash screen showing startup progress."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(500, 300)
        
        # Main Container
        container = QFrame(self)
        container.setFixedSize(500, 300)
        container.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 2px solid #555;
                border-radius: 15px;
            }
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Icon and Title
        header = QHBoxLayout()
        
        # V26.0: Square frame for icon to match square source image
        icon_frame = QFrame()
        icon_frame.setFixedSize(84, 84)
        icon_frame.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 0px;
            }
        """)
        icon_inner_layout = QVBoxLayout(icon_frame)
        icon_inner_layout.setContentsMargins(2, 2, 2, 2)
        
        icon_lbl = QLabel()
        pix = get_app_icon().pixmap(80, 80)
        if not pix.isNull():
            icon_lbl.setPixmap(pix)
        icon_inner_layout.addWidget(icon_lbl)
        header.addWidget(icon_frame)
        
        title_box = QVBoxLayout()
        title_lbl = QLabel("Commander Tool")
        title_lbl.setStyleSheet("color: #ffaa00; font-size: 24px; font-weight: bold; border: none;")
        ver_lbl = QLabel(f"Version {APP_VERSION}")
        ver_lbl.setStyleSheet("color: #888; font-size: 14px; border: none;")
        title_box.addWidget(title_lbl)
        title_box.addWidget(ver_lbl)
        header.addLayout(title_box)
        header.addStretch()
        
        layout.addLayout(header)
        layout.addStretch()
        
        # Status Label
        self.status_lbl = QLabel("Initializing...")
        self.status_lbl.setStyleSheet("color: #ccc; font-size: 13px; border: none;")
        layout.addWidget(self.status_lbl)
        
        # Progress Bar
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background-color: #333;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffaa00, stop:1 #ffcc33);
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress)
        
        # Center on screen
        rect = self.frameGeometry()
        cp = QApplication.desktop().availableGeometry().center()
        rect.moveCenter(cp)
        self.move(rect.topLeft())

    def update_status(self, message, percentage):
        self.status_lbl.setText(message)
        self.progress.setValue(int(percentage))
        QApplication.processEvents() # Ensure UI updates

def ensure_emojis(splash=None):
    """
    If resource_dir()/emojis does not exist,
    download manamoji-slack from GitHub and extract emojis.
    V23.0: Supports splash screen progress reporting.
    """
    if EMOJI_DIR.exists():
        if splash: splash.update_status("Checking components...", 100)
        return

    try:
        if splash: splash.update_status("Downloading mana symbols (First time setup)...", 10)
        logging.info("Downloading mana emojis from GitHub...")
        
        response = requests.get(EMOJI_ZIP_URL, stream=True, timeout=15)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        content = io.BytesIO()
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                content.write(chunk)
                downloaded += len(chunk)
                if splash and total_size > 0:
                    prog = 10 + (downloaded / total_size * 50) # 10% to 60%
                    splash.update_status(f"Downloading symbols... {int(downloaded/1024/1024*10)/10}MB", prog)

        if splash: splash.update_status("Extracting assets...", 65)
        
        with zipfile.ZipFile(content) as z:
            members = [m for m in z.namelist() if "emojis/" in m and not m.endswith("/")]
            total_members = len(members)
            
            for i, member in enumerate(members):
                target = EMOJI_DIR / Path(member).name
                EMOJI_DIR.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                
                if splash and i % 5 == 0:
                    prog = 65 + (i / total_members * 35) # 65% to 100%
                    splash.update_status(f"Extracting {i}/{total_members}...", prog)

        logging.info("Mana emojis downloaded.")
        if splash: splash.update_status("Startup complete", 100)

    except Exception as e:
        logging.error(f"Failed to download emojis: {e}")
        QMessageBox.critical(
            None,
            "Error",
            f"Failed to download mana symbol images:\n{e}"
        )
class CSVFilterProxyModel(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        
        if index.isValid():
            # If it's a directory, always accept it so user can navigate
            file_info_index = model.index(source_row, 0, source_parent)
            if model.isDir(file_info_index):
                return True
                
            filename = model.data(index)
            if filename and isinstance(filename, str):
                # 1. Hide consideration files
                if filename.endswith("_consideration.csv"):
                    return False
                # 2. Accept only .csv files (Enforce this across all OS to avoid macOS native dialog issues)
                if not filename.lower().endswith(".csv"):
                    return False
                    
        return super().filterAcceptsRow(source_row, source_parent)


# ================= Mana Symbol Handling =================

def parse_mana_cost(cost: str):
    if not cost:
        return []
    return re.findall(r"\{([^}]+)\}", cost)


class ManaCostWidget(QWidget):
    def __init__(self, mana_cost: str):
        super().__init__()

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        dpr = self.devicePixelRatioF()
        for sym in parse_mana_cost(mana_cost):
            fn = mana_symbol_to_filename(sym)
            path = EMOJI_DIR / fn
            if not path.exists():
                continue

            label = QLabel()
            pix = QPixmap(str(path))
            if not pix.isNull():
                scaled_size = int(22 * dpr)
                label.setPixmap(
                    pix.scaled(
                        scaled_size, scaled_size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                )
                label.pixmap().setDevicePixelRatio(dpr)
                layout.addWidget(label)



class ProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Generate card images")
        self.setModal(True)
        self.setFixedSize(420, 120)

        self.setStyleSheet("""
            QDialog { background:#222; color:white; }
            QLabel { color:white; }
            QProgressBar {
                background:#111;
                border:1px solid #555;
                height:18px;
                text-align:center;
            }
            QProgressBar::chunk {
                background:#3daee9;
            }
        """)

        self.label = QLabel("under preparation...")
        self.bar = QProgressBar()
        self.bar.setValue(0)

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

    def start(self, maximum: int, text: str = ""):
        self.bar.setMaximum(maximum)
        self.bar.setValue(0)
        if text:
            self.label.setText(text)
        QApplication.processEvents()

    def update_progress(self, value: int, text: str = ""):
        self.bar.setValue(value)
        if text:
            self.label.setText(text)
        QApplication.processEvents()



def get_mana_value(mana_cost: str) -> int:
    """Calculates mana value (CMC) from a mana cost string like {2}{G}{G}."""
    if not mana_cost:
        return 0
    # Remove braces
    content = mana_cost.replace("{", "").replace("}", " ").strip()
    # Split by space
    parts = content.split()
    total = 0
    for p in parts:
        if p.isdigit():
            total += int(p)
        elif p in ("X", "Y", "Z"):
            total += 0
        else:
            # Most symbols like G, U, R, B, W, C, S count as 1
            # Hybrid mana {G/U} or Phyrexian {G/P} also count as 1 mana value
            # Split by '/' if needed, but normally each group of braces is 1 mana value
            total += 1
    return total

def sort_cards(cards: List[Dict]) -> List[Dict]:
    """
    Sorts cards according to the following priority:
    1. Commander A
    2. Commander B
    3. Companion
    4. Mainboard (Creature -> Spell -> Land)
       - Within Mainboard: CMC (asc), then Name (asc)
    """
    if not cards:
        return []

    # Separate cards into categories
    comm_a = []
    comm_b = []
    comp = []
    creatures = []
    instants = []
    sorceries = []
    enchantments = []
    artifacts = []
    planeswalkers = []
    battles = []
    lands = []

    for c in cards:
        if c.get("Commander_A"):
            comm_a.append(c)
        elif c.get("Commander_B"):
            comm_b.append(c)
        elif c.get("Companion"):
            comp.append(c)
        else:
            tl = c.get("type_front", "").lower()
            if "land" in tl:
                lands.append(c)
            elif "creature" in tl:
                creatures.append(c)
            elif "instant" in tl:
                instants.append(c)
            elif "sorcery" in tl:
                sorceries.append(c)
            elif "enchantment" in tl:
                enchantments.append(c)
            elif "artifact" in tl:
                artifacts.append(c)
            elif "planeswalker" in tl:
                planeswalkers.append(c)
            elif "battle" in tl:
                battles.append(c)
            else:
                sorceries.append(c) # Fallback for other spells

    # Sort each category (except commanders/companion which are usually singletons)
    def sub_sort_key(card):
        mv = get_mana_value(card.get("mana_cost", ""))
        cost_str = card.get("mana_cost", "")
        name = card.get("name_en", "").lower()
        return (mv, cost_str, name)

    for cat_list in [creatures, instants, sorceries, enchantments, artifacts, planeswalkers, battles, lands]:
        cat_list.sort(key=sub_sort_key)

    return (comm_a + comm_b + comp + creatures + instants + sorceries + 
            enchantments + artifacts + planeswalkers + battles + lands)

# ================= CardListItem =================

class CardListItem(QWidget):
    def __init__(self, mana: str, card_type: str, name: str):
        super().__init__()

        font = QFont("", UI_FONT_SIZE)

        # Mana cost
        mana_widget = ManaCostWidget(mana)
        mana_widget.setFixedWidth(200)

        # Card type
        type_label = QLabel(card_type)
        type_label.setFont(font)
        type_label.setAlignment(Qt.AlignCenter)
        type_label.setFixedWidth(160)  

        # Card name
        name_label = QLabel(name)
        name_label.setFont(font)
        name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(10)
        layout.addWidget(type_label)
        layout.addWidget(mana_widget)
        layout.addWidget(name_label)

# ================= MainWindow =================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # V17.2: Final Release-ready icon settings
        self.setWindowIcon(get_app_icon())
        self.setWindowTitle(f"Commander Tool (v{APP_VERSION})")
        self.resize(820, 620)

        # V16: Delayed refresh to help the taskbar "catch up"
        QTimer.singleShot(1500, lambda: self.setWindowIcon(get_app_icon()))

        self.setStyleSheet(f"""
            QWidget {{
                background: #222;
                color: white;
                font-size: {UI_FONT_SIZE}px;
            }}
            QListWidget {{
                background: #111;
            }}
        """)

        # ---- Language selector ----
        self.language = "ja"

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("日本語", "ja")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.currentIndexChanged.connect(self.change_language)

        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Language:"))
        lang_layout.addWidget(self.lang_combo)
        lang_layout.addStretch()

        self.csv_path = None
        self.cards = []
        self.filtered_indices = []
        self.image_dir = app_dir()
        self.camera_window = None

        self.list = QListWidget()
        self.list.itemClicked.connect(self.select_card)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_context_menu)

        self.camera_chk = QCheckBox(UI_TEXT[self.language]["camera_mode"])
        self.camera_chk.stateChanged.connect(self.toggle_camera)

        self.type_filter_label = QLabel(UI_TEXT[self.language]["type_filter"])
        self.type_filter = QComboBox()
        self.type_filter.addItem(UI_TEXT[self.language]["all"], None)
        for t in TYPE_LABELS["en"].keys(): 
            self.type_filter.addItem(TYPE_LABELS[self.language][t], t)
        self.type_filter.currentIndexChanged.connect(self.apply_filter)

        self.font_size = QSpinBox()
        self.font_size.setRange(8, 30)
        self.font_size.setValue(18)
        self.font_size.valueChanged.connect(self.change_text_size)
        self.font_size_label = QLabel(UI_TEXT[self.language]["text_size"])

        self.reset_btn = QPushButton(UI_TEXT[self.language]["reset"])
        self.reset_btn.clicked.connect(self.reset_counters)

        self.mulligan_btn = QPushButton(UI_TEXT[self.language]["mulligan_simulator"])
        self.mulligan_btn.clicked.connect(self.launch_mulligan_simulator)
        self.mulligan_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: #ffaa00;
                font-weight: bold;
                border: 1px solid #ffaa00;
            }
            QPushButton:hover { background-color: #4d4d4d; }
        """)

        self.btn_deck_building = QPushButton(UI_TEXT[self.language]["deck_building"])
        self.btn_deck_building.clicked.connect(self.launch_deck_building)
        self.btn_deck_building.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: #00ccff;
                font-weight: bold;
                border: 1px solid #00ccff;
            }
            QPushButton:hover { background-color: #4d4d4d; }
        """)


        self.btn_test_play = QPushButton(UI_TEXT[self.language]["launch_test_play"])
        self.btn_test_play.clicked.connect(self.launch_test_play)
        self.btn_test_play.setStyleSheet("""
            QPushButton {
                background-color: #3d3d3d;
                color: #ff5555;
                font-weight: bold;
                border: 1px solid #ff5555;
            }
            QPushButton:hover { background-color: #4d4d4d; }
        """)

        self.btn_txt = QPushButton(UI_TEXT[self.language]["generate_fm_txt"])
        self.btn_csv = QPushButton(UI_TEXT[self.language]["load_csv"])
        self.btn_txt.clicked.connect(self.generate_from_txt)
        self.btn_csv.clicked.connect(self.load_csv_direct)

       
        self.commander_a_btn = QPushButton(UI_TEXT[self.language]["commander_a"])
        self.commander_b_btn = QPushButton(UI_TEXT[self.language]["commander_b"])
        self.companion_btn = QPushButton(UI_TEXT[self.language]["companion"])

        self.commander_a_btn.clicked.connect(lambda: self.show_commander("Commander_A"))
        self.commander_b_btn.clicked.connect(lambda: self.show_commander("Commander_B"))
        self.companion_btn.clicked.connect(lambda: self.show_commander("Companion"))

        commander_layout = QHBoxLayout()
        commander_layout.addWidget(self.commander_a_btn)
        commander_layout.addWidget(self.commander_b_btn)
        commander_layout.addWidget(self.companion_btn)


        layout = QVBoxLayout(self)
        layout.addLayout(lang_layout)
        layout.addWidget(self.camera_chk)
        layout.addSpacing(10)
        layout.addWidget(self.btn_txt)
        layout.addWidget(self.btn_csv)
        layout.addWidget(self.reset_btn)
        layout.addWidget(self.mulligan_btn)
        layout.addWidget(self.btn_deck_building)
        layout.addWidget(self.btn_test_play)
        layout.addSpacing(20)
        layout.addWidget(self.font_size_label)
        layout.addWidget(self.font_size)
        layout.addSpacing(20)
        layout.addLayout(commander_layout)
        layout.addSpacing(10)
        layout.addWidget(self.type_filter_label)
        layout.addWidget(self.type_filter)
        layout.addWidget(self.list)

        self.play = PlayWindow(self.image_dir, self.language)
        self.play.show()

        if DEBUG_MODE:
            QTimer.singleShot(100, self.load_debug_csv)

    def load_debug_csv(self):
        # Using the relative path provided by the user
        debug_csv = Path(__file__).parent / "../../Toph, the First Metalbender_images/Toph, the First Metalbender.csv"
        if debug_csv.exists():
            logging.info(f"DEBUG_MODE: Loading default CSV: {debug_csv}")
            self.load_csv(debug_csv, debug_csv.parent)
        else:
            logging.warning(f"DEBUG_MODE: File not found: {debug_csv}")


    def retranslate_ui(self):
        lang = self.language

        self.btn_txt.setText(UI_TEXT[self.language]["generate_fm_txt"])
        self.btn_csv.setText(UI_TEXT[self.language]["load_csv"])
        self.camera_chk.setText(UI_TEXT[lang]["camera_mode"])
        self.reset_btn.setText(UI_TEXT[lang]["reset"])
        self.mulligan_btn.setText(UI_TEXT[lang]["mulligan_simulator"])
        self.btn_deck_building.setText(UI_TEXT[lang]["deck_building"])
        self.btn_test_play.setText(UI_TEXT[lang]["launch_test_play"])
        self.commander_a_btn.setText(UI_TEXT[lang]["commander_a"])
        self.commander_b_btn.setText(UI_TEXT[lang]["commander_b"])
        self.companion_btn.setText(UI_TEXT[lang]["companion"])

        self.type_filter_label.setText(UI_TEXT[lang]["type_filter"])
        self.font_size_label.setText(UI_TEXT[lang]["text_size"])
        self.camera_chk.setText(UI_TEXT[lang]["camera_mode"])

    def load_csv_direct(self):
        base = exe_dir()
        dialog = QFileDialog(self, "Select CSV", str(base), "CSV (*.csv)")
        dialog.setOption(QFileDialog.DontUseNativeDialog) # Required on Windows for ProxyModel
        
        # Style the dialog for dark mode (non-native dialog inherits QWidget style but headers can be tricky)
        dialog.setStyleSheet(f"""
            QFileDialog {{
                background-color: #222;
            }}
            QTreeView, QListView {{
                background-color: #111;
                color: white;
            }}
            QHeaderView::section {{
                background-color: #333;
                color: white;
                padding: 4px;
                border: 1px solid #444;
            }}
            QLineEdit {{
                background-color: #111;
                color: white;
                border: 1px solid #555;
            }}
        """)

        proxy = CSVFilterProxyModel(self)
        dialog.setProxyModel(proxy)
        
        if dialog.exec_() == QDialog.Accepted:
            files = dialog.selectedFiles()
            if files:
                csv_path = files[0]
                self.load_csv(Path(csv_path), Path(csv_path).parent)

    def launch_deck_building(self):
        if not self.csv_path:
             QMessageBox.warning(self, "Warning", "Please load CSV first.")
             return
        
        # Pass loaded cards to DeckBuildingWindow
        # Note: DeckBuildingWindow expects cards list similar to what we have?
        # Actually DeckBuildingWindow loads built deck from somewhere?
        # No, user wants to build deck. 
        # But wait, logic for DeckBuildingWindow?
        # Let's check DeckBuildingWindow init.
        # It usually takes parent and maybe existing deck?
        # In current code (that I didn't fully read), let's assume it works.
        
        # User request: "Test Play window uses loaded CSV."
        
        # For simplicity, relaunch DeckBuildingWindow logic if needed, but I am adding TestPlay launch here.
        
        win = DeckBuildingWindow(self.csv_path, self.language, self)
        win.show()

    def launch_test_play(self):
        if not self.csv_path:
             QMessageBox.warning(self, "Warning", "Please load CSV first.")
             return
             
        # Create TestPlayWindow
        # Pass self.cards (loaded csv content)
        deck_name = self.csv_path.stem
        self.test_play_window = TestPlayWindow(self.cards, deck_name, self.language)
        self.test_play_window.show()

    def toggle_camera(self, state):
        if state == Qt.Checked:
            if not self.csv_path:
                QMessageBox.warning(
                    self,
                    "CSV未読み込み",
                    "先にCSVを読み込んでください"
                )
                self.camera_chk.setChecked(False)
                return

            if not self.camera_window:
                self.camera_window = CameraWindow(self.csv_path)
                self.camera_window.cardDetected.connect(self.on_card_detected)
            self.camera_window.show()
        else:
            if self.camera_window:
                self.camera_window.close()
                self.camera_window = None

    def on_card_detected(self, card_name: str):
        if not card_name:
            return

        for i, c in enumerate(self.cards):            
            if card_name in (c.get("name_en"), c.get("name_ja")):


                # If not included in the current filter, force switch to "All"
                if i not in self.filtered_indices:
                    self.type_filter.blockSignals(True)
                    self.type_filter.setCurrentIndex(0)
                    self.type_filter.blockSignals(False)
                    self.apply_filter()

                self.select_card_by_index(i)
                return



    def select_card_by_index(self, index: int):
        if index < 0 or index >= len(self.cards):
            return

        # Find the position inside filtered_indices
        if index not in self.filtered_indices:
            return

        row = self.filtered_indices.index(index)
        item = self.list.item(row)

        if item:
            self.list.setCurrentItem(item)
            self.select_card(item)

    def show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)

        # Current language
        lang = self.language

        # Get card for role check
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]
        
        label_a = "unset_commander_a" if card.get("Commander_A") else "set_commander_a"
        label_b = "unset_commander_b" if card.get("Commander_B") else "set_commander_b"
        label_comp = "unset_companion" if card.get("Companion") else "set_companion"

        # create right click menu
        action_image = menu.addAction(UI_TEXT[lang]["select_image"])
        action_commander_a = menu.addAction(UI_TEXT[lang][label_a])
        action_commander_b = menu.addAction(UI_TEXT[lang][label_b])
        action_companion = menu.addAction(UI_TEXT[lang][label_comp])
        
        # Multiple Illustrations for Basic Lands
        action_add_illustration = None
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]
        if "Basic Land" in card.get("type_front", ""):
            menu.addSeparator()
            action_add_illustration = menu.addAction(UI_TEXT[lang]["add_different_illustration"])

        action = menu.exec_(self.list.mapToGlobal(pos))
        if not action:
            return

        # actions
        if action == action_image:
            self.open_image_selector(item)
        elif action == action_add_illustration:
            self.open_image_selector_for_new_illustration(item)
        elif action == action_commander_a:
            self.set_commander(item, "Commander_A")
        elif action == action_commander_b:
            self.set_commander(item, "Commander_B")
        elif action == action_companion:
            self.set_commander(item, "Companion")


    def set_commander(self, item, column):
        """
        Set Commander A / B or Companion.
        Unsets the same column for all other cards.
        """
        idx = self.filtered_indices[self.list.row(item)]
        target_card = self.cards[idx]

        # Check if already set
        is_already_set = bool(target_card.get(column))

        # Reset the column for all cards first
        for c in self.cards:
            c[column] = ""

        if not is_already_set:
            # Set for the target card
            target_card[column] = target_card["name_ja"] if self.language == "ja" else target_card["name_en"]

        # Reflect to csv (this will also sort them, potentially moving the card to top)
        self.save_current_csv()
        
        # Refresh the list to show new order if needed
        self.apply_filter()

        # Show the updated card in the preview panel
        self.show_commander(column)


    def generate_from_txt(self):
        base = exe_dir()
        txt, _ = QFileDialog.getOpenFileName(
            self,
            "Select txt",
            str(base),
            "Text (*.txt)"
        )
        if not txt:
            return

        txt_path = Path(txt)

        if not is_ascii_filename(txt_path):
            QMessageBox.warning(
                self,
                "Invalid file name",
                "日本語を含むファイル名の txt は使用できません。\n"
                "英数字のみの名前に変更してください。"
            )
            return

        out = txt_path.parent / f"{txt_path.stem}_images"
        out.mkdir(parents=True, exist_ok=True)

        dialog = ProgressDialog(self)
        dialog.show()

        # ★ progress callback
        def progress(i, total, name):
            if i == 1:
                dialog.start(total, name)
            else:
                dialog.update_progress(i, name)

        try:
            csv_path = generator.generate_from_txt(
                txt_path,
                out,
                language=self.language,
                progress_callback=progress
            )
        finally:
            dialog.close()

        if csv_path:
            self.load_csv(csv_path, out)

    def load_csv(self, csv_path: Path, image_dir: Path):
        self.csv_path = csv_path 
        self.cards.clear()
        self.filtered_indices.clear()
        self.list.clear()

        self.image_dir = image_dir
        self.play.image_dir = image_dir

        temp_cards = []
        with open(csv_path, encoding="utf-8") as f:
            temp_cards = list(csv.DictReader(f))

        if temp_cards:
            # Migration detection: 
            # 1. Old schema check (missing type_front)
            # 2. Missing count column check
            needs_save = False
            
            if temp_cards[0].get("type_front") is None:
                logging.info(f"Migrating legacy CSV (type schema): {csv_path}")
                for c in temp_cards:
                    old_type = c.get("type", "")
                    if " // " in old_type:
                        parts = old_type.split(" // ")
                        c["type_front"] = parts[0]
                        c["type_back"] = parts[1] if len(parts) > 1 else ""
                    else:
                        c["type_front"] = old_type
                        c["type_back"] = ""
                    if "type" in c:
                        del c["type"]
                needs_save = True

            if temp_cards[0].get("count") is None:
                logging.info(f"Migrating CSV (adding count): {csv_path}")
                for c in temp_cards:
                    c["count"] = "1" # CSV values are strings
                needs_save = True

            if temp_cards[0].get("is_token") is None:
                logging.info(f"Migrating CSV (adding is_token): {csv_path}")
                for c in temp_cards:
                    c["is_token"] = "False"
                needs_save = True

            # Sort cards before assigning to self.cards
            temp_cards = sort_cards(temp_cards)
            self.cards = temp_cards
            
            if needs_save:
                self.save_current_csv()

        self.apply_filter()
        if self.cards:
            self.show_commander("Commander_A")

    def apply_filter(self):
        """Rebuild the card list based on the type filter"""
        self.list.clear()
        self.filtered_indices.clear()

        # Get the internal value from the ComboBox (None or English type)
        selected_type = self.type_filter.currentData()

        for i, c in enumerate(self.cards):
            # Exclude tokens from the main list view
            if c.get("is_token") == "True":
                continue

            # Use 'type_front' for filtering
            type_line = c.get("type_front", "")
            main_types_part = type_line.split(" — ")[0]

            # Split by spaces → ["Artifact", "Creature"]
            main_types = main_types_part.split(" ")

            # Filter condition
            if selected_type is not None and selected_type not in main_types:
                continue

            # Use UI language for the display label
            card_type_label = get_display_type(c.get("type_front", ""), self.language)
            raw_name = c["name_ja"] if self.language == "ja" else c["name_en"]
            card_name = strip_ruby(raw_name)

            # Create list item
            item = QListWidgetItem()
            widget = CardListItem(
                c.get("mana_cost", ""),
                card_type_label,
                card_name
            )

            item.setSizeHint(widget.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)

            # Store the original index from the full list
            self.filtered_indices.append(i)


    def change_language(self):
        self.language = self.lang_combo.currentData()

        # update labels
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem(UI_TEXT[self.language]["all"], None) 
        for t_en in TYPE_LABELS["en"].keys():  # Internal values are fixed to English
            t_label = TYPE_LABELS[self.language][t_en]  # Display labels are language-dependent
            self.type_filter.addItem(t_label, t_en)
        self.type_filter.blockSignals(False)

        self.retranslate_ui()
        self.apply_filter()
        self.play.language = self.language
        self.play.retranslate_ui()
        self.play._update()


    def select_card(self, item):
        idx = self.filtered_indices[self.list.row(item)]
        selected_card = self.cards[idx]
        stack = self.get_special_stack(selected_card)
        self.play.show_card(selected_card, stack_cards=stack)

    def get_special_stack(self, card):
        """Helper to find all special cards (Comm A, B, Comp) and return as a list."""
        is_special = card.get("Commander_A") or card.get("Commander_B") or card.get("Companion")
        if not is_special:
            return None

        stack = []
        seen_ids = set()
        for col in ["Commander_A", "Commander_B", "Companion"]:
            for c in self.cards:
                if c.get(col):
                    # Use front file as a unique-ish ID for the actual image entity
                    cid = c.get("card_file_front")
                    if cid not in seen_ids:
                        stack.append(c)
                        seen_ids.add(cid)
                    break
        return stack

    def change_text_size(self, size):
        self.play.set_text_font_size(size)

   
    def show_commander(self, slot=None):
        """
        slot:
            "Commander_A" - Commander A
            "Commander_B" - Commander B
            "Companion"   - Companion
            None          - Last card in the CSV (legacy behavior)
        """
        card_to_show = None

        if not self.cards:
            return

        if slot is None:
            # Legacy behavior: show the last card (Hareruya deck list format)
            card_to_show = self.cards[-1]
        else:
            # Find the card corresponding to the given slot
            for c in self.cards:
                if c.get(slot):
                    card_to_show = c
                    break

            if card_to_show is None:
                lang = self.language  # "ja" or "en"
                slot_label = UI_TEXT[lang].get(slot.lower(), slot)
                QMessageBox.warning(
                    self,
                    "Not Set", 
                    f"{slot_label} is not set."
                )
                return

        stack = self.get_special_stack(card_to_show)
        self.play.show_card(card_to_show, stack_cards=stack)


    def reset_counters(self):
        self.play.reset_counters()

    def launch_mulligan_simulator(self):
        if not self.csv_path:
            QMessageBox.warning(
                self,
                "CSV Loader",
                UI_TEXT[self.language]["csv_not_loaded"]
            )
            return

        # StartWindow will automatically trigger loading because we pass csv_path
        # V24.0: Pass language directly to constructor
        self.sim_start_window = mulligan_simulator.StartWindow(initial_csv=self.csv_path, language=self.language)
        
        self.sim_start_window.show()

    def launch_deck_building(self):
        if not self.csv_path or not self.cards:
            QMessageBox.warning(
                self,
                "CSV Loader",
                UI_TEXT[self.language]["csv_not_loaded"]
            )
            return

        self.deck_building_win = DeckBuildingWindow(self.cards, self.image_dir, self.language, csv_path=self.csv_path)
        self.deck_building_win.data_changed.connect(self.apply_filter)
        self.deck_building_win.show()

    def launch_test_play(self):
        if not self.csv_path:
             QMessageBox.warning(
                 self,
                 "CSV Loader",
                 UI_TEXT[self.language]["csv_not_loaded"]
             )
             return
             
        # Create TestPlayWindow
        deck_name = self.csv_path.stem
        self.test_play_window = TestPlayWindow(self.cards, deck_name, self.language, image_root=self.csv_path.parent, csv_path=self.csv_path)
        self.test_play_window.show()


    def open_image_selector(self, item):
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]
        image_path = self.image_dir / card["card_file_front"]
        card_name = card["name_en"]
        is_token = (str(card.get("is_token")) == "True")

        dlg = ImageSelectDialog(card_name, image_path, self, is_token=is_token)
        if dlg.exec_():
            face = dlg.selected_face
            oid = face.get("oracle_id")
            
            # If it's a token, enforce the unique name-ID filename
            if is_token and oid:
                card["oracle_id"] = oid # Sync metadata
                short_oid = f"_{oid[:8]}"
                safe_name = generator.safe_filename(card["name_en"])
                card["card_file_front"] = f"{safe_name}{short_oid}_front.jpg"
                if card.get("card_file_back"):
                     card["card_file_back"] = f"{safe_name}{short_oid}_back.jpg"

            front_path = self.image_dir / card["card_file_front"]
            back_path = (self.image_dir / card["card_file_back"]) if card.get("card_file_back") else None

            # Download selected face
            import requests
            data = requests.get(face["image_normal"], timeout=5).content
            if face["face_index"] == 0:
                front_path.write_bytes(data)
            elif back_path:
                back_path.write_bytes(data)

            # Update opposite face if it's a double-faced card
            if back_path:
                for r in dlg.all_results:
                    if (r["card_id"] == face["card_id"] and 
                        r["lang"] == face["lang"] and 
                        r["face_index"] != face["face_index"]):
                        
                        other_data = requests.get(r["image_normal"], timeout=5).content
                        if face["face_index"] == 0:
                            back_path.write_bytes(other_data)
                        else:
                            front_path.write_bytes(other_data)
                        break

            self.save_current_csv()
            QMessageBox.information(self, "Done", "Card images updated.")
            self.play._update()

    def open_image_selector_for_new_illustration(self, item):
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]
        card_name = card["name_en"]
        image_dir = self.image_dir

        # We don't have a specific path yet, just a name
        dlg = ImageSelectDialog(card_name, image_dir / card["card_file_front"], self)
        if dlg.exec_():
            face = dlg.selected_face
            
            # 1. Generate unique filename
            base_name = card["card_file_front"]  # e.g., Forest_front.jpg
            stem = Path(base_name).stem
            ext = Path(base_name).suffix
            
            # Remove existing numbering if any? 
            # User said "Forest_front_2.jpg" if original is "Forest_front.jpg".
            # Let's check stem and increment.
            
            def get_next_filename(dir_path, base_stem, extension):
                counter = 2
                while True:
                    candidate = f"{base_stem}_{counter}{extension}"
                    if not (dir_path / candidate).exists():
                        return candidate
                    counter += 1
            
            new_filename = get_next_filename(image_dir, stem, ext)
            new_path = image_dir / new_filename
            
            # 2. Download and save
            try:
                data = requests.get(face["image_normal"], timeout=5).content
                new_path.write_bytes(data)
                
                # 3. Create new card entry
                new_card = card.copy()
                new_card["card_file_front"] = new_filename
                new_card["count"] = "1" # Default to 1 for new illustration
                
                # Add to self.cards
                self.cards.append(new_card)
                
                # 4. Save CSV
                self.save_current_csv()
                
                # 5. Refresh
                QMessageBox.information(self, "Done", f"Added new illustration: {new_filename}")
                self.apply_filter()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to download image: {e}")

    def save_current_csv(self):
        if not self.csv_path or not self.cards:
            return
        
        # 1. Gather all keys from current cards
        all_card_keys = set()
        for c in self.cards:
            all_card_keys.update(c.keys())

        # 2. Get existing fieldnames to maintain order if possible
        fieldnames = []
        try:
            if self.csv_path.exists():
                with self.csv_path.open("r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames or []
        except:
            pass

        # 3. Ensure all keys from data are in fieldnames
        for k in sorted(all_card_keys):
            if k not in fieldnames:
                fieldnames.append(k)

        # 4. Filter fieldnames to only those actually present in current data
        final_fieldnames = [f for f in fieldnames if f in all_card_keys]

        # Sort cards before saving
        self.cards = sort_cards(self.cards)

        with self.csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=final_fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(self.cards)







if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support() 

    if platform.system() == "Windows":
        import ctypes
        from ctypes import wintypes
        try:
            myappid = "Tiora.CommanderTool.Final"
            shell32 = ctypes.windll.shell32
            shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPWSTR]
            hr = shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    
    app.setApplicationName("CommanderTool")
    app.setOrganizationName("Tiora")
    app.setApplicationVersion(APP_VERSION)

    # Initial Splash (V23.1: At the very start!)
    splash = StartupSplashScreen()
    splash.show()
    splash.update_status("Starting up...", 5)
    app.processEvents()

    # Load heavy modules with status
    splash.update_status("Loading core modules...", 15)
    import generator as gen_mod
    generator = gen_mod
    
    splash.update_status("Loading deck editor...", 30)
    from deck_building_window import DeckBuildingWindow as DBW
    DeckBuildingWindow = DBW
    
    splash.update_status("Loading simulation engine...", 45)
    import mulligan_simulator as ms_mod
    mulligan_simulator = ms_mod
    
    splash.update_status("Loading card viewer...", 60)
    from play_window import PlayWindow as PW
    PlayWindow = PW
    from test_play_window import TestPlayWindow as TPW
    TestPlayWindow = TPW
    
    splash.update_status("Loading AI camera...", 75)
    from camera_window import CameraWindow as CW
    CameraWindow = CW

    # Assets
    ensure_emojis(splash)

    splash.update_status("Finalizing UI...", 95)
    icon = get_app_icon()
    app.setWindowIcon(icon)
    app.setFont(QFont("Arial", 10))
    app.setDesktopFileName("Tiora.CommanderTool.Final")

    # Main window
    w = MainWindow()
    splash.close()
    w.show()
    sys.exit(app.exec_())



