# gui_language.py

LANG_JA = "ja"
LANG_EN = "en"

# ---------------------------
# UI strings
# ---------------------------
UI_TEXT = {
    "ja": {
        "language": "Language:",
        "all": "すべて",
        "type_filter": "タイプフィルタ",
        "camera_mode": "カメラモード",
        "reset": "プレイヤー / ライフ リセット",
        "generate_fm_txt": "デッキ(txt)から画像生成",
        "load_csv": "CSVを読み込む",
        "commander": "統率者",
        "commander_a": "統率者A表示",
        "commander_b": "統率者B表示",
        "companion": "相棒表示",
        "text_size": "カード テキストサイズ",
        "flip_back": "裏面",
        "flip_front": "表面",
        "player": "プレイヤー",
        "life": "ライフ",
        "set_commander_a": "統率者Aに設定",
        "set_commander_b": "統率者Bに設定",
        "set_companion": "相棒に設定",
        "select_image": "カード画像選択",
        "commander_counters": "統率者ダメージ / カウンター",
        "commander_damage": "統率者ダメージ",
        "commander_counters_placeholder":
            "・統率者ダメージ\n"
            "・毒カウンター\n"
            "・経験カウンター\n\n"
            "（後で実装予定）",
        "mulligan": "マリガン",
        "keep": "キープ",
        "start": "スタート",
        "select_csv": "デッキ CSV を選択",
        "mulligan_status": "現在のマリガン:",
        "free_mulligan": "フリーマリガン",
        "initial_hand": "初手",
        "bottom_required": "戻す枚数:",
        "need_select_bottom": "{n} 枚のカードを選択してください。",
        "kept": "キープしました。",
        "rating": "評価:",
        "average_hand_size": "平均ハンド枚数:",
        "runs": "実行回数:",
        "most_bottomed_cards": "よくボトムに戻されるカード:",
        "most_kept_cards": "よくキープされるカード:",
        "start_simulation": "シミュレーション開始",
        "recent_results": "評価別の最近の結果 (最大5件):",
        "rating_header_prefix": "評価",
        "reset_results": "結果をリセット",
        "reset_confirm_title": "リセットの確認",
        "reset_confirm_msg": "このデッキのすべてのシミュレーション結果を削除してもよろしいですか？",
        "btn_serum_powder": "血清の粉末を起動",
        "exiled_cards_label": "追放したカード：",
        "mulligan_simulator": "マリガンシミュレーターを起動",
        "csv_not_loaded": "先にCSVを読み込んでください",
    },
    "en": {
        "language": "Language:",
        "all": "All",
        "type_filter": "Type Filter",
        "camera_mode": "Camera Mode",
        "reset": "Player / Life Reset",
        "generate_fm_txt": "Generate from Deck (txt)",
        "load_csv": "Load CSV",
        "commander": "Commander",
        "commander_a": "Show Commander A",
        "commander_b": "Show Commander B",
        "companion": "Show Companion",
        "text_size": "Card Text Size",
        "flip_back": "Back",
        "flip_front": "Front",
        "player": "Player",
        "life": "Life",
        "set_commander_a": "Set as Commander A",
        "set_commander_b": "Set as Commander B",
        "set_companion": "Set as Companion",
        "select_image": "Select Card Image",
        "commander_counters": "Commander Damage / Counters",
        "commander_damage": "Commander Damage",
        "commander_counters_placeholder":
            "• Commander Damage\n"
            "• Poison Counters\n"
            "• Experience Counters\n\n"
            "(Coming soon)",
        "mulligan": "Mulligan",
        "keep": "Keep",
        "start": "Start",
        "select_csv": "Select Deck CSV",
        "mulligan_status": "Current Mulligan:",
        "free_mulligan": "Free Mulligan",
        "initial_hand": "Initial Hand",
        "bottom_required": "Cards to bottom:",
        "need_select_bottom": "Select {n} cards to bottom.",
        "kept": "Hand kept.",
        "rating": "Rating:",
        "average_hand_size": "Average Hand Size:",
        "runs": "Runs:",
        "most_bottomed_cards": "Most Bottomed Cards:",
        "most_kept_cards": "Most Kept Cards:",
        "start_simulation": "Start Simulation",
        "recent_results": "Recent Results by Rating (Max 5):",
        "rating_header_prefix": "Rating",
        "reset_results": "Reset Results",
        "reset_confirm_title": "Confirm Reset",
        "reset_confirm_msg": "Are you sure you want to delete all simulation results for this deck?",
        "btn_serum_powder": "Activate Serum Powder",
        "exiled_cards_label": "Exiled Cards:",
        "mulligan_simulator": "Launch Mulligan Simulator",
        "csv_not_loaded": "Please load a CSV first",
    }
}


# ---------------------------
# Card type display
# Internal values (English) → Display names
# ---------------------------
TYPE_LABELS = {
    "ja": {
        "Land": "土地",
        "Creature": "クリーチャー",
        "Enchantment": "エンチャント",
        "Artifact": "アーティファクト",
        "Instant": "インスタント",
        "Sorcery": "ソーサリー",
        "Kindred": "同族",
        "Planeswalker": "プレインズウォーカー",
        "Battle": "バトル",
    },
    "en": {
        "Land": "Land",
        "Creature": "Creature",
        "Enchantment": "Enchantment",
        "Artifact": "Artifact",
        "Instant": "Instant",
        "Sorcery": "Sorcery",
        "Kindred": "Kindred",
        "Planeswalker": "Planeswalker",
        "Battle": "Battle",
    }
}
