from typing import List, Dict
import sys
import random
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGraphicsView, 
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem, QGraphicsRectItem,
    QMessageBox, QLabel, QMenu, QAction, QGraphicsProxyWidget,
    QScrollArea, QGridLayout, QFrame, QSizePolicy, QCheckBox, QInputDialog,
    QPlainTextEdit, QGraphicsOpacityEffect
)

from PyQt5.QtCore import Qt, QPoint, QPointF, QRectF, QSize, QTimer, QVariantAnimation, QPropertyAnimation, QEasingCurve, QDateTime, QObject, pyqtProperty, QThread, pyqtSignal, QMimeData
from PyQt5.QtGui import (
    QPixmap, QColor, QBrush, QPen, QTransform, QFont, QPainter, 
    QDrag, QPainterPath, QCursor, QIcon, QRadialGradient, QLinearGradient,
    QTextCursor
)


from PyQt5.QtWidgets import QGraphicsObject





from common_func import load_or_download_card_back, exe_dir, app_dir, get_app_icon
from gui_language import UI_TEXT, LANG_EN, LANG_JA
from simulation_window import SimulationWindow
from image_selector import ImageSelectDialog


# Constants for layout
CARD_WIDTH_LOGICAL = 100
CARD_HEIGHT_LOGICAL = 140
CARD_CORNER_RADIUS = 7
ZONE_MARGIN = 10

class ToastLabel(QLabel):
    """Temporary overlay message that fades out."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            QLabel {
                background-color: rgba(30, 30, 30, 220);
                color: #ffaa00;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 10px 18px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }
        """)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(2000)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.InQuad)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()

