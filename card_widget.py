from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QRectF
from PyQt5.QtGui import QPixmap, QPainterPath, QRegion, QPainter, QColor, QFont
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton, QGraphicsOpacityEffect




class CardWidget(QWidget):
    clicked = pyqtSignal(object)           # emit self
    serum_activated = pyqtSignal(object)   # emit self

    def __init__(self, img_path, card_id):
        super().__init__()

        self.card_id = card_id
        self.marked_bottom = False
        self.is_hovering = False
        self.pixmap = None

        pix = QPixmap(str(img_path))
        if not pix.isNull():
            # Support High DPI (e.g. 150% scaling) by pre-scaling to 2x logical size
            # target logical height is 300, so we scale to 600
            self.pixmap = pix.scaledToHeight(600, Qt.SmoothTransformation)
            self.pixmap.setDevicePixelRatio(2.0)
        else:
            self.pixmap = None

        # Serum Powder Button Overlay
        self.btn_serum = QPushButton("Activate", self)
        self.btn_serum.setStyleSheet("""
            QPushButton {
                background-color: #ff4757;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px;
                font-size: 14px;
                font-family: 'Meiryo UI';
            }
            QPushButton:hover { background-color: #ff6b81; }
        """)
        self.btn_serum.hide()
        self.btn_serum.clicked.connect(lambda: self.serum_activated.emit(self))

        # Pulsing effect setup (initialized but not attached)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.pulse_anim = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.pulse_anim.setDuration(800)
        self.pulse_anim.setStartValue(1.0)
        self.pulse_anim.setKeyValueAt(0.5, 0.7) # Less transparent
        self.pulse_anim.setEndValue(1.0)
        self.pulse_anim.setLoopCount(-1) # Infinite

        # Enable mouse tracking for hover events
        self.setMouseTracking(True)
        # Transparent background to allow rounded corners with AA
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(214, 300) # Match card ratio appx

    # keep overlay size aligned
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Center the serum button near the middle-bottom
        btn_w = 170
        btn_h = 36
        self.btn_serum.setGeometry(
            (self.width() - btn_w) // 2,
            self.height() - btn_h - 40,
            btn_w,
            btn_h
        )
        self.btn_serum.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = QRectF(self.rect())
        radius = 15.0 # Standard MTG corner ratio (7px/140px scaled to 300px height)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        # 1. Draw Card Pixmap
        if self.pixmap:
            painter.drawPixmap(self.rect(), self.pixmap)
        else:
            painter.fillRect(self.rect(), QColor("#333"))
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "Image Error")

        # 2. Hover Overlay
        if self.is_hovering:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        # 3. Bottom Overlay
        if self.marked_bottom:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
            painter.setPen(Qt.white)
            font = QFont("Meiryo UI", 20, QFont.Bold)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "BOTTOM")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.is_hovering = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovering = False
        self.update()
        super().leaveEvent(event)

    def set_marked(self, state: bool):
        self.marked_bottom = state
        self.update()
        if state:
            # Ensure serum button is always on top if it exists
            if self.btn_serum.isVisible():
                self.btn_serum.raise_()

    def toggle_bottom_mark(self):
        self.set_marked(not self.marked_bottom)

    def start_pulse(self):
        self.setGraphicsEffect(self.opacity_effect)
        self.pulse_anim.start()

    def stop_pulse(self):
        self.pulse_anim.stop()
        self.setGraphicsEffect(None) # Remove effect completely

    def show_serum_button(self, text):
        self.btn_serum.setText(text)
        self.btn_serum.show()
        self.btn_serum.raise_()

    def hide_serum_button(self):
        self.btn_serum.hide()
