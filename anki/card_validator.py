from typing import Dict, Any, Optional


def validate_card(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = str(card.get("type", "")).strip().lower()
    if t not in ("qa", "cloze"):
        return None

    tags = card.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(x) for x in tags if str(x).strip()]
    card["tags"] = tags

    source = card.get("source", {})
    if not isinstance(source, dict):
        source = {}
    card["source"] = source

    if t == "qa":
        front = str(card.get("front", "")).strip()
        back = str(card.get("back", "")).strip()
        if not front or not back:
            return None
        if len(front) > 400 or len(back) > 1200:
            return None
        card["front"] = front
        card["back"] = back
        card.pop("text", None)
        return card

    if t == "cloze":
        text = str(card.get("text", "")).strip()
        if not text:
            return None
        if "{{c1::" not in text or "}}" not in text:
            return None
        if len(text) > 1800:
            return None
        card["text"] = text
        card.pop("front", None)
        card.pop("back", None)
        return card

    return None
