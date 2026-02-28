#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# =========================
# LLM SYSTEM PROMPT
# =========================

SYSTEM_PROMPT = r'''Ты — движок дистилляции знаний для Anki.

Задача: по данному фрагменту текста сгенерировать высококачественные атомарные карточки Anki на русском языке.

ЖЁСТКИЙ ФОРМАТ ВЫВОДА:
- Верни ТОЛЬКО валидный JSON-массив (array). Без текста, без пояснений, без Markdown, без "```".
- Никаких комментариев до/после JSON.

ТИПЫ КАРТОЧЕК:
1) type="qa":
   - front: вопрос
   - back: ответ
2) type="cloze":
   - text: предложение/абзац с cloze в формате {{c1::...}}
   - Не используй c2/c3 — только c1.

ПРАВИЛА КАЧЕСТВА:
- 1 карточка = 1 факт/правило/определение/отличие. Никаких «два в одном».
- Вопрос должен быть однозначным и проверять ровно один тезис.
- Ответ короткий: 1–4 строки. Без воды.
- Не выдумывай факты. Используй только то, что явно есть в тексте.
- Не делай карточки из очевидных вводных фраз.
- Если термин/сокращение встречается впервые — кратко расшифруй в ответе.
- Cloze делай только если предложение самодостаточно без контекста.

ТРЕБОВАНИЯ К ПОЛЯМ:
- Для qa: обязательны type, front, back.
- Для cloze: обязательны type, text.
- tags: массив строк (может быть пустым).
- source: объект с полем chunk (номер чанка).

ОГРАНИЧЕНИЯ:
- Не более 12 карточек на один фрагмент текста.
- Не повторяй смысл карточек внутри одного ответа.

СХЕМА ЭЛЕМЕНТА МАССИВА:
{
  "type": "qa" | "cloze",
  "front": "...",
  "back": "...",
  "text": "...",
  "tags": ["..."],
  "source": {"chunk": 1}
}
'''


# =========================
# DATA MODELS
# =========================

@dataclass
class Article:
    title: str
    source_url: str
    deck: str
    tags: List[str]
    text: str
    slug: str


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


# =========================
# INPUT VALIDATION
# =========================

