from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QGridLayout,
    QLineEdit, QComboBox, QPushButton, QMessageBox, QCompleter, QMenu
)
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer, QStringListModel, QPoint, QRectF
from PyQt5.QtGui import QPixmap, QFont, QIcon, QPainter, QPainterPath, QColor
from pathlib import Path
import requests
import csv
import logging
from gui_language import UI_TEXT, TYPE_LABELS
import generator
from image_selector import ImageSelectDialog

class AddCardWorker(QThread):
    finished = pyqtSignal(list) # list of row dicts
    error = pyqtSignal(str)

    def __init__(self, card_name, out_dir, language):
        super().__init__()
        self.card_name = card_name
        self.out_dir = out_dir
        self.language = language

    def run(self):
        try:
            # create_card_row now returns a list [main_card, token1, token2, ...]
            rows = generator.create_card_row(self.card_name, self.out_dir, self.language)
            if rows:
                self.finished.emit(rows)
            else:
                self.error.emit(UI_TEXT[self.language]["card_not_found"])
        except Exception as e:
            self.error.emit(str(e))

class SyncTokensWorker(QThread):
    progress = pyqtSignal(int, int, str) # current, total, name
    finished = pyqtSignal(list) # all new token rows found
    error = pyqtSignal(str)

    def __init__(self, cards, image_dir, language):
        super().__init__()
        self.cards = cards
        self.image_dir = image_dir
        self.language = language

    def run(self):
        try:
            all_deck_tokens = []
            # Only scan non-token cards
            main_cards = [c for c in self.cards if str(c.get("is_token")) != "True"]
            total = len(main_cards)
            
            for i, card in enumerate(main_cards):
                # Use current language name if available, else fallback
                name = card.get("name_ja") if self.language == "ja" else card.get("name_en")
                if not name:
                    name = card.get("name_en") or card.get("name_ja")
                if not name: continue
                
                self.progress.emit(i+1, total, name)
                
                # Fetch fresh data from Scryfall to get all_parts/tokens
                # Do NOT pass csv row as card_data
                rows = generator.create_card_row(name, self.image_dir, self.language)
                
                for r in rows:
                    if str(r.get("is_token")) == "True":
                        # Deduplicate within the newly found list
                        if not generator.find_existing_card_in_list(r, all_deck_tokens):
                            all_deck_tokens.append(r)
                
                import time
                time.sleep(0.1) # Be nice to Scryfall
                
            self.finished.emit(all_deck_tokens)
        except Exception as e:
            self.error.emit(str(e))

class AutocompleteWorker(QThread):
    finished = pyqtSignal(list)

class RoundedImageLabel(QLabel):
    def __init__(self, radius=12, parent=None):
        super().__init__(parent)
        self.radius = radius
        self.pixmap_to_draw = None
        self.setAttribute(Qt.WA_TranslucentBackground)

    def setPixmap(self, pixmap):
        self.pixmap_to_draw = pixmap
        self.update()

    def paintEvent(self, event):
        if not self.pixmap_to_draw:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = QRectF(self.rect())
        
        # Clip to rounded rect
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        painter.setClipPath(path)

        # Draw pixmap scaled to label size
        painter.drawPixmap(self.rect(), self.pixmap_to_draw)

        # Draw border (without clipping)
        painter.setClipping(False)
        pen = QColor("#555")
        painter.setPen(pen)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self.radius, self.radius)

