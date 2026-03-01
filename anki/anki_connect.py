from typing import List, Dict, Any

import requests

from models.configs import AnkiConfig


def anki_invoke(anki_url: str, action: str, params: Dict[str, Any]) -> Any:
    payload = {"action": action, "version": 6, "params": params}
    r = requests.post(anki_url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnkiConnect error for action={action}: {data['error']}")
    return data.get("result")


def ensure_deck(anki_url: str, deck: str) -> None:
    anki_invoke(anki_url, "createDeck", {"deck": deck})


def add_note_basic(cfg: AnkiConfig, deck: str, front: str, back: str, tags: List[str]) -> int:
    note = {
        "deckName": deck,
        "modelName": cfg.model_basic,
        "fields": {cfg.field_front: front, cfg.field_back: back},
        "tags": tags,
        "options": {"allowDuplicate": False},
    }
    return anki_invoke(cfg.anki_url, "addNote", {"note": note})


def add_note_cloze(cfg: AnkiConfig, deck: str, text: str, tags: List[str]) -> int:
    note = {
        "deckName": deck,
        "modelName": cfg.model_cloze,
        "fields": {cfg.field_cloze_text: text},
        "tags": tags,
        "options": {"allowDuplicate": False},
    }
    return anki_invoke(cfg.anki_url, "addNote", {"note": note})
