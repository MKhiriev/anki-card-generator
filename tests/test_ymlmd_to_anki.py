import json
from pathlib import Path
from unittest.mock import patch

import pytest

import ymlmd_to_anki as sut


def write_tmp(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# -------------------------
# slugify
# -------------------------

def test_slugify_basic_ru():
    assert sut.slugify("Как устроена оперативная память") == "как-устроена-оперативная-память"


def test_slugify_strips_symbols():
    assert sut.slugify("  RAM: что это?  ") == "ram-что-это"


def test_slugify_empty_fallback():
    assert sut.slugify("   ") == "article"


# -------------------------
# parse_ymlmd
# -------------------------

def test_parse_ymlmd_ok(tmp_path: Path):
    content = """---
title: "Как устроена оперативная память"
source_url: "https://example.com/a"
deck: "Inbox::Articles"
tags: ["topic:hardware", "topic:ram"]
---
Первый абзац.

Второй абзац.
"""
    p = write_tmp(tmp_path, "article.yml.md", content)
    a = sut.parse_ymlmd(str(p))

    assert a.title == "Как устроена оперативная память"
    assert a.source_url == "https://example.com/a"
    assert a.deck == "Inbox::Articles"
    assert "topic:hardware" in a.tags
    assert "topic:ram" in a.tags
    assert any(t.startswith("article:") for t in a.tags)
    assert "src:example.com" in a.tags
    assert "Первый абзац." in a.text
    assert a.slug == "как-устроена-оперативная-память"


def test_parse_ymlmd_requires_frontmatter(tmp_path: Path):
    p = write_tmp(tmp_path, "bad.yml.md", "no frontmatter here")
    with pytest.raises(ValueError):
        sut.parse_ymlmd(str(p))


def test_parse_ymlmd_requires_title(tmp_path: Path):
    content = """---
source_url: "x"
deck: "d"
tags: ["a"]
---
Body
"""
    p = write_tmp(tmp_path, "no_title.yml.md", content)
    with pytest.raises(ValueError):
        sut.parse_ymlmd(str(p))


def test_parse_ymlmd_tags_single_value(tmp_path: Path):
    content = """---
title: "T"
tags: tag1
---
Body
"""
    p = write_tmp(tmp_path, "single_tag.yml.md", content)
    a = sut.parse_ymlmd(str(p))
    # expects it to become list with single tag (script supports it)
    assert "tag1" in a.tags


# -------------------------
# chunk_paragraphs
# -------------------------

def test_chunk_paragraphs_basic_and_overlap():
    text = "\n\n".join([
        "A" * 900,
        "B" * 900,
        "C" * 900,
    ])
    # max 1500 => should create multiple chunks with overlap 1 paragraph
    chunks = sut.chunk_paragraphs(text, max_chars=1500, overlap_paras=1)

    assert len(chunks) >= 2
    # overlap: second chunk starts with last paragraph of previous chunk
    first_paras = chunks[0].split("\n\n")
    second_paras = chunks[1].split("\n\n")
    assert second_paras[0] == first_paras[-1]


def test_chunk_paragraphs_empty():
    assert sut.chunk_paragraphs(" \n\n ", max_chars=1000, overlap_paras=1) == []


# -------------------------
# parse_json_array_strict
# -------------------------

def test_parse_json_array_strict_ok():
    s = '[{"type":"qa","front":"Q","back":"A"}]'
    arr = sut.parse_json_array_strict(s)
    assert isinstance(arr, list)
    assert arr[0]["type"] == "qa"


def test_parse_json_array_strict_rejects_non_array():
    with pytest.raises(ValueError):
        sut.parse_json_array_strict('{"a":1}')


def test_parse_json_array_strict_strips_codefence():
    s = "```json\n[{\"type\":\"qa\",\"front\":\"Q\",\"back\":\"A\"}]\n```"
    arr = sut.parse_json_array_strict(s)
    assert arr[0]["front"] == "Q"


# -------------------------
# validate_card
# -------------------------

def test_validate_card_qa_ok():
    c = {"type": "qa", "front": "Что такое ОЗУ?", "back": "Рабочая память.", "tags": ["t1"], "source": {"chunk": 1}}
    vc = sut.validate_card(c)
    assert vc is not None
    assert vc["type"] == "qa"
    assert "front" in vc and "back" in vc
    assert "text" not in vc


def test_validate_card_cloze_ok():
    c = {"type": "cloze", "text": "ОЗУ — это {{c1::оперативная память}}.", "tags": [], "source": {"chunk": 1}}
    vc = sut.validate_card(c)
    assert vc is not None
    assert vc["type"] == "cloze"
    assert "text" in vc
    assert "front" not in vc and "back" not in vc


def test_validate_card_rejects_missing_fields():
    assert sut.validate_card({"type": "qa", "front": "Q"}) is None
    assert sut.validate_card({"type": "cloze", "text": "без cloze"}) is None


def test_validate_card_rejects_too_long():
    c = {"type": "qa", "front": "Q" * 500, "back": "A"}
    assert sut.validate_card(c) is None


# -------------------------
# normalize_key
# -------------------------

def test_normalize_key_qa():
    k = sut.normalize_key({"type": "qa", "front": "  Hello   World  "})
    assert k == "qa:hello world"


def test_normalize_key_cloze():
    k = sut.normalize_key({"type": "cloze", "text": "  X  {{c1::Y}}  "})
    assert k == "cloze:x {{c1::y}}"


# -------------------------
# build_user_prompt
# -------------------------

def test_build_user_prompt_contains_meta_and_chunk():
    article = sut.Article(
        title="T",
        source_url="https://example.com",
        deck="D",
        tags=["tag1", "article:t"],
        text="body",
        slug="t",
    )
    prompt = sut.build_user_prompt(article, "chunk text", 3)
    assert "Метаданные (JSON):" in prompt
    assert '"chunk": 3' in prompt
    assert "chunk text" in prompt


# -------------------------
# HTTP wrappers: ollama_chat / anki_invoke
# -------------------------

class DummyResp:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_ollama_chat_happy_path():
    with patch("requests.post") as mpost:
        mpost.return_value = DummyResp({"message": {"content": '[{"type":"qa","front":"Q","back":"A"}]'}})
        out = sut.ollama_chat("http://127.0.0.1:11434", "model", "sys", "user", temperature=0.2)
        assert out.startswith("[")
        # verify endpoint used
        args, kwargs = mpost.call_args
        assert args[0].endswith("/api/chat")
        assert kwargs["json"]["model"] == "model"


def test_anki_invoke_ok():
    with patch("requests.post") as mpost:
        mpost.return_value = DummyResp({"result": 123, "error": None})
        res = sut.anki_invoke("http://127.0.0.1:8765", "version", {})
        assert res == 123


def test_anki_invoke_raises_on_error():
    with patch("requests.post") as mpost:
        mpost.return_value = DummyResp({"result": None, "error": "Boom"})
        with pytest.raises(RuntimeError):
            sut.anki_invoke("http://127.0.0.1:8765", "addNote", {})


def test_load_anki_config_defaults_when_none():
    cfg = sut.load_anki_config(None)
    assert cfg.anki_url.startswith("http://127.0.0.1")


def test_load_anki_config_from_file(tmp_path):
    p = tmp_path / "anki_config.json"
    p.write_text(json.dumps({"anki_url": "http://x:1", "model_basic": "MyBasic"}, ensure_ascii=False), encoding="utf-8")
    cfg = sut.load_anki_config(p)
    assert cfg.anki_url == "http://x:1"
    assert cfg.model_basic == "MyBasic"
    assert cfg.model_cloze == "Cloze"  # default preserved
