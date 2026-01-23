import csv
import pickle
from pathlib import Path
import cv2
import sys
import numpy as np
import hashlib

from PyQt5.QtWidgets import (
    QApplication, QFileDialog,
    QProgressDialog, QLabel, QWidget, QVBoxLayout
)
from PyQt5.QtCore import Qt, QPoint

from clip_model import extract_image_feature
from image_utils import (
    crop_art_region,
    augment_image,
    extract_color_hist_hsv   
)
import re

# =========================
# Settings
# =========================
AUG_N = 100
DEBUG = False


# =========================
# Utilities
# =========================

def safe_name(name: str) -> str:
    """
    Convert to a safe directory name compatible with both Windows and Linux
    """
    # Replace forbidden characters with "_"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)

    # Trailing spaces and dots are not allowed on Windows
    name = name.rstrip(" .")

    return name

def imread_utf8(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def save_debug_image(
    base_dir: Path,
    card_name: str,
    side: str,
    region: str,   # "full" or "art"
    img: np.ndarray,
    suffix: str
):
    safe_card_name = safe_name(card_name)

    out_dir = (
        base_dir
        / "debug_images"
        / safe_card_name
        / side
        / region
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{suffix}.jpg"
    cv2.imwrite(str(out_dir / filename), img)


def calc_image_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def extract_features_from_image(
    img_path: Path,
    status: QWidget | None = None,
    label: str = "",
    debug_base_dir: Path | None = None,
    card_name: str = "",
    side: str = "front",
    card_idx = None,
    total_cards = None
):
    img = imread_utf8(img_path)
    if img is None:
        return None

    img = np.ascontiguousarray(img)

    # =========================
    # --- FULL IMAGE ---
    # =========================
    # full_clip_feats = [extract_image_feature(img)]

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    full_clip_feats = [extract_image_feature(img_rgb)]
    full_color_hist = extract_color_hist_hsv(img_rgb)

    # --- FULL base debug ---
    if DEBUG and debug_base_dir:
        save_debug_image(
            debug_base_dir,
            card_name,
            side,
            "full",
            img,
            "base"
        )

    # augmentation（FULL）
    for i in range(AUG_N):
        if status:
            status.update_text(f"Card : {card_name} {card_idx}/{total_cards}\n {label} Full Augment {i + 1}/{AUG_N}")

        # aug_img = augment_image(img)
        aug_img = augment_image(img_rgb)
        aug_img = np.ascontiguousarray(aug_img)

        if DEBUG and debug_base_dir:
            save_debug_image(
                debug_base_dir,
                card_name,
                side,
                "full",
                cv2.cvtColor(aug_img, cv2.COLOR_RGB2BGR),
                f"aug_{i+1:03d}"
            )

        full_clip_feats.append(extract_image_feature(aug_img))

    # =========================
    # --- ART IMAGE ---
    # =========================
    art = crop_art_region(img)
    if art is None or art.size == 0:
        return None

    art = np.ascontiguousarray(art)

    # art_clip_feats = [extract_image_feature(art)]

    art_rgb = cv2.cvtColor(art, cv2.COLOR_BGR2RGB)
    art_clip_feats = [extract_image_feature(art_rgb)]
    art_color_hist = extract_color_hist_hsv(art_rgb)

    # --- ART base debug ---
    if DEBUG and debug_base_dir:
        save_debug_image(
            debug_base_dir,
            card_name,
            side,
            "art",
            art,
            "base"
        )

    # augmentation（ART）
    for i in range(AUG_N):
        if status:
            status.update_text(f"Card : {card_name} {card_idx}/{total_cards}\n {label} Art Augment {i + 1}/{AUG_N}")

        # aug_img = augment_image(img)
        aug_img = augment_image(img_rgb)
        art_aug = crop_art_region(aug_img)
        if art_aug is None or art_aug.size == 0:
            continue

        art_aug = np.ascontiguousarray(art_aug)

        if DEBUG and debug_base_dir:
            save_debug_image(
                debug_base_dir,
                card_name,
                side,
                "art",
                cv2.cvtColor(art_aug, cv2.COLOR_RGB2BGR),
                f"aug_{i+1:03d}"
            )

        art_clip_feats.append(extract_image_feature(art_aug))

    return {
        "art": {
            "clip_feats": art_clip_feats,
            "color_hist": art_color_hist,
        },
        "full": {
            "clip_feats": full_clip_feats,
            "color_hist": full_color_hist,
        }
    }



# -------------------------
# CSV selection dialog
# -------------------------
def select_csv():
    csv_path, _ = QFileDialog.getOpenFileName(
        None,
        "Select deck CSV",
        "",
        "CSV Files (*.csv)"
    )
    if not csv_path:
        return None
    return Path(csv_path)


# -------------------------
# Progress display window
# -------------------------
class ProgressWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Feature extraction")
        self.resize(400, 120)

        self.label = QLabel("Preparation...", self)
        self.label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)

    def update_text(self, text):
        self.label.setText(text)
        QApplication.processEvents()


# -------------------------
# Main processing
# -------------------------
def process_deck_from_csv(csv_path: Path):
    deck_dir = csv_path.parent

    cache_path = deck_dir / "deck_clip_cache.pkl"
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            cache = pickle.load(f)
    else:
        cache = {}

    cards = []

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total_cards = len(rows)

    progress = QProgressDialog(
        "Calc from Card images ...",
        "Cancel",
        0,
        total_cards
    )
    progress.setWindowTitle("Progress..")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.show()

    status = ProgressWindow()
    status.show()
    QApplication.processEvents()
    pg_geo = progress.frameGeometry()
    status.move(pg_geo.bottomLeft() + QPoint(0, 20))

    for card_idx, row in enumerate(rows, start=1):
        progress.setValue(card_idx - 1)

        if progress.wasCanceled():
            break

        card_data = {
            "name_en": row["name_en"],
            "front": None,
            "back": None
        }

        # ==========
        # Front side
        # ==========
        front_file = row.get("card_file_front")
        if front_file:
            front_path = deck_dir / front_file
            if front_path.exists():
                img_hash = calc_image_hash(front_path)
                cache_entry = cache.get(front_file)

                if cache_entry and cache_entry["hash"] == img_hash:
                    data = cache_entry["data"]
                else:
                    data = extract_features_from_image(
                        front_path,
                        status,
                        label="Front",
                        debug_base_dir=deck_dir,
                        card_name=row["name_en"],
                        side="front",
                        card_idx = card_idx,
                        total_cards = total_cards
                    )
                    if data:
                        cache[front_file] = {
                            "hash": img_hash,
                            "data": data
                        }

                if data:
                    card_data["front"] = {
                        "image": front_file,
                        "art": data["art"],
                        "full": data["full"],
                    }

        # ==========
        # Back side
        # ==========
        back_file = row.get("card_file_back")
        if back_file:
            back_path = deck_dir / back_file
            if back_path.exists():
                img_hash = calc_image_hash(back_path)
                cache_entry = cache.get(back_file)

                if cache_entry and cache_entry["hash"] == img_hash:
                    data = cache_entry["data"]
                else:
                    data = extract_features_from_image(
                        back_path,
                        status,
                        label="Back",
                        debug_base_dir=deck_dir,
                        card_name=row["name_en"],
                        side="back",
                        card_idx = card_idx,
                        total_cards = total_cards
                    )
                    if data:
                        cache[back_file] = {
                            "hash": img_hash,
                            "data": data
                        }

                if data:
                    card_data["back"] = {
                        "image": back_file,
                        "art": data["art"],
                        "full": data["full"],
                    }

        cards.append(card_data)

    progress.setValue(total_cards)
    status.update_text("Complete")

    out_path = deck_dir / "deck_clip.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(cards, f)

    with open(cache_path, "wb") as f:
        pickle.dump(cache, f)

    print(f"[OK] {csv_path.name}: {len(cards)} cards")


# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)

    csv_path = select_csv()
    if csv_path:
        process_deck_from_csv(csv_path)

    sys.exit(0)
