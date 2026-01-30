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
    QMessageBox, QMenu, QCheckBox, QFrame, QGridLayout
)
from PyQt5.QtCore import Qt, QUrl, QSize, QPoint, QTimer
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

APP_VERSION = "1.0.2"

import os
import logging

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

UI_FONT_SIZE = 18

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


EMOJI_DIR = exe_dir() / "emojis"

EMOJI_ZIP_URL = (
    "https://github.com/scryfall/manamoji-slack/archive/refs/heads/main.zip"
)

PHYREXIAN_MAP = {
    "(W/P)": "{W/P}",
    "(U/P)": "{U/P}",
    "(B/P)": "{B/P}",
    "(R/P)": "{R/P}",
    "(G/P)": "{G/P}",
    "(w/p)": "{W/P}",
    "(u/p)": "{U/P}",
    "(b/p)": "{B/P}",
    "(r/p)": "{R/P}",
    "(g/p)": "{G/P}",
}

def get_display_type(type_line: str, lang: str) -> str:
    if not type_line:
        return ""

    for key in TYPE_LABELS[lang]:
        if key in type_line:
            return TYPE_LABELS[lang][key]

    return type_line


def normalize_mana_text(text: str) -> str:
    if not text:
        return text

    # -------------------------------------------------
    # ① (w/p) → {W/P}
    # -------------------------------------------------
    for k, v in PHYREXIAN_MAP.items():
        text = text.replace(k, v)

    # -------------------------------------------------
    # ② {1R} → {1}{R}, {2GG} → {2}{G}{G}
    # -------------------------------------------------
    def split_number_and_letters(match):
        content = match.group(1)
        parts = re.findall(r"\d+|[A-Z]+", content)
        expanded = []
        for p in parts:
            if p.isalpha() and len(p) > 1:
                expanded.extend(list(p))
            else:
                expanded.append(p)
        return "".join(f"{{{x}}}" for x in expanded)

    text = re.sub(r"\{(\d+[A-Z]+)\}", split_number_and_letters, text)

    # -------------------------------------------------
    # ③ {BB} → {B}{B}, {WWU} → {W}{W}{U}
    #    ※ {W/P}, {2/W}, {X} are excluded
    # -------------------------------------------------
    def expand_compact_mana(match):
        symbols = match.group(1)
        return "".join(f"{{{c}}}" for c in symbols)

    text = re.sub(
        r"\{([WUBRG]{2,})\}",
        expand_compact_mana,
        text
    )

    return text



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


# ================= Mana Symbol Handling =================

def parse_mana_cost(cost: str):
    if not cost:
        return []
    return re.findall(r"\{([^}]+)\}", cost)


def mana_symbol_to_filename(sym: str):
    sym = sym.upper()

    special = {
        "∞": "infinity"
    }

    if sym in special:
        return f"mana-{special[sym]}.png"

    return f"mana-{sym.lower().replace('/', '')}.png"


