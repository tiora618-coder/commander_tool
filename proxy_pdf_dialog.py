import math
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QScrollArea, QWidget, QFileDialog, QMessageBox, QApplication, QCheckBox,
    QGroupBox
)
from PyQt5.QtCore import Qt, QRectF, QSizeF
from PyQt5.QtGui import QPixmap, QPainter, QImage, QColor, QFont, QPdfWriter, QPageSize, QPageLayout, QPainterPath, QPen, QBrush, QFontMetrics
from gui_language import UI_TEXT

# 用紙サイズ定義 (mm単位、幅 x 高さ)
PAPER_SIZES = {
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "B3": (364.0, 515.0),
    "B4": (257.0, 364.0),
}

class ProxyPDFPreviewDialog(QDialog):
    def __init__(self, cards, image_dir, language, csv_path=None, parent=None,
                 consideration_cards=None):
        super().__init__(parent)
        self.cards = cards
        self.consideration_cards = consideration_cards or []
        self.image_dir = Path(image_dir)
        self.language = language
        self.csv_path = Path(csv_path) if csv_path else None
        self.setWindowTitle(UI_TEXT[self.language].get("proxy_pdf_preview", "Proxy PDF Preview"))
        self.resize(900, 750)

        self.spacing_mm = 2.0

        # Setup UI
        self.layout = QVBoxLayout(self)

        # ── 上部コントロール行 ──────────────────────────────────────────
        top_layout = QHBoxLayout()

        # 余白
        spacing_label = QLabel(UI_TEXT[self.language].get("card_spacing_mm", "Card Spacing (mm):"))
        self.spacing_combo = QComboBox()
        for i in range(11):
            self.spacing_combo.addItem(str(i))
        self.spacing_combo.setCurrentText(str(int(self.spacing_mm)))
        self.spacing_combo.currentTextChanged.connect(self.on_spacing_changed)

        # 用紙サイズ
        paper_label_text = "用紙サイズ:" if self.language == "ja" else "Paper Size:"
        paper_label = QLabel(paper_label_text)
        self.paper_combo = QComboBox()
        for name in PAPER_SIZES.keys():
            self.paper_combo.addItem(name)
        self.paper_combo.setCurrentText("A4")
        self.paper_combo.currentTextChanged.connect(self.update_preview)
        self.paper_combo.setStyleSheet("padding: 4px; background: #333; color: white; border: 1px solid #555;")

        # Export ボタン
        self.export_btn = QPushButton(UI_TEXT[self.language].get("export_pdf", "Export PDF"))
        self.export_btn.clicked.connect(self.export_pdf)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d7; color: white; font-weight: bold;
                padding: 6px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #0086f1; }
        """)

        top_layout.addWidget(spacing_label)
        top_layout.addWidget(self.spacing_combo)
        top_layout.addSpacing(16)
        top_layout.addWidget(paper_label)
        top_layout.addWidget(self.paper_combo)
        top_layout.addStretch()
        top_layout.addWidget(self.export_btn)
        self.layout.addLayout(top_layout)

        # ── カテゴリ選択チェックボックス ──────────────────────────────
        cb_group = QGroupBox("出力カード" if self.language == "ja" else "Output Cards")
        cb_group.setStyleSheet("""
            QGroupBox {
                color: white; border: 1px solid #555; border-radius: 4px;
                margin-top: 6px; padding: 6px;
                font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; }
            QCheckBox { color: white; spacing: 6px; }
        """)
        cb_layout = QHBoxLayout(cb_group)
        cb_layout.setSpacing(16)

        def make_cb(text, checked=True):
            cb = QCheckBox(text)
            cb.setChecked(checked)
            cb.stateChanged.connect(self.update_preview)
            return cb

        self.cb_commander   = make_cb("統率者"  if self.language == "ja" else "Commander")
        self.cb_creature    = make_cb("クリーチャー" if self.language == "ja" else "Creature")
        self.cb_spell       = make_cb("スペル"  if self.language == "ja" else "Spell")
        self.cb_land        = make_cb("土地"    if self.language == "ja" else "Land")
        self.cb_considering = make_cb("検討中"  if self.language == "ja" else "Considering")
        self.cb_token       = make_cb("トークン" if self.language == "ja" else "Token")

        for cb in (self.cb_commander, self.cb_creature, self.cb_spell,
                   self.cb_land, self.cb_considering, self.cb_token):
            cb_layout.addWidget(cb)
        cb_layout.addStretch()

        self.layout.addWidget(cb_group)

        # ── プレビュースクロールエリア ─────────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setAlignment(Qt.AlignHCenter)
        self.scroll.setWidget(self.preview_container)
        self.layout.addWidget(self.scroll)

        self.update_preview()

    # ──────────────────────────────────────────────────────────────────────
    def on_spacing_changed(self, val):
        self.spacing_mm = float(val)
        self.update_preview()

    def _get_paper_mm(self):
        """選択中の用紙サイズ (w_mm, h_mm) を返す"""
        name = self.paper_combo.currentText()
        return PAPER_SIZES.get(name, PAPER_SIZES["A4"])

    def _build_flat_cards(self):
        """チェックボックスの状態に従いカードを分類・フラット化して返す"""
        commanders   = []
        creatures    = []
        spells       = []
        lands        = []
        tokens       = []

        for c in self.cards:
            is_cmd   = bool(c.get("Commander_A")) or bool(c.get("Commander_B"))
            is_tok   = str(c.get("is_token")) == "True"
            type_str = c.get("type_front", "")

            if is_cmd:
                commanders.append(c)
            elif is_tok:
                tokens.append(c)
            elif "Land" in type_str:
                lands.append(c)
            elif "Creature" in type_str:
                creatures.append(c)
            else:
                spells.append(c)

        ordered = []
        if self.cb_commander.isChecked():
            ordered += commanders
        if self.cb_creature.isChecked():
            ordered += creatures
        if self.cb_spell.isChecked():
            ordered += spells
        if self.cb_land.isChecked():
            ordered += lands
        if self.cb_considering.isChecked():
            ordered += self.consideration_cards
        if self.cb_token.isChecked():
            ordered += tokens

        flat = []
        for c in ordered:
            try:
                count = int(c.get("count") or 1)
            except (ValueError, TypeError):
                count = 1
            for _ in range(count):
                front = c.get("card_file_front")
                if front:
                    flat.append(front)
                back = c.get("card_file_back")
                if back:
                    flat.append(back)
        return flat

    def get_pages(self, dpi):
        paper_w_mm, paper_h_mm = self._get_paper_mm()
        card_w_mm = 63.0
        card_h_mm = 88.0

        def mm_to_px(mm):
            return int((mm / 25.4) * dpi)

        paper_w_px = mm_to_px(paper_w_mm)
        paper_h_px = mm_to_px(paper_h_mm)
        card_w_px  = mm_to_px(card_w_mm)
        card_h_px  = mm_to_px(card_h_mm)
        spacing_px = mm_to_px(self.spacing_mm)

        cols = max(1, int((paper_w_px + spacing_px) // (card_w_px + spacing_px)))
        rows = max(1, int((paper_h_px + spacing_px) // (card_h_px + spacing_px)))
        cards_per_page = cols * rows

        flat_cards = self._build_flat_cards()

        pages = []
        for i in range(0, len(flat_cards), cards_per_page):
            pages.append(flat_cards[i:i + cards_per_page])

        return pages, (paper_w_px, paper_h_px), (card_w_px, card_h_px), spacing_px, cols, rows

    def render_page(self, page_cards, page_size, card_size, spacing, cols):
        page_w_px, page_h_px = page_size
        card_w_px, card_h_px = card_size

        img = QImage(page_w_px, page_h_px, QImage.Format_RGB32)
        img.fill(Qt.white)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        font = QFont("Arial", weight=QFont.Bold)
        font.setPixelSize(int(min(card_w_px, card_h_px) / 4))
        fm = QFontMetrics(font)

        outline_pen = QPen(QColor(255, 255, 255, 200))
        outline_pen.setWidth(max(2, int(min(card_w_px, card_h_px) / 100)))
        outline_pen.setJoinStyle(Qt.RoundJoin)
        fill_brush = QBrush(QColor(0, 0, 0, 150))

        for idx, filename in enumerate(page_cards):
            col = idx % cols
            row = idx // cols
            x = col * (card_w_px + spacing)
            y = row * (card_h_px + spacing)

            path_img = self.image_dir / filename
            if path_img.exists():
                pix = QPixmap(str(path_img))
                if not pix.isNull():
                    target_rect = QRectF(x, y, card_w_px, card_h_px)
                    painter.drawPixmap(target_rect, pix, QRectF(pix.rect()))

                    painter.save()
                    text = "PROXY"
                    text_rect = fm.boundingRect(text)
                    cx = target_rect.x() + (target_rect.width() - text_rect.width()) / 2.0
                    cy = target_rect.y() + (target_rect.height() + fm.ascent() - fm.descent()) / 2.0

                    proxy_path = QPainterPath()
                    proxy_path.addText(cx, cy, font, text)
                    painter.setPen(outline_pen)
                    painter.setBrush(fill_brush)
                    painter.drawPath(proxy_path)
                    painter.restore()

        painter.end()
        return img

    def update_preview(self):
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        pages, page_size, card_size, spacing, cols, rows = self.get_pages(dpi=192)

        if not pages:
            lbl = QLabel("出力するカードがありません。" if self.language == "ja" else "No cards to display.")
            lbl.setStyleSheet("color: white; padding: 20px;")
            self.preview_layout.addWidget(lbl)
            return

        for p in pages:
            img = self.render_page(p, page_size, card_size, spacing, cols)
            pix = QPixmap.fromImage(img)
            pix.setDevicePixelRatio(2.0)
            lbl = QLabel()
            lbl.setPixmap(pix)
            lbl.setStyleSheet("border: 1px solid #666; margin: 4px;")
            self.preview_layout.addWidget(lbl)

    def export_pdf(self):
        dpi = 600
        pages, page_size, card_size, spacing, cols, rows = self.get_pages(dpi=dpi)

        if not pages:
            QMessageBox.warning(self, "Warning",
                                "出力するカードがありません。" if self.language == "ja" else "No cards to export.")
            return

        if self.csv_path:
            deck_name = self.csv_path.stem
            paper_name = self.paper_combo.currentText()
            default_name = f"Proxy_{paper_name}_{deck_name}.pdf"
            default_path = str(self.csv_path.parent / default_name)
        else:
            default_path = "Proxy_Deck.pdf"

        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", default_path, "PDF Files (*.pdf)")
        if not path:
            return

        paper_w_mm, paper_h_mm = self._get_paper_mm()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            writer = QPdfWriter(path)
            writer.setResolution(dpi)

            from PyQt5.QtCore import QMarginsF
            layout = QPageLayout(
                QPageSize(QSizeF(paper_w_mm, paper_h_mm), QPageSize.Millimeter),
                QPageLayout.Portrait,
                QMarginsF(0, 0, 0, 0),
                QPageLayout.Millimeter
            )
            writer.setPageLayout(layout)

            painter = QPainter(writer)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            page_w_px, page_h_px = page_size
            card_w_px, card_h_px = card_size

            font = QFont("Arial", weight=QFont.Bold)
            font.setPixelSize(int(min(card_w_px, card_h_px) / 4))
            fm = QFontMetrics(font)

            outline_pen = QPen(QColor(255, 255, 255, 200))
            outline_pen.setWidth(max(2, int(min(card_w_px, card_h_px) / 100)))
            outline_pen.setJoinStyle(Qt.RoundJoin)
            fill_brush = QBrush(QColor(0, 0, 0, 150))

            for page_idx, page_cards in enumerate(pages):
                if page_idx > 0:
                    writer.newPage()

                for idx, filename in enumerate(page_cards):
                    col = idx % cols
                    row = idx // cols
                    x = col * (card_w_px + spacing)
                    y = row * (card_h_px + spacing)

                    img_path = self.image_dir / filename
                    if img_path.exists():
                        pix = QPixmap(str(img_path))
                        if not pix.isNull():
                            target_rect = QRectF(x, y, card_w_px, card_h_px)
                            painter.drawPixmap(target_rect, pix, QRectF(pix.rect()))

                            painter.save()
                            text = "PROXY"
                            text_rect = fm.boundingRect(text)
                            cx = target_rect.x() + (target_rect.width() - text_rect.width()) / 2.0
                            cy = target_rect.y() + (target_rect.height() + fm.ascent() - fm.descent()) / 2.0

                            proxy_path = QPainterPath()
                            proxy_path.addText(cx, cy, font, text)
                            painter.setPen(outline_pen)
                            painter.setBrush(fill_brush)
                            painter.drawPath(proxy_path)
                            painter.restore()

            painter.end()
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self, "Success",
                                    f"PDFを出力しました:\n{path}" if self.language == "ja"
                                    else f"PDF exported successfully to:\n{path}")

        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error",
                                 f"PDF出力に失敗しました:\n{e}" if self.language == "ja"
                                 else f"Failed to export PDF:\n{e}")
