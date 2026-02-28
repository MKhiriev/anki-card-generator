#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

import requests


SYSTEM_PROMPT = """Ты — движок дистилляции знаний для Anki.

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
"""


@dataclass
class Article:
    title: str
    source_url: str
    deck: str
    tags: List[str]
    text: str
    slug: str


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9а-яё\-]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "article"


def parse_ymlmd(path: str) -> Article:
    raw = open(path, "r", encoding="utf-8").read()

    # Expect:
    # ---
    # key: value
    # tags: [a, b]
    # ---
    # body...
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

        # Simple tags: [a, b, c]
        if k == "tags":
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                if not inner:
                    meta[k] = []
                else:
                    parts = [p.strip().strip('"').strip("'") for p in inner.split(",")]
                    meta[k] = [p for p in parts if p]
            else:
                # single tag
                meta[k] = [v.strip('"').strip("'")] if v else []
        else:
            meta[k] = v.strip('"').strip("'")

    title = str(meta.get("title", "")).strip()
    if not title:
        raise ValueError("Frontmatter must include: title")

    source_url = str(meta.get("source_url", "")).strip()
    deck = str(meta.get("deck", "Inbox::Articles")).strip()
    tags = meta.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    slug = slugify(title)
    # add stable tags
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
    # Normalize newlines
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

    for i, p in enumerate(paras):
        add_len = len(p) + (2 if cur else 0)
        if cur and (cur_len + add_len > max_chars):
            flush()
            # overlap: take last N paragraphs from previous chunk (if any)
            if overlap_paras > 0 and chunks:
                prev_paras = chunks[-1].split("\n\n")
                overlap = prev_paras[-overlap_paras:]
                cur = overlap[:]  # start new chunk with overlap
                cur_len = sum(len(x) for x in cur) + 2 * (len(cur) - 1)

        cur.append(p)
        cur_len += add_len

    flush()
    return chunks


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
    # Guard against code fences
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    obj = json.loads(s)
    if not isinstance(obj, list):
        raise ValueError("LLM output JSON must be an array.")
    # Ensure objects
    out: List[Dict[str, Any]] = []
    for x in obj:
        if isinstance(x, dict):
            out.append(x)
    return out


def normalize_key(card: Dict[str, Any]) -> str:
    t = str(card.get("type", "")).strip().lower()
    if t == "cloze":
        base = str(card.get("text", ""))
    else:
        base = str(card.get("front", ""))
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
        # basic length sanity
        if len(front) > 400 or len(back) > 1200:
            return None
        card["front"] = front
        card["back"] = back
        # remove cloze-only field if present
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


def add_note_basic(anki_url: str, deck: str, front: str, back: str, tags: List[str]) -> int:
    note = {
        "deckName": deck,
        "modelName": "Basic",
        "fields": {"Front": front, "Back": back},
        "tags": tags,
        "options": {"allowDuplicate": False},
    }
    return anki_invoke(anki_url, "addNote", {"note": note})


def add_note_cloze(anki_url: str, deck: str, text: str, tags: List[str]) -> int:
    note = {
        "deckName": deck,
        "modelName": "Cloze",
        "fields": {"Text": text},
        "tags": tags,
        "options": {"allowDuplicate": False},
    }
    return anki_invoke(anki_url, "addNote", {"note": note})


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


def main():
    ap = argparse.ArgumentParser(description="Convert article.ymlmd -> Anki via Ollama + AnkiConnect")
    ap.add_argument("input", help="Path to article in ymlmd format")
    ap.add_argument("--model", default="qwen2.5:7b-instruct", help="Ollama model name")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434", help="Ollama base URL")
    ap.add_argument("--anki", default="http://127.0.0.1:8765", help="AnkiConnect URL")
    ap.add_argument("--max-chars", type=int, default=2200, help="Max chars per chunk")
    ap.add_argument("--overlap", type=int, default=1, help="Paragraph overlap between chunks")
    ap.add_argument("--temperature", type=float, default=0.2, help="LLM temperature")
    ap.add_argument("--dry-run", action="store_true", help="Do not send to Anki, just print JSON")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between chunk requests")
    args = ap.parse_args()

    article = parse_ymlmd(args.input)
    chunks = chunk_paragraphs(article.text, max_chars=args.max_chars, overlap_paras=args.overlap)
    if not chunks:
        print("No text chunks produced.", file=sys.stderr)
        sys.exit(2)

    all_cards: List[Dict[str, Any]] = []
    seen = set()

    for idx, chunk in enumerate(chunks, start=1):
        user_prompt = build_user_prompt(article, chunk, idx)

        content = None
        last_err = None
        for attempt in range(1, 4):
            try:
                raw = ollama_chat(args.ollama, args.model, SYSTEM_PROMPT, user_prompt, temperature=args.temperature)
                cards = parse_json_array_strict(raw)
                content = cards
                break
            except Exception as e:
                last_err = e
                # repair attempt using the same model
                try:
                    raw2 = ollama_chat(args.ollama, args.model, SYSTEM_PROMPT, repair_prompt(raw), temperature=0.0)
                    cards2 = parse_json_array_strict(raw2)
                    content = cards2
                    break
                except Exception as e2:
                    last_err = e2
                    # continue retries
        if content is None:
            print(f"[chunk {idx}] failed after retries: {last_err}", file=sys.stderr)
            continue

        # attach/merge tags and validate
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

    # Send to Anki
    ensure_deck(args.anki, article.deck)

    added = 0
    for c in all_cards:
        t = c["type"]
        tags = c.get("tags", [])
        try:
            if t == "qa":
                add_note_basic(args.anki, article.deck, c["front"], c["back"], tags)
            else:
                add_note_cloze(args.anki, article.deck, c["text"], tags)
            added += 1
        except Exception as e:
            print(f"Failed to add note: {e}", file=sys.stderr)

    print(f"Done. Chunks={len(chunks)} Cards={len(all_cards)} Added={added} Deck='{article.deck}'")


if __name__ == "__main__":
    main()