def validate_input_file(path_str: str) -> Path:
    input_path = Path(path_str).expanduser()

    if not input_path.exists():
        print(f"Error: file does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not input_path.is_file():
        print(f"Error: not a file: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.suffix.lower() not in (".ymlmd", ".md"):
        print(
            f"Error: invalid file extension '{input_path.suffix}'. Expected .ymlmd or .md",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with input_path.open("r", encoding="utf-8") as _:
            pass
    except Exception as e:
        print(f"Error: cannot read file '{input_path}': {e}", file=sys.stderr)
        sys.exit(1)

    return input_path.resolve()


def validate_optional_config_file(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str).expanduser()
    if not p.exists():
        print(f"Error: config file does not exist: {p}", file=sys.stderr)
        sys.exit(1)
    if not p.is_file():
        print(f"Error: config path is not a file: {p}", file=sys.stderr)
        sys.exit(1)
    try:
        with p.open("r", encoding="utf-8") as _:
            pass
    except Exception as e:
        print(f"Error: cannot read config file '{p}': {e}", file=sys.stderr)
        sys.exit(1)
    return p.resolve()


# =========================
# CONFIG LOADING
# =========================

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


def load_generator_config(config_path: Optional[Path]) -> GeneratorConfig:
    cfg = GeneratorConfig()

    if config_path is None:
        return cfg

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Config JSON must be an object")
    except Exception as e:
        print(f"Error: invalid generator config JSON '{config_path}': {e}", file=sys.stderr)
        sys.exit(1)

    def get_str(key: str, default: str) -> str:
        v = data.get(key, default)
        return str(v).strip() if v is not None else default

    def get_int(key: str, default: int) -> int:
        v = data.get(key, default)
        try:
            return int(v)
        except Exception:
            return default

    def get_float(key: str, default: float) -> float:
        v = data.get(key, default)
        try:
            return float(v)
        except Exception:
            return default

    cfg.model = get_str("model", cfg.model)
    cfg.ollama_url = get_str("ollama_url", cfg.ollama_url)
    cfg.temperature = get_float("temperature", cfg.temperature)
    cfg.max_chars = get_int("max_chars", cfg.max_chars)
    cfg.overlap = get_int("overlap", cfg.overlap)

    if cfg.max_chars < 200:
        cfg.max_chars = 200
    if cfg.overlap < 0:
        cfg.overlap = 0
    if cfg.temperature < 0:
        cfg.temperature = 0.0

    return cfg


# =========================
# CORE: PARSE / CHUNK
# =========================

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9а-яё\-]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "article"


def parse_ymlmd(path: str) -> Article:
    raw = Path(path).read_text(encoding="utf-8")

    m = re.match(r"(?s)^\s*---\s*\n(.*?)\n---\s*\n(.*)$", raw)
    if not m:
        raise ValueError("Input must be ymlmd: frontmatter between --- ... --- then body text.")

    fm = m.group(1)
    body = m.group(2).strip()

    meta: Dict[str, Any] = {}
    for line in fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()

        if k == "tags":
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                if not inner:
                    meta[k] = []
                else:
                    parts = [p.strip().strip('"').strip("'") for p in inner.split(",")]
                    meta[k] = [p for p in parts if p]
            else:
                meta[k] = [v.strip('"').strip("'")] if v else []
        else:
            meta[k] = v.strip('"').strip("'")

    title = str(meta.get("title", "")).strip()
    if not title:
        raise ValueError("Frontmatter must include: title")

    source_url = str(meta.get("source_url", "")).strip()
    deck = str(meta.get("deck", "")).strip()  # may be empty -> fill later from config

    tags = meta.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    slug = slugify(title)

    tags = list(tags) + [f"article:{slug}"]
    if source_url:
        try:
            domain = re.sub(r"^https?://", "", source_url).split("/")[0]
            if domain:
                tags.append(f"src:{domain}")
        except Exception:
            pass

    return Article(
        title=title,
        source_url=source_url,
        deck=deck,
        tags=tags,
        text=body,
        slug=slug,
    )


def chunk_paragraphs(text: str, max_chars: int = 2200, overlap_paras: int = 1) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []

    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        if cur:
            chunks.append("\n\n".join(cur).strip())
        cur = []
        cur_len = 0

    for p in paras:
        add_len = len(p) + (2 if cur else 0)
        if cur and (cur_len + add_len > max_chars):
            flush()
            if overlap_paras > 0 and chunks:
                prev_paras = chunks[-1].split("\n\n")
                overlap = prev_paras[-overlap_paras:]
                cur = overlap[:]
                cur_len = sum(len(x) for x in cur) + 2 * (len(cur) - 1)

        cur.append(p)
        cur_len += add_len

    flush()
    return chunks


# =========================
# CORE: OLLAMA + JSON
# =========================

def ollama_chat(ollama_url: str, model: str, system: str, user: str, temperature: float = 0.2) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": temperature},
        "stream": False,
    }
    r = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["message"]["content"]


def parse_json_array_strict(s: str) -> List[Dict[str, Any]]:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    obj = json.loads(s)
    if not isinstance(obj, list):
        raise ValueError("LLM output JSON must be an array.")
    out: List[Dict[str, Any]] = []
    for x in obj:
        if isinstance(x, dict):
            out.append(x)
    return out


def build_user_prompt(article: Article, chunk_text: str, chunk_index: int) -> str:
    meta = {
        "title": article.title,
        "source_url": article.source_url,
        "article_slug": article.slug,
        "chunk": chunk_index,
        "base_tags": article.tags,
    }
    return (
        "Метаданные (JSON):\n"
        + json.dumps(meta, ensure_ascii=False)
        + "\n\n"
        "Текст фрагмента:\n"
        + chunk_text
        + "\n\n"
        "Сгенерируй карточки согласно правилам. Верни ТОЛЬКО JSON-массив."
    )


def repair_prompt(bad_output: str) -> str:
    return (
        "Твой предыдущий ответ НЕ является валидным JSON-массивом.\n"
        "Исправь его и верни ТОЛЬКО валидный JSON-массив (array) без текста и без Markdown.\n\n"
        "Плохой вывод:\n"
        + bad_output
    )


# =========================
# CARD VALIDATION / DEDUPE
# =========================

def normalize_key(card: Dict[str, Any]) -> str:
    t = str(card.get("type", "")).strip().lower()
    base = str(card.get("text" if t == "cloze" else "front", ""))
    base = base.strip().lower()
    base = re.sub(r"\s+", " ", base)
    return f"{t}:{base}"


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


# =========================
# ANKI CONNECT (uses config)
# =========================

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


# =========================
# MAIN
# =========================

def main() -> None:
    ap = argparse.ArgumentParser(description="Convert article.ymlmd -> Anki via Ollama + AnkiConnect")

    ap.add_argument("input", help="Path to article in ymlmd format (.ymlmd or .md)")

    # Config files
    ap.add_argument(
        "--anki-config",
        default="anki_config.json",
        help="Path to Anki config JSON (default: ./anki_config.json). Use empty string to disable.",
    )
    ap.add_argument(
        "--gen-config",
        default="generator_config.json",
        help="Path to generator config JSON (default: ./generator_config.json). Use empty string to disable.",
    )

    # CLI overrides (optional)
    ap.add_argument("--anki", default="", help="Override AnkiConnect URL (otherwise from anki config)")
    ap.add_argument("--model", default="", help="Override Ollama model (otherwise from generator config)")
    ap.add_argument("--ollama", default="", help="Override Ollama base URL (otherwise from generator config)")
    ap.add_argument("--temperature", type=float, default=None, help="Override temperature (otherwise from generator config)")
    ap.add_argument("--max-chars", type=int, default=None, help="Override max chars per chunk (otherwise from generator config)")
    ap.add_argument("--overlap", type=int, default=None, help="Override paragraph overlap (otherwise from generator config)")

    # execution
    ap.add_argument("--dry-run", action="store_true", help="Do not send to Anki, just print JSON")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between chunk requests")
    args = ap.parse_args()

    input_path = validate_input_file(args.input)

    anki_cfg_path = None if args.anki_config == "" else validate_optional_config_file(args.anki_config)
    anki_cfg = load_anki_config(anki_cfg_path)

    gen_cfg_path = None if args.gen_config == "" else validate_optional_config_file(args.gen_config)
    gen_cfg = load_generator_config(gen_cfg_path)

    # Apply CLI overrides
    if args.anki.strip():
        anki_cfg.anki_url = args.anki.strip()

    if args.model.strip():
        gen_cfg.model = args.model.strip()

    if args.ollama.strip():
        gen_cfg.ollama_url = args.ollama.strip()

    if args.temperature is not None:
        gen_cfg.temperature = max(0.0, float(args.temperature))

    if args.max_chars is not None:
        gen_cfg.max_chars = max(200, int(args.max_chars))

    if args.overlap is not None:
        gen_cfg.overlap = max(0, int(args.overlap))

    # parse + chunk
    try:
        article = parse_ymlmd(str(input_path))
    except Exception as e:
        print(f"Error: failed to parse ymlmd '{input_path}': {e}", file=sys.stderr)
        sys.exit(2)

    # deck fallback from config if missing in article
    if not article.deck:
        article.deck = anki_cfg.default_deck

    chunks = chunk_paragraphs(article.text, max_chars=gen_cfg.max_chars, overlap_paras=gen_cfg.overlap)
    if not chunks:
        print("No text chunks produced.", file=sys.stderr)
        sys.exit(2)

    all_cards: List[Dict[str, Any]] = []
    seen = set()

    for idx, chunk in enumerate(chunks, start=1):
        user_prompt = build_user_prompt(article, chunk, idx)

        content: Optional[List[Dict[str, Any]]] = None
        last_err: Optional[Exception] = None
        last_raw: str = ""

        for _attempt in range(1, 4):
            try:
                last_raw = ollama_chat(gen_cfg.ollama_url, gen_cfg.model, SYSTEM_PROMPT, user_prompt, temperature=gen_cfg.temperature)
                content = parse_json_array_strict(last_raw)
                break
            except Exception as e:
                last_err = e
                try:
                    repaired = ollama_chat(
                        gen_cfg.ollama_url,
                        gen_cfg.model,
                        SYSTEM_PROMPT,
                        repair_prompt(last_raw),
                        temperature=0.0,
                    )
                    content = parse_json_array_strict(repaired)
                    break
                except Exception as e2:
                    last_err = e2

        if content is None:
            print(f"[chunk {idx}] failed after retries: {last_err}", file=sys.stderr)
            continue

        for c in content:
            if not isinstance(c, dict):
                continue

            # merge tags + enforce source.chunk
            c_tags = c.get("tags", [])
            if not isinstance(c_tags, list):
                c_tags = []
            merged_tags = list(dict.fromkeys(article.tags + [str(x) for x in c_tags if str(x).strip()]))
            c["tags"] = merged_tags

            src = c.get("source", {})
            if not isinstance(src, dict):
                src = {}
            src["chunk"] = idx
            c["source"] = src

            vc = validate_card(c)
            if not vc:
                continue

            k = normalize_key(vc)
            if k in seen:
                continue
            seen.add(k)
            all_cards.append(vc)

        if args.sleep > 0:
            time.sleep(args.sleep)

    if args.dry_run:
        print(json.dumps(all_cards, ensure_ascii=False, indent=2))
        return

    ensure_deck(anki_cfg.anki_url, article.deck)

    added = 0
    for c in all_cards:
        try:
            if c["type"] == "qa":
                add_note_basic(anki_cfg, article.deck, c["front"], c["back"], c.get("tags", []))
            else:
                add_note_cloze(anki_cfg, article.deck, c["text"], c.get("tags", []))
            added += 1
        except Exception as e:
            print(f"Failed to add note: {e}", file=sys.stderr)

    print(f"Done. Chunks={len(chunks)} Cards={len(all_cards)} Added={added} Deck='{article.deck}'")


if __name__ == "__main__":
    main()
