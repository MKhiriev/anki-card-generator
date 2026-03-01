import re
from typing import Dict, Any


def normalize_key(card: Dict[str, Any]) -> str:
    t = str(card.get("type", "")).strip().lower()
    base = str(card.get("text" if t == "cloze" else "front", ""))
    base = base.strip().lower()
    base = re.sub(r"\s+", " ", base)
    return f"{t}:{base}"