class HoverPreviewPopup(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        
        self.image_labels = [RoundedImageLabel(12), RoundedImageLabel(12)]
        for lbl in self.image_labels:
            lbl.hide()
            self.layout.addWidget(lbl)

        self.hide()

    def show_card(self, image_dir, card_meta, global_pos):
        card = card_meta.get("card", {})
        front_file = card.get("card_file_front")
        back_file = card.get("card_file_back")
        is_token = str(card.get("is_token")) == "True"

        pixmaps = []
        if front_file:
            path = image_dir / front_file
            if path.exists():
                pixmaps.append(QPixmap(str(path)))
        
        # Only show back for TDFCs if it actually has a file
        if back_file:
            path = image_dir / back_file
            if path.exists():
                pixmaps.append(QPixmap(str(path)))

        if not pixmaps:
            self.hide()
            return

        # Width: 488, Height: 680 (Standard Scryfall 'normal')
        # We scale them down slightly for the popup but keep it large
        disp_h = 500
        total_w = 0
        
        for i, lbl in enumerate(self.image_labels):
            if i < len(pixmaps):
                pix = pixmaps[i]
                aspect = pix.width() / pix.height()
                disp_w = int(aspect * disp_h)
                
                lbl.setPixmap(pix)
                lbl.setFixedSize(disp_w, disp_h)
                lbl.show()
                total_w += disp_w + (self.layout.spacing() if i > 0 else 0)
            else:
                lbl.hide()

        self.setFixedSize(total_w, disp_h)
        
        # Intelligent positioning: Try to place it to the right of the cursor
        # If it would go off-screen, place it to the left
        target_x = global_pos.x() + 20
        target_y = global_pos.y() - disp_h // 2
        
        # Bounds check
        screen = self.screen().availableGeometry()
        if target_x + self.width() > screen.right():
            target_x = global_pos.x() - self.width() - 20
        
        # Y bounds
        if target_y < screen.top(): target_y = screen.top() + 10
        if target_y + disp_h > screen.bottom(): target_y = screen.bottom() - disp_h - 10

        self.move(target_x, target_y)
        self.show()

class MiniCardWidget(QWidget):
    right_clicked = pyqtSignal(QPoint)
    count_changed = pyqtSignal(int)
    hover_entered = pyqtSignal(dict, QPoint) # meta, global_pos
    hover_left = pyqtSignal()

    def __init__(self, img_path: Path, tool_tip="", scale_height=180, card_data=None, header_text="", count=1):
        super().__init__()
        self.card_data = card_data
        self.scale_height = scale_height
        self.count = int(count)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if header_text:
            h_label = QLabel(header_text)
            h_label.setAlignment(Qt.AlignCenter)
            h_label.setStyleSheet("font-weight: bold; color: #ffaa00; font-size: 11px;")
            layout.addWidget(h_label)

        # High DPI scaling support:
        # Instead of scaling the pixmap down to a small size and losing data, 
        # we load the high-res image and tell Qt it's a 2x density (DPR 2.0) image.
        # This allows Windows scaling (e.g. 150%) to use the extra pixels for sharpness.
        self.pixmap = QPixmap(str(img_path))
        if not self.pixmap.isNull():
            # Scryfall 'normal' is roughly 488x680. 
            # By setting DPR=2.0, Qt treats it as a 244x340 logical item.
            self.pixmap.setDevicePixelRatio(2.0)
            
            # Calculate logical width based on fixed scale_height
            # (width / height) * scale_height
            orig_w = self.pixmap.width()
            orig_h = self.pixmap.height()
            aspect = orig_w / orig_h
            w = int(aspect * scale_height)
            h = scale_height
            
            self.card_rect = QRectF(0, 0, w, h)
            self.setFixedSize(w, h + (15 if header_text else 0))
        else:
            self.pixmap = None
            self.setFixedSize(120, scale_height + (15 if header_text else 0))
        
        if tool_tip:
            self.setToolTip(tool_tip)
        
        # Spacer for the card area since we draw it in paintEvent
        self.img_area = QWidget()
        self.img_area.setFixedSize(self.width(), scale_height)
        layout.addWidget(self.img_area)

        self.setMouseTracking(True)

        # Quantity Overlay (Bottom Right)
        self.qty_container = QWidget(self)
        self.qty_container.setStyleSheet("background-color: rgba(0, 0, 0, 180); border-top-left-radius: 4px;")
        qty_layout = QHBoxLayout(self.qty_container)
        qty_layout.setContentsMargins(4, 2, 4, 2)
        qty_layout.setSpacing(4)

        self.btn_minus = QPushButton("-")
        self.btn_minus.setFixedSize(18, 18)
        self.btn_minus.setStyleSheet("background: #555; border: none; font-weight: bold; padding: 0;")
        self.btn_minus.clicked.connect(self.decrement)
        
        self.qty_label = QLabel(str(self.count))
        self.qty_label.setStyleSheet("font-weight: bold; color: white; background: transparent; font-size: 13px;")
        
        self.btn_plus = QPushButton("+")
        self.btn_plus.setFixedSize(18, 18)
        self.btn_plus.setStyleSheet("background: #555; border: none; font-weight: bold; padding: 0;")
        self.btn_plus.clicked.connect(self.increment)

        qty_layout.addWidget(self.btn_minus)
        qty_layout.addWidget(self.qty_label)
        qty_layout.addWidget(self.btn_plus)

        # Positioning (Wait for layout to calculate height)
        QTimer.singleShot(0, self.position_qty_overlay)
        
        self.setAttribute(Qt.WA_TranslucentBackground)

    def position_qty_overlay(self):
        # Place it at bottom-right of the whole widget
        self.qty_container.adjustSize()
        self.qty_container.move(
            self.width() - self.qty_container.width(),
            self.height() - self.qty_container.height()
        )

    def increment(self):
        self.count += 1
        self.qty_label.setText(str(self.count))
        self.count_changed.emit(self.count)
        self.qty_container.adjustSize()
        self.position_qty_overlay()

    def decrement(self):
        if self.count > 0:
            self.count -= 1
            self.qty_label.setText(str(self.count))
            self.count_changed.emit(self.count)
            self.qty_container.adjustSize()
            self.position_qty_overlay()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Get the position of the image area relative to self
        y_offset = self.img_area.pos().y()
        rect = QRectF(0, y_offset, self.width(), self.scale_height)
        radius = 6.0

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        if self.pixmap:
            painter.drawPixmap(rect.toRect(), self.pixmap)
        else:
            painter.fillRect(rect, QColor("#333"))
            painter.setPen(QColor("#555"))
            painter.drawText(rect, Qt.AlignCenter, "N/A")

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.right_clicked.emit(event.globalPos())
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        if self.card_data:
            self.hover_entered.emit(self.card_data, self.mapToGlobal(self.rect().bottomRight()))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)

