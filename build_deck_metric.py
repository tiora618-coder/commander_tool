# build_deck_metric.py
import csv
import pickle
from pathlib import Path
import cv2
import numpy as np
import sys
from PyQt5.QtWidgets import QApplication, QFileDialog
from image_utils import crop_art_region, augment_image
from train_metric import train_metric
from log_window import LogWindow, StdoutRedirect, enable_dark_mode
from PyQt5.QtCore import QTimer

import hashlib

HASH_PATH_NAME = "deck_metric.hash"

AUG_N = 10

from PyQt5.QtCore import QThread, pyqtSignal

class CountdownCloser:
    def __init__(self, seconds: int, log_window: LogWindow, app: QApplication):
        self.remaining = seconds
        self.log_window = log_window
        self.app = app

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)

    def start(self):
        self.log_window.write(
            f"[INFO] window will close in {self.remaining} seconds"
        )
        self.timer.start(1000)

    def tick(self):
        self.remaining -= 1

        if self.remaining > 0:
            self.log_window.write(
                f"[INFO] closing in {self.remaining}..."
            )
        else:
            self.log_window.write("[INFO] closing window now")
            self.timer.stop()
            self.log_window.close()
            self.app.quit()


class MetricWorker(QThread):
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, csv_path: Path, epochs=30):
        super().__init__()
        self.csv_path = csv_path
        self.epochs = epochs

    def run(self):
        try:
            self.log.emit("[INFO] processing metric dataset...")

            changed = process_deck_metric(self.csv_path)

            if changed:
                self.log.emit("[INFO] training metric model...")
                train_metric(self.csv_path, epochs=self.epochs)
            else:
                self.log.emit("[SKIP] metric training skipped (no changes)")

            self.log.emit("[DONE] all tasks finished")

        except Exception as e:
            self.log.emit(f"[ERROR] {e}")

        self.finished.emit()


def imread_utf8(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

def compute_deck_fingerprint(image_hashes: list[str]) -> str:
    h = hashlib.sha256()
    for ih in sorted(image_hashes):
        h.update(ih.encode("utf-8"))
    return h.hexdigest()

def hash_image(img_rgb: np.ndarray) -> str:
    """
    Generate a stable hash from the image content.
    Assumes pre-augmentation RGB uint8 input.
    """
    # Normalize size (remove resolution-dependent differences)
    img = cv2.resize(img_rgb, (128, 128), interpolation=cv2.INTER_AREA)

    # Convert to byte sequence
    data = img.tobytes()

    # SHA256
    return hashlib.sha256(data).hexdigest()

def process_deck_metric(csv_path: Path, log_fn=print) -> bool:
    """
    Returns:
        True  -> Data has changed (retraining required)
        False -> Same as last time (no training needed)
    """
    deck_dir = csv_path.parent
    hash_path = deck_dir / HASH_PATH_NAME

    cards = []
    image_hashes = []

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        card_entry = {
            "name_en": row["name_en"],
            "images": []
        }

        for side_key in ("card_file_front", "card_file_back"):
            file = row.get(side_key)
            if not file:
                continue

            img_path = deck_dir / file
            if not img_path.exists():
                continue

            img = imread_utf8(img_path)
            if img is None:
                continue

            art = crop_art_region(img)
            if art is None or art.size == 0:
                continue

            art = cv2.cvtColor(art, cv2.COLOR_BGR2RGB)
            art = np.ascontiguousarray(art)

            # Compute hash (before augmentation)
            image_hashes.append(hash_image(art))

            card_entry["images"].append(art)
            for _ in range(AUG_N):
                card_entry["images"].append(augment_image(art))

        if card_entry["images"]:
            cards.append(card_entry)

    # Deck fingerprint
    deck_fingerprint = compute_deck_fingerprint(image_hashes)

    # Compare with previous run
    if hash_path.exists():
        prev = hash_path.read_text().strip()
        if prev == deck_fingerprint:
            log_fn("[INFO] metric dataset unchanged → skip training")
            return False

    # Save
    out_path = deck_dir / "deck_metric.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(cards, f)

    hash_path.write_text(deck_fingerprint)

    log_fn(f"[OK] metric dataset saved: {out_path}")
    return True


def build_metric_core(
    csv_path: Path,
    epochs=3,
    log_fn=print, 
):
    """
    GUI-independent core logic with injectable logging function
    """

    log_fn("[INFO] processing metric dataset...")

    changed = process_deck_metric(csv_path, log_fn=log_fn)

    if changed:
        log_fn("[INFO] training metric model...")
        train_metric(csv_path, epochs=epochs, log_fn=log_fn)
    else:
        log_fn("[SKIP] metric training skipped (no changes)")

    log_fn("[DONE] metric build finished")



