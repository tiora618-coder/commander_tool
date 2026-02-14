# mulligan_simulator.py
import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QMessageBox, QFrame, QScrollArea,
    QProgressDialog, QHBoxLayout
)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QFont, QPixmap, QPolygon, QPainter, QColor

from deck_loader import load_deck_from_csv
from simulation_window import SimulationWindow
from gui_language import UI_TEXT, LANG_EN, LANG_JA
import collections
import json
import requests

class StartWindow(QWidget):
    def __init__(self, initial_csv=None):
        super().__init__()

        self.csv_path = Path(initial_csv) if initial_csv else None
        self.language = LANG_JA

        self.setWindowTitle("Mulligan Simulator")
        self.resize(1300, 850)
        # Dark mode styles — ensure most text widgets use white text
        self.setStyleSheet("""
            QWidget { background: #1e1e1e; color: #ffffff; }
            QLabel { color: #ffffff; }
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QPushButton:hover { background-color: #444444; }
            QComboBox, QSpinBox, QLineEdit { color: #ffffff; background: #2b2b2b; }
            QComboBox QAbstractItemView { color: #ffffff; background: #2b2b2b; }
            QMenu { color: #ffffff; background: #2b2b2b; }
            QToolTip { color: #ffffff; background: #333333; }
        """)

        # ===============================
        # Layout定義 (Scroll Area)
        # ===============================
        outer_layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        
        container = QWidget()
        main = QVBoxLayout(container)
        main.setSpacing(18)
        main.setContentsMargins(20, 20, 20, 20)
        
        self.scroll_area.setWidget(container)
        outer_layout.addWidget(self.scroll_area)

        # ==========================================================
        # Runs + Rating + Average Hand Size（3カラム）
        # ==========================================================
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        # --- Runs フレーム ---
        runs_frame = QFrame()
        runs_frame.setStyleSheet("""
            QFrame {
                border: 2px solid #666666;
                border-radius: 6px;
                padding: 10px;
                background-color: #1e1e1e;
            }
        """)
        runs_col = QVBoxLayout(runs_frame)
        runs_col.setSpacing(6)
        runs_col.setContentsMargins(0, 0, 0, 0)

        self.lbl_runs_title = QLabel(UI_TEXT[self.language]["runs"])
        self.lbl_runs_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #cccccc; border: 1px solid #1e1e1e; background-color: #1e1e1e;")
        self.lbl_runs = QLabel("-")
        self.lbl_runs.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")

        runs_col.addWidget(self.lbl_runs_title)
        runs_col.addWidget(self.lbl_runs)

        # --- Rating フレーム ---
        rating_frame = QFrame()
        rating_frame.setStyleSheet("""
            QFrame {
                border: 2px solid #666666;
                border-radius: 6px;
                padding: 10px;
                background-color: #1e1e1e;
            }
        """)
        self.rating_col = QVBoxLayout(rating_frame)
        self.rating_col.setSpacing(6)
        self.rating_col.setContentsMargins(0, 0, 0, 0)

        self.lbl_rating_title = QLabel(UI_TEXT[self.language]["rating"])
        self.lbl_rating_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #cccccc; border: 1px solid #1e1e1e; background-color: #1e1e1e;")

        self.star_widget = StarRatingWidget(0.0)

        self.rating_col.addWidget(self.lbl_rating_title)
        self.rating_col.addWidget(self.star_widget)

        # --- Average Hand Size フレーム ---
        hand_frame = QFrame()
        hand_frame.setStyleSheet("""
            QFrame {
                border: 2px solid #666666;
                border-radius: 6px;
                padding: 10px;
                background-color: #1e1e1e;
            }
        """)
        self.hand_col = QVBoxLayout(hand_frame)
        self.hand_col.setSpacing(6)
        self.hand_col.setContentsMargins(0, 0, 0, 0)

        self.lbl_hand_title = QLabel(UI_TEXT[self.language]["average_hand_size"])
        self.lbl_hand_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #cccccc; border: 1px solid #1e1e1e; background-color: #1e1e1e;")

        hand_row = QHBoxLayout()
        hand_row.setSpacing(8)
        hand_row.setContentsMargins(0, 0, 0, 0)

        self.hand_bar = HandSizeBarWidget(0.0)

        self.lbl_avg_hand = QLabel("0.00")
        self.lbl_avg_hand.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")

        hand_row.addWidget(self.hand_bar)
        hand_row.addWidget(self.lbl_avg_hand)
        hand_row.addStretch()

        self.hand_col.addWidget(self.lbl_hand_title)
        self.hand_col.addLayout(hand_row)

        # --- CSV & Language フレーム (New 4th Column) ---
        config_frame = QFrame()
        config_frame.setStyleSheet("""
            QFrame {
                border: 2px solid #666666;
                border-radius: 6px;
                padding: 10px;
                background-color: #1e1e1e;
            }
            QLabel { border: none; }
        """)
        config_col = QVBoxLayout(config_frame)
        config_col.setSpacing(4)
        config_col.setContentsMargins(0, 0, 0, 0)

        # Language Selector
        lang_row = QHBoxLayout()
        self.lang_label = QLabel("Language:")
        self.lang_label.setStyleSheet("color: #ffffff; font-size: 12px;")
        self.lang_selector = QComboBox()
        self.lang_selector.addItem("日本語", LANG_JA)
        self.lang_selector.addItem("English", LANG_EN)
        self.lang_selector.currentIndexChanged.connect(self.change_language)
        lang_row.addWidget(self.lang_label)
        lang_row.addWidget(self.lang_selector)
        config_col.addLayout(lang_row)

        # CSV Label
        self.csv_label = QLabel("(No CSV Loaded)")
        self.csv_label.setAlignment(Qt.AlignLeft)
        self.csv_label.setStyleSheet("color: #ffffff; font-size: 12px;")
        config_col.addWidget(self.csv_label)

        # Load CSV Button
        self.btn_load = QPushButton(UI_TEXT[self.language]["load_csv"])
        self.btn_load.clicked.connect(self.load_csv)
        self.btn_load.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                font-size: 12px;
                padding: 4px;
            }
        """)
        config_col.addWidget(self.btn_load)

        # Reset Results Button
        self.btn_reset = QPushButton(UI_TEXT[self.language]["reset_results"])
        self.btn_reset.clicked.connect(self.reset_results)
        self.btn_reset.setEnabled(False) # Default to disabled until a CSV/JSON is loaded
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: #ff6666;
                border: 1px solid #ff4444;
                font-size: 12px;
                padding: 4px;
            }
            QPushButton:hover { background-color: #443333; }
            QPushButton:disabled { color: #888; border: 1px solid #555; }
        """)
        config_col.addWidget(self.btn_reset)

        # --- 横並びに配置 ---
        info_row.addWidget(runs_frame)
        info_row.addWidget(rating_frame)
        info_row.addWidget(hand_frame)
        info_row.addWidget(config_frame)
        info_row.addStretch()

        main.addLayout(info_row)
        main.addWidget(self._separator())

        # Start Simulation (Moved here)
        self.btn_start = QPushButton(UI_TEXT[self.language]["start_simulation"])
        self.btn_start.clicked.connect(self.start_simulation)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #4cd137;
                color: #0a3d0a;
                font-size: 20px;
                font-weight: bold;
                padding: 12px;
                border-radius: 10px;
            }
            QPushButton:hover { background-color: #a8ffbe; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        main.addWidget(self.btn_start)

        main.addWidget(self._separator())

        # ==========================================================
        # Most Bottomed Cards
        # ==========================================================
        self.lbl_bottom = QLabel(UI_TEXT[self.language]["most_bottomed_cards"])
        self.lbl_bottom.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        main.addWidget(self.lbl_bottom)

        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.setSpacing(8)
        main.addLayout(self.bottom_layout)

        main.addWidget(self._separator())

        # ==========================================================
        # Most Kept Cards
        # ==========================================================
        self.lbl_kept = QLabel(UI_TEXT[self.language]["most_kept_cards"])
        self.lbl_kept.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        main.addWidget(self.lbl_kept)

        self.kept_layout = QHBoxLayout()
        self.kept_layout.setSpacing(8)
        main.addLayout(self.kept_layout)

        main.addWidget(self._separator())

        # ==========================================================
        # Recent Results by Rating
        # ==========================================================
        self.lbl_recent = QLabel(UI_TEXT[self.language]["recent_results"])
        self.lbl_recent.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        main.addWidget(self.lbl_recent)

        # Rating 5 -> 1 の順に並べるためのコンテナ
        self.recent_container = QVBoxLayout()
        self.recent_container.setSpacing(5)
        main.addLayout(self.recent_container)

        self.rating_sections = {} # rating -> CollapsibleRatingSection
        for r in range(5, 0, -1):
            section = CollapsibleRatingSection(r)
            self.recent_container.addWidget(section)
            self.rating_sections[r] = section

        main.addWidget(self._separator())

        # 初回は JSON があれば読み込み
        if self.csv_path:
            self.load_csv_from_path(self.csv_path)
        else:
            self.load_mulligan_json_if_exists()


    # -------------------------------------------------------------------
    # Separator (水平線)
    # -------------------------------------------------------------------
    def _separator(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #666; margin-top:10px; margin-bottom:10px;")
        return line


    # ---------------------------------------------------
    # UI 言語変更
    # ---------------------------------------------------
    def change_language(self):
        self.language = self.lang_selector.currentData()
        self.lang_label.setText(UI_TEXT[self.language]["language"])
        self.btn_load.setText(UI_TEXT[self.language]["load_csv"])
        self.btn_start.setText(UI_TEXT[self.language]["start_simulation"])
        self.lbl_rating_title.setText(UI_TEXT[self.language]["rating"])
        self.lbl_hand_title.setText(UI_TEXT[self.language]["average_hand_size"])
        self.lbl_runs_title.setText(UI_TEXT[self.language]["runs"])
        self.lbl_bottom.setText(UI_TEXT[self.language]["most_bottomed_cards"])
        self.lbl_kept.setText(UI_TEXT[self.language]["most_kept_cards"])
        self.lbl_recent.setText(UI_TEXT[self.language]["recent_results"])
        self.btn_reset.setText(UI_TEXT[self.language]["reset_results"])
        for section in self.rating_sections.values():
            section.update_language(self.language)

    def start_simulation(self):
        if not self.csv_path:
            return

        try:
            deck = load_deck_from_csv(self.csv_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        deck_name = self.csv_path.stem
        
        # Load existing JSON to get current run count
        json_path = self.csv_path.with_name(deck_name + "_mulligan.json")
        initial_runs = 0
        if json_path.exists():
            try:
                with json_path.open(encoding="utf-8") as f:
                    json_data = json.load(f)
                    initial_runs = len(json_data)  # Number of runs = number of entries
            except:
                initial_runs = 0

        # 既存ウィンドウがあったら閉じる
        if hasattr(self, "sim_window") and self.sim_window is not None:
            self.sim_window.close()

        self.sim_window = SimulationWindow(
            deck,
            deck_name,
            self.language,
            csv_path=self.csv_path,
            parent=self,
            initial_run_count=initial_runs
        )
        self.sim_window.show()
        self.hide()


    # ---------------------------------------------------
    # JSON 読み込み（存在しなければ None を返す）
    # ---------------------------------------------------
    def load_mulligan_json_if_exists(self):
        if not self.csv_path:
            return None

        json_path = self.csv_path.with_name(self.csv_path.stem + "_mulligan.json")
        if not json_path.exists():
            return None

        try:
            with json_path.open(encoding="utf-8") as f:
                return json.load(f)
        except:
            return None

    # ---------------------------------------------------
    # CSV ロード時、自動で JSON を読み込んで GUI に反映
    # ---------------------------------------------------
    def load_csv_from_path(self, path: Path):
        self.csv_path = path
        self.csv_label.setText(self.csv_path.name)
        self.btn_start.setEnabled(True)

        # ---- JSON 自動読み込み ----
        result = self.load_mulligan_json_if_exists()
        self._set_ui_from_json_result(result)

    def load_csv(self):
        csv_path, _ = QFileDialog.getOpenFileName(
            self,
            UI_TEXT[self.language]["load_csv"],
            "",
            "CSV Files (*.csv)"
        )
        if not csv_path:
            return

        self.load_csv_from_path(Path(csv_path))

    def _set_ui_from_json_result(self, result):
        if result is None:
            # 初回起動など ⇒ 表示を初期化して終了
            self.lbl_runs.setText("-")
            self.lbl_avg_hand.setText("-")
            self.lbl_avg_hand.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")

            new_star = StarRatingWidget(0.0)
            self.rating_col.replaceWidget(self.star_widget, new_star)
            self.star_widget.deleteLater()
            self.star_widget = new_star

            new_bar = HandSizeBarWidget(0.0)
            self.hand_col.itemAt(1).replaceWidget(self.hand_bar, new_bar)
            self.hand_bar.deleteLater()
            self.hand_bar = new_bar

            self.update_card_images(self.bottom_layout, {})
            self.update_card_images(self.kept_layout, {})
            self.update_recent_results_ui({})

            self.btn_reset.setEnabled(False)
            return

        # JSON がある時だけ解析して GUI に表示
        self.btn_reset.setEnabled(True)
        progress = QProgressDialog("Loading Simulation Data...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.autoClose()
        progress.show()
        QApplication.processEvents()

        stats = self.parse_simulation_results(result, progress, 0, 50)

        self.lbl_runs.setText(f"{stats['run_count']}")
        self.lbl_avg_hand.setText(f"{stats['avg_hand_size']:.2f}")
        self.lbl_avg_hand.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")

        new_star = StarRatingWidget(stats["avg_rating"])
        self.rating_col.replaceWidget(self.star_widget, new_star)
        self.star_widget.deleteLater()
        self.star_widget = new_star

        new_bar = HandSizeBarWidget(stats["avg_hand_size"])
        self.hand_col.itemAt(1).replaceWidget(self.hand_bar, new_bar)
        self.hand_bar.deleteLater()
        self.hand_bar = new_bar

        self.update_card_images(self.bottom_layout, stats["bottom_counts"])
        self.update_card_images(self.kept_layout, stats["kept_counts"])
        self.update_recent_results_ui(stats["recent_by_rating"], progress, 50, 100)
        
        progress.setValue(100)


    def reload_json_results(self):
        if not self.csv_path:
            return

        result = self.load_mulligan_json_if_exists()
        if result is None:
            return

        progress = QProgressDialog("Reloading Simulation Data...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.autoClose()
        progress.show()
        QApplication.processEvents()

        stats = self.parse_simulation_results(result, progress, 0, 50)
        self.btn_reset.setEnabled(True)

        # --- Runs / Hand Size 更新 ---
        self.lbl_runs.setText(f"{stats['run_count']}")
        self.lbl_avg_hand.setText(f"{stats['avg_hand_size']:.2f}")
        self.lbl_avg_hand.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")

        # --- 星評価の更新 ---
        new_star = StarRatingWidget(stats["avg_rating"])
        self.rating_col.replaceWidget(self.star_widget, new_star)
        self.star_widget.deleteLater()
        self.star_widget = new_star

        # 平均手札サイズバー更新
        new_bar = HandSizeBarWidget(stats["avg_hand_size"])
        self.hand_col.itemAt(1).replaceWidget(self.hand_bar, new_bar)
        self.hand_bar.deleteLater()
        self.hand_bar = new_bar

        # --- bottom / kept 更新 ---
        self.update_card_images(self.bottom_layout, stats["bottom_counts"])
        self.update_card_images(self.kept_layout, stats["kept_counts"])
        self.update_recent_results_ui(stats["recent_by_rating"], progress, 50, 100)
        
        progress.setValue(100)


    # ---------------------------------------------------
    # JSON を読み込んで GUI を更新（外部API向け）
    # ---------------------------------------------------
    def load_result_json_from_path(self, json_path: Path):
        if not json_path.exists():
            return

        with json_path.open(encoding="utf-8") as f:
            json_list = json.load(f)

        stats = self.parse_simulation_results(json_list)

        self.lbl_runs.setText(f"{stats['run_count']}")
        self.lbl_avg_hand.setText(f"{stats['avg_hand_size']:.2f}")
        self.lbl_avg_hand.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")

        new_star = StarRatingWidget(stats["avg_rating"])
        self.layout().replaceWidget(self.star_widget, new_star)
        self.star_widget.deleteLater()
        self.star_widget = new_star

        self.update_card_images(self.bottom_layout, stats["bottom_counts"])
        self.update_card_images(self.kept_layout, stats["kept_counts"])

    def parse_simulation_results(self, json_list, progress_diag=None, start_val=0, end_val=100):

        run_count = len(json_list)
        if run_count == 0:
            return None

        total_mulligans = 0
        total_effective_hand_size = 0
        total_rating = 0

        bottom_counts = collections.Counter()
        kept_counts = collections.Counter()

        for i, entry in enumerate(json_list):
            bottom = entry.get("bottom", [])
            hand = entry.get("hand", [])

            total_mulligans += entry.get("mulligan_count", 0)

            # ---- 実質のハンド枚数 ----
            effective = 7 - len(bottom)
            total_effective_hand_size += effective

            total_rating += entry.get("rating", 0)

            # ---- bottom 集計 ----
            for card in bottom:
                bottom_counts[card] += 1

            # ---- kept（手札にあったカード） ----
            for card in hand:
                kept_counts[card] += 1
            
            # Progress update (every 100 entries)
            if progress_diag and i % 100 == 0:
                val = start_val + int((i / run_count) * (end_val - start_val))
                progress_diag.setValue(val)
                QApplication.processEvents()
                if progress_diag.wasCanceled():
                    break

        avg_mulligans = total_mulligans / run_count
        avg_hand_size = total_effective_hand_size / run_count
        avg_rating = total_rating / run_count

        # ---- Rating別の最近5件 ----
        recent_by_rating = {r: [] for r in range(1, 6)}
        # 最新のものから順に見ていく
        for entry in reversed(json_list):
            r = entry.get("rating")
            if r in recent_by_rating and len(recent_by_rating[r]) < 5:
                # hand と bottom の両方を保存
                recent_by_rating[r].append({
                    "hand": entry.get("hand", []),
                    "bottom": entry.get("bottom", [])
                })

        return {
            "run_count": run_count,
            "avg_mulligans": avg_mulligans,
            "avg_hand_size": avg_hand_size,
            "avg_rating": avg_rating,
            "bottom_counts": bottom_counts,
            "kept_counts": kept_counts,
            "recent_by_rating": recent_by_rating
        }
    
    def update_recent_results_ui(self, recent_dict, progress_diag=None, start_val=0, end_val=100):
        folder = self.csv_path.parent if self.csv_path else None
        
        ratings = list(self.rating_sections.items())
        total_sections = len(ratings)

        for i, (r, section) in enumerate(ratings):
            section.clear_results()
            
            if not folder or r not in recent_dict:
                continue
                
            for record in recent_dict[r]:
                w = HandResultWidget(record["hand"], record["bottom"], folder)
                section.add_result(w)
            
            if progress_diag:
                val = start_val + int(((i + 1) / total_sections) * (end_val - start_val))
                progress_diag.setValue(val)
                QApplication.processEvents()
                if progress_diag.wasCanceled():
                    break

    def update_card_images(self, layout, count_dict):
        # layout クリア
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self.csv_path:
            return

        folder = self.csv_path.parent

        # 多い順 上位10枚
        sorted_cards = sorted(count_dict.items(), key=lambda x: -x[1])[:10]

        for card_id, count in sorted_cards:
            img_path = folder / card_id
            if not img_path.exists():
                continue

            label = QLabel()
            pix = QPixmap(str(img_path))
            pix = pix.scaled(110, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pix)
            label.setToolTip(f"{card_id}\nCount: {count}")
            layout.addWidget(label)

    def reset_results(self):
        if not self.csv_path:
            return

        json_path = self.csv_path.with_name(self.csv_path.stem + "_mulligan.json")
        if not json_path.exists():
            return

        # Confirmation Dialog
        ret = QMessageBox.question(
            self,
            UI_TEXT[self.language]["reset_confirm_title"],
            UI_TEXT[self.language]["reset_confirm_msg"],
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel
        )

        if ret == QMessageBox.Ok:
            try:
                json_path.unlink()
                # Clear UI
                self.lbl_runs.setText("-")
                self.lbl_avg_hand.setText("-")
                self.lbl_avg_hand.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")

                new_star = StarRatingWidget(0.0)
                self.rating_col.replaceWidget(self.star_widget, new_star)
                self.star_widget.deleteLater()
                self.star_widget = new_star

                new_bar = HandSizeBarWidget(0.0)
                self.hand_col.itemAt(1).replaceWidget(self.hand_bar, new_bar)
                self.hand_bar.deleteLater()
                self.hand_bar = new_bar

                self.update_card_images(self.bottom_layout, {})
                self.update_card_images(self.kept_layout, {})
                self.update_recent_results_ui({})
                
                self.btn_reset.setEnabled(False)

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete results: {e}")


class StarRatingWidget(QWidget):
    def __init__(self, rating: float, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.star_area = StarPainterWidget(rating)
        layout.addWidget(self.star_area)

        num_label = QLabel(f"{rating:.2f}")
        num_label.setFont(QFont("Arial", 18))
        num_label.setStyleSheet("color: #ffffff; margin-left: 16px;")
        layout.addWidget(num_label)


class StarPainterWidget(QWidget):
    def __init__(self, rating: float, parent=None):
        super().__init__(parent)
        self.rating = rating
        self.star_size = 28
        self.margin = 4
        self.setFixedSize((self.star_size + self.margin) * 5, 30)

    def draw_star(self, painter, x, y, color):
        from math import sin, cos, pi
        R = 12
        r = R * 0.45

        points = []
        for i in range(10):
            angle = pi/2 + i * pi / 5
            radius = R if i % 2 == 0 else r
            px = x + R + radius * cos(angle)
            py = y + R + radius * sin(angle)
            points.append(QPoint(int(px), int(py)))

        painter.setBrush(color)
        painter.drawPolygon(QPolygon(points))

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QColor

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        full = int(self.rating)
        frac = self.rating - full

        # 星の実描画幅（計算すると約22px）
        STAR_DRAW_WIDTH = 22
        STAR_LEFT_OFFSET = 2   # 星の左側の余白（約2px）

        for i in range(5):
            x = i * (self.star_size + self.margin)

            # ---- グレー星（ベース） ----
            self.draw_star(painter, x, 0, QColor(180, 180, 180))

            painter.save()

            if i < full:
                # 完全塗り
                painter.setClipRect(x + STAR_LEFT_OFFSET, 0,
                                    STAR_DRAW_WIDTH, self.star_size)

            elif i == full and frac > 0:
                # 部分塗り
                fill_width = int(STAR_DRAW_WIDTH * frac)
                painter.setClipRect(int(x + STAR_LEFT_OFFSET), 0,
                                    fill_width, self.star_size)
            else:
                painter.restore()
                continue

            # 黄色星をクリップ状態で上から描く
            self.draw_star(painter, x, 0, QColor("gold"))
            painter.restore()

        painter.end()


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


class HandSizeBarWidget(QWidget):
    def __init__(self, avg_size: float, parent=None):
        super().__init__(parent)
        self.avg_size = avg_size

        # カード裏面画像
        back_path = Path(__file__).parent / "assets" / "card_back.png"
        self.back_img = load_or_download_card_back(back_path)

        # サイズ
        self.box_width = 50
        self.box_height = 70
        self.margin = 6

        self.setFixedSize((self.box_width + self.margin) * 7, self.box_height)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # ---- 黒塗り量（右から 7 - avg）----
        black_total = 7 - self.avg_size        # 例 6.16 → 0.84
        full_black = int(black_total)          # 例 0
        frac = black_total - full_black        # 例 0.84

        # 黒塗り開始位置（右端から）
        # 例：full_black = 0 → 最右の1枚が部分塗り用
        start_index = 7 - full_black - 1

        for i in range(7):
            x = i * (self.box_width + self.margin)

            # --- 裏面画像 ---
            scaled_back = self.back_img.scaled(
                self.box_width, self.box_height,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            painter.drawPixmap(x, 0, scaled_back)

            # --- 完全黒塗り（右側 full_black 枚）---
            if i > 6 - full_black:
                painter.fillRect(
                    x, 0,
                    self.box_width, self.box_height,
                    QColor(0, 0, 0, 220)
                )

            # --- 部分黒塗り：右から start_index のカードが対象 ---
            elif i == start_index and frac > 0:
                width = int(self.box_width * frac)
                # 右側から塗る
                painter.fillRect(
                    x + (self.box_width - width), 0,
                    width, self.box_height,
                    QColor(0, 0, 0, 220)
                )

        painter.end()

class HandResultWidget(QWidget):
    """
    1回のハンド結果（キープ時の手札）をサムネイルで表示する。
    Bottomに返したカードにはオーバーレイを表示する。
    """
    def __init__(self, hand_ids, bottom_ids, folder, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter) # Center thumbnails

        for card_id in hand_ids:
            img_path = folder / card_id
            if img_path.exists():
                container = QWidget()
                container_layout = QVBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                
                label = QLabel()
                pix = QPixmap(str(img_path))
                # さらにサイズアップ (1.5倍)
                # 80 * 1.5 = 120, 116 * 1.5 = 174
                pix = pix.scaled(120, 174, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(pix)
                label.setToolTip(card_id)
                
                # Bottom オーバーレイ
                if card_id in bottom_ids:
                    overlay = QLabel("Bottom", label)
                    overlay.setAlignment(Qt.AlignCenter)
                    overlay.setStyleSheet("""
                        background-color: rgba(0, 0, 0, 180);
                        color: #ff4444;
                        font-weight: bold;
                        font-size: 18px;
                        border-radius: 4px;
                    """)
                    overlay.setFixedSize(120, 40)
                    overlay.move(0, 67) # Center slightly (174 - 40) / 2 approx
                
                container_layout.addWidget(label)
                layout.addWidget(container)
        layout.addStretch()

class CollapsibleRatingSection(QWidget):
    """
    Ratingごとの折り畳みセクション
    """
    def __init__(self, rating, parent=None):
        super().__init__(parent)
        self.rating = rating
        self.expanded = False
        self.language = LANG_JA # Default or passed from parent

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Header Button
        self.btn_toggle = QPushButton()
        self.update_language(self.language)
        self.btn_toggle.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px;
                font-weight: bold;
                background-color: #333333;
                border: 1px solid #444444;
                border-radius: 4px;
                color: gold;
            }
            QPushButton:hover { background-color: #444444; }
        """)
        self.btn_toggle.clicked.connect(self.toggle_expand)
        self.main_layout.addWidget(self.btn_toggle)

        # Content Area (Scroll Area)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(200) # Increased from 150
        self.scroll_area.setMaximumHeight(600) # Increased from 400
        self.scroll_area.setVisible(False)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(20, 5, 10, 10)
        self.content_layout.setSpacing(10)
        self.content_layout.setAlignment(Qt.AlignCenter)
        
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)

    def toggle_expand(self):
        self.expanded = not self.expanded
        self.scroll_area.setVisible(self.expanded)
        self.update_language(self.language)

    def update_language(self, language):
        self.language = language
        prefix = UI_TEXT[language].get("rating_header_prefix", "Rating")
        stars = "★" * self.rating + "☆" * (5 - self.rating)
        sign = " [ - ] " if self.expanded else " [ + ] "
        self.btn_toggle.setText(f"{prefix} {self.rating} {stars}{sign}")

    def clear_results(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def add_result(self, widget):
        self.content_layout.addWidget(widget)

def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    w = StartWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
