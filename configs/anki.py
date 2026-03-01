# SPDX-License-Identifier: BSD-4-Clause
# Copyright (c) 2026 Rasul Khiriev

import json
import sys
from pathlib import Path
from typing import Optional

from models.configs import AnkiConfig


def load_anki_config(config_path: Optional[Path]) -> AnkiConfig:
    cfg = AnkiConfig()

    if config_path is None:
        return cfg

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Config JSON must be an object")
    except Exception as e:
        print(f"Error: invalid config JSON '{config_path}': {e}", file=sys.stderr)
        sys.exit(1)

    def get_str(key: str, default: str) -> str:
        v = data.get(key, default)
        return str(v).strip() if v is not None else default

    cfg.anki_url = get_str("anki_url", cfg.anki_url)
    cfg.default_deck = get_str("default_deck", cfg.default_deck)
    cfg.model_basic = get_str("model_basic", cfg.model_basic)
    cfg.model_cloze = get_str("model_cloze", cfg.model_cloze)
    cfg.field_front = get_str("field_front", cfg.field_front)
    cfg.field_back = get_str("field_back", cfg.field_back)
    cfg.field_cloze_text = get_str("field_cloze_text", cfg.field_cloze_text)

    return cfg
