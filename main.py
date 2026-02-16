# main.py
import sys
import csv
from pathlib import Path
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QTextBrowser, QComboBox,
    QSplitter, QSpinBox, QDialog, QProgressBar, QSizePolicy,
    QMessageBox, QMenu, QCheckBox, QFrame, QGridLayout, QScrollArea
)
from PyQt5.QtCore import Qt, QUrl, QSize, QPoint, QTimer, QSortFilterProxyModel
from image_selector import ImageSelectDialog
from PyQt5.QtGui import (
    QTextDocument,
    QPixmap,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPalette,
    QColor      
)
import requests
import generator
from camera_window import CameraWindow

from PyQt5.QtCore import QRunnable, QObject, pyqtSignal, QThreadPool

import zipfile
import io
from gui_language import UI_TEXT, TYPE_LABELS
import traceback
from play_window import PlayWindow
from config import APP_VERSION, EMOJI_DIR, UI_FONT_SIZE
from common_func import strip_ruby, mana_symbol_to_filename, app_dir, exe_dir
from deck_building_window import DeckBuildingWindow

import mulligan_simulator

import os
import logging
import platform

# ==== Safeguard for stdout / stderr ====
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# ==== Suppress Hugging Face / tqdm / transformers output ====
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import logging

DEBUG_LOG = True

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
def get_app_icon():
    icon_dir = app_dir() / "icons"

    if platform.system() == "Darwin":
        # macOS
        return QIcon(str(icon_dir / "commander_tool_icon.icns"))
    else:
        # Windows / Linux → ICO を使うのが安全
        return QIcon(str(icon_dir / "commander_tool_icon.ico"))
    
def set_app_icon(window):
    base = app_dir() / "icons"

    # Select appropriate icon depending on OS
    if platform.system() == "Windows":
        # Use .ico for Windows (affects taskbar icon)
        icon_file = base / "commander_tool_icon.ico"
    elif platform.system() == "Darwin":
        # Use .icns for macOS (Dock will automatically use this icon)
        icon_file = base / "commander_tool_icon_mac.icns"
    else:
        # Fallback for Linux or others
        icon_file = base / "commander_tool_icon.png"

    # Set window icon (Windows taskbar uses this)
    window.setWindowIcon(QIcon(str(icon_file)))


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


def get_display_type(type_line: str, lang: str) -> str:
    if not type_line:
        return ""

    for key in TYPE_LABELS[lang]:
        if key in type_line:
            return TYPE_LABELS[lang][key]

    return type_line



