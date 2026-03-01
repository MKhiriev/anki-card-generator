#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-4-Clause
# Copyright (c) 2026 Rasul Khiriev

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional

from anki.anki_connect import ensure_deck, add_note_basic, add_note_cloze
from anki.card_validator import validate_card
from anki.normalization import normalize_key
from configs.anki import load_anki_config
from configs.generator import load_generator_config
from configs.validator import validate_optional_config_file
from input.data_slicer import chunk_paragraphs
from input.file_validator import validate_input_file
from input.ymlmd_parser import parse_ymlmd
from llm.ollama import build_user_prompt, ollama_chat, repair_prompt
from llm.response import parse_json_array_strict
from llm.system_prompt import SYSTEM_PROMPT


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
    ap.add_argument("--temperature", type=float, default=None,
                    help="Override temperature (otherwise from generator config)")
    ap.add_argument("--max-chars", type=int, default=None,
                    help="Override max chars per chunk (otherwise from generator config)")
    ap.add_argument("--overlap", type=int, default=None,
                    help="Override paragraph overlap (otherwise from generator config)")

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
                last_raw = ollama_chat(gen_cfg.ollama_url, gen_cfg.model, SYSTEM_PROMPT, user_prompt,
                                       temperature=gen_cfg.temperature)
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
