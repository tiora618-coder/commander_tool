# camera_window.py
import cv2
import numpy as np
from ultralytics import YOLO

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QComboBox, QMessageBox, QCheckBox, QSpinBox
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from pathlib import Path
import sys
import pickle
import numpy as np
from clip_model import extract_image_feature
from dataset_metric import extract_metric_feature
from image_utils import crop_art_region, search_clip_with_color, metric_score_for_card
import time
from collections import deque
from collections import Counter
from PyQt5.QtGui import QPainter, QFont, QColor
from build_deck_clip import process_deck_from_csv
from PyQt5.QtCore import pyqtSignal
import torch
from model_metric import ConvNeXtEmbed
from log_window import LogWindow, StdoutRedirect
import platform
import cv2







# ================= Setting =================

RESOLUTIONS = {
    "640 x 480 (4:3)": (640, 480),
    "800 x 600 (4:3)": (800, 600),
    "1280 x 720 (16:9)": (1280, 720),
    "1920 x 1080 (16:9)": (1920, 1080),
}

def load_deck_clip(pkl_path):
    with open(pkl_path, "rb") as f:
        return pickle.load(f)
    
def load_deck_metric(pkl_path):
    with open(pkl_path, "rb") as f:
        return pickle.load(f)
    
def resource_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent



WEIGHTS_DIR = resource_dir() / "weights"
YOLO_MODEL_PATH = WEIGHTS_DIR / "card_yolo.pt"

CONF_TH = 0.4          # Confidence threshold
CARD_RATIO_TH = 8.0    # Percentage threshold to consider the card "close"
CLIP_SCORE_TH = 0.5    # Minimum similarity score
METRIC_SCORE_TH = 0.2  # Metric score threshold

class MetricBuildWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, csv_path: Path, epochs=3):
        super().__init__()
        self.csv_path = csv_path
        self.epochs = epochs

    def run(self):
        try:
            from build_deck_metric import build_metric_core
            build_metric_core(
                self.csv_path,
                epochs=self.epochs
            )  
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


