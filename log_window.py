# log_window.py
from PyQt5.QtWidgets import QWidget, QMainWindow, QTextEdit, QVBoxLayout, QApplication
from PyQt5.QtGui import QTextCursor, QPalette, QColor
from PyQt5.QtCore import Qt, QObject, pyqtSignal
import sys

from PyQt5.QtCore import QMetaObject, Qt
from PyQt5.QtCore import pyqtSlot

def enable_dark_mode(app: QApplication):
    palette = QPalette()

    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(20, 20, 20))
    palette.setColor(QPalette.AlternateBase, QColor(30, 30, 30))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(40, 40, 40))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Highlight, QColor(90, 130, 200))
    palette.setColor(QPalette.HighlightedText, Qt.black)

    app.setPalette(palette)

class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Log")
        self.resize(800, 400)

        layout = QVBoxLayout(self)

        self.text = QTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.NoWrap)

        layout.addWidget(self.text)

    @pyqtSlot(str)
    def append_log(self, msg: str):
        if not msg:
            return
        self.text.append(msg.rstrip())



class StdoutRedirect(QObject):
    text_emitted = pyqtSignal(str)

    def __init__(self):
        super().__init__()

    def write(self, msg):
        if msg:
            self.text_emitted.emit(msg)

    def flush(self):
        pass


