# logger.py
import json
from pathlib import Path
from datetime import datetime


# def append_mulligan_log(deck_name: str, entry: dict):
#     """
#     deck_name_mulligan.json に追記
#     """
#     log_path = Path(f"{deck_name}_mulligan.json")

#     data = []
#     if log_path.exists():
#         try:
#             data = json.loads(log_path.read_text(encoding="utf-8"))
#         except:
#             data = []

#     entry["timestamp"] = datetime.now().isoformat()
#     data.append(entry)

#     log_path.write_text(
#         json.dumps(data, ensure_ascii=False, indent=2),
#         encoding="utf-8"
#     )

def append_mulligan_log(deck_name: str, entry: dict, csv_path: Path):
    """
    Save log JSON next to the CSV file.
    """
    # CSV と同じフォルダに JSON 保存
    folder = csv_path.parent
    log_path = folder / f"{deck_name}_mulligan.json"

    data = []
    if log_path.exists():
        try:
            data = json.loads(log_path.read_text(encoding="utf-8"))
        except:
            data = []

    entry["timestamp"] = datetime.now().isoformat()
    data.append(entry)

    log_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