def mana_text_to_html(text: str, doc: QTextDocument, size_px: int, align_middle=False) -> str:
    if not text:
        return ""

    text = normalize_mana_text(text)

    def repl(match):
        sym = match.group(1)
        fn = mana_symbol_to_filename(sym)
        path = EMOJI_DIR / fn
        if not path.exists():
            return match.group(0)

        pix = QPixmap(str(path))
        if pix.isNull():
            return match.group(0)

        pix = pix.scaled(
            size_px, size_px,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        url = QUrl(f"mana:{sym}")
        doc.addResource(QTextDocument.ImageResource, url, pix)

        style = "vertical-align:middle;" if align_middle else ""
        return f'<img src="{url.toString()}" style="{style}">'

    html = re.sub(r"\{([^}]+)\}", repl, text)
    html = html.replace("\n", "<br>")
    return html



def strip_ruby(name: str) -> str:
    if not name:
        return name
    return re.sub(r"（[^）]*）", "", name)




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



# ================= Counter =================

class CounterWidget(QWidget):
    def __init__(self, title, initial, min_value=None, max_value=None):
        super().__init__()
        self.initial = initial
        self.value = initial
        self.min_value = min_value
        self.max_value = max_value

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(QFont("", UI_FONT_SIZE))

        self.value_label = QLabel(str(self.value))
        self.value_label.setAlignment(Qt.AlignCenter)

        value_font = QFont("", 48)
        value_font.setBold(True)
        self.value_label.setFont(value_font)

        plus = QPushButton("+")
        minus = QPushButton("-")
        plus.clicked.connect(self.inc)
        minus.clicked.connect(self.dec)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(plus)
        layout.addWidget(minus)

    def inc(self):
        if self.max_value is None or self.value < self.max_value:
            self.value += 1
            self.value_label.setText(str(self.value))

    def dec(self):
        if self.min_value is None or self.value > self.min_value:
            self.value -= 1
            self.value_label.setText(str(self.value))

    def reset(self):
        self.value = self.initial
        self.value_label.setText(str(self.value))



# ================= PlayWindow =================

class PlayWindow(QWidget):
    def __init__(self, image_dir: Path, language="ja"):
        super().__init__()
        self.image_dir = image_dir
        self.language = language
        self.card = None
        self.face = "front"

        self.setWindowTitle(f"Commander Tool (v{APP_VERSION}) - Play Window -")
        self.resize(560, 900)

        self.setStyleSheet("""
            QWidget { background:#111; color:white; }
            QTextBrowser { background:#1a1a1a; color:white; border:none; }
        """)

        self.commander_damage = {
            1: {"A": 0, "B": 0},
            2: {"A": 0, "B": 0},
            3: {"A": 0, "B": 0},
            4: {"A": 0, "B": 0},
        }
        self.counter_popup = None

        self.card_title = QTextBrowser()
        self.card_title.setFont(QFont("", 16))
        self.card_title.setStyleSheet("background:#1a1a1a; color:white; border:none;")
        self.card_title.setMaximumHeight(40)  
        self.card_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.card_title.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_title.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image.setMinimumSize(0, 0)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image.installEventFilter(self)

        self.text = QTextBrowser()
        self.text.setAlignment(Qt.AlignLeft)
        self.text_font = QFont("", 14)
        self.text.setFont(self.text_font)

        self.text.document().setDefaultStyleSheet("""
        img {
            height: 1em;
            width: auto;
        }
        """)


        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.image)
        self.splitter.addWidget(self.card_title)
        self.splitter.addWidget(self.text)

        self.flip_btn = QPushButton(UI_TEXT[self.language]["flip_back"])
        self.flip_btn.clicked.connect(self.flip)
        self.flip_btn.setEnabled(False)

        self.counter_btn = QPushButton(UI_TEXT[self.language]["commander_counters"])
        self.counter_btn.setFixedHeight(36)
        self.counter_btn.clicked.connect(self.toggle_counter_popup)


        self.player = CounterWidget(UI_TEXT[self.language]["player"], 1, min_value=1, max_value=4)
        self.life = CounterWidget(UI_TEXT[self.language]["life"], 40)

        counters = QHBoxLayout()
        counters.addWidget(self.player)
        counters.addWidget(self.life)

        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)
        layout.addWidget(self.flip_btn)
        layout.addWidget(self.counter_btn)
        layout.addLayout(counters)

    def retranslate_ui(self):
        lang = self.language

        if self.face == "front":
            self.flip_btn.setText(UI_TEXT[lang]["flip_back"])
        else:
            self.flip_btn.setText(UI_TEXT[lang]["flip_front"])

        self.player.title_label.setText(UI_TEXT[lang]["player"])
        self.life.title_label.setText(UI_TEXT[lang]["life"])

        self.counter_btn.setText(UI_TEXT[lang]["commander_counters"])

        if hasattr(self, "counter_popup"):
            self.counter_popup.retranslate_ui(lang)


    def show_card(self, card: dict):
        self.card = card
        self.face = "front"
        self.flip_btn.setEnabled(bool(card.get("card_file_back")))
        self._update()

    def _update(self):
        if not self.card:
            return

        
        raw_name = self.card.get("name_ja") if self.language == "ja" else self.card.get("name_en")
        card_name = strip_ruby(raw_name)
        mana_cost = self.card.get("mana_cost", "")
        doc_title = self.card_title.document()
        doc_title.clear()
        html_title = f"""
        <html>
        <body style="font-size:16pt; color:white; margin:0; padding:0; text-align:left;">
            {card_name}&nbsp;&nbsp;{mana_text_to_html(mana_cost, doc_title, 22, align_middle=True)}
        </body>
        </html>
        """

        self.card_title.setHtml(html_title)

        fn = (
                    self.card["card_file_front"]
                    if self.face == "front"
                    else self.card["card_file_back"]
                )

        lang = self.language

        key = (
            f"text_front_{lang}"
            if self.face == "front"
            else f"text_back_{lang}"
        )

        text = self.card.get(key, "")

        img = self.image_dir / fn
        if img.exists():
            pix = QPixmap(str(img))
            if not pix.isNull():
                self.image.setPixmap(
                    pix.scaled(
                        self.image.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                )

        font_pt = self.text_font.pointSize()
        icon_px = int(font_pt * 1.5)   

        doc = self.text.document()
        doc.clear()

        html = f"""
        <html>
        <body style="
            font-size:{font_pt}pt;
            line-height:1.4;
            color:white;
        ">
        {mana_text_to_html(text, doc, icon_px, align_middle=True)}
        </body>
        </html>
        """

        self.text.setHtml(html)


    def flip(self):
        self.face = "back" if self.face == "front" else "front"
        self.retranslate_ui()   
        self._update()


    def resizeEvent(self, e):
        self._update()

    def reset_counters(self):
        self.player.reset()
        self.life.reset()

        # ---- commander damage reset ----
        for p in self.commander_damage:
            for key in self.commander_damage[p]:
                self.commander_damage[p][key] = 0

        # ---- extra counters reset ----
        if self.counter_popup:
            for c in getattr(self.counter_popup, "extra_counters", {}).values():
                c.reset()

            if hasattr(self.counter_popup, "refresh"):
                self.counter_popup.refresh()

    def set_text_font_size(self, size):
        self.text_font.setPointSize(size)
        self._update()

    def eventFilter(self, obj, event):
        if obj is self.image and event.type() == event.Resize:
            self._update()
        return super().eventFilter(obj, event)
    

    def toggle_counter_popup(self):
        # If counter_popup exists and is currently visible, hide it
        if getattr(self, "counter_popup", None) is not None and self.counter_popup.isVisible():
            self.counter_popup.hide()
            return

        # If the popup does not exist yet, create it
        if getattr(self, "counter_popup", None) is None:
            self.counter_popup = CounterPopup(self, lang=self.language)
        else:
            # Always rebuild rows before showing to match the current player
            self.counter_popup.rebuild_rows()

        # Match the popup width to the PlayWindow width
        self.counter_popup.setFixedWidth(self.width())

        # Adjust the popup size to fit its content
        self.counter_popup.adjustSize()

        # Get the global position of the counter button and map it to the window
        btn_pos = self.counter_btn.mapToGlobal(QPoint(0, 0))
        win_pos = self.mapFromGlobal(btn_pos)

        x = 0  # Align the popup to the left of PlayWindow
        y = win_pos.y() - self.counter_popup.height() - 8  # Position it above the button

        # Move and show the popup
        self.counter_popup.move(x, y)
        self.counter_popup.show()
        self.counter_popup.raise_()

        # Adjust fonts of children after showing the popup (twice for safety)
        QTimer.singleShot(0, self.counter_popup.adjust_children_fonts)
        QTimer.singleShot(50, self.counter_popup.adjust_children_fonts)


    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update()
        if self.counter_popup and self.counter_popup.isVisible():
            self.counter_popup.hide()  

    
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self.counter_popup and self.counter_popup.isVisible():
            self.counter_popup.hide()  


class CounterPopup(QFrame):
    def __init__(self, parent=None, lang="ja"):
        super().__init__(parent)
        self.play = parent
        self.lang = lang
        self.rows = []
        self.build_ui()

        # Optional: popup-like appearance
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background: #222;
                border: none;
            }
        """)

    def build_ui(self):
        layout = QVBoxLayout(self)

        # ---- extra counters ----
        self.build_extra_counters(layout)

        # ---- title ----
        self.title_label = QLabel()
        self.title_label.setFont(QFont("", 16, QFont.Bold))
        layout.addWidget(self.title_label)

        # ---- commander damage ----
        my_player = self.play.player.value
        for p in range(1, 5):
            if p == my_player:
                continue
            row = PlayerCommanderRow(p, self.play, self.lang)
            self.rows.append(row)
            layout.addWidget(row)

        layout.addStretch()
        self.retranslate_ui(self.lang)

    def build_extra_counters(self, parent_layout):
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        base = app_dir() / "icons"  

        self.extra_counters = {
            "poison": IconCounterWidget(base / "poison.png"),
            "exp": IconCounterWidget(base / "exp.png"),
            "energy": IconCounterWidget(base / "energy.png"),
            "ticket": IconCounterWidget(base / "ticket.png"),
            "rad": IconCounterWidget(base / "rad.png"),
        }

        items = list(self.extra_counters.values())

        for i, w in enumerate(items):
            row = i // 2
            col = i % 2
            grid.addWidget(w, row, col)

        frame = QFrame()
        frame.setLayout(grid)
        frame.setStyleSheet("background:#1a1a1a; border-radius:6px;")
        parent_layout.addWidget(frame)

  
    def rebuild_rows(self):
        """Rebuild rows according to the current player"""
        layout = self.layout()

        # Remove old rows
        for row in self.rows:
            row.setParent(None)
        self.rows.clear()

        my_player = self.play.player.value

        for p in range(1, 5):
            if p == my_player:
                continue
            row = PlayerCommanderRow(p, self.play, self.lang)
            self.rows.append(row)
            layout.insertWidget(layout.count()-1, row)  # Insert before the stretch

        # Retranslate texts
        self.retranslate_ui(self.lang)
    
    def retranslate_ui(self, lang):
        self.lang = lang
        self.title_label.setText(
            UI_TEXT[lang]["commander_damage"]
        )

        for row in self.rows:
            row.retranslate_ui(lang)
        
        QTimer.singleShot(0, self.adjust_children_fonts)
    
    def adjust_children_fonts(self):
        for row in self.rows:
            row.ca.adjust_title_font()
            row.cb.adjust_title_font()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.adjust_children_fonts)
        QTimer.singleShot(50, self.adjust_children_fonts)
    

    def refresh(self):
        for row in self.rows:
            row.sync_from_model()

class CommanderDamageCounter(QWidget):
    valueChanged = pyqtSignal(int)  # delta (+1 / -1)
    
    def __init__(self, label_text: str, initial=0):
        super().__init__()
        self.value = initial

        self.base_font_family = ""
        self.base_font_weight = QFont.Bold
        self.max_font_size = 20
        self.min_font_size = 2

        self.title_label = QLabel(label_text) 
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(QFont("", 12,))
        self.title_label.setMinimumHeight(14)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.value_label = QLabel(str(self.value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(QFont("", 18, QFont.Bold))
        self.value_label.setFixedWidth(36)

        up = QPushButton("▲")
        down = QPushButton("▼")
        up.clicked.connect(lambda: self.change(1))
        down.clicked.connect(lambda: self.change(-1))

        btns = QVBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(0)
        btns.addWidget(up)
        btns.addWidget(down)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addLayout(btns)

        self.setStyleSheet("""
            QLabel {
                padding: 0;
                margin: 0;
            }
        """)

    def change(self, delta: int):
        self.value += delta
        if self.value < 0:
            self.value = 0
            return

        self.value_label.setText(str(self.value))
        self.valueChanged.emit(delta)
    
    def adjust_title_font(self):
        label = self.title_label
        text = label.text()
        if not text:
            return

        rect = label.contentsRect()
        max_width = rect.width() - 4
        max_height = rect.height() - 2

        if max_width <= 0 or max_height <= 0:
            QTimer.singleShot(0, self.adjust_title_font)
            return

        for size in range(self.max_font_size, self.min_font_size - 1, -1):
            font = QFont(self.base_font_family, size, self.base_font_weight)
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(text)
            text_height = fm.height()

            if text_width <= max_width and text_height <= max_height:
                label.setFont(font)
                return

        label.setFont(QFont(self.base_font_family, self.min_font_size, self.base_font_weight))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_title_font()


class PlayerCommanderRow(QWidget):
    def __init__(self, player_no: int, play_window: "PlayWindow", lang="ja"):
        super().__init__()
        self.play = play_window
        self.player_no = player_no
        self.lang = lang

        # --- Remove widget-level padding ---
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("""
            QLabel {
                padding: 0;
                margin: 0;
            }
        """)

        # --- Title label ---
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignLeft)
        self.title_label.setFont(QFont("", 12, QFont.Bold))

        # --- Damage counters ---
        self.ca = CommanderDamageCounter("", self.play.commander_damage[player_no]["A"])
        self.cb = CommanderDamageCounter("", self.play.commander_damage[player_no]["B"])

        # --- Horizontal row ---
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.ca)
        row.addWidget(self.cb)

        # --- Main layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_label)
        layout.addLayout(row)

        # Make the row compact
        self.setMinimumHeight(18)

        self.retranslate_ui(lang)


    def on_damage_changed(self, slot: str, delta: int):
        dmg = self.play.commander_damage[self.player_no][slot]
        dmg += delta
        if dmg < 0:
            dmg = 0

        self.play.commander_damage[self.player_no][slot] = dmg

        # Life adjustment
        self.play.life.value -= delta
        self.play.life.value_label.setText(str(self.play.life.value))

    def retranslate_ui(self, lang):
        self.lang = lang
        self.title_label.setText(
            f"{UI_TEXT[lang]['player']} {self.player_no} {UI_TEXT[lang]['commander']}"
        )
        self.ca.title_label.setText(" A :")
        self.cb.title_label.setText(" B :")

        QTimer.singleShot(0, self.ca.adjust_title_font)
        QTimer.singleShot(0, self.cb.adjust_title_font)
    
    def sync_from_model(self):
        a = self.play.commander_damage[self.player_no]["A"]
        b = self.play.commander_damage[self.player_no]["B"]

        self.ca.value = a
        self.ca.value_label.setText(str(a))

        self.cb.value = b
        self.cb.value_label.setText(str(b))


class IconCounterWidget(QWidget):
    def __init__(self, icon_path: Path, initial=0):
        super().__init__()
        self.value = initial

        # icon
        self.icon = QLabel()
        pix = QPixmap(str(icon_path))
        ICON_SIZE = 120

        self.icon.setPixmap(
            pix.scaled(
                ICON_SIZE,
                ICON_SIZE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        )
        self.icon.setFixedSize(ICON_SIZE, ICON_SIZE)

        self.icon.setAlignment(Qt.AlignCenter)

        # value
        self.value_label = QLabel(str(self.value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(QFont("", 20, QFont.Bold))
        self.value_label.setFixedWidth(40)

        # buttons
        up = QPushButton("▲")
        down = QPushButton("▼")
        up.clicked.connect(lambda: self.change(1))
        down.clicked.connect(lambda: self.change(-1))

        btns = QVBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.addWidget(up)
        btns.addWidget(down)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self.icon)
        layout.addWidget(self.value_label)
        layout.addLayout(btns)

    def change(self, delta):
        self.value = max(0, self.value + delta)
        self.value_label.setText(str(self.value))

    def reset(self):
        self.value = 0
        self.value_label.setText("0")


# ================= MainWindow =================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
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
            "type",
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
        csv_path, _ = QFileDialog.getOpenFileName(self, "Select CSV", str(base), "CSV (*.csv)")
        if csv_path:
            self.load_csv(Path(csv_path), Path(csv_path).parent)

    def load_csv(self, csv_path: Path, image_dir: Path):
        self.csv_path = csv_path 
        self.cards.clear()
        self.filtered_indices.clear()
        self.list.clear()

        self.image_dir = image_dir
        self.play.image_dir = image_dir

        with open(csv_path, encoding="utf-8") as f:
            self.cards = list(csv.DictReader(f))

        if self.cards:
            last_card = self.cards[-1]
            last_card["Commander_A"] = (
                last_card["name_ja"]
                if self.language == "ja"
                else last_card["name_en"]
            )
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
            # The "type" field in CSV is in a format like "Creature — Elf"
            # Extract only the main types
            type_line = c["type"]
            main_types_part = type_line.split(" — ")[0]

            # Split by spaces → ["Artifact", "Creature"]
            main_types = main_types_part.split(" ")

            # Filter condition
            if selected_type is not None and selected_type not in main_types:
                continue

            # Use UI language for the display label
            card_type_label = get_display_type(c["type"], self.language)
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

    def open_image_selector(self, item):
        idx = self.filtered_indices[self.list.row(item)]
        card = self.cards[idx]

        image_path = self.image_dir / card["card_file_front"]

        card_name = card["name_en"]
        dlg = ImageSelectDialog(card_name, image_path, self)

        if dlg.exec_():
            self.play._update() 






class ImageSelectDialog(QDialog):
    def __init__(self, card_name, image_path: Path, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Select Card Image")
        self.resize(820, 620)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        self.thumb_cache = {}
        self.request_id = 0

        self.card_name = card_name
        self.image_path = image_path

        # Performance optimization parameters
        self.page_size = 10
        self.current_page = 0
        self.all_results = []

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.thumb_size = QSize(120, 170)
        self.list.setIconSize(self.thumb_size)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setSpacing(10)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["10", "20", "50"])
        self.page_size_combo.setCurrentText("10")
        self.page_size_combo.currentIndexChanged.connect(self.change_page_size)

        # Language selection check
        self.chk_ja = QCheckBox("日本語")
        self.chk_en = QCheckBox("English")
        self.chk_other = QCheckBox("Others")
        self.chk_ja.setChecked(True)

        self.chk_ja.stateChanged.connect(self.update_search)
        self.chk_en.stateChanged.connect(self.update_search)
        self.chk_other.stateChanged.connect(self.update_search)

        # Page navigation
        self.prev_btn = QPushButton("◀ Prev")
        self.next_btn = QPushButton("Next ▶")
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn.clicked.connect(self.next_page)

        top = QHBoxLayout()
        top.addWidget(self.chk_ja)
        top.addWidget(self.chk_en)
        top.addWidget(self.chk_other)
        top.addSpacing(20)
        top.addWidget(QLabel("Items per page"))
        top.addWidget(self.page_size_combo)
        top.addStretch()

        nav = QHBoxLayout()
        nav.addStretch()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list)
        layout.addLayout(nav)

        self.list.itemClicked.connect(self.select_image)

        self.update_search()

    # ---------- Search (URLs only) ----------
    def update_search(self):
        self.current_page = 0

        use_other = self.chk_other.isChecked()

        # -----------------------------
        #  Determine language
        # -----------------------------
        if not use_other:
            langs = []
            if self.chk_ja.isChecked():
                langs.append("ja")
            if self.chk_en.isChecked():
                langs.append("en")

            if not langs:
                langs = ["ja", "en"]
        else:
            langs = ("ja", "en", "fr", "de", "it", "es", "pt", "ko", "ru", "zhs", "zht")

        # -----------------------------
        # Fetch from Scryfall (per printing)
        # -----------------------------
        raw_results = generator.search_card_images(
            self.card_name,
            languages=tuple(langs)
        )

        # -----------------------------
        # Flatten per face
        # -----------------------------
        faces = []

        for entry in raw_results:
            lang = entry.get("lang")

            # UI filter when "Others" is enabled
            if use_other:
                if lang == "ja" and not self.chk_ja.isChecked():
                    continue
                if lang == "en" and not self.chk_en.isChecked():
                    continue
                if lang not in ("ja", "en") and not self.chk_other.isChecked():
                    continue

            for face in entry.get("faces", []):
                faces.append({
                    "card_id": entry["card_id"],
                    "oracle_id": entry["oracle_id"],
                    "lang": lang,
                    "face_index": face["face_index"],
                    "face_name": face["name"],
                    "side": face["side"],
                    "image_normal": face["image_normal"],   # ★
                    "image_small": face.get("image_small"), # ★
                })



        self.all_results = faces
        self.update_page()

    def update_page(self):
        self.clear_list_safely()
        self.request_id += 1
        current_id = self.request_id

        start = self.current_page * self.page_size
        end = start + self.page_size

        for i, r in enumerate(self.all_results[start:end]):
            # Display name: card name + face + language
            title = f'{r["face_name"]} [{r["side"]}] ({r["lang"]})'
            item = QListWidgetItem(title)

            item.setSizeHint(QSize(
                self.thumb_size.width() + 20,
                self.thumb_size.height() + 40
            ))

            # Store per-face data as-is
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)

            thumb_url = r.get("image_small")

            if thumb_url:
                loader = ImageLoader(
                    i,
                    thumb_url,
                    self.thumb_size,
                    current_id
                )
                loader.signals.finished.connect(self.on_image_loaded)
                self.pool.start(loader)

        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(
            (self.current_page + 1) * self.page_size < len(self.all_results)
        )

 
    def on_image_loaded(self, req_id, index, img):
        if req_id != self.request_id:
            return  

        item = self.list.item(index)
        if item:
            item.setIcon(QIcon(QPixmap.fromImage(img)))



    def change_page_size(self):
        self.page_size = int(self.page_size_combo.currentText())
        self.current_page = 0
        self.update_page()

    def next_page(self):
        if (self.current_page + 1) * self.page_size < len(self.all_results):
            self.current_page += 1
            self.update_page()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_page()

    # ---------- Image selection ----------
    def select_image(self, item):
        face = item.data(Qt.UserRole)

        try:
            parent = self.parent()

            # Get the current card from the parent (MainWindow)
            idx = parent.filtered_indices[parent.list.row(parent.list.currentItem())]
            card = parent.cards[idx]

            front_path = parent.image_dir / card["card_file_front"]
            back_path = (
                parent.image_dir / card["card_file_back"]
                if card["card_file_back"]
                else None
            )

            # ---------- Selected face ----------
            data = requests.get(face["image_normal"], timeout=5).content

            if face["face_index"] == 0:
                front_path.write_bytes(data)
            else:
                if back_path:
                    back_path.write_bytes(data)

            # ---------- Update the opposite face as well ----------
            if back_path:
                for r in self.all_results:
                    if (
                        r["card_id"] == face["card_id"]
                        and r["lang"] == face["lang"]
                        and r["face_index"] != face["face_index"]
                    ):
                        other_data = requests.get(
                            r["image_normal"], timeout=5
                        ).content

                        if face["face_index"] == 0:
                            back_path.write_bytes(other_data)
                        else:
                            front_path.write_bytes(other_data)
                        break

            QMessageBox.information(
                self,
                "Done",
                "Both front and back card images have been updated."
            )
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "error", str(e))


    def fetch_image(self, url: str):
        try:
            r = requests.get(url, timeout=5)
            pix = QPixmap()
            pix.loadFromData(r.content)
            return pix
        except Exception:
            return None

    def clear_list_safely(self):
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        self.list.setUpdatesEnabled(True)

class ImageResult(QObject):
    finished = pyqtSignal(int, int, QImage)

class ImageLoader(QRunnable):
    def __init__(self, index, url, size, request_id):
        super().__init__()
        self.index = index
        self.url = url
        self.size = size
        self.request_id = request_id
        self.signals = ImageResult()

        self.session = requests.Session()

    def run(self):
        try:
            r = self.session.get(self.url, timeout=5)
            r.raise_for_status()

            img = QImage.fromData(r.content)
            if img.isNull():
                return

            img = img.scaled(
                self.size,
                Qt.KeepAspectRatio,
                Qt.FastTransformation
            )

            self.signals.finished.emit(self.request_id, self.index, img)


        except Exception:
            pass
        finally:
            self.session.close()



# ================= Entry =================

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support() 

    QApplication.setAttribute(Qt.AA_Use96Dpi, True)
    app = QApplication(sys.argv)
    ensure_emojis()
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
