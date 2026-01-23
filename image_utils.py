import cv2
import numpy as np
import random


def extract_color_hist_hsv(img, bins=(8, 8, 8)):
    """
    HSV color histogram (normalized)
    img: RGB image
    return: 1D numpy array
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)

    hist = cv2.calcHist(
        [hsv],
        channels=[0, 1, 2],
        mask=None,
        histSize=bins,
        ranges=[0, 180, 0, 256, 0, 256]
    )

    cv2.normalize(hist, hist)
    return hist.flatten()

def color_similarity(hist1, hist2):
    """
    Histogram similarity (closer to 1.0 means more similar)
    """
    # Bhattacharyya distance → convert to similarity
    dist = cv2.compareHist(hist1, hist2, cv2.HISTCMP_BHATTACHARYYA)
    return 1.0 - dist

def cosine(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    return float(np.dot(a, b))


def compare_color_hist(h1, h2):
    # Bhattacharyya distance → convert to similarity
    d = cv2.compareHist(h1, h2, cv2.HISTCMP_BHATTACHARYYA)
    return 1.0 - d   # 1.0 means a perfect match

def search_clip_with_color(
    query_art_clip_feat,
    query_art_img,
    query_full_clip_feat,
    query_full_img,
    deck,
    topk=10,

    # ---- Weights ----
    w_art_clip=0.8,
    w_art_color=0.10,
    w_full_clip=0.00,
    w_full_color=0.10,
    # w_art_clip=0.4,
    # w_art_color=0.10,
    # w_full_clip=0.4,
    # w_full_color=0.10,
):
    import numpy as np
    from image_utils import extract_color_hist_hsv

    # =========================
    # Query features
    # =========================
    q_art_clip = query_art_clip_feat / np.linalg.norm(query_art_clip_feat)
    q_art_color = extract_color_hist_hsv(query_art_img)

    q_full_clip = query_full_clip_feat / np.linalg.norm(query_full_clip_feat)
    q_full_color = extract_color_hist_hsv(query_full_img)

    best_card = None
    best_side = None
    best_score = -1.0

    candidates = []

    # =========================
    # Search (combined ART + FULL evaluation)
    # =========================
    for card in deck:
        for side in ("front", "back"):
            face = card.get(side)
            if not face:
                continue

            art = face.get("art")
            full = face.get("full")
            if not art or not full:
                continue

            if not art.get("clip_feats") or not full.get("clip_feats"):
                continue

            # ---------- ART CLIP ----------
            art_clip_scores = [
                float(np.dot(q_art_clip, f / np.linalg.norm(f)))
                for f in art["clip_feats"]
            ]
            art_clip_scores = np.array(art_clip_scores)

            art_clip_max = float(art_clip_scores.max())
            art_clip_mean = float(art_clip_scores.mean())
            art_clip_median = float(np.median(art_clip_scores))

            art_color_score = (
                compare_color_hist(q_art_color, art["color_hist"])
                if art.get("color_hist") is not None else 0.0
            )

            # ---------- FULL CLIP ----------
            full_clip_scores = [
                float(np.dot(q_full_clip, f / np.linalg.norm(f)))
                for f in full["clip_feats"]
            ]
            full_clip_scores = np.array(full_clip_scores)

            full_clip_max = float(full_clip_scores.max())
            full_clip_mean = float(full_clip_scores.mean())
            full_clip_median = float(np.median(full_clip_scores))

            full_color_score = (
                compare_color_hist(q_full_color, full["color_hist"])
                if full.get("color_hist") is not None else 0.0
            )

            # =========================
            # FINAL SCORE (scoring function)
            # =========================
            final_score = (
                w_art_clip   * art_clip_max +
                w_art_color  * art_color_score +
                w_full_clip  * full_clip_max +
                w_full_color * full_color_score
            )

            # ---- Update best result ----
            if final_score > best_score:
                best_score = final_score
                best_card = card
                best_side = side

            candidates.append({
                "card": card,
                "side": side,

                # Based on the scoring function
                "final_score": final_score,

                # --- ART ---
                "art_clip_max": art_clip_max,
                "art_clip_mean": art_clip_mean,
                "art_clip_median": art_clip_median,
                "art_color_score": art_color_score,

                # --- FULL ---
                "full_clip_max": full_clip_max,
                "full_clip_mean": full_clip_mean,
                "full_clip_median": full_clip_median,
                "full_color_score": full_color_score,
            })

    # =========================
    # TOP-K (based on the scoring function)
    # =========================
    top_cards = sorted(
        candidates,
        key=lambda x: x["final_score"],
        reverse=True
    )[:topk]

    return {
        "best": {
            "card": best_card,
            "side": best_side,
            "score": best_score,
        },
        "topk": top_cards,
    }



def search_metric(query_feat, metric_features):
    best_name = None
    best_score = -1.0

    q = query_feat / np.linalg.norm(query_feat)

    for card in metric_features:
        f = card["metric_feature"]
        score = float(np.dot(q, f))

        if score > best_score:
            best_score = score
            best_name = card["name_en"]

    return best_name, best_score


def search_metric_topk(query_feat, metric_features, k=5):
    """
    query_feat: np.ndarray (D,)
    metric_features: list of {
        "name_en": str,
        "metric_feature": np.ndarray (D,)
    }
    k: number of results to return
    """

    q = query_feat / np.linalg.norm(query_feat)

    results = []

    for card in metric_features:
        f = card["metric_feature"]
        score = float(np.dot(q, f))  # cosine similarity

        results.append({
            "name_en": card["name_en"],
            "score": score
        })

    # Sort by score in descending order
    results.sort(key=lambda x: x["score"], reverse=True)

    # Return Top-K results
    return results[:k]


def metric_score_for_card(metric_feat, card_name, metric_features):
    """
    Returns the metric cosine similarity for the specified card name.
    """
    for c in metric_features:
        if c["name_en"] == card_name:
            f = c["metric_feature"]
            f = f / np.linalg.norm(f)
            q = metric_feat / np.linalg.norm(metric_feat)
            return float(np.dot(q, f))

    return None



def crop_art_region(img):
    """
    Crop the illustration (art) region from an MTG card image.
    """
    if img is None or img.size == 0:
        return None

    h, w = img.shape[:2]

    # ---- Ratio-based crop (stable for MTG cards) ----
    y1 = int(h * 0.12)
    y2 = int(h * 0.56)

    x1 = int(w * 0.06)
    x2 = int(w * 0.94)

    if y2 <= y1 or x2 <= x1:
        return None

    return img[y1:y2, x1:x2]



def augment_image(
    img,
    rotate_deg=3,
    shift_ratio=0.01,
    scale_range=(0.9, 1.1),
    brightness_range=(-20, 40),     
    contrast_range=(0.40, 1.00)
):
    """
    Apply data augmentation to an image.
    """
    h, w = img.shape[:2]

    # --- Rotation  ---
    angle = random.uniform(-rotate_deg, rotate_deg)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)

    # --- Translation ---
    tx = random.uniform(-shift_ratio, shift_ratio) * w
    ty = random.uniform(-shift_ratio, shift_ratio) * h
    M[:, 2] += (tx, ty)

    # --- Scaling ---
    scale = random.uniform(*scale_range)
    M[:, :2] *= scale

    aug = cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101
    )

    # --- Brightness & Contrast ---
    alpha = random.uniform(*contrast_range)    # contrast
    beta  = random.uniform(*brightness_range)  # brightness (offset)

    aug = np.clip(aug * alpha + beta, 0, 255).astype(np.uint8)

    return aug
