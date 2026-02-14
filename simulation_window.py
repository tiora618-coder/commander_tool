# simulation_window.py
import random
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QMessageBox, QInputDialog, QDialog
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QPoint, QEasingCurve, QTimer
from PyQt5.QtGui import QPixmap
from star_rating_widget import StarRatingWidget

from card_widget import CardWidget
from logger import append_mulligan_log
from gui_language import UI_TEXT, LANG_EN, LANG_JA


class SimulationWindow(QWidget):
    def __init__(self, deck, deck_name, language, csv_path, parent=None, initial_run_count=0):
        super().__init__()
        self.csv_path = Path(csv_path) 

        self.parent_window = parent  # reference to StartWindow
        for card in deck:
            print(card)  # これを追加

        self.initial_library = [
            card for card in deck
            if not (card.get("Commander_A") or card.get("Commander_B") or card.get("Companion"))
        ]
        self.deck = list(self.initial_library)
        self.animations = []
        self.deck_name = deck_name
        self.language = language

        # Dark mode stylesheet (applies to this window and children)
        self.setStyleSheet("""
            QWidget { background: #1e1e1e; color: #eeeeee; }
            QLabel { color: #eeeeee; }
            QPushButton { color: #ffffff; }
        """)

        # Hand & mulligan state
        self.current_hand = []
        self.mulligan_count = 0
        self.return_required = 0
        self.return_selected = []
        self.exiled_cards = [] 
        self.run_count = initial_run_count  # Initialize with passed value

        self.setWindowTitle("Mulligan Simulation")

        # ---------- State label ----------
        self.state_label = QLabel()
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                border: 2px solid #444444;
                border-radius: 12px;
                padding: 8px;
                background-color: rgba(40, 40, 40, 220);
                color: #ffffff;
            }
        """)

        # ---------- Runs counter (top-left) ----------
        self.runs_label = QLabel(f"Runs: {self.run_count}")
        self.runs_label.setStyleSheet("""
            QLabel {
                font-size: 32px;
                font-weight: bold;
                color: #ffffff;
            }
        """)

        # ---------- Card container ----------
        self.card_container = QWidget(self)
        self.card_container.setMinimumHeight(350)
        self.card_container.setStyleSheet("background-color: rgba(255,255,255,0.02);")

        # ---------- Buttons ----------
        self.btn_mulligan = QPushButton(UI_TEXT[self.language]["mulligan"])
        self.btn_keep = QPushButton(UI_TEXT[self.language]["keep"])
        self.btn_exit = QPushButton(UI_TEXT[self.language].get("exit", "Exit"))

        self.btn_mulligan.clicked.connect(self.do_mulligan)
        self.btn_keep.clicked.connect(self.do_keep)
        self.btn_exit.clicked.connect(self.close)  # close window

        # Button styles (glossy)
        self.btn_keep.setStyleSheet("""
            QPushButton {
                background-color: #ff9f43;
                border-radius: 12px;
                padding: 14px 24px;
                font-size: 22px;
                font-weight: bold;
                color: white;
                border: 2px solid #d87f1c;
            }
            QPushButton:hover {
                background-color: #ffb76b;
            }
            QPushButton:pressed {
                background-color: #e68a2e;
            }
        """)

        self.btn_mulligan.setStyleSheet("""
            QPushButton {
                background-color: #7bed9f;
                border-radius: 12px;
                padding: 14px 24px;
                font-size: 22px;
                font-weight: bold;
                color: #0a3d0a;
                border: 2px solid #4cd137;
            }
            QPushButton:hover {
                background-color: #a8ffbe;
            }
            QPushButton:pressed {
                background-color: #63d471;
            }
        """)

        self.btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #cccccc;
                border-radius: 10px;
                padding: 10px 18px;
                font-size: 18px;
                font-weight: bold;
                color: black;
            }
            QPushButton:hover {
                background-color: #e6e6e6;
            }
            QPushButton:pressed {
                background-color: #b3b3b3;
            }
        """)


        # Horizontal layout for buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.btn_mulligan)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_keep)
        btn_row.addStretch()

        exit_row = QHBoxLayout()
        exit_row.addStretch()
        exit_row.addWidget(self.btn_exit)  # right aligned

        # ---------- Main layout ----------
        main_layout = QVBoxLayout()
        
        # Top row: runs counter (left) | exiled cards (right)
        top_row = QHBoxLayout()
        top_row.addWidget(self.runs_label)
        top_row.addStretch()
        
        self.exile_container = QWidget()
        self.exile_layout = QHBoxLayout(self.exile_container)
        self.exile_layout.setContentsMargins(0, 0, 0, 0)
        self.exile_layout.setSpacing(5)
        
        self.lbl_exile_title = QLabel(UI_TEXT[self.language]["exiled_cards_label"])
        self.lbl_exile_title.setStyleSheet("font-weight: bold; color: #ff6666;")
        self.lbl_exile_title.hide() # Hidden by default
        self.exile_layout.addWidget(self.lbl_exile_title)
        
        top_row.addWidget(self.exile_container)
        
        main_layout.addLayout(top_row)
        
        main_layout.addWidget(self.card_container)
        main_layout.addWidget(self.state_label)
        main_layout.addLayout(btn_row)
        main_layout.addLayout(exit_row)
        self.setLayout(main_layout)

        self.resize(1100, 650)

        # Start first hand
        self.start_new_game()

    # -----------------------------
    # Override close event to return to StartWindow
    # -----------------------------
    def closeEvent(self, event):
        if self.parent_window:
            self.parent_window.show()  # show StartWindow again
            self.parent_window.reload_json_results()
        event.accept()

    # -----------------------------
    # Start new game
    # -----------------------------
    def start_new_game(self):
        self.deck = list(self.initial_library)
        self.exiled_cards = []
        self.mulligan_count = 0
        self.return_required = 0
        self.return_selected = []
        self.update_exile_display()
        self.current_hand = self.draw_hand()
        self.update_state_text()
        self.display_hand()

    # -----------------------------
    # Update state label
    # -----------------------------
    def update_state_text(self):
        if self.language == LANG_JA:
            if self.mulligan_count == 0:
                t = "初手"
            elif self.mulligan_count == 1:
                t = "フリーマリガン中"
            else:
                t = f"{self.mulligan_count - 1} 枚戻しマリガン中"
        else:
            if self.mulligan_count == 0:
                t = "Opening Hand"
            elif self.mulligan_count == 1:
                t = "Free Mulligan"
            else:
                t = f"Mulligan: put back {self.mulligan_count - 1}"
        
        if self.exiled_cards:
            count = len(self.exiled_cards)
            if self.language == LANG_JA:
                t += f" (追放中: {count}枚)"
            else:
                t += f" (Exiled: {count})"
                
        self.state_label.setText(t)

    # -----------------------------
    # Draw 7 cards
    # -----------------------------
    def draw_hand(self):
        random.shuffle(self.deck)
        return self.deck[:7]

    # -----------------------------
    # Mulligan button
    # -----------------------------
    def do_mulligan(self):
        self.mulligan_count += 1
        self.return_required = max(0, self.mulligan_count - 1)
        self.return_selected = []
        self.current_hand = self.draw_hand()
        self.update_state_text()
        self.display_hand()

    # -----------------------------
    # Keep button
    # -----------------------------
    def do_keep(self):
        # 1) Validate selection
        if len(self.return_selected) != self.return_required:
            QMessageBox.warning(
                self,
                "Warning",
                f"You must select {self.return_required} card(s) to bottom."
            )
            return

        # 2) Show star rating dialog
        rating_dialog = QDialog(self)
        rating_dialog.setWindowTitle("Rate Hand")
        layout = QVBoxLayout()
        label = QLabel("Rate this hand (1-5 stars):")
        layout.addWidget(label)
        stars = StarRatingWidget()
        layout.addWidget(stars)
        rating_dialog.setLayout(layout)
        rating_dialog.resize(400, 100)

        rating_value = {"value": 0}

        def on_rating_changed(val):
            rating_value["value"] = val
            rating_dialog.accept()  # Close the dialog

        stars.ratingChanged.connect(on_rating_changed)

        # Modal dialog
        rating_dialog.setWindowModality(Qt.ApplicationModal)
        rating_dialog.exec_()  # PyQt5 uses exec_()

        if rating_value["value"] == 0:
            return  # user closed without selecting

        # 3) Build log entry
        entry = {
            "mulligan_count": self.mulligan_count,
            "hand": [c["id"] for c in self.current_hand],
            "bottom": self.return_selected,
            "rating": rating_value["value"]
        }

        # 4) Append to JSON log
        append_mulligan_log(self.deck_name, entry, self.csv_path)

        # 4b) Increment run count
        self.run_count += 1
        self.runs_label.setText(f"Runs: {self.run_count}")

        # QMessageBox.information(self, "Keep", f"Hand kept and rated {rating_value['value']} stars.")

        # 5) Start next hand
        self.start_new_game()



    # -----------------------------
    # Display cards with slide-in animation
    # -----------------------------
    def display_hand(self):
        # Clear old cards
        for child in getattr(self, "card_widgets", []):
            child.hide() # Hide immediately to prevent overlap
            child.deleteLater()
        self.card_widgets = []

        # Create new card widgets
        for card in self.current_hand:
            w = CardWidget(card["img"], card["id"])
            w.clicked.connect(self.on_card_clicked)
            w.serum_activated.connect(self.handle_serum_powder)
            w.setParent(self.card_container)
            w.hide()
            self.card_widgets.append(w)
            
            # Special check for Serum Powder
            if card["id"] == "Serum_Powder_front.jpg":
                w.start_pulse()
                w.show_serum_button(UI_TEXT[self.language]["btn_serum_powder"])

        # Animate cards with delay
        for i, widget in enumerate(self.card_widgets):
            QTimer.singleShot(i * 100, lambda w=widget, idx=i: self.animate_card(w, idx))

    # -----------------------------
    # Slide-in animation for a card
    # -----------------------------
    def animate_card(self, widget, index):
        try:
            widget.show()
            widget.raise_()

            container_width = self.card_container.width()
            container_height = self.card_container.height()
            num_cards = len(self.card_widgets)
            card_width = widget.width()
            card_height = widget.height()

            if num_cards > 1:
                spacing = (container_width - card_width * num_cards) / (num_cards - 1)
            else:
                spacing = 0

            x_end = index * (card_width + spacing)
            y_end = (container_height - card_height) // 2

            # Start off-screen right
            start_x = container_width + 50
            start_y = y_end

            widget.move(start_x, start_y)

            anim = QPropertyAnimation(widget, b"pos", self)
            anim.setDuration(400)
            anim.setStartValue(QPoint(start_x, start_y))
            anim.setEndValue(QPoint(int(x_end), int(y_end)))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self.animations.append(anim)
        except RuntimeError:
            # Widget was likely deleted before the timer fired
            pass


    # -----------------------------
    # Recalculate card positions on resize
    # -----------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "card_widgets"):
            return
        num_cards = len(self.card_widgets)
        if num_cards == 0:
            return

        container_width = self.card_container.width()
        container_height = self.card_container.height()
        card_width = self.card_widgets[0].width() or 200

        if num_cards > 1:
            spacing = (container_width - card_width * num_cards) / (num_cards - 1)
        else:
            spacing = 0

        for i, w in enumerate(self.card_widgets):
            x = i * (card_width + spacing)
            y = (container_height - w.height()) // 2
            w.move(int(x), int(y))


    # -----------------------------
    # Card clicked for bottom selection
    # -----------------------------
    def on_card_clicked(self, widget: CardWidget):
        if self.return_required == 0:
            return
        cid = widget.card_id
        selected_count = len(self.return_selected)
        already_selected = widget.marked_bottom
        if not already_selected and selected_count >= self.return_required:
            return
        new_state = not already_selected
        widget.set_marked(new_state)
        if new_state and cid not in self.return_selected:
            self.return_selected.append(cid)
        elif not new_state and cid in self.return_selected:
            self.return_selected.remove(cid)

    def handle_serum_powder(self, widget: CardWidget):
        if not self.csv_path:
            return

        # Cards NOT marked for bottom are exiled
        to_exile = []
        to_return = []
        
        for w in self.card_widgets:
            card_data = next((c for c in self.current_hand if c["id"] == w.card_id), None)
            if not card_data: continue
            
            if w.marked_bottom:
                to_return.append(card_data)
            else:
                to_exile.append(card_data)

        # Confirm exile
        ret = QMessageBox.question(
            self,
            UI_TEXT[self.language].get("reset_confirm_title", "Confirm"),
            "このハンドを追放して引き直しますか？\nDo you want to exile this hand and redraw?",
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if ret != QMessageBox.Ok:
            return
        
        # 1) Exile cards (remove from current simulation pool)
        self.exiled_cards.extend(to_exile)
        for c in to_exile:
            if c in self.deck:
                self.deck.remove(c)
        
        # 3) Redraw
        # Shuffle library (which still contains 'to_return' cards because draw_hand didn't remove them)
        random.shuffle(self.deck)
        
        num_to_draw = len(to_exile)
        new_drawn = self.deck[:num_to_draw]
        
        # New hand is ONLY the drawn cards. return_required becomes 0.
        self.current_hand = new_drawn
        self.return_required = 0
        self.return_selected = []
            
        self.update_state_text()
        self.display_hand()
        self.update_exile_display()

    def update_exile_display(self):
        # Clear existing except label
        while self.exile_layout.count() > 1:
            item = self.exile_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        if not self.exiled_cards:
            self.lbl_exile_title.hide()
            return
            
        self.lbl_exile_title.show()
        # Limit display to last N cards or similar if needed, but for now show all small
        folder = self.csv_path.parent
        for card_data in self.exiled_cards:
            lbl = QLabel()
            pix = QPixmap(str(folder / card_data["id"]))
            if not pix.isNull():
                lbl.setPixmap(pix.scaledToHeight(60, Qt.SmoothTransformation))
                lbl.setToolTip(card_data["id"])
            else:
                lbl.setText("?")
            self.exile_layout.addWidget(lbl)