def ensure_emojis():
    """
    If resource_dir()/emojis does not exist,
    download manamoji-slack from GitHub and extract emojis
    """
    if EMOJI_DIR.exists():
        return

    try:
        logging.info("Downloading mana emojis from GitHub...")
        r = requests.get(EMOJI_ZIP_URL, timeout=15)
        r.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for member in z.namelist():
                # Extract only the emojis directory
                if "emojis/" in member and not member.endswith("/"):
                    target = EMOJI_DIR / Path(member).name
                    EMOJI_DIR.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())

        logging.info("Mana emojis downloaded.")

    except Exception as e:
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
            filename = model.data(index)
            if filename and isinstance(filename, str) and filename.endswith("_consideration.csv"):
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

        for sym in parse_mana_cost(mana_cost):
            fn = mana_symbol_to_filename(sym)
            path = EMOJI_DIR / fn
            if not path.exists():
                continue

            label = QLabel()
            pix = QPixmap(str(path))
            if not pix.isNull():
                label.setPixmap(
                    pix.scaled(
                        22, 22,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                )
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
        set_app_icon(self)
        self.setWindowTitle(f"Commander Tool (v{APP_VERSION}) - Main Window -")
        self.resize(820, 620)

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

    def retranslate_ui(self):
        lang = self.language

        self.btn_txt.setText(UI_TEXT[self.language]["generate_fm_txt"])
        self.btn_csv.setText(UI_TEXT[self.language]["load_csv"])
        self.camera_chk.setText(UI_TEXT[lang]["camera_mode"])
        self.reset_btn.setText(UI_TEXT[lang]["reset"])
        self.mulligan_btn.setText(UI_TEXT[lang]["mulligan_simulator"])
        self.btn_deck_building.setText(UI_TEXT[lang]["deck_building"])
        self.commander_a_btn.setText(UI_TEXT[lang]["commander_a"])
        self.commander_b_btn.setText(UI_TEXT[lang]["commander_b"])
        self.companion_btn.setText(UI_TEXT[lang]["companion"])

        self.font_size_label.setText(UI_TEXT[lang]["text_size"])
        self.type_filter_label.setText(UI_TEXT[lang]["type_filter"])

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

        # create right click menu
        action_image = menu.addAction(UI_TEXT[lang]["select_image"])
        action_commander_a = menu.addAction(UI_TEXT[lang]["set_commander_a"])
        action_commander_b = menu.addAction(UI_TEXT[lang]["set_commander_b"])
        action_companion = menu.addAction(UI_TEXT[lang]["set_companion"])

        action = menu.exec_(self.list.mapToGlobal(pos))
        if not action:
            return

        # actions
        if action == action_image:
            self.open_image_selector(item)
        elif action == action_commander_a:
            self.set_commander(item, "Commander_A")
        elif action == action_commander_b:
            self.set_commander(item, "Commander_B")
        elif action == action_companion:
            self.set_commander(item, "Companion")


    def set_commander(self, item, column):
        """
        Set Commander A / B or Companion
        """
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]

        # choose card name
        card[column] = card["name_ja"] if self.language == "ja" else card["name_en"]

        # reflect to csv
        self.save_current_csv()


    def save_current_csv(self):
        """
        Save the current card data to CSV
        """
        if not self.csv_path or not self.cards:
            return

        fieldnames = [
            "card_file_front",
            "card_file_back",
            "name_front",
            "name_back",
            "name_ja",
            "name_en",
            "type_front",
            "type_back",
            "mana_cost",
            "text_front_ja",
            "text_front_en",
            "text_back_ja",
            "text_back_en",
            "Commander_A",
            "Commander_B",
            "Companion",
        ]

        try:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(self.cards)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save the CSV file:\n{e}")


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
            # Migration detection: if 'type_front' is missing, it's old schema
            if temp_cards[0].get("type_front") is None:
                logging.info(f"Migrating legacy CSV: {csv_path}")
                for c in temp_cards:
                    old_type = c.get("type", "")
                    if " // " in old_type:
                        parts = old_type.split(" // ")
                        c["type_front"] = parts[0]
                        c["type_back"] = parts[1] if len(parts) > 1 else ""
                    else:
                        c["type_front"] = old_type
                        c["type_back"] = ""
                    # Remove old key
                    if "type" in c:
                        del c["type"]
                
                # Resave new schema immediately
                self.cards = temp_cards
                self.save_current_csv()
            else:
                self.cards = temp_cards


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
        self.play.show_card(self.cards[idx])

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

        self.play.show_card(card_to_show)


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
        self.sim_start_window = mulligan_simulator.StartWindow(initial_csv=self.csv_path)
        # Use initial_csv's language if possible, otherwise it defaults to JA in StartWindow.__init__
        # For now, it will use StartWindow's default (JA). 
        # But we can sync it:
        self.sim_start_window.language = self.language
        self.sim_start_window.change_language() 
        
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

    def open_image_selector(self, item):
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]
        image_path = self.image_dir / card["card_file_front"]
        card_name = card["name_en"]

        dlg = ImageSelectDialog(card_name, image_path, self)
        if dlg.exec_():
            face = dlg.selected_face
            front_path = self.image_dir / card["card_file_front"]
            back_path = (self.image_dir / card["card_file_back"]) if card["card_file_back"] else None

            # Download selected face
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

            QMessageBox.information(self, "Done", "Card images updated.")
            self.play._update()







# ================= Entry =================
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support() 

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    
    # Set modern font for DPI-awareness and to prevent DirectWrite errors
    default_font = QFont("Meiryo UI", 10)
    app.setFont(default_font)

    ensure_emojis()

    # Set application-wide icon (affects Dock, taskbar, Alt+Tab)
    app_icon = QIcon(str(app_dir() / "icons" / "commander_tool_icon.ico"))
    QApplication.setWindowIcon(app_icon)

    # Main window
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