class CardItem(QGraphicsPixmapItem):
    @staticmethod
    def _scale_pixmap(pixmap, factor=3.0):
        if pixmap.isNull() or pixmap.height() <= 0:
            return pixmap
        hi_res_w = int(CARD_WIDTH_LOGICAL * factor)
        hi_res_h = int(CARD_HEIGHT_LOGICAL * factor)
        scaled = pixmap.scaled(
            hi_res_w, hi_res_h,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        scaled.setDevicePixelRatio(factor)
        return scaled

    def __init__(self, card_data, pixmap, back_pixmap, card_id):
        super().__init__()
        # Store original for high-quality preview
        self.pixmap_face_orig = pixmap
        # Use 3x for the scene cards (High-DPI support)
        scaled_face = CardItem._scale_pixmap(pixmap, factor=3.0)
        
        self.card_data = card_data
        self.card_id = card_id
        self.face_pixmap = scaled_face
        self.back_pixmap_orig = back_pixmap
        self.is_face_down = False
        self.is_tapped = False
        self.is_not_selectable_by_scene = False
        
        self.counters = {} # label -> count
        self.counter_hitboxes = {} # label -> QRectF (local)
        self.hovered_counter = None # label
        self.highlighted = False
        self.does_not_untap = False
        self.is_token = card_data.get("is_token") == "True"
        
        self.setFlags(QGraphicsObject.ItemIsMovable | QGraphicsObject.ItemIsSelectable | QGraphicsObject.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setTransformOriginPoint(CARD_WIDTH_LOGICAL/2, CARD_HEIGHT_LOGICAL/2)
        self.setPixmap(self.face_pixmap) # Set initial pixmap

    def hoverEnterEvent(self, event):
        if self.scene() and hasattr(self.scene(), "show_hover_preview"):
            self.scene().show_hover_preview(self)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self.scene() and hasattr(self.scene(), "hide_hover_preview"):
            self.scene().hide_hover_preview()
        
        # Clear hovered counter to hide ▲▼ GUI
        self.hovered_counter = None
        self.update()
        
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Prevent double-click (tap) when clicking on counters
        if self.hovered_counter and self.hovered_counter in self.counter_hitboxes:
            rect = self.counter_hitboxes[self.hovered_counter]
            expanded_rect = rect.adjusted(-10, -10, 10, 10)
            if expanded_rect.contains(event.pos()):
                # Do nothing (or we could trigger another hit, but usually best to just skip the tap)
                return

        if self.scene():
            zone = self.scene().get_card_zone(self)
            if zone in ["Battlefield", "Lands"]:
                self.toggle_tap()
            elif zone == "Library":
                # Only allow top card to trigger draw on double-click
                if self.flags() & QGraphicsItem.ItemIsMovable:
                    items = self.scene().cards_in_zone["Library"]
                    if items and items[-1] == self:
                        win = self.scene().test_play_window
                        if win:
                            win.draw_cards(1)
        super().mouseDoubleClickEvent(event)

    def toggle_tap(self, log=True):
        win = self.get_test_play_window()
        if win: win.save_snapshot()
        self.is_tapped = not self.is_tapped
        self.setRotation(90 if self.is_tapped else 0)
        
        if log:
            win = self.get_test_play_window()
            if win:
                name = self.card_data.get("name_ja") if win.language == "ja" else self.card_data.get("name_en")
                msg = UI_TEXT[win.language]["log_tapped"] if self.is_tapped else UI_TEXT[win.language]["log_untapped"]
                win.log_action(msg.format(name=name))

    def get_test_play_window(self):
        s = self.scene()
        if s and hasattr(s, 'test_play_window'):
            return s.test_play_window
        return None

    def flip(self, face_down=None):
        win = self.get_test_play_window()
        if win: win.save_snapshot()
        if face_down is None:
            self.is_face_down = not self.is_face_down
        else:
            self.is_face_down = face_down
        
        if self.is_face_down:
            scaled_back = CardItem._scale_pixmap(self.back_pixmap_orig)
            self.setPixmap(scaled_back)
        else:
            self.setPixmap(self.face_pixmap)

    def mousePressEvent(self, event):
        # Check if clicking on ▲▼ of a hovered counter
        if self.hovered_counter and self.hovered_counter in self.counter_hitboxes:
            rect = self.counter_hitboxes[self.hovered_counter]
            # Use the same expansion as hoverMoveEvent to ensure arrows are clickable
            expanded_rect = rect.adjusted(-10, -10, 10, 10)
            local_pos = event.pos()
            if expanded_rect.contains(local_pos):
                # Upper half (of expanded rect) = increment, Lower half = decrement
                if local_pos.y() < expanded_rect.center().y():
                    self.add_counter(self.hovered_counter, 1)
                else:
                    self.add_counter(self.hovered_counter, -1)
                return # Consume event

        # Only bring to front and allow interaction if movable 
        # (Prevents non-top Library cards from jumping to top)
        if self.flags() & QGraphicsItem.ItemIsMovable:
            self.setZValue(100)
            # Hide preview immediately on press to avoid blockage during drag
            if self.scene() and hasattr(self.scene(), "hide_hover_preview"):
                self.scene().hide_hover_preview()
            super().mousePressEvent(event)
        else:
            # If not movable, don't consume the event or change ZValue
            # This allows clicks to potentially pass through or just be ignored
            event.ignore()

    def hoverMoveEvent(self, event):
        pos = event.pos()
        found = None
        for label, rect in self.counter_hitboxes.items():
            # Expand rect slightly to make hit area for ▲▼ more forgiving
            expanded_rect = rect.adjusted(-10, -10, 10, 10) 
            if expanded_rect.contains(pos):
                found = label
                break
        
        if found != self.hovered_counter:
            self.hovered_counter = found
            self.update() # Redraw to show/hide ▲▼
        super().hoverMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            # If multiple cards are selected, handle drop for all of them
            selected_items = scene.selectedItems()
            if len(selected_items) > 1:
                for item in selected_items:
                    if isinstance(item, CardItem):
                        scene.handle_card_drop(item)
            else:
                scene.handle_card_drop(self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            # Clamp position within scene boundaries
            new_pos = value
            rect = self.scene().sceneRect()
            # Card size is 100x140 logical
            card_w = CARD_WIDTH_LOGICAL
            card_h = CARD_HEIGHT_LOGICAL
            
            # Rotation can affect bounding box, but for simple translation clamping 
            # we usually use the top-left pos.
            # If tapped (90 deg), the visual box changes, but pos is still the same pivot point usually.
            # Here we just clamp the logical rect.
            
            if new_pos.x() < rect.left():
                new_pos.setX(rect.left())
            elif new_pos.x() + card_w > rect.right():
                new_pos.setX(rect.right() - card_w)
                
            if new_pos.y() < rect.top():
                new_pos.setY(rect.top())
            elif new_pos.y() + card_h > rect.bottom():
                new_pos.setY(rect.bottom() - card_h)
                
            return new_pos
            
        return super().itemChange(change, value)

    def set_face_down(self, down: bool):
        self.is_face_down = down
        if down:
            scaled_back = CardItem._scale_pixmap(self.back_pixmap_orig)
            self.setPixmap(scaled_back)
        else:
            self.setPixmap(self.face_pixmap)
        self.setTransformOriginPoint(self.boundingRect().center())

    def add_counter(self, label, delta):
        win = self.get_test_play_window()
        if win: win.save_snapshot()
        curr = self.counters.get(label, 0)
        self.counters[label] = max(0, curr + delta)
        added = self.counters[label] - curr
        
        win = self.get_test_play_window()
        name = "Card"
        lang = "en"
        if win:
            lang = win.language
            name = self.card_data.get("name_ja") if lang == "ja" else self.card_data.get("name_en")
            if added != 0:
                win.log_action(UI_TEXT[lang]["log_added_counter"].format(
                    name=name, label=label, n=added, total=self.counters[label]
                ))

        # Rule 704.5q: +1/+1 and -1/-1 counters cancel each other out
        if label in ["+1/+1", "-1/-1"]:
            p1 = self.counters.get("+1/+1", 0)
            m1 = self.counters.get("-1/-1", 0)
            if p1 > 0 and m1 > 0:
                cancel = min(p1, m1)
                self.counters["+1/+1"] = p1 - cancel
                self.counters["-1/-1"] = m1 - cancel
                if win:
                    win.log_action(UI_TEXT[lang]["log_annihilated"].format(name=name))
        
        # Cleanup zero/negative counters
        to_del = [k for k, v in self.counters.items() if v <= 0]
        for k in to_del:
            del self.counters[k]
            
        self.update()

    def paint(self, painter, option, widget):
        # 1. Draw the card image with rounded corners
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(self.boundingRect(), CARD_CORNER_RADIUS, CARD_CORNER_RADIUS)
        painter.setClipPath(path)
        super().paint(painter, option, widget)
        painter.restore()

        # Highlight for random discard animation
        if self.highlighted:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#ffaa00"), 5)) # Bold orange highlight
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.boundingRect().adjusted(2, 2, -2, -2), CARD_CORNER_RADIUS, CARD_CORNER_RADIUS)
            painter.restore()
        
        # 2. Draw Indicators (Reset clip to allow drawing over the image)
        painter.setClipping(False)

        # Tapped/Untap restriction indicator
        if self.does_not_untap:
            win = self.get_test_play_window()
            icon_rect = QRectF(CARD_WIDTH_LOGICAL - 22, 5, 18, 18)
            if win and not win.untap_pixmap.isNull():
                painter.drawPixmap(icon_rect.toRect(), win.untap_pixmap)
            
            # Draw Prohibition Mark (Prohibition symbol)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#ff0000"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(icon_rect)
            # Diagonal line
            painter.drawLine(
                int(icon_rect.left() + 3), int(icon_rect.top() + 3),
                int(icon_rect.right() - 3), int(icon_rect.bottom() - 3)
            )
        
        if self.counters:
            self.counter_hitboxes = {}
            y_off = 10
            font = QFont("Arial", 9, QFont.Bold)
            painter.setFont(font)
            
            for label, count in self.counters.items():
                if count <= 0: continue
                
                # Style Selection
                if label == "+1/+1":
                    c1, c2, t_color = QColor("#FFD700"), QColor("#B8860B"), Qt.black
                elif label == "-1/-1":
                    c1, c2, t_color = QColor("#9932CC"), QColor("#4B0082"), Qt.white
                elif label == UI_TEXT[LANG_EN]["loyalty"] or label == UI_TEXT[LANG_JA]["loyalty"]:
                    c1, c2, t_color = QColor("#FF4500"), QColor("#8B0000"), Qt.white
                elif label == UI_TEXT[LANG_EN]["lore_counter"] or label == UI_TEXT[LANG_JA]["lore_counter"]:
                    # Lore: Parchment/Beige style
                    c1, c2, t_color = QColor("#F5DEB3"), QColor("#D2B48C"), Qt.black
                else:
                    c1, c2, t_color = QColor("#D3D3D3"), QColor("#808080"), Qt.black

                cx, cy = 22, y_off + 15
                radius = 16
                
                # Custom shape for Loyalty (Shield) or Lore (Scroll)
                is_loyalty = (label == UI_TEXT[LANG_EN]["loyalty"] or label == UI_TEXT[LANG_JA]["loyalty"])
                is_lore = (label == UI_TEXT[LANG_EN]["lore_counter"] or label == UI_TEXT[LANG_JA]["lore_counter"])
                
                # Shadow
                painter.setBrush(QColor(0, 0, 0, 80))
                painter.setPen(Qt.NoPen)
                if is_loyalty:
                    # Simple pentagon/shield shape shadow
                    shadow_path = QPainterPath()
                    shadow_path.moveTo(cx - radius + 2, cy - radius/2 + 2)
                    shadow_path.lineTo(cx + 2, cy - radius + 2)
                    shadow_path.lineTo(cx + radius + 2, cy - radius/2 + 2)
                    shadow_path.lineTo(cx + radius + 2, cy + radius/2 + 2)
                    shadow_path.lineTo(cx + 2, cy + radius + 2)
                    shadow_path.lineTo(cx - radius + 2, cy + radius/2 + 2)
                    shadow_path.closeSubpath()
                    painter.drawPath(shadow_path)
                elif is_lore:
                    # Circular scroll/parchment shadow
                    painter.drawEllipse(int(cx - radius + 2), int(cy - radius/2 + 2), int(radius*2), int(radius + 2))
                else:
                    painter.drawEllipse(cx - radius + 2, cy - radius + 2, radius*2, radius*2)
                
                # Main Shape
                grad = QRadialGradient(cx - 4, cy - 4, radius * 1.5)
                grad.setColorAt(0, c1)
                grad.setColorAt(1, c2)
                painter.setBrush(grad)
                painter.setPen(QPen(Qt.black, 0.5))
                
                if is_loyalty:
                    shape_path = QPainterPath()
                    shape_path.moveTo(cx - radius, cy - radius/2)
                    shape_path.lineTo(cx, cy - radius)
                    shape_path.lineTo(cx + radius, cy - radius/2)
                    shape_path.lineTo(cx + radius, cy + radius/2)
                    shape_path.lineTo(cx, cy + radius)
                    shape_path.lineTo(cx - radius, cy + radius/2)
                    shape_path.closeSubpath()
                    painter.drawPath(shape_path)
                elif is_lore:
                    # Draw a slightly oval "scroll" shape (horizontal-ish)
                    painter.drawRoundedRect(QRectF(cx - radius, cy - radius*0.7, radius*2, radius*1.4), 4, 4)
                else:
                    painter.drawEllipse(cx - radius, cy - radius, radius*2, radius*2)
                
                # Hitbox tracking
                self.counter_hitboxes[label] = QRectF(cx - radius, cy - radius, radius*2, radius*2)

                # Shine
                painter.setBrush(QColor(255, 255, 255, 60))
                painter.setPen(Qt.NoPen)
                if is_loyalty:
                   painter.drawEllipse(int(cx - radius/2), int(cy - radius + 3), int(radius), int(radius/2))
                else:
                   painter.drawEllipse(cx - radius + 3, cy - radius + 3, (radius-4)*2, (radius-4)*2)

                # Text
                painter.setPen(t_color)
                txt = str(count)
                
                # Draw Label (Small, Top)
                painter.setFont(QFont("Arial", 6, QFont.Bold))
                lr = painter.fontMetrics().boundingRect(label)
                painter.drawText(int(cx - lr.width()/2), int(cy - 2), label)
                
                # Draw Count (Larger, Bottom)
                painter.setFont(QFont("Arial", 10, QFont.Bold))
                cr = painter.fontMetrics().boundingRect(txt)
                painter.drawText(int(cx - cr.width()/2), int(cy + 12), txt)
                
                # Draw ▲/▼ if hovered
                if self.hovered_counter == label:
                    painter.setPen(Qt.white)
                    painter.setFont(QFont("Arial", 10, QFont.Bold))
                    # Draw ▲ at the top and ▼ at the bottom of the counter
                    painter.drawText(int(cx - 5), int(cy - radius + 6), "▲")
                    painter.drawText(int(cx - 5), int(cy + radius + 1), "▼")

                painter.setFont(font) # Restore
                y_off += 36

    def contextMenuEvent(self, event):
        scene = self.scene()
        if not scene: return
        window = scene.test_play_window
        if not window: return
        lang = window.language
        zone = scene.get_card_zone(self)
        
        menu = QMenu()
        
        if zone == "Library":
            # Library actions are mostly for the whole library, 
            # but user wants them on right-click of a card (usually the top one)
            act_draw_7 = menu.addAction(UI_TEXT[lang]["draw_7"])
            act_draw_x = menu.addAction(UI_TEXT[lang]["draw_x"])
            act_draw_bottom = menu.addAction(UI_TEXT[lang]["draw_bottom"])
            
            action = menu.exec_(event.screenPos())
            if action == act_draw_7: window.draw_cards(7)
            elif action == act_draw_x: window.draw_x_cards()
            elif action == act_draw_bottom: window.draw_bottom_card()
            
        elif zone == "Hand":
            act_discard_all = menu.addAction(UI_TEXT[lang]["discard_hand"])
            
            cards_in_hand = window.scene.cards_in_zone.get("Hand", [])
            act_discard_random = menu.addAction(UI_TEXT[lang]["discard_random"])
            act_discard_random.setEnabled(len(cards_in_hand) > 0)
            
            menu.addSeparator()
            act_top = menu.addAction(UI_TEXT[lang]["put_on_top"])
            act_bottom = menu.addAction(UI_TEXT[lang]["put_on_bottom"])
            
            action = menu.exec_(event.screenPos())
            if action == act_discard_all: window.discard_all_hand()
            elif action == act_discard_random: window.discard_random_hand()
            elif action == act_top: window.put_card_on_top(self)
            elif action == act_bottom: window.put_card_on_bottom(self)
            
        elif zone in ["Battlefield", "Lands"]:
            act_p1 = menu.addAction("+1/+1 Counter")
            act_m1 = menu.addAction("-1/-1 Counter")
            act_loyalty = menu.addAction(UI_TEXT[lang]["loyalty"])
            act_lore = menu.addAction(UI_TEXT[lang]["lore_counter"])
            act_other = menu.addAction(UI_TEXT[lang]["add_counter"] + " (Other)")
            menu.addSeparator()
            
            flip_label = UI_TEXT[lang]["flip_face_up"] if self.is_face_down else UI_TEXT[lang]["flip_face_down"]
            act_flip = menu.addAction(flip_label)
            
            untap_label = UI_TEXT[lang]["toggle_no_untap"]
            if self.does_not_untap: untap_label += " [ON]"
            act_untap = menu.addAction(untap_label)
            
            if self.is_token:
                menu.addSeparator()
                act_delete = menu.addAction(UI_TEXT[lang]["delete_token"])
            else:
                act_delete = None

            action = menu.exec_(event.screenPos())
            if action == act_p1: self.add_counter("+1/+1", 1)
            elif action == act_m1: self.add_counter("-1/-1", 1)
            elif action == act_loyalty: self.add_counter(UI_TEXT[lang]["loyalty"], 1)
            elif action == act_lore: self.add_counter(UI_TEXT[lang]["lore_counter"], 1)
            elif action == act_other: self.add_other_counter_dialog()
            elif action == act_flip: self.flip()
            elif action == act_untap:
                self.does_not_untap = not self.does_not_untap
                self.update()
            elif act_delete and action == act_delete:
                window.delete_card(self)

        elif zone == "Graveyard":
            act_exile_all = menu.addAction(UI_TEXT[lang]["exile_all_graveyard"])
            act_return_all = menu.addAction(UI_TEXT[lang]["return_all_to_library"])
            
            action = menu.exec_(event.screenPos())
            if action == act_exile_all: window.exile_all_graveyard()
            elif action == act_return_all: window.return_all_to_library("Graveyard")
        
        elif zone == "Exile":
            act_return_all = menu.addAction(UI_TEXT[lang]["return_all_to_library"])
            action = menu.exec_(event.screenPos())
            if action == act_return_all: window.return_all_to_library("Exile")

    def add_other_counter_dialog(self):
        text, ok = QInputDialog.getText(None, "Counter", "Enter counter name:")
        if ok and text:
            self.add_counter(text, 1)


    # def paint(self, painter, option, widget):
    #    # print(f"DEBUG: CardItem paint called for {self.card_id}")
    #    super().paint(painter, option, widget)
    #    # Debug border
    #    painter.setPen(QPen(Qt.yellow, 20))
    #    painter.drawRect(self.boundingRect())






class ZoneItem(QGraphicsRectItem):
    def __init__(self, name, rect, color, label_text):
        super().__init__(rect)
        self.name = name
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(-100) # Background
        
        # Label
        self.text_item = None
        self.set_label(label_text)

    def set_label(self, text):
        if self.text_item:
            if self.scene():
                self.scene().removeItem(self.text_item)
            self.text_item = None
            
        # Simple text item
        # We can't easily add child QGraphicsTextItem to RectItem and have it render cleanly 
        # without managing transforms, so we might just let Scene handle it or add as child.
        pass # Logic handled in Scene for simplicity or implemented here

class HoverPreviewItem(QGraphicsPixmapItem):
    """Large preview image that appears on hover."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setZValue(1000) # Always on top
        self.setEnabled(False) # Do not block mouse
        self.hide()

    def set_card(self, pixmap):
        # pixmap here should be the original high-res pixmap from CardItem
        if pixmap.isNull(): return
        
        # Target logical size: 312x437 (80% of previous 390x546)
        logical_w = 312
        logical_h = 437
        
        # Scale to 2x for High DPI sharpness
        raw_w = logical_w * 2
        raw_h = logical_h * 2
        
        scaled = pixmap.scaled(raw_w, raw_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(2.0)
        self.setPixmap(scaled)
        self.show()

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        # Radius for larger preview: (390/100) * 7 = 27.3. Let's use 28 or so. 
        # Or if user prefers subtle, maybe keep it smaller. 
        # 12-15 looks good usually.
        # Proportionally scaled radius: (312/100) * 7 = 21.84
        path.addRoundedRect(self.boundingRect(), 22, 22)
        painter.setClipPath(path)
        super().paint(painter, option, widget)

class TestPlayScene(QGraphicsScene):

    def __init__(self, width, height, parent=None):
        super().__init__(0, 0, width, height, parent)
        self.test_play_window = parent
        self.setBackgroundBrush(QColor("#2b2b2b"))

        
        # Zone Rects
        # Right Column for zones: Widen to allow buttons on right
        # width = 1600 approx
        right_col_x = width - 400 # 1600 - 400 = 1200
        col_w = 190 # 1.35x of 140
        
        self.zones = {}

        
        # Command (Top Right)
        self.zones["Command"] = QRectF(right_col_x, 20, col_w, 180)
        
        # Exile (Below Command)
        self.zones["Exile"] = QRectF(right_col_x, 220, col_w, 180)
        
        # Graveyard (Below Exile)
        self.zones["Graveyard"] = QRectF(right_col_x, 420, col_w, 180)
        
        # Library (Below Graveyard)
        self.zones["Library"] = QRectF(right_col_x, 620, col_w, 180)
        
        # Hand (Bottom, Left of Right Column)
        self.zones["Hand"] = QRectF(20, height - 180, right_col_x - 40, 160)
        
        # Lands (Bottom half of left area, above Hand)
        lands_h = 160
        lands_y = height - 180 - lands_h - 10  # 10px gap above Hand
        self.zones["Lands"] = QRectF(20, lands_y, right_col_x - 40, lands_h)
        
        # Battlefield (The rest, above Lands)
        bf_h = lands_y - 30  # 10px gap below top
        self.zones["Battlefield"] = QRectF(20, 20, right_col_x - 40, bf_h)


        # Zone Labels Storage
        self.zone_labels = {}
        
        def get_text(key):
            lang = self.test_play_window.language
            return UI_TEXT.get(lang, UI_TEXT["ja"]).get(key, key)

        # Calm, muted color palette
        self.add_zone("Command",    QColor("#3d5a6e"), get_text("zone_command"))
        self.add_zone("Exile",      QColor("#5a5a5a"), get_text("zone_exile"))
        self.add_zone("Graveyard",  QColor("#3a3a3a"), get_text("zone_graveyard"))
        self.add_zone("Library",    QColor("#2e4057"), get_text("zone_library"))
        self.add_zone("Hand",       QColor("#2e5744"), get_text("zone_hand"))
        self.add_zone("Lands",      QColor("#4a5e3e"), get_text("zone_lands"))
        self.add_zone("Battlefield",QColor("#3e3e3e"), get_text("zone_battlefield"))

        # Logic State
        self.cards_in_zone = {
            "Command": [], "Exile": [], "Graveyard": [], 
            "Library": [], "Hand": [], "Lands": [], "Battlefield": []
        }
        
        # Hover Preview
        self.hover_preview = HoverPreviewItem()
        self.addItem(self.hover_preview)



    def add_zone(self, name, color, label):
        rect = self.zones[name]
        item = ZoneItem(name, rect, color, label)
        self.addItem(item)
        
        # Zone Label
        text = self.addSimpleText(label)
        text.setBrush(QBrush(QColor(200, 200, 200, 180)))  # Semi-transparent white
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        text.setFont(font)
        text.setPos(rect.x() + 5, rect.y() + 3)
        text.setZValue(-99)  # Just above zone bg
        self.zone_labels[name] = text

    def retranslate_ui(self):
        """V22.0: Update all zone labels."""
        def get_text(key):
            lang = self.test_play_window.language
            return UI_TEXT.get(lang, UI_TEXT["ja"]).get(key, key)

        mapping = {
            "Command": "zone_command",
            "Exile": "zone_exile",
            "Graveyard": "zone_graveyard",
            "Library": "zone_library",
            "Hand": "zone_hand",
            "Lands": "zone_lands",
            "Battlefield": "zone_battlefield"
        }
        for zone_name, text_item in self.zone_labels.items():
            key = mapping.get(zone_name)
            if key:
                text_item.setText(get_text(key))

    def get_card_zone(self, card_item):
        for z, items in self.cards_in_zone.items():
            if card_item in items:
                return z
        return None

    def show_hover_preview(self, card_item):
        if card_item.is_face_down: return
        
        # Don't show if dragging (any mouse button pressed)
        from PyQt5.QtWidgets import QApplication
        if QApplication.mouseButtons() & Qt.LeftButton:
            return
        
        # Position preview near the card or at a fixed spot
        card_pos = card_item.scenePos()
        preview_w = 312
        
        # Default: show on the right of the card
        px = card_pos.x() + CARD_WIDTH_LOGICAL + 20
        if px + preview_w > self.width():
            # Show on left instead
            px = card_pos.x() - preview_w - 20
            
        py = card_pos.y() - 50
        # Clamp Y
        self.hover_preview.hide()
        py = card_pos.y() - 50
        # Clamp Y
        py = max(10, min(py, self.height() - 450)) # Adjusted for 437px height
        
        self.hover_preview.setPos(px, py)
        self.hover_preview.set_card(card_item.pixmap_face_orig)

    def hide_hover_preview(self):
        self.hover_preview.hide()


    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-card-instance-id"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-card-instance-id"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-card-instance-id"):
            instance_id = event.mimeData().data("application/x-card-instance-id").data().decode()
            
            # Find the card item in the scene
            target_card = None
            # The scene's parent is the TestPlayWindow
            window = self.parent()
            if window and hasattr(window, "card_items"):
                for item in window.card_items:
                    if str(id(item)) == instance_id:
                        target_card = item
                        break

            
            if target_card:
                # Ensure it's visible (it might have been hidden for token drag)
                target_card.setVisible(True)
                # Get scene drop position
                pos = event.scenePos()
                # Move card to drop position (center it)
                target_card.setPos(pos.x() - CARD_WIDTH_LOGICAL/2, pos.y() - CARD_HEIGHT_LOGICAL/2)
                # Apply drop logic (z-index, zone check, etc)
                self.handle_card_drop(target_card)
                event.acceptProposedAction()
        else:
            super().dropEvent(event)



    def handle_card_drop(self, card_item):
        # Find which zone contains center of card
        center = card_item.mapToScene(card_item.boundingRect().center())
        
        target_zone = "Battlefield" # Default
        
        for name, rect in self.zones.items():
            if rect.contains(center):
                target_zone = name
                break
        
        # Auto-untap if moving to a non-permanent zone
        if target_zone in ["Library", "Graveyard", "Exile", "Command"]:
            card_item.is_tapped = False
            card_item.setRotation(0)

        # Find current zone
        current_zone = self.get_card_zone(card_item)
        
        # If same zone, behavior depends on zone type
        if target_zone == current_zone:
            if target_zone == "Hand":
                self.arrange_hand()
            elif target_zone == "Lands":
                self.arrange_lands()
            elif target_zone == "Battlefield":
                pass # Stay where dropped
            else:
                # Stacks (Library, GY, Exile): Re-order to top
                self.move_card_to_zone(card_item, target_zone)
        else:
            # Different zone: New placement
            self.move_card_to_zone(card_item, target_zone, log=True)




    def move_card_to_zone(self, card_item, zone_name, log=False):
        win = self.test_play_window
        if win: win.save_snapshot()
        
        # Remove from old zone list
        old_zone = None
        for z in self.cards_in_zone:
            if card_item in self.cards_in_zone[z]:
                self.cards_in_zone[z].remove(card_item)
                old_zone = z
                break
        
        # Rearrange old zone to update stack states (e.g. enabling new top card of Library)
        if old_zone == "Hand":
            self.arrange_hand()
        elif old_zone in ["Library", "Graveyard", "Exile", "Command"]:
            self.arrange_stack(old_zone)
        elif old_zone == "Lands":
            self.arrange_lands()
        
        self.cards_in_zone[zone_name].append(card_item)
        
        if log:
            win = self.test_play_window
            lang = win.language
            name = card_item.card_data.get("name_ja") if lang == "ja" else card_item.card_data.get("name_en")
            
            # Specialized log for newly generated tokens
            if old_zone is None and card_item.is_token:
                win.log_action(UI_TEXT[lang]["log_token_generated"].format(
                    name=name, dst=zone_name
                ))
            else:
                win.log_action(UI_TEXT[lang]["log_moved"].format(
                    name=name, src=old_zone or "???", dst=zone_name
                ))

        # Ensure card is draggable and selectable by default (Library stack will override this)
        card_item.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        card_item.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        
        # Zone specific behavior
        if zone_name == "Library":
            card_item.set_face_down(True)
            self.arrange_stack(zone_name)
        elif zone_name == "Hand":
            card_item.set_face_down(False)
            self.arrange_hand()
        elif zone_name in ["Graveyard", "Exile", "Command"]:
            card_item.set_face_down(False) 
            self.arrange_stack(zone_name)
        elif zone_name == "Lands":
            if card_item.is_face_down:
                card_item.set_face_down(False)
            self.arrange_lands()
        else: # Battlefield
            # Free placement, do not auto arrange
            if card_item.is_face_down:
                card_item.set_face_down(False)

    def arrange_stack(self, zone_name):
        rect = self.zones[zone_name]
        items = self.cards_in_zone[zone_name]
        
        # Stack items at center of zone
        x = rect.center().x() - (CARD_WIDTH_LOGICAL / 2)
        y = rect.center().y() - (CARD_HEIGHT_LOGICAL / 2)
        
        total = len(items)
        for i, item in enumerate(items):
            # Use larger horizontal offset for Command zone so multiple commanders/companions are visible
            if zone_name == "Command":
                item.setPos(x + i*25, y)
                item.setZValue(total - i)
            elif zone_name == "Library":
                # Offset to look like a physical deck (0.25px for subtle 3D effect)
                item.setPos(x + i*0.25, y - i*0.25)
                item.setZValue(i)
            else:
                # Perfect overlap for Graveyard, Exile as requested
                item.setPos(x, y) 
                item.setZValue(i)
            item.setRotation(0) # Reset rotation in stack
            item.is_tapped = False # Ensure untapped in stack
            
            # Special rule for Library: only top card (last in list) is draggable/selectable
            if zone_name == "Library":
                is_top = (i == total - 1)
                item.setFlag(QGraphicsItem.ItemIsMovable, is_top)
                item.setFlag(QGraphicsItem.ItemIsSelectable, is_top)
                if not is_top:
                    item.setSelected(False) # Force deselect for middle cards
                
                # Handling "Always Show Top"
                win = self.test_play_window
                if win and hasattr(win, 'cb_show_top'):
                    show_top = win.cb_show_top.isChecked()
                    if is_top:
                        item.set_face_down(not show_top)
                    else:
                        item.set_face_down(True)
            else:
                # Other stacks (Graveyard/Exile) let you pick any card
                item.setFlag(QGraphicsItem.ItemIsMovable, True)



    def arrange_hand(self):
        rect = self.zones["Hand"]
        items = self.cards_in_zone["Hand"]
        count = len(items)
        if count == 0: return
        
        # Center horizontally
        total_w = count * CARD_WIDTH_LOGICAL
        if total_w > rect.width() - 80:
            # Overlap
            offset = (rect.width() - 80 - CARD_WIDTH_LOGICAL) / (count - 1)
        else:
            offset = CARD_WIDTH_LOGICAL + 5
            
        start_x = rect.x() + 80  # Offset to not cover label
        y = rect.y() + 10
        
        
        for i, item in enumerate(items):
            x_pos = start_x + i * offset
            item.setPos(x_pos, y)
            item.setZValue(i + 100) # Ensure on top
            item.setRotation(0)

    def arrange_lands(self):
        rect = self.zones["Lands"]
        items = self.cards_in_zone["Lands"]
        count = len(items)
        if count == 0: return
        
        total_w = count * CARD_WIDTH_LOGICAL
        if total_w > rect.width() - 80:
            offset = (rect.width() - 80 - CARD_WIDTH_LOGICAL) / max(count - 1, 1)
        else:
            offset = CARD_WIDTH_LOGICAL + 5
            
        start_x = rect.x() + 80  # Offset to not cover label
        y = rect.y() + 10
        
        for i, item in enumerate(items):
            x_pos = start_x + i * offset
            item.setPos(x_pos, y)
            item.setZValue(i + 50)






class CardIconWidget(QWidget):
    """Small widget for Library Viewer grid that supports dragging with rounded corners."""
    def __init__(self, card_item, is_draggable=True, parent=None):
        super().__init__(parent)
        self.card_item = card_item
        self.is_draggable = is_draggable
        
        self.setFixedSize(110, 154)
        self.setToolTip(card_item.card_data.get("name_en", card_item.card_id))
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # High-res pixmap for display in grid
        pix = card_item.face_pixmap
        self.display_pix = None
        if not pix.isNull():
            # Scale for display: 110x154 logical -> 220x308 raw
            self.display_pix = pix.scaled(220, 308, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.display_pix.setDevicePixelRatio(2.0)
        
        self.drag_start_pos = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        # Adjusted radius: original 7 * 0.8 = 5.6. Using 6.0 as requested.
        path.addRoundedRect(QRectF(self.rect()), 6, 6)
        painter.setClipPath(path)
        
        if self.display_pix:
            painter.drawPixmap(self.rect(), self.display_pix)
        else:
            painter.fillRect(self.rect(), QColor("#333"))
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "Img Error")




    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.is_draggable: 
            return
        if not (event.buttons() & Qt.LeftButton) or not self.drag_start_pos:
            return

        if (event.pos() - self.drag_start_pos).manhattanLength() < 10:
            return

        # Start Drag
        drag = QDrag(self)
        mime = QMimeData()
        # Use object ID as unique instance ID
        instance_id = str(id(self.card_item))
        mime.setData("application/x-card-instance-id", instance_id.encode())
        drag.setMimeData(mime)
        
        # Cursor feedback
        if self.display_pix:
            drag.setPixmap(self.display_pix)
            drag.setHotSpot(self.drag_start_pos)
        
        # Hide parent popup immediately so we can see the scene
        parent_popup = self.window()
        if isinstance(parent_popup, ZoneViewerPopup) or isinstance(parent_popup, TokenViewerPopup):
            parent_popup.hide()

        drag.exec_(Qt.MoveAction)


class TokenIconWidget(QWidget):
    """Small widget for Token Viewer that supports dragging to spawn in scene."""
    def __init__(self, card_data, test_play_window, parent=None):
        super().__init__(parent)
        self.card_data = card_data
        self.test_play_window = test_play_window
        
        self.setFixedSize(130, 182)
        self.setToolTip(card_data.get("name_ja") if test_play_window.language == "ja" else card_data.get("name_en"))
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Load Image
        self.pix = None
        if test_play_window.image_root:
            fname = card_data.get("card_file_front")
            if fname:
                p = test_play_window.image_root / fname
                if p.exists():
                    self.pix = QPixmap(str(p)).scaled(260, 364, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.pix.setDevicePixelRatio(2.0)
        
        self.drag_start_pos = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        painter.setClipPath(path)
        
        if self.pix:
            painter.drawPixmap(self.rect(), self.pix)
        else:
            painter.fillRect(self.rect(), QColor("#333"))
            painter.setPen(Qt.white)
            name = self.card_data.get("name_ja") if self.test_play_window.language == "ja" else self.card_data.get("name_en")
            painter.drawText(self.rect(), Qt.AlignCenter, name or "No Img")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or not self.drag_start_pos:
            return

        if (event.pos() - self.drag_start_pos).manhattanLength() < 10:
            return

        # Start Drag: Spawn the actual item in the scene first
        item = self.test_play_window.spawn_token(self.card_data, auto_place=False)
        
        drag = QDrag(self)
        mime = QMimeData()
        instance_id = str(id(item))
        mime.setData("application/x-card-instance-id", instance_id.encode())
        drag.setMimeData(mime)
        
        if self.pix:
            drag.setPixmap(self.pix)
            drag.setHotSpot(self.drag_start_pos)
        
        # Hide parent popup
        parent_popup = self.window()
        if isinstance(parent_popup, TokenViewerPopup):
            parent_popup.hide()

        result = drag.exec_(Qt.MoveAction)
        
        # If drag was cancelled or didn't drop on scene, cleanup the orphan item
        if result == Qt.IgnoreAction:
            if item in self.test_play_window.card_items:
                self.test_play_window.card_items.remove(item)
                self.test_play_window.scene.removeItem(item)

class SyncTokensWorker(QThread):
    progress = pyqtSignal(int, int, str, bool) # current, total, name, is_cached
    finished = pyqtSignal(list) # all new token rows found
    error = pyqtSignal(str)

    def __init__(self, cards, image_dir, language):
        super().__init__()
        self.cards = cards
        self.image_dir = image_dir
        self.language = language

    def run(self):
        try:
            import generator
            import time
            new_tokens = []
            # Only scan non-token cards
            main_cards = [c for c in self.cards if str(c.get("is_token")) != "True"]
            total = len(main_cards)
            
            for i, card in enumerate(main_cards):
                name = card.get("name_en")
                if not name: continue
                self.progress.emit(i+1, total, name, False) # Assume miss until confirmed
                
                # V19.8: Explicitly pass the English card name for maximum token discovery fidelity.
                rows, is_cached = generator.create_card_row(name, self.image_dir, self.language, name_en=name)
                
                # Re-emit actual status
                self.progress.emit(i+1, total, name, is_cached)
                for r in rows:
                    if str(r.get("is_token")) == "True":
                        # Deduplicate
                        if not any(t["name_en"] == r["name_en"] for t in new_tokens) and \
                           not any(t["name_en"] == r["name_en"] for t in self.cards):
                            new_tokens.append(r)
                if not is_cached:
                    time.sleep(0.1)
                
            self.finished.emit(new_tokens)
        except Exception as e:
            self.error.emit(str(e))

class TokenViewerPopup(QFrame):
    def __init__(self, test_play_window, parent=None):
        super().__init__(parent)
        self.test_play_window = test_play_window
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(900, 750)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 2px solid #555;
                border-radius: 8px;
            }
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:disabled {
                color: #777;
                background-color: #2a2a2a;
            }
            QMessageBox {
                background-color: #2b2b2b;
                border: 2px solid #555;
            }
            QMessageBox QLabel {
                color: white;
            }
        """)

        layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        self.lbl_title = QLabel(UI_TEXT[test_play_window.language]["tokens"])
        self.lbl_title.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        header.addWidget(self.lbl_title)
        header.addStretch()
        self.btn_sync = QPushButton(UI_TEXT[test_play_window.language]["generate_token_list"])
        self.btn_sync.clicked.connect(self.on_sync_tokens_clicked)
        header.addWidget(self.btn_sync)
        
        layout.addLayout(header)

        # Grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(10)
        scroll.setWidget(self.grid_widget)
        layout.addWidget(scroll)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.hide)
        footer.addWidget(btn_close)
        self.btn_close = btn_close
        layout.addLayout(footer)

    def retranslate_ui(self):
        """Update strings from UI_TEXT."""
        lang = self.test_play_window.language
        def get_text(key):
            return UI_TEXT.get(lang, UI_TEXT["ja"]).get(key, key)
        
        self.lbl_title.setText(get_text("tokens"))
        self.btn_sync.setText(get_text("sync_tokens"))
        self.btn_close.setText(get_text("close"))

    def populate(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
            
        token_cards = [c for c in self.test_play_window.deck_list if str(c.get("is_token")) == "True"]
        if not token_cards:
            lbl = QLabel("No tokens found. Click 'Generate Token List' to scan.")
            lbl.setStyleSheet("color: #888; font-style: italic;")
            self.grid_layout.addWidget(lbl, 0, 0)
            return

        cols = 6
        for i, card_data in enumerate(token_cards):
            row, col = divmod(i, cols)
            w = TokenIconWidget(card_data, self.test_play_window)
            self.grid_layout.addWidget(w, row, col)

    def on_sync_tokens_clicked(self):
        self.btn_sync.setEnabled(False)
        self.btn_sync.setText("Scanning...")
        
        self.worker = SyncTokensWorker(self.test_play_window.deck_list, self.test_play_window.image_root, self.test_play_window.language)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_sync_finished)
        self.worker.error.connect(self.on_sync_error)
        self.worker.start()

    def update_progress(self, curr, total, name, is_cached):
        self.btn_sync.setText(f"Scanning {curr}/{total} - {name}")
        if not is_cached:
            self.btn_sync.setStyleSheet("QPushButton { color: red; font-weight: bold; text-align: left; }")
        else:
            self.btn_sync.setStyleSheet("QPushButton { text-align: left; }")

    def on_sync_finished(self, new_tokens):
        self.btn_sync.setEnabled(True)
        self.btn_sync.setText(UI_TEXT[self.test_play_window.language]["generate_token_list"])
        
        if new_tokens:
            self.test_play_window.deck_list.extend(new_tokens)
            # Update CSV if possible
            self.test_play_window.save_deck_csv()
            self.populate()
            QMessageBox.information(self, "Sync", f"Added {len(new_tokens)} tokens.")
        else:
            QMessageBox.information(self, "Sync", "All tokens are up to date.")

    def on_sync_error(self, err):
        self.btn_sync.setEnabled(True)
        self.btn_sync.setText(UI_TEXT[self.test_play_window.language]["generate_token_list"])
        QMessageBox.warning(self, "Error", err)

    def show_at(self, pos):
        # Position centered but clamp to screen
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        
        target_x = pos.x() - self.width() // 2
        target_y = pos.y() - self.height() // 2
        
        # Clamp X
        if target_x < screen.left(): target_x = screen.left()
        if target_x + self.width() > screen.right(): target_x = screen.right() - self.width()
        
        # Clamp Y
        if target_y < screen.top(): target_y = screen.top()
        if target_y + self.height() > screen.bottom(): target_y = screen.bottom() - self.height()
        
        self.move(target_x, target_y)
        self.populate()
        self.show()

