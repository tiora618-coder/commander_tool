from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QGridLayout,
    QLineEdit, QComboBox, QPushButton, QMessageBox, QCompleter, QMenu
)
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer, QStringListModel, QPoint
from PyQt5.QtGui import QPixmap, QFont, QIcon
from pathlib import Path
import requests
import csv
import logging
from gui_language import UI_TEXT, TYPE_LABELS
import generator
from image_selector import ImageSelectDialog

class AddCardWorker(QThread):
    finished = pyqtSignal(dict) # row dict
    error = pyqtSignal(str)

    def __init__(self, card_name, out_dir, language):
        super().__init__()
        self.card_name = card_name
        self.out_dir = out_dir
        self.language = language

    def run(self):
        try:
            # We need a function in generator that can return a single row
            row = generator.create_card_row(self.card_name, self.out_dir, self.language)
            if row:
                self.finished.emit(row)
            else:
                self.error.emit(UI_TEXT[self.language]["card_not_found"])
        except Exception as e:
            self.error.emit(str(e))

class AutocompleteWorker(QThread):
    finished = pyqtSignal(list)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            results = generator.get_card_autocomplete(self.query)
            self.finished.emit(results)
        except:
            self.finished.emit([])

class MiniCardWidget(QWidget):
    right_clicked = pyqtSignal(QPoint)

    def __init__(self, img_path: Path, tool_tip="", scale_height=180, card_data=None, header_text=""):
        super().__init__()
        self.card_data = card_data
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if header_text:
            h_label = QLabel(header_text)
            h_label.setAlignment(Qt.AlignCenter)
            h_label.setStyleSheet("font-weight: bold; color: #ffaa00; font-size: 11px;")
            layout.addWidget(h_label)

        self.img_label = QLabel()
        pix = QPixmap(str(img_path))
        if not pix.isNull():
            self.img_label.setPixmap(pix.scaledToHeight(scale_height, Qt.SmoothTransformation))
        else:
            self.img_label.setText("N/A")
            self.img_label.setFixedSize(120, 180)
            self.img_label.setStyleSheet("background: #333; color: #555;")
        
        self.img_label.setAlignment(Qt.AlignCenter)
        if tool_tip:
            self.setToolTip(tool_tip)
        
        layout.addWidget(self.img_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.right_clicked.emit(event.globalPos())
        else:
            super().mousePressEvent(event)

class SectionWidget(QWidget):
    def __init__(self, title, cards, image_dir, lang="ja", col_count=6, scale_height=180, section_key="main", callback=None, card_labels=None):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)

        suffix = " 枚" if lang == "ja" else " cards"
        self.title_label = QLabel(f"{title} {len(cards)}{suffix}")
        font = self.title_label.font()
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setStyleSheet("color: #ffaa00; border-bottom: 1px solid #444; padding-bottom: 3px;")
        self.layout.addWidget(self.title_label)

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

            w = MiniCardWidget(img_path, tool_tip=name, scale_height=scale_height, card_data=meta, header_text=h_text)
            w.right_clicked.connect(callback)
            self.grid.addWidget(w, i // col_count, i % col_count)

class DeckBuildingWindow(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, cards, image_dir, lang="ja", csv_path=None, parent=None):
        super().__init__(parent)
        self.csv_path = Path(csv_path) if csv_path else None
        self.consideration_csv_path = self.csv_path.parent / f"{self.csv_path.stem}_consideration.csv" if self.csv_path else None
        
        self.setWindowTitle(UI_TEXT[lang]["deck_building"])
        self.resize(1100, 900)
        self.setStyleSheet("background: #111; color: white; font-family: 'Segoe UI', 'Meiryo UI', sans-serif;")

        self.cards = cards # Main Cards (reference from main window)
        self.consideration_cards = []
        self.image_dir = image_dir
        self.lang = lang

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

        self.load_considerations()
        self.build_sections()

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
        self.search_input.setStyleSheet("padding: 8px; background: #111; color: white; border: 1px solid #555; border-radius: 4px;")
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
        if not path: return
        fieldnames = [
            "card_file_front", "card_file_back", "name_front", "name_back",
            "name_ja", "name_en", "type_front", "type_back", "mana_cost",
            "text_front_ja", "text_front_en", "text_back_ja", "text_back_en",
            "Commander_A", "Commander_B", "Companion"
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL, extrasaction='ignore')
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
                lines.append(f"1 {get_export_name(c)}")
            for c in c_b:
                lines.append(f"1 {get_export_name(c)}")
            
            lines.append("") # Blank line
            
            # 2. Companion and Mainboard
            commander_list = c_a + c_b
            companions = [c for c in self.cards if bool(c.get("Companion"))]
            mainboard = [c for c in self.cards if c not in commander_list and c not in companions]
            
            for c in companions:
                lines.append(f"1 {get_export_name(c)}")
                
            for c in mainboard:
                lines.append(f"1 {get_export_name(c)}")
                
            lines.append("") # Blank line

            # 3. Considering
            for c in self.consideration_cards:
                lines.append(f"1 {get_export_name(c)}")
                
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

            QMessageBox.information(self, "Done", "Card images updated.")
            self.refresh_ui()

    def on_card_fetched(self, row):
        dest = self.dest_combo.currentData()
        row["Commander_A"] = ""
        row["Commander_B"] = ""
        row["Companion"] = ""
        
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

    def on_card_error(self, err_msg):
        QMessageBox.warning(self, "Error", err_msg)
        self.add_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText(UI_TEXT[self.lang]["search_card_placeholder"])

    def refresh_ui(self):
        # Clear content and rebuild
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.build_sections()

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
        
        mainboard = [c for c in self.cards if c not in commander_list and c not in companions]
        
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
            top_row_layout.addWidget(sw)
        
        if companions:
            sw = SectionWidget(UI_TEXT[self.lang]["companion"], companions, self.image_dir, self.lang, 
                               col_count=1, scale_height=240, section_key="main", callback=self.show_context_menu)
            top_row_layout.addWidget(sw)
        
        top_row_layout.addStretch()
        self.content_layout.addWidget(top_row)

        # 2. Mainboard Header
        total_main = len(creatures) + len(spells) + len(lands)
        suffix = " 枚" if self.lang == "ja" else " cards"
        mb_header = QLabel(f"{UI_TEXT[self.lang]['mainboard']} {total_main}{suffix}")
        font = mb_header.font()
        font.setPointSize(16)
        font.setBold(True)
        mb_header.setFont(font)
        mb_header.setStyleSheet("color: white; background: #222; padding: 10px; border-radius: 4px;")
        self.content_layout.addWidget(mb_header)

        # 3. Creatures
        if creatures:
            self.content_layout.addWidget(SectionWidget(UI_TEXT[self.lang]["creature"], creatures, self.image_dir, self.lang, 
                                                       col_count=7, section_key="main", callback=self.show_context_menu))

        # 4. Spells
        if spells:
            self.content_layout.addWidget(SectionWidget(UI_TEXT[self.lang]["spell"], spells, self.image_dir, self.lang, 
                                                       col_count=7, section_key="main", callback=self.show_context_menu))

        # 5. Lands
        if lands:
            self.content_layout.addWidget(SectionWidget(UI_TEXT[self.lang]["land"], lands, self.image_dir, self.lang, 
                                                       col_count=7, section_key="main", callback=self.show_context_menu))

        # 6. Considering Section
        if self.consideration_cards:
            self.content_layout.addWidget(SectionWidget(UI_TEXT[self.lang]["considering"], self.consideration_cards, self.image_dir, self.lang, 
                                                       col_count=7, section_key="consideration", callback=self.show_context_menu))

        self.content_layout.addStretch()
