# card_widget.py
from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton, QGraphicsOpacityEffect


class CardWidget(QWidget):
    clicked = pyqtSignal(object)           # emit self
    serum_activated = pyqtSignal(object)   # emit self

    def __init__(self, img_path, card_id):
        super().__init__()

        self.card_id = card_id
        self.marked_bottom = False

        # Image label
        self.img_label = QLabel()
        pix = QPixmap(str(img_path))
        if not pix.isNull():
            self.img_label.setPixmap(pix.scaledToHeight(300, Qt.SmoothTransformation))
        else:
            self.img_label.setText("Image Error")

        # Overlay for "BOTTOM"
        self.overlay = QLabel("BOTTOM", self)
        self.overlay.setAlignment(Qt.AlignCenter)
        self.overlay.setStyleSheet(
            "background-color: rgba(0,0,0,120);"
            "color: white;"
            "font-size: 28px;"
            "font-weight: bold;"
            "font-family: 'Meiryo UI';"
        )
        self.overlay.hide()

        # Overlay for hover effect (darken)
        self.hover_overlay = QLabel(self)
        self.hover_overlay.setStyleSheet(
            "background-color: rgba(0,0,0,80);"
        )
        self.hover_overlay.hide()

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

        layout = QVBoxLayout()
        layout.addWidget(self.img_label)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Enable mouse tracking for hover events
        self.setMouseTracking(True)
        self.img_label.setMouseTracking(True)

    # keep overlay size aligned
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.resize(self.img_label.size())
        self.overlay.raise_()
        self.hover_overlay.resize(self.img_label.size())
        self.hover_overlay.raise_()
        
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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.hover_overlay.show()
        self.hover_overlay.raise_()
        if self.btn_serum.isVisible():
            self.btn_serum.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_overlay.hide()
        super().leaveEvent(event)

    def set_marked(self, state: bool):
        self.marked_bottom = state
        if state:
            self.overlay.show()
            self.overlay.raise_()
            # Ensure serum button is always on top if it exists
            if self.btn_serum.isVisible():
                self.btn_serum.raise_()
        else:
            self.overlay.hide()

    def toggle_bottom_mark(self):
        self.set_marked(not self.marked_bottom)

    def start_pulse(self):
        self.img_label.setGraphicsEffect(self.opacity_effect)
        self.pulse_anim.start()

    def stop_pulse(self):
        self.pulse_anim.stop()
        self.img_label.setGraphicsEffect(None) # Remove effect completely

    def show_serum_button(self, text):
        self.btn_serum.setText(text)
        self.btn_serum.show()
        self.btn_serum.raise_()

    def hide_serum_button(self):
        self.btn_serum.hide()
