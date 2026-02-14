# star_rating_widget.py
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor, QPolygonF, QMouseEvent
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
import math

class StarRatingWidget(QWidget):
    ratingChanged = pyqtSignal(int)  # emit 1-5 when user clicks

    def __init__(self, max_stars=5, parent=None):
        super().__init__(parent)
        self.max_stars = max_stars
        self.current_rating = 0  # clicked rating
        self.hover_rating = 0    # hover highlight
        self.setMouseTracking(True)
        self.setMinimumHeight(50)

    # -----------------------------
    # Create star polygon
    # -----------------------------
    def star_polygon(self, cx, cy, r):
        points = []
        for i in range(10):
            angle_deg = i * 36
            rad = math.radians(angle_deg)
            radius = r if i % 2 == 0 else r / 2
            x = cx + radius * math.cos(rad)
            y = cy - radius * math.sin(rad)
            points.append(QPointF(x, y))
        return QPolygonF(points)

    # -----------------------------
    # Draw stars
    # -----------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        star_spacing = w / (self.max_stars + 1)
        r = min(star_spacing, h) * 0.4

        for i in range(self.max_stars):
            cx = star_spacing * (i + 1)
            cy = h / 2
            if i < max(self.current_rating, self.hover_rating):
                painter.setBrush(QColor(255, 215, 0))  # yellow
            else:
                painter.setBrush(QColor(200, 200, 200))  # gray
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(self.star_polygon(cx, cy, r))

        # Explicitly end painter for PyQt5
        painter.end()

    # -----------------------------
    # Update hover rating on mouse move
    # -----------------------------
    def mouseMoveEvent(self, event: QMouseEvent):
        w = self.width()
        h = self.height()
        star_spacing = w / (self.max_stars + 1)
        r = min(star_spacing, h) * 0.4

        for i in range(self.max_stars):
            star_left = star_spacing * (i + 1) - r
            star_right = star_spacing * (i + 1) + r
            if event.x() <= star_right:  # マウスが星の右端に触れたら
                self.hover_rating = i + 1
                break
        else:
            self.hover_rating = self.max_stars
        self.update()

    # -----------------------------
    # Clear hover when mouse leaves
    # -----------------------------
    def leaveEvent(self, event):
        self.hover_rating = 0
        self.update()

    # -----------------------------
    # Set clicked rating
    # -----------------------------
    def mousePressEvent(self, event: QMouseEvent):
        w = self.width()
        h = self.height()
        star_spacing = w / (self.max_stars + 1)
        r = min(star_spacing, h) * 0.4

        for i in range(self.max_stars):
            star_left = star_spacing * (i + 1) - r
            star_right = star_spacing * (i + 1) + r
            if event.x() <= star_right:
                self.current_rating = i + 1
                break
        else:
            self.current_rating = self.max_stars

        self.ratingChanged.emit(self.current_rating)
        self.update()
