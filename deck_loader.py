# deck_loader.py
import csv
from pathlib import Path

def load_deck_from_csv(csv_path: Path):
    deck = []
    folder = csv_path.parent

    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if "card_file_front" not in reader.fieldnames:
            raise ValueError("CSV missing 'card_file_front'")

        for row in reader:
            img_name = row.get("card_file_front", "").strip()
            if not img_name:
                continue

            img_path = folder / img_name
            if not img_path.exists():
                continue

            # ★ Commander フラグを正しく読み込む
            card = {
                "id": img_name,
                "img": img_path,
                "Commander_A": row.get("Commander_A", "").strip(),
                "Commander_B": row.get("Commander_B", "").strip(),
                "Companion":   row.get("Companion", "").strip(),
            }

            deck.append(card)

    return deck
