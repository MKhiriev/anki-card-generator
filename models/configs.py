# SPDX-License-Identifier: BSD-4-Clause
# Copyright (c) 2026 Rasul Khiriev

from dataclasses import dataclass


@dataclass
class AnkiConfig:
    anki_url: str = "http://127.0.0.1:8765"
    default_deck: str = "Inbox::Articles"
    model_basic: str = "Basic"
    model_cloze: str = "Cloze"
    field_front: str = "Front"
    field_back: str = "Back"
    field_cloze_text: str = "Text"


@dataclass
class GeneratorConfig:
    model: str = "qwen2.5:7b-instruct"
    ollama_url: str = "http://127.0.0.1:11434"
    temperature: float = 0.2
    max_chars: int = 2200
    overlap: int = 1
