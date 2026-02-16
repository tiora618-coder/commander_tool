# image_selector.py
import requests
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QComboBox, QCheckBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt, QSize, QThreadPool, QRunnable, QObject, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QImage
import generator

class ImageResult(QObject):
    finished = pyqtSignal(int, int, QImage)

class ImageLoader(QRunnable):
    def __init__(self, index, url, size, request_id):
        super().__init__()
        self.index = index
        self.url = url
        self.size = size
        self.request_id = request_id
        self.signals = ImageResult()
        self.session = requests.Session()

    def run(self):
        try:
            r = self.session.get(self.url, timeout=5)
            r.raise_for_status()

            img = QImage.fromData(r.content)
            if img.isNull():
                return

            img = img.scaled(
                self.size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.signals.finished.emit(self.request_id, self.index, img)

        except Exception:
            pass
        finally:
            self.session.close()

class ImageSelectDialog(QDialog):
    def __init__(self, card_name, image_path: Path, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Select Card Image")
        self.resize(820, 620)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        self.thumb_cache = {}
        self.request_id = 0

        self.card_name = card_name
        self.image_path = image_path

        # Performance optimization parameters
        self.page_size = 10
        self.current_page = 0
        self.all_results = []

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.thumb_size = QSize(120, 170)
        self.list.setIconSize(self.thumb_size)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setSpacing(10)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["10", "20", "50"])
        self.page_size_combo.setCurrentText("10")
        self.page_size_combo.currentIndexChanged.connect(self.change_page_size)

        # Language selection check
        self.chk_ja = QCheckBox("日本語")
        self.chk_en = QCheckBox("English")
        self.chk_other = QCheckBox("Others")
        self.chk_ja.setChecked(True)

        self.chk_ja.stateChanged.connect(self.update_search)
        self.chk_en.stateChanged.connect(self.update_search)
        self.chk_other.stateChanged.connect(self.update_search)

        # Page navigation
        self.prev_btn = QPushButton("◀ Prev")
        self.next_btn = QPushButton("Next ▶")
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn.clicked.connect(self.next_page)

        top = QHBoxLayout()
        top.addWidget(self.chk_ja)
        top.addWidget(self.chk_en)
        top.addWidget(self.chk_other)
        top.addSpacing(20)
        top.addWidget(QLabel("Items per page"))
        top.addWidget(self.page_size_combo)
        top.addStretch()

        nav = QHBoxLayout()
        nav.addStretch()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list)
        layout.addLayout(nav)

        self.list.itemClicked.connect(self.select_image)

        self.update_search()

    def update_search(self):
        self.current_page = 0
        use_other = self.chk_other.isChecked()

        if not use_other:
            langs = []
            if self.chk_ja.isChecked():
                langs.append("ja")
            if self.chk_en.isChecked():
                langs.append("en")
            if not langs:
                langs = ["ja", "en"]
        else:
            langs = ("ja", "en", "fr", "de", "it", "es", "pt", "ko", "ru", "zhs", "zht")

        raw_results = generator.search_card_images(
            self.card_name,
            languages=tuple(langs)
        )

        faces = []
        for entry in raw_results:
            lang = entry.get("lang")
            if use_other:
                if lang == "ja" and not self.chk_ja.isChecked(): continue
                if lang == "en" and not self.chk_en.isChecked(): continue
                if lang not in ("ja", "en") and not self.chk_other.isChecked(): continue

            for face in entry.get("faces", []):
                faces.append({
                    "card_id": entry["card_id"],
                    "oracle_id": entry["oracle_id"],
                    "lang": lang,
                    "face_index": face["face_index"],
                    "face_name": face["name"],
                    "side": face["side"],
                    "image_normal": face["image_normal"],
                    "image_small": face.get("image_small"),
                })

        self.all_results = faces
        self.update_page()

    def update_page(self):
        self.clear_list_safely()
        self.request_id += 1
        current_id = self.request_id

        start = self.current_page * self.page_size
        end = start + self.page_size

        for i, r in enumerate(self.all_results[start:end]):
            title = f'{r["face_name"]} [{r["side"]}] ({r["lang"]})'
            item = QListWidgetItem(title)
            item.setSizeHint(QSize(self.thumb_size.width() + 20, self.thumb_size.height() + 40))
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)

            thumb_url = r.get("image_small")
            if thumb_url:
                loader = ImageLoader(i, thumb_url, self.thumb_size, current_id)
                loader.signals.finished.connect(self.on_image_loaded)
                self.pool.start(loader)

        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled((self.current_page + 1) * self.page_size < len(self.all_results))

    def on_image_loaded(self, req_id, index, img):
        if req_id != self.request_id: return
        item = self.list.item(index)
        if item:
            item.setIcon(QIcon(QPixmap.fromImage(img)))

    def change_page_size(self):
        self.page_size = int(self.page_size_combo.currentText())
        self.current_page = 0
        self.update_page()

    def next_page(self):
        if (self.current_page + 1) * self.page_size < len(self.all_results):
            self.current_page += 1
            self.update_page()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_page()

    def select_image(self, item):
        face = item.data(Qt.UserRole)
        # Note: Logic for saving files is moved to a strategy or passed via callback?
        # In main.py, it expects parent to be MainWindow.
        # We should accept a callback instead for better reuse.
        self.selected_face = face
        self.accept()

    def clear_list_safely(self):
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        self.list.setUpdatesEnabled(True)
