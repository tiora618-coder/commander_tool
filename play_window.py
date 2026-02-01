from gui_language import UI_TEXT, TYPE_LABELS
from config import APP_VERSION, EMOJI_DIR, UI_FONT_SIZE
from common_func import strip_ruby, mana_symbol_to_filename, app_dir
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QSplitter, QSizePolicy, QFrame, QScrollArea
)
from PyQt5.QtCore import Qt, QPoint, QUrl
from PyQt5.QtGui import (
    QTextDocument, QPixmap, QFont    
)
from PyQt5.QtCore import pyqtSignal
import re

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

        # Get the inner content height
        inner_height = self.counter_popup.inner.sizeHint().height()

        # Calculate remaining space in the window
        window_height = self.height()
        flip_btn_height = self.flip_btn.height()
        counter_btn_height = self.counter_btn.height()
        counters_height = self.player.height()

        available_height = window_height - flip_btn_height - counter_btn_height - counters_height - 16  # add a little margin

        # Set the popup height
        # It will be the smaller of the content height or the available window space
        popup_height = min(inner_height, available_height)
        self.counter_popup.setFixedHeight(popup_height)
        self.counter_popup.setFixedWidth(self.width())

        # Get the global position of the counter button and map it to the window
        btn_pos = self.counter_btn.mapToGlobal(QPoint(0, 0))
        win_pos = self.mapFromGlobal(btn_pos)

        x = 0  # Align the popup to the left of PlayWindow
        y = win_pos.y() - self.counter_popup.height() - 8  # Position it above the button

        # Move and show the popup
        self.counter_popup.move(x, y)
        self.counter_popup.show()
        self.counter_popup.raise_()

        self.counter_popup.resize_icon_all()


    
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
                background-color: #000000;
                border: none;
            }
        """)



    def build_ui(self):
        # --- Create scroll container only once ---
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.inner = QWidget()
        scroll.setWidget(self.inner)

        # Store the inner layout to modify later
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(4, 4, 4, 4)
        self.inner_layout.setSpacing(6)

        # ---- extra counters ----
        self.build_extra_counters(self.inner_layout)

        # ---- title ----
        self.title_label = QLabel()
        self.title_label.setFont(QFont("", 16, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  
        self.title_label.setWordWrap(True)  
        self.title_label.setContentsMargins(4, 4, 4, 4)  
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.title_label.setMinimumHeight(50)  
        self.inner_layout.addWidget(self.title_label)


        # ---- commander rows ----
        self.build_commander_rows()

        # ---- final stretch ----
        self.inner_layout.addStretch()

        # Add scroll to outer layout
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

        self.retranslate_ui(self.lang)

    def build_commander_rows(self):
        """Build commander rows inside inner_layout."""
        self.rows = []

        my_player = self.play.player.value

        for p in range(1, 5):
            if p == my_player:
                continue
            row = PlayerCommanderRow(p, self.play, self.lang)
            self.rows.append(row)
            self.inner_layout.addWidget(row)

    def build_extra_counters(self, parent_layout):
        base = app_dir() / "icons"

        # Desired display order (top to bottom)
        rows = [
            ["poison", "exp"],
            ["rad", "energy"],
            ["ticket"],
        ]

        # Create widgets for each counter
        self.extra_counters = {}
        for row in rows:
            for k in row:
                if k not in self.extra_counters:
                    self.extra_counters[k] = IconCounterWidget(base / f"{k}.png")

        frame = QFrame()
        frame.setStyleSheet("background:#1a1a1a; border-radius:6px;")

        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(4)

        # --- Push content to the bottom ---
        vbox.addStretch()

        # --- Build rows from bottom to top ---
        for row in reversed(rows):
            h = QHBoxLayout()
            h.setSpacing(6)

            if len(row) == 1:
                # Single item row → left aligned
                h.addWidget(self.extra_counters[row[0]])
                h.addStretch()  # Add space on the right
            else:
                # Two-item row → place side-by-side
                for k in row:
                    h.addWidget(self.extra_counters[k])

            vbox.addLayout(h)

        parent_layout.addWidget(frame)

    def rebuild_rows(self):
        """Rebuild commander rows correctly inside inner_layout."""
        # Remove old rows from layout
        for row in self.rows:
            row.setParent(None)

        # Rebuild
        self.build_commander_rows()

        self.retranslate_ui(self.lang)
  
    def retranslate_ui(self, lang):
        self.lang = lang
        self.title_label.setText(
            UI_TEXT[lang]["commander_damage"]
        )

        for row in self.rows:
            row.retranslate_ui(lang)
        
    def resize_icon_all(self):
        """Force all extra counters to resize their icons."""
        for w in self.extra_counters.values():
            w.resize_icon()

    def showEvent(self, event):
        super().showEvent(event)
        for w in self.extra_counters.values():
            w.resize_icon()

    def refresh(self):
        for row in self.rows:
            row.sync_from_model()
   

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
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.title_label.setMinimumHeight(60)  
        self.title_label.setContentsMargins(4, 4, 4, 4)  
        self.title_label.setFont(QFont("", 14, QFont.Bold))  

        # --- Damage counters ---
        self.ca = CommanderDamageCounter("", self.play.commander_damage[player_no]["A"])
        self.cb = CommanderDamageCounter("", self.play.commander_damage[player_no]["B"])

        self.ca.valueChanged.connect(lambda d: self.on_damage_changed("A", d))
        self.cb.valueChanged.connect(lambda d: self.on_damage_changed("B", d))

        # --- Horizontal row ---
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(4)
        row.addWidget(self.ca)
        row.addWidget(self.cb)

        # --- Main layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self.title_label)
        layout.addLayout(row)

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
        self.title_label.setMinimumHeight(50)
        self.ca.title_label.setText(" A :")
        self.cb.title_label.setText(" B :")
        self.ca.title_label.setFont(QFont("", 14, QFont.Bold))  
        self.cb.title_label.setFont(QFont("", 14, QFont.Bold))  
    
    def sync_from_model(self):
        a = self.play.commander_damage[self.player_no]["A"]
        b = self.play.commander_damage[self.player_no]["B"]

        self.ca.value = a
        self.ca.value_label.setText(str(a))

        self.cb.value = b
        self.cb.value_label.setText(str(b))

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


class IconCounterWidget(QWidget):
    def __init__(self, icon_path: Path, initial=0):
        super().__init__()
        self.value = initial
        self.icon_path = icon_path

        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignCenter)

        self.value_label = QLabel(str(self.value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(QFont("", 20, QFont.Bold))
        self.value_label.setFixedWidth(40)

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

        self.resize_icon()

    def resize_icon(self):
        """Resize the icon dynamically based on widget width"""
        if not self.icon_path.exists():
            return

        pix = QPixmap(str(self.icon_path))
        w = max(120, int(self.width() * 0.25))
        pix = pix.scaled(
            w, w,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.icon.setPixmap(pix)
        self.icon.setFixedSize(w, w)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_icon()

    def change(self, delta):
        self.value = max(0, self.value + delta)
        self.value_label.setText(str(self.value))

    def reset(self):
        self.value = 0
        self.value_label.setText("0")


class CommanderDamageCounter(QWidget):
    valueChanged = pyqtSignal(int)  # delta (+1 / -1)

    def __init__(self, label_text: str, initial=0):
        super().__init__()
        self.value = initial
        self.setStyleSheet("""
            QWidget {
                background-color: #000;
            }
            QLabel {
                background-color: #000;
                color: white;
            }
            QPushButton {
                background-color: #333;
                color: white;
            }
        """)
        self.base_font_family = ""
        self.base_font_weight = QFont.Bold
        self.max_font_size = 20
        self.min_font_size = 2

        self.title_label = QLabel(label_text)
        self.title_label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.title_label.setMinimumHeight(50) 

        self.value_label = QLabel(str(self.value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(QFont("", 18, QFont.Bold))
        self.value_label.setMinimumWidth(40)

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
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addLayout(btns)
        self.setMinimumHeight(50)


    def change(self, delta: int):
        self.value += delta
        if self.value < 0:
            self.value = 0
            return

        self.value_label.setText(str(self.value))
        self.valueChanged.emit(delta)
 