def cosine(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    return float(np.dot(a, b))


def search_clip(query_feat, deck):
    best, best_score = None, -1
    best_side = None

    q = query_feat / np.linalg.norm(query_feat)

    for card in deck:
        for side in ("front", "back"):
            face = card.get(side)
            if not face:
                continue

            for f in face["features"]:
                f = f / np.linalg.norm(f)
                score = float(np.dot(q, f))

                if score > best_score:
                    best = card
                    best_score = score
                    best_side = side

    return best, best_score, best_side

def search_clip_mean(query_feat, deck, region="art"):
    q = query_feat / np.linalg.norm(query_feat)

    best, best_score = None, -1

    for card in deck:
        for side in ("front", "back"):
            face = card.get(side)
            if not face:
                continue

            feats = face.get(region, {}).get("clip_feats")
            if not feats:
                continue

            feats = np.array(feats)
            feats = feats / np.linalg.norm(feats, axis=1, keepdims=True)

            mean_feat = feats.mean(axis=0)
            mean_feat /= np.linalg.norm(mean_feat)

            score = float(np.dot(q, mean_feat))

            if score > best_score:
                best, best_score = card, score

    return best, best_score


def search_clip_topk(query_feat, deck, k=3, region="art"):
    q = query_feat / np.linalg.norm(query_feat)

    best, best_score = None, -1

    for card in deck:
        for side in ("front", "back"):
            face = card.get(side)
            if not face:
                continue

            feats = face.get(region, {}).get("clip_feats")
            if not feats:
                continue

            scores = []
            for f in feats:
                f = f / np.linalg.norm(f)
                scores.append(float(np.dot(q, f)))

            scores.sort(reverse=True)
            score = sum(scores[:k]) / min(k, len(scores))

            if score > best_score:
                best, best_score = card, score

    return best, best_score


def search_resnet(query_feat, deck):
    best, best_score = None, -1
    for c in deck:
        score = cosine(query_feat, c["resnet"])
        if score > best_score:
            best, best_score = c, score
    return best, best_score


def crop_inner(frame, x1, y1, x2, y2, margin=0.05):
    w = x2 - x1
    h = y2 - y1
    dx = int(w * margin)
    dy = int(h * margin)
    return frame[
        y1 + dy : y2 - dy,
        x1 + dx : x2 - dx
    ]

def get_cv_backend():
    system = platform.system()
    if system == "Windows":
        return cv2.CAP_DSHOW
    elif system == "Darwin":  # macOS
        return cv2.CAP_AVFOUNDATION
    else:
        return 0  # Linux


def detect_cameras(max_devices=5):
    backend = get_cv_backend()
    cams = []

    for i in range(max_devices):
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():
            cams.append(i)
        cap.release()

    return cams


# ================= Camera Window =================

class CameraWindow(QWidget):
    cardDetected = pyqtSignal(str)

    def __init__(self, csv_path: Path, parent=None):
        super().__init__(parent)

        self.csv_path = csv_path
        self.deck_dir = csv_path.parent

        # ---------- Detection State ----------
        self.last_box_center = None
        self.last_score = 0.0
        self.last_detect_time = 0.0

        self.KEEP_TIME = 1.0      # How many seconds to keep the last detection
        self.show_line = False
        self.LINE_KEEP_TIME = 0.3  # Duration to keep only the guide line (seconds)
        self.last_line_time = 0.0

        self.fade_alpha = 0.0     #  Alpha value for the composited image
        self.vote_window = 10
        self.vote_buffer = deque(maxlen=self.vote_window)
        self.current_card = None    # Result of majority voting
        self.display_card = None    # Currently displayed card

        self.metric_loaded = False
        self.metric_loading = False

        self.advanced_enabled = False



        self.vote_spin = QSpinBox()
        self.vote_spin.setRange(3, 20)          # Minimum 3 votes, maximum 20 votes
        self.vote_spin.setValue(self.vote_window)
        self.vote_spin.setSingleStep(1)
        self.vote_spin.setToolTip("多数決に使うフレーム数")
        self.vote_spin.valueChanged.connect(self.on_vote_window_changed)


        process_deck_from_csv(self.csv_path)
        self.deck_features = load_deck_clip(
            self.deck_dir / "deck_clip.pkl"
        )

        self.setWindowTitle("Camera Window")
        self.resize(1000, 650)

        self.detected_pix = None   
        self.detected_name = None


        # ---------- YOLO ----------
        try:
            self.model = YOLO(YOLO_MODEL_PATH)
        except Exception as e:
            QMessageBox.critical(self, "YOLO Error", str(e))
            self.model = None

        # ---------- Camera ----------
        self.cap = None
        self.camera_index = 0

        # ---------- View ----------
        self.view = QLabel(alignment=Qt.AlignCenter)
        self.view.setStyleSheet("background:black;")

        self.debug_view = QLabel(alignment=Qt.AlignCenter)
        self.debug_view.setStyleSheet("background:#111;")
        self.debug_view.hide()

        view_layout = QHBoxLayout()
        view_layout.addWidget(self.view, 1)
        view_layout.addWidget(self.debug_view, 1)

        # ---------- UI ----------
        self.debug_check = QCheckBox("debug mode")
        self.advanced_check = QCheckBox("Advanced image detection")
        self.advanced_check.setToolTip(
            "Ranked CLIP then choose one card by Metric"
        )
        self.advanced_check.stateChanged.connect(self.on_advanced_check_changed)

        self.camera_box = QComboBox()
        self.camera_indices = detect_cameras()
        if not self.camera_indices:
            QMessageBox.critical(self, "Camera Error", "Camera not found.")
        for i in self.camera_indices:
            self.camera_box.addItem(f"Camera {i}", i)
        self.camera_index = self.camera_indices[0]

        self.camera_box.currentIndexChanged.connect(self.change_camera)

        self.resolution_box = QComboBox()
        self.resolution_box.addItems(RESOLUTIONS.keys())
        self.resolution_box.setCurrentText("1280 x 720 (16:9)")
        self.resolution_box.currentIndexChanged.connect(self.reopen_camera)

        self.debug_check.stateChanged.connect(self.toggle_debug)

        # ---------- Layout ----------
        top = QHBoxLayout()
        top.addWidget(self.debug_check)
        top.addSpacing(10)
        top.addWidget(self.advanced_check)
        top.addSpacing(20)
        top.addWidget(QLabel("Camera"))
        top.addWidget(self.camera_box)
        top.addSpacing(20)
        top.addWidget(QLabel("Resolution"))
        top.addWidget(self.resolution_box)
        top.addSpacing(20)
        top.addWidget(QLabel("Vote num."))
        top.addWidget(self.vote_spin)
        top.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(view_layout, 1)

        # ---------- Timer ----------
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        self.open_camera()

    def on_advanced_check_changed(self, state):
        if state == Qt.Checked:
            reply = QMessageBox.question(
                self,
                "Advanced Image Detection",
                "This feature requires metric model preparation on first use,\n"
                "which may take some time.\n\n"
                "Do you want to continue?",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Cancel
            )

            if reply == QMessageBox.Ok:
                self.advanced_enabled = True
            else:
                self.advanced_check.blockSignals(True)
                self.advanced_check.setChecked(False)
                self.advanced_check.blockSignals(False)
                self.advanced_enabled = False

        else:
            self.advanced_enabled = False

    def load_metric_if_needed(self):
        if self.metric_loaded or self.metric_loading:
            return

        self.metric_loading = True

        # ===== KILL logging BEFORE redirecting stdout =====
        import logging
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(logging.NullHandler())
        root.propagate = False

        # --- Log window ---
        self.log_window = LogWindow()
        self.log_window.show()

        # --- Redirect stdout / stderr to the GUI ---
        self._stdout = sys.stdout
        self._stderr = sys.stderr

        self.stdout_redirect = StdoutRedirect()
        self.stdout_redirect.text_emitted.connect(
            self.log_window.append_log,
            Qt.QueuedConnection
        )

        sys.stdout = self.stdout_redirect
        sys.stderr = self.stdout_redirect

        print("[INFO] building metric files")

        # --- Worker ---
        self.metric_worker = MetricBuildWorker(
            csv_path=self.csv_path,
            epochs=20
        )

        self.metric_worker.finished.connect(self.on_metric_ready)
        self.metric_worker.error.connect(
            lambda e: print(f"[ERROR] {e}")
        )

        self.metric_worker.start()



    def on_metric_ready(self):
        print("[INFO] loading metric model and features...")

 
        self.deck_metric = load_deck_metric(
            self.deck_dir / "deck_metric.pkl"
        )

        self.metric_model = ConvNeXtEmbed(embed_dim=256)
        self.metric_model.load_state_dict(
            torch.load(self.deck_dir / "metric_model.pth", map_location="cpu", weights_only=True)
        )
        self.metric_model.eval()

        self.metric_features = []
        with torch.no_grad():
            for card in self.deck_metric:
                feats = []
                for img in card["images"]:
                    f = extract_metric_feature(self.metric_model, img)
                    feats.append(f)

                mean_feat = np.mean(feats, axis=0)
                mean_feat /= np.linalg.norm(mean_feat)

                self.metric_features.append({
                    "name_en": card["name_en"],
                    "metric_feature": mean_feat
                })

        self.metric_loaded = True
        self.metric_loading = False

        print("[INFO] Metric model loaded")

        print("[INFO] This window can be closed.")

        # --- Restore stdout / stderr ---
        sys.stdout = self._stdout
        sys.stderr = self._stderr


    # ================= Camera Control =================
    def on_vote_window_changed(self, value):
        self.vote_window = value

        # Reset recent detection history
        self.vote_buffer.clear()
        self.vote_buffer = deque(maxlen=self.vote_window)

    def toggle_debug(self, state):
        self.debug_view.setVisible(state == Qt.Checked)

    def open_camera(self):
        if self.cap:
            self.cap.release()

        backend = get_cv_backend()
        self.cap = cv2.VideoCapture(self.camera_index, backend)
        w, h = RESOLUTIONS[self.resolution_box.currentText()]
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

        self.timer.start(30)

    def reopen_camera(self):
        self.open_camera()

    def change_camera(self):
        self.camera_index = self.camera_box.currentData()
        self.open_camera()

    # ================= YOLO Detection =================

    def detect_card(self, frame):
        """
        Detect cards using YOLO.
        Returns:
            boxes: [(x1, y1, x2, y2, conf)]
        """
        if self.model is None:
            return []

        results = self.model.predict(
            frame,
            conf=CONF_TH,
            verbose=False,
            device="cpu"
        )

        boxes = []
        for r in results:
            if r.boxes is None:
                continue
            for b in r.boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                conf = float(b.conf[0])
                boxes.append((x1, y1, x2, y2, conf))

        return boxes

    
    def overlay_detected_image(self, frame):
        if self.detected_pix is None or self.fade_alpha <= 0.01:
            return frame

        h, w = frame.shape[:2]
        overlay = frame.copy()

        # ---- Display area ----
        area_x1 = int(w * 0.75)
        area_w = w - area_x1
        area_h = h

        img = self.detected_pix.copy()
        ih, iw = img.shape[:2]

        scale = min(area_w / iw, area_h / ih) * 0.9
        nw, nh = int(iw * scale), int(ih * scale)
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)

        x = area_x1 + (area_w - nw) // 2
        y = (area_h - nh) // 2

        # ---- Draw image onto overlay ----
        roi = overlay[y:y+nh, x:x+nw]
        if roi.shape[:2] == img.shape[:2]:
            overlay[y:y+nh, x:x+nw] = img

        # ---- Draw guide line onto overlay----
        if self.show_line and self.last_box_center is not None:
            cv2.line(
                overlay,
                self.last_box_center,
                (x, y + nh // 2),
                (0, 0, 255),
                2
            )

        # ---- Fade blending ----
        cv2.addWeighted(
            overlay, self.fade_alpha,
            frame, 1 - self.fade_alpha,
            0,
            frame
        )

        return frame





    def draw_text_qt(self, frame, text, x, y):
        # OpenCV → RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w

        # NumPy → QImage
        qimg = QImage(
            rgb.data,
            w,
            h,
            bytes_per_line,
            QImage.Format_RGB888
        )

        painter = QPainter(qimg)
        painter.setFont(QFont("Meiryo", 16))
        painter.setPen(QColor(255, 0, 0))
        painter.drawText(x, y, text)
        painter.end()

        ptr = qimg.bits()
        ptr.setsize(h * bytes_per_line)
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w, ch))

        # Convert RGB back to BGR
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)



    # ================= Frame Update =================

    def update_frame(self):
        if self.metric_loading:
            return

        if not self.cap:
            return
        
        if self.advanced_enabled:
            self.load_metric_if_needed()


        now = time.time()
        ret, frame = self.cap.read()
        found_target = False
        if not ret:
            return

        h, w = frame.shape[:2]

        boxes = self.detect_card(frame)

        valid_boxes = []
        best_clip_score = 0
        best_color_score = 0

        # ---------- Draw ----------
        for (x1, y1, x2, y2, conf) in boxes:
            area = (x2 - x1) * (y2 - y1)
            ratio = area / (w * h) * 100

            # ---- Check ratio ----
            if ratio >= CARD_RATIO_TH:
                valid_boxes.append((x1, y1, x2, y2, conf, area))

            if self.debug_check.isChecked():
                color = (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

                cv2.putText(
                    frame,
                    f"{conf:.2f}  {ratio:.1f}%",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    color,
                    2
                )
        if not valid_boxes:
            found_target = False
        else:
            found_target = True
            x1, y1, x2, y2, conf, area = max(
                valid_boxes,
                key=lambda b: b[5]  # area
            )

        if found_target:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)

            cv2.putText(
                frame,
                f"{conf:.2f}  {ratio:.1f}%",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2
            )


            card_img = crop_inner(frame, x1, y1, x2, y2)
            if card_img.size == 0:
                # continue
                return

            card_img = cv2.cvtColor(card_img, cv2.COLOR_BGR2RGB)


            card_img = cv2.rotate(card_img, cv2.ROTATE_180)
            art_img = crop_art_region(card_img)
            if art_img is None or art_img.size == 0:
                # continue
                return
            art_img = np.ascontiguousarray(art_img)

            h2, w2 = art_img.shape[:2]

            art_qimg = QImage(
                art_img.tobytes(),
                w2,
                h2,
                art_img.strides[0],
                QImage.Format_RGB888
            )

            self.debug_view.setPixmap(
                QPixmap.fromImage(art_qimg).scaled(
                    self.debug_view.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            )

            if art_img.ndim != 3 or art_img.shape[2] != 3:
                # continue
                return
            art_clip = extract_image_feature(art_img)

            full_img = card_img            
            full_clip = extract_image_feature(full_img)

            res = search_clip_with_color(
                query_art_clip_feat=art_clip,
                query_art_img=art_img,
                query_full_clip_feat=full_clip,
                query_full_img=full_img,
                deck=self.deck_features,
            )


            clip_card = res["best"]["card"]
            clip_side = res["best"]["side"]
            clip_score = res["best"]["score"]
            top_cards = res["topk"]

            final_card = clip_card
            final_score = clip_score
            best_clip_score = final_score

            # ---------------------------
            # Advanced image detection
            # ---------------------------
            if self.advanced_enabled:

                if not self.metric_loaded:
                    return
                
                self.load_metric_if_needed()

                metric_feat = extract_metric_feature(self.metric_model, art_img)

                # Re-evaluate only the CLIP Top-K card names using the Metric model
                best_metric_score = -1
                best_metric_name = None

                for c in top_cards:
                    name = c["card"]["name_en"]
                    score = metric_score_for_card(
                        metric_feat,
                        name,
                        self.metric_features
                    )

                    if score > best_metric_score:
                        best_metric_score = score
                        best_metric_name = name

                if best_metric_name is not None:
                    final_card = {"name_en": best_metric_name}
                    final_score = best_metric_score



            # ---------------------------
            # Vote decision
            # ---------------------------
            if self.advanced_enabled:
                # Advanced ON → decide using Metric score
                if final_card is not None and final_score >= METRIC_SCORE_TH:
                    self.vote_buffer.append(final_card["name_en"])

            else:
                # Advanced OFF → decide using CLIP score
                if final_card is not None and final_score >= CLIP_SCORE_TH:
                    self.vote_buffer.append(final_card["name_en"])



            voted_name = self.majority_vote()

            # ---- Final decision ----
            self.current_card = voted_name

            if self.current_card is not None:
                # Extend lifetime if the same card continues to be detected
                self.last_detect_time = now
                self.fade_alpha = 1.0

                if self.current_card != self.display_card:
                    self.display_card = self.current_card
                    self.detected_name = self.current_card
                    self.cardDetected.emit(self.current_card)

                    # ---- Update displayed image ----
                    voted_card = next(
                        (c for c in self.deck_features if c["name_en"] == self.current_card),
                        None
                    )
                    if voted_card:
                        face = voted_card.get("front")
                        if face:
                            img_path = self.deck_dir / face["image"]
                            img = cv2.imread(str(img_path))
                            if img is not None:
                                self.detected_pix = img

                # ---- Update guide line (always refresh while detection continues) ----
                self.last_box_center = (
                    (x1 + x2) // 2,
                    (y1 + y2) // 2
                )
                self.show_line = True
                self.last_line_time = now


            # ---- Manage display lifetime (based on display_card) ----
            if self.display_card is not None:
                if now - self.last_detect_time > self.KEEP_TIME:
                    self.display_card = None
                    self.detected_pix = None
                    self.fade_alpha = 0.0


            # ---- Hide the guide line earlier ----
            if self.show_line and (now - self.last_line_time > self.LINE_KEEP_TIME):
                self.show_line = False


            # ---- Draw text ----
            topk_text = "\n".join(
            (
                f"{i+1}. {c['card']['name_en']} "
                f"[ART] "
                f"max:{c['art_clip_max']:.2f} "
                f"mean:{c['art_clip_mean']:.2f} "
                f"med:{c['art_clip_median']:.2f} "
                f"Col:{c['art_color_score']:.2f} "
                f"[FULL] "
                f"max:{c['full_clip_max']:.2f} "
                f"mean:{c['full_clip_mean']:.2f} "
                f"med:{c['full_clip_median']:.2f} "
                f"Col:{c['full_color_score']:.2f} "
                + (
                    f"METRIC:{metric_score_for_card(metric_feat, c['card']['name_en'], self.metric_features):.2f}"
                    if self.advanced_enabled
                    else ""
                )
            )
            for i, c in enumerate(top_cards)
        )


            if final_card is not None:
                text = (
                    f"{final_card['name_en']} "
                    f"CLIP:{best_clip_score:.2f} "
                    f"--- TOP-{len(top_cards)} ---\n"
                    f"{topk_text}"
                )


                frame = self.draw_text_qt(frame, text, x1, y2 + 30)
                print(text)


        # Reset only if no nearby card was found in this frame
        if not found_target:
            self.vote_buffer.clear()


        # ---------- Main View ----------
        frame = self.overlay_detected_image(frame)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QImage(
            rgb.data, rgb.shape[1], rgb.shape[0],
            rgb.strides[0], QImage.Format_RGB888
        )
        self.view.setPixmap(
            QPixmap.fromImage(img).scaled(
                self.view.size(),
                Qt.KeepAspectRatio,
                Qt.FastTransformation
            )
        )
        # ---------- Debug View ----------

        if self.debug_check.isChecked():
            self.debug_view.show()
        else:
            self.debug_view.hide()

        if self.fade_alpha > 0:
            self.fade_alpha = max(0.0, self.fade_alpha - 0.02)

        if self.current_card is not None:
            print("votes:", list(self.vote_buffer))
            print("current:", self.current_card)


    def majority_vote(self):
        IGNORE_LAST = 2

        if len(self.vote_buffer) <= IGNORE_LAST:
            return None

        valid_votes = list(self.vote_buffer)[:-IGNORE_LAST]

        counter = Counter(valid_votes)
        name, count = counter.most_common(1)[0]

        if count < 2:
            return None

        return name




    # ================= Cleanup =================

    def closeEvent(self, event):
        if self.cap:
            self.cap.release()
        event.accept()