class ZoneViewerPopup(QFrame):

    """Popup that shows cards in a specific zone in a scrollable grid."""
    def __init__(self, test_play_window, parent=None):
        super().__init__(parent)
        self.test_play_window = test_play_window
        self.current_zone = None
        # Use Qt.Tool instead of Qt.Popup to allow reliable toggling via buttons
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 2px solid #555;
                border-radius: 8px;
            }
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """)
        self.setFixedSize(900, 700)

        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Title
        self.lbl_title = QLabel("Zone Viewer")
        self.lbl_title.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.lbl_title)

        
        # Scroll area with card grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(6)
        scroll.setWidget(self.grid_widget)
        layout.addWidget(scroll)
        
        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        self.btn_close = btn_close
        layout.addWidget(btn_close)
        
    def retranslate_ui(self):
        """Update strings from UI_TEXT."""
        lang = self.test_play_window.language
        def get_text(key):
            return UI_TEXT.get(lang, UI_TEXT["ja"]).get(key, key)
        
        if hasattr(self, "btn_close"):
            self.btn_close.setText(get_text("close"))
    
    def populate(self, zone_name):
        """Fill grid with cards from the specified zone."""
        self.current_zone = zone_name
        self.lbl_title.setText(zone_name)
        
        # Clear old
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Get items from scene
        items = list(self.test_play_window.scene.cards_in_zone.get(zone_name, []))
        
        # For Library, we show top-first (reverse)
        if zone_name == "Library":
            items.reverse()
        
        cols = 6
        for i, card_item in enumerate(items):
            row, col = divmod(i, cols)
            # In viewers, we usually let you pick any card
            icon_w = CardIconWidget(card_item, is_draggable=True)
            self.grid_layout.addWidget(icon_w, row, col)





    
    def _move_to_hand(self, card_item):
        self.test_play_window.scene.move_card_to_zone(card_item, "Hand")
        if self.current_zone:
            self.populate(self.current_zone)  # Refresh grid

    def show_at(self, pos, zone_name):
        # Position centered but clamp to screen
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        
        target_x = pos.x() - self.width() // 2
        target_y = pos.y() - self.height() // 2
        
        # Clamp X
        if target_x < screen.left(): target_x = screen.left()
        if target_x + self.width() > screen.right(): target_x = screen.right() - self.width()
        
        # Clamp Y
        if target_y < screen.top(): target_y = screen.top()
        if target_y + self.height() > screen.bottom(): target_y = screen.bottom() - self.height()
        
        self.move(target_x, target_y)
        self.populate(zone_name)
        self.show()


class TestPlayWindow(QWidget):
    def __init__(self, cards: List[Dict], deck_name: str, language="ja", image_root: Path = None, csv_path=None):
        super().__init__()
        self.deck_list = cards
        self.image_root = Path(image_root) if image_root else None
        self.csv_path = Path(csv_path) if csv_path else None
        self.language = language
        self.card_items = []
        self._initializing = True
        self.setWindowTitle(f"Test Play - {deck_name}")
        self.deck_name = deck_name # V22.0: Store for re-titling
        self.setWindowIcon(get_app_icon())
        self.resize(1600, 900)

        # Delayed refresh for taskbar grouping
        QTimer.singleShot(1500, lambda: self.setWindowIcon(get_app_icon()))
        
        main_layout = QVBoxLayout(self)
        
        # Toolbar
        btn_layout = QHBoxLayout()
        
        # Language selection (leftmost)
        from PyQt5.QtWidgets import QComboBox
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["日本語", "English"])
        self.combo_lang.setCurrentIndex(0 if self.language == "ja" else 1)
        self.combo_lang.setFixedWidth(80)
        self.combo_lang.currentIndexChanged.connect(self.on_language_changed)
        btn_layout.addWidget(self.combo_lang)

        # Use .get() or check key to be safe
        def get_text(key):
            return UI_TEXT.get(self.language, UI_TEXT["ja"]).get(key, key)

        self.btn_reset = QPushButton(get_text("reset_game"))
        self.btn_next_turn = QPushButton(get_text("next_turn"))
        self.btn_undo = QPushButton(get_text("undo"))
        self.btn_redo = QPushButton(get_text("redo"))
        
        self.turn_count = 1
        self.lbl_turn = QLabel(f"{get_text('turn')}: {self.turn_count}")
        self.lbl_turn.setStyleSheet("font-size: 16px; font-weight: bold; margin-left: 10px; color: #ffaa00;")
        
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addWidget(self.btn_undo)
        btn_layout.addWidget(self.btn_redo)
        btn_layout.addWidget(self.btn_next_turn)
        btn_layout.addWidget(self.lbl_turn)
        btn_layout.addStretch()

        
        main_layout.addLayout(btn_layout)
        
        # Main Area: Log | View
        content_layout = QHBoxLayout()
        
        # Log Sidebar
        self.log_visible = True
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedWidth(300)
        self.log_area.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #444;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }
        """)
        content_layout.addWidget(self.log_area)

        # Toggle Handle (between log and view)
        self.btn_log_handle = QPushButton("◁")
        self.btn_log_handle.setFixedWidth(20)
        self.btn_log_handle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.btn_log_handle.setStyleSheet("""
            QPushButton {
                background-color: #333;
                color: #aaa;
                border: 1px solid #444;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #444;
                color: #fff;
            }
        """)
        self.btn_log_handle.clicked.connect(self.toggle_log)
        content_layout.addWidget(self.btn_log_handle)
        
        # Scene
        # Widen to allow buttons on right
        # Increased to 1600 to handle wider zones
        scene_w = 1600
        scene_h = 800
        self.scene = TestPlayScene(scene_w, scene_h, self) 
        self.scene.setSceneRect(0, 0, scene_w, scene_h)
        
        self.view = QGraphicsView(self.scene)
        self.view.setAcceptDrops(True)
        self.view.setDragMode(QGraphicsView.RubberBandDrag)

        self.view.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setSceneRect(0, 0, scene_w, scene_h)
        
        content_layout.addWidget(self.view)
        main_layout.addLayout(content_layout)
        
        # Load Back Image
        back_path = exe_dir() / "assets" / "card_back.png"
        self.back_pixmap = load_or_download_card_back(back_path)
        if self.back_pixmap.isNull():
             self.back_pixmap = QPixmap(CARD_WIDTH_LOGICAL, CARD_HEIGHT_LOGICAL)
             self.back_pixmap.fill(QColor("brown"))
        
        # Undo/Redo History
        self.history_stack = []
        self.redo_stack = []
        self._is_undoing = False
        
        self.life = 40

        # Add in-scene buttons
        self._add_scene_buttons()
        
        # Zone Viewer Popup (Generalized)
        self.zone_popup = ZoneViewerPopup(self)
        
        # Token Viewer Popup
        self.token_viewer = TokenViewerPopup(self)
        
        # Initialize Cards
        QTimer.singleShot(100, self.start_mulligan_flow)

        
        # Connect Actions
        self.btn_reset.clicked.connect(self.reset_game)
        self.btn_next_turn.clicked.connect(self.next_turn)
        self.btn_undo.clicked.connect(self.undo_action)
        self.btn_redo.clicked.connect(self.redo_action)
        # self.btn_log_handle already connected earlier

        # Assets for indicators
        untap_path = exe_dir() / "emojis" / "mana-q.png"
        self.untap_pixmap = QPixmap(str(untap_path))
        if self.untap_pixmap.isNull():
             # Fallback: create a blank 16x16
             self.untap_pixmap = QPixmap(16, 16)
             self.untap_pixmap.fill(Qt.transparent)

        self.token_id_counter = 0
        self.active_toasts = []
        
        # Initial retranslate to set correct labels (V22.0)
        self.retranslate_ui()

    def on_language_changed(self, index):
        """V22.0: Handler for language combo box change."""
        self.language = "ja" if index == 0 else "en"
        self.retranslate_ui()
        # Log the language change
        msg = "Language changed to English" if self.language == "en" else "言語を日本語に変更しました"
        self.log_action(msg)

    def retranslate_ui(self):
        """V22.0: Update all UI strings based on self.language."""
        def get_text(key):
            return UI_TEXT.get(self.language, UI_TEXT["ja"]).get(key, key)

        # Window Title
        self.setWindowTitle(f"{get_text('test_play_title')} - {self.deck_name}")

        # Toolbar Buttons
        self.btn_reset.setText(get_text("reset_game"))
        self.btn_next_turn.setText(get_text("next_turn"))
        self.btn_undo.setText(get_text("undo"))
        self.btn_redo.setText(get_text("redo"))
        self.lbl_turn.setText(f"{get_text('turn')}: {self.turn_count}")

        # Log Handle
        self.btn_log_handle.setText("◁" if self.log_visible else "▷")
        
        # Scene Buttons (Update text on each Button widget)
        if hasattr(self, "scene_btn_view_lib"):
            self.scene_btn_view_lib.widget().setText(get_text("view_library"))
        if hasattr(self, "scene_btn_shuffle"):
            self.scene_btn_shuffle.widget().setText(get_text("shuffle_library"))
        if hasattr(self, "scene_btn_view_gy"):
            self.scene_btn_view_gy.widget().setText(get_text("view_graveyard"))
        if hasattr(self, "scene_btn_view_ex"):
            self.scene_btn_view_ex.widget().setText(get_text("view_exile"))
        if hasattr(self, "scene_btn_tokens"):
            self.scene_btn_tokens.widget().setText(get_text("tokens"))
        if hasattr(self, "cb_show_top"):
            self.cb_show_top.setText(get_text("always_show_top"))
        if hasattr(self, "lbl_life_header"):
            self.lbl_life_header.setText(get_text("life_label_scene"))

        if hasattr(self, "zone_popup"):
            self.zone_popup.retranslate_ui()
        if hasattr(self, "token_viewer"):
            self.token_viewer.retranslate_ui()
        if hasattr(self, "scene"):
            self.scene.retranslate_ui()

    def toggle_log(self):
        self.log_visible = not self.log_visible
        self.log_area.setVisible(self.log_visible)
        self.btn_log_handle.setText("◁" if self.log_visible else "▷")
        
        # Give UI a moment to layout then re-fit
        QTimer.singleShot(50, lambda: self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio))

    def save_snapshot(self):
        """Save a snapshot of the entire game state for Undo."""
        if getattr(self, "_initializing", False): return
        if self._is_undoing: return
        
        state = {
            "turn_count": self.turn_count,
            "life": self.life,
            "card_states": []
        }
        
        for item in self.card_items:
            card_state = {
                "card_id": item.card_id,
                "is_token": item.is_token,
                "card_data": item.card_data.copy(),
                "pos": (item.pos().x(), item.pos().y()),
                "rotation": item.rotation(),
                "is_tapped": item.is_tapped,
                "is_face_down": item.is_face_down,
                "does_not_untap": item.does_not_untap,
                "counters": item.counters.copy(),
                "zone": self.scene.get_card_zone(item)
            }
            state["card_states"].append(card_state)
            
        self.history_stack.append(state)
        # Clear redo stack on new action
        self.redo_stack.clear()
        
        # Limit history size (e.g. 50 steps)
        if len(self.history_stack) > 50:
            self.history_stack.pop(0)

    def undo_action(self):
        if not self.history_stack: return
        
        # Save current state to redo stack before undoing
        current_state = self._capture_current_state()
        self.redo_stack.append(current_state)
        
        last_state = self.history_stack.pop()
        self._is_undoing = True
        self.apply_snapshot(last_state)
        self._is_undoing = False
        self.log_action("<<< Undo")

    def redo_action(self):
        if not self.redo_stack: return
        
        # Save current state to history stack before redoing
        current_state = self._capture_current_state()
        self.history_stack.append(current_state)
        
        next_state = self.redo_stack.pop()
        self._is_undoing = True
        self.apply_snapshot(next_state)
        self._is_undoing = False
        self.log_action(">>> Redo")

    def _capture_current_state(self):
        # Helper to get current state without clearing redo_stack
        state = {
            "turn_count": self.turn_count,
            "life": self.life,
            "card_states": []
        }
        for item in self.card_items:
            card_state = {
                "card_id": item.card_id,
                "is_token": item.is_token,
                "card_data": item.card_data.copy(),
                "pos": (item.pos().x(), item.pos().y()),
                "rotation": item.rotation(),
                "is_tapped": item.is_tapped,
                "is_face_down": item.is_face_down,
                "does_not_untap": item.does_not_untap,
                "counters": item.counters.copy(),
                "zone": self.scene.get_card_zone(item)
            }
            state["card_states"].append(card_state)
        return state

    def apply_snapshot(self, state):
        """Restore game state from a snapshot."""
        self.turn_count = state["turn_count"]
        self.lbl_turn.setText(f"Turn: {self.turn_count}")
        self.life = state.get("life", 40)
        self.update_life_display()
        
        # 1. Handle tokens
        snap_ids = {s["card_id"] for s in state["card_states"]}
        
        # Remove current cards not in the snapshot
        to_remove = [item for item in self.card_items if item.card_id not in snap_ids]
        for item in to_remove:
            if item in self.card_items:
                self.card_items.remove(item)
            self.scene.removeItem(item)
            # Remove from zone lists
            for z in self.scene.cards_in_zone:
                if item in self.scene.cards_in_zone[z]:
                    self.scene.cards_in_zone[z].remove(item)

        # 2. Restore/Update existing cards and re-add missing tokens
        for s in state["card_states"]:
            # Find item
            item = next((i for i in self.card_items if i.card_id == s["card_id"]), None)
            
            if not item:
                # Re-create token if missing
                if s["is_token"]:
                    # Create placeholder for re-creation
                    pix = QPixmap(100, 140)
                    pix.fill(Qt.white)
                    item = CardItem(s["card_data"], pix, self.back_pixmap, s["card_id"])
                    self.scene.addItem(item)
                    self.card_items.append(item)
                    # Re-load image if image_root available
                    if self.image_root:
                        fname = s["card_data"].get("card_file_front")
                        if fname:
                            p = self.image_root / fname
                            if p.exists():
                                item.setPixmap(QPixmap(str(p)))
                else:
                    # Should not happens for non-tokens usually
                    continue

            # Restore properties
            item.setPos(s["pos"][0], s["pos"][1])
            item.setRotation(s["rotation"])
            item.is_tapped = s["is_tapped"]
            item.is_face_down = s["is_face_down"]
            item.does_not_untap = s["does_not_untap"]
            item.counters = s["counters"]
            
            # Restore zone placement
            target_zone = s["zone"]
            current_zone = self.scene.get_card_zone(item)
            if target_zone != current_zone:
                if current_zone in self.scene.cards_in_zone:
                    if item in self.scene.cards_in_zone[current_zone]:
                        self.scene.cards_in_zone[current_zone].remove(item)
                if target_zone in self.scene.cards_in_zone:
                    self.scene.cards_in_zone[target_zone].append(item)
            
            item.update()
        
        # 3. Refresh Hand/Lands/Stacks
        self.scene.arrange_hand()
        self.scene.arrange_lands()
        for z in ["Library", "Graveyard", "Exile", "Command"]:
            self.scene.arrange_stack(z)
        
        self.view.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'scene') and self.scene:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def log_action(self, message):
        """Append a message to the action log with timestamp."""
        from datetime import datetime
        time_str = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{time_str}] {message}"
        self.log_area.appendPlainText(full_msg)
        self.log_area.moveCursor(QTextCursor.End)
        
        if not self.log_visible:
            self.show_toast(message)

    def show_toast(self, message):
        toast = ToastLabel(message, self)
        toast.adjustSize()
        
        self.active_toasts.append(toast)
        self.reposition_toasts()
        
        # When toast is deleted, remove from list and reposition others
        # We use a lambda but need to be careful with references. 
        # Better to have a dedicated method.
        toast.destroyed.connect(lambda: self._on_toast_destroyed(toast))
        toast.show()

    def _on_toast_destroyed(self, toast):
        if hasattr(self, "active_toasts") and toast in self.active_toasts:
            self.active_toasts.remove(toast)
            self.reposition_toasts()

    def reposition_toasts(self):
        current_y = 60
        for toast in self.active_toasts:
            # For now, just move. Could use animation for "shift up"
            toast.move(20, current_y)
            current_y += toast.height() + 8

    def _add_scene_buttons(self):
        """Add Shuffle and View Library buttons in the scene, right of zones."""
        
        # Helper to create styled button
        def create_btn(text, callback, x, y, width=120):
            btn = QPushButton(text)
            btn.setFixedSize(width, 32)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2e4057; color: white;
                    border: 1px solid #5a7a9a; border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton:hover { background-color: #3a5070; }
            """)
            btn.clicked.connect(callback)
            proxy = QGraphicsProxyWidget()
            proxy.setWidget(btn)
            proxy.setPos(x, y)
            self.scene.addItem(proxy)
            return proxy

        # Library Controls
        lib_rect = self.scene.zones["Library"]
        btn_x = lib_rect.x() + lib_rect.width() + 10

        # Show Top Checkbox (Above buttons)
        self.cb_show_top = QCheckBox("Always Show Top")
        self.cb_show_top.setFixedSize(140, 24)
        self.cb_show_top.setStyleSheet("""
            QCheckBox {
                color: #ffaa00; font-size: 11px; font-weight: bold;
                background-color: rgba(30, 30, 30, 200);
                border: 1px solid #555; border-radius: 4px;
                padding-left: 5px;
            }
            QCheckBox:hover { background-color: #333; }
        """)
        self.cb_show_top.stateChanged.connect(lambda: self.scene.arrange_stack("Library"))
        proxy_cb = QGraphicsProxyWidget()
        proxy_cb.setWidget(self.cb_show_top)
        proxy_cb.setPos(btn_x - 10, lib_rect.y() - 25)
        self.scene.addItem(proxy_cb)

        self.scene_btn_view_lib = create_btn("View Library", lambda: self._show_zone_popup("Library"), btn_x, lib_rect.y() + 10)
        self.scene_btn_shuffle = create_btn("Shuffle Library", self.shuffle_library, btn_x, lib_rect.y() + 45)


        # Graveyard Controls
        gy_rect = self.scene.zones["Graveyard"]
        self.scene_btn_view_gy = create_btn("View Graveyard", lambda: self._show_zone_popup("Graveyard"), btn_x, gy_rect.y() + 10)

        # Exile Controls
        ex_rect = self.scene.zones["Exile"]
        self.scene_btn_view_ex = create_btn("View Exile", lambda: self._show_zone_popup("Exile"), btn_x, ex_rect.y() + 10)

        # Tokens Control
        self.scene_btn_tokens = create_btn(UI_TEXT[self.language]["tokens"], self.show_token_menu, btn_x, ex_rect.y() + 45)

        # Life Counter (Below Library buttons)
        life_y = lib_rect.y() + 90 
        
        # Life Label (Static)
        self.lbl_life_header = self.scene.addSimpleText("LIFE")
        self.lbl_life_header.setBrush(QBrush(QColor(200, 200, 200, 180)))
        font = QFont("Segoe UI", 10, QFont.Bold)
        self.lbl_life_header.setFont(font)
        self.lbl_life_header.setPos(btn_x + 35, life_y)
        self.lbl_life_header.setZValue(-99)

        # Life Number Display
        self.lbl_life_val = QLabel(str(self.life))
        self.lbl_life_val.setFixedSize(120, 50)
        self.lbl_life_val.setAlignment(Qt.AlignCenter)
        self.lbl_life_val.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 36px;
                font-weight: bold;
                background-color: rgba(50, 50, 50, 150);
                border: 2px solid #555;
                border-radius: 8px;
            }
        """)
        proxy_life = QGraphicsProxyWidget()
        proxy_life.setWidget(self.lbl_life_val)
        proxy_life.setPos(btn_x, life_y + 20)
        self.scene.addItem(proxy_life)

        # Life Buttons +/-
        btn_minus = QPushButton("-")
        btn_minus.setFixedSize(55, 30)
        btn_minus.setStyleSheet("background-color: #8b0000; color: white; font-weight: bold; font-size: 16px; border-radius: 4px;")
        btn_minus.clicked.connect(lambda: self.change_life(-1))
        
        proxy_m = QGraphicsProxyWidget()
        proxy_m.setWidget(btn_minus)
        proxy_m.setPos(btn_x, life_y + 75)
        self.scene.addItem(proxy_m)

        btn_plus = QPushButton("+")
        btn_plus.setFixedSize(55, 30)
        btn_plus.setStyleSheet("background-color: #006400; color: white; font-weight: bold; font-size: 16px; border-radius: 4px;")
        btn_plus.clicked.connect(lambda: self.change_life(1))
        
        proxy_p = QGraphicsProxyWidget()
        proxy_p.setWidget(btn_plus)
        proxy_p.setPos(btn_x + 65, life_y + 75)
        self.scene.addItem(proxy_p)

    def change_life(self, delta):
        self.save_snapshot()
        self.life += delta
        self.update_life_display()
        
        if not hasattr(self, "_accumulated_life_delta"):
            self._accumulated_life_delta = 0
            
        self._accumulated_life_delta += delta
        
        if not hasattr(self, "_life_log_timer"):
            self._life_log_timer = QTimer(self)
            self._life_log_timer.setSingleShot(True)
            self._life_log_timer.timeout.connect(self._flush_life_log)
            
        # Restart the timer to wait 2 seconds from the LAST click
        self._life_log_timer.start(2000)

    def _flush_life_log(self):
        delta = getattr(self, "_accumulated_life_delta", 0)
        if delta == 0:
            return
            
        lang = self.language
        if delta > 0:
            self.log_action(UI_TEXT[lang]["log_life_inc"].format(n=delta))
        else:
            self.log_action(UI_TEXT[lang]["log_life_dec"].format(n=abs(delta)))
            
        self._accumulated_life_delta = 0

    def update_life_display(self):
        if hasattr(self, 'lbl_life_val'):
            self.lbl_life_val.setText(str(self.life))

    def show_token_menu(self):
        # Now shows the visual Token Viewer popup instead of a QMenu
        self.token_viewer.show_at(QCursor.pos())

    def save_deck_csv(self):
        """Save the current deck list back to CSV (used after generating tokens)."""
        if not self.csv_path: return
        import csv
        try:
            fieldnames = list(self.deck_list[0].keys()) if self.deck_list else []
            if not fieldnames: return
            
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.deck_list)
        except Exception as e:
            print(f"Error saving CSV: {e}")

    def spawn_token(self, card_data, auto_place=True):
        self.token_id_counter += 1
        unique_id = f"token_{self.token_id_counter}"

        # Load Image
        pix = None
        if self.image_root:
            fname = card_data.get("card_file_front")
            if fname:
                p = self.image_root / fname
                if p.exists():
                    pix = QPixmap(str(p))
        
        if pix is None or pix.isNull():
            pix = QPixmap(100, 140)
            pix.fill(Qt.white)
        
        item = CardItem(card_data, pix, self.back_pixmap, unique_id)
        self.scene.addItem(item)
        self.card_items.append(item)

        if auto_place:
            # Move to Battlefield (center-ish)
            rect = self.scene.zones["Battlefield"]
            item.setPos(rect.center().x() - 50, rect.center().y() - 70)
            self.scene.handle_card_drop(item)
        else:
            # Hide it initially so it doesn't appear at (0,0) during drag
            item.setVisible(False)
        return item

    def _show_zone_popup(self, zone_name):
        # Toggle: if already showing this zone, hide it.
        if self.zone_popup.isVisible() and self.zone_popup.current_zone == zone_name:
            self.zone_popup.hide()
            return

        view_center = self.view.mapToGlobal(self.view.rect().center())
        self.zone_popup.show_at(view_center, zone_name)


    def start_mulligan_flow(self):
        """Open SimulationWindow to decide starting hand."""
        if not self.csv_path or not self.deck_list:
            self.init_cards() # Fallback if no CSV or deck
            return

        # Prepare cards in the format SimulationWindow expects (from deck_loader.py)
        mulligan_deck = []
        for i, c in enumerate(self.deck_list):
            # Skip tokens in mulligan/library
            if str(c.get("is_token")) == "True":
                continue

            count = int(c.get("count", 1))
            # SimulationWindow expects unique-ish ids
            cid = c.get("id") or c.get("card_file_front", "Unknown")
            for j in range(count):
                img_name = c.get("card_file_front", "").strip()
                img_path = self.image_root / img_name if self.image_root and img_name else None
                
                mulligan_deck.append({
                    # Include row index i and instance index j to ensure global uniqueness
                    "id": f"{cid}_{i}_{j}" if count > 1 or i > 0 else cid,
                    "name": c.get("name_en", "Unknown"),
                    "img": str(img_path) if img_path else None,
                    "Commander_A": c.get("Commander_A", "").strip(),
                    "Commander_B": c.get("Commander_B", "").strip(),
                    "Companion":   c.get("Companion", "").strip(),
                    "count":       "1", # Each entry is a single card instance
                    "is_token":    "False"
                })

        self.sim_win = SimulationWindow(
            mulligan_deck,
            self.windowTitle().replace("Test Play - ", ""),
            self.language,
            self.csv_path,
            is_setup_mode=True
        )
        self.sim_win.finished_mulligan.connect(self.handle_mulligan_result)
        self.sim_win.show()


    def handle_mulligan_result(self, hand_cards, exiled_cards, bottom_cards):
        """Callback from SimulationWindow when 'Keep' is clicked."""
        self.init_cards(hand_cards, exiled_cards, bottom_cards)

    def init_cards(self, hand_cards=None, exiled_cards=None, bottom_cards=None):
        if hand_cards is not None:
             self.log_action(UI_TEXT[self.language]["log_mulligan"].format(n=len(hand_cards)))
        
        # Log Turn 1 specifically when initializing or resetting
        if self.turn_count == 1:
            self.log_action(UI_TEXT[self.language]["log_turn"].format(n=self.turn_count))
        
        # Clear existing card items from scene and list
        if hasattr(self, 'card_items'):
            for item in self.card_items:
                if item.scene():
                    self.scene.removeItem(item)
        self.card_items = []

        # Clear zone tracking
        for z in self.scene.cards_in_zone:
            self.scene.cards_in_zone[z] = []

        if not self.deck_list:
            QMessageBox.warning(self, "Warning", "Card list is empty!")
            return
        commanders = []
        library = []
        
        # print(f"DEBUG: init_cards started. Deck list len: {len(self.deck_list)}")
        # print(f"DEBUG: image_root: {self.image_root}")



        for i, card_data in enumerate(self.deck_list):
            # Skip tokens during initial library/commander population
            if str(card_data.get("is_token")) == "True":
                continue

            count = int(card_data.get("count", 1))
            
            for c_idx in range(count):
                # Robust Commander check
                c_a = card_data.get("Commander_A", "").strip()
                c_b = card_data.get("Commander_B", "").strip()
                comp = card_data.get("Companion", "").strip()
                is_cmdr = bool(c_a or c_b or comp)
                
                # ID Fallback
                c_id = card_data.get("id")
                if not c_id:
                    c_id = card_data.get("card_file_front", "Unknown")
                
                # MUST match the ID scheme in start_mulligan_flow
                unique_id = f"{c_id}_{i}_{c_idx}" if count > 1 or i > 0 else c_id
                
                # Load Image
                img_path = card_data.get("img")
                pix = None
                if img_path and Path(img_path).exists():
                    pix = QPixmap(str(img_path))
                elif self.image_root:
                    fname = card_data.get("card_file_front")
                    if fname:
                        p = self.image_root / fname
                        if p.exists():
                            pix = QPixmap(str(p))
                
                if pix is None or pix.isNull():
                    pix = QPixmap(100, 140)
                    pix.fill(Qt.red)
                
                # Create CardItem
                item = CardItem(card_data, pix, self.back_pixmap, unique_id)
                self.scene.addItem(item)
                self.card_items.append(item)
                
                if is_cmdr:
                    commanders.append(item)
                else:
                    library.append(item)

        # print(f"DEBUG: Init loop done. Created {len(self.card_items)} items.")
        # print(f"DEBUG: Commanders: {len(commanders)}, Library: {len(library)}")

        
        # Determine initial zones
        # 1) Hand cards from Mulligan
        hand_ids = [c["id"] for c in hand_cards] if hand_cards else []
        # 2) Exiled cards from Serum Powder
        exile_ids = [c["id"] for c in exiled_cards] if exiled_cards else []
        # 3) Bottomed cards from Mulligan
        bottom_ids = [c["id"] for c in bottom_cards] if bottom_cards else []
        
        commanders = []
        library_pool = []
        starting_hand = []
        starting_exile = []

        # First pass: separating cards that are NOT on the bottom
        for item in self.card_items:
            c_data = item.card_data
            c_a = c_data.get("Commander_A", "").strip()
            c_b = c_data.get("Commander_B", "").strip()
            comp = c_data.get("Companion", "").strip()
            is_cmdr = bool(c_a or c_b or comp)

            if is_cmdr:
                commanders.append(item)
            elif item.card_id in hand_ids:
                starting_hand.append(item)
                hand_ids.remove(item.card_id)
            elif item.card_id in exile_ids:
                starting_exile.append(item)
                exile_ids.remove(item.card_id)
            elif item.card_id not in bottom_ids:
                library_pool.append(item)
        
        # Second pass: building starting_bottom EXACTLY in the order of bottom_ids
        starting_bottom = []
        # Note: bottom_ids[0] should be the bottom-most card
        for bid in bottom_ids:
            # Find the item that belongs to this ID and wasn't placed yet
            # In init_cards, all items are newly created, so we just match by unique_id
            item = next((i for i in self.card_items if i.card_id == bid), None)
            if item:
                starting_bottom.append(item)

        # Initial placement
        for item in commanders:
           self.scene.move_card_to_zone(item, "Command")
            
        # Shuffle remaining library cards before adding bottom cards
        random.shuffle(library_pool)
        
        # Combined list: bottom-most cards first, then the random rest
        final_library = starting_bottom + library_pool
        
        for item in final_library:
            self.scene.move_card_to_zone(item, "Library")
            
        for item in starting_hand:
            self.scene.move_card_to_zone(item, "Hand")
            
        for item in starting_exile:
            self.scene.move_card_to_zone(item, "Exile")

        # Cards are already placed in Library zone in correct order (bottom-first)
        # So we just need to ensure they are stacked. shuffle_library() would randomize it again.
        self.scene.arrange_stack("Library")
        
        # If no hand was passed, draw 7 (Legacy/Fallback)
        if hand_cards is None:
            self.draw_cards(7)

        self._initializing = False

        # Force view update
        self.view.viewport().update()
        
        # Ensure visible and fit (using delay to allow UI/Layout to settle)
        # This addresses the cards-in-top-left issue by re-arranging after setup
        def final_layout():
            self.scene.arrange_hand()
            self.scene.arrange_lands()
            for z in ["Library", "Graveyard", "Exile", "Command"]:
                self.scene.arrange_stack(z)
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            
            # Auto-draw 1 card for Turn 1
            QTimer.singleShot(500, lambda: self.draw_cards(1))

        QTimer.singleShot(200, final_layout)


    def reset_game(self):
        lang = self.language
        title = UI_TEXT[lang].get("reset_game_confirm_title", "Confirm")
        msg = UI_TEXT[lang].get("reset_game_confirm_msg", "Reset the game and restart with Mulligan?")
        ret = QMessageBox.question(self, title, msg, QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
            
        self._initializing = True
        # Reset card states (tapped/flipped) and start mulligan
        for item in self.card_items:
            item.is_tapped = False
            item.setRotation(0)
            # Flipped state should also be reset if any
            if hasattr(item, "is_face_down") and item.is_face_down:
                item.flip() 

        self.log_action(UI_TEXT[self.language]["log_reset"])
        self.turn_count = 1
        self.lbl_turn.setText(f"Turn: {self.turn_count}")
        self.life = 40
        self.update_life_display()

        self.start_mulligan_flow()


    def shuffle_library(self):
        self.save_snapshot()
        self.log_action(UI_TEXT[self.language]["log_shuffled"])
        lib = self.scene.cards_in_zone["Library"]
        for card in lib:
            card.set_face_down(True)
        random.shuffle(lib)
        self.scene.arrange_stack("Library")
        # Refresh popup if open and viewing library
        if self.zone_popup.isVisible() and self.zone_popup.current_zone == "Library":
            self.zone_popup.populate("Library")



    def draw_cards(self, count):
        self.save_snapshot()
        lib = self.scene.cards_in_zone["Library"]
        
        to_draw = []
        for _ in range(count):
            if not lib: break
            card = lib.pop()
            to_draw.append(card)
        
        # Refresh Library flags immediately so the NEW top card can be clicked/dragged
        # during the animation of the previous one.
        self.scene.arrange_stack("Library")
        
        # Animate each card
        for i, card in enumerate(to_draw):
            name = card.card_data.get("name_ja") if self.language == "ja" else card.card_data.get("name_en")
            self.log_action(UI_TEXT[self.language]["log_drew"].format(name=name))
            # Delay each draw slightly for better feel
            QTimer.singleShot(i * 150, lambda c=card: self.animate_draw_card(c))

    def animate_draw_card(self, card_item):
        """Slide card from Library to Hand with animation."""
        # 1. Calculate target position based on current hand + animating cards
        if not hasattr(self, '_animating_to_hand'): self._animating_to_hand = []
        
        index_in_hand = len(self.scene.cards_in_zone["Hand"]) + len(self._animating_to_hand)
        target_pos = self.get_hand_target_pos(index_in_hand)
        
        self._animating_to_hand.append(card_item)
    
        # 2. Setup animation
        card_item.setZValue(2000 + index_in_hand) # High Z, and newer cards higher
        card_item.set_face_down(False)
        
        # Disable interaction during animation so it doesn't block stack clicks below
        card_item.setFlag(QGraphicsItem.ItemIsMovable, False)
        card_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        card_item.setAcceptedMouseButtons(Qt.NoButton)
        
        anim = QVariantAnimation(self)
        anim.setDuration(500)
        anim.setStartValue(card_item.pos())
        anim.setEndValue(target_pos)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        
        anim.valueChanged.connect(card_item.setPos)
        
        # 3. On finishing, finalize in zone
        def on_finished():
            if card_item in self._animating_to_hand:
                self._animating_to_hand.remove(card_item)
            self.scene.move_card_to_zone(card_item, "Hand")
            # arrange_hand will set the final ZValue based on list index

        anim.finished.connect(on_finished)
        
        # We DON'T append to Hand list yet to avoid move_card_to_zone confusion
        # and to keep arrange_hand calls from affecting it until finished.
        
        anim.start()
        # Keep reference to prevent GC
        if not hasattr(self, '_anims'): self._anims = []
        self._anims.append(anim)
        # Cleanup finished animations
        anim.finished.connect(lambda: self._anims.remove(anim) if anim in self._anims else None)

    def get_hand_target_pos(self, index_in_hand):
        """Calculate where the i-th card should be in Hand."""
        rect = self.scene.zones["Hand"]
        # We use a similar logic to arrange_hand
        # But since we might be drawing multiple, we estimate the final spacing
        # Or just use a fixed spacing if it fits
        count = len(self.scene.cards_in_zone["Hand"]) + 1
        
        total_w = count * CARD_WIDTH_LOGICAL
        if total_w > rect.width() - 80:
            offset = (rect.width() - 80 - CARD_WIDTH_LOGICAL) / max(1, count - 1)
        else:
            offset = CARD_WIDTH_LOGICAL + 5
            
        start_x = rect.x() + 80
        y = rect.y() + 10
        return QPointF(start_x + index_in_hand * offset, y)

    def next_turn(self):
        self.save_snapshot()
        # Untap all cards in Battlefield and Lands
        for zone_name in ["Battlefield", "Lands"]:
            items = self.scene.cards_in_zone.get(zone_name, [])
            for item in items:
                if item.is_tapped and not item.does_not_untap:
                    item.toggle_tap(log=False)
        
        # Increment turn
        self.turn_count += 1
        self.lbl_turn.setText(f"Turn: {self.turn_count}")
        self.log_action(UI_TEXT[self.language]["log_turn"].format(n=self.turn_count))

        # Draw 1
        self.draw_cards(1)


    def draw_bottom_card(self):
        lib = self.scene.cards_in_zone["Library"]
        if not lib: return
        card = lib.pop(0)
        name = card.card_data.get("name_ja") if self.language == "ja" else card.card_data.get("name_en")
        self.log_action(UI_TEXT[self.language]["log_drew"].format(name=name))
        self.scene.arrange_stack("Library")
        self.animate_draw_card(card)

    def draw_x_cards(self):
        val, ok = QInputDialog.getInt(self, "Draw X", "How many cards?", 1, 1, 100)
        if ok:
            self.draw_cards(val)

    def discard_all_hand(self):
        hand = list(self.scene.cards_in_zone["Hand"])
        for card in hand:
            self.scene.move_card_to_zone(card, "Graveyard")

    def discard_random_hand(self):
        """Roulette animation to discard a random card from hand."""
        hand = list(self.scene.cards_in_zone.get("Hand", []))
        if not hand: return

        # Prevent multiple concurrent animations
        if hasattr(self, "_discard_timer") and self._discard_timer.isActive():
            return

        self._discard_targets = hand
        self._discard_idx = 0
        self._discard_start_time = QDateTime.currentMSecsSinceEpoch()
        self._discard_duration = 3000 # 3 seconds
        self._discard_base_interval = 60 # ms
        
        self._discard_timer = QTimer(self)
        self._discard_timer.timeout.connect(self._on_discard_anim_step)
        self._discard_timer.start(self._discard_base_interval)

    def _on_discard_anim_step(self):
        # Clear all hand highlights
        for c in self._discard_targets:
            c.highlighted = False
            c.update()
            
        elapsed = QDateTime.currentMSecsSinceEpoch() - self._discard_start_time
        
        if elapsed >= self._discard_duration:
            self._discard_timer.stop()
            # Stop on current and discard
            if self._discard_targets:
                target_card = self._discard_targets[self._discard_idx % len(self._discard_targets)]
                self.scene.move_card_to_zone(target_card, "Graveyard", log=True)
            return

        # Move to next
        self._discard_idx += 1
        current_card = self._discard_targets[self._discard_idx % len(self._discard_targets)]
        current_card.highlighted = True
        current_card.update()
        
        # Slow down curve: Linear slowdown from 60ms to 600ms
        progress = elapsed / self._discard_duration
        new_interval = self._discard_base_interval + int(progress * 540)
        self._discard_timer.setInterval(new_interval)

    def put_card_on_top(self, card):
        self.scene.move_card_to_zone(card, "Library")

    def put_card_on_bottom(self, card):
        # Custom logic for bottom of library
        for z in self.scene.cards_in_zone:
            if card in self.scene.cards_in_zone[z]:
                self.scene.cards_in_zone[z].remove(card)
                if z == "Hand": self.scene.arrange_hand()
                break
        self.scene.cards_in_zone["Library"].insert(0, card)
        # Force re-stack
        self.scene.arrange_stack("Library")

    def exile_all_graveyard(self):
        gy = list(self.scene.cards_in_zone["Graveyard"])
        for card in gy:
            self.scene.move_card_to_zone(card, "Exile")

    def return_all_to_library(self, zone_name):
        items = list(self.scene.cards_in_zone[zone_name])
        for card in items:
            self.scene.move_card_to_zone(card, "Library")
        # Shuffle result?
        random.shuffle(self.scene.cards_in_zone["Library"])
        self.scene.arrange_stack("Library")

    def delete_card(self, card):
        if card in self.card_items:
            self.card_items.remove(card)
        # Remove from zone lists
        for z in self.scene.cards_in_zone:
            if card in self.scene.cards_in_zone[z]:
                self.scene.cards_in_zone[z].remove(card)
                if z == "Hand": self.scene.arrange_hand()
                break
        self.scene.removeItem(card)