class SectionWidget(QWidget):
    hover_entered = pyqtSignal(dict, QPoint)
    hover_left = pyqtSignal()

    def __init__(self, title, cards, image_dir, lang="ja", col_count=6, scale_height=180, section_key="main", callback=None, card_labels=None):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)

        self.title_base = title
        self.cards_ref = cards
        self.lang = lang
        
        self.title_label = QLabel("")
        font = self.title_label.font()
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setStyleSheet("color: #ffaa00; border-bottom: 1px solid #444; padding-bottom: 3px;")
        self.layout.addWidget(self.title_label)
        self.update_title()

        self.grid_layout = QHBoxLayout()
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self.grid_layout.addLayout(self.grid)
        self.grid_layout.addStretch()
        self.layout.addLayout(self.grid_layout)

        for i, card in enumerate(cards):
            img_path = image_dir / card.get("card_file_front", "")
            name = card.get("name_ja") if lang == "ja" else card.get("name_en")
            # Store metadata in card_data for context menu
            meta = {"index": i, "section": section_key, "card": card}
            
            h_text = ""
            if card_labels and i < len(card_labels):
                h_text = card_labels[i]

            w = MiniCardWidget(
                img_path, 
                tool_tip=name, 
                scale_height=scale_height, 
                card_data=meta, 
                header_text=h_text,
                count=card.get("count", 1)
            )
            w.right_clicked.connect(callback)
            w.count_changed.connect(lambda val, c=card: self.on_count_changed(c, val))
            w.hover_entered.connect(self.hover_entered.emit)
            w.hover_left.connect(self.hover_left.emit)
            self.grid.addWidget(w, i // col_count, i % col_count)

    def update_title(self):
        total_qty = sum(int(c.get("count", 1)) for c in self.cards_ref)
        suffix = " 枚" if self.lang == "ja" else " cards"
        self.title_label.setText(f"{self.title_base} {total_qty}{suffix}")


    def on_count_changed(self, card_dict, new_val):
        card_dict["count"] = str(new_val)
        self.update_title()
        # Notify MainWindow (if it's the owner of self.cards)
        # We need DeckBuildingWindow to have a reference to MainWindow or emit a signal
        # DeckBuildingWindow actually has self.data_changed signal
        self.window().data_changed.emit()

class DeckBuildingWindow(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, cards, image_dir, lang="ja", csv_path=None, parent=None):
        super().__init__(parent)
        self.csv_path = Path(csv_path) if csv_path else None
        self.consideration_csv_path = self.csv_path.parent / f"{self.csv_path.stem}_consideration.csv" if self.csv_path else None
        
        self.setWindowTitle(UI_TEXT[lang]["deck_building"])
        self.resize(1100, 900)
        self.setStyleSheet("background: #1c1c1c; color: white; font-family: 'Segoe UI', 'Meiryo UI', sans-serif;")

        self.cards = cards # Main Cards (reference from main window)
        self.consideration_cards = []
        self.image_dir = image_dir
        self.lang = lang

        self.preview_popup = HoverPreviewPopup(self)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. Search Header (Fixed)
        self.setup_header()

        # 1.5 Autocomplete setup
        # 1.5 Autocomplete setup
        self.completer = QCompleter()
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer_model = QStringListModel()
        self.completer.setModel(self.completer_model)
        self.completer.activated.connect(self.on_completer_activated)
        self.search_input.setCompleter(self.completer)

        self.autocomplete_timer = QTimer()
        self.autocomplete_timer.setSingleShot(True)
        self.autocomplete_timer.timeout.connect(self.fetch_autocomplete)
        self.search_input.textChanged.connect(self.on_search_text_changed)

        # 2. Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        
        self.main_layout.addWidget(self.scroll)

        self.data_changed.connect(self.on_data_updated)

        self.load_considerations()
        self.build_sections()

    def on_data_updated(self):
        # Update the Mainboard total label (if it exists)
        if hasattr(self, "mb_header"):
            total_main = sum(int(c.get("count", 1)) for c in self.cards if not (c.get("Commander_A") or c.get("Commander_B") or c.get("Companion")))
            suffix = " 枚" if self.lang == "ja" else " cards"
            self.mb_header.setText(f"{UI_TEXT[self.lang]['mainboard']} {total_main}{suffix}")

        # MainWindow usually handles the actual saving, but we can do it here if we have context
        # In main.py: launch_deck_building connects this or similar
        # Let's ensure MainWindow's save_current_csv is called.
        parent = self.parent()
        if hasattr(parent, "save_current_csv"):
            parent.save_current_csv()

    def setup_header(self):
        # 1st row: Language and Export (formerly 2nd)
        row1 = QFrame()
        row1.setStyleSheet("background: #222; border-bottom: 1px solid #444;")
        r1_layout = QHBoxLayout(row1)
        r1_layout.setContentsMargins(15, 10, 15, 10)
        r1_layout.setSpacing(10)

        # Language selection
        self.lang_label = QLabel(UI_TEXT[self.lang]["language"])
        r1_layout.addWidget(self.lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("日本語", "ja")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(0 if self.lang == "ja" else 1)
        self.lang_combo.currentIndexChanged.connect(self.on_lang_dropdown_changed)
        self.lang_combo.setStyleSheet("padding: 6px; background: #333; color: white; border: 1px solid #555;")
        r1_layout.addWidget(self.lang_combo, 1)

        r1_layout.addStretch()

        # Export Button
        self.export_btn = QPushButton(UI_TEXT[self.lang]["export_txt"])
        self.export_btn.clicked.connect(self.export_to_txt)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 4px;
                border: 1px solid #777;
            }
            QPushButton:hover { background-color: #666; }
        """)
        r1_layout.addWidget(self.export_btn, 1)

        # Sync Tokens Button (Renamed to Generate Token List)
        self.sync_btn = QPushButton(UI_TEXT[self.lang]["generate_token_list"])
        self.sync_btn.clicked.connect(self.on_sync_tokens_clicked)
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #ccc;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 4px;
                border: 1px solid #666;
            }
            QPushButton:hover { background-color: #555; color: white; }
        """)
        r1_layout.addWidget(self.sync_btn, 1)

        self.main_layout.addWidget(row1)

        # 2nd row: Search and Add (formerly 1st)
        row2 = QFrame()
        row2.setStyleSheet("background: #222; border-bottom: 1px solid #444;")
        r2_layout = QHBoxLayout(row2)
        r2_layout.setContentsMargins(15, 10, 15, 10)
        r2_layout.setSpacing(10)

        # Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])
        self.search_input.setStyleSheet("padding: 8px; background: #252525; color: white; border: 1px solid #555; border-radius: 4px;")
        self.search_input.returnPressed.connect(self.on_add_clicked)
        r2_layout.addWidget(self.search_input, 4)

        # Destination dropdown
        self.dest_label = QLabel(UI_TEXT[self.lang]["destination"])
        r2_layout.addWidget(self.dest_label)
        self.dest_combo = QComboBox()
        self.dest_combo.addItem(UI_TEXT[self.lang]["mainboard"], "main")
        self.dest_combo.addItem(UI_TEXT[self.lang]["considering"], "consideration")
        self.dest_combo.setStyleSheet("padding: 6px; background: #333; color: white; border: 1px solid #555;")
        r2_layout.addWidget(self.dest_combo, 2)

        # Add button
        self.add_btn = QPushButton(UI_TEXT[self.lang]["add"])
        self.add_btn.clicked.connect(self.on_add_clicked)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d7;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0086f1; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        r2_layout.addWidget(self.add_btn, 1)

        self.main_layout.addWidget(row2)

    def load_considerations(self):
        if not self.consideration_csv_path or not self.consideration_csv_path.exists():
            return
        try:
            with open(self.consideration_csv_path, encoding="utf-8") as f:
                self.consideration_cards = list(csv.DictReader(f))
        except Exception as e:
            logging.error(f"Error loading consideration CSV: {e}")

    def save_csvs(self):
        # We need to save BOTH CSVs when changes happen
        # Actually, MainBoard cards are owned by MainWindow, but we can save them here too 
        # as we have the reference and csv_path.
        
        # Save Main
        self.save_one_csv(self.csv_path, self.cards)
        # Save Consideration
        self.save_one_csv(self.consideration_csv_path, self.consideration_cards)
        
        self.data_changed.emit()

    def save_one_csv(self, path, card_list):
        if not path or not card_list: return
        
        # Sort cards before saving
        from main import sort_cards
        card_list[:] = sort_cards(card_list)

        # 1. Gather all keys from current cards
        all_card_keys = set()
        for c in card_list:
            all_card_keys.update(c.keys())

        # 2. Get existing fieldnames to maintain order if possible
        fieldnames = []
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
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

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=final_fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(card_list)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save CSV {path.name}:\n{e}")

    def on_add_clicked(self):
        name = self.search_input.text().strip()
        if not name: return

        self.autocomplete_timer.stop() # Stop any pending autocomplete
        self.add_btn.setEnabled(False)
        self.search_input.setEnabled(False)
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_adding"])

        self.worker = AddCardWorker(name, self.image_dir, self.lang)
        self.worker.finished.connect(self.on_card_fetched)
        self.worker.error.connect(self.on_card_error)
        self.worker.start()

    def on_search_text_changed(self, text):
        if len(text) < 2:
            self.completer_model.setStringList([])
            return
        self.autocomplete_timer.start(200) # 200ms debounce

    def fetch_autocomplete(self):
        query = self.search_input.text().strip()
        if not query: return
        self.auto_worker = AutocompleteWorker(query)
        self.auto_worker.finished.connect(self.on_autocomplete_finished)
        self.auto_worker.start()

    def on_completer_activated(self, text):
        """Automatically called when a user selects an item from the autocomplete list."""
        self.search_input.setText(text)
        self.on_add_clicked()

    def on_autocomplete_finished(self, results):
        if not results:
            self.completer.popup().hide()
            return
            
        self.completer_model.setStringList(results)
        # Re-trigger the completer to show the updated list
        self.completer.complete()

    def show_context_menu(self, pos):
        widget = self.sender()
        if not widget or not widget.card_data: return
        
        meta = widget.card_data
        section = meta["section"]
        card = meta["card"]

        menu = QMenu(self)
        
        # Commmon: Image Selector
        act_img = menu.addAction(UI_TEXT[self.lang]["select_image"])
        act_img.triggered.connect(lambda: self.open_image_selector(card))
        
        # Multiple Illustrations for Basic Lands
        if "Basic Land" in card.get("type_front", ""):
            act_add_ill = menu.addAction(UI_TEXT[self.lang]["add_different_illustration"])
            act_add_ill.triggered.connect(lambda: self.open_image_selector_for_new_illustration(card))
        
        if section == "main":
            menu.addSeparator()
            
            # Commander A
            label_a = UI_TEXT[self.lang]["unset_commander_a"] if card.get("Commander_A") else UI_TEXT[self.lang]["set_commander_a"]
            act_a = menu.addAction(label_a)
            act_a.triggered.connect(lambda: self.set_role(card, "Commander_A"))
            
            # Commander B
            label_b = UI_TEXT[self.lang]["unset_commander_b"] if card.get("Commander_B") else UI_TEXT[self.lang]["set_commander_b"]
            act_b = menu.addAction(label_b)
            act_b.triggered.connect(lambda: self.set_role(card, "Commander_B"))
            
            # Companion
            label_comp = UI_TEXT[self.lang]["unset_companion"] if card.get("Companion") else UI_TEXT[self.lang]["set_companion"]
            act_comp = menu.addAction(label_comp)
            act_comp.triggered.connect(lambda: self.set_role(card, "Companion"))
            
            menu.addSeparator()
            act_move = menu.addAction(UI_TEXT[self.lang]["move_to_considering"])
            act_move.triggered.connect(lambda: self.move_card(card, "main"))
        else:
            menu.addSeparator()
            act_move = menu.addAction(UI_TEXT[self.lang]["move_to_mainboard"])
            act_move.triggered.connect(lambda: self.move_card(card, "consideration"))
        
        menu.addSeparator()
        act_del = menu.addAction(UI_TEXT[self.lang]["delete_card"])
        act_del.triggered.connect(lambda: self.delete_card(card, section))
        
        menu.exec_(pos)

    def set_role(self, card, role):
        # Clear role for other cards first if it's singleton role? 
        # Actually Commander A/B and Companion can be multiple in theory (different cards).
        # But usually you want to togggle.
        
        if card[role]: # Already set? Clear it
            card[role] = ""
        else:
            card[role] = "1"
        
        self.save_csvs()
        self.refresh_ui()

    def move_card(self, card, from_section):
        # Clear roles when moving
        card["Commander_A"] = ""
        card["Commander_B"] = ""
        card["Companion"] = ""

        if from_section == "main":
            if card in self.cards:
                self.cards.remove(card)
                self.consideration_cards.append(card)
        else:
            if card in self.consideration_cards:
                self.consideration_cards.remove(card)
                self.cards.append(card)
        
        self.save_csvs()
        self.refresh_ui()

    def on_lang_dropdown_changed(self):
        new_lang = self.lang_combo.currentData()
        self.lang = new_lang
        # Update UI texts
        self.setWindowTitle(UI_TEXT[self.lang]["deck_building"])
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])
        self.add_btn.setText(UI_TEXT[self.lang]["add"])
        self.dest_label.setText(UI_TEXT[self.lang]["destination"])
        self.lang_label.setText(UI_TEXT[self.lang]["language"])
        # Update destination combo labels? Not easy to update existing items without iteration
        self.dest_combo.setItemText(0, UI_TEXT[self.lang]["mainboard"])
        self.dest_combo.setItemText(1, UI_TEXT[self.lang]["considering"])
        self.export_btn.setText(UI_TEXT[self.lang]["export_txt"])
        
        self.refresh_ui()

    def export_to_txt(self):
        from PyQt5.QtWidgets import QFileDialog
        
        default_name = f"{self.csv_path.stem}_export.txt" if self.csv_path else "deck_export.txt"
        save_path, _ = QFileDialog.getSaveFileName(self, "Export Deck", str(self.csv_path.parent / default_name), "Text files (*.txt)")
        
        if not save_path:
            return
            
        try:
            def get_export_name(card):
                full_name = card.get("name_en") or card.get("name_ja", "Unknown")
                return full_name.split(" // ")[0]

            lines = []
            
            # 1. Commanders
            c_a = [c for c in self.cards if bool(c.get("Commander_A"))]
            c_b = [c for c in self.cards if bool(c.get("Commander_B"))]
            for c in c_a:
                lines.append(f"{c.get('count', 1)} {get_export_name(c)}")
            for c in c_b:
                lines.append(f"{c.get('count', 1)} {get_export_name(c)}")
            
            lines.append("") # Blank line
            
            # 2. Companion and Mainboard
            commander_list = c_a + c_b
            companions = [c for c in self.cards if bool(c.get("Companion"))]
            mainboard = [c for c in self.cards if c not in commander_list and c not in companions]
            
            for c in companions:
                lines.append(f"{c.get('count', 1)} {get_export_name(c)}")
                
            for c in mainboard:
                lines.append(f"{c.get('count', 1)} {get_export_name(c)}")
                
            lines.append("") # Blank line

            # 3. Considering
            for c in self.consideration_cards:
                lines.append(f"{c.get('count', 1)} {get_export_name(c)}")
                
            # Cleanup trailing blank lines if sections were empty
            while lines and lines[-1] == "":
                lines.pop()

            with open(save_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                
            QMessageBox.information(self, "Export", f"Deck exported to {Path(save_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export deck:\n{e}")

    def delete_card(self, card, from_section):
        ret = QMessageBox.question(self, UI_TEXT[self.lang]["delete_card"], UI_TEXT[self.lang]["confirm_delete"],
                                   QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
            
        if from_section == "main":
            if card in self.cards:
                self.cards.remove(card)
        else:
            if card in self.consideration_cards:
                self.consideration_cards.remove(card)
        
        self.save_csvs()
        self.refresh_ui()

    def open_image_selector(self, card):
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

            # Update opposite face if double-faced
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

            self.save_csvs()
            QMessageBox.information(self, "Done", "Card images updated.")
            self.refresh_ui()

    def open_image_selector_for_new_illustration(self, card):
        image_dir = self.image_dir
        # Open selector
        from image_selector import ImageSelectDialog
        image_path = image_dir / card["card_file_front"]
        card_name = card["name_en"]
        is_token = (card.get("is_token") == "True")

        dlg = ImageSelectDialog(card_name, image_path, self, is_token=is_token)
        if dlg.exec_():
            face = dlg.selected_face
            
            # 1. Generate unique filename
            base_name = card["card_file_front"]
            stem = Path(base_name).stem
            ext = Path(base_name).suffix
            
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
                import requests
                data = requests.get(face["image_normal"], timeout=5).content
                new_path.write_bytes(data)
                
                # 3. Create new card entry
                new_card = card.copy()
                new_card["card_file_front"] = new_filename
                new_card["count"] = "1"
                
                # 4. Update counts
                # Decrement original count by 1 (if > 1)
                curr_count = int(card.get("count", 1))
                if curr_count > 1:
                    card["count"] = str(curr_count - 1)
                
                # Find which list it belongs to
                if card in self.cards:
                    self.cards.append(new_card)
                elif card in self.consideration_cards:
                    self.consideration_cards.append(new_card)
                else:
                    # Fallback to mainboard
                    self.cards.append(new_card)
                
                # 5. Save and Refresh
                self.save_csvs()
                self.refresh_ui()
                QMessageBox.information(self, "Done", f"Added new illustration: {new_filename}")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to download image: {e}")


    def on_card_fetched(self, rows):
        if not isinstance(rows, list):
            rows = [rows]

        dest = self.dest_combo.currentData()
        for row in rows:
            row["Commander_A"] = ""
            row["Commander_B"] = ""
            row["Companion"] = ""
            
            is_token = (row.get("is_token") == "True")
            existing = generator.find_existing_card_in_list(row, self.cards + self.consideration_cards)

            if existing:
                if not is_token:
                    # Increment count for normal cards
                    curr = int(existing.get("count", 1))
                    existing["count"] = str(curr + 1)
                # For tokens, we just skip adding it again
            else:
                if is_token:
                    if dest == "main":
                        self.cards.append(row)
                    # Skip tokens if added to consideration
                else:
                    if dest == "main":
                        self.cards.append(row)
                    else:
                        self.consideration_cards.append(row)
        
        self.save_csvs()
        self.refresh_ui()

        self.add_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.search_input.setText("")
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])

    def on_sync_tokens_clicked(self):
        self.sync_btn.setEnabled(False)
        self.search_input.setEnabled(False)
        self.search_input.setPlaceholderText("Scanning tokens...")
        
        self.sync_worker = SyncTokensWorker(self.cards, self.image_dir, self.lang)
        self.sync_worker.progress.connect(self.update_sync_progress)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.error.connect(lambda msg: QMessageBox.warning(self, "Error", msg))
        self.sync_worker.start()

    def update_sync_progress(self, current, total, name):
        self.search_input.setPlaceholderText(f"Scanning ({current}/{total}): {name}")

    def on_sync_finished(self, relevant_tokens):
        self.sync_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])
        
        # 1. Identify Existing Tokens
        existing_tokens = [c for c in self.cards if str(c.get("is_token")) == "True"]
        other_cards = [c for c in self.cards if str(c.get("is_token")) != "True"]
        
        tokens_to_keep = []
        tokens_to_remove = []
        
        # 2. Match existing tokens against relevant ones
        for et in existing_tokens:
            if generator.find_existing_card_in_list(et, relevant_tokens):
                tokens_to_keep.append(et)
            else:
                tokens_to_remove.append(et)
        
        # 3. Identify new tokens to add
        tokens_to_add = []
        for rt in relevant_tokens:
            if not generator.find_existing_card_in_list(rt, existing_tokens):
                rt["Commander_A"] = ""
                rt["Commander_B"] = ""
                rt["Companion"] = ""
                tokens_to_add.append(rt)

        # 4. Perform Cleanup (Delete JPGs)
        import os
        for rt_meta in tokens_to_remove:
            for field in ["card_file_front", "card_file_back"]:
                fname = rt_meta.get(field)
                if fname:
                    fpath = self.image_dir / fname
                    if fpath.exists():
                        try:
                            os.remove(fpath)
                            logging.info(f"Deleted orphaned token image: {fname}")
                        except Exception as e:
                            logging.error(f"Failed to delete {fname}: {e}")

        # 5. Update state
        self.cards = other_cards + tokens_to_keep + tokens_to_add
        
        self.save_csvs()
        self.refresh_ui()
        
        summary = f"Sync complete.\n- Added: {len(tokens_to_add)}\n- Kept: {len(tokens_to_keep)}\n- Removed: {len(tokens_to_remove)}"
        QMessageBox.information(self, "Sync", summary)

    def on_card_error(self, err_msg):
        QMessageBox.warning(self, "Error", err_msg)
        self.add_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])

    def refresh_ui(self):
        # 1. Update static UI elements
        self.retranslate_ui()
        
        # 2. Clear content and rebuild
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.build_sections()

    def retranslate_ui(self):
        """Update all static UI elements with the current language."""
        self.setWindowTitle(UI_TEXT[self.lang]["deck_building"])
        
        # Header Row 1
        self.export_btn.setText(UI_TEXT[self.lang]["export_txt"])
        self.sync_btn.setText(UI_TEXT[self.lang]["generate_token_list"])
        
        # Header Row 2
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])
        self.dest_label.setText(UI_TEXT[self.lang]["destination"])
        self.dest_combo.setItemText(0, UI_TEXT[self.lang]["mainboard"])
        self.dest_combo.setItemText(1, UI_TEXT[self.lang]["considering"])
        self.add_btn.setText(UI_TEXT[self.lang]["add"])

    def on_hover_preview(self, card_meta, global_pos):
        self.preview_popup.show_card(self.image_dir, card_meta, global_pos)

    def on_hover_hide(self):
        self.preview_popup.hide()

    def build_sections(self):
        # Categorization
        c_a = [c for c in self.cards if bool(c.get("Commander_A"))]
        c_b = [c for c in self.cards if bool(c.get("Commander_B"))]
        
        commander_list = []
        commander_labels = []
        if c_a:
            commander_list.extend(c_a)
            commander_labels.extend([UI_TEXT[self.lang]["label_commander_a"]] * len(c_a))
        if c_b:
            commander_list.extend(c_b)
            commander_labels.extend([UI_TEXT[self.lang]["label_commander_b"]] * len(c_b))

        companions = [c for c in self.cards if bool(c.get("Companion"))]
        
        # Filter out tokens from mainboard, commanders, and companions
        all_special_cards = commander_list + companions
        mainboard_and_tokens = [c for c in self.cards if c not in all_special_cards]
        
        tokens = [c for c in mainboard_and_tokens if c.get("is_token") == "True"]
        mainboard = [c for c in mainboard_and_tokens if c.get("is_token") != "True"]

        # Sort mainboard
        creatures = []
        lands = []
        spells = []

        for c in mainboard:
            # CSV now uses 'type_front' and 'type_back'
            tl = c.get("type_front", "")
            if "Land" in tl:
                lands.append(c)
            elif "Creature" in tl:
                creatures.append(c)
            else:
                spells.append(c)

        # 1. Top Row: Commanders and Companions
        top_row = QFrame()
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        
        if commander_list:
            sw = SectionWidget(UI_TEXT[self.lang]["commander"], commander_list, self.image_dir, self.lang, 
                               col_count=2, scale_height=240, section_key="main", callback=self.show_context_menu,
                               card_labels=commander_labels)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            top_row_layout.addWidget(sw)
        
        if companions:
            sw = SectionWidget(UI_TEXT[self.lang]["companion"], companions, self.image_dir, self.lang, 
                               col_count=1, scale_height=240, section_key="main", callback=self.show_context_menu)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            top_row_layout.addWidget(sw)
        
        top_row_layout.addStretch()
        self.content_layout.addWidget(top_row)

        # 2. Mainboard Header
        total_main = sum(int(c.get("count", 1)) for c in creatures + spells + lands)
        suffix = " 枚" if self.lang == "ja" else " cards"
        self.mb_header = QLabel(f"{UI_TEXT[self.lang]['mainboard']} {total_main}{suffix}")
        font = self.mb_header.font()
        font.setPointSize(16)
        font.setBold(True)
        self.mb_header.setFont(font)
        self.mb_header.setStyleSheet("color: white; background: #222; padding: 10px; border-radius: 4px;")
        self.content_layout.addWidget(self.mb_header)

        # 3. Creatures
        if creatures:
            sw = SectionWidget(UI_TEXT[self.lang]["creature"], creatures, self.image_dir, self.lang, 
                                col_count=7, section_key="main", callback=self.show_context_menu)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            self.content_layout.addWidget(sw)

        # 4. Spells
        if spells:
            sw = SectionWidget(UI_TEXT[self.lang]["spell"], spells, self.image_dir, self.lang, 
                                col_count=7, section_key="main", callback=self.show_context_menu)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            self.content_layout.addWidget(sw)

        # 5. Lands
        if lands:
            sw = SectionWidget(UI_TEXT[self.lang]["land"], lands, self.image_dir, self.lang, 
                                col_count=7, section_key="main", callback=self.show_context_menu)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            self.content_layout.addWidget(sw)

        # 6. Considering Section
        if self.consideration_cards:
            sw = SectionWidget(UI_TEXT[self.lang]["considering"], self.consideration_cards, self.image_dir, self.lang, 
                                col_count=7, section_key="consideration", callback=self.show_context_menu)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            self.content_layout.addWidget(sw)

        # 7. Tokens Section
        if tokens:
            sw = SectionWidget(UI_TEXT[self.lang]["tokens"], tokens, self.image_dir, self.lang, 
                                col_count=7, section_key="main", callback=self.show_context_menu)
            sw.hover_entered.connect(self.on_hover_preview)
            sw.hover_left.connect(self.on_hover_hide)
            self.content_layout.addWidget(sw)

        self.content_layout.addStretch()